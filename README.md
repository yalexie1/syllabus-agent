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

The app ships with one recording: a real verified run over five real Fall 2026 syllabi (CPSC 2010, MATH 1200, MATH 2250, MATH 2410, TDPS 0001). Replaying it needs no API key or network. Before going on stage, open the app and check that **Replay the demo** plays.

1. **Replay (10 s).** Click **Replay the demo** on the landing page. The term calendar the run used loads with it.
2. **Workers and a rejected citation (25 s).** Five workers run side by side, one per syllabus. Point at MATH 2410's red ❌: the model wrote "weeks of Oct. 12", but the syllabus says "the weeks of Sept. 28, Oct. 12, and Nov. 30". That date isn't in the text, so the check rejects it, the worker gets one retry, and the item is dropped. Nothing reaches the calendar without a quote that's really on its page.
3. **Needs review (10 s).** Open the *Needs review* tab. TDPS 0001 says "Thurs. Dec. 15", but Dec 15, 2026 is a Tuesday: the syllabus contradicts itself, so a person decides. TBD finals and "every Wednesday" homework land here too, not on the calendar.
4. **Crunch weeks (15 s).** Scroll to the heatmap. Week 11 (Nov 9–15) lights up: two midterms in different math courses plus a response paper, 44% of a course grade. The cards underneath list what's due.
5. **Source quote (10 s).** Click the MATH 1200 *Midterm Exam 1* row. That PDF's text lost its spaces ("MidtermExam1isscheduledforThursday, October1"), and the quote still checks out on page 4; the date is computed by code as **Thu Oct 1**.
6. **Import the .ics (15 s).** Click **Download .ics**, then in Google Calendar go to Settings → Import & export → Import. Each event's description carries its quote and page.
7. **Baseline (optional, live, about 4 minutes).** Toggle *Use the 5 demo syllabi*, click **Load demo term**, and run both modes. The single prompt has no checks; on these synthetic syllabi it typically misplaces "Week N" and "Lecture N" dates (a midterm during fall break) and cites text that isn't in the PDFs. The comparison table scores both against a hand-checked answer key. The baseline can't run on the five real syllabi on Groq's free tier: one prompt with all of them is over the per-minute token limit.

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
  runs/                 the recorded demo run (every completed live run is saved here)
tests/
  test_syllabus_agent.py
  fixtures/             synthetic syllabi, demo term, answer key (make_syllabi.py), a recorded run for tests
```

## Tests

```sh
python -m unittest discover -s tests -v
```

The tests run the real fixture PDFs through a scripted fake model, so they cost nothing and need no API key. Rebuild the fixtures with `python tests/fixtures/make_syllabi.py`.

## Links

[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) · [Groq Responses API](https://console.groq.com/docs/responses-api) · [iCalendar (RFC 5545)](https://datatracker.ietf.org/doc/html/rfc5545)
