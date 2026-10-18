"""Score a run against a reference: the hand-made answer key for the demo syllabi, or else the
verified pipeline's own output. Measurement only; nothing here changes what goes on the calendar."""

import json
import re
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from .term import course_key

ROOT = Path(__file__).resolve().parents[1]
# The synthetic demo syllabi's key, and a hand-checked key for the five real syllabi in the demo recording.
KEY_FILES = [ROOT / "tests" / "fixtures" / "syllabi" / "answer_key.json", ROOT / "evals" / "real-answer-key.json"]
WORDS = [(r"\bproblem sets?\b", "ps"), (r"\bpset\b", "ps"), (r"\bhomework\b", "hw"),
         (r"\bmidterm exam\b", "midterm"), (r"\bfinal exam(ination)?\b", "final"), (r"\bexam\b", ""),
         (r"\biii\b", "3"), (r"\bii\b", "2"), (r"\bi\b", "1")]  # "Midterm Exam II" is "Midterm 2"


def answer_key(files):
    """The answer-key items if every uploaded file has a hand-checked key, else None."""
    if not files:
        return None
    key = {entry["sha256"]: entry for path in KEY_FILES if path.exists()
           for entry in json.loads(path.read_text()).values() if isinstance(entry, dict)}
    if not all(f["sha256"] in key for f in files):
        return None
    return [{"course": key[f["sha256"]]["course"], **item,
             "date": date.fromisoformat(item["date"]) if item["date"] else None,
             "end_date": date.fromisoformat(item["end_date"]) if item["end_date"] else None}
            for f in files for item in key[f["sha256"]]["items"]]


def from_pipeline(result):
    return ([{**i, "end_date": i.get("end_date")} for i in result["calendar"]]
            + [{**i, "date": None, "end_date": None} for i in result["review"]])


def plain(title):
    text = (title or "").lower()
    for pattern, replacement in WORDS:
        text = re.sub(pattern, replacement, text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def similar(a, b):
    a, b = plain(a), plain(b)
    numbers_a, numbers_b = re.findall(r"\d+", a), re.findall(r"\d+", b)
    if numbers_a and numbers_b and numbers_a[0] != numbers_b[0]:
        return 0.0
    if a and b and (a in b or b in a):
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def match(items, reference):
    """Pair each item with at most one reference item: same course, most similar title."""
    pairs = sorted(((similar(i["title"], r["title"]) + (0.05 if i.get("type") == r["type"] else 0), n, m)
                    for n, i in enumerate(items) for m, r in enumerate(reference)
                    if course_key(i["course"]) == course_key(r["course"])), reverse=True)
    used_items, used_refs, found = set(), set(), {}
    for score, n, m in pairs:
        if score < 0.5 or n in used_items or m in used_refs:
            continue
        used_items.add(n)
        used_refs.add(m)
        found[n] = reference[m]
    return found


def verdict(item, ref):
    if ref is None:
        return "not in reference"
    if ref["date"] is None:
        return "dated, but undatable"
    if item["date"] != ref["date"] or (item.get("end_date") or None) != (ref.get("end_date") or None):
        return "wrong date"
    return "correct"


def score(calendar, reference):
    """calendar: items with a date. Returns per-item verdicts and the totals for the comparison table."""
    pairs = match(calendar, reference)
    verdicts = [verdict(item, pairs.get(n)) for n, item in enumerate(calendar)]
    matched = {id(r) for r in pairs.values()}
    missed = [r for r in reference if r["date"] and id(r) not in matched]
    return verdicts, {
        "on_calendar": len(calendar),
        "correct": verdicts.count("correct"),
        "wrong_date": verdicts.count("wrong date"),
        "invented_date": verdicts.count("dated, but undatable"),
        "not_in_reference": verdicts.count("not in reference"),
        "missed": len(missed),
    }


def baseline_calendar(events):
    """The baseline's events as calendar items. Unparseable dates can't go on a calendar."""
    items = []
    for e in next((x["events"] for x in events if x["type"] == "baseline"), []):
        try:
            start = date.fromisoformat(e["date"].strip()[:10])
        except ValueError:
            continue
        try:
            end = date.fromisoformat(e["end_date"].strip()[:10]) if e["end_date"].strip() else None
        except ValueError:
            end = None
        items.append({**e, "date": start, "end_date": end if end != start else None})
    return items
