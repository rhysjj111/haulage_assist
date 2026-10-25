"""Entirely fictional Silvey-style invoices, generated as in-memory PDFs."""

from collections import defaultdict
from decimal import Decimal

from payroll_pdf_fixtures import text_pdf


TRANSACTIONS = (
    dict(card="900001", site="800001", place="FICTIONAL NORTH SERVICES", product="Derv",
         date="1/10/26", time="6:05", registration="ZZ26 ABC", odometer="10101", quantity="10.00", rate="1.20", cost="12.00"),
    dict(card="900001", site="800002", place="FICTIONAL EAST SERVICES", product="Derv",
         date="2/10/26", time="7:15", registration="ZZ26 ABC", odometer="10202", quantity="20.25", rate="1.20", cost="24.30"),
    dict(card="900001", site="800003", place="FICTIONAL SOUTH SERVICES", product="ADBLUE",
         date="2/10/26", time="7:15", registration="ZZ26 ABC", odometer="10202", quantity="5.00", rate="2.00", cost="10.00"),
    dict(card="900002", site="800004", place="FICTIONAL WEST SERVICES", product="Derv",
         date="3/10/26", time="8:30", registration="ZX26 DEF", odometer="20303", quantity="30.10", rate="1.40", cost="42.14"),
    dict(card="900002", site="800005", place="FICTIONAL DEPOT", product="Derv",
         date="4/10/26", time="9:35", registration="ZX26 DEF", odometer="20404", quantity="40.00", rate="1.20", cost="48.00"),
    dict(card="900003", site="800006", place="FICTIONAL PORT", product="Derv",
         date="5/10/26", time="10:40", registration="ZY26 GHI", odometer="30505", quantity="50.00", rate="1.40", cost="70.00"),
)
TABLE_HEADER = "CARD No SITE CODE & NAME DATE TIME REG. ODOMETER LITRES PRICE"
SUMMARY_HEADER = "PRODUCT DESCRIPTION QUANTITY £ UNIT PRICE £ VALUE VAT CODE"
FOOTER = ("Trading & registered ofce :", "Fictional supplier address", "www.silveyfleet.co.uk")


def transaction(overrides=None, *, base=0):
    row = dict(TRANSACTIONS[base])
    row.update(overrides or {})
    return row


def transaction_line(row, *, glued_time=False):
    separator = "" if glued_time else " "
    return (f"{row['card']} {row['site']} {row['place']} {row['product']} {row['date']} "
            f"{row['time']}{separator}{row['registration']} {row['odometer']} {row['quantity']} {row['cost']}")


def invoice_pages(*, rows=TRANSACTIONS, split_after=4, summary_lines=None,
                  grand_total=None, card_total_overrides=None, glued_time=False,
                  invoice_date="6-Oct-2026"):
    """Return text pages; a card deliberately continues onto the second page."""
    totals = defaultdict(lambda: [Decimal("0.00"), Decimal("0.00")])
    for row in rows:
        product, rate = row["product"].upper(), Decimal(row["rate"])
        totals[(product, rate)][0] += Decimal(row["quantity"])
        totals[(product, rate)][1] += Decimal(row["cost"])
    if summary_lines is None:
        summary_lines = [f"KEYFUELS {product} {quantity:.2f} {rate:.4f} {cost:.2f} 1"
                         for (product, rate), (quantity, cost) in totals.items()]
    overall = sum((Decimal(row["cost"]) for row in rows), Decimal("0.00"))
    first = ["Silvey Fleet Ltd", "SALES INVOICE", f"Invoice number date 9123456 {invoice_date}",
             "Fictional Customer Ltd", SUMMARY_HEADER,
             *summary_lines, f"{overall * Decimal('1.2'):.2f}", "VAT Code VAT Rate £ VAT £ Taxable", TABLE_HEADER]
    pages = [first]
    card_cost = Decimal("0.00")
    overrides = card_total_overrides or {}
    for index, row in enumerate(rows):
        if index == split_after and index:
            pages[-1].extend(FOOTER)
            pages.append([TABLE_HEADER])
        pages[-1].append(transaction_line(row, glued_time=glued_time))
        card_cost += Decimal(row["cost"])
        if index == len(rows) - 1 or row["card"] != rows[index + 1]["card"]:
            value = overrides.get(row["card"], f"{card_cost:.2f}")
            pages[-1].append(f"Total For Card: {value}")
            card_cost = Decimal("0.00")
    pages[-1].append(f"Grand Total: {grand_total if grand_total is not None else f'{overall:.2f}'}")
    pages[-1].extend(FOOTER)
    return ["\n".join(page) for page in pages]


def invoice_pdf(*, password=None, **kwargs):
    return text_pdf([page.splitlines() for page in invoice_pages(**kwargs)], password=password)
