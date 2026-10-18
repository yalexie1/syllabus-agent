"""The term calendar and every piece of date arithmetic. No model, no guessing.

Week 1 is the Monday-to-Sunday week that contains the term start; breaks don't renumber weeks.
Class meetings are counted from the term start on the course's meeting days, skipping breaks.
"""

import re
from datetime import date, timedelta

import yaml

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Unresolved(ValueError):
    """The date can't be pinned down from the syllabus and the term. It goes to Needs review."""


def as_date(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def load_term(text):
    raw = yaml.safe_load(text) or {}
    term = {
        "name": raw.get("name", "Term"),
        "start": as_date(raw["start"]),
        "end": as_date(raw["end"]),
        "breaks": [{"name": b.get("name", "Break"), "start": as_date(b["start"]), "end": as_date(b["end"])}
                   for b in raw.get("breaks") or []],
        "courses": {code: [day_name(d) for d in days] for code, days in (raw.get("courses") or {}).items()},
    }
    if term["end"] < term["start"]:
        raise ValueError("The term ends before it starts.")
    return term


def term_yaml(term):
    plain = {
        "name": term["name"], "start": term["start"].isoformat(), "end": term["end"].isoformat(),
        "breaks": [{"name": b["name"], "start": b["start"].isoformat(), "end": b["end"].isoformat()}
                   for b in term["breaks"]],
        "courses": term["courses"],
    }
    return yaml.safe_dump(plain, sort_keys=False, allow_unicode=True)


def day_name(text):
    key = str(text).strip()[:3].title()
    if key not in WEEKDAYS:
        raise ValueError(f"Unknown weekday {text!r}")
    return key


def course_key(code):
    return re.sub(r"[^A-Z0-9]", "", str(code).upper())


def meeting_days(term, course, found=()):
    """Days from the term config win; otherwise the days the syllabus states."""
    for code, days in term["courses"].items():
        if course_key(code) == course_key(course) and days:
            return days
    return list(found)


def break_on(term, day):
    return next((b["name"] for b in term["breaks"] if b["start"] <= day <= b["end"]), None)


def monday(day):
    return day - timedelta(days=day.weekday())


def week_of(term, day):
    return (monday(day) - monday(term["start"])).days // 7 + 1


def week_monday(term, week):
    return monday(term["start"]) + timedelta(weeks=week - 1)


def meetings(term, days):
    """Every class meeting in the term, in order."""
    wanted = {WEEKDAYS.index(d) for d in days}
    day, found = term["start"], []
    while day <= term["end"]:
        if day.weekday() in wanted and not break_on(term, day):
            found.append(day)
        day += timedelta(days=1)
    return found


def fmt(day):
    return f"{day:%a %b} {day.day}, {day.year}"


def point(spec, term, days):
    kind = spec.get("kind")
    if kind == "absolute":
        month, day = spec.get("month"), spec.get("day")
        if not month or not day:
            raise Unresolved("month or day missing")
        # No year in a syllabus: take the term year that puts the date inside the term.
        candidates = []
        for year in sorted({term["start"].year, term["end"].year}):
            try:
                candidates.append(date(year, month, day))
            except ValueError:
                raise Unresolved(f"{month}/{day} is not a real date") from None
        inside = [d for d in candidates if term["start"] <= d <= term["end"]]
        if len(inside) > 1:
            raise Unresolved(f"{month}/{day} occurs twice in this term")
        if not inside:
            raise Unresolved(f"{candidates[0]:%b} {day} is outside the term ({fmt(term['start'])} to {fmt(term['end'])})")
        # "Thurs. Dec. 15" when Dec 15 is a Tuesday: the syllabus contradicts itself, so a person decides.
        if spec.get("weekday") in WEEKDAYS and WEEKDAYS[inside[0].weekday()] != spec["weekday"]:
            raise Unresolved(f"the syllabus says {spec['weekday']}, but {fmt(inside[0])} is a {inside[0]:%A}")
        return inside[0]
    if kind == "week_weekday":
        week, weekday = spec.get("week"), spec.get("weekday")
        if not week or week < 1 or weekday not in WEEKDAYS:
            raise Unresolved("week number or weekday missing")
        return week_monday(term, week) + timedelta(days=WEEKDAYS.index(weekday))
    if kind == "nth_meeting":
        n = spec.get("n")
        if not n or n < 1:
            raise Unresolved("meeting number missing")
        if not days:
            raise Unresolved("meeting days unknown for this course; add them in the sidebar")
        held = meetings(term, days)
        if n > len(held):
            raise Unresolved(f"the term has only {len(held)} {'/'.join(days)} meetings, not {n}")
        return held[n - 1] + timedelta(days=spec.get("offset_days") or 0)
    raise Unresolved(spec.get("reason") or "no date given")


def check_in_term(term, day, what="date"):
    if not term["start"] <= day <= term["end"]:
        raise Unresolved(f"{what} {fmt(day)} is outside the term")
    if name := break_on(term, day):
        raise Unresolved(f"{what} {fmt(day)} falls in {name}")


def resolve(spec, term, days=()):
    """A parsed date expression → (start, end). end is None for a single day. Raises Unresolved."""
    if spec.get("kind") == "range":
        start_spec, end_spec = spec.get("start") or {}, dict(spec.get("end") or {})
        # "Nov 3-5": the end may come back without a month.
        if end_spec.get("kind") == "absolute" and not end_spec.get("month"):
            end_spec["month"] = start_spec.get("month")
        start, end = point(start_spec, term, days), point(end_spec, term, days)
        if end < start:
            raise Unresolved(f"window ends ({fmt(end)}) before it starts ({fmt(start)})")
        check_in_term(term, start, "start")
        if end > term["end"]:  # a window may span a break, but it must end inside the term
            raise Unresolved(f"end {fmt(end)} is outside the term")
        return start, (end if end != start else None)
    day = point(spec, term, days)
    check_in_term(term, day)
    return day, None


def describe(spec):
    """How the model read a date expression, in a few words."""
    kind = spec.get("kind")
    if kind == "absolute":
        return f"month {spec.get('month')}, day {spec.get('day')}"
    if kind == "week_weekday":
        return f"Week {spec.get('week')} {spec.get('weekday')}"
    if kind == "nth_meeting":
        offset = spec.get("offset_days") or 0
        return f"meeting {spec.get('n')}" + (f" {offset:+d} days" if offset else "")
    if kind == "range":
        return f"{describe(spec.get('start') or {})} → {describe(spec.get('end') or {})}"
    return f"unresolvable: {spec.get('reason') or '?'}"
