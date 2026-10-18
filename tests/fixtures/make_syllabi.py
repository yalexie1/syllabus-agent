"""Build the synthetic syllabi used by the tests and the demo.

Run: python tests/fixtures/make_syllabi.py

Everything here is fictional: "Example University", made-up courses and a made-up Fall 2026
calendar (demo_term.yaml). Each PDF is drawn line by line so the hard cases land exactly
where we want them: tables, a hyphen across a line break, typos, TBA dates, a repeated item.

answer_key.json lists what a careful human would put on the calendar. Its dates were worked
out by hand from demo_term.yaml, independently of syllabus_agent/term.py.
"""

import hashlib
import json
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "syllabi"
TOP, LEFT, LEADING = 740, 64, 15

# Each page is a list of lines: a string, ("h", heading), ("row", cells) or ("rule",).
SYLLABI = {
    "chem210_organic_chemistry.pdf": [
        [
            ("title", "CHEM 210: Organic Chemistry I"),
            "Example University · Fall 2026 · Prof. A. Placeholder",
            "Lectures: Mon/Wed/Fri 9:00-9:50 am, Sterling Hall 110",
            "",
            ("h", "Grading"),
            ("row", ["Component", "Weight", "Notes"]),
            ("rule",),
            ("row", ["Problem sets", "30%", "6 sets, lowest dropped"]),
            ("row", ["Midterm 1", "20%", "evening exam"]),
            ("row", ["Midterm 2", "20%", "in class"]),
            ("row", ["Final exam", "30%", "cumulative"]),
            "",
            ("h", "Exams"),
            "The first midterm is an evening ex-",
            "amination on Week 7 Thursday at 7 pm in Sterling Hall 110.",
            "Midterm 2 is held in class on Week 12 Wednesday and covers chapters 9-14.",
            "The cumulative final exam is on Jan 6 at 9:00 am; location to be announced.",
            "",
            ("h", "Problem sets"),
            "Problem sets are due on Fridays at 5 pm in the course dropbox. Your lowest",
            "problem set score is dropped. Weeks are numbered from the first week of term,",
            "including fall break.",
        ],
        [
            ("h", "Schedule"),
            ("row", ["Week", "Day", "Topic / Due"]),
            ("rule",),
            ("row", ["Week 1", "Mon", "Structure and bonding"]),
            ("row", ["Week 2", "Fri", "Problem Set 1 due"]),
            ("row", ["Week 3", "Wed", "Acids and bases"]),
            ("row", ["Week 4", "Fri", "Problem Set 2 due"]),
            ("row", ["Week 5", "Fri", "Problem Set 3 due"]),
            ("row", ["Week 6", "-", "Fall break, no class"]),
            ("row", ["Week 7", "Thu", "Midterm 1 (evening)"]),
            ("row", ["Week 8", "Fri", "Problem Set 4 due"]),
            ("row", ["Week 10", "Fri", "Problem Set 5 due"]),
            ("row", ["Week 12", "Wed", "Midterm 2 (in class)"]),
            ("row", ["Week 13", "Fri", "Problem Set 6 due"]),
            ("row", ["Finals", "Jan 6", "Final exam, 9:00 am"]),
        ],
    ],
    "cpsc223_data_structures.pdf": [
        [
            ("title", "CPSC 223: Data Structures and Programming Techniques"),
            "Example University · Fall 2026",
            "Lectures meet Tue/Thu 1:00-2:15 pm. Lectures are numbered in order, skipping breaks.",
            "",
            ("h", "Grading"),
            "Problem sets 40% (five sets, equally weighted) · Take-home midterm 25% · Final exam 35%",
            "",
            ("h", "Exams"),
            "The take-home midterm is released and due within the window Nov 3-5; you may use",
            "your notes but not other people. The final exam is on Thursday, January 7, 2-5 pm.",
            "",
            ("h", "Problem set deadlines"),
            "Problem Set 1 is due at the start of Lecture 4.",
            "Problem Set 2 is due two days after Lecture 8, at 11:59 pm.",
            "Problem Set 3 is due the day after Lecture 12.",
            "Problem Set 4 is due at Lecture 21.",
            "Problem Set 5 is due two days after Lecture 23, at 11:59 pm.",
        ],
        [
            ("h", "Lecture plan"),
            ("row", ["Lecture", "Topic", "Notes"]),
            ("rule",),
            ("row", ["1-3", "C review, pointers", ""]),
            ("row", ["4-8", "Linked lists, stacks", "PS1 due Lecture 4"]),
            ("row", ["9-12", "Hash tables", "PS2, PS3 out"]),
            ("row", ["13-14", "Trees", "Take-home midterm Nov 3-5"]),
            ("row", ["15-21", "Graphs, heaps", "PS4 due Lecture 21"]),
            ("row", ["22-25", "Review", ""]),
            "",
            "All dates are subject to change; changes will be posted on the course site.",
        ],
    ],
    "econ115_microeconomics.pdf": [
        [
            ("title", "ECON 115: Introductory Microeconomics"),
            "Example University · Fall 2026",
            "Class meets Monday and Wednesday, 11:35 am-12:50 pm.",
            "",
            ("h", "Course requirements"),
            ("row", ["Problem sets", "20%", "8 sets; lowest dropped"]),
            ("row", ["Quizzes", "20%", "4 in-class quizzes"]),
            ("row", ["Midterm", "25%", "Wednesday, October 28"]),
            ("row", ["Final exam", "35%", "Monday, January 4"]),
            "",
            "In-class quizzes are given at the start of Lecture 5, Lecture 10, Lecture 15 and",
            "Lecture 20. There are no make-up quizzes.",
            "",
            ("h", "Problem set due dates (Fridays, 5 pm)"),
            ("row", ["PS1", "Sep 25", ""]),
            ("row", ["PS2", "Oct 9", ""]),
            ("row", ["PS3", "Oct 16", ""]),
            ("row", ["PS4", "Oct 30", ""]),
            ("row", ["PS5", "Nov 13", ""]),
            ("row", ["PS6", "Nov 20", ""]),
            ("row", ["PS7", "Dec 4", ""]),
            ("row", ["PS8", "Dec 11", ""]),
            "",
            "Late problem sets are not accepted, but your lowest score is droped automatically.",
        ],
    ],
    "hist145_modern_europe.pdf": [
        [
            ("title", "HIST 145: Modern Europe, 1789-1989"),
            "Example University · Fall 2026 · Seminar meets Mon/Wed 2:30-3:45 pm",
            "",
            ("h", "Assignments and grading"),
            "Participation 20% · Response papers 20% (four, 5% each) · Paper 1 20% ·",
            "Final paper 30% · Presentation 10%",
            "",
            "Your final paper (4,000 words) is due Dec 16 by noon. It builds on Paper 1,",
            "which is due Friday, October 30. Presentations are scheduled TBA; we’ll",
            "sign up in the third week of class.",
            "",
            "This syllabus is subject to change. “Late” means after the posted deadline.",
        ],
        [
            ("h", "Reading and writing schedule"),
            ("row", ["Due", "Assignment", ""]),
            ("rule",),
            ("row", ["Sept 30", "Response paper 1", ""]),
            ("row", ["Oct 14", "Response paper 2", ""]),
            ("row", ["Oct 30", "Paper 1 (2,000 words)", ""]),
            ("row", ["Nov 11", "Response paper 3", ""]),
            "Response paper 4 is due on Wendesday, Dec 9, before seminar.",
            ("row", ["Dec 16", "Final paper due by noon", ""]),
        ],
    ],
    "math225_linear_algebra.pdf": [
        [
            ("title", "MATH 225: Linear Algebra and Matrix Theory"),
            "Example University · Fall 2026 · Lectures Tue/Thu 10:30-11:45 am",
            "",
            ("h", "Grading"),
            ("row", ["Homework", "10%", "due every Friday"]),
            ("row", ["Quizzes", "10%", "dates announced in class"]),
            ("row", ["Midterm 1", "20%", "Week 7 Tuesday"]),
            ("row", ["Midterm 2", "20%", "Week 12 Tuesday (subject to change)"]),
            ("row", ["Final exam", "40%", "Jan 5, 9 am-noon"]),
            "",
            "Both midterms are in class. Midterm 1 is on Week 7 Tuesday and covers chapters 1-3.",
            "Midterm 2 is on Week 12 Tuesday. The final exam is cumulative and is held on Jan 5.",
            "Weekly homework is due every Friday at 5 pm on Gradescope.",
        ],
    ],
}

# What belongs on the calendar. date None means it can't be dated from the syllabus (Needs review).
KEY = {
    "chem210_organic_chemistry.pdf": ("CHEM 210", [
        ("problem_set", "Problem Set 1", "2026-09-25"), ("problem_set", "Problem Set 2", "2026-10-09"),
        ("problem_set", "Problem Set 3", "2026-10-16"), ("exam", "Midterm 1", "2026-10-29"),
        ("problem_set", "Problem Set 4", "2026-11-06"), ("problem_set", "Problem Set 5", "2026-11-20"),
        ("exam", "Midterm 2", "2026-12-02"), ("problem_set", "Problem Set 6", "2026-12-11"),
        ("exam", "Final exam", "2027-01-06"),
    ]),
    "cpsc223_data_structures.pdf": ("CPSC 223", [
        ("problem_set", "Problem Set 1", "2026-09-24"), ("problem_set", "Problem Set 2", "2026-10-10"),
        ("problem_set", "Problem Set 3", "2026-10-30"), ("exam", "Take-home midterm", "2026-11-03", "2026-11-05"),
        ("problem_set", "Problem Set 4", "2026-12-03"), ("problem_set", "Problem Set 5", "2026-12-12"),
        ("exam", "Final exam", "2027-01-07"),
    ]),
    "econ115_microeconomics.pdf": ("ECON 115", [
        ("quiz", "Quiz 1", "2026-09-28"), ("quiz", "Quiz 2", "2026-10-14"),
        ("quiz", "Quiz 3", "2026-11-09"), ("quiz", "Quiz 4", "2026-11-30"),
        ("exam", "Midterm", "2026-10-28"), ("exam", "Final exam", "2027-01-04"),
        ("problem_set", "PS1", "2026-09-25"), ("problem_set", "PS2", "2026-10-09"),
        ("problem_set", "PS3", "2026-10-16"), ("problem_set", "PS4", "2026-10-30"),
        ("problem_set", "PS5", "2026-11-13"), ("problem_set", "PS6", "2026-11-20"),
        ("problem_set", "PS7", "2026-12-04"), ("problem_set", "PS8", "2026-12-11"),
    ]),
    "hist145_modern_europe.pdf": ("HIST 145", [
        ("paper", "Response paper 1", "2026-09-30"), ("paper", "Response paper 2", "2026-10-14"),
        ("paper", "Paper 1", "2026-10-30"), ("paper", "Response paper 3", "2026-11-11"),
        ("paper", "Response paper 4", "2026-12-09"), ("paper", "Final paper", "2026-12-16"),
        ("presentation", "Presentation", None),
    ]),
    "math225_linear_algebra.pdf": ("MATH 225", [
        ("exam", "Midterm 1", "2026-10-27"), ("exam", "Midterm 2", "2026-12-01"),
        ("exam", "Final exam", "2027-01-05"), ("quiz", "Quizzes", None),
        ("problem_set", "Homework", None),
    ]),
}

COLUMNS = [0, 120, 300]


def draw(path, pages):
    pdf = canvas.Canvas(str(path), pagesize=letter)
    pdf.setTitle(path.stem)
    for lines in pages:
        y = TOP
        for line in lines:
            kind = line[0] if isinstance(line, tuple) else "text"
            if kind == "title":
                pdf.setFont("Helvetica-Bold", 15)
                pdf.drawString(LEFT, y, line[1])
                y -= 8
            elif kind == "h":
                pdf.setFont("Helvetica-Bold", 11.5)
                pdf.drawString(LEFT, y, line[1])
            elif kind == "row":
                pdf.setFont("Helvetica", 10.5)
                for x, cell in zip(COLUMNS, line[1]):
                    pdf.drawString(LEFT + x, y, cell)
            elif kind == "rule":
                pdf.line(LEFT, y + 10, 540, y + 10)
                y += 6
            else:
                pdf.setFont("Helvetica", 10.5)
                pdf.drawString(LEFT, y, line)
            y -= LEADING
        pdf.showPage()
    pdf.save()


def scanned(path):
    """A page with drawings but no text layer, like a scan."""
    pdf = canvas.Canvas(str(path), pagesize=letter)
    for n in range(12):
        pdf.rect(LEFT, TOP - n * 40, 300 + n * 10, 18, fill=1)
    pdf.showPage()
    pdf.save()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    key = {}
    for name, pages in SYLLABI.items():
        draw(OUT / name, pages)
        course, items = KEY[name]
        key[name] = {
            "sha256": hashlib.sha256((OUT / name).read_bytes()).hexdigest(),
            "course": course,
            "items": [{"type": t, "title": title, "date": date, "end_date": rest[0] if rest else None}
                      for t, title, date, *rest in items],
        }
    (OUT / "answer_key.json").write_text(json.dumps(key, indent=1) + "\n")
    scanned(Path(__file__).parent / "scanned_handout.pdf")
    print(f"Wrote {len(SYLLABI)} syllabi, answer_key.json and scanned_handout.pdf")


if __name__ == "__main__":
    main()
