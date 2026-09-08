"""Twenty invoice layouts.

The same invoice can be drawn twenty different ways: the supplier name moves,
the GSTIN turns up somewhere else, labels are reworded, blocks are dropped.
The numbers never change - only where they sit on the page.

That is the point. A parser that only reads one layout is not finished, and
these twenty are how you find out.

Pattern 1 (Classic) is drawn by the original renderer in render.py; the rest
are drawn here. Every pattern is a function taking a `Doc` - a plain view of
the invoice - so none of them touch the invoice model directly.
"""
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas

from .model import fmt, half_tax, money

HERE = os.path.dirname(os.path.abspath(__file__))
DEVA = os.path.join(HERE, "fonts", "NotoSansDevanagari-Regular.ttf")
_deva_ready = None


def deva_font():
    """Register the Devanagari face once; None if it is unavailable."""
    global _deva_ready
    if _deva_ready is None:
        try:
            pdfmetrics.registerFont(TTFont("Deva", DEVA))
            _deva_ready = "Deva"
        except Exception:
            _deva_ready = False
    return _deva_ready or None


# ---------------------------------------------------------------- the view

class Doc:
    """Everything a pattern needs, flattened out of the invoice model."""

    def __init__(self, inv, t, seller):
        p = inv["buyer"]
        self.title = inv.get("doc_title", "TAX INVOICE")
        self.number = inv["number"]
        self.date = inv["date"]
        self.pos = inv["place_of_supply"]
        self.is_order = bool(inv.get("is_order"))
        self.logo = inv.get("logo")
        self.sup = {
            "name": seller["name"], "gstin": seller["gstin"],
            "addr": seller.get("addr", []), "phone": seller.get("mobile", ""),
        }
        self.buy = {
            "name": p.get("name", ""), "gstin": p.get("gstin") or "",
            "addr": p.get("bill", []), "ship": p.get("ship", p.get("bill", [])),
        }
        self.bank = seller.get("bank") or {}
        self.inter = bool(t["interstate"])
        self.words = t.get("words", "")
        self.taxable = t["taxable"]
        self.tax = t["tax"]
        self.cgst = t["cgst"]
        self.sgst = t["sgst"]
        self.igst = t["igst"]
        self.round_off = t["round_off"]
        self.total = t["total"]
        self.charges = inv.get("charges", [])
        self.rows = [{
            "d": l.desc, "h": l.code, "r": l.rate, "q": l.qty, "u": l.uom,
            "g": l.gst, "tv": l.taxable, "tx": l.tax, "amt": l.amount,
            "disc": l.discount_pct,
        } for l in inv["lines"]]
        # A charge is billed like any other supply, so it joins the table with
        # its SAC and no quantity. It is therefore inside `taxable` below and
        # must not be listed again in the totals.
        self.rows += [{
            "d": c.label, "h": c.code, "r": None, "q": None, "u": "",
            "g": c.gst, "tv": c.amount, "tx": c.tax,
            "amt": money(c.amount + c.tax), "disc": 0,
        } for c in self.charges]
        self.taxable = money(self.taxable + t["charges"])
        # Display forms, so every layout prints a charge row the same way
        # without each one having to test for the missing rate and quantity.
        for r in self.rows:
            r["r_txt"] = "-" if r["r"] is None else fmt(r["r"])
            r["q_txt"] = ("-" if r["q"] is None
                          else ("%g %s" % (r["q"], r["u"])).strip())
            r["qn_txt"] = "-" if r["q"] is None else "%g" % r["q"]
            r["h_txt"] = r["h"] or "-"
        self.summary = t.get("summary", [])
        self.original = inv.get("original_invoice")
        self.terms = inv.get("order_terms")

    def bank_lines(self):
        b = self.bank
        if not b:
            return []
        return [b.get("name", ""), "A/c " + str(b.get("account", "")),
                "IFSC " + str(b.get("ifsc", ""))]


# ---------------------------------------------------------------- drawing

class Sheet:
    """A thin drawing surface, so each pattern reads like a description."""

    def __init__(self, path, size=A4, title=""):
        self.c = pdfcanvas.Canvas(path, pagesize=size)
        if title:
            self.c.setTitle(title)
        self.W, self.H = size

    def t(self, x, y, s, f="Helvetica", sz=8, col=None, align="l"):
        try:
            self.c.setFont(f, sz)
        except Exception:
            self.c.setFont("Helvetica", sz)
        self.c.setFillColor(col or colors.black)
        s = str(s)
        if align == "r":
            self.c.drawRightString(x, y, s)
        elif align == "c":
            self.c.drawCentredString(x, y, s)
        else:
            self.c.drawString(x, y, s)
        self.c.setFillColor(colors.black)

    def line(self, x1, y1, x2, y2, w=0.6, col=None, dash=None):
        self.c.setLineWidth(w)
        self.c.setStrokeColor(col or colors.black)
        if dash:
            self.c.setDash(dash, 2)
        self.c.line(x1, y1, x2, y2)
        self.c.setDash()
        self.c.setStrokeColor(colors.black)

    def box(self, x, y, w, h, fill=None, stroke=colors.black, lw=0.6):
        self.c.setLineWidth(lw)
        if fill:
            self.c.setFillColor(fill)
        if stroke:
            self.c.setStrokeColor(stroke)
        self.c.rect(x, y, w, h, stroke=1 if stroke else 0,
                    fill=1 if fill else 0)
        self.c.setFillColor(colors.black)
        self.c.setStrokeColor(colors.black)

    def clip(self, s, f, sz, width):
        """Trim a string to fit, so a long item name never overruns."""
        s = str(s)
        while s and self.c.stringWidth(s, f, sz) > width:
            s = s[:-1]
        return s

    def done(self):
        self.c.showPage()
        self.c.save()


# ---------------------------------------------------------- shared pieces

HEAD_STD = [("#", "l"), ("Item", "l"), ("HSN", "l"), ("Rate", "r"),
            ("Qty", "r"), ("Taxable", "r"), ("Tax", "r"), ("Amount", "r")]
# right edges in mm from the left margin: #, item, HSN, rate, qty,
# taxable, tax, amount - HSN needs room for 8 digits before the rate
COLS_STD = [3, 8, 86, 112, 128, 147, 170, 188]


def items_std(sh, d, size=7.5, width=76 * mm):
    out = []
    for i, r in enumerate(d.rows, 1):
        # a charge row has no unit rate or quantity, and may have no SAC
        out.append([(str(i), "l"),
                    (sh.clip(r["d"], "Helvetica", size, width), "l"),
                    (r["h_txt"], "l"), (r["r_txt"], "r"),
                    (r["q_txt"], "r"), (fmt(r["tv"]), "r"),
                    ("%s (%g%%)" % (fmt(r["tx"]), r["g"]), "r"),
                    (fmt(r["amt"]), "r")])
    return out


def table(sh, x, y, width, cols, headers, body, *, font="Helvetica",
          hfont="Helvetica-Bold", size=7.5, grid=False, rule=True,
          shade=None, dash=None):
    xs = [x + c * mm for c in cols]
    if rule:
        sh.line(x, y, x + width, y, dash=dash)
    hy = y - 4.5 * mm
    for (label, align), cx in zip(headers, xs):
        sh.t(cx, hy, label, hfont, size, align=align)
    y = hy - 2 * mm
    if rule:
        sh.line(x, y, x + width, y, dash=dash)
    for i, r in enumerate(body):
        ry = y - 4.6 * mm
        if shade and i % 2:
            sh.box(x, ry - 1.4 * mm, width, 4.6 * mm, fill=shade, stroke=None)
        for (val, align), cx in zip(r, xs):
            sh.t(cx, ry, val, font, size, align=align)
        if grid:
            sh.line(x, ry - 1.6 * mm, x + width, ry - 1.6 * mm, 0.3,
                    colors.HexColor("#cccccc"))
        y = ry - 1.6 * mm
    if rule:
        sh.line(x, y, x + width, y, dash=dash)
    return y


def totals(sh, d, x, y, *, align="r", label="Amount Payable", width=52,
           box=False, tint=None, font="Helvetica", bfont="Helvetica-Bold"):
    lbl = x - width * mm if align == "r" else x
    val = x if align == "r" else x + width * mm
    # charges are rows in the table and already inside d.taxable
    rows = [("Taxable Amount", fmt(d.taxable))]
    if d.inter:
        rows.append(("IGST", fmt(d.igst)))
    else:
        rows.append(("CGST", fmt(d.cgst)))
        rows.append(("SGST", fmt(d.sgst)))
    rows.append(("Round Off", fmt(d.round_off)))
    if box:
        sh.box(lbl - 3 * mm, y - (len(rows) + 1) * 4.4 * mm,
               width * mm + 6 * mm, (len(rows) + 2) * 4.4 * mm,
               fill=tint or colors.HexColor("#f4f6f9"), stroke=None)
    for t_, v in rows:
        sh.t(lbl, y, t_, font, 8)
        sh.t(val, y, v, font, 8, align="r")
        y -= 4.4 * mm
    sh.line(lbl, y + 2 * mm, val, y + 2 * mm)
    y -= 1 * mm
    sh.t(lbl, y, label, bfont, 9.5)
    sh.t(val, y, fmt(d.total), bfont, 9.5, align="r")
    return y


def summary(sh, d, x, y, width=95):
    if not d.summary:
        return y
    sh.t(x, y, "HSN/SAC", "Helvetica-Bold", 7)
    sh.t(x + 40 * mm, y, "Taxable", "Helvetica-Bold", 7, align="r")
    if d.inter:
        sh.t(x + 70 * mm, y, "IGST", "Helvetica-Bold", 7, align="r")
    else:
        sh.t(x + 62 * mm, y, "CGST", "Helvetica-Bold", 7, align="r")
        sh.t(x + 84 * mm, y, "SGST", "Helvetica-Bold", 7, align="r")
    y -= 1.5 * mm
    sh.line(x, y, x + width * mm, y)
    for s in d.summary:
        y -= 4.2 * mm
        half = half_tax(s["tax"])
        sh.t(x, y, s["code"], "Helvetica", 7)
        sh.t(x + 40 * mm, y, fmt(s["taxable"]), "Helvetica", 7, align="r")
        if d.inter:
            sh.t(x + 70 * mm, y, fmt(s["tax"]), "Helvetica", 7, align="r")
        else:
            sh.t(x + 62 * mm, y, fmt(half), "Helvetica", 7, align="r")
            sh.t(x + 84 * mm, y, fmt(half), "Helvetica", 7, align="r")
    y -= 1.5 * mm
    sh.line(x, y, x + width * mm, y)
    return y


def footer(sh, d, y, *, bank=True, notes=True, sign=True, x=15 * mm,
           W=180 * mm):
    if bank and d.bank_lines():
        sh.t(x, y, "Bank Details:", "Helvetica-Bold", 7.5)
        for ln in d.bank_lines():
            y -= 3.8 * mm
            sh.t(x, y, ln, "Helvetica", 7.5)
    if notes:
        y -= 6 * mm
        sh.t(x, y, "Certified that the particulars given above are true and "
                   "correct.", "Helvetica", 6.5, colors.HexColor("#555555"))
    if sign:
        sh.t(x + W, y + 12 * mm, "For " + d.sup["name"], "Helvetica-Bold", 8,
             align="r")
        sh.t(x + W, y, "Authorised Signatory", "Helvetica", 7.5, align="r")
    return y


# ================================================================ layouts
# Each takes (Doc, path). Pattern 01 is drawn by render.py, not here.


def p02_tally(d, path):
    """Title band, supplier centred, GSTIN in the party block, meta in a
    ruled strip, totals under the table."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 10 * mm, W - 10 * mm
    sh.box(L, H - 26 * mm, Rm - L, 12 * mm, fill=colors.HexColor("#e8e8e8"))
    sh.t(W / 2, H - 22 * mm, d.title, "Helvetica-Bold", 13, align="c")
    sh.t(W / 2, H - 33 * mm, d.sup["name"], "Helvetica-Bold", 12, align="c")
    sh.t(W / 2, H - 38 * mm, ", ".join(d.sup["addr"]), "Helvetica", 7.5,
         align="c")
    y = H - 46 * mm
    sh.line(L, y, Rm, y)
    sh.t(L + 2 * mm, y - 5 * mm, "Invoice No. : " + d.number, "Helvetica", 8)
    sh.t(W / 2, y - 5 * mm, "Dated : " + d.date, "Helvetica", 8, align="c")
    sh.t(Rm - 2 * mm, y - 5 * mm, "Place of Supply : " + d.pos, "Helvetica",
         8, align="r")
    y -= 8 * mm
    sh.line(L, y, Rm, y)
    sh.t(L + 2 * mm, y - 6 * mm, "Buyer (Bill to)", "Helvetica-Bold", 8)
    sh.t(L + 2 * mm, y - 11 * mm, d.buy["name"], "Helvetica-Bold", 9.5)
    if d.buy["gstin"]:
        sh.t(L + 2 * mm, y - 16 * mm, "GSTIN/UIN : " + d.buy["gstin"],
             "Helvetica", 8)
    if d.buy["addr"]:
        sh.t(L + 2 * mm, y - 20.5 * mm, d.buy["addr"][0], "Helvetica", 7.5)
    sh.t(Rm - 2 * mm, y - 11 * mm, "Supplier GSTIN : " + d.sup["gstin"],
         "Helvetica", 8, align="r")
    y = table(sh, L, y - 26 * mm, Rm - L, COLS_STD, HEAD_STD,
              items_std(sh, d), grid=True)
    ty = totals(sh, d, Rm - 2 * mm, y - 6 * mm, label="Grand Total")
    sh.t(L + 2 * mm, ty - 6 * mm, "Amount Chargeable (in words)",
         "Helvetica-Bold", 7.5)
    sh.t(L + 2 * mm, ty - 10 * mm, d.words, "Helvetica", 8)
    footer(sh, d, 40 * mm, notes=False, x=L + 2 * mm, W=Rm - L - 4 * mm)
    sh.done()


def p03_modern(d, path):
    """Coloured header bar, GSTIN pushed to the footer, borderless shaded
    table, tinted totals box."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 14 * mm, W - 14 * mm
    accent = colors.HexColor("#1f4e79")
    pale = colors.HexColor("#c9d9ea")
    sh.box(0, H - 30 * mm, W, 30 * mm, fill=accent, stroke=None)
    sh.t(L, H - 18 * mm, d.sup["name"], "Helvetica-Bold", 16, colors.white)
    sh.t(L, H - 24 * mm, "  ".join(d.sup["addr"]), "Helvetica", 8, pale)
    sh.t(Rm, H - 16 * mm, d.title, "Helvetica-Bold", 15, colors.white,
         align="r")
    sh.t(Rm, H - 22 * mm, d.number, "Helvetica", 8.5, pale, align="r")
    sh.t(Rm, H - 27 * mm, d.date, "Helvetica", 8.5, pale, align="r")
    sh.t(L, H - 42 * mm, "Billed To", "Helvetica-Bold", 7.5)
    sh.t(L, H - 48 * mm, d.buy["name"], "Helvetica-Bold", 10)
    yy = H - 53 * mm
    if d.buy["gstin"]:
        sh.t(L, yy, "GSTIN: " + d.buy["gstin"], "Helvetica", 7.5)
        yy -= 4 * mm
    for ln in d.buy["addr"][:2]:
        sh.t(L, yy, ln, "Helvetica", 7.5)
        yy -= 4 * mm
    sh.t(Rm, H - 42 * mm, "Place of Supply", "Helvetica-Bold", 7.5, align="r")
    sh.t(Rm, H - 47 * mm, d.pos, "Helvetica", 8.5, align="r")
    y = table(sh, L, H - 70 * mm, Rm - L, COLS_STD, HEAD_STD,
              items_std(sh, d), rule=False,
              shade=colors.HexColor("#f0f4f9"))
    sh.line(L, y, Rm, y, 1.2, accent)
    ty = totals(sh, d, Rm, y - 8 * mm, label="Total Due", box=True,
                tint=colors.HexColor("#eef3f9"))
    sh.t(L, ty - 4 * mm, d.words, "Helvetica-Oblique", 7.5)
    sh.line(L, 26 * mm, Rm, 26 * mm, 0.4, colors.HexColor("#999999"))
    sh.t(L, 21 * mm, "GSTIN " + d.sup["gstin"] + "   " + d.sup["phone"] +
         "   " + "  ".join(d.bank_lines()), "Helvetica", 7,
         colors.HexColor("#666666"))
    sh.done()


def p04_compact(d, path):
    """Everything shrunk. No shipping address, no tax summary, totals in
    three inline lines."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 12 * mm, W - 12 * mm
    sh.t(L, H - 16 * mm, d.sup["name"], "Helvetica-Bold", 10)
    tail = d.sup["addr"][-1] if d.sup["addr"] else ""
    sh.t(L, H - 20 * mm, "GSTIN " + d.sup["gstin"] + "  |  " + tail,
         "Helvetica", 7)
    sh.t(Rm, H - 16 * mm, d.title, "Helvetica-Bold", 10, align="r")
    sh.t(Rm, H - 20 * mm, d.number + "   " + d.date, "Helvetica", 7,
         align="r")
    sh.line(L, H - 23 * mm, Rm, H - 23 * mm)
    sh.t(L, H - 28 * mm, "Party", "Helvetica-Bold", 7)
    who = d.buy["name"] + ("   GSTIN " + d.buy["gstin"] if d.buy["gstin"]
                           else "")
    sh.t(L + 14 * mm, H - 28 * mm, who, "Helvetica", 7.5)
    sh.t(L + 14 * mm, H - 32 * mm, ", ".join(d.buy["addr"][:2]), "Helvetica",
         6.5)
    cols = [3, 7, 78, 98, 112, 132, 152, 172]
    y = table(sh, L, H - 37 * mm, Rm - L, cols, HEAD_STD,
              items_std(sh, d, 6.8, 66 * mm), size=6.8)
    y -= 5 * mm
    rows = [("Taxable", fmt(d.taxable))]
    rows += [("GST", fmt(d.tax)), ("Net", fmt(d.total))]
    for lbl, v in rows:
        bold = "Helvetica-Bold" if lbl == "Net" else "Helvetica"
        sh.t(Rm - 30 * mm, y, lbl, bold, 8)
        sh.t(Rm, y, v, bold, 8, align="r")
        y -= 4.2 * mm
    sh.t(L, y - 2 * mm, d.words, "Helvetica", 6.5)
    sh.done()


def p05_boxed(d, path):
    """Form-like. Every field in a ruled cell, GSTIN in a labelled cell of
    its own."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 12 * mm, W - 12 * mm
    wid = Rm - L
    grey = colors.HexColor("#666666")
    sh.box(L, H - 20 * mm, wid, 8 * mm)
    sh.t(W / 2, H - 17.5 * mm, d.title, "Helvetica-Bold", 11, align="c")
    sh.box(L, H - 34 * mm, wid * 0.55, 14 * mm)
    sh.box(L + wid * 0.55, H - 34 * mm, wid * 0.45, 14 * mm)
    sh.t(L + 2 * mm, H - 24 * mm, "Name of Supplier", "Helvetica", 6.5, grey)
    sh.t(L + 2 * mm, H - 30 * mm, d.sup["name"], "Helvetica-Bold", 10)
    sh.t(L + wid * 0.55 + 2 * mm, H - 24 * mm, "GSTIN of Supplier",
         "Helvetica", 6.5, grey)
    sh.t(L + wid * 0.55 + 2 * mm, H - 30 * mm, d.sup["gstin"],
         "Helvetica-Bold", 10)
    for i, (lbl, val) in enumerate((("Invoice No.", d.number),
                                    ("Invoice Date", d.date),
                                    ("Place of Supply", d.pos))):
        x = L + i * wid / 3
        sh.box(x, H - 46 * mm, wid / 3, 12 * mm)
        sh.t(x + 2 * mm, H - 37 * mm, lbl, "Helvetica", 6.5, grey)
        sh.t(x + 2 * mm, H - 43 * mm, sh.clip(val, "Helvetica-Bold", 8.5,
                                              wid / 3 - 4 * mm),
             "Helvetica-Bold", 8.5)
    sh.box(L, H - 68 * mm, wid / 2, 22 * mm)
    sh.box(L + wid / 2, H - 68 * mm, wid / 2, 22 * mm)
    sh.t(L + 2 * mm, H - 51 * mm, "Billed To", "Helvetica-Bold", 7)
    sh.t(L + 2 * mm, H - 56 * mm, d.buy["name"], "Helvetica-Bold", 9)
    if d.buy["gstin"]:
        sh.t(L + 2 * mm, H - 61 * mm, "GSTIN " + d.buy["gstin"], "Helvetica",
             7)
    if d.buy["addr"]:
        sh.t(L + 2 * mm, H - 65 * mm, d.buy["addr"][0], "Helvetica", 7)
    sh.t(L + wid / 2 + 2 * mm, H - 51 * mm, "Shipped To", "Helvetica-Bold", 7)
    for i, ln in enumerate(d.buy["ship"][:3]):
        sh.t(L + wid / 2 + 2 * mm, H - 56 * mm - i * 4 * mm, ln, "Helvetica",
             7)
    y = table(sh, L, H - 70 * mm, wid, COLS_STD, HEAD_STD, items_std(sh, d),
              grid=True)
    ty = totals(sh, d, Rm - 2 * mm, y - 6 * mm, label="Total Invoice Value")
    sh.t(L + 2 * mm, ty - 6 * mm, d.words, "Helvetica", 7.5)
    footer(sh, d, 44 * mm, x=L + 2 * mm, W=wid - 4 * mm)
    sh.done()


def p06_minimal(d, path):
    """No borders. Large light supplier name, GSTIN as small grey text
    under the address."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 20 * mm, W - 20 * mm
    grey = colors.HexColor("#888888")
    sh.t(L, H - 24 * mm, d.sup["name"].title(), "Helvetica", 17)
    for i, ln in enumerate(d.sup["addr"]):
        sh.t(L, H - 31 * mm - i * 4 * mm, ln, "Helvetica", 8, grey)
    sh.t(L, H - 43 * mm, "GSTIN " + d.sup["gstin"], "Helvetica", 7, grey)
    sh.t(Rm, H - 24 * mm, d.title.title(), "Helvetica", 13, grey, align="r")
    sh.t(Rm, H - 31 * mm, d.number, "Helvetica", 8.5, align="r")
    sh.t(Rm, H - 36 * mm, d.date, "Helvetica", 8.5, grey, align="r")
    sh.t(L, H - 56 * mm, "To", "Helvetica", 7.5, grey)
    sh.t(L, H - 62 * mm, d.buy["name"], "Helvetica-Bold", 10)
    if d.buy["addr"]:
        sh.t(L, H - 67 * mm, d.buy["addr"][0], "Helvetica", 8, grey)
    if d.buy["gstin"]:
        sh.t(L, H - 71 * mm, "GSTIN " + d.buy["gstin"], "Helvetica", 7.5,
             grey)
    y = table(sh, L, H - 84 * mm, Rm - L, COLS_STD, HEAD_STD,
              items_std(sh, d))
    ty = totals(sh, d, Rm, y - 8 * mm, label="Amount")
    sh.t(L, ty - 6 * mm, d.words, "Helvetica", 7.5, grey)
    sh.t(L, 24 * mm, "  ".join(d.bank_lines()), "Helvetica", 7, grey)
    sh.done()


def p07_letterhead(d, path):
    """Branded header holding name, address and GSTIN together. Totals
    bottom-LEFT."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 15 * mm, W - 15 * mm
    band = colors.HexColor("#0f3d2e")
    pale = colors.HexColor("#a8c8bb")
    sh.box(0, H - 46 * mm, W, 46 * mm, fill=band, stroke=None)
    sh.t(W / 2, H - 22 * mm, d.sup["name"], "Helvetica-Bold", 18,
         colors.white, align="c")
    sh.t(W / 2, H - 29 * mm, " | ".join(d.sup["addr"]), "Helvetica", 8, pale,
         align="c")
    sh.t(W / 2, H - 35 * mm, "GSTIN " + d.sup["gstin"] + "    Tel " +
         d.sup["phone"], "Helvetica", 8, pale, align="c")
    sh.t(W / 2, H - 42 * mm, d.title, "Helvetica-Bold", 10, colors.white,
         align="c")
    sh.t(L, H - 54 * mm, "Invoice To", "Helvetica-Bold", 7.5)
    sh.t(L, H - 60 * mm, d.buy["name"], "Helvetica-Bold", 10)
    if d.buy["gstin"]:
        sh.t(L, H - 65 * mm, "GSTIN " + d.buy["gstin"], "Helvetica", 7.5)
    if d.buy["addr"]:
        sh.t(L, H - 69.5 * mm, d.buy["addr"][0], "Helvetica", 7.5)
    sh.t(Rm, H - 54 * mm, "Invoice No.  " + d.number, "Helvetica", 8,
         align="r")
    sh.t(Rm, H - 59 * mm, "Date  " + d.date, "Helvetica", 8, align="r")
    sh.t(Rm, H - 64 * mm, "Place of Supply  " + d.pos, "Helvetica", 8,
         align="r")
    y = table(sh, L, H - 80 * mm, Rm - L, COLS_STD, HEAD_STD,
              items_std(sh, d))
    ty = totals(sh, d, L, y - 8 * mm, align="l", label="Payable")
    summary(sh, d, Rm - 95 * mm, y - 8 * mm)
    sh.t(L, ty - 8 * mm, d.words, "Helvetica", 7.5)
    footer(sh, d, 40 * mm, x=L, W=Rm - L)
    sh.done()


def p08_twocol(d, path):
    """No meta panel. Supplier left, party right, invoice number centred
    between them."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 14 * mm, W - 14 * mm
    sh.t(W / 2, H - 16 * mm, d.title, "Helvetica-Bold", 12, align="c")
    sh.line(L, H - 20 * mm, Rm, H - 20 * mm, 1.0)
    sh.t(L, H - 27 * mm, "From", "Helvetica-Bold", 7.5)
    sh.t(L, H - 33 * mm, d.sup["name"], "Helvetica-Bold", 10)
    sh.t(L, H - 38 * mm, "GSTIN " + d.sup["gstin"], "Helvetica", 7.5)
    for i, ln in enumerate(d.sup["addr"]):
        sh.t(L, H - 43 * mm - i * 4 * mm, ln, "Helvetica", 7.5)
    sh.t(Rm, H - 27 * mm, "To", "Helvetica-Bold", 7.5, align="r")
    sh.t(Rm, H - 33 * mm, d.buy["name"], "Helvetica-Bold", 10, align="r")
    if d.buy["gstin"]:
        sh.t(Rm, H - 38 * mm, "GSTIN " + d.buy["gstin"], "Helvetica", 7.5,
             align="r")
    for i, ln in enumerate(d.buy["addr"][:2]):
        sh.t(Rm, H - 43 * mm - i * 4 * mm, ln, "Helvetica", 7.5, align="r")
    sh.t(W / 2, H - 33 * mm, d.number, "Helvetica-Bold", 9, align="c")
    sh.t(W / 2, H - 38 * mm, d.date, "Helvetica", 8, align="c")
    sh.t(W / 2, H - 43 * mm, d.pos, "Helvetica", 7.5, align="c")
    y = table(sh, L, H - 60 * mm, Rm - L, COLS_STD, HEAD_STD,
              items_std(sh, d))
    ty = totals(sh, d, Rm, y - 8 * mm, label="Balance Due")
    sh.t(L, ty - 6 * mm, d.words, "Helvetica", 7.5)
    footer(sh, d, 42 * mm, x=L, W=Rm - L)
    sh.done()


def p09_serif(d, path):
    """Times throughout, supplier centred with a rule, GSTIN centred
    beneath, tax summary ABOVE the totals."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 16 * mm, W - 16 * mm
    sh.t(W / 2, H - 22 * mm, d.sup["name"].title(), "Times-Bold", 16,
         align="c")
    sh.line(L + 30 * mm, H - 25 * mm, Rm - 30 * mm, H - 25 * mm, 0.8)
    sh.t(W / 2, H - 30 * mm, ", ".join(d.sup["addr"]), "Times-Roman", 8.5,
         align="c")
    sh.t(W / 2, H - 35 * mm, "GSTIN: " + d.sup["gstin"], "Times-Roman", 8.5,
         align="c")
    sh.t(W / 2, H - 44 * mm, d.title, "Times-Bold", 12, align="c")
    sh.t(L, H - 54 * mm, "Messrs.", "Times-Bold", 8)
    sh.t(L, H - 60 * mm, d.buy["name"], "Times-Bold", 10)
    if d.buy["addr"]:
        sh.t(L, H - 65 * mm, d.buy["addr"][0], "Times-Roman", 8.5)
    if d.buy["gstin"]:
        sh.t(L, H - 70 * mm, "GSTIN: " + d.buy["gstin"], "Times-Roman", 8.5)
    sh.t(Rm, H - 54 * mm, "No. " + d.number, "Times-Roman", 9, align="r")
    sh.t(Rm, H - 60 * mm, "Dated " + d.date, "Times-Roman", 9, align="r")
    y = table(sh, L, H - 80 * mm, Rm - L, COLS_STD, HEAD_STD,
              items_std(sh, d, 8.5), font="Times-Roman", hfont="Times-Bold",
              size=8.5)
    sy = summary(sh, d, L, y - 8 * mm)
    ty = totals(sh, d, Rm, sy - 8 * mm, label="Total Amount",
                font="Times-Roman", bfont="Times-Bold")
    sh.t(L, ty - 8 * mm, "Rupees " + d.words.replace("INR ", ""),
         "Times-Italic", 9)
    sh.t(Rm, 34 * mm, "For " + d.sup["name"].title(), "Times-Bold", 9,
         align="r")
    sh.t(Rm, 24 * mm, "Authorised Signatory", "Times-Roman", 8.5, align="r")
    sh.done()


def p10_wide(d, path):
    """Full-width table with extra columns, GSTIN inline after the supplier
    name, totals underneath the table."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 8 * mm, W - 8 * mm
    sh.t(L, H - 15 * mm, d.sup["name"] + "    GSTIN " + d.sup["gstin"],
         "Helvetica-Bold", 10)
    sh.t(L, H - 20 * mm, ", ".join(d.sup["addr"]) + "    " + d.sup["phone"],
         "Helvetica", 7.5)
    sh.t(Rm, H - 15 * mm, d.title + "  " + d.number, "Helvetica-Bold", 10,
         align="r")
    sh.t(Rm, H - 20 * mm, d.date + "    " + d.pos, "Helvetica", 7.5,
         align="r")
    sh.line(L, H - 23 * mm, Rm, H - 23 * mm)
    line2 = ("Consignee: " + d.buy["name"] +
             ("   GSTIN " + d.buy["gstin"] if d.buy["gstin"] else "") +
             ("   " + d.buy["addr"][0] if d.buy["addr"] else ""))
    sh.t(L, H - 29 * mm, line2, "Helvetica", 8)
    head = [("#", "l"), ("Description of Goods", "l"), ("HSN/SAC", "l"),
            ("UOM", "l"), ("Qty", "r"), ("Rate", "r"), ("Taxable", "r"),
            ("GST%", "r"), ("Tax", "r"), ("Amount", "r")]
    cols = [3, 8, 96, 116, 128, 142, 158, 170, 180, 194]
    body = [[(str(i), "l"), (sh.clip(r["d"], "Helvetica", 7, 84 * mm), "l"),
             (r["h_txt"], "l"), (r["u"], "l"), (r["qn_txt"], "r"),
             (r["r_txt"], "r"), (fmt(r["tv"]), "r"), ("%g%%" % r["g"], "r"),
             (fmt(r["tx"]), "r"), (fmt(r["amt"]), "r")]
            for i, r in enumerate(d.rows, 1)]
    y = table(sh, L, H - 36 * mm, Rm - L, cols, head, body, grid=True, size=7)
    y -= 6 * mm
    sh.t(L + 2 * mm, y, "Amount in words: " + d.words, "Helvetica", 7.5)
    ty = totals(sh, d, Rm - 2 * mm, y, label="Invoice Total")
    footer(sh, d, 40 * mm, x=L + 2 * mm, W=Rm - L - 4 * mm)
    sh.done()


def p11_billship(d, path):
    """US-style wording. Supplier small top-left, GSTIN labelled 'Tax ID'
    in the meta panel, two labelled address boxes."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 15 * mm, W - 15 * mm
    grey = colors.HexColor("#666666")
    sh.t(L, H - 18 * mm, d.sup["name"].title(), "Helvetica-Bold", 11)
    for i, ln in enumerate(d.sup["addr"][:2]):
        sh.t(L, H - 23 * mm - i * 4 * mm, ln, "Helvetica", 7.5)
    sh.t(Rm, H - 20 * mm, d.title.split()[-1], "Helvetica-Bold", 20,
         colors.HexColor("#444444"), align="r")
    ry = H - 30 * mm
    for lbl, val in (("Invoice #", d.number), ("Date", d.date),
                     ("Tax ID", d.sup["gstin"]),
                     ("Place of Supply", d.pos)):
        sh.t(Rm - 40 * mm, ry, lbl, "Helvetica-Bold", 7.5)
        sh.t(Rm, ry, val, "Helvetica", 8, align="r")
        ry -= 4.4 * mm
    bw = (Rm - L) / 2 - 3 * mm
    sh.box(L, H - 74 * mm, bw, 24 * mm, stroke=colors.HexColor("#bbbbbb"))
    sh.box(L + bw + 6 * mm, H - 74 * mm, bw, 24 * mm,
           stroke=colors.HexColor("#bbbbbb"))
    sh.t(L + 2 * mm, H - 55 * mm, "BILL TO", "Helvetica-Bold", 7.5, grey)
    sh.t(L + 2 * mm, H - 61 * mm, d.buy["name"], "Helvetica-Bold", 9.5)
    if d.buy["addr"]:
        sh.t(L + 2 * mm, H - 66 * mm, d.buy["addr"][0], "Helvetica", 7.5)
    if d.buy["gstin"]:
        sh.t(L + 2 * mm, H - 70 * mm, "Tax ID " + d.buy["gstin"], "Helvetica",
             7)
    sh.t(L + bw + 8 * mm, H - 55 * mm, "SHIP TO", "Helvetica-Bold", 7.5, grey)
    sh.t(L + bw + 8 * mm, H - 61 * mm, d.buy["name"], "Helvetica-Bold", 9.5)
    for i, ln in enumerate(d.buy["ship"][:2]):
        sh.t(L + bw + 8 * mm, H - 66 * mm - i * 4 * mm, ln, "Helvetica", 7.5)
    y = table(sh, L, H - 84 * mm, Rm - L, COLS_STD, HEAD_STD,
              items_std(sh, d))
    ty = totals(sh, d, Rm, y - 8 * mm, label="Balance")
    sh.t(L, ty - 6 * mm, d.words, "Helvetica", 7.5)
    footer(sh, d, 40 * mm, x=L, W=Rm - L)
    sh.done()


def p12_nosummary(d, path):
    """No HSN summary at all. Supplier centred, GSTIN buried in the notes."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 14 * mm, W - 14 * mm
    sh.t(W / 2, H - 20 * mm, d.sup["name"], "Helvetica-Bold", 13, align="c")
    sh.t(W / 2, H - 26 * mm, ", ".join(d.sup["addr"]), "Helvetica", 8,
         align="c")
    sh.line(L, H - 30 * mm, Rm, H - 30 * mm, 1.0)
    sh.t(W / 2, H - 37 * mm, d.title, "Helvetica-Bold", 11, align="c")
    sh.t(L, H - 46 * mm, "Customer", "Helvetica-Bold", 7.5)
    sh.t(L, H - 52 * mm, d.buy["name"], "Helvetica-Bold", 10)
    if d.buy["gstin"]:
        sh.t(L, H - 57 * mm, "GSTIN " + d.buy["gstin"], "Helvetica", 7.5)
    if d.buy["addr"]:
        sh.t(L, H - 61.5 * mm, d.buy["addr"][0], "Helvetica", 7.5)
    sh.t(Rm, H - 46 * mm, d.number, "Helvetica-Bold", 9, align="r")
    sh.t(Rm, H - 51 * mm, d.date, "Helvetica", 8, align="r")
    sh.t(Rm, H - 56 * mm, d.pos, "Helvetica", 8, align="r")
    y = table(sh, L, H - 72 * mm, Rm - L, COLS_STD, HEAD_STD,
              items_std(sh, d))
    ty = totals(sh, d, Rm, y - 8 * mm, width=44)
    sh.t(L, ty - 6 * mm, d.words, "Helvetica", 7.5)
    sh.t(L, 30 * mm, "Notes:", "Helvetica-Bold", 7)
    sh.t(L, 25 * mm, "Supplier GSTIN " + d.sup["gstin"] + ". Goods once sold "
         "will not be taken back. Subject to Pune jurisdiction.",
         "Helvetica", 6.5, colors.HexColor("#555555"))
    sh.done()


def p13_rightalign(d, path):
    """Mirror of Classic - meta top-LEFT, supplier top-RIGHT, totals
    bottom-left."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 12 * mm, W - 12 * mm
    sh.t(W / 2, H - 14 * mm, d.title, "Helvetica-Bold", 12, align="c")
    sh.box(L, 20 * mm, Rm - L, H - 40 * mm)
    y = H - 25 * mm
    sh.t(Rm - 3 * mm, y, d.sup["name"], "Helvetica-Bold", 11, align="r")
    sh.t(Rm - 3 * mm, y - 5 * mm, "GSTIN: " + d.sup["gstin"], "Helvetica", 8,
         align="r")
    for i, ln in enumerate(d.sup["addr"]):
        sh.t(Rm - 3 * mm, y - 9 * mm - i * 4 * mm, ln, "Helvetica", 8,
             align="r")
    mid = L + 82 * mm
    sh.line(mid, H - 21 * mm, mid, H - 52 * mm)
    sh.t(L + 3 * mm, y, "Invoice #:", "Helvetica", 7.5)
    sh.t(L + 3 * mm, y - 4.5 * mm, d.number, "Helvetica-Bold", 9)
    sh.t(L + 3 * mm, y - 11 * mm, "Date:", "Helvetica", 7.5)
    sh.t(L + 3 * mm, y - 15.5 * mm, d.date, "Helvetica-Bold", 9)
    sh.t(L + 42 * mm, y - 11 * mm, "Place of Supply:", "Helvetica", 7.5)
    sh.t(L + 42 * mm, y - 15.5 * mm, d.pos, "Helvetica-Bold", 9)
    sh.line(L, H - 52 * mm, Rm, H - 52 * mm)
    sh.t(Rm - 3 * mm, H - 57 * mm, "Sold To", "Helvetica-Bold", 7.5,
         align="r")
    sh.t(Rm - 3 * mm, H - 62 * mm, d.buy["name"], "Helvetica-Bold", 9.5,
         align="r")
    if d.buy["gstin"]:
        sh.t(Rm - 3 * mm, H - 67 * mm, "GSTIN " + d.buy["gstin"], "Helvetica",
             7.5, align="r")
    sh.t(L + 3 * mm, H - 57 * mm, "Delivered To", "Helvetica-Bold", 7.5)
    for i, ln in enumerate(d.buy["ship"][:3]):
        sh.t(L + 3 * mm, H - 62 * mm - i * 4 * mm, ln, "Helvetica", 7.5)
    y = table(sh, L, H - 78 * mm, Rm - L, COLS_STD, HEAD_STD,
              items_std(sh, d))
    ty = totals(sh, d, L + 3 * mm, y - 6 * mm, align="l", label="Total")
    summary(sh, d, Rm - 97 * mm, y - 6 * mm)
    sh.t(L + 3 * mm, ty - 8 * mm, d.words, "Helvetica", 7.5)
    footer(sh, d, 46 * mm, x=L + 3 * mm, W=Rm - L - 6 * mm)
    sh.done()


def p14_thermal(d, path):
    """Narrow receipt. One centred column, items stacked not tabled."""
    sh = Sheet(path, size=(80 * mm, 260 * mm), title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 4 * mm, W - 4 * mm
    sh.t(W / 2, H - 10 * mm, "M/s " + sh.clip(d.sup["name"],
                                              "Helvetica-Bold", 8, 68 * mm),
         "Helvetica-Bold", 8, align="c")
    sh.t(W / 2, H - 14 * mm, "GSTIN " + d.sup["gstin"], "Helvetica", 6.5,
         align="c")
    if d.sup["addr"]:
        sh.t(W / 2, H - 18 * mm, d.sup["addr"][-1], "Helvetica", 6.5,
             align="c")
    sh.line(L, H - 21 * mm, Rm, H - 21 * mm, 0.4, dash=[1, 1])
    sh.t(W / 2, H - 26 * mm, d.title, "Helvetica-Bold", 8, align="c")
    sh.t(L, H - 32 * mm, "No : " + d.number, "Helvetica", 6.5)
    sh.t(L, H - 36 * mm, "Dt : " + d.date, "Helvetica", 6.5)
    sh.t(L, H - 40 * mm, "To : " + sh.clip(d.buy["name"], "Helvetica", 6.5,
                                           62 * mm), "Helvetica", 6.5)
    if d.buy["gstin"]:
        sh.t(L, H - 44 * mm, "GSTIN " + d.buy["gstin"], "Helvetica", 6.5)
    sh.line(L, H - 47 * mm, Rm, H - 47 * mm, 0.4, dash=[1, 1])
    y = H - 52 * mm
    for i, r in enumerate(d.rows, 1):
        sh.t(L, y, "%d. %s" % (i, sh.clip(r["d"], "Helvetica", 6.5, 66 * mm)),
             "Helvetica", 6.5)
        y -= 3.6 * mm
        sh.t(L + 3 * mm, y, ("%s x %s" % (r["q_txt"], r["r_txt"])),
             "Helvetica", 6.5)
        sh.t(Rm, y, fmt(r["amt"]), "Helvetica", 6.5, align="r")
        y -= 4.4 * mm
    sh.line(L, y, Rm, y, 0.4, dash=[1, 1])
    y -= 5 * mm
    pairs = [("Taxable", fmt(d.taxable))]
    if d.inter:
        pairs.append(("IGST", fmt(d.igst)))
    else:
        pairs += [("CGST", fmt(d.cgst)), ("SGST", fmt(d.sgst))]
    for lbl, v in pairs:
        sh.t(L, y, lbl, "Helvetica", 6.5)
        sh.t(Rm, y, v, "Helvetica", 6.5, align="r")
        y -= 3.8 * mm
    sh.line(L, y, Rm, y, 0.4, dash=[1, 1])
    y -= 5 * mm
    sh.t(L, y, "TOTAL", "Helvetica-Bold", 9)
    sh.t(Rm, y, fmt(d.total), "Helvetica-Bold", 9, align="r")
    sh.t(W / 2, y - 10 * mm, "Thank you", "Helvetica", 6.5, align="c")
    sh.done()


def p15_legacy(d, path):
    """1990s billing software. Monospace, upper case, dashed rules."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 12 * mm, W - 12 * mm
    F, FB = "Courier", "Courier-Bold"
    sh.t(L, H - 16 * mm, d.sup["name"].upper(), FB, 10)
    for i, ln in enumerate(d.sup["addr"][:2]):
        sh.t(L, H - 21 * mm - i * 4 * mm, ln.upper(), F, 7.5)
    sh.t(L, H - 30 * mm, "GSTIN/UIN : " + d.sup["gstin"], F, 7.5)
    sh.t(Rm, H - 16 * mm, "  ".join(d.title), FB, 10, align="r")
    sh.line(L, H - 33 * mm, Rm, H - 33 * mm, 0.5, dash=[2, 2])
    sh.t(L, H - 38 * mm, "INV NO  : " + d.number, F, 7.5)
    sh.t(L, H - 42 * mm, "DATE    : " + d.date.upper(), F, 7.5)
    sh.t(L + 90 * mm, H - 38 * mm, "PARTY NAME : " +
         sh.clip(d.buy["name"].upper(), F, 7.5, 80 * mm), F, 7.5)
    if d.buy["gstin"]:
        sh.t(L + 90 * mm, H - 42 * mm, "GSTIN      : " + d.buy["gstin"], F,
             7.5)
    sh.t(L + 90 * mm, H - 46 * mm, "POS        : " + d.pos, F, 7.5)
    sh.line(L, H - 50 * mm, Rm, H - 50 * mm, 0.5, dash=[2, 2])
    head = [("SR", "l"), ("DESCRIPTION", "l"), ("HSN", "l"), ("QTY", "r"),
            ("RATE", "r"), ("TAXABLE", "r"), ("GST", "r"), ("AMT", "r")]
    body = [[(str(i), "l"), (sh.clip(r["d"].upper(), F, 7, 74 * mm), "l"),
             (r["h_txt"], "l"), (r["qn_txt"], "r"), (r["r_txt"], "r"),
             (fmt(r["tv"]), "r"), (fmt(r["tx"]), "r"), (fmt(r["amt"]), "r")]
            for i, r in enumerate(d.rows, 1)]
    y = table(sh, L, H - 54 * mm, Rm - L, COLS_STD, head, body, font=F,
              hfont=FB, size=7, dash=[2, 2])
    y -= 6 * mm
    pairs = [("TAXABLE VALUE", fmt(d.taxable))]
    if d.inter:
        pairs.append(("IGST", fmt(d.igst)))
    else:
        pairs += [("CGST", fmt(d.cgst)), ("SGST", fmt(d.sgst))]
    pairs.append(("ROUND OFF", fmt(d.round_off)))
    for lbl, v in pairs:
        sh.t(Rm - 46 * mm, y, lbl, F, 7.5)
        sh.t(Rm, y, v, F, 7.5, align="r")
        y -= 4 * mm
    sh.line(Rm - 48 * mm, y + 2 * mm, Rm, y + 2 * mm, 0.5, dash=[2, 2])
    sh.t(Rm - 46 * mm, y - 2 * mm, "NET PAYABLE", FB, 9)
    sh.t(Rm, y - 2 * mm, fmt(d.total), FB, 9, align="r")
    sh.t(L, y - 2 * mm, "RS. " + d.words.replace("INR ", "").upper(), F, 7)
    sh.t(L, 30 * mm, "E. & O.E.", F, 7)
    sh.t(Rm, 30 * mm, "FOR " + d.sup["name"].upper(), F, 7.5, align="r")
    sh.done()


def p16_portal(d, path):
    """Government e-invoice print. QR block top-right, IRN strip above
    everything, rigid labelled grid."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 12 * mm, W - 12 * mm
    wid = Rm - L
    sh.box(L, H - 30 * mm, wid, 16 * mm)
    sh.t(L + 2 * mm, H - 19 * mm, "IRN :", "Helvetica-Bold", 6.5)
    sh.t(L + 14 * mm, H - 19 * mm,
         "a5c9f1e2b7d43086fa1c2e5b9d7408f3c6a1e4b8d2079c5f", "Helvetica", 6.5)
    sh.t(L + 2 * mm, H - 24 * mm, "Ack No :", "Helvetica-Bold", 6.5)
    sh.t(L + 14 * mm, H - 24 * mm, "172614938201456", "Helvetica", 6.5)
    sh.t(L + 62 * mm, H - 24 * mm, "Ack Date :", "Helvetica-Bold", 6.5)
    sh.t(L + 78 * mm, H - 24 * mm, d.date, "Helvetica", 6.5)
    sh.box(Rm - 26 * mm, H - 28 * mm, 22 * mm, 22 * mm)
    for i in range(6):
        for j in range(6):
            if (i * 7 + j * 3) % 4 < 2:
                sh.box(Rm - 25 * mm + i * 3.4 * mm,
                       H - 27 * mm + j * 3.4 * mm, 3 * mm, 3 * mm,
                       fill=colors.black, stroke=None)
    sh.t(W / 2, H - 36 * mm, d.title, "Helvetica-Bold", 11, align="c")
    # the e-invoice print carries the supplier's own number too
    sh.t(L + 2 * mm, H - 36 * mm, "Invoice No : " + d.number, "Helvetica", 7.5)
    sh.t(Rm - 2 * mm, H - 36 * mm, "Date : " + d.date, "Helvetica", 7.5,
         align="r")
    sh.box(L, H - 62 * mm, wid / 2, 22 * mm)
    sh.box(L + wid / 2, H - 62 * mm, wid / 2, 22 * mm)
    sh.t(L + 2 * mm, H - 45 * mm, "Supplier Details", "Helvetica-Bold", 7)
    sh.t(L + 2 * mm, H - 50 * mm, d.sup["name"], "Helvetica-Bold", 8.5)
    sh.t(L + 2 * mm, H - 54 * mm, "GSTIN: " + d.sup["gstin"], "Helvetica", 7)
    if d.sup["addr"]:
        sh.t(L + 2 * mm, H - 58 * mm, d.sup["addr"][-1], "Helvetica", 7)
    sh.t(L + wid / 2 + 2 * mm, H - 45 * mm, "Recipient Details",
         "Helvetica-Bold", 7)
    sh.t(L + wid / 2 + 2 * mm, H - 50 * mm, d.buy["name"], "Helvetica-Bold",
         8.5)
    if d.buy["gstin"]:
        sh.t(L + wid / 2 + 2 * mm, H - 54 * mm, "GSTIN: " + d.buy["gstin"],
             "Helvetica", 7)
    if d.buy["addr"]:
        sh.t(L + wid / 2 + 2 * mm, H - 58 * mm, d.buy["addr"][-1],
             "Helvetica", 7)
    y = table(sh, L, H - 66 * mm, wid, COLS_STD, HEAD_STD, items_std(sh, d),
              grid=True)
    ty = totals(sh, d, Rm - 2 * mm, y - 6 * mm, label="Total Invoice Value")
    sh.t(L + 2 * mm, ty - 6 * mm, d.words, "Helvetica", 7.5)
    footer(sh, d, 40 * mm, x=L + 2 * mm, W=wid - 4 * mm)
    sh.done()


def p17_bilingual(d, path):
    """Bilingual headings - English with Devanagari beneath. Supplier name
    appears twice."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 14 * mm, W - 14 * mm
    grey = colors.HexColor("#777777")
    DV = deva_font() or "Helvetica"

    def bi(x, y, en, hi, f="Helvetica-Bold", sz=7.5, align="l"):
        sh.t(x, y, en, f, sz, align=align)
        sh.t(x, y - 3.6 * mm, hi, DV, sz - 0.5, grey, align=align)

    sh.t(W / 2, H - 16 * mm, d.title, "Helvetica-Bold", 12, align="c")
    sh.t(W / 2, H - 21 * mm, "कर बिल", DV, 9, grey, align="c")
    sh.line(L, H - 25 * mm, Rm, H - 25 * mm)
    sh.t(L, H - 32 * mm, d.sup["name"], "Helvetica-Bold", 11)
    sh.t(L, H - 37 * mm, "पुरवठादार", DV, 8, grey)
    sh.t(L, H - 42.5 * mm, "GSTIN : " + d.sup["gstin"], "Helvetica", 7.5)
    if d.sup["addr"]:
        sh.t(L, H - 47 * mm, d.sup["addr"][-1], "Helvetica", 7.5)
    bi(Rm, H - 32 * mm, "Invoice No.", "बिल क्रमांक", "Helvetica", 7,
       align="r")
    sh.t(Rm, H - 40 * mm, d.number, "Helvetica-Bold", 9, align="r")
    bi(Rm, H - 46 * mm, "Date", "दिनांक", "Helvetica", 7, align="r")
    sh.t(Rm, H - 54 * mm, d.date, "Helvetica-Bold", 9, align="r")
    bi(L, H - 60 * mm, "Customer Details", "ग्राहक तपशील")
    sh.t(L, H - 69 * mm, d.buy["name"], "Helvetica-Bold", 10)
    if d.buy["gstin"]:
        sh.t(L, H - 74 * mm, "GSTIN : " + d.buy["gstin"], "Helvetica", 7.5)
    head = [("#", "l"), ("Item", "l"), ("HSN", "l"), ("Rate", "r"),
            ("Qty", "r"), ("Taxable", "r"), ("Tax", "r"), ("Amount", "r")]
    y = table(sh, L, H - 82 * mm, Rm - L, COLS_STD, head, items_std(sh, d))
    ty = totals(sh, d, Rm, y - 8 * mm, label="Amount Payable")
    sh.t(Rm - 52 * mm, ty - 4 * mm, "देय रक्कम", DV, 7.5, grey)
    sh.t(L, ty - 6 * mm, "In words : " + d.words, "Helvetica", 7.5)
    sh.t(L, ty - 10 * mm, "अक्षरी", DV, 7, grey)
    footer(sh, d, 40 * mm, x=L, W=Rm - L)
    sh.done()


def p18_landscape(d, path):
    """Rotated to landscape. Wider table, totals to the far right."""
    sh = Sheet(path, size=landscape(A4), title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 12 * mm, W - 12 * mm
    sh.t(L, H - 14 * mm, d.sup["name"], "Helvetica-Bold", 12)
    sh.t(L, H - 19 * mm, "GSTIN " + d.sup["gstin"], "Helvetica", 7.5)
    sh.t(L, H - 23.5 * mm, ", ".join(d.sup["addr"]), "Helvetica", 7.5)
    sh.t(W / 2, H - 14 * mm, d.title, "Helvetica-Bold", 13, align="c")
    sh.t(W / 2, H - 20 * mm, d.number + "    " + d.date, "Helvetica", 8.5,
         align="c")
    sh.t(Rm, H - 14 * mm, "Buyer", "Helvetica-Bold", 7.5, align="r")
    sh.t(Rm, H - 19 * mm, d.buy["name"], "Helvetica-Bold", 9.5, align="r")
    if d.buy["gstin"]:
        sh.t(Rm, H - 24 * mm, "GSTIN " + d.buy["gstin"], "Helvetica", 7.5,
             align="r")
    sh.line(L, H - 28 * mm, Rm, H - 28 * mm)
    # the table takes the left two-thirds; totals sit in the right third,
    # so the two never overlap on a 297mm page
    cols = [3, 8, 96, 118, 133, 152, 175, 194]
    y = table(sh, L, H - 34 * mm, 196 * mm, cols, HEAD_STD,
              items_std(sh, d, 7.5, 86 * mm), grid=True)
    ty = H - 40 * mm
    pairs = [("Taxable", fmt(d.taxable))]
    if d.inter:
        pairs.append(("IGST", fmt(d.igst)))
    else:
        pairs += [("CGST", fmt(d.cgst)), ("SGST", fmt(d.sgst))]
    pairs.append(("Round Off", fmt(d.round_off)))
    for lbl, v in pairs:
        sh.t(L + 204 * mm, ty, lbl, "Helvetica", 7.5)
        sh.t(Rm, ty, v, "Helvetica", 7.5, align="r")
        ty -= 4.4 * mm
    sh.line(L + 202 * mm, ty + 2 * mm, Rm, ty + 2 * mm)
    sh.t(L + 204 * mm, ty - 2 * mm, "Net Amount", "Helvetica-Bold", 9)
    sh.t(Rm, ty - 2 * mm, fmt(d.total), "Helvetica-Bold", 9, align="r")
    sh.t(L, y - 8 * mm, d.words, "Helvetica", 7.5)
    sh.t(Rm, 18 * mm, "For " + d.sup["name"], "Helvetica-Bold", 8, align="r")
    sh.done()


def p19_stamped(d, path):
    """Classic overprinted with a DUPLICATE watermark and a rubber stamp."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 12 * mm, W - 12 * mm
    sh.c.saveState()
    sh.c.translate(W / 2, H / 2)
    sh.c.rotate(38)
    sh.c.setFont("Helvetica-Bold", 40)
    sh.c.setFillColor(colors.HexColor("#e2e2e2"))
    sh.c.drawCentredString(0, 0, "DUPLICATE")
    sh.c.setFont("Helvetica-Bold", 15)
    sh.c.drawCentredString(0, -18 * mm, "FOR TRANSPORTER")
    sh.c.restoreState()
    sh.t(W / 2, H - 14 * mm, d.title, "Helvetica-Bold", 12, align="c")
    sh.t(Rm, H - 14 * mm, "DUPLICATE FOR TRANSPORTER", "Helvetica-Bold", 7,
         align="r")
    sh.box(L, 20 * mm, Rm - L, H - 40 * mm)
    y = H - 25 * mm
    sh.t(L + 3 * mm, y, d.sup["name"], "Helvetica-Bold", 11)
    sh.t(L + 3 * mm, y - 5 * mm, "GSTIN: " + d.sup["gstin"], "Helvetica", 8)
    for i, ln in enumerate(d.sup["addr"]):
        sh.t(L + 3 * mm, y - 9 * mm - i * 4 * mm, ln, "Helvetica", 8)
    mid = L + 108 * mm
    sh.t(mid + 3 * mm, y, "Invoice #:", "Helvetica", 7.5)
    sh.t(mid + 3 * mm, y - 4.5 * mm, d.number, "Helvetica-Bold", 9)
    sh.t(mid + 45 * mm, y, "Date:", "Helvetica", 7.5)
    sh.t(mid + 45 * mm, y - 4.5 * mm, d.date, "Helvetica-Bold", 9)
    sh.line(L, H - 52 * mm, Rm, H - 52 * mm)
    sh.t(L + 3 * mm, H - 57 * mm, "Consignee", "Helvetica-Bold", 7.5)
    sh.t(L + 3 * mm, H - 62 * mm, d.buy["name"], "Helvetica-Bold", 9.5)
    yy = H - 67 * mm
    if d.buy["gstin"]:
        sh.t(L + 3 * mm, yy, "GSTIN: " + d.buy["gstin"], "Helvetica", 7.5)
        yy -= 4 * mm
    for ln in d.buy["addr"][:2]:
        sh.t(L + 3 * mm, yy, ln, "Helvetica", 7.5)
        yy -= 4 * mm
    y = table(sh, L, H - 78 * mm, Rm - L, COLS_STD, HEAD_STD,
              items_std(sh, d))
    ty = totals(sh, d, Rm - 3 * mm, y - 6 * mm)
    sh.t(L + 2 * mm, ty - 8 * mm, d.words, "Helvetica", 7.5)
    sh.c.saveState()
    sh.c.translate(Rm - 34 * mm, 34 * mm)
    sh.c.rotate(-8)
    sh.c.setStrokeColor(colors.HexColor("#7a2020"))
    sh.c.setLineWidth(1.4)
    sh.c.rect(-22 * mm, -9 * mm, 44 * mm, 18 * mm)
    sh.c.setFillColor(colors.HexColor("#7a2020"))
    sh.c.setFont("Helvetica-Bold", 7)
    sh.c.drawCentredString(0, 2 * mm, d.sup["name"][:26])
    sh.c.setFont("Helvetica", 6.5)
    sh.c.drawCentredString(0, -3 * mm, "PUNE - 411002")
    sh.c.restoreState()
    sh.done()


def p20_continuation(d, path):
    """Forced onto two pages with carried / brought forward."""
    sh = Sheet(path, title=d.number)
    W, H = sh.W, sh.H
    L, Rm = 12 * mm, W - 12 * mm
    rows = list(d.rows)
    while len(rows) < 20:                 # ensure it really does break
        rows += list(d.rows)
    rows = rows[:26]
    split = 16

    def head_block(page):
        sh.t(W / 2, H - 14 * mm, d.title, "Helvetica-Bold", 12, align="c")
        sh.t(Rm, H - 14 * mm, "Page %d of 2" % page, "Helvetica", 7,
             align="r")
        sh.t(L, H - 22 * mm, d.sup["name"], "Helvetica-Bold", 10)
        sh.t(L, H - 27 * mm, "GSTIN " + d.sup["gstin"], "Helvetica", 7.5)
        sh.t(Rm, H - 22 * mm, d.number, "Helvetica-Bold", 9, align="r")
        sh.t(Rm, H - 27 * mm, d.date, "Helvetica", 8, align="r")
        who = d.buy["name"] + ("   GSTIN " + d.buy["gstin"]
                               if d.buy["gstin"] else "")
        sh.t(L, H - 34 * mm, "Party: " + who, "Helvetica", 8)
        sh.line(L, H - 38 * mm, Rm, H - 38 * mm)

    def body_for(chunk, start):
        return [[(str(i), "l"),
                 (sh.clip(r["d"], "Helvetica", 7.5, 76 * mm), "l"),
                 (r["h_txt"], "l"), (r["r_txt"], "r"),
                 (r["q_txt"], "r"), (fmt(r["tv"]), "r"),
                 (fmt(r["tx"]), "r"), (fmt(r["amt"]), "r")]
                for i, r in enumerate(chunk, start)]

    head_block(1)
    first = rows[:split]
    y = table(sh, L, H - 44 * mm, Rm - L, COLS_STD, HEAD_STD,
              body_for(first, 1))
    cf = sum(r["amt"] for r in first)
    y -= 5 * mm
    sh.t(Rm - 60 * mm, y, "Carried Forward", "Helvetica-Bold", 8.5)
    sh.t(Rm, y, fmt(cf), "Helvetica-Bold", 8.5, align="r")
    sh.c.showPage()

    head_block(2)
    sh.t(L + 2 * mm, H - 44 * mm, "Brought Forward", "Helvetica-Bold", 8.5)
    sh.t(Rm, H - 44 * mm, fmt(cf), "Helvetica-Bold", 8.5, align="r")
    rest = rows[split:]
    y = table(sh, L, H - 50 * mm, Rm - L, COLS_STD, HEAD_STD,
              body_for(rest, split + 1))
    tv = sum(r["tv"] for r in rows)
    tx = sum(r["tx"] for r in rows)
    # print one rounded half on both sides, and let the total follow from it,
    # so CGST and SGST can never differ by a paisa
    half = half_tax(tx)
    tot = round(tv + half * 2)
    ty = y - 8 * mm
    for lbl, v in (("Taxable Amount", fmt(tv)), ("CGST", fmt(half)),
                   ("SGST", fmt(half))):
        sh.t(Rm - 52 * mm, ty, lbl, "Helvetica", 8)
        sh.t(Rm, ty, v, "Helvetica", 8, align="r")
        ty -= 4.4 * mm
    sh.line(Rm - 54 * mm, ty + 2 * mm, Rm, ty + 2 * mm)
    sh.t(Rm - 52 * mm, ty - 2 * mm, "Grand Total", "Helvetica-Bold", 9.5)
    sh.t(Rm, ty - 2 * mm, fmt(tot), "Helvetica-Bold", 9.5, align="r")
    footer(sh, d, 40 * mm, x=L, W=Rm - L)
    sh.done()


# ---------------------------------------------------------------- registry
# id, label, function. "classic" is drawn by render.py and has no function.

PATTERNS = [
    ("classic", "Classic", None),
    ("tally", "Tally Default", p02_tally),
    ("modern", "Modern Sans", p03_modern),
    ("compact", "Compact", p04_compact),
    ("boxed", "Boxed Grid", p05_boxed),
    ("minimal", "Minimal", p06_minimal),
    ("letterhead", "Letterhead", p07_letterhead),
    ("twocolumn", "Two-Column Header", p08_twocol),
    ("serif", "Serif Formal", p09_serif),
    ("widetable", "Wide Table", p10_wide),
    ("billship", "Bill To / Ship To", p11_billship),
    ("nosummary", "No Tax Summary", p12_nosummary),
    ("rightalign", "Right Aligned", p13_rightalign),
    ("thermal", "Thermal / Narrow", p14_thermal),
    ("legacy", "Legacy Software", p15_legacy),
    ("portal", "GST Portal", p16_portal),
    ("bilingual", "Bilingual", p17_bilingual),
    ("landscape", "Landscape", p18_landscape),
    ("stamped", "Stamped Duplicate", p19_stamped),
    ("continuation", "Continuation (2 pages)", p20_continuation),
]

BY_ID = {p[0]: p for p in PATTERNS}
ALL_IDS = [p[0] for p in PATTERNS]

# what each layout is called in a filename - readable, and safe on Windows
FILE_TAG = {
    "classic": "Classic", "tally": "Tally", "modern": "Modern",
    "compact": "Compact", "boxed": "Boxed", "minimal": "Minimal",
    "letterhead": "Letterhead", "twocolumn": "TwoColumn",
    "serif": "Serif", "widetable": "WideTable",
    "billship": "BillToShipTo", "nosummary": "NoSummary",
    "rightalign": "RightAligned", "thermal": "Thermal",
    "legacy": "Legacy", "portal": "GSTPortal",
    "bilingual": "Bilingual", "landscape": "Landscape",
    "stamped": "Stamped", "continuation": "Continuation",
}


def tag(pid):
    """The filename suffix for a layout."""
    return FILE_TAG.get(pid, pid.capitalize())


def label(pid):
    return BY_ID[pid][1]


def draw(pid, inv, t, seller, path):
    """Render one invoice in one pattern. Classic falls back to render.py."""
    fn = BY_ID[pid][2]
    if fn is None:
        from .render import render as classic
        classic(inv, t, seller, path)
        return
    fn(Doc(inv, t, seller), path)
