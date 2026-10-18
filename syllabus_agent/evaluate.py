"""Score the recorded runs in evals/ against the hand-checked answer keys. No model calls.

    python -m syllabus_agent.evaluate      prints the tables the README and the app show

Synthetic: five generated syllabi full of relative dates ("Week 7 Thu", "the day after Lecture 12"),
one verified run and four baseline runs. Real: five real syllabi, the verified demo run; the
baseline only fits Groq's free tier for two of them at once, so it is compared on those two.
"""

import json
from pathlib import Path

from .compare import answer_key, baseline_calendar, score
from .load import build
from .term import course_key, load_term

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"


def load(path):
    return json.loads(Path(path).read_text())


def scored(calendar, reference, courses=None):
    keep = (lambda i: course_key(i["course"]) in courses) if courses else (lambda i: True)
    calendar, reference = [i for i in calendar if keep(i)], [r for r in reference if keep(r)]
    totals = score(calendar, reference)[1]
    return {**totals, "dated": sum(1 for r in reference if r["date"]),
            "unsourced": sum(not i.get("source_found", True) for i in calendar)}


def verified(record, courses=None):
    result = build(record["events"], load_term(record["term"]))
    totals = scored(result["calendar"], answer_key(record["files"]), courses)
    keep = (lambda i: course_key(i["course"]) in courses) if courses else (lambda i: True)
    return {**totals, "review": sum(map(keep, result["review"])), "rejected": sum(map(keep, result["rejected"]))}


def baseline(record):
    return {**scored(baseline_calendar(record["events"]), answer_key(record["files"])), "review": 0}


def summary():
    demo = EVALS / "real-verified.json"  # a copy of the demo recording, so new live runs don't change the eval
    pair = load(EVALS / "real-baseline-CPSC2010-MATH2250.json")
    courses = {course_key(r["course"]) for r in answer_key(pair["files"])}
    return {
        "synthetic": {"verified": [verified(load(EVALS / "synthetic-verified.json"))],
                      "baseline": [baseline(load(p)) for p in sorted(EVALS.glob("synthetic-baseline-*.json"))]},
        "real": {"verified": verified(load(demo)),
                 "pair": {"verified": verified(load(demo), courses), "baseline": baseline(pair)}},
    }


def runs(scores, field):
    values = [s[field] for s in scores]
    return str(values[0]) if len(set(values)) == 1 else ", ".join(map(str, values))


def synthetic_table(results):
    v, b = results["synthetic"]["verified"], results["synthetic"]["baseline"]
    dated = v[0]["dated"]
    return {
        "": ["Correct dates", "Wrong dates", "Reference items missed", "Cited text not in the PDFs",
             "Sent to review instead of guessing"],
        f"Verified pipeline ({len(v)} run)": [f"{runs(v, 'correct')} of {dated}", runs(v, "wrong_date"), runs(v, "missed"),
                                             runs(v, "unsourced"), runs(v, "review")],
        f"Single-prompt baseline ({len(b)} runs)": [f"{runs(b, 'correct')} of {dated}", runs(b, "wrong_date"),
                                                    runs(b, "missed"), runs(b, "unsourced"), runs(b, "review")],
    }


def real_table(results):
    v, pv, pb = results["real"]["verified"], results["real"]["pair"]["verified"], results["real"]["pair"]["baseline"]
    return {
        "": ["Correct dates", "Wrong dates", "Reference items missed", "Extra items (not graded)", "Sent to review"],
        "Verified · all 5 syllabi": [f"{v['correct']} of {v['dated']}", v["wrong_date"], v["missed"],
                                     v["not_in_reference"], v["review"]],
        "Verified · CPSC 2010 + MATH 2250": [f"{pv['correct']} of {pv['dated']}", pv["wrong_date"], pv["missed"],
                                            pv["not_in_reference"], pv["review"]],
        "Baseline · CPSC 2010 + MATH 2250": [f"{pb['correct']} of {pb['dated']}", pb["wrong_date"], pb["missed"],
                                            pb["not_in_reference"], pb["review"]],
    }


def markdown(table):
    columns = list(table)
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(str(table[c][n]) for c in columns) + " |" for n in range(len(table[columns[0]]))]
    return "\n".join(lines)


if __name__ == "__main__":
    results = summary()
    print("Synthetic syllabi (relative dates)\n\n" + markdown(synthetic_table(results)))
    print("\nReal syllabi (mostly absolute dates)\n\n" + markdown(real_table(results)))
