"""Sample invoices rebuilt from the Tally Purchase Register export.

The register is a cross-tab: eight fixed columns, then one column per
expense ledger, each row carrying its amount under whichever ledger applies.
The GST rate is written into the ledger NAME ("Courier Expenses 18%"), so a
row's lines are recovered by reading every populated ledger column and
taking the rate off its heading.

Three things the register does not carry, and how they are handled here:

  * No HSN/SAC code  -> LEDGER_SAC maps each ledger to its service code.
  * No quantity/rate -> every line is a lump-sum service line (no_qty), which
    is what an expense ledger actually represents. Feeding a qty of 1 and a
    rate equal to the ledger amount reproduces the register's taxable value
    to the paisa, with no division and so no rounding drift.
  * No supplier address -> only the state, decoded from the GSTIN prefix.

The buyer is always the company the register belongs to, read off row 1-5.
"""
import os
import sys
from decimal import Decimal

import openpyxl

from invoicegen.manual import ManualForm, build, _safe

SRC = os.path.join(os.path.expanduser("~"), "Desktop",
                   "Purchase  Register - Jan.xlsx")
OUT = os.path.join(os.path.expanduser("~"), "Desktop", "Register_Invoices")

# Fixed columns, 0-based, as the header row lays them out.
C_DATE, C_PARTY, C_VTYPE, C_VNO, C_GSTIN, C_VALUE, C_ADDL, C_GROSS = range(8)
LEDGER_FROM = 8                 # ledger columns start here

# Tax and adjustment columns are not expense lines and never become items.
TAX_LEDGERS = {"CGST Input", "SGST Input", "IGST"}
ADJ_LEDGERS = {"Rounding Off"}

# The register names a ledger, not a code. These are the standard SACs for
# the services the ledgers describe; a goods ledger gets its HSN chapter.
LEDGER_SAC = {
    "Printing & Stationery": "998912",
    "Legal & Professional Fees": "998212",
    "Repairs Machine": "998717",
    "Courier Expenses": "996812",
    "Repair Centre Gst": "998717",
    "Repair - Centre": "998717",
    "Freight Charges Gst": "996511",
    "Panel": "853710",
    "Installation Charges": "995461",
    "Consumables": "998729",
    "Software Exp": "997331",
    "Service Charges (Purchase)": "998599",
    "Sales Pramotion": "998397",
    "Sales Promotion": "998397",
    "Audio Visual Equipment": "852852",
    "Computer": "847130",
    "Insurance": "997133",
    "UPS": "850440",
    "Furniture": "940360",
    "Car Expenses": "996601",
    "Internet Expenses": "998422",
    "Bank Charges": "997119",
    "Book Writing Expenses": "998912",
    "Travelling": "996411",
}

# State code -> state, for the address block the register cannot supply.
STATES = {
    "01": "Jammu & Kashmir", "06": "Haryana", "07": "Delhi",
    "19": "West Bengal", "24": "Gujarat", "27": "Maharashtra",
    "29": "Karnataka", "33": "Tamil Nadu", "36": "Telangana",
}


def _dec(v):
    """A blank cell is zero, not None - every column is money."""
    return Decimal(0) if v in (None, "") else Decimal(str(v))


def split_ledger(name):
    """('Courier Expenses 18%') -> ('Courier Expenses', Decimal 18).

    A ledger with no rate in its name is an unregistered/no-tax purchase and
    comes back at 0%.
    """
    name = name.strip()
    if name.endswith("%"):
        head, _, rate = name[:-1].rpartition(" ")
        if head and rate.replace(".", "").isdigit():
            return head.strip(), Decimal(rate)
    return name, Decimal(0)


def read_rows(path):
    """The register's data rows, header-mapped. Skips letterhead and total."""
    ws = openpyxl.load_workbook(path, data_only=True)["Purchase Register"]
    rows = list(ws.iter_rows(values_only=True))
    company = [str(r[0]).strip() for r in rows[:5] if r[0]]
    header = [("" if c is None else str(c).strip()) for c in rows[7]]
    data = [r for r in rows[8:]
            if r[C_PARTY] and str(r[C_PARTY]).strip() != "Grand Total"]
    return company, header, data


def to_form(row, header, buyer):
    """One register row -> a filled ManualForm ready to render."""
    gstin = str(row[C_GSTIN] or "").strip()
    state = STATES.get(gstin[:2], "")

    form = ManualForm()
    # A purchase register records what a supplier billed us, so the supplier
    # heads the invoice and our own company is the buyer.
    form.supplier.update({
        "name": str(row[C_PARTY]).strip(),
        "gstin": gstin,
        "addr1": state,
        "addr2": "",
    })
    form.buyer.update(buyer)
    date = row[C_DATE]
    form.invoice.update({
        "number": str(row[C_VNO]).strip(),
        "date": date.strftime("%d %b %Y") if hasattr(date, "strftime")
                else str(date),
        "pos": buyer["gstin"][:2] if buyer["gstin"] else "",
    })

    for col in range(LEDGER_FROM, len(header)):
        amount = _dec(row[col] if col < len(row) else None)
        if not amount:
            continue
        name = header[col]
        if name in TAX_LEDGERS or name in ADJ_LEDGERS:
            continue
        ledger, rate = split_ledger(name)
        form.items.append({
            "desc": ledger,
            "hsn": LEDGER_SAC.get(ledger, "-"),
            # The ledger amount IS the taxable value. Quantity 1 at that
            # exact rate reproduces it with no division, so nothing rounds.
            "qty": "1",
            "uom": "",
            "rate": str(amount),
            "gst": str(rate),
            "disc": "",
        })
    return form


def render(form, outdir, formats=("pdf",)):
    """Draw the invoice, titling it for what it actually is.

    manual.generate always prints TAX INVOICE. A supplier with no GSTIN
    charged no GST and cannot issue one - that document is a Bill of Supply,
    so the title is set on the built dict before it reaches the renderer.
    """
    from invoicegen.render import render as render_classic

    inv, t, seller = build(form)
    if not form.supplier["gstin"].strip():
        inv["doc_title"] = "BILL OF SUPPLY"
    pdf_dir = os.path.join(outdir, "pdf")
    os.makedirs(pdf_dir, exist_ok=True)
    path = os.path.join(pdf_dir, (_safe(inv["number"]) or "Invoice") + ".pdf")
    render_classic(inv, t, seller, path)
    return [path], inv["doc_title"]


def main():
    company, header, data = read_rows(SRC)
    by_no = {str(r[C_VNO]).strip(): r for r in data}
    arg = sys.argv[1:]
    if not arg:
        rows = data[:3]                     # the register's first three
    elif len(arg) == 1 and arg[0].isdigit():
        rows = data[:int(arg[0])]           # "first N"
    else:
        rows = [by_no[v] for v in arg if v in by_no]
        for v in arg:
            if v not in by_no:
                print("not in register:", v)

    buyer = {
        "name": company[0] if company else "",
        # The register is the buyer's own book; its GSTIN is not printed on
        # it, so the company's Maharashtra registration is supplied here.
        "gstin": "27AAFCC1234A1Z5",
        "addr1": ", ".join(company[1:3]),
        "addr2": company[3] if len(company) > 3 else "",
    }

    made = []
    for row in rows:
        vno = str(row[C_VNO]).strip()
        form = to_form(row, header, buyer)
        problems = form.problems()
        if problems:
            print("skipped", vno, "-", ", ".join(problems))
            continue
        t = form.totals()
        files, title = render(form, OUT)
        made += files
        # Print what the register said next to what the document computed,
        # so any drift shows up immediately.
        print("%-18s %-28s %-15s taxable %11s  tax %9s  total %11s  "
              "(register %s)" % (
                  vno, form.supplier["name"][:28], title, t["taxable"],
                  t["tax"], t["total"], _dec(row[C_GROSS])))
    print("\n%d file(s) in %s" % (len(made), os.path.join(OUT, "pdf")))


if __name__ == "__main__":
    main()
