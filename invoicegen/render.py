"""PDF renderer - Abhidnya Enterprises tax-invoice layout.

Rows are drawn on a single baseline per line item so that text extraction
recovers whole rows; long descriptions shrink to fit rather than wrapping and
pushing their own row's columns out of alignment.
"""
import random

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas

from .model import fmt, half_tax, money

W, H = A4
L, R = 10 * mm, W - 10 * mm
BOTTOM = 20 * mm


def _scan_page(c, rng):
    """Speckle, blotches and edge shadow - drawn under the text."""
    c.saveState()
    # uneven paper tone
    c.setFillColorRGB(0.965, 0.957, 0.94)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    # dust and toner specks
    for _ in range(int(rng.uniform(500, 1100))):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        g = rng.uniform(0.55, 0.86)
        c.setFillColorRGB(g, g, g)
        r = rng.uniform(0.15, 0.75)
        c.circle(x, y, r, stroke=0, fill=1)
    # faint blotches, as from uneven pressure on the glass
    for _ in range(rng.randint(3, 8)):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        g = rng.uniform(0.88, 0.95)
        c.setFillColorRGB(g, g, g)
        c.circle(x, y, rng.uniform(12, 46), stroke=0, fill=1)
    # dark scanner edge down one or two sides
    for side in rng.sample(["l", "r", "t", "b"], rng.randint(1, 2)):
        for i in range(16):
            g = 0.55 + i * 0.027
            c.setFillColorRGB(g, g, g)
            w = 1.4
            if side == "l":
                c.rect(i * w, 0, w, H, stroke=0, fill=1)
            elif side == "r":
                c.rect(W - (i + 1) * w, 0, w, H, stroke=0, fill=1)
            elif side == "t":
                c.rect(0, H - (i + 1) * w, W, w, stroke=0, fill=1)
            else:
                c.rect(0, i * w, W, w, stroke=0, fill=1)
    c.restoreState()


def _wrap(c, text, font, size, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if c.stringWidth(trial, font, size) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


class Renderer:
    def __init__(self, inv, t, seller, path):
        self.inv, self.t, self.s = inv, t, seller
        self.c = pdfcanvas.Canvas(path, pagesize=A4)
        self.c.setTitle(inv["number"])
        self.page = 0
        self.pages_total = 1
        # "scanned" degrades the page the way a photocopy or phone snap does:
        # slight skew, uneven ink, speckle and a dark scanner edge.
        self.scanned = bool(inv.get("scanned"))
        self.rng = random.Random(inv.get("scan_seed", 0))
        self.ink = 0.0
        if self.scanned:
            self.ink = self.rng.uniform(0.16, 0.34)   # faded toner

    # ---------------------------------------------------------- header

    def begin_page(self):
        """Paint the scan artefacts and tilt the page before any content."""
        if not self.scanned:
            return
        _scan_page(self.c, self.rng)
        self.c.saveState()
        # a degree of skew, as if fed in crooked, plus a small offset
        ang = self.rng.uniform(-0.9, 0.9)
        self.c.translate(W / 2, H / 2)
        self.c.rotate(ang)
        self.c.translate(-W / 2 + self.rng.uniform(-4, 4),
                         -H / 2 + self.rng.uniform(-4, 4))
        g = self.ink
        self.c.setFillColorRGB(g, g, g)
        self.c.setStrokeColorRGB(min(g + 0.25, 0.7), min(g + 0.25, 0.7),
                                 min(g + 0.25, 0.7))

    def end_page(self):
        if self.scanned:
            self.c.restoreState()

    def header(self):
        c, inv, s = self.c, self.inv, self.s
        self.page += 1
        y = H - 10 * mm
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(W / 2, y, inv.get("doc_title", "TAX INVOICE"))
        c.setFont("Helvetica", 7)
        c.drawRightString(R, y, "" if inv.get("is_order")
                          else "ORIGINAL FOR RECIPIENT")
        if self.t["reverse_charge"]:
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(L, y, "REVERSE CHARGE APPLICABLE")
        y -= 5 * mm
        c.setLineWidth(0.7)
        c.rect(L, BOTTOM, R - L, y - BOTTOM)
        top = y

        mid = L + 108 * mm
        c.line(mid, top, mid, top - 30 * mm)
        yy = top - 5 * mm
        # Whose document this is. On purchase-side documents our own firm is
        # the buyer placing the order, so say so rather than leaving the
        # letterhead to read like a seller's.
        # A logo, when there is one, sits in the corner and the name shifts
        # right to clear it.
        from .logo import draw as draw_logo
        lx = draw_logo(c, inv.get("logo"), L + 3 * mm, yy + 2 * mm)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(L + 3 * mm + lx, yy,
                     "Buyer (Ordered By):"
                     if inv.get("letterhead_is_buyer") else "Seller:")
        yy -= 3.4 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(L + 3 * mm + lx, yy, s["name"])
        yy -= 4.5 * mm
        c.setFont("Helvetica", 8)
        # only print a label when there is something to put after it - a
        # manually entered invoice may leave the phone or GSTIN blank
        head = []
        if s.get("gstin"):
            head.append(f"GSTIN: {s['gstin']}")
        head += [a for a in s.get("addr", []) if str(a).strip()]
        if s.get("mobile"):
            head.append(f"Mobile: {s['mobile']}")
        for ln in head:
            c.drawString(L + 3 * mm + lx, yy, ln)
            yy -= 3.6 * mm

        yy = top - 5 * mm
        c.setFont("Helvetica", 7.5)
        order = inv.get("is_order")
        c.drawString(mid + 3 * mm, yy, "Order #:" if order else "Invoice #:")
        c.drawString(mid + 42 * mm, yy,
                     "Order Date:" if order else "Invoice Date:")
        yy -= 4.2 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(mid + 3 * mm, yy, inv["number"])
        c.drawString(mid + 42 * mm, yy, inv["date"])
        yy -= 6 * mm
        c.setFont("Helvetica", 7.5)
        c.drawString(mid + 3 * mm, yy, "Place of Supply:")
        yy -= 4.2 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(mid + 3 * mm, yy, inv["place_of_supply"])
        if inv.get("eway_bill"):
            yy -= 5 * mm
            c.setFont("Helvetica", 7.5)
            c.drawString(mid + 3 * mm, yy, f"E-Way Bill: {inv['eway_bill']}")

        # party block
        y = top - 31 * mm
        c.line(L, y, R, y)
        c.line(mid, y, mid, y - 33 * mm)
        b = inv["buyer"]
        yy = y - 4.5 * mm
        c.setFont("Helvetica-Bold", 7.5)
        purchase = inv.get("is_purchase")
        c.drawString(L + 3 * mm, yy,
                     "Supplier Details:" if purchase else "Customer Details:")
        c.drawString(mid + 3 * mm, yy,
                     "Despatched From:" if purchase else "Shipping Address:")
        yy -= 4.2 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(L + 3 * mm, yy, b["name"])
        c.drawString(mid + 3 * mm, yy, b["name"])
        ys = yy - 4 * mm
        yy -= 4 * mm
        c.setFont("Helvetica", 7.5)
        if b.get("gstin"):
            c.drawString(L + 3 * mm, yy, f"GSTIN: {b['gstin']}")
        else:
            c.drawString(L + 3 * mm, yy, "GSTIN: Unregistered")
        for ln in b["ship"]:
            c.drawString(mid + 3 * mm, ys, ln)
            ys -= 3.6 * mm
        yy -= 4.5 * mm
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(L + 3 * mm, yy, "Billing Address:")
        yy -= 4 * mm
        c.setFont("Helvetica", 7.5)
        for ln in b["bill"]:
            c.drawString(L + 3 * mm, yy, ln)
            yy -= 3.6 * mm
        if b.get("phone"):
            c.drawString(L + 3 * mm, yy, f"Ph: {b['phone']}")
        if inv.get("reference"):
            ys -= 1.5 * mm
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(mid + 3 * mm, ys, "Reference:")
            ys -= 4 * mm
            c.setFont("Helvetica", 7.5)
            c.drawString(mid + 3 * mm, ys, inv["reference"])
        if inv.get("order_terms"):
            ot = inv["order_terms"]
            ys -= 4.5 * mm
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(mid + 3 * mm, ys, "Delivery Date:")
            c.setFont("Helvetica", 7.5)
            c.drawString(mid + 26 * mm, ys, ot["delivery_date"])
            ys -= 4 * mm
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(mid + 3 * mm, ys, "Payment Terms:")
            ys -= 3.6 * mm
            c.setFont("Helvetica", 7)
            for ln in _wrap(c, ot["payment_terms"], "Helvetica", 7, 72 * mm):
                c.drawString(mid + 3 * mm, ys, ln)
                ys -= 3.4 * mm
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(mid + 3 * mm, ys, "Delivery Terms:")
            ys -= 3.6 * mm
            c.setFont("Helvetica", 7)
            c.drawString(mid + 3 * mm, ys, ot["delivery_terms"])
            ys -= 3.4 * mm
        if inv.get("original_invoice"):
            oi = inv["original_invoice"]
            ys -= 4.5 * mm
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(mid + 3 * mm, ys, "Against Original Invoice:")
            ys -= 4 * mm
            c.setFont("Helvetica", 7.5)
            c.drawString(mid + 3 * mm, ys, f"{oi['number']}  dt. {oi['date']}")
            ys -= 4 * mm
            for ln in _wrap(c, f"Reason: {oi['reason']}", "Helvetica", 7,
                            72 * mm):
                c.drawString(mid + 3 * mm, ys, ln)
                ys -= 3.4 * mm
        if inv.get("irn"):
            ys -= 4 * mm
            c.setFont("Helvetica", 6)
            c.drawString(mid + 3 * mm, ys, f"IRN: {inv['irn'][:32]}")
            ys -= 3 * mm
            c.drawString(mid + 3 * mm, ys, f"     {inv['irn'][32:]}")

        # the party block must clear whichever column ran longer, so a note's
        # extra "against original invoice" lines cannot collide with the table
        return min(y - 35 * mm, min(yy, ys) - 4 * mm)

    def table_head(self, y):
        c, inter = self.c, self.t["interstate"]
        c.line(L, y, R, y)
        # A Discount column only earns its place when something is discounted;
        # otherwise the item description gets the room instead.
        self.show_disc = any(l.discount_pct for l in self.inv["lines"])
        if self.show_disc:
            #  #   item   HSN    rate   qty   disc%  taxable  tax  amount
            self.X = [L + 2 * mm, L + 7 * mm, L + 70 * mm, L + 90 * mm,
                      L + 106 * mm, L + 120 * mm, L + 144 * mm, L + 170 * mm,
                      R - 2 * mm]
        else:
            # the HSN sits left-aligned at 80mm, so the rate that follows
            # needs clear air after an 8-digit code
            self.X = [L + 2 * mm, L + 7 * mm, L + 78 * mm, L + 108 * mm,
                      L + 126 * mm, None, L + 150 * mm, L + 172 * mm,
                      R - 2 * mm]
        X = self.X
        hy = y - 4.5 * mm
        c.setFont("Helvetica-Bold", 7)
        c.drawString(X[0], hy, "#")
        c.drawString(X[1], hy, "Item")
        c.drawString(X[2], hy, "HSN/SAC")
        c.drawRightString(X[3], hy, "Rate / Item")
        c.drawRightString(X[4], hy, "Qty")
        if self.show_disc:
            c.drawRightString(X[5], hy, "Discount")
        c.drawRightString(X[6], hy, "Taxable Value")
        c.drawRightString(X[7], hy, "IGST" if inter else "Tax Amount")
        c.drawRightString(X[8], hy, "Amount")
        y = hy - 2 * mm
        c.line(L, y, R, y)
        return y

    def row(self, y, i, l):
        c, X = self.c, self.X
        dsize, avail = 7.2, X[2] - X[1] - 2 * mm
        while dsize > 5.0 and c.stringWidth(l.desc, "Helvetica", dsize) > avail:
            dsize -= 0.2
        desc = _wrap(c, l.desc, "Helvetica", dsize, avail)

        base = y - 4.2 * mm
        c.setFont("Helvetica", 7.2)
        c.drawString(X[0], base, str(i))
        c.setFont("Helvetica", dsize)
        c.drawString(X[1], base, desc[0])
        c.setFont("Helvetica", 7.2)
        c.drawString(X[2], base, l.code or "-")
        # With a Discount column the rate shown is the list price, and the
        # discount is deducted from gross to reach the taxable value:
        #     rate x qty  -  discount  =  taxable value
        # A charge (freight, packing) has no quantity or unit rate
        qty_txt = "-" if l.qty is None else f"{l.qty:g} {l.uom}".strip()
        if self.show_disc:
            c.drawRightString(X[3], base,
                              "-" if l.mrp is None else fmt(l.mrp))
            c.drawRightString(X[4], base, qty_txt)
            if l.discount_pct:
                c.drawRightString(X[5], base, f"{l.discount_pct:g}%")
            else:
                c.drawRightString(X[5], base, "-")
        else:
            c.drawRightString(X[3], base,
                              "-" if l.rate is None else fmt(l.rate))
            c.drawRightString(X[4], base, qty_txt)
        c.drawRightString(X[6], base, fmt(l.taxable))
        tx = f"{fmt(l.tax)} ({l.gst:g}%)"
        if l.cess_pct:
            tx += f" +{fmt(l.cess)} cess"
        c.drawRightString(X[7], base, tx)
        # Charge.amount is the pre-tax figure (the accounting code posts it
        # that way), so the gross for the Amount column comes from line_total.
        c.drawRightString(X[8], base,
                          fmt(getattr(l, "line_total", None) or l.amount))

        cont = base
        extra = []
        if l.discount_pct and not self.show_disc:
            extra.append(("mrp", f"{fmt(l.mrp)} (-{l.discount_pct:g}%)"))
        if l.godown:
            extra.append(("note", f"Godown: {l.godown}"))
        if l.batch:
            extra.append(("note", f"Batch: {l.batch}"))
        rows = max(len(desc) - 1, len(extra))
        for k in range(rows):
            cont -= 3.4 * mm
            if k + 1 < len(desc):
                c.setFont("Helvetica", dsize)
                c.drawString(X[1], cont, desc[k + 1])
            if k < len(extra):
                kind, txt = extra[k]
                c.setFont("Helvetica", 6.2)
                c.setFillColor(colors.grey)
                if kind == "mrp":
                    c.drawRightString(X[3], cont, txt)
                else:
                    c.drawString(X[2], cont, txt)
                c.setFillColor(colors.black)
            c.setFont("Helvetica", 7.2)
        y = cont - 1.2 * mm
        c.setStrokeColor(colors.lightgrey)
        c.line(L, y, R, y)
        c.setStrokeColor(colors.black)
        return y

    # ---------------------------------------------------------- footer

    def totals_block(self, y):
        c, t, inv = self.c, self.t, self.inv
        X = self.X

        y -= 4 * mm
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(X[0], y, f"Total Items / Qty : {t['count']} / {t['qty']:g}")
        c.setFont("Helvetica", 7.5)
        if self.show_disc:
            c.drawRightString(X[5], y, fmt(t["discount"]))
        c.drawRightString(X[6], y, fmt(t["taxable"]))
        c.drawRightString(X[7], y, fmt(t["tax"]))
        c.drawRightString(X[8], y,
                          fmt(money(t["taxable"] + t["tax"] + t["cess"])))
        y -= 2 * mm
        c.line(L, y, R, y)

        # HSN summary on the left
        sy = y - 5 * mm
        inter = t["interstate"]
        c.setFont("Helvetica-Bold", 7)
        c.drawString(L + 2 * mm, sy, "HSN/SAC")
        c.drawRightString(L + 40 * mm, sy, "Taxable Value")
        if inter:
            c.drawRightString(L + 58 * mm, sy, "IGST Rate")
            c.drawRightString(L + 80 * mm, sy, "IGST Amount")
        else:
            c.drawRightString(L + 66 * mm, sy, "CGST")
            c.drawRightString(L + 90 * mm, sy, "SGST")
        c.drawRightString(L + 110 * mm, sy, "Total Tax")
        sy -= 1.5 * mm
        c.line(L, sy, L + 112 * mm, sy)
        c.setFont("Helvetica", 7)
        for s in t["summary"]:
            sy -= 4 * mm
            half = half_tax(s["tax"])
            c.drawString(L + 2 * mm, sy, s["code"])
            c.drawRightString(L + 40 * mm, sy, fmt(s["taxable"]))
            if inter:
                c.drawRightString(L + 58 * mm, sy, f"{s['gst']:g}%")
                c.drawRightString(L + 80 * mm, sy, fmt(s["tax"]))
            else:
                c.drawRightString(L + 66 * mm, sy,
                                  f"{s['gst'] / 2:g}%  {fmt(half)}")
                c.drawRightString(L + 90 * mm, sy,
                                  f"{s['gst'] / 2:g}%  {fmt(half)}")
            c.drawRightString(L + 110 * mm, sy, fmt(s["tax"]))
        sy -= 1.5 * mm
        c.line(L, sy, L + 112 * mm, sy)

        # totals on the right
        lbl, val = R - 62 * mm, R - 3 * mm
        rows = [("Taxable Amount", fmt(t["taxable"]))]
        for ch in inv.get("charges", []):
            rows.append((ch.label, fmt(ch.amount)))
        if t["reverse_charge"]:
            rows.append(("Tax under RCM (by recipient)", fmt(t["tax"])))
        elif t["interstate"]:
            rows.append(("IGST", fmt(t["igst"])))
        else:
            rows.append(("CGST", fmt(t["cgst"])))
            rows.append(("SGST", fmt(t["sgst"])))
        if t["cess"]:
            rows.append(("Cess", fmt(t["cess"])))
        if t["discount"]:
            # Already deducted on the lines to reach the taxable value, so it
            # must not read like another subtraction from the running total.
            rows.append(("Trade Discount (already deducted)",
                         fmt(t["discount"])))
        if t.get("cash_discount"):
            rows.append(("Less: Cash Discount",
                         f"({fmt(t['cash_discount'])})"))
        if t.get("customs_duty"):
            rows.append(("Customs Duty", fmt(t["customs_duty"])))
        if t["tcs"]:
            rows.append(("TCS @ 0.1%", fmt(t["tcs"])))
        if t["tds"]:
            rows.append((f"Less: TDS {inv['tds']['section']}",
                         f"({fmt(t['tds'])})"))
        if t["advance"]:
            rows.append(("Less: Advance", f"({fmt(t['advance'])})"))
        rows.append(("Round Off", fmt(t["round_off"])))

        ty = y - 5 * mm
        c.setFont("Helvetica", 7.5)
        for a, bl in rows:
            c.drawString(lbl, ty, a)
            c.drawRightString(val, ty, bl)
            ty -= 4.2 * mm
        c.line(lbl - 2 * mm, ty + 1.8 * mm, val, ty + 1.8 * mm)
        ty -= 1 * mm
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(lbl, ty, "Total")
        c.drawRightString(val, ty, fmt(t["total"]))
        ty -= 5.5 * mm
        c.setFont("Helvetica-Bold", 9)
        is_order = inv.get("is_order")
        c.drawString(lbl, ty, "Estimated Value:" if is_order
                     else "Amount Payable:")
        c.drawRightString(val, ty, fmt(t["total"]))
        if is_order:
            # an order commits to a purchase; it is not a tax document
            ty -= 4.5 * mm
            c.setFont("Helvetica-Oblique", 6.3)
            c.drawString(lbl, ty, "Taxes indicative only. Not a tax invoice")
            ty -= 3 * mm
            c.drawString(lbl, ty, "and not a demand for payment.")

        wy = min(sy, ty) - 6 * mm
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(L + 2 * mm, wy, "Total amount (in words):")
        c.setFont("Helvetica", 7.5)
        for ln in _wrap(c, t["words"], "Helvetica", 7.5, 115 * mm):
            wy -= 4 * mm
            c.drawString(L + 2 * mm, wy, ln)

        if inv.get("bill_wise"):
            bw = inv["bill_wise"]
            wy -= 5 * mm
            c.setFont("Helvetica", 7)
            c.drawString(L + 2 * mm, wy,
                         f"Bill-wise: {bw['method']} - {bw['reference']}  |  "
                         f"Credit {bw['credit_days']} days  |  "
                         f"Due {bw['due_date']}")
        return wy

    def footer(self):
        c, s = self.c, self.s
        # A manually entered invoice may carry no bank details at all, so the
        # block is skipped rather than printed empty.
        bk = s.get("bank") or {}
        by = 58 * mm
        if bk.get("name"):
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(L + 2 * mm, by, "Bank Details:")
            c.setFont("Helvetica", 7.5)
            for ln in [f"Bank:        {bk.get('name', '')}",
                       f"Account #:   {bk.get('account', '')}",
                       f"IFSC Code:   {bk.get('ifsc', '')}",
                       f"Branch:      {bk.get('branch', '')}"]:
                by -= 3.8 * mm
                c.drawString(L + 2 * mm, by, ln)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawRightString(R - 3 * mm, 58 * mm, f"For {s['name']}")
        c.setFont("Helvetica", 7.5)
        c.drawRightString(R - 3 * mm, 38 * mm, "Authorized Signatory")

        ny = 38 * mm
        c.setFont("Helvetica-Bold", 7)
        c.drawString(L + 2 * mm, ny, "Notes:")
        c.setFont("Helvetica", 6.2)
        if self.inv.get("is_order"):
            note = ("Please supply the goods / services listed above as per the "
                    "terms stated. Quote our order number on all despatch "
                    "documents and invoices. Material not conforming to "
                    "specification may be returned at the supplier's cost. "
                    "Subject to Pune.")
        else:
            note = ("Certified that the particulars given above are true and "
                    "correct and amount indicated in the documents, represents "
                    "price, actually charged by us and that there is no flow of "
                    "additional consideration directly or indirectly from the "
                    "buyer. Subject to Pune.")
        for ln in _wrap(c, note, "Helvetica", 6.2, 105 * mm):
            ny -= 3.2 * mm
            c.drawString(L + 2 * mm, ny, ln)
        c.setFont("Helvetica", 7)
        c.drawString(L + 2 * mm, 24 * mm, "Receiver's Signature")

    def page_label(self):
        self.c.setFont("Helvetica", 6.2)
        self.c.drawCentredString(
            W / 2, 15 * mm,
            f"Page {self.page} / {self.pages_total}  -  This is a computer "
            "generated document and requires no signature.")

    # ---------------------------------------------------------- drive

    def run(self, fixed_total=False):
        c, inv = self.c, self.inv
        lines = inv["lines"]

        # first pass: how many pages? totals block needs ~85mm of room
        self.begin_page()
        y = self.header()
        y = self.table_head(y)
        need = 85 * mm + 4 * mm * len(self.t["summary"])
        i = 0
        while i < len(lines):
            if y - 12 * mm < BOTTOM + (need if i == len(lines) - 1 else 15 * mm):
                self.page_label()
                self.end_page()
                c.showPage()
                self.begin_page()
                y = self.header()
                y = self.table_head(y)
            y = self.row(y, i + 1, lines[i])
            i += 1

        if y - need < BOTTOM:
            self.page_label()
            self.end_page()
            c.showPage()
            self.begin_page()
            y = self.header()
            y = self.table_head(y)

        self.totals_block(y)
        self.footer()
        if not fixed_total:
            self.pages_total = self.page
        self.page_label()
        self.end_page()
        c.showPage()
        c.save()


def render(inv, t, seller, path):
    """Lay the invoice out twice: once to learn the page count, once to draw
    it with correct "Page n / total" labels."""
    import os
    import tempfile

    probe = Renderer(inv, t, seller, os.devnull)
    probe.run()

    final = Renderer(inv, t, seller, path)
    final.pages_total = probe.page
    final.run(fixed_total=True)
