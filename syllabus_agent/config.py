"""Provider and tuning settings. Switching model providers is a change in this file only.

Groq (groq.com) speaks the OpenAI API, so the openai SDK works with a different base URL.
To use xAI Grok instead: BASE_URL = "https://api.x.ai/v1", API_KEY_ENV = "XAI_API_KEY",
and a model name from xAI's docs.
"""

import os

from openai import OpenAI

BASE_URL = "https://api.groq.com/openai/v1"
MODEL = os.getenv("SYLLABUS_MODEL", "openai/gpt-oss-120b")
API_KEY_ENV = "GROQ_API_KEY"
ALSO_ACCEPT = ["GROK_API_KEY"]  # a common mix-up between Groq and Grok

REASONING_EFFORT = "medium"  # gpt-oss reasons before answering; "low" is faster but missed TBA items in testing

# Groq's Responses API defaults to ~3k output tokens, reasoning included; long lists get cut off.
MAX_OUTPUT_TOKENS = 16000
# Groq's free tier allows 8,000 tokens per minute and refuses any request whose input plus
# max_output_tokens is larger. Set to None after upgrading (console.groq.com → Settings → Billing).
TOKENS_PER_MINUTE = 8000
# The baseline sends every syllabus at once; under the free-tier cap only "low" reasoning fits.
BASELINE_REASONING_EFFORT = "low" if TOKENS_PER_MINUTE else REASONING_EFFORT

MAX_FILES = 8
MAX_CALLS_PER_WORKER = 3  # extract, one repair, resolve (a long syllabus under the free-tier cap extracts in batches)

# Used when neither the item nor the grading breakdown gives a weight (percent of the course grade).
DEFAULT_WEIGHTS = {
    "exam": 20, "quiz": 2, "problem_set": 4, "paper": 10,
    "project": 15, "presentation": 5, "reading": 0, "other": 2,
}
ITEM_TYPES = list(DEFAULT_WEIGHTS)


def api_key():
    return next((os.getenv(name) for name in [API_KEY_ENV, *ALSO_ACCEPT] if os.getenv(name)), None)


def client():
    return OpenAI(base_url=BASE_URL, api_key=api_key(), max_retries=0, timeout=120)
