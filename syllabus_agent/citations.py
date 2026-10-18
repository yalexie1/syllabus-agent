"""The citation check. Plain code, no model: is the quote really on the cited page?"""

import re
import unicodedata
from difflib import SequenceMatcher

MAX_QUOTE_WORDS = 40
CHARACTERS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "′": "'", "`": "'", "´": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ", "­": "",
})


def normalize(text):
    """Make PDF text and model quotes comparable.

    NFKC turns ligatures like "ﬁ" into "fi". Hyphens between letters are removed everywhere,
    so "ex-\\namination", "examination" and "take-home"/"takehome" all compare equal.
    """
    text = unicodedata.normalize("NFKC", text or "").translate(CHARACTERS)
    text = re.sub(r"([A-Za-z])-\s+([a-z])", r"\1\2", text)  # "Novem-\nber" or "Novem- ber"
    text = re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z])", "", text)
    text = re.sub(r"\s*-\s*", "-", text)
    return " ".join(text.split()).lower().strip(" '\".,;:")


def contains(text, quote):
    """Exact match, or the same characters with spaces ignored: some PDFs drop the spaces inside a line
    but keep a line break, so "ashorter\nassignment" never matches a quote copied as "ashorterassignment"."""
    return quote in text or quote.replace(" ", "") in text.replace(" ", "")


def closest(quote, page):
    """The run of page words that looks most like the quote, to show why a check failed."""
    words, size = page.split(), max(len(quote.split()), 1)
    best, best_score = "", 0.0
    for start in range(0, max(len(words) - size + 1, 1)):
        window = " ".join(words[start:start + size])
        score = SequenceMatcher(None, quote, window).ratio()
        if score > best_score:
            best, best_score = window, score
    return best


def check_item(item, pages):
    """Pass only if the normalized quote is on the cited page and contains the date expression."""
    page, quote, when = item.get("page"), normalize(item.get("quote")), normalize(item.get("date_expr"))
    if not isinstance(page, int) or not 1 <= page <= len(pages):
        return False, f"page {page} does not exist (the PDF has {len(pages)})"
    if not quote:
        return False, "no quote given"
    if len(quote.split()) > MAX_QUOTE_WORDS:
        return False, f"quote is {len(quote.split())} words; use at most {MAX_QUOTE_WORDS}"
    text = normalize(pages[page - 1])
    if not contains(text, quote):
        elsewhere = [n for n, other in enumerate(pages, 1) if n != page and contains(normalize(other), quote)]
        if elsewhere:
            return False, f"quote is on page {elsewhere[0]}, not page {page}"
        return False, f"not on page {page}. Closest text: \"{closest(quote, text)}\""
    if not when:
        return False, "no date expression given"
    if when.replace(" ", "") not in quote.replace(" ", ""):  # PDFs often drop spaces: "October1"
        return False, f"date \"{item.get('date_expr')}\" is not inside the quote"
    return True, "quote found on the cited page"


def found_anywhere(quote, pages):
    """Used to score the baseline, which gives no page numbers."""
    quote = normalize(quote)
    return bool(quote) and any(contains(normalize(page), quote) for page in pages)
