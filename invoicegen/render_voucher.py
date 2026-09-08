"""Render a receipt, payment or contra voucher.

These are small slips, not invoices: a party, an amount, how it was paid, and
the bills it settles. Kept separate from the invoice renderer because almost
nothing about the layout is shared.
"""
import random

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas

from .model import fmt, rupees_in_words

W, H = A4
L, R = 18 * mm, W - 18 * mm
TOP = H - 18 * mm


def _wrap(c, text, font, size, width):
    words, out, cur = text.split(), [], ""
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


def render_voucher(txn, seller, path):
    c = pdfcanvas.Canvas(path, pagesize=A4)
    c.setTitle(txn.number)
    m = txn.meta

    # a voucher occupies the top half of the sheet, as printed in practice
    box_top = TOP
    box_bottom = H / 2 - 10 * mm
    c.setLineWidth(0.8)
    c.rect(L, box_bottom, R - L, box_top - box_bottom)

    # ---- header
    y = box_top - 8 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawString(L + 5 * mm, y, seller["name"])
    c.setFont("Helvetica", 8)
    y -= 4.5 * mm
    for ln in seller["addr"]:
        c.drawString(L + 5 * mm, y, ln)
        y -= 3.8 * mm
    c.drawString(L + 5 * mm, y, f"GSTIN: {seller['gstin']}")

    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(R - 5 * mm, box_top - 8 * mm, txn.title)
    c.setFont("Helvetica", 8.5)
    c.drawRightString(R - 5 * mm, box_top - 14 * mm, f"No: {txn.number}")
    c.drawRightString(R - 5 * mm, box_top - 19 * mm,
                      f"Date: {txn.date.strftime('%d %b %Y')}")

    y -= 6 * mm
    c.line(L, y, R, y)

    # ---- who, and how much
    y -= 8 * mm
    receipt = txn.kind == "receipt"
    # a journal, like a contra, has no counterparty - it is a pure Dr/Cr entry
    contra = txn.kind in ("contra", "journal")
    c.setFont("Helvetica", 9.5)
    if contra:
        label = "Being"
    else:
        label = "Received from" if receipt else "Paid to"
    c.drawString(L + 5 * mm, y, label)
    c.setFont("Helvetica-Bold", 11)
    who = txn.party["name"] if txn.party else txn.narration
    # narrations already open with "Being ..."; don't print the word twice
    if not txn.party and who.lower().startswith("being "):
        who = who[6:]
    c.drawString(L + 34 * mm, y, who[:56])

    if txn.party and txn.party.get("gstin"):
        y -= 5 * mm
        c.setFont("Helvetica", 8)
        c.drawString(L + 34 * mm, y, f"GSTIN: {txn.party['gstin']}")

    # amount in a boxed panel, the way a printed voucher shows it
    y -= 10 * mm
    amt = m["amount"]
    c.setFillColor(colors.HexColor("#f2f4f7"))
    c.rect(L + 5 * mm, y - 3 * mm, R - L - 10 * mm, 13 * mm, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    c.drawString(L + 9 * mm, y + 4 * mm, "Amount")
    c.setFont("Helvetica-Bold", 15)
    c.drawRightString(R - 9 * mm, y + 3 * mm, f"Rs {fmt(amt)}")

    y -= 9 * mm
    c.setFont("Helvetica", 8.5)
    words = rupees_in_words(amt)
    for ln in _wrap(c, f"({words})", "Helvetica", 8.5, R - L - 14 * mm):
        y -= 4.5 * mm
        c.drawString(L + 5 * mm, y, ln)

    # ---- how it moved. A journal moves no money, so it has no mode.
    if m.get("mode"):
        y -= 8 * mm
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(L + 5 * mm, y, "Mode:")
        c.setFont("Helvetica", 8.5)
        c.drawString(L + 22 * mm, y, m.get("mode", "-"))
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(L + 70 * mm, y, "Account:")
        c.setFont("Helvetica", 8.5)
        c.drawString(L + 88 * mm, y, m.get("instrument", "-"))

    if m.get("cheque"):
        ch = m["cheque"]
        y -= 5 * mm
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(L + 5 * mm, y, "Cheque:")
        c.setFont("Helvetica", 8.5)
        c.drawString(L + 22 * mm, y,
                     f"{ch['number']}  dt. {ch['date']}  -  {ch['bank']}")

    # ---- bills settled
    bills = m.get("bills") or []
    if bills:
        y -= 8 * mm
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(L + 5 * mm, y, "Against Bills")
        y -= 1.5 * mm
        c.line(L + 5 * mm, y, L + 110 * mm, y)
        c.setFont("Helvetica", 8)
        for b in bills:
            y -= 4.5 * mm
            c.drawString(L + 7 * mm, y, b["ref"])
            c.drawRightString(L + 108 * mm, y, fmt(b["amount"]))
        y -= 1.5 * mm
        c.line(L + 5 * mm, y, L + 110 * mm, y)
    elif m.get("method"):
        y -= 6 * mm
        c.setFont("Helvetica", 8.5)
        c.drawString(L + 5 * mm, y, f"Method: {m['method']}")

    # ---- narration and signature
    ny = box_bottom + 20 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawString(L + 5 * mm, ny, "Narration:")
    c.setFont("Helvetica", 8)
    ny -= 4.5 * mm
    for ln in _wrap(c, txn.narration, "Helvetica", 8, 105 * mm):
        c.drawString(L + 5 * mm, ny, ln)
        ny -= 4 * mm

    c.setFont("Helvetica", 8.5)
    c.drawRightString(R - 8 * mm, box_bottom + 16 * mm,
                      f"For {seller['name']}")
    c.line(R - 55 * mm, box_bottom + 8 * mm, R - 8 * mm, box_bottom + 8 * mm)
    c.setFont("Helvetica", 7.5)
    c.drawRightString(R - 8 * mm, box_bottom + 4 * mm, "Authorised Signatory")
    c.drawString(L + 5 * mm, box_bottom + 4 * mm,
                 "Receiver's Signature" if txn.kind == "payment" else "")

    c.setFont("Helvetica", 6.5)
    c.drawCentredString(W / 2, box_bottom - 6 * mm,
                        "This is a computer generated voucher.")
    c.showPage()
    c.save()
