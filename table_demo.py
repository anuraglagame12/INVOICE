"""Prototype: one invoice, ten different TABLE shapes.

The page around the table stays the same - supplier at the top, party block,
totals at the bottom. Only the item table changes: which columns exist, what
they are called, what order they run in, and whether "Amount" includes GST.

Throwaway code, so the ten can be looked at before anything is committed.

    python table_demo.py
"""
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas

OUT = "_tables"

SUP = {"name": "ABHIDNYA ENTERPRISES", "gstin": "27ACOPN6109M1Z1",
       "addr": ["217, Nana Peth next to Shri Ram Mandir",
                "Pune, MAHARASHTRA, 411002"]}
BUY = {"name": "Shiv Shambho Electrical", "gstin": "27DVJPP3046L1Z2",
       "addr": ["Flat No.6, Hausai Niwas, Bhosari Gavthan",
                "Pune, MAHARASHTRA, 411039"]}
INV = {"no": "AE/SI/26-27/26401", "date": "12 Aug 2026",
       "pos": "27-MAHARASHTRA"}

ITEMS = [
    ("10AX 1Way Switch 1M White Vision", "85361010", 212.00, 20, "PCS", 18, 10),
    ("9W LED Round Panel Light Cool White", "94054090", 340.00, 10, "PCS", 12, 0),
    ("1.5 Sq.mm FR PVC Copper Wire 90m", "85444911", 1450.00, 2, "COIL", 12, 20),
]


def rows():
    out = []
    for desc, hsn, mrp, qty, uom, gst, disc in ITEMS:
        rate = round(mrp * (1 - disc / 100), 2)
        gross = round(mrp * qty, 2)
        dv = round(gross - rate * qty, 2)
        tv = round(rate * qty, 2)
        tx = round(tv * gst / 100, 2)
        out.append({"d": desc, "h": hsn, "mrp": mrp, "rate": rate, "q": qty,
                    "u": uom, "g": gst, "disc": disc, "gross": gross,
                    "dv": dv, "tv": tv, "tx": tx, "half": round(tx / 2, 2),
                    "wg": round(tv + tx, 2)})
    return out


R = rows()
TAXABLE = round(sum(r["tv"] for r in R), 2)
TAX = round(sum(r["tx"] for r in R), 2)
GROSS = round(TAXABLE + TAX, 2)
TOTAL = round(GROSS)
ROUND_OFF = round(TOTAL - GROSS, 2)
WORDS = "INR Twelve Thousand, Nine Hundred Forty Rupees Only."


def m(v):
    return "{:,.2f}".format(v)


# ---------------------------------------------------------------- the page

def page(path, note):
    """Everything except the table, so the ten differ only in the middle."""
    c = pdfcanvas.Canvas(path, pagesize=A4)
    W, H = A4
    L, Rm = 12 * mm, W - 12 * mm
    c.setTitle(note)

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(W / 2, H - 14 * mm, "TAX INVOICE")
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.HexColor("#1f4e79"))
    c.drawRightString(Rm, H - 14 * mm, note)
    c.setFillColor(colors.black)

    c.setLineWidth(0.7)
    c.rect(L, 20 * mm, Rm - L, H - 40 * mm)
    y = H - 25 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(L + 3 * mm, y, SUP["name"])
    c.setFont("Helvetica", 8)
    c.drawString(L + 3 * mm, y - 5 * mm, "GSTIN: " + SUP["gstin"])
    for i, ln in enumerate(SUP["addr"]):
        c.drawString(L + 3 * mm, y - 9 * mm - i * 4 * mm, ln)

    mid = L + 108 * mm
    c.line(mid, H - 21 * mm, mid, H - 46 * mm)
    c.setFont("Helvetica", 7.5)
    c.drawString(mid + 3 * mm, y, "Invoice #:")
    c.drawString(mid + 45 * mm, y, "Date:")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(mid + 3 * mm, y - 4.5 * mm, INV["no"])
    c.drawString(mid + 45 * mm, y - 4.5 * mm, INV["date"])
    c.setFont("Helvetica", 7.5)
    c.drawString(mid + 3 * mm, y - 11 * mm, "Place of Supply:")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(mid + 3 * mm, y - 15.5 * mm, INV["pos"])

    c.line(L, H - 46 * mm, Rm, H - 46 * mm)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(L + 3 * mm, H - 51 * mm, "Customer Details:")
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(L + 3 * mm, H - 56 * mm, BUY["name"])
    c.setFont("Helvetica", 7.5)
    c.drawString(L + 3 * mm, H - 61 * mm, "GSTIN: " + BUY["gstin"])
    for i, ln in enumerate(BUY["addr"]):
        c.drawString(L + 3 * mm, H - 65.5 * mm - i * 4 * mm, ln)
    return c, L, Rm, H - 76 * mm


def table(c, x, y, width, heads, widths, body, *, size=7.5, caps=False):
    """Draw a table from column headings and their right-edge offsets."""
    xs = [x + w * mm for w in widths]
    c.setLineWidth(0.6)
    c.line(x, y, x + width, y)
    hy = y - 4.5 * mm
    c.setFont("Helvetica-Bold", size)
    for (label, align), cx in zip(heads, xs):
        if align == "l":
            c.drawString(cx, hy, label)
        else:
            c.drawRightString(cx, hy, label)
    y = hy - 2 * mm
    c.line(x, y, x + width, y)
    c.setFont("Helvetica", size)
    for r in body:
        y -= 4.6 * mm
        for (val, align), cx in zip(r, xs):
            s = str(val)
            if align == "l":
                avail = 40 * mm
                while c.stringWidth(s, "Helvetica", size) > avail and len(s) > 4:
                    s = s[:-1]
                c.drawString(cx, y, s)
            else:
                c.drawRightString(cx, y, s)
        y -= 1.6 * mm
    c.line(x, y, x + width, y)
    return y


def tail(c, L, Rm, y, amount_note):
    """Totals, words, and a line saying what Amount meant."""
    lbl, val = Rm - 55 * mm, Rm - 3 * mm
    for t_, v in (("Taxable Amount", m(TAXABLE)),
                  ("CGST", m(round(TAX / 2, 2))),
                  ("SGST", m(round(TAX / 2, 2))),
                  ("Round Off", m(ROUND_OFF))):
        y -= 4.4 * mm
        c.setFont("Helvetica", 8)
        c.drawString(lbl, y, t_)
        c.drawRightString(val, y, v)
    y -= 5 * mm
    c.line(lbl, y + 3 * mm, val, y + 3 * mm)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(lbl, y, "Amount Payable")
    c.drawRightString(val, y, m(TOTAL))

    c.setFont("Helvetica", 7.5)
    c.drawString(L + 2 * mm, y - 10 * mm, "Amount in words: " + WORDS)
    c.setFont("Helvetica-Oblique", 7)
    c.setFillColor(colors.HexColor("#a00000"))
    c.drawString(L + 2 * mm, y - 16 * mm, amount_note)
    c.setFillColor(colors.black)
    c.showPage()
    c.save()


# ================================================================ 10 tables

def t01_standard(path):
    c, L, Rm, y = page(path, "TABLE 1 - STANDARD")
    heads = [("#", "l"), ("Item", "l"), ("HSN/SAC", "l"), ("Rate", "r"),
             ("Qty", "r"), ("Taxable", "r"), ("Tax", "r"), ("Amount", "r")]
    cols = [3, 8, 88, 112, 128, 148, 168, 186]
    body = [[(str(i), "l"), (r["d"], "l"), (r["h"], "l"), (m(r["rate"]), "r"),
             ("%g %s" % (r["q"], r["u"]), "r"), (m(r["tv"]), "r"),
             (m(r["tx"]), "r"), (m(r["wg"]), "r")]
            for i, r in enumerate(R, 1)]
    y = table(c, L, y, Rm - L, heads, cols, body)
    tail(c, L, Rm, y, "Amount column INCLUDES GST  (taxable + tax)")


def t02_splittax(path):
    c, L, Rm, y = page(path, "TABLE 2 - SPLIT TAX")
    heads = [("Sr", "l"), ("Particulars", "l"), ("Code", "l"), ("Qty", "r"),
             ("Rate", "r"), ("CGST", "r"), ("SGST", "r"),
             ("Total Value", "r")]
    cols = [3, 9, 88, 108, 126, 146, 165, 186]
    body = [[(str(i), "l"), (r["d"], "l"), (r["h"], "l"),
             ("%g %s" % (r["q"], r["u"]), "r"), (m(r["rate"]), "r"),
             (m(r["half"]), "r"), (m(r["half"]), "r"), (m(r["wg"]), "r")]
            for i, r in enumerate(R, 1)]
    y = table(c, L, y, Rm - L, heads, cols, body)
    tail(c, L, Rm, y, "Tax split into CGST + SGST.  No Taxable column - it "
                      "must be derived.  Total Value INCLUDES GST")


def t03_simple(path):
    c, L, Rm, y = page(path, "TABLE 3 - SIMPLE")
    heads = [("#", "l"), ("Description", "l"), ("Qty", "r"), ("Price", "r"),
             ("Amount", "r")]
    cols = [3, 8, 128, 155, 186]
    body = [[(str(i), "l"), (r["d"], "l"),
             ("%g %s" % (r["q"], r["u"]), "r"), (m(r["rate"]), "r"),
             (m(r["tv"]), "r")] for i, r in enumerate(R, 1)]
    y = table(c, L, y, Rm - L, heads, cols, body)
    tail(c, L, Rm, y, "No HSN column, no tax column.  Amount EXCLUDES GST")


def t04_tally(path):
    c, L, Rm, y = page(path, "TABLE 4 - TALLY STYLE")
    heads = [("Sl", "l"), ("Description of Goods", "l"), ("HSN/SAC", "l"),
             ("Quantity", "r"), ("Rate", "r"), ("per", "l"), ("Amount", "r")]
    cols = [3, 8, 92, 118, 140, 143, 186]
    body = [[(str(i), "l"), (r["d"], "l"), (r["h"], "l"),
             ("%g" % r["q"], "r"), (m(r["rate"]), "r"), (r["u"], "l"),
             (m(r["tv"]), "r")] for i, r in enumerate(R, 1)]
    y = table(c, L, y, Rm - L, heads, cols, body)
    tail(c, L, Rm, y, "UOM in its own 'per' column.  Amount EXCLUDES GST")


def t05_withuom(path):
    c, L, Rm, y = page(path, "TABLE 5 - WITH UOM")
    heads = [("#", "l"), ("Item Description", "l"), ("HSN", "l"),
             ("UOM", "l"), ("Qty", "r"), ("Unit Rate", "r"),
             ("Taxable Value", "r"), ("GST%", "r"), ("Tax", "r"),
             ("Total", "r")]
    cols = [3, 7, 74, 92, 104, 122, 146, 156, 172, 186]
    body = [[(str(i), "l"), (r["d"], "l"), (r["h"], "l"), (r["u"], "l"),
             ("%g" % r["q"], "r"), (m(r["rate"]), "r"), (m(r["tv"]), "r"),
             ("%g%%" % r["g"], "r"), (m(r["tx"]), "r"), (m(r["wg"]), "r")]
            for i, r in enumerate(R, 1)]
    y = table(c, L, y, Rm - L, heads, cols, body, size=6.8)
    tail(c, L, Rm, y, "10 columns.  UOM and GST% separate.  Total INCLUDES GST")


def t06_discount(path):
    c, L, Rm, y = page(path, "TABLE 6 - DISCOUNT")
    heads = [("Sr No.", "l"), ("Particulars", "l"), ("HSN Code", "l"),
             ("MRP", "r"), ("Qty", "r"), ("Discount", "r"), ("Taxable", "r"),
             ("Tax", "r"), ("Net Amount", "r")]
    cols = [3, 12, 80, 100, 118, 138, 158, 172, 186]
    body = [[(str(i), "l"), (r["d"], "l"), (r["h"], "l"), (m(r["mrp"]), "r"),
             ("%g %s" % (r["q"], r["u"]), "r"),
             (m(r["dv"]) if r["dv"] else "-", "r"), (m(r["tv"]), "r"),
             (m(r["tx"]), "r"), (m(r["wg"]), "r")]
            for i, r in enumerate(R, 1)]
    y = table(c, L, y, Rm - L, heads, cols, body, size=7)
    tail(c, L, Rm, y, "MRP shown, discount in its own column.  "
                      "Net Amount INCLUDES GST")


def t07_minimal(path):
    c, L, Rm, y = page(path, "TABLE 7 - MINIMAL")
    heads = [("Description", "l"), ("Qty", "r"), ("Rate", "r"),
             ("Amount", "r")]
    cols = [3, 130, 158, 186]
    body = [[(r["d"], "l"), ("%g %s" % (r["q"], r["u"]), "r"),
             (m(r["rate"]), "r"), (m(r["tv"]), "r")] for r in R]
    y = table(c, L, y, Rm - L, heads, cols, body)
    tail(c, L, Rm, y, "Only 4 columns.  No serial number, no HSN, no tax.  "
                      "Amount EXCLUDES GST")


def t08_taxlast(path):
    c, L, Rm, y = page(path, "TABLE 8 - TAX LAST")
    heads = [("#", "l"), ("Goods Description", "l"), ("Tariff", "l"),
             ("Rate", "r"), ("Qty", "r"), ("Amount", "r"), ("GST Amt", "r"),
             ("Total", "r")]
    cols = [3, 8, 86, 110, 126, 148, 168, 186]
    body = [[(str(i), "l"), (r["d"], "l"), (r["h"], "l"), (m(r["rate"]), "r"),
             ("%g %s" % (r["q"], r["u"]), "r"), (m(r["tv"]), "r"),
             (m(r["tx"]), "r"), (m(r["wg"]), "r")]
            for i, r in enumerate(R, 1)]
    y = table(c, L, y, Rm - L, heads, cols, body)
    tail(c, L, Rm, y, "'Amount' here means the TAXABLE value, and Total "
                      "includes GST - the reverse of Table 1")


def t09_legacy(path):
    c, L, Rm, y = page(path, "TABLE 9 - LEGACY")
    heads = [("SR", "l"), ("DESCRIPTION", "l"), ("HSN", "l"), ("QTY", "r"),
             ("RATE", "r"), ("TAXABLE", "r"), ("GST", "r"), ("AMT", "r")]
    cols = [3, 8, 88, 108, 128, 150, 168, 186]
    body = [[(str(i), "l"), (r["d"].upper(), "l"), (r["h"], "l"),
             ("%g" % r["q"], "r"), (m(r["rate"]), "r"), (m(r["tv"]), "r"),
             (m(r["tx"]), "r"), (m(r["wg"]), "r")]
            for i, r in enumerate(R, 1)]
    y = table(c, L, y, Rm - L, heads, cols, body)
    tail(c, L, Rm, y, "All upper case, abbreviated headings.  "
                      "AMT INCLUDES GST")


def t10_detailed(path):
    c, L, Rm, y = page(path, "TABLE 10 - DETAILED")
    heads = [("#", "l"), ("Nature of Goods", "l"), ("Commodity Code", "l"),
             ("Qty", "r"), ("Unit", "l"), ("Rate/Unit", "r"), ("Gross", "r"),
             ("Less: Disc", "r"), ("Assessable Value", "r"), ("CGST", "r"),
             ("SGST", "r"), ("Total", "r")]
    cols = [2, 6, 56, 82, 84, 102, 120, 137, 158, 168, 178, 188]
    body = [[(str(i), "l"), (r["d"], "l"), (r["h"], "l"),
             ("%g" % r["q"], "r"), (r["u"], "l"), (m(r["mrp"]), "r"),
             (m(r["gross"]), "r"), (m(r["dv"]) if r["dv"] else "-", "r"),
             (m(r["tv"]), "r"), (m(r["half"]), "r"), (m(r["half"]), "r"),
             (m(r["wg"]), "r")] for i, r in enumerate(R, 1)]
    y = table(c, L, y, Rm - L, heads, cols, body, size=6)
    tail(c, L, Rm, y, "11 columns - gross, discount and assessable value all "
                      "shown.  Total INCLUDES GST")


TABLES = [
    ("01_Standard", t01_standard), ("02_SplitTax", t02_splittax),
    ("03_Simple", t03_simple), ("04_TallyStyle", t04_tally),
    ("05_WithUOM", t05_withuom), ("06_Discount", t06_discount),
    ("07_Minimal", t07_minimal), ("08_TaxLast", t08_taxlast),
    ("09_Legacy", t09_legacy), ("10_Detailed", t10_detailed),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    print("one invoice, %d table shapes" % len(TABLES))
    print("  taxable %s   tax %s   total %s\n" % (m(TAXABLE), m(TAX),
                                                  m(TOTAL)))
    for name, fn in TABLES:
        p = os.path.join(OUT, name + ".pdf")
        try:
            fn(p)
            print("  %-16s %5.0f KB" % (name, os.path.getsize(p) / 1024))
        except Exception as e:
            print("  %-16s FAILED  %s: %s" % (name, type(e).__name__, e))
    print("\nwritten to %s/" % OUT)


if __name__ == "__main__":
    main()
