"""Calendar files. Only verified, dated items are exported; Needs review stays out."""

import hashlib
from datetime import datetime, timedelta, timezone

from icalendar import Calendar, Event


def summary(item):
    weight = f" ({'~' if item.get('weight_inferred') else ''}{item['weight']:g}%)" if item.get("weight") else ""
    return f"[{item['course']}] {item['title']}{weight}"


def description(item):
    lines = [f"“{item['quote']}”", f"Source: {item['file']}, page {item['page']}",
             f"Written as: {item['date_expr']}"]
    if item.get("weight_note"):
        lines.append(f"Weight: {item['weight_note']}" + (" (inferred)" if item.get("weight_inferred") else ""))
    return "\n".join(lines)


def calendar_file(items, name="Semester deadlines"):
    """All-day events. DTEND is exclusive in iCalendar, so a one-day event ends the next day."""
    cal = Calendar()
    cal.add("prodid", "-//y/cs Catalyst//Syllagent//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", name)
    stamp = datetime.now(timezone.utc)
    for item in items:
        event = Event()
        key = f"{item['course']}|{item['type']}|{item['title']}|{item['date']}"
        event.add("uid", hashlib.sha1(key.encode()).hexdigest()[:16] + "@syllabus-agent")
        event.add("dtstamp", stamp)
        event.add("summary", summary(item))
        event.add("dtstart", item["date"])
        event.add("dtend", (item.get("end_date") or item["date"]) + timedelta(days=1))
        event.add("description", description(item))
        event.add("categories", [item["type"].replace("_", " ")])
        event.add("transp", "TRANSPARENT")  # a deadline doesn't make you busy all day
        cal.add_component(event)
    return cal.to_ical()
