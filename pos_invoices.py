"""Reconstruct tax invoices from a Food Junction POS sales report.

The POS exports one row per line item; rows sharing an Invoice No. are the
lines of one invoice, and Invoice Val repeats on each of them. Every printed
figure is taken from the report verbatim - taxable value and tax are never
recomputed, so a document can always be tied back to the source row.
"""
import os
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

import xlrd

from invoicegen.model import Line, money, rupees_in_words
from invoicegen.render import render

# The store issuing these. The POS export carries transactions only, so the
# letterhead is configured here rather than read from the sheet.
SELLER = {
    "name": "FOOD JUNCTION",
    "gstin": "27AAGFF3693L1ZX",
    "state": "MAHARASHTRA",
    "state_code": "27",
    "addr": ["Seasons Rd, Shambhu Vihar Society, Sanewadi",
             "Aundh, Pune, Maharashtra 411067"],
    "mobile": "",
    "bank": {"name": "-", "account": "-", "ifsc": "-", "branch": "-"},
}

# Column positions in the sales report (header sits on row 7, data from row 8).
C_GSTIN, C_NAME, C_PHONE, C_INVNO, C_MEMO, C_DATE, C_INVVAL = 1, 2, 3, 4, 5, 6, 7
C_HSN, C_PROD, C_TAXABLE = 8, 9, 10
C_SGST_R, C_SGST, C_CGST_R, C_CGST, C_IGST_R, C_IGST = 11, 12, 13, 14, 15, 16
C_CESS_R, C_CESS, C_ACESS_R, C_ACESS = 17, 18, 19, 20
C_POS, C_UOM, C_QTY, C_RATE, C_MRP, C_PAY = 21, 22, 23, 24, 25, 26

FIRST_DATA_ROW = 8


class PosLine(Line):
    """A line whose money comes from the POS, not from mrp x qty.

    The report's RATE is the MRP-inclusive shelf price, so deriving taxable
    from it would disagree with the taxable value the store actually charged
    tax on. These invoices must reconcile to the report to the paisa, so the
    reported figures win and the base Line arithmetic is bypassed.
    """

    def __init__(self, taxable, tax, cess, **kw):
        super().__init__(**kw)
        self._taxable = money(taxable)
        self._tax = money(tax)
        self._cess = money(cess)

    @property
    def taxable(self):
        return self._taxable

    @property
    def tax(self):
        return self._tax

    @property
    def cess(self):
        return self._cess

    @property
    def discount_value(self):
        return Decimal(0)


def _text(sh, r, c):
    """A cell as the sheet shows it, with float artefacts on integers removed."""
    v = sh.cell_value(r, c)
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return str(v).strip()


def _dec(sh, r, c):
    """A numeric cell; the report writes an absent figure as a dash."""
    s = _text(sh, r, c).replace(",", "")
    if s in ("", "-"):
        return Decimal(0)
    try:
        return Decimal(s)
    except Exception:
        return Decimal(0)


def _rate(sh, r, c):
    """A percentage cell such as 2.5%."""
    s = _text(sh, r, c).replace("%", "").strip()
    if s in ("", "-"):
        return Decimal(0)
    try:
        return Decimal(s)
    except Exception:
        return Decimal(0)


def _hsn(sh, r):
    """The HSN with its leading zero restored.

    Excel typed the column numerically and dropped leading zeros, leaving
    7-, 5- and 3-digit codes where GST allows only 4, 6 or 8. Padding one
    digit recovers the original code. Single-digit values are broken beyond
    repair upstream and are left exactly as recorded.
    """
    s = _text(sh, r, C_HSN)
    if len(s) in (3, 5, 7):
        return "0" + s
    return s


def read_invoices(path):
    """Group the report's rows into invoices, in the order they appear."""
    sh = xlrd.open_workbook(path).sheet_by_index(0)
    groups = defaultdict(list)
    order = []
    for r in range(FIRST_DATA_ROW, sh.nrows):
        no = _text(sh, r, C_INVNO)
        if not no:
            continue
        if no not in groups:
            order.append(no)
        groups[no].append(r)
    return sh, groups, order


def defects(sh, rows):
    """Why an invoice cannot be reproduced faithfully, if it cannot.

    Anything listed here would put a figure on the page that the store's own
    books do not support, so such invoices are skipped rather than patched.
    """
    bad = []
    if any(_text(sh, r, C_MEMO) not in ("0", "") for r in rows):
        bad.append("memo")
    hs = [_text(sh, r, C_HSN) for r in rows]
    if any(not h for h in hs):
        bad.append("blank_hsn")
    if any(len(h) == 1 for h in hs if h):
        bad.append("single_digit_hsn")
    if any(_dec(sh, r, C_TAXABLE) < 0 or _dec(sh, r, C_INVVAL) < 0
           for r in rows):
        bad.append("negative")
    if any(_dec(sh, r, C_QTY) <= 0 for r in rows):
        bad.append("bad_qty")
    if _dec(sh, rows[0], C_INVVAL) <= 0:
        bad.append("zero_total")
    total = sum(_dec(sh, r, C_TAXABLE) + _dec(sh, r, C_SGST)
                + _dec(sh, r, C_CGST) + _dec(sh, r, C_IGST)
                + _dec(sh, r, C_CESS) + _dec(sh, r, C_ACESS) for r in rows)
    if abs(total - _dec(sh, rows[0], C_INVVAL)) > 1:
        bad.append("sum_mismatch")
    return bad


def build(sh, rows):
    """One invoice as the renderer's (inv, t, seller) view."""
    head = rows[0]
    lines = []
    taxable = tax = cess = Decimal(0)
    interstate = False
    for r in rows:
        sg = _dec(sh, r, C_SGST)
        cg = _dec(sh, r, C_CGST)
        ig = _dec(sh, r, C_IGST)
        ln_cess = _dec(sh, r, C_CESS) + _dec(sh, r, C_ACESS)
        ln_tax = sg + cg + ig
        ln_taxable = _dec(sh, r, C_TAXABLE)
        if ig:
            interstate = True
        # The report gives each half separately; the full slab is their sum.
        gst = (_rate(sh, r, C_IGST_R) if ig
               else _rate(sh, r, C_SGST_R) + _rate(sh, r, C_CGST_R))
        qty = _dec(sh, r, C_QTY)
        lines.append(PosLine(
            taxable=ln_taxable, tax=ln_tax, cess=ln_cess,
            desc=_text(sh, r, C_PROD) or "Item",
            code=_hsn(sh, r),
            mrp=(ln_taxable / qty if qty else ln_taxable),
            qty=qty,
            uom=_text(sh, r, C_UOM) or "PC",
            gst=gst,
            cess_pct=(_rate(sh, r, C_CESS_R) + _rate(sh, r, C_ACESS_R)),
            exempt=(gst == 0),
        ))
        taxable += ln_taxable
        tax += ln_tax
        cess += ln_cess

    total = _dec(sh, head, C_INVVAL)
    sgst = sum(_dec(sh, r, C_SGST) for r in rows)
    cgst = sum(_dec(sh, r, C_CGST) for r in rows)
    igst = sum(_dec(sh, r, C_IGST) for r in rows)
    date = datetime.strptime(_text(sh, head, C_DATE), "%d/%m/%Y").date()

    # Retail counter sales: the buyer is unregistered and unnamed unless the
    # customer asked for the bill in their own name.
    name = _text(sh, head, C_NAME)
    gstin = _text(sh, head, C_GSTIN)
    pos_code = _text(sh, head, C_POS) or "27"

    inv = {
        "number": _text(sh, head, C_INVNO),
        "date": date.strftime("%d %b %Y"),
        "date_iso": date.isoformat(),
        "doc_title": "TAX INVOICE",
        "is_order": False,
        "letterhead_is_buyer": False,
        "is_purchase": False,
        "place_of_supply": pos_code + "-MAHARASHTRA",
        "buyer": {
            "name": name or "Cash Sale",
            "gstin": gstin or None,
            "state": "MAHARASHTRA",
            "bill": [] if name else ["Unregistered / walk-in customer"],
            "ship": [] if name else ["Unregistered / walk-in customer"],
            "phone": _text(sh, head, C_PHONE) or None,
        },
        "lines": lines,
        "charges": [],
        "reference": None,
        "original_invoice": None,
        "order_terms": None,
        "scanned": False,
        "tds": None,
    }

    # HSN-wise summary, the way a tax invoice must carry it.
    groups = {}
    for l in lines:
        g = groups.setdefault((l.code, l.gst),
                              {"taxable": Decimal(0), "tax": Decimal(0),
                               "cess": Decimal(0)})
        g["taxable"] += l.taxable
        g["tax"] += l.tax
        g["cess"] += l.cess

    t = {
        "taxable": money(taxable),
        "tax": money(tax),
        "cess": money(cess),
        "discount": Decimal(0),
        "charges": Decimal(0),
        "round_off": money(total - taxable - tax - cess),
        "total": money(total),
        "reverse_charge": False,
        "tds": Decimal(0),
        "tcs": Decimal(0),
        "cash_discount": Decimal(0),
        "customs_duty": Decimal(0),
        "advance": Decimal(0),
        "cgst": money(cgst),
        "sgst": money(sgst),
        "igst": money(igst),
        "interstate": interstate,
        "summary": [{"code": k[0], "gst": k[1],
                     **{kk: money(vv) for kk, vv in v.items()}}
                    for k, v in sorted(groups.items(), key=lambda kv: kv[0])],
        "qty": sum(l.qty for l in lines),
        "count": len(lines),
        "rates": sorted({float(l.gst) for l in lines}),
    }
    t["words"] = rupees_in_words(t["total"])
    return inv, t, SELLER


DEFAULT_SRC = (r"C:\Users\Anurag L\Desktop\FOOD JUNC\EXCEL"
               r"\Aundh Store - April2026SalesReport.xls")
DEFAULT_OUT = r"C:\Users\Anurag L\Desktop\Aundh Invoices"


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 800
    only = sys.argv[4] if len(sys.argv) > 4 else None

    os.makedirs(out, exist_ok=True)
    sh, groups, order = read_invoices(src)

    if only:
        inv, t, seller = build(sh, groups[only])
        path = os.path.join(out, only + ".pdf")
        render(inv, t, seller, path)
        print("wrote " + path)
        print("lines=%d taxable=%s tax=%s total=%s"
              % (t["count"], t["taxable"], t["tax"], t["total"]))
        return

    made = skipped = 0
    for no in order:
        if made >= limit:
            break
        if defects(sh, groups[no]):
            skipped += 1
            continue
        inv, t, seller = build(sh, groups[no])
        render(inv, t, seller, os.path.join(out, no + ".pdf"))
        made += 1
        if made % 100 == 0:
            print("  %d invoices..." % made, flush=True)
    print("done: %d invoices in %s (%d skipped as defective)"
          % (made, out, skipped))


if __name__ == "__main__":
    main()
