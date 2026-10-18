# Syllabus Agent

Upload course syllabi (PDFs). It finds every deadline, exam and graded item, proves each one against the PDF text, works out dates like "Week 7 Thursday" or "two days after Lecture 8", shows which weeks are crunch weeks, and exports an `.ics` file.

Plain Python and Streamlit, with model calls through the OpenAI SDK's Responses API. There's no agent framework.

## Run it

You need Python 3.10 or newer.

**1. Install (once)**

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

**2. Add `GROQ_API_KEY` to `.env`.** Get one at [console.groq.com](https://console.groq.com/keys); it starts with `gsk_`. Groq (with a q) is not xAI's Grok. Never commit `.env`.

**3. Start the app**

```sh
streamlit run app.py
```

Open the URL Streamlit prints. Next time, run only `source .venv/bin/activate` and step 3.

The model is `openai/gpt-oss-120b` on Groq. To switch providers, change `BASE_URL`, `MODEL` and `API_KEY_ENV` in `syllabus_agent/config.py`; for xAI Grok that's `https://api.x.ai/v1` and `XAI_API_KEY`. Check the connection with `python -m syllabus_agent.smoke`.

## How it works

| Step | Pattern | What happens |
| --- | --- | --- |
| 1 · Extract | Orchestrator–workers, parallel | One worker per syllabus, each with its own context. It returns items with the date exactly as written, a verbatim quote and a page number. At most 3 model calls per worker, except that on Groq's free tier a long syllabus is read in batches of pages so each call has room to answer. |
| 2 · Citation check | Evaluator | Plain Python normalizes the PDF text and the quote (hyphenated line breaks, ligatures, smart quotes) and checks that the quote is on the cited page and contains the date. A failure goes back to the worker once, with the reason. Then it's dropped. |
| 3 · Dates | Model parses, code computes | The model only labels each date: absolute, week + weekday, nth class meeting, a range, or unresolvable. `term.py` does the arithmetic from the term calendar: weeks start at the term start, class meetings skip breaks, and dates without a year get the right one across New Year. Anything it can't pin down goes to **Needs review** instead of the calendar. |
| 4 · Load | | Weights come from the syllabus or are inferred from the grading breakdown ("30%, 6 sets, lowest dropped" → 6% each). Weekly totals feed the heatmap. The 3 heaviest weeks, and any week with 2+ exams, are crunch weeks. |

**Term calendar:** `syllabus_agent/term.yaml` holds placeholder dates. Fill it in from your school's official calendar, or edit it in the sidebar. **Load demo term** loads the fictional term that matches the demo syllabi.

**Groq free tier:** it allows 8,000 tokens per minute. A live run on all five demo syllabi takes about 2 minutes, mostly waiting, and the trace shows each wait. The baseline only fits at low reasoning effort, and the page says so. After upgrading to a paid tier, set `TOKENS_PER_MINUTE = None` in `config.py`.

## 90-second demo script

Before going on stage: open the app, click **Load demo term**, and check that **Replay recording** works offline.

1. **Upload syllabi (10 s).** Drag the five PDFs from `tests/fixtures/syllabi/` into the sidebar (or toggle *Use the 5 demo syllabi*) and click **Run**. If the network is slow, use **Replay recording** instead. It's a real run, played back.
2. **Workers and a rejected citation (25 s).** Five workers run side by side. Point at a red ❌: the model glued a table header onto a row and "quoted" text that isn't in the PDF. The check shows the closest real text, the worker gets one retry, and it comes back ✅. Nothing reaches the calendar without a quote that's really on its page.
3. **Crunch weeks (15 s).** Scroll to the heatmap. Week 7 lights up: three midterms, a paper and two problem sets in one week, 96% of a course grade. The cards underneath list what's due.
4. **Source quote (10 s).** Click a calendar row, e.g. CPSC 223 Problem Set 2. The card shows the quote, the page, "two days after Lecture 8" → *meeting 8 +2 days* → **Sat Oct 10**, and how its weight was inferred.
5. **Import the .ics (15 s).** Click **Download .ics**, then in Google Calendar go to Settings → Import & export → Import. Each event's description carries its quote and page. Needs-review items (TBA, "announced in class") stay off the calendar.
6. **Baseline (15 s).** Switch the mode to **Single-prompt baseline** and run (or replay its recording). One prompt, no checks: in the recorded run it got 11 dates wrong (every one a "Week N" or "Lecture N" date, e.g. a midterm placed during fall break) and missed 4 items, and 4 of its "sources" aren't in the PDFs. The comparison table puts the two side by side, scored against a hand-checked answer key.

**Read the results carefully:** the check proves a quote is on the page, not that the model labeled it correctly. The answer key exists only for the demo syllabi. For your own PDFs, the baseline is scored against the verified pipeline, which shows disagreement, not ground truth.

## Project layout

```text
app.py                  starts the app
syllabus_agent/
  config.py             provider, model, key name, token limits, default weights
  pdfs.py               text per page; scanned PDFs are skipped
  agents.py             extractor workers, repair, date parsing, baseline
  citations.py          the citation check (plain Python)
  term.py               term calendar and all date arithmetic
  load.py               resolve, dedupe, infer weights, crunch weeks
  charts.py, export.py  heatmap and .ics
  compare.py            scores a run against the answer key
  page.py               live trace, results, replay, comparison
  term.yaml             placeholder term: fill in from your school's calendar
  runs/                 saved real runs you can replay
tests/
  test_syllabus_agent.py
  fixtures/             synthetic syllabi, demo term and answer key (make_syllabi.py)
```

## Tests

```sh
python -m unittest discover -s tests -v
```

The tests run the real fixture PDFs through a scripted fake model, so they cost nothing and need no API key. Rebuild the fixtures with `python tests/fixtures/make_syllabi.py`.

## Links

[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) · [Groq Responses API](https://console.groq.com/docs/responses-api) · [iCalendar (RFC 5545)](https://datatracker.ietf.org/doc/html/rfc5545)
