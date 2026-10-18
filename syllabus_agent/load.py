"""From recorded events + the term to the semester: resolve, dedupe, weigh, find crunch weeks.

Pure Python, so editing the term re-runs all of it instantly with no model calls, and a replayed
recording goes through exactly the same code.
"""

import re
from difflib import SequenceMatcher

from . import config
from .term import Unresolved, describe, meeting_days, resolve, week_monday, week_of

NAMES = {"exam": ("exam", "exams"), "quiz": ("quiz", "quizzes"), "problem_set": ("pset", "psets"),
         "paper": ("paper", "papers"), "project": ("project", "projects"), "reading": ("reading", "readings"),
         "presentation": ("presentation", "presentations"), "other": ("other", "other")}
CRUNCH_WEEKS = 3


def collect(events):
    """Group a run's events by worker."""
    workers = {}
    for e in events:
        w = e.get("worker")
        if e["type"] == "worker":
            workers[w] = {"id": w, "file": e["file"], "course": None, "meeting_days": [], "grading": [],
                          "results": {}, "dropped": set(), "specs": {}, "errors": [], "waits": 0, "done": False}
        elif w not in workers:
            continue
        elif e["type"] == "extracted":
            workers[w].update(course=e["course"], meeting_days=e["meeting_days"], grading=e["grading"])
        elif e["type"] == "check":
            for r in e["results"]:  # a retry's result replaces the first attempt's
                workers[w]["results"][r["id"]] = {**r, "retried": e["retry"]}
        elif e["type"] == "dropped":
            workers[w]["dropped"].update(e["ids"])
        elif e["type"] == "parsed":
            workers[w]["specs"].update({d["id"]: d for d in e["dates"]})
        elif e["type"] == "error":
            workers[w]["errors"].append(e["message"])
        elif e["type"] == "waiting":
            workers[w]["waits"] += 1
        elif e["type"] == "done":
            workers[w]["done"] = True
    return workers


def build(events, term):
    workers = collect(events)
    calendar, review, rejected = [], [], []
    for w in workers.values():
        days = meeting_days(term, w["course"] or "", w["meeting_days"])
        for r in w["results"].values():
            item = {**r, "course": w["course"], "file": w["file"], "worker": w["id"]}
            if not r["ok"] or r["id"] in w["dropped"]:
                rejected.append({**item, "status": "rejected"})
                continue
            spec = w["specs"].get(r["id"])
            if spec is None:
                review.append({**item, "status": "needs_review", "reason": "date was not parsed"})
                continue
            item["parsed_as"] = describe(spec)
            try:
                start, end = resolve(spec, term, days)
            except Unresolved as why:
                review.append({**item, "status": "needs_review", "reason": str(why)})
                continue
            calendar.append({**item, "status": "verified", "date": start, "end_date": end,
                             "week": week_of(term, start)})
    calendar.sort(key=lambda i: (i["date"], i["course"] or ""))
    calendar, duplicates = dedupe(calendar)
    infer_weights(calendar, review, workers)
    weeks = weekly(calendar, term)
    return {"workers": workers, "calendar": calendar, "review": review, "rejected": rejected,
            "duplicates": duplicates, "weeks": weeks, "crunch": [w for w in weeks if w["crunch"]]}


# Deduplication

def number(title):
    found = re.search(r"\d+", title or "")
    return found[0] if found else None


def same_title(a, b):
    a, b = (re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip() for t in (a, b))
    if number(a) != number(b):
        return False
    return a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.8


def dedupe(items):
    """Same course, type and date with a similar title: keep one, preferring an explicit weight."""
    kept, duplicates = [], []
    for item in items:
        twin = next((k for k in kept if k["course"] == item["course"] and k["type"] == item["type"]
                     and k["date"] == item["date"] and same_title(k["title"], item["title"])), None)
        if twin is None:
            kept.append(item)
            continue
        if twin.get("weight_pct") is None and item.get("weight_pct") is not None:
            kept[kept.index(twin)], twin, item = item, item, twin
        duplicates.append({**item, "status": "duplicate", "reason": f"same as {twin['id']} \"{twin['title']}\""})
    return kept, duplicates


# Weights

def category(item, grading):
    """The grading-breakdown line an item belongs to, if there is one clear match."""
    lines = [g for g in grading if g["type"] == item["type"] and g.get("weight_pct") is not None]
    if len(lines) == 1:
        return lines[0]
    scored = [(SequenceMatcher(None, g["label"].lower(), item["title"].lower()).ratio(), g) for g in lines]
    best = max(scored, key=lambda pair: pair[0], default=(0, None))
    return best[1] if best[0] >= 0.6 else None


def as_percent(grading):
    """Some answers give a breakdown as fractions (0.67 for 67%); scale those to percents."""
    weights = [g["weight_pct"] for g in grading if g.get("weight_pct") is not None]
    if weights and sum(weights) <= 1.01:
        return [{**g, "weight_pct": None if g.get("weight_pct") is None else round(g["weight_pct"] * 100, 2)}
                for g in grading]
    return grading


def infer_weights(calendar, review, workers):
    grading = {w["course"]: as_percent(w["grading"]) for w in workers.values()}
    everything = calendar + review
    for item in calendar:
        if item.get("weight_pct") is not None:
            item.update(weight=item["weight_pct"], weight_inferred=False,
                        weight_note=item.get("weight_expr") or f"{item['weight_pct']:g}% stated")
            continue
        line = category(item, grading.get(item["course"], []))
        if line:
            count = line.get("count") or sum(1 for i in everything
                                             if i["course"] == item["course"] and i["type"] == item["type"])
            dropped = line.get("dropped") or 0
            counted = max(count - dropped, 1)
            note = f"{line['label']} {line['weight_pct']:g}% ÷ {counted} counted"
            if counted == 1:
                note = f"{line['label']}: {line['weight_pct']:g}% in the grading breakdown"
            elif dropped:
                note += f" ({count} total, {dropped} dropped)"
            item.update(weight=round(line["weight_pct"] / counted, 2), weight_inferred=True, weight_note=note)
        else:
            item.update(weight=config.DEFAULT_WEIGHTS[item["type"]], weight_inferred=True,
                        weight_note=f"default for {item['type'].replace('_', ' ')}")


# Weekly load

def summary(items, total):
    counts = {}
    for item in items:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    order = sorted(counts, key=lambda t: (t != "exam", -counts[t]))
    parts = [f"{counts[t]} {NAMES[t][counts[t] > 1]}" for t in order]
    return " + ".join(parts) + f" = {total:g}%"


def weekly(calendar, term):
    last = week_of(term, term["end"])
    weeks = []
    for n in range(1, last + 1):
        items = [i for i in calendar if i["week"] == n]
        total = round(sum(i["weight"] for i in items), 1)
        exams = sum(i["type"] == "exam" for i in items)
        weeks.append({"week": n, "monday": week_monday(term, n), "total": total, "exams": exams,
                      "items": items, "summary": summary(items, total) if items else "", "crunch": False,
                      "why": ""})
    ranked = sorted((w for w in weeks if w["total"] > 0), key=lambda w: -w["total"])[:CRUNCH_WEEKS]
    for rank, w in enumerate(ranked, 1):
        w["crunch"], w["why"] = True, f"#{rank} heaviest"
    for w in weeks:
        if w["exams"] >= 2:
            w["why"] = ", ".join(filter(None, [w["why"], f"{w['exams']} exams"]))
            w["crunch"] = True
    return weeks
