"""The term heatmap: weeks across, graded weight as a green → red diverging color."""

from datetime import timedelta

import altair as alt

# Diverging: the lightest week is dark green, the middle is pale, the heaviest is dark red, so darkness is
# distance from an ordinary week. Each chart is normalized to its own min–max of non-empty cells.
RAMP = ["#14592e", "#5aa86a", "#eee6c8", "#e8745f", "#9c1b1f"]
EMPTY = {"light": "#e9e1d1", "dark": "#26201a"}  # the theme's secondary background
INK = {"light": "#1d1915", "dark": "#eee6d7"}
MUTED = "#8a7f70"


def week_label(w):
    return f"W{w['week']} · {w['monday']:%b} {w['monday'].day}"


def rows(result, term):
    weeks = result["weeks"]
    breaks = {w["week"]: b["name"] for w in weeks for b in term["breaks"]
              if b["start"] <= w["monday"] + timedelta(days=4) and b["end"] >= w["monday"]}
    courses = sorted({i["course"] for i in result["calendar"]})
    total, grid = [], []
    for w in weeks:
        label = week_label(w)
        sunday = w["monday"] + timedelta(days=6)
        span = f"{w['monday']:%b} {w['monday'].day} – {sunday:%b} {sunday.day}"
        note = breaks.get(w["week"], "")
        total.append({"week": label, "order": w["week"], "total": w["total"], "span": span,
                      "summary": w["summary"] or "nothing due", "crunch": w["crunch"], "why": w["why"],
                      "label": f"{w['total']:g}" if w["total"] else ("break" if note else ""), "break": note})
        for course in courses:
            items = [i for i in w["items"] if i["course"] == course]
            grid.append({"week": label, "order": w["week"], "course": course, "span": span,
                         "weight": round(sum(i["weight"] for i in items), 1),
                         "items": "; ".join(f"{i['title']} ({'~' if i['weight_inferred'] else ''}{i['weight']:g}%)"
                                            for i in items) or "nothing due"})
    return total, grid


def bounds(values):
    nonzero = [v for v in values if v] or [1]
    return min(nonzero), max(nonzero)


def position(value, lo, hi):
    """Where a value sits on the ramp, 0 (lightest week) to 1 (heaviest); 0.5 when all are equal."""
    return (value - lo) / (hi - lo) if hi > lo else 0.5


def scale(values):
    lo, hi = bounds(values)
    if hi == lo:  # one distinct value: center it on the pale midpoint
        lo, hi = lo - 1, hi + 1
    domain = [lo + (hi - lo) * n / (len(RAMP) - 1) for n in range(len(RAMP))]
    return alt.Scale(domain=domain, range=RAMP, interpolate="lab")


def heatmap(result, term, mode="light"):
    total, grid = rows(result, term)
    lo, hi = bounds([t["total"] for t in total])
    for t in total:  # label ink: muted on empty weeks, white on the dark ends of the ramp, dark on the pale middle
        t["ink"] = "muted" if not t["total"] else ("deep" if abs(position(t["total"], lo, hi) - 0.5) > 0.3 else "pale")
    order = [t["week"] for t in total]
    x = alt.X("week:N", sort=order, title=None,
              axis=alt.Axis(labelAngle=-45, labelFontSize=11, ticks=False, domain=False))
    ink = INK[mode]

    strip_base = alt.Chart(alt.Data(values=total)).encode(x=x)
    strip = strip_base.mark_rect(cornerRadius=4, stroke=ink).encode(
        color=alt.condition("datum.total > 0", alt.Color("total:Q", scale=scale([t["total"] for t in total]),
                                                         legend=None), alt.value(EMPTY[mode])),
        strokeWidth=alt.condition("datum.crunch", alt.value(2.5), alt.value(0)),
        tooltip=[alt.Tooltip("week:N", title="Week"), alt.Tooltip("span:N", title="Dates"),
                 alt.Tooltip("summary:N", title="Due"), alt.Tooltip("why:N", title="Crunch"),
                 alt.Tooltip("break:N", title="Break")],
    )
    strip_text = strip_base.mark_text(fontSize=12, fontWeight="bold").encode(
        text="label:N",
        color=alt.when(alt.datum.ink == "muted").then(alt.value(MUTED))
                 .when(alt.datum.ink == "deep").then(alt.value("#ffffff"))
                 .otherwise(alt.value("#1d1915")),
    )
    top = (strip + strip_text).properties(
        height=56, title=alt.Title("All courses: total graded weight due each week (% of a course grade, summed)",
                                   anchor="start", fontSize=13, fontWeight="normal"))

    cells = alt.Chart(alt.Data(values=grid)).mark_rect(cornerRadius=3, stroke=EMPTY[mode], strokeWidth=2).encode(
        x=alt.X("week:N", sort=order, axis=None),
        y=alt.Y("course:N", title=None, axis=alt.Axis(labelFontSize=12, ticks=False, domain=False)),
        color=alt.condition("datum.weight > 0",
                            alt.Color("weight:Q", scale=scale([g["weight"] for g in grid]),
                                      legend=alt.Legend(title="% of course grade", orient="bottom",
                                                        direction="horizontal", gradientLength=160)),
                            alt.value(EMPTY[mode])),
        tooltip=[alt.Tooltip("course:N", title="Course"), alt.Tooltip("week:N", title="Week"),
                 alt.Tooltip("span:N", title="Dates"), alt.Tooltip("items:N", title="Due"),
                 alt.Tooltip("weight:Q", title="Weight %")],
    ).properties(height=34 * max(len({g["course"] for g in grid}), 1))

    return (alt.vconcat(top, cells, spacing=10).resolve_scale(color="independent")
            .configure(background="transparent", font="Figtree, sans-serif")
            .configure_view(stroke=None)
            .configure_axis(labelColor=ink, titleColor=ink)
            .configure_title(color=ink)
            .configure_legend(labelColor=ink, titleColor=ink))
