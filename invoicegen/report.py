"""Render statement-style documents: GST summary, Outstanding, Trial
Balance, Profit & Loss, Balance Sheet, Stock Journal.

These are registers rather than vouchers - a title, a column header, rows,
and a total - so one generic renderer covers them all.
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas

from .model import fmt

W, H = A4
L, R = 15 * mm, W - 15 * mm


def _wrap(c, text, font, size, width):
    words, out, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if c.stringWidth(t, font, size) <= width or not cur:
            cur = t
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


def render_report(spec, seller, path):
    """`spec` describes the report:

        title      the heading
        subtitle   the period or basis
        columns    [(label, width_mm, align)]
        sections   [(section title or None, [row, ...])]
        totals     [(label, [cell, ...])]
        note       optional closing line
    """
    c = pdfcanvas.Canvas(path, pagesize=A4)
    c.setTitle(spec["title"])
    cols = spec["columns"]

    def header():
        y = H - 16 * mm
        c.setFont("Helvetica-Bold", 12)
        c.drawString(L, y, seller["name"])
        c.setFont("Helvetica", 8)
        y -= 4.5 * mm
        for ln in seller["addr"]:
            c.drawString(L, y, ln)
            y -= 3.8 * mm
        c.drawString(L, y, "GSTIN: " + seller["gstin"])

        c.setFont("Helvetica-Bold", 14)
        c.drawRightString(R, H - 16 * mm, spec["title"])
        c.setFont("Helvetica", 8.5)
        c.drawRightString(R, H - 22 * mm, spec.get("subtitle", ""))
        y -= 6 * mm
        c.setLineWidth(0.8)
        c.line(L, y, R, y)
        return y - 7 * mm

    def col_x():
        """Right edge of each column, laid out from the left margin."""
        xs, x = [], L
        for _label, w, _a in cols:
            x += w * mm
            xs.append(x)
        return xs

    xs = col_x()

    def col_head(y):
        c.setFont("Helvetica-Bold", 8)
        for (label, w, align), x in zip(cols, xs):
            if align == "l":
                c.drawString(x - w * mm, y, label)
            else:
                c.drawRightString(x - 1.5 * mm, y, label)
        y -= 1.8 * mm
        c.line(L, y, R, y)
        return y - 4.5 * mm

    def row(y, cells, bold=False, size=8):
        # every cell of a row shares one baseline, so text extraction keeps
        # whole rows together rather than interleaving neighbouring columns
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        for (label, w, align), x, cell in zip(cols, xs, cells):
            if cell is None or cell == "":
                continue
            if align == "l":
                txt = str(cell)
                avail = w * mm - 2 * mm
                while (c.stringWidth(txt, "Helvetica", size) > avail
                       and len(txt) > 4):
                    txt = txt[:-2]
                c.drawString(x - w * mm, y, txt)
            else:
                c.drawRightString(x - 1.5 * mm, y, str(cell))
        return y - 4.6 * mm

    y = header()
    y = col_head(y)

    for title, rows in spec["sections"]:
        if y < 40 * mm:
            c.showPage()
            y = col_head(header())
        if title:
            y -= 1.5 * mm
            c.setFillColor(colors.HexColor("#eef2f7"))
            c.rect(L, y - 1.2 * mm, R - L, 5.4 * mm, stroke=0, fill=1)
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 8.5)
            c.drawString(L + 1.5 * mm, y, title)
            y -= 6.5 * mm
        for cells in rows:
            if y < 32 * mm:
                c.showPage()
                y = col_head(header())
            y = row(y, cells)

    if spec.get("totals"):
        y -= 1 * mm
        c.line(L, y + 2 * mm, R, y + 2 * mm)
        y -= 2 * mm
        for cells in spec["totals"]:
            y = row(y, cells, bold=True, size=9)
        c.line(L, y + 2.5 * mm, R, y + 2.5 * mm)
        c.line(L, y + 3.2 * mm, R, y + 3.2 * mm)

    if spec.get("note"):
        y -= 6 * mm
        c.setFont("Helvetica-Oblique", 7.5)
        for ln in _wrap(c, spec["note"], "Helvetica-Oblique", 7.5, R - L):
            c.drawString(L, y, ln)
            y -= 3.6 * mm

    c.setFont("Helvetica", 6.5)
    c.drawCentredString(W / 2, 12 * mm,
                        "This is a computer generated statement.")
    c.showPage()
    c.save()
