"""The Syllagent page. Open it from app.py."""

import json
import os
import queue
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

from syllabus_agent import config
from syllabus_agent.agents import Run
from syllabus_agent.charts import heatmap
from syllabus_agent.compare import answer_key, baseline_calendar, from_pipeline, score
from syllabus_agent.evaluate import real_table, summary, synthetic_table
from syllabus_agent.export import calendar_file
from syllabus_agent.load import build, collect
from syllabus_agent.pdfs import NoText, read_pdf
from syllabus_agent.term import as_date, day_name, fmt, load_term, term_yaml

HERE = Path(__file__).parent
RUNS = HERE / "runs"
DEMO = HERE.parent / "tests" / "fixtures" / "syllabi"
SHOW_FAILURES = 2
MODES = {"Verified pipeline": "verified", "Single-prompt baseline": "baseline"}

ACCENT = {"light": "#c2410c", "dark": "#ff7a3d"}


def theme_mode():
    try:
        return st.context.theme.type or "light"
    except Exception:
        return "light"


def style():
    accent = ACCENT[theme_mode()]
    st.html(f"""<style>
    [data-testid="stMarkdownContainer"] blockquote {{ border-left: 3px solid {accent}; padding: .1rem 0 .1rem 1rem;
        margin: .4rem 0; font-size: 1.1rem; }}
    </style>""")


def masthead():
    st.title("Syllagent")
    st.image(str(HERE / "architecture.png"), width="stretch")


def section(title, note=""):
    st.subheader(title, divider="gray")
    if note:
        st.caption(note)


# Term config lives in session state. Widgets are keyed by a version number so that loading
# a term (demo, replay, or meeting days found in a syllabus) redraws them with the new values.

def set_term(term):
    st.session_state.term = term
    st.session_state.term_version = st.session_state.get("term_version", 0) + 1


if "term" not in st.session_state:
    set_term(load_term((HERE / "term.yaml").read_text()))
style()


def records(table):
    rows = table.to_dict("records") if hasattr(table, "to_dict") else list(table)
    return [r for r in rows if all(v is not None and str(v) not in ("", "NaT", "nan") for v in r.values())]


def term_editor():
    term, v = st.session_state.term, st.session_state.term_version
    name = st.text_input("Term name", term["name"], key=f"name{v}")
    left, right = st.columns(2)
    start = left.date_input("Start", term["start"], key=f"start{v}")
    end = right.date_input("End", term["end"], key=f"end{v}")
    st.caption("Breaks and holidays (no classes)")
    breaks = st.data_editor(
        [{"name": b["name"], "start": b["start"], "end": b["end"]} for b in term["breaks"]] or
        [{"name": None, "start": None, "end": None}],
        num_rows="dynamic", key=f"breaks{v}", width="stretch", hide_index=True,
        column_config={"name": "Break", "start": st.column_config.DateColumn("Start"),
                       "end": st.column_config.DateColumn("End")})
    st.caption("Meeting days per course, e.g. Mon/Wed/Fri. Filled in from the syllabus when found.")
    courses = st.data_editor(
        [{"course": c, "days": "/".join(d)} for c, d in term["courses"].items()] or [{"course": None, "days": None}],
        num_rows="dynamic", key=f"courses{v}", width="stretch", hide_index=True,
        column_config={"course": "Course", "days": "Meeting days"})
    try:
        edited = {
            "name": name, "start": start, "end": end,
            "breaks": [{"name": b["name"], "start": as_date(str(b["start"])[:10]), "end": as_date(str(b["end"])[:10])}
                       for b in records(breaks)],
            "courses": {c["course"].strip(): [day_name(d) for d in str(c["days"]).replace(",", "/").split("/") if d.strip()]
                        for c in records(courses)},
        }
        st.session_state.term = load_term(term_yaml(edited))  # same validation as the YAML file
    except Exception as error:
        st.error(f"Term config problem: {error}")


def load_demo_term():
    set_term(load_term((DEMO / "demo_term.yaml").read_text()))


def start_replay(path):
    record = json.loads(Path(path).read_text())
    set_term(load_term(record["term"]))
    st.session_state.replay = record


def learn_meeting_days(events):
    """Pre-fill meeting days the syllabi state for courses the term config doesn't list yet."""
    term = st.session_state.term
    known = {c.upper().replace(" ", "") for c in term["courses"]}
    found = {w["course"]: w["meeting_days"] for w in collect(events).values()
             if w["course"] and w["meeting_days"] and w["course"].upper().replace(" ", "") not in known}
    if found:
        set_term({**term, "courses": {**term["courses"], **found}})


# Rendering. The same functions draw a live run and a replayed recording.

def rejection(r):
    st.markdown(f"**{r['title']}** · p.{r['page']}  \n:red[{r['reason']}]  \n:gray[quoted: “{r['quote']}”]")


def worker_panel(w, result, events):
    title = w["course"] or w["file"]
    state = ":green[done]" if w["done"] and not w["errors"] else (":red[error]" if w["errors"] else ":gray[running]")
    st.markdown(f"**{title}** · {state}")
    st.caption(f"{w['file']} · worker {w['id']}")
    mine = [e for e in events if e.get("worker") == w["id"]]
    for e in mine:
        if e["type"] == "extracted":
            st.markdown(f"Found **{len(e['items'])}** items")
        elif e["type"] == "check" and not e["retry"]:
            passed = [r for r in e["results"] if r["ok"]]
            failed = [r for r in e["results"] if not r["ok"]]
            st.markdown(f"**{len(passed)}** quotes verified" + (f", :red[{len(failed)} failed]" if failed else ""))
            for r in failed[:SHOW_FAILURES]:
                rejection(r)
            if len(failed) > SHOW_FAILURES:
                with st.expander(f"{len(failed) - SHOW_FAILURES} more failed the check"):
                    for r in failed[SHOW_FAILURES:]:
                        rejection(r)
        elif e["type"] == "check":
            fixed = [r["title"] for r in e["results"] if r["ok"]]
            if fixed:
                st.markdown(f"Retry: **{len(fixed)}** fixed ({', '.join(fixed)})")
            for r in e["results"]:
                if not r["ok"]:
                    st.markdown(f"Retry: **{r['title']}** still fails, rejected  \n:red[{r['reason']}]")
        elif e["type"] == "dropped":
            titles = [w["results"][i]["title"] for i in e["ids"] if i in w["results"]]
            st.markdown("Withdrawn by the worker, rejected: " + ", ".join(f"**{t}**" for t in titles))
        elif e["type"] == "parsed":
            mine_cal = [i for i in result["calendar"] if i["worker"] == w["id"]]
            mine_rev = [i for i in result["review"] if i["worker"] == w["id"]]
            mine_dup = [i for i in result["duplicates"] if i["worker"] == w["id"]]
            st.markdown(f"**{len(mine_cal)}** dated · **{len(mine_rev)}** need review"
                        + (f" · {len(mine_dup)} duplicate merged" if mine_dup else ""))
        elif e["type"] == "lowered":
            st.caption("Answer was cut off by the free-tier token limit; retried at low reasoning")
        elif e["type"] == "error":
            st.error(e["message"][:300])
    if mine and mine[-1]["type"] == "waiting":
        st.caption(f"Rate limited by Groq, retrying in {mine[-1]['seconds']:.0f} s…")


def trace(events, term):
    result = build(events, term)
    workers = list(result["workers"].values())
    if workers:
        section("Workers", "One per syllabus, running in parallel. Every quote is checked against its page.")
        per_row = len(workers) if len(workers) <= 5 else 4  # five syllabi fit one row; more wrap in fours
        for row in range(0, len(workers), per_row):
            for column, w in zip(st.columns(per_row), workers[row:row + per_row]):
                with column, st.container(border=True):
                    worker_panel(w, result, events)
    return result


def when(item):
    text = f"{item['date']:%a %b} {item['date'].day}"
    return text + (f" → {item['end_date']:%a %b} {item['end_date'].day}" if item.get("end_date") else "")


def weight_text(item):
    if not item.get("weight"):
        return "–"
    return f"{'~' if item['weight_inferred'] else ''}{item['weight']:.3g}%"


def source_card(item):
    with st.container(border=True):
        st.markdown(f"**{item['course']} · {item['title']}** :gray[({item['type'].replace('_', ' ')})]")
        st.markdown(f"> “{item['quote']}”")
        st.caption(f"{item['file']} · page {item['page']}")
        lines = [f"Written as “{item['date_expr']}”"]
        if item.get("parsed_as"):
            lines.append(f"read as *{item['parsed_as']}*")
        if item.get("date"):
            lines.append(f"**{fmt(item['date'])}**" + (f" to **{fmt(item['end_date'])}**" if item.get("end_date") else ""))
        st.markdown(" → ".join(lines))
        if item.get("weight_note"):
            st.caption(f"Weight {weight_text(item)}: {item['weight_note']}" + (" (inferred)" if item["weight_inferred"] else ""))
        if item.get("reason") and item["status"] != "verified":
            st.markdown(f":red[{item['reason']}]")


def open_row(key):
    rows = st.session_state[f"{key}{st.session_state.get(key + '_v', 0)}"]["selection"]["rows"]
    if rows:
        st.session_state[key + "_open"] = rows[0]


def close_row(key):
    st.session_state.pop(key + "_open", None)
    st.session_state[key + "_v"] = st.session_state.get(key + "_v", 0) + 1  # a fresh table, nothing selected


def table(items, columns, key):
    """A table whose rows open their source card; the card has a button back to the full table."""
    opened = st.session_state.get(key + "_open")
    if opened is not None and opened < len(items):
        st.button(f"Back to all {len(items)}", key=key + "_back", icon=":material/arrow_back:",
                  on_click=close_row, args=(key,))
        source_card(items[opened])
        return
    rows = [{name: get(i) for name, get in columns.items()} for i in items]
    st.dataframe(rows, hide_index=True, width="stretch", on_select=lambda: open_row(key),
                 selection_mode="single-row", key=f"{key}{st.session_state.get(key + '_v', 0)}")
    if items:
        st.caption("Select a row to see its source quote.")


def outcome(result, stats):
    section("Results", "Built from verified items only.")
    repaired = sum(r["ok"] for w in result["workers"].values() for r in w["results"].values() if r.get("retried"))
    columns = st.columns(4)
    columns[0].metric("On calendar", len(result["calendar"]))
    columns[1].metric("Needs review", len(result["review"]))
    columns[2].metric("Rejected", len(result["rejected"]))
    columns[3].metric("Crunch weeks", len(result["crunch"]))
    st.caption(f"`{stats['model_calls']} model calls` · `{stats['seconds']:.0f} s` · `{repaired} fixed on retry` · "
               f"`{len(result['duplicates'])} duplicates merged`")
    if result["calendar"]:
        count = len(result["calendar"])
        st.download_button(f"Download {count} verified events for Google Calendar (.ics)",
                           calendar_file(result["calendar"]), "syllagent.ics", "text/calendar", type="primary",
                           icon=":material/download:")
        st.caption(f"The file holds only the {count} verified, dated items in the Calendar tab below. "
                   f"The {len(result['review'])} items in Needs review and {len(result['rejected'])} rejected items "
                   "are not in it. Each event is all-day, with its source quote and page in the description. "
                   "In Google Calendar: Settings → Import & export → Import. Apple Calendar and Outlook also open .ics files.")

    st.altair_chart(heatmap(result, st.session_state.term, theme_mode()), width="stretch", theme=None)
    if result["crunch"]:
        st.markdown("**Crunch weeks**")
        for column, w in zip(st.columns(len(result["crunch"])), result["crunch"]):
            with column, st.container(border=True):
                sunday = w["monday"] + timedelta(days=6)
                st.markdown(f"**Week {w['week']}** · {w['monday']:%b} {w['monday'].day} – {sunday:%b} {sunday.day}")
                st.markdown(w["summary"])
                st.caption(w["why"] + "  \n" + "  \n".join(
                    f"{i['course']} {i['title']} · {i['date']:%a} · {weight_text(i)}"
                    for i in w["items"]))

    tabs = st.tabs([f"Calendar ({len(result['calendar'])})", f"Needs review ({len(result['review'])})",
                    f"Rejected ({len(result['rejected'])})", f"Duplicates ({len(result['duplicates'])})"])
    with tabs[0]:
        table(result["calendar"], {
            "Date": when, "Week": lambda i: i["week"], "Course": lambda i: i["course"],
            "Type": lambda i: i["type"].replace("_", " "),
            "Title": lambda i: i["title"], "Weight": weight_text, "Source": lambda i: f"p.{i['page']}"}, "cal")
    with tabs[1]:
        st.caption("The quote checked out, but the date can't be pinned down. Not added to the calendar.")
        table(result["review"], {"Course": lambda i: i["course"], "Title": lambda i: i["title"],
                                 "Written as": lambda i: i["date_expr"], "Why": lambda i: i["reason"]}, "rev")
    with tabs[2]:
        st.caption("The quote could not be found on the cited page, even after one retry. Dropped.")
        table(result["rejected"], {"Course": lambda i: i["course"], "Title": lambda i: i["title"],
                                   "Written as": lambda i: i["date_expr"], "Why": lambda i: i["reason"]}, "rej")
    with tabs[3]:
        table(result["duplicates"], {"Course": lambda i: i["course"], "Title": lambda i: i["title"],
                                     "Date": when, "Merged into": lambda i: i["reason"]}, "dup")


VERDICTS = {"correct": "correct", "wrong date": "wrong date", "dated, but undatable": "date invented",
            "not in reference": "not in reference"}


def reference(files, term):
    """What to score against: the answer key for the demo syllabi, else a verified run on the same files."""
    key = answer_key(files)
    if key is not None:
        return "the hand-checked answer key", key
    runs = st.session_state.get("compare", {}).get(tuple(sorted(f["sha256"] for f in files)), {})
    if "verified" in runs:
        return "the verified pipeline's output", from_pipeline(build(runs["verified"]["events"], term))
    return None, None


def baseline_view(events, term, files, final):
    section("Baseline", "One prompt with every syllabus. No citation check, no date code.")
    raw = next((e["events"] for e in events if e["type"] == "baseline"), None)
    if raw is None:
        st.caption("Waiting for one big model call…")
        return
    calendar = baseline_calendar(events)
    effort = next((e.get("reasoning") for e in events if e["type"] == "baseline"), None)
    if effort and effort != config.REASONING_EFFORT:
        st.caption(f"Ran with {effort} reasoning effort (the pipeline uses {config.REASONING_EFFORT}): a single "
                   f"prompt this size only fits Groq's free-tier limit at {effort}.")
    label, ref = reference(files, term)
    verdicts = score(calendar, ref)[0] if ref else [""] * len(calendar)
    columns = st.columns(4)
    columns[0].metric("On calendar", len(calendar))
    columns[1].metric("Source text not in PDFs", sum(not i["source_found"] for i in calendar))
    if ref:
        columns[2].metric("Wrong dates", verdicts.count("wrong date"))
        columns[3].metric("Dates invented for TBA items", verdicts.count("dated, but undatable"))
        st.caption(f"Checked against {label}.")
    else:
        st.caption("Run the verified pipeline on the same PDFs to score these dates.")
    rows = [{"Date": when(i), "Course": i["course"], "Title": i["title"],
             "Weight": f"{i['weight_pct']:g}%" if i.get("weight_pct") else "–",
             "Source in PDF": "found" if i["source_found"] else "not found",
             "Check": VERDICTS.get(v, "")} for i, v in zip(calendar, verdicts)]
    st.dataframe(rows, hide_index=True, width="stretch", height=min(38 + 35 * len(rows), 600))
    if final and calendar:
        st.download_button("Download baseline .ics (unverified)", calendar_file(
            [{**i, "weight": i.get("weight_pct"), "weight_inferred": False, "quote": i["source"], "page": "?",
              "file": "(not checked)", "date_expr": i["date"].isoformat(), "type": i["type"]} for i in calendar]),
            "baseline.ics", "text/calendar")


def comparison(term):
    last = st.session_state.get("last")
    if not last:
        return
    runs = st.session_state.get("compare", {}).get(tuple(sorted(f["sha256"] for f in last["files"])), {})
    if len(runs) < 2:
        if last["mode"] == "verified":
            st.caption("Switch the mode to **Single-prompt baseline** and run the same PDFs to compare.")
        return
    label, ref = reference(last["files"], term)
    verified = build(runs["verified"]["events"], term)
    _, mine = score(verified["calendar"], ref)
    _, theirs = score(baseline_calendar(runs["baseline"]["events"]), ref)
    stats = {mode: next(e for e in run["events"] if e["type"] == "stats") for mode, run in runs.items()}
    unsourced = sum(not e["source_found"] for e in baseline_calendar(runs["baseline"]["events"]))
    self_reference = label.startswith("the verified")
    show = (lambda n: "—") if self_reference else (lambda n: n)
    rows = [
        ("Items on the calendar", mine["on_calendar"], theirs["on_calendar"]),
        ("Correct dates", show(mine["correct"]), theirs["correct"]),
        ("Wrong dates", show(mine["wrong_date"]), theirs["wrong_date"]),
        ("Dates invented for TBA / undatable items", show(mine["invented_date"]), theirs["invented_date"]),
        ("Source text not found in the PDFs", 0, unsourced),
        ("Extra items not in the reference", show(mine["not_in_reference"]), theirs["not_in_reference"]),
        ("Reference items missed", show(mine["missed"]), theirs["missed"]),
        ("Sent to Needs review instead of guessing", len(verified["review"]), 0),
        ("Model calls", stats["verified"]["model_calls"], stats["baseline"]["model_calls"]),
        ("Seconds", stats["verified"]["seconds"], stats["baseline"]["seconds"]),
    ]
    section("Same syllabi, both modes")
    st.table({"": [r[0] for r in rows], "Verified pipeline": [str(r[1]) for r in rows],
              "Single-prompt baseline": [str(r[2]) for r in rows]})
    st.caption(f"Scored against {label}. One run each; the baseline's mistakes vary from run to run.")


LIMITATIONS = [
    "**Recall depends on the model.** The check proves every calendar item is real (its quote is on its page); "
    "it can't prove nothing was missed. A rerun can drop a minor item, e.g. MATH 2250's weekly homework once.",
    "**A real quote can still be mislabeled.** TDPS's \"Oct. 12: Homework for the Live Event\" is a seminar "
    "title, not an assignment, but the quote is genuine, so it reached the calendar: the one extra item above.",
    "**Conservative by design.** A paraphrased date (\"weeks of Oct. 12\") is rejected, not fixed, and "
    "repeating items (\"every Wednesday\") go to Needs review rather than becoming weekly events.",
    "**Free-tier limits.** 8,000 tokens a minute: five syllabi take about 5 minutes, long PDFs are read in page "
    "batches, and the baseline can't take all five real syllabi in one prompt.",
    "**A small eval.** One verified run per set, ten syllabi, answer keys written by the builder. On real syllabi "
    "with absolute dates the baseline does about as well; the gap is on relative dates and on provenance.",
    "**Inputs.** No OCR (scanned PDFs are skipped), the term calendar is entered by hand, and weights marked ~ "
    "are inferred when a syllabus doesn't give one.",
]


@st.cache_data
def eval_tables():
    results = summary()
    return synthetic_table(results), real_table(results)


def evaluation():
    synthetic, real = eval_tables()
    section("Evaluation: verified pipeline vs. one prompt", "Recorded runs scored against hand-checked answer keys.")
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Synthetic syllabi** · relative dates like “Week 7 Thu” and “the day after Lecture 12”")
        st.table(synthetic)
    with right:
        st.markdown("**Real syllabi** · mostly absolute dates like “Tuesday Oct 13”")
        st.table(real)
    st.caption("Reproduce with `python -m syllabus_agent.evaluate` (no API calls). The baseline only fits Groq's "
               "free tier for two of the real syllabi at once, so it is compared on those two.")
    section("Limitations")
    st.markdown("\n".join(f"- {line}" for line in LIMITATIONS))


def render(events, term, final=True):
    for e in events:
        if e["type"] == "error" and e.get("worker") is None:
            st.error(e["message"])
    start = next((e for e in events if e["type"] == "start"), None)
    if start and start["mode"] == "baseline":
        baseline_view(events, term, start["files"], final)
        return None
    result = trace(events, term)
    stats = next((e for e in events if e["type"] == "stats"), None)
    if stats and final:
        outcome(result, stats)
    return result


def run_live(syllabi, term, mode):
    events, inbox = [], queue.Queue()

    def work():
        try:
            Run(syllabi, term, emit=inbox.put).run(mode)
        except Exception as error:
            inbox.put({"type": "error", "worker": None, "message": str(error)})

    # Workers run on background threads; only this thread draws the page.
    thread = threading.Thread(target=work)
    thread.start()
    area = st.empty()
    while thread.is_alive() or not inbox.empty():
        fresh = False
        while not inbox.empty():
            events.append(inbox.get())
            fresh = True
        if fresh:
            with area.container():
                render(events, term, final=False)
        time.sleep(0.25)
    area.empty()
    return events


def save(record):
    RUNS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    courses = "-".join(sorted({w["course"].replace(" ", "") for w in collect(record["events"]).values()
                               if w["course"]}))[:60] or f"{len(record['files'])}files"
    (RUNS / f"{stamp}-{record['mode']}-{courses}.json").write_text(json.dumps(record, indent=1, default=str))


def completed(record):
    kinds = {e["type"] for e in record["events"]}
    return "stats" in kinds and ("baseline" in kinds if record["mode"] == "baseline" else "parsed" in kinds)


def remember(record):
    st.session_state.last = record
    if completed(record):  # only finished runs go into the comparison
        key = tuple(sorted(f["sha256"] for f in record["files"]))
        st.session_state.setdefault("compare", {}).setdefault(key, {})[record["mode"]] = record


def recording_label(path):
    """20261017-225013-verified-CPSC2010-MATH1200 → Oct 17, 22:50 · verified · CPSC2010, MATH1200"""
    stamp, clock, mode, *courses = path.stem.split("-")
    when = datetime.strptime(stamp + clock, "%Y%m%d%H%M%S")
    return f"{when:%b} {when.day}, {when:%H:%M} · {mode} · {', '.join(courses)}"


def demo_recording(saved):
    """The recording with the most syllabi, newest first on ties: a live run on stage saves a new,
    smaller recording, and the landing button should still replay the full demo."""
    sizes = {path: len(json.loads(path.read_text())["files"]) for path in saved}
    return max(saved, key=lambda path: sizes[path]) if saved else None


def welcome(saved):
    demo = demo_recording(saved)
    with st.container(border=True):
        left, right = st.columns([3, 2], vertical_alignment="center")
        with left:
            st.markdown("#### Watch a real run")
            st.markdown("A recorded run over real syllabi, replayed step by step: no API key or network needed."
                        if saved else "No recordings yet. Every completed live run is saved here.")
            if demo:
                st.caption(recording_label(demo))
        right.button("Replay the demo", type="primary", icon=":material/play_arrow:", width="stretch",
                     disabled=not demo, on_click=start_replay, args=(demo,))
    st.caption("Or upload your own PDFs in the sidebar, set the term dates, and press **Run**.")


def uploaded_syllabi(files, use_demo):
    sources = [(p.name, p.read_bytes()) for p in sorted(DEMO.glob("*.pdf"))] if use_demo else \
              [(f.name, f.getvalue()) for f in files or []]
    if len(sources) > config.MAX_FILES:
        st.warning(f"Using the first {config.MAX_FILES} of {len(sources)} PDFs.")
    syllabi = []
    for name, data in sources[:config.MAX_FILES]:
        try:
            syllabi.append(read_pdf(name, data))
        except NoText as error:
            st.session_state.notes.append(str(error))
        except Exception as error:
            st.session_state.notes.append(f"Could not read {name}: {error}")
    return syllabi


saved = sorted(RUNS.glob("*.json"), reverse=True) if RUNS.exists() else []

with st.sidebar:
    st.markdown("#### Syllabi")
    files = st.file_uploader("Syllabus PDFs (1–8)", type="pdf", accept_multiple_files=True)
    use_demo = st.toggle("Use the 5 demo syllabi instead", help="Synthetic syllabi from tests/fixtures/syllabi")
    with st.expander("Term dates"):
        st.caption("Needed to turn dates like “Week 7 Thu” into real ones. Replays and the demo syllabi set "
                   "this for you.")
        st.button("Load demo term", on_click=load_demo_term, width="stretch")
        term_editor()
    st.markdown("#### Run")
    mode_label = st.radio("Mode", list(MODES))
    start = st.button("Run", type="primary", width="stretch")
    st.caption(f"Model: {config.MODEL} via {config.BASE_URL.split('/')[2]}")
    st.markdown("#### Recorded runs")
    chosen = st.selectbox("Recording", saved, format_func=recording_label, label_visibility="collapsed")
    st.button("Replay recording", disabled=not saved, width="stretch",
              on_click=start_replay, args=(chosen,))
    st.caption("Every live run is saved, so a real run can be replayed with no network.")

term = st.session_state.term
masthead()
idle = not start and "replay" not in st.session_state and "last" not in st.session_state
if idle:
    welcome(saved)

if start:
    if not config.api_key():
        st.error(f"Add {config.API_KEY_ENV} to .env.")
        st.stop()
    if "PLACEHOLDER" in term["name"]:
        if not use_demo:
            st.error("Set the term's start, end and breaks under **Term dates** in the sidebar first.")
            st.stop()
        load_demo_term()  # the demo syllabi are written for the demo term
        term = st.session_state.term
    st.session_state.notes = []
    syllabi = uploaded_syllabi(files, use_demo)
    if not syllabi:
        st.error("Upload at least one syllabus PDF with selectable text.")
        st.stop()
    mode = MODES[mode_label]
    events = run_live(syllabi, term, mode)
    record = {"mode": mode, "model": config.MODEL, "created": datetime.now().isoformat(timespec="seconds"),
              "term": term_yaml(term), "files": [{"name": s["name"], "sha256": s["sha256"], "pages": len(s["pages"])}
                                                 for s in syllabi], "events": events}
    if completed(record):  # a failed run is no use as an on-stage backup
        save(record)
    remember(record)
    learn_meeting_days(events)
    st.rerun()
elif "replay" in st.session_state:
    record = st.session_state.pop("replay")
    created = datetime.fromisoformat(record["created"])
    st.caption(f"Replaying a recorded {record['mode']} run from {created:%b} {created.day}, {created:%H:%M} · "
               f"{record['model']}")
    area = st.empty()
    speed = float(os.getenv("SYLLABUS_REPLAY_SPEED", "1"))  # 0 replays instantly (tests)
    pace = {"waiting": 0.05, "worker": 0.1, "extracted": 0.5, "check": 0.7, "parsed": 0.5, "baseline": 1.5}
    for n in range(1, len(record["events"]) + 1):
        with area.container():
            render(record["events"][:n], term, final=False)
        time.sleep(pace.get(record["events"][n - 1]["type"], 0.2) * speed)
    area.empty()
    remember(record)

for note in st.session_state.get("notes", []):
    st.warning(note)
if "last" in st.session_state:
    render(st.session_state.last["events"], term)
    comparison(term)
evaluation()
