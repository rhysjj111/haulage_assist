"""Small, entirely fictional text PDFs for the payroll reader tests.

Generate PDFs in memory instead of committing a real payroll report or adding
a PDF-generation dependency to the application.
"""

from decimal import Decimal
from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject


EMPLOYER_HEADER = (
    "Employee Total Payments Employer Pension",
    "Contrib.",
    "Employer NI Employer NI",
    "(Class 1A)",
    "Total Cost Per",
    "Employee",
)

EMPLOYEES = (
    ("Alice Example", "615.37", "13.59", "77.42", "0.00", "706.38"),
    ("Ben Sample", "801.20", "20.00", "100.50", "2.25", "923.95"),
)


def amount(value):
    """Read the limited fictional amounts used by the fixture generator."""
    if value.startswith("(") and value.endswith(")"):
        return -Decimal(value[1:-1].replace(",", ""))
    return Decimal(value.replace(",", ""))


def total_row(employees=EMPLOYEES):
    totals = [sum((amount(row[column]) for row in employees), Decimal("0.00"))
              for column in range(1, 6)]
    return "Totals " + " ".join(f"{value:.2f}" for value in totals)


def employee_lines(employees=EMPLOYEES):
    return [" ".join(row) for row in employees]


def text_pdf(pages, *, password=None):
    """Render supplied lines as actual PDF text, with no report contents."""
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    }))
    for lines in pages:
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        commands = []
        for index, line in enumerate(lines):
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"BT /F1 10 Tf 1 0 0 1 35 {805 - index * 14} Tm ({escaped}) Tj ET")
        stream = StreamObject()
        stream.set_data("\n".join(commands).encode("cp1252"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if password is not None:
        writer.encrypt(password)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def report_pdf(*, employees=EMPLOYEES, pay_date="25 Sep 2026", header=EMPLOYER_HEADER,
               row_lines=None, totals=None, after=()):
    """One-page section 4, with a deliberately unrelated payroll-run number."""
    lines = ["Fictional Haulage Ltd", f"Weekly Pay Run : 99 Pay Date : {pay_date}",
             "Section 4 - Employer Costs", *header,
             *(employee_lines(employees) if row_lines is None else row_lines)]
    lines.extend([total_row(employees) if totals is None else totals, *after])
    return text_pdf([lines])
