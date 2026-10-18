# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```sh
source .venv/bin/activate                     # Python venv; deps in requirements.txt
streamlit run app.py                          # the app (.claude/launch.json uses --server.port 8503)
python -m unittest discover -s tests -v       # all tests: no API key, no network
python -m unittest tests.test_syllabus_agent.PipelineTests -v                    # one class
python -m unittest tests.test_syllabus_agent.CitationTests.test_normalize -v     # one test
python -m syllabus_agent.smoke                # live check of key/model/provider
python tests/fixtures/make_syllabi.py         # regenerate fixture PDFs, demo_term.yaml, answer_key.json
```

The theme (fonts, light/dark colors) is in `.streamlit/config.toml`; page-level CSS is in `page.style()`. There is no linter or build step. After editing a module that `page.py` imports, restart the Streamlit server; it does not reliably reload imported modules.

## What this is

A local Streamlit demo ("Syllabus Agent"): upload syllabus PDFs → extract every graded item with a verbatim quote → verify quotes in plain Python → resolve dates → crunch-week heatmap + `.ics` export. A "single-prompt baseline" mode exists only to be compared against the verified pipeline. Demo value comes first; if a design decision would change what the demo shows, ask the user rather than guessing.

## Architecture

The pipeline is an **event stream**. `agents.Run(syllabi, term, emit=...)` runs workers in parallel (one per PDF, at most `MAX_CALLS_PER_WORKER` model calls each, plus extra extraction calls when `Run.batches` splits a long PDF under the free-tier cap) and emits plain dict events (`start`, `worker`, `extracted`, `check`, `dropped`, `parsed`, `waiting`, `error`, `baseline`, `stats`, `done`). Everything downstream is a pure function of that event list:

- `load.build(events, term)` → calendar / needs-review / rejected / duplicates / weekly totals / crunch weeks. It calls `term.resolve` for dates and `infer_weights` for weights.
- `page.py` renders the live trace from the same events. It also saves completed runs as JSON in `syllabus_agent/runs/` and replays them by re-emitting the events (`SYLLABUS_REPLAY_SPEED=0` makes replay instant; tests use this).
- `compare.py` scores a calendar against `tests/fixtures/syllabi/answer_key.json`, matched by PDF sha256. For non-demo PDFs it scores against the verified run instead.

Changing an event's shape therefore affects `load.py`, `page.py`, `compare.py`, the saved recordings (`runs/` and `tests/fixtures/demo_run.json`), and the tests.

Key division of labor:
- **The model never computes dates.** It labels each `date_expr` as a spec (absolute, week_weekday, nth_meeting, range, unresolvable); `term.py` does all date arithmetic from the term calendar (weeks numbered from term start and not renumbered by breaks, class meetings skip breaks, year rollover). Anything unresolvable raises `term.Unresolved` and goes to Needs review, never onto the calendar or `.ics`.
- **Citation check is plain Python** (`citations.py`): normalized quote must be on the cited page and must contain the date_expr. One repair call with the failure reason, then the item is dropped (still shown in the UI as rejected).
- **Prompts and strict JSON schemas** live at the top of `agents.py`. Groq validates the schema after generation, so a null in a non-nullable field fails the call; fields that may be absent must use `nullable(...)`. `Run.call` retries once on `json_validate_failed`.

## Provider and limits (`syllabus_agent/config.py`)

- Groq via the OpenAI SDK **Responses API**: `BASE_URL=https://api.groq.com/openai/v1`, model `openai/gpt-oss-120b` (override with `SYLLABUS_MODEL`). Don't guess other model names.
- Key: `GROQ_API_KEY` in `.env`; `GROK_API_KEY` is also accepted (the user's `.env` uses it). It's a Groq key (`gsk_`), not xAI Grok. Never print the key or commit `.env`, and don't edit the user's `.env`.
- Free tier: `TOKENS_PER_MINUTE=8000`. Groq counts input + `max_output_tokens` against it, so `Run.output_budget` sizes the output to fit, and `Run.call` waits out 429s with visible `waiting` events. Because of this cap the baseline runs at low reasoning effort (labeled in the UI). Setting `TOKENS_PER_MINUTE = None` (paid tier) removes both.
- Groq's default output cap (~3K tokens) truncates; `MAX_OUTPUT_TOKENS` must be set explicitly.

## Tests

`tests/test_syllabus_agent.py` runs the real fixture PDFs through a scripted fake model client, and uses Streamlit `AppTest` for the page (missing key, replay, comparison). Fixtures are synthetic: five PDFs, a fictional `demo_term.yaml`, and a hand-checked `answer_key.json` keyed by PDF sha256. Regenerating the PDFs changes their hashes, so the answer key and `tests/fixtures/demo_run.json` (a recorded run over them, used by the comparison test) must stay consistent with them. `syllabus_agent/runs/` holds only the demo recording the app offers (a real run over five real syllabi; the PDFs themselves are gitignored); the replay test uses whatever recording is newest there.

## Project rules (from the original spec)

- Never hardcode real university calendar dates. `syllabus_agent/term.yaml` holds placeholders (2099); the demo term is fictional.
- No OCR (scanned PDFs raise `pdfs.NoText` and are skipped), no Canvas/Gmail/Google Calendar APIs, no accounts, database or deployment.
- Plain Python + Streamlit; no agent framework.
