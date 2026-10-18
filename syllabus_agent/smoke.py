"""One live structured-output call, to check the provider before anything else.

Run: python -m syllabus_agent.smoke
"""

import json
from pathlib import Path

from dotenv import load_dotenv

from . import config
from .agents import RESOLVER, RESOLVE_FORMAT


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if not config.api_key():
        raise SystemExit(f"Add {config.API_KEY_ENV} to .env")
    sample = [{"id": "a", "date_expr": "Week 7 Thursday", "quote": "Midterm 1 is on Week 7 Thursday"},
              {"id": "b", "date_expr": "Nov 3-5", "quote": "take-home midterm window Nov 3-5"},
              {"id": "c", "date_expr": "TBA", "quote": "Presentations are scheduled TBA"}]
    response = config.client().responses.create(
        model=config.MODEL, store=False, instructions=RESOLVER,
        input=[{"role": "user", "content": json.dumps(sample)},
               {"role": "assistant", "content": "{\"dates\": []}"},
               {"role": "user", "content": "That was empty. Convert all three."}],
        text={"format": RESOLVE_FORMAT})
    print(f"{config.BASE_URL} · {config.MODEL}")
    print(json.dumps(json.loads(response.output_text), indent=1))


if __name__ == "__main__":
    main()
