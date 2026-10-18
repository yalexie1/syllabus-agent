import json
import os
import re
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from icalendar import Calendar
from openai import BadRequestError, RateLimitError

from syllabus_agent.agents import BASELINE, EXTRACTOR, REPAIR, RESOLVER, Run, retry_after
from syllabus_agent.charts import heatmap
from syllabus_agent.compare import answer_key, baseline_calendar, score, similar
from syllabus_agent.export import calendar_file
from syllabus_agent.citations import check_item, found_anywhere, normalize
from syllabus_agent.load import build, dedupe, infer_weights, weekly
from syllabus_agent.pdfs import NoText, read_pdf
from syllabus_agent.term import Unresolved, load_term, meeting_days, resolve, term_yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SYLLABI = FIXTURES / "syllabi"
TERM = load_term((SYLLABI / "demo_term.yaml").read_text())


def syllabus(name):
    path = SYLLABI / name
    return read_pdf(path.name, path.read_bytes())


class CitationTests(unittest.TestCase):
    PAGES = ["The first midterm is an evening ex-\namination on Week 7 Thursday at 7 pm.\n"
             "The ﬁnal exam is on Jan 6. Students’ “late” work: Nov 3–5.",
             "Week 2 Fri Problem Set 1 due"]

    def check(self, quote, when, page=1):
        return check_item({"quote": quote, "date_expr": when, "page": page}, self.PAGES)

    def test_normalize(self):
        self.assertEqual(normalize("ex-\namination"), "examination")
        self.assertEqual(normalize("ﬁnal  EXAM"), "final exam")
        self.assertEqual(normalize("“Late” it’s"), "late\" it's")
        self.assertEqual(normalize("Nov 3 – 5"), normalize("Nov 3-5"))
        self.assertEqual(normalize("take-home"), normalize("takehome"))

    def test_passes_across_hyphenated_line_break(self):
        self.assertTrue(self.check("an evening examination on Week 7 Thursday at 7 pm", "Week 7 Thursday")[0])

    def test_passes_with_ligatures_smart_quotes_and_dashes(self):
        self.assertTrue(self.check("The final exam is on Jan 6.", "Jan 6")[0])
        self.assertTrue(self.check("Students' \"late\" work: Nov 3-5", "Nov 3–5")[0])

    def test_fails_when_quote_is_not_on_the_page(self):
        ok, reason = self.check("The final exam is on Jan 7.", "Jan 7")
        self.assertFalse(ok)
        self.assertIn("Closest text", reason)

    def test_fails_on_wrong_page_and_says_where(self):
        ok, reason = self.check("Week 2 Fri Problem Set 1 due", "Week 2 Fri", page=1)
        self.assertEqual((ok, reason), (False, "quote is on page 2, not page 1"))

    def test_passes_when_pdf_text_lost_spaces(self):
        page = "MidtermExam1isscheduledforThursday, October1, andMidtermExam2forThursday, Novem-\nber 12."
        for expr in ("Thursday, October 1", "Thursday, November 12"):
            ok, _ = check_item({"page": 1, "date_expr": expr, "quote": page.replace("-\n", "- ")}, [page])
            self.assertTrue(ok, expr)

    def test_passes_when_quote_drops_the_space_at_a_line_break(self):
        page = "HomeworkwillbedueonThursdaysat11:59pm,exceptonexamweekswhentherewillbeashorter\nassignment due on Monday."
        quote = "HomeworkwillbedueonThursdaysat11:59pm,exceptonexamweekswhentherewillbeashorterassignmentdueonMonday."
        self.assertTrue(check_item({"page": 1, "date_expr": "Thursdays at 11:59pm", "quote": quote}, [page])[0])

    def test_fails_when_date_is_not_in_the_quote(self):
        ok, reason = self.check("The final exam is on Jan 6.", "January 6")
        self.assertFalse(ok)
        self.assertIn("not inside the quote", reason)

    def test_fails_on_bad_page_or_long_quote(self):
        self.assertFalse(self.check("Week 2 Fri", "Week 2 Fri", page=3)[0])
        self.assertIn("words", self.check("word " * 41, "word")[1])

    def test_found_anywhere(self):
        self.assertTrue(found_anywhere("problem set 1 due", self.PAGES))
        self.assertFalse(found_anywhere("Problem Set 9 due", self.PAGES))


class PdfTests(unittest.TestCase):
    def test_reads_pages(self):
        chem = syllabus("chem210_organic_chemistry.pdf")
        self.assertEqual(len(chem["pages"]), 2)
        self.assertIn("Week 7 Thursday", chem["pages"][0])
        self.assertEqual(len(chem["sha256"]), 64)

    def test_scanned_pdf_is_skipped(self):
        with self.assertRaises(NoText):
            read_pdf("scan.pdf", (FIXTURES / "scanned_handout.pdf").read_bytes())

    def test_answer_key_matches_fixture_files(self):
        key = json.loads((SYLLABI / "answer_key.json").read_text())
        for name, entry in key.items():
            self.assertEqual(syllabus(name)["sha256"], entry["sha256"], f"rerun make_syllabi.py ({name})")


def at(**spec):
    return resolve(spec, TERM, ["Tue", "Thu"])[0]


class ResolverTests(unittest.TestCase):
    def test_absolute_dates_take_the_term_year_across_new_year(self):
        self.assertEqual(at(kind="absolute", month=10, day=14), date(2026, 10, 14))
        self.assertEqual(at(kind="absolute", month=1, day=6), date(2027, 1, 6))

    def test_absolute_outside_term_or_impossible(self):
        with self.assertRaisesRegex(Unresolved, "outside the term"):
            at(kind="absolute", month=3, day=3)
        with self.assertRaisesRegex(Unresolved, "not a real date"):
            at(kind="absolute", month=2, day=30)

    def test_absolute_date_with_the_wrong_weekday_needs_review(self):
        self.assertEqual(at(kind="absolute", month=10, day=14, weekday="Wed"), date(2026, 10, 14))
        with self.assertRaisesRegex(Unresolved, "says Thu, but Tue Dec 15, 2026 is a Tuesday"):
            at(kind="absolute", month=12, day=15, weekday="Thu")

    def test_week_weekday_counts_calendar_weeks_including_breaks(self):
        self.assertEqual(at(kind="week_weekday", week=1, weekday="Mon"), date(2026, 9, 14))
        self.assertEqual(at(kind="week_weekday", week=7, weekday="Thu"), date(2026, 10, 29))

    def test_date_in_a_break_needs_review(self):
        with self.assertRaisesRegex(Unresolved, "Fall break"):
            at(kind="week_weekday", week=6, weekday="Tue")

    def test_nth_meeting_skips_breaks(self):
        self.assertEqual(at(kind="nth_meeting", n=10, offset_days=0), date(2026, 10, 15))
        self.assertEqual(at(kind="nth_meeting", n=11, offset_days=0), date(2026, 10, 27))
        self.assertEqual(at(kind="nth_meeting", n=12, offset_days=1), date(2026, 10, 30))
        monday_wednesday = resolve({"kind": "nth_meeting", "n": 20}, TERM, ["Mon", "Wed"])[0]
        self.assertEqual(monday_wednesday, date(2026, 11, 30))  # Nov 25 is Thanksgiving recess

    def test_nth_meeting_needs_days_and_enough_meetings(self):
        with self.assertRaisesRegex(Unresolved, "meeting days unknown"):
            resolve({"kind": "nth_meeting", "n": 3}, TERM, [])
        with self.assertRaisesRegex(Unresolved, "only"):
            at(kind="nth_meeting", n=99)

    def test_range(self):
        window = {"kind": "range", "start": {"kind": "absolute", "month": 11, "day": 3},
                  "end": {"kind": "absolute", "month": None, "day": 5}}
        self.assertEqual(resolve(window, TERM), (date(2026, 11, 3), date(2026, 11, 5)))
        backwards = {"kind": "range", "start": {"kind": "absolute", "month": 11, "day": 5},
                     "end": {"kind": "absolute", "month": 11, "day": 3}}
        with self.assertRaisesRegex(Unresolved, "before it starts"):
            resolve(backwards, TERM)

    def test_unresolvable_keeps_its_reason(self):
        with self.assertRaisesRegex(Unresolved, "TBA"):
            at(kind="unresolvable", reason="TBA")

    def test_term_config(self):
        term = load_term(term_yaml({**TERM, "courses": {"CHEM 210": ["Mon", "Wed", "Fri"]}}))
        self.assertEqual(term["breaks"], TERM["breaks"])
        self.assertEqual(meeting_days(term, "chem-210", ["Tue"]), ["Mon", "Wed", "Fri"])
        self.assertEqual(meeting_days(term, "CPSC 223", ["Tue", "Thu"]), ["Tue", "Thu"])
        placeholder = load_term((ROOT / "syllabus_agent" / "term.yaml").read_text())
        self.assertIn("PLACEHOLDER", placeholder["name"])
        with self.assertRaises(ValueError):
            load_term("start: 2026-09-01\nend: 2026-08-01\n")


def item(id, course="CHEM 210", type="problem_set", title="Problem Set 1", day=date(2026, 9, 25), weight=None):
    return {"id": id, "course": course, "type": type, "title": title, "date": day, "end_date": None,
            "weight_pct": weight, "weight_expr": "", "week": (day - date(2026, 9, 14)).days // 7 + 1}


def worker(grading, course="CHEM 210"):
    return {"W": {"course": course, "grading": grading}}


class LoadTests(unittest.TestCase):
    def test_weight_from_breakdown_with_dropped_items(self):
        sets = [item(f"p{n}", title=f"Problem Set {n}") for n in range(1, 7)]
        infer_weights(sets, [], worker([{"type": "problem_set", "label": "Problem sets", "weight_pct": 30,
                                         "count": 6, "dropped": 1}]))
        self.assertEqual({s["weight"] for s in sets}, {6.0})
        self.assertTrue(sets[0]["weight_inferred"])
        self.assertIn("1 dropped", sets[0]["weight_note"])

    def test_weight_counts_items_when_breakdown_has_no_count(self):
        quizzes = [item(f"q{n}", type="quiz", title=f"Quiz {n}") for n in range(4)]
        infer_weights(quizzes, [], worker([{"type": "quiz", "label": "Quizzes", "weight_pct": 20,
                                            "count": None, "dropped": 0}]))
        self.assertEqual(quizzes[0]["weight"], 5)

    def test_explicit_weight_and_default_fallback(self):
        exam, paper = item("e", type="exam", title="Midterm", weight=25), item("p", type="paper", title="Essay")
        infer_weights([exam, paper], [], worker([]))
        self.assertEqual((exam["weight"], exam["weight_inferred"]), (25, False))
        self.assertEqual((paper["weight"], paper["weight_inferred"]), (10, True))

    def test_breakdown_line_without_a_weight_falls_back_to_default(self):
        exam = item("m1", type="exam", title="Midterm Exam 1")
        infer_weights([exam], [], worker([{"type": "exam", "label": "Midterm Exam 1", "weight_pct": None,
                                           "count": None, "dropped": 0}]))
        self.assertEqual((exam["weight"], exam["weight_note"]), (20, "default for exam"))

    def test_breakdown_given_as_fractions_is_read_as_percents(self):
        exams = [item(f"e{n}", type="exam", title=f"Exam {n}") for n in range(3)]
        infer_weights(exams, [], worker([{"type": "exam", "label": "Exams", "weight_pct": 0.67, "count": 3, "dropped": 0},
                                         {"type": "other", "label": "Homework", "weight_pct": 0.33, "count": None,
                                          "dropped": 0}]))
        self.assertAlmostEqual(exams[0]["weight"], 22.33)

    def test_multiple_exam_lines_match_by_label(self):
        exams = [item("m1", type="exam", title="Midterm 1"), item("f", type="exam", title="Final exam")]
        infer_weights(exams, [], worker([
            {"type": "exam", "label": "Midterm 1", "weight_pct": 20, "count": 1, "dropped": 0},
            {"type": "exam", "label": "Final exam", "weight_pct": 30, "count": 1, "dropped": 0}]))
        self.assertEqual([e["weight"] for e in exams], [20, 30])

    def test_dedupe_keeps_the_item_with_a_weight(self):
        first = item("a", type="exam", title="Midterm 1 (evening)")
        second = item("b", type="exam", title="Midterm 1", weight=20)
        kept, dupes = dedupe([first, second])
        self.assertEqual([k["id"] for k in kept], ["b"])
        self.assertEqual(dupes[0]["id"], "a")

    def test_dedupe_keeps_different_items_on_the_same_day(self):
        kept, dupes = dedupe([item("a"), item("b", title="Problem Set 2"), item("c", course="ECON 115")])
        self.assertEqual((len(kept), dupes), (3, []))

    def test_crunch_weeks(self):
        cal = [item("a", type="exam", title="A", day=date(2026, 10, 27)),
               item("b", type="exam", title="B", day=date(2026, 10, 29)),
               item("c", day=date(2026, 9, 25)), item("d", day=date(2026, 11, 6))]
        for weight, i in zip([20, 25, 6, 4], cal):
            i["weight"] = weight
        weeks = weekly(cal, TERM)
        self.assertEqual(len(weeks), 17)
        crunch = [w for w in weeks if w["crunch"]]
        self.assertEqual([w["week"] for w in crunch], [2, 7, 8])
        self.assertEqual(crunch[1]["summary"], "2 exams = 45%")
        self.assertIn("2 exams", crunch[1]["why"])


class ExportTests(unittest.TestCase):
    def test_ics_round_trips(self):
        exam = {**item("e", type="exam", title="Midterm 1", day=date(2026, 10, 29)), "weight": 20,
                "weight_inferred": False, "quote": "an evening examination on Week 7 Thursday", "page": 1,
                "file": "chem.pdf", "date_expr": "Week 7 Thursday", "weight_note": "20%"}
        window = {**exam, "id": "w", "title": "Take-home", "date": date(2026, 11, 3),
                  "end_date": date(2026, 11, 5), "weight": 6, "weight_inferred": True}
        events = Calendar.from_ical(calendar_file([exam, window])).walk("VEVENT")
        self.assertEqual([str(e["summary"]) for e in events],
                         ["[CHEM 210] Midterm 1 (20%)", "[CHEM 210] Take-home (~6%)"])
        self.assertEqual((events[0]["dtstart"].dt, events[0]["dtend"].dt), (date(2026, 10, 29), date(2026, 10, 30)))
        self.assertEqual((events[1]["dtstart"].dt, events[1]["dtend"].dt), (date(2026, 11, 3), date(2026, 11, 6)))
        self.assertIn("an evening examination on Week 7 Thursday", str(events[0]["description"]))
        self.assertIn("page 1", str(events[0]["description"]))
        self.assertNotEqual(events[0]["uid"], events[1]["uid"])

    def test_pipeline_ics_excludes_needs_review(self):
        result = build(run_pipeline(FakeModel()), TERM)
        events = Calendar.from_ical(calendar_file(result["calendar"])).walk("VEVENT")
        titles = [str(e["summary"]) for e in events]
        self.assertEqual(len(titles), len(result["calendar"]))
        self.assertFalse(any("Schedule changes" in t or "Lab 1" in t for t in titles))


# A scripted model. It reads real fixture PDFs, cites one quote wrongly (fixed on repair) and
# invents one item (dropped on repair), so the pipeline's checks have something to catch.

def response(payload):
    return SimpleNamespace(output_text=json.dumps(payload), output=[],
                           usage=SimpleNamespace(input_tokens=100, output_tokens=50))


def found(type, title, when, quote, page, weight=None):
    return {"type": type, "title": title, "date_expr": when, "weight_pct": weight,
            "weight_expr": f"{weight}%" if weight else "", "quote": quote, "page": page}


EXTRACTIONS = {
    "chem210_organic_chemistry.pdf": {
        "course": "CHEM 210", "meeting_days": ["Mon", "Wed", "Fri"],
        "grading_breakdown": [
            {"type": "problem_set", "label": "Problem sets", "weight_pct": 30, "count": 6, "dropped": 1},
            {"type": "exam", "label": "Midterm 1", "weight_pct": 20, "count": 1, "dropped": 0},
            {"type": "exam", "label": "Final exam", "weight_pct": 30, "count": 1, "dropped": 0}],
        "items": [
            found("problem_set", "Problem Set 1", "Week 2 Fri", "Week 2 Fri Problem Set 1 due", 2),
            found("problem_set", "Problem Set 3", "Week 5 Fri", "Week 5 Friday Problem Set 3 due", 2),
            found("exam", "Midterm 1", "Week 7 Thursday",
                  "The first midterm is an evening examination on Week 7 Thursday at 7 pm", 1, 20),
            found("exam", "Midterm 1 (evening)", "Week 7 Thu", "Week 7 Thu Midterm 1 (evening)", 2),
            found("exam", "Final exam", "Jan 6", "The cumulative final exam is on Jan 6 at 9:00 am", 1, 30)]},
    "cpsc223_data_structures.pdf": {
        "course": "CPSC 223", "meeting_days": ["Tue", "Thu"],
        "grading_breakdown": [{"type": "problem_set", "label": "Problem sets", "weight_pct": 40,
                               "count": 5, "dropped": 0}],
        "items": [
            found("problem_set", "Problem Set 3", "the day after Lecture 12",
                  "Problem Set 3 is due the day after Lecture 12.", 1),
            found("exam", "Take-home midterm", "Nov 3-5", "due within the window Nov 3-5; you may use", 1, 25),
            found("other", "Schedule changes", "subject to change", "All dates are subject to change; changes will be posted", 2),
            found("other", "Lab 1", "Sep 18", "Lab 1 is due Sep 18", 1)]},
}

DATES = {
    r"Week (\d+) (\w{3})\w*": lambda m: {"kind": "week_weekday", "week": int(m[1]), "weekday": m[2]},
    r"the day after Lecture (\d+)": lambda m: {"kind": "nth_meeting", "n": int(m[1]), "offset_days": 1},
    r"Nov 3-5": lambda m: {"kind": "range", "start": {"kind": "absolute", "month": 11, "day": 3},
                          "end": {"kind": "absolute", "month": 11, "day": 5}},
    r"Jan (\d+)": lambda m: {"kind": "absolute", "month": 1, "day": int(m[1])},
}


class FakeModel:
    def __init__(self, fail_first=None):
        self.calls, self.fail_first = [], fail_first
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_first:
            error, self.fail_first = self.fail_first, None
            raise error
        instructions, given = kwargs["instructions"], kwargs["input"]
        if instructions == EXTRACTOR:
            name = re.match(r"File: (\S+)", given)[1]
            return response(json.loads(json.dumps(EXTRACTIONS[name])))
        if instructions == REPAIR:
            notes = given[-1]["content"]
            fixes = []
            if "Week 5 Friday" in notes:
                failed_id = re.search(r"- (\S+) \"Problem Set 3\"", notes)[1]
                fixes.append({"id": failed_id, **found("problem_set", "Problem Set 3", "Week 5 Fri",
                                                       "Week 5 Fri Problem Set 3 due", 2)})
            return response({"items": fixes})  # Lab 1 can't be supported, so it's left out
        if instructions == BASELINE:
            return response({"events": [
                {"course": "CHEM 210", "type": "exam", "title": "Midterm 1", "date": "2026-11-05", "end_date": "",
                 "weight_pct": 20, "source": "Midterm 1 is on Week 7 Thursday"},
                {"course": "CHEM 210", "type": "exam", "title": "Final exam", "date": "2027-01-06", "end_date": "",
                 "weight_pct": 30, "source": "The cumulative final exam is on Jan 6"},
                {"course": "CHEM 210", "type": "problem_set", "title": "Problem Set 1", "date": "TBA",
                 "end_date": "", "weight_pct": None, "source": "Week 2 Fri Problem Set 1 due"}]})
        if instructions == RESOLVER:
            dates = []
            for entry in json.loads(given):
                spec = {"kind": "unresolvable", "reason": entry["date_expr"]}
                for pattern, make in DATES.items():
                    if m := re.fullmatch(pattern, entry["date_expr"]):
                        spec = make(m)
                dates.append({"id": entry["id"], **spec})
            return response({"dates": dates})
        raise AssertionError(f"unexpected instructions {instructions[:40]}")


def run_pipeline(model, names=("chem210_organic_chemistry.pdf", "cpsc223_data_structures.pdf")):
    events = []
    Run([syllabus(n) for n in names], TERM, emit=events.append, client=model).run()
    return events


class PipelineTests(unittest.TestCase):
    def test_end_to_end_on_fixtures(self):
        model = FakeModel()
        events = run_pipeline(model)
        self.assertEqual(events[0]["type"], "start")
        self.assertEqual(events[-1]["type"], "stats")
        self.assertEqual({e["worker"] for e in events if e["type"] == "worker"}, {"S1", "S2"})

        result = build(events, TERM)
        on_calendar = {(i["course"], i["title"]): (i["date"], i["end_date"]) for i in result["calendar"]}
        self.assertEqual(on_calendar, {
            ("CHEM 210", "Problem Set 1"): (date(2026, 9, 25), None),
            ("CHEM 210", "Problem Set 3"): (date(2026, 10, 16), None),
            ("CHEM 210", "Midterm 1"): (date(2026, 10, 29), None),
            ("CHEM 210", "Final exam"): (date(2027, 1, 6), None),
            ("CPSC 223", "Problem Set 3"): (date(2026, 10, 30), None),
            ("CPSC 223", "Take-home midterm"): (date(2026, 11, 3), date(2026, 11, 5)),
        })
        self.assertEqual([i["title"] for i in result["rejected"]], ["Lab 1"])
        self.assertEqual([i["title"] for i in result["review"]], ["Schedule changes"])
        self.assertEqual([i["title"] for i in result["duplicates"]], ["Midterm 1 (evening)"])
        weights = {i["title"]: i["weight"] for i in result["calendar"] if i["course"] == "CHEM 210"}
        self.assertEqual(weights["Problem Set 1"], 6.0)
        self.assertEqual(weights["Midterm 1"], 20)

    def test_repair_sees_the_failure_and_only_the_pages_involved(self):
        model = FakeModel()
        events = run_pipeline(model, names=("chem210_organic_chemistry.pdf",))
        repair = next(c for c in model.calls if c["instructions"] == REPAIR)
        pages = [int(n) for n in re.findall(r"=== Page (\d+) ===", repair["input"][0]["content"])]
        failed = [r for e in events if e["type"] == "check" and not e["retry"] for r in e["results"] if not r["ok"]]
        self.assertTrue(pages and all(any(abs(n - r["page"]) <= 1 for r in failed) for n in pages))
        self.assertIn("Closest text", repair["input"][1]["content"])
        retry = [e for e in events if e["type"] == "check" and e["retry"]]
        self.assertTrue(retry[0]["results"][0]["ok"])

    def test_at_most_three_calls_per_worker(self):
        model = FakeModel()
        run_pipeline(model)
        self.assertLessEqual(len(model.calls), 3 * 2)

    def test_rate_limit_waits_and_is_shown(self):
        limited = RateLimitError("Rate limit reached. Please try again in 1.5s.",
                                 response=httpx.Response(429, request=httpx.Request("POST", "http://x")), body=None)
        self.assertGreaterEqual(retry_after(limited), 1.5)
        with patch("syllabus_agent.agents.time.sleep") as sleep:
            events = run_pipeline(FakeModel(fail_first=limited), names=("chem210_organic_chemistry.pdf",))
        self.assertTrue(sleep.called)
        self.assertTrue(any(e["type"] == "waiting" for e in events))
        self.assertEqual(len(build(events, TERM)["calendar"]), 4)

    def test_daily_limit_fails_fast_with_a_clear_message(self):
        daily = RateLimitError("Rate limit reached on tokens per day (TPD): Limit 200000. Please try again in "
                               "35m40.3s.", response=httpx.Response(429, request=httpx.Request("POST", "http://x")),
                               body=None)
        with patch("syllabus_agent.agents.time.sleep") as sleep:
            events = run_pipeline(FakeModel(fail_first=daily), names=("chem210_organic_chemistry.pdf",))
        self.assertFalse(sleep.called)
        self.assertEqual([e["message"] for e in events if e["type"] == "error"],
                         ["Groq's daily token limit is used up; try again in 35m40.3s."])

    def test_off_schema_answer_is_retried_once(self):
        invalid = BadRequestError("json_validate_failed", body=None,
                                  response=httpx.Response(400, request=httpx.Request("POST", "http://x")))
        events = run_pipeline(FakeModel(fail_first=invalid), names=("chem210_organic_chemistry.pdf",))
        self.assertFalse([e for e in events if e["type"] == "error"])

    def test_truncated_answer_is_retried_at_low_reasoning(self):
        cut_off = BadRequestError("max completion tokens reached before generating a valid document", body=None,
                                  response=httpx.Response(400, request=httpx.Request("POST", "http://x")))
        model = FakeModel(fail_first=cut_off)
        events = run_pipeline(model, names=("chem210_organic_chemistry.pdf",))
        self.assertFalse([e for e in events if e["type"] == "error"])
        self.assertTrue(any(e["type"] == "lowered" for e in events))
        self.assertEqual(model.calls[1]["reasoning"], {"effort": "low"})

    def test_long_syllabus_is_extracted_in_batches_of_pages(self):
        chem = syllabus("chem210_organic_chemistry.pdf")
        one_page = Run.output_budget(EXTRACTOR, Run.extract_text(chem, [1]))
        model = FakeModel()
        with patch("syllabus_agent.agents.MIN_EXTRACT_OUTPUT", one_page):  # both pages together don't fit
            events = run_pipeline(model, names=("chem210_organic_chemistry.pdf",))
        extracts = [c["input"] for c in model.calls if c["instructions"] == EXTRACTOR]
        self.assertEqual(len(extracts), 2)
        self.assertIn("=== Page 1 ===", extracts[0])
        self.assertNotIn("=== Page 2 ===", extracts[0])
        self.assertIn("Pages 2-2 of 2", extracts[1])
        self.assertIn("don't repeat these:\n- Problem Set 1: Week 2 Fri", extracts[1])
        # The fake answers the same for each batch: the merge keeps one copy of each item and category.
        extracted = next(e for e in events if e["type"] == "extracted")
        self.assertEqual(len(extracted["items"]), 5)
        self.assertEqual(len(extracted["grading"]), 3)
        self.assertFalse([e for e in events if e["type"] == "error"])

    def test_worker_errors_are_reported_not_raised(self):
        model = FakeModel(fail_first=RuntimeError("boom"))
        events = run_pipeline(model, names=("chem210_organic_chemistry.pdf",))
        self.assertEqual([e["message"] for e in events if e["type"] == "error"], ["boom"])
        self.assertEqual(events[-1]["type"], "stats")


class BaselineAndCompareTests(unittest.TestCase):
    def test_baseline_is_one_unchecked_call(self):
        model, events = FakeModel(), []
        Run([syllabus("chem210_organic_chemistry.pdf")], TERM, emit=events.append, client=model).run("baseline")
        self.assertEqual(len(model.calls), 1)
        self.assertIn("2026-09-14", model.calls[0]["input"])  # it gets the term, to be fair
        raw = next(e for e in events if e["type"] == "baseline")["events"]
        self.assertEqual([e["source_found"] for e in raw], [False, True, True])
        calendar = baseline_calendar(events)
        self.assertEqual([i["title"] for i in calendar], ["Midterm 1", "Final exam"])  # "TBA" isn't a date

    def test_answer_key_only_for_demo_files(self):
        chem = syllabus("chem210_organic_chemistry.pdf")
        self.assertEqual(len(answer_key([chem])), 9)
        self.assertIsNone(answer_key([chem, {"sha256": "0" * 64}]))

    def test_title_matching(self):
        self.assertGreaterEqual(similar("PS1", "Problem Set 1"), 0.5)
        self.assertGreaterEqual(similar("Final Exam", "Final exam"), 0.5)
        self.assertEqual(similar("Problem Set 1", "Problem Set 2"), 0.0)

    def test_score(self):
        reference = [
            {"course": "CHEM 210", "type": "exam", "title": "Midterm 1", "date": date(2026, 10, 29), "end_date": None},
            {"course": "CHEM 210", "type": "exam", "title": "Final exam", "date": date(2027, 1, 6), "end_date": None},
            {"course": "CHEM 210", "type": "presentation", "title": "Presentation", "date": None, "end_date": None},
            {"course": "CHEM 210", "type": "paper", "title": "Essay", "date": date(2026, 12, 1), "end_date": None}]
        calendar = [
            {"course": "CHEM 210", "type": "exam", "title": "Midterm 1", "date": date(2026, 11, 5)},
            {"course": "chem-210", "type": "exam", "title": "Final Exam", "date": date(2027, 1, 6)},
            {"course": "CHEM 210", "type": "presentation", "title": "Presentation", "date": date(2026, 12, 2)},
            {"course": "CHEM 210", "type": "quiz", "title": "Pop quiz", "date": date(2026, 9, 30)}]
        verdicts, totals = score(calendar, reference)
        self.assertEqual(verdicts, ["wrong date", "correct", "dated, but undatable", "not in reference"])
        self.assertEqual((totals["missed"], totals["on_calendar"]), (1, 4))


class ChartTests(unittest.TestCase):
    def test_heatmap_spec_in_both_themes(self):
        result = build(run_pipeline(FakeModel()), TERM)
        for mode in ("light", "dark"):
            spec = heatmap(result, TERM, mode).to_dict()
            self.assertEqual(len(spec["vconcat"]), 2)
            self.assertNotIn('"scale": null', json.dumps(spec))  # Vega-Lite fails to render a null scale


FIXTURE_RUN = ROOT / "tests" / "fixtures" / "demo_run.json"  # a verified run over the five fixture PDFs
DEMO = sorted((ROOT / "syllabus_agent" / "runs").glob("*.json"))[-1]  # the recording the app offers


class PageTests(unittest.TestCase):
    def app(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(str(ROOT / "syllabus_agent" / "page.py"), default_timeout=60)

    def test_missing_key(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "GROK_API_KEY": ""}):
            app = self.app().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("placeholder" in w.value for w in app.warning))
            next(b for b in app.button if b.label == "Run").click().run()
            self.assertTrue(any("GROQ_API_KEY" in e.value for e in app.error))

    def test_replay_runs_offline_and_restores_the_recorded_term(self):
        with patch.dict(os.environ, {"SYLLABUS_REPLAY_SPEED": "0"}):
            app = self.app().run()
            app.selectbox[0].select(DEMO).run()
            next(b for b in app.button if b.label == "Replay recording").click().run()
        self.assertFalse(app.exception)
        recorded = json.loads(DEMO.read_text())
        self.assertEqual(app.session_state.term["name"], load_term(recorded["term"])["name"])
        metrics = {m.label: m.value for m in app.metric}
        expected = build(recorded["events"], load_term(recorded["term"]))
        self.assertEqual(int(metrics["On calendar"]), len(expected["calendar"]))

    def test_comparison_table_after_both_modes(self):
        verified = json.loads(FIXTURE_RUN.read_text())
        events = []
        Run([syllabus(f["name"]) for f in verified["files"]], TERM, emit=events.append,
            client=FakeModel()).baseline()
        baseline = {**verified, "mode": "baseline", "events": [
            {"type": "start", "mode": "baseline", "model": "fake", "files": verified["files"]}, *events,
            {"type": "stats", "mode": "baseline", "seconds": 1, "model_calls": 1, "input_tokens": 1, "output_tokens": 1}]}
        key = tuple(sorted(f["sha256"] for f in verified["files"]))
        app = self.app()
        app.session_state.term = load_term(verified["term"])
        app.session_state.term_version = 1
        app.session_state.last = baseline
        app.session_state.compare = {key: {"verified": verified, "baseline": baseline}}
        app.run()
        self.assertFalse(app.exception)
        table = app.table[0].value
        self.assertEqual(list(table.columns), ["", "Verified pipeline", "Single-prompt baseline"])
        wrong = table[table[""] == "Wrong dates"]
        self.assertEqual(wrong["Verified pipeline"].iloc[0], "0")
        self.assertEqual(wrong["Single-prompt baseline"].iloc[0], "1")


if __name__ == "__main__":
    unittest.main()
