"""Draw thermal-printer style tax invoices.

Every seller prints from its own POS, so each has its own layout: its own
face, rule style, wording and section order, and one is on a 58mm roll.
The figures are computed the same way for all of them: once, from the
taxable value and the GST rate, with the halves rounded together so CGST
and SGST are always identical.
"""
import io
import os
import random
import sys
from decimal import Decimal

from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont

from invoicegen.model import fmt, half_tax, money, rupees_in_words
from invoicegen.patterns import Sheet

SELLER = {
    "name": "DECURE CONNECT PRIVATE LIMITED",
    "gstin": "27AAFCD9101R1Z7",
    "addr": ["5B/269, Akshay Mittal Industrial Estate",
             "Andheri Kurla Road, Andheri East",
             "Mumbai Suburban, Maharashtra - 400059"],
    "state": "27-MAHARASHTRA",
    "layout": "classic",
}

MOHAN = {
    "name": "MOHAN CLOTHING CO. PVT. LTD.",
    "gstin": "27AAACM1374L1ZC",
    "addr": ["Block-2, 1st Floor, Shop No F-04, Phoenix Mall",
             "Senapati Bapat Marg, Lower Parel",
             "Mumbai, Maharashtra - 400013"],
    "state": "27-MAHARASHTRA",
    "layout": "mall",
}

RELIANCE = {
    "name": "RELIANCE RETAIL LIMITED",
    "gstin": "27AABCR1718E1ZP",
    "addr": ["Reliance Corporate Park, Thane Belapur Road",
             "RCP, 5 TTC Industrial Area, Ghansoli",
             "Navi Mumbai, Thane, Maharashtra - 400701"],
    "state": "27-MAHARASHTRA",
    # Reliance bills use the house A4 tax invoice, not a thermal roll
    "layout": "a4",
}

SHUBHAM = {
    "name": "SHUBHAM MART",
    "gstin": "27AAGHV9175F1ZL",
    "addr": ["14th Floor, 1403, Oasis Sapphire, Opp S T Workshop",
             "Makhmali Lake, Khopat",
             "Thane, Maharashtra - 400601"],
    "state": "27-MAHARASHTRA",
    "layout": "mini",
}

BUYER = {
    "name": "COMPUTER EDUCATION LEARNING",
    "gstin": "27AALFC3614R1ZY",
    "addr": ["F Wing 6th Floor, F-62-A, Maker Tower",
             "GD Somani Marg, World Trade Centre",
             "Cuffe Parade, Mumbai, Maharashtra - 400005"],
    "state": "27-MAHARASHTRA",
}

CHAIR = {"desc": "Office Chair (Swivel, Height Adjustable)", "hsn": "940130",
         "qty": 1, "uom": "Nos", "gst": Decimal("18")}

# one entry per bill: file name -> its particulars
BILLS = {
    "decure1": {
        "number": "222300803", "date": "05-08-2022", "time": "11:42",
        "cashier": "Counter 1", "pay_mode": "Bank Transfer",
        "items": [{**CHAIR, "taxable": Decimal("3661.02")}],
    },
    "decure2": {
        "number": "222301515", "date": "02-12-2022", "time": "15:27",
        "cashier": "Counter 1", "pay_mode": "Bank Transfer",
        "items": [{**CHAIR, "taxable": Decimal("3254.24")}],
    },
    "decure3": {
        "number": "222300571", "date": "02-07-2022", "time": "12:08",
        "cashier": "Counter 1", "pay_mode": "Bank Transfer",
        "items": [{**CHAIR, "taxable": Decimal("9472.88")}],
    },
    "decure4": {
        "number": "222300572", "date": "02-07-2022", "time": "12:31",
        "cashier": "Counter 1", "pay_mode": "Bank Transfer",
        "items": [{**CHAIR, "desc": "Office Chair (Mesh Back, Swivel)",
                   "taxable": Decimal("3686.44")}],
    },
    "decure5": {
        "number": "222300609", "date": "07-07-2022", "time": "16:05",
        "cashier": "Counter 1", "pay_mode": "Bank Transfer",
        "items": [{**CHAIR, "taxable": Decimal("3050.85")}],
    },
    "decure6": {
        "number": "222300974", "date": "10-09-2022", "time": "11:19",
        "cashier": "Counter 1", "pay_mode": "Bank Transfer",
        "items": [{**CHAIR, "taxable": Decimal("9974.58")}],
    },
    "decure7": {
        "number": "222300984", "date": "12-09-2022", "time": "13:47",
        "cashier": "Counter 1", "pay_mode": "Bank Transfer",
        "items": [{**CHAIR, "taxable": Decimal("3305.08")}],
    },
    "mohan1": {
        "seller": MOHAN,
        "number": "230SC1032405175", "date": "22-01-2023", "time": "17:12",
        "cashier": "Counter 2", "pay_mode": "Bank Transfer",
        # the register carries this one to the paisa, so no rupee rounding
        "round": False,
        "items": [{
            "desc": "Fcosie Extra Long Curtains 10-24 ft Length, Solid "
                    "Luxury Linen Drapes for High Ceilings, Room Darkening "
                    "Curtain Panels with Grommet Top, Loft Drapes Window "
                    "Treatments (Pale Blue, 50\" W x 168\" L)",
            "hsn": "630399", "qty": 1, "uom": "Set",
            "taxable": Decimal("28375.01"), "gst": Decimal("12")}],
    },
    "mohan2": {
        "seller": MOHAN,
        "number": "230SC1032405274", "date": "26-01-2023", "time": "12:54",
        "cashier": "Counter 2", "pay_mode": "Bank Transfer",
        "items": [{
            "desc": "Blackout Linen Curtain Panels, Room Darkening, "
                    "Thermal Insulated with Grommet Top, Ivory "
                    "(52\" W x 96\" L)",
            "hsn": "630399", "qty": 2, "uom": "Pcs",
            "taxable": Decimal("12495.54"), "gst": Decimal("12")}],
    },
    "mohan3": {
        "seller": MOHAN,
        "number": "230SC1032405408", "date": "30-01-2023", "time": "18:21",
        "cashier": "Counter 2", "pay_mode": "Bank Transfer",
        "items": [{
            "desc": "Sheer Voile Curtain Panel with Rod Pocket, "
                    "Light Filtering, White (54\" W x 84\" L)",
            "hsn": "630399", "qty": 1, "uom": "Pcs",
            "taxable": Decimal("1959.82"), "gst": Decimal("12")}],
    },
    "reliance1": {
        "seller": RELIANCE,
        "number": "TFB714522900189", "date": "16-08-2022", "time": "14:36",
        "cashier": "Counter 3", "pay_mode": "Bank Transfer",
        "round": False,
        "items": [{
            "desc": "LG 1.5 Ton 5 Star AI DUAL Inverter Split AC, "
                    "Copper, Super Convertible 6-in-1, HD Filter "
                    "(RS-Q19YNZE, White)",
            "hsn": "841510", "qty": 2, "uom": "Nos",
            "taxable": Decimal("70769.40"), "gst": Decimal("18")}],
    },
    "reliance2": {
        "seller": RELIANCE,
        "number": "TFB714822900082", "date": "15-08-2022", "time": "16:02",
        "cashier": "Counter 3", "pay_mode": "Bank Transfer",
        "round": False,
        "items": [{
            "desc": "V-Guard VWI 400 Voltage Stabilizer for AC up to "
                    "1.5 Ton, Wide Working Range 130-290V, Wall Mount",
            "hsn": "850440", "qty": 2, "uom": "Nos",
            "taxable": Decimal("17301.36"), "gst": Decimal("18")}],
    },
    "reliance3": {
        "seller": RELIANCE,
        "number": "TFB714822900104", "date": "18-10-2022", "time": "13:15",
        "cashier": "Counter 3", "pay_mode": "Bank Transfer",
        "round": False,
        "items": [{
            "desc": "Dell 24 inch Full HD IPS Monitor, 75Hz, "
                    "HDMI + VGA, Tilt Stand (SE2422H, Black)",
            "hsn": "852852", "qty": 2, "uom": "Nos",
            "taxable": Decimal("20661.10"), "gst": Decimal("18")}],
    },
    "shubham1": {
        "seller": SHUBHAM,
        "number": "001338", "date": "23-06-2022", "time": "12:40",
        "cashier": "Counter 1", "pay_mode": "Bank Transfer",
        # printed at 70,400 with no round-off: taxable is worked back from
        # the 18%-inclusive total (70,400 / 1.18 = 59,661.02), which puts
        # CGST and SGST at 5,369.49 each. Two makes, 3 + 2 chairs.
        "items": [
            {"desc": "Nilkamal Premium High Back Boss Chair, Leatherette, "
                     "Lumbar Support, Adjustable Height, Chrome Base (Black)",
             "hsn": "940130", "qty": 3, "uom": "Nos",
             "taxable": Decimal("35997.00"), "gst": Decimal("18")},
            {"desc": "Featherlite Executive Boss Chair, High Back PU "
                     "Leather, Synchro Tilt, Nylon Base (Brown)",
             "hsn": "940130", "qty": 2, "uom": "Nos",
             "taxable": Decimal("23664.02"), "gst": Decimal("18")},
        ],
    },
}
BILL = BILLS["decure1"]

# every supplier has been paid; each uses its own stamp
STAMPS = {"paid": os.path.join("invoicegen", "stamps", "paid.png"),
          "paid_stars": os.path.join("invoicegen", "stamps", "paid_stars.png"),
          "paid_box": os.path.join("invoicegen", "stamps", "paid_box.png")}
for _n, _b in BILLS.items():
    if _n.startswith("decure"):
        _b["stamp"] = "paid"
    elif _n.startswith("mohan"):
        _b["stamp"] = "paid_stars"
    elif _n.startswith(("reliance", "shubham")):
        _b["stamp"] = "paid_box"


# ---------------------------------------------------------------- faces
#
# One face per till. Courier for the generic POS, Times for the mall
# store, Helvetica for the chain, and Lucida Console - the dot-matrix look
# of a cheap printer - for the small mart, falling back to bold Courier
# where that font is not installed.

F, FB = "Courier", "Courier-Bold"
T, TB = "Times-Roman", "Times-Bold"
H, HB = "Helvetica", "Helvetica-Bold"


def _lucida():
    path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                        "Fonts", "lucon.ttf")
    try:
        pdfmetrics.registerFont(TTFont("Lucon", path))
        return "Lucon"
    except Exception:
        return "Courier-Bold"


M = _lucida()


def wrap(text, f, sz, width):
    """Break text into lines that fit `width`, on spaces."""
    line, out = "", []
    for w in text.split():
        cand = (line + " " + w).strip()
        if line and stringWidth(cand, f, sz) > width:
            out.append(line)
            line = w
        else:
            line = cand
    out.append(line)
    return out


def compute(items, round_total=True, fixed_total=None):
    """Exact per-line figures, rounded once at the point they are printed."""
    rows, taxable, tax = [], Decimal(0), Decimal(0)
    for it in items:
        tv = money(it["taxable"])
        tx = money(tv * it["gst"] / 100)
        rate = tv / it["qty"]            # exact; formatted only when drawn
        rows.append({**it, "tv": tv, "tx": tx, "rate": rate, "amt": tv + tx})
        taxable += tv
        tax += tx
    half = half_tax(tax)
    gross = taxable + half * 2
    if fixed_total is not None:
        total = money(fixed_total)
    elif round_total:
        total = money(gross).quantize(Decimal("1"))
    else:
        total = gross
    return rows, taxable, half, gross, total - gross, total


class Roll:
    """A strip of thermal paper with a cursor that moves down as text lands.

    A layout is drawn twice: once onto a throwaway buffer to find out how
    long it runs, then onto the real file cut to that length.
    """

    def __init__(self, target, width, height, title, margin):
        self.sh = Sheet(target, size=(width, height), title=title)
        self.W, self.H = width, height
        self.L, self.R = margin, width - margin
        self.y = height - 7 * mm

    # -- text
    def t(self, x, y, s, f, sz, align="l"):
        self.sh.t(x, y, s, f, sz, align=align)

    def centre(self, s, f=F, sz=7.5, dy=3.6):
        self.t(self.W / 2, self.y, s, f, sz, "c")
        self.y -= dy * mm

    def left(self, s, f=F, sz=7.5, dy=3.6, x=None):
        self.t(self.L if x is None else x, self.y, s, f, sz)
        self.y -= dy * mm

    def pair(self, lbl, val, f=F, sz=7.5, dy=3.6, lf=None):
        self.t(self.L, self.y, lbl, lf or f, sz)
        self.t(self.R, self.y, val, f, sz, "r")
        self.y -= dy * mm

    def cols(self, cells, f=F, sz=7, dy=3.4):
        """Several strings on one line: (x, text, align) each."""
        for x, s, a in cells:
            self.t(x, self.y, s, f, sz, a)
        self.y -= dy * mm

    def para(self, text, f=F, sz=7.5, dy=3.4, x=None, width=None):
        x = self.L if x is None else x
        for s in wrap(text, f, sz, width or (self.R - x)):
            self.left(s, f, sz, dy, x)

    def clip(self, s, f, sz, width):
        return self.sh.clip(s, f, sz, width)

    # -- rules
    def rule(self, style="dash", dy=3.4, f=F, sz=7, lw=0.5):
        yy = self.y + 1.2 * mm
        if style == "dash":
            self.sh.line(self.L, yy, self.R, yy, lw, dash=[1.2, 1.2])
        elif style == "solid":
            self.sh.line(self.L, yy, self.R, yy, lw)
        elif style == "double":
            self.sh.line(self.L, yy + 0.7 * mm, self.R, yy + 0.7 * mm, lw)
            self.sh.line(self.L, yy - 0.3 * mm, self.R, yy - 0.3 * mm, lw)
        else:                       # a run of characters, e.g. "=" or "*"
            n = int((self.R - self.L) / stringWidth(style, f, sz))
            self.t(self.L, self.y, style * n, f, sz)
        self.y -= dy * mm

    def gap(self, dy):
        self.y -= dy * mm

    def box(self, x, y, w, h, lw=0.6):
        self.sh.box(x, y, w, h, lw=lw)

    def barcode(self, seed, height=6 * mm, dy=8):
        """A bar pattern in the style of a till's own bill-number code."""
        rng = random.Random(seed)
        c = self.sh.c
        x = self.W / 2 - 24 * mm
        y = self.y - height + 2 * mm
        while x < self.W / 2 + 24 * mm:
            w = rng.choice([0.25, 0.25, 0.5, 0.5, 0.75, 1.0]) * mm
            if rng.random() < 0.55:
                c.rect(x, y, w, height, stroke=0, fill=1)
            x += w
        self.y -= dy * mm

    # -- stamp
    def stamp(self, bill, anchor_y):
        """Lands a little differently on every bill, the way a hand stamp
        does, and crosses the lower lines rather than sitting in clear
        space. The seed is the bill number, so a re-run gives the same
        bill."""
        if not bill.get("stamp"):
            return
        rng = random.Random(bill["number"])
        img = ImageReader(STAMPS[bill["stamp"]])
        scale = self.W / (80 * mm)
        size = rng.uniform(27, 31) * mm * scale
        iw, ih = img.getSize()
        sw, sh_ = (size, size * ih / iw) if iw >= ih else (size * iw / ih, size)
        cx = self.W - rng.uniform(17, 27) * mm * scale
        cy = anchor_y - rng.uniform(6, 22) * mm
        c = self.sh.c
        c.saveState()
        c.translate(cx, cy)
        c.rotate(rng.uniform(-28, 18))
        c.setFillAlpha(rng.uniform(0.62, 0.78))
        c.drawImage(img, -sw / 2, -sh_ / 2, sw, sh_, mask="auto")
        c.restoreState()

    def done(self):
        self.sh.done()


def slab_label(rows):
    """'6%' when every line shares one slab, else '' - for the CGST/SGST rows."""
    slabs = {r["gst"] for r in rows}
    return ("%g%%" % (slabs.pop() / 2)) if len(slabs) == 1 else ""


def summary_rows(rows):
    """HSN-wise tax summary; the two halves of each line rounded together."""
    out = []
    for r in rows:
        h = half_tax(r["tx"])
        out.append((r["hsn"], r["gst"], r["tv"], h, h * 2))
    return out


# ---------------------------------------------------------------- layouts
#
# Each takes a Roll and the computed figures and draws the whole bill. They
# return the y of the grand total, which is where the stamp is anchored.

def classic(ro, seller, buyer, bill, fig):
    """Courier and dashed rules: a generic counter POS."""
    rows, taxable, half, gross, round_off, total = fig
    L, R, W = ro.L, ro.R, ro.W
    ro.centre(seller["name"], FB, 8.5, 4.2)
    for a in seller["addr"]:
        ro.centre(a, F, 6.8, 3.2)
    ro.centre("GSTIN: " + seller["gstin"], F, 7, 3.6)
    ro.centre("State: " + seller["state"], F, 6.8, 3.6)
    ro.rule("dash")
    ro.centre("TAX INVOICE", FB, 9, 4.6)
    ro.rule("dash")
    ro.pair("Bill No : " + bill["number"], "Date: " + bill["date"])
    ro.pair("Time    : " + bill["time"], bill["cashier"])
    ro.rule("dash")
    ro.left("Bill To:", FB)
    ro.left(ro.clip(buyer["name"], FB, 7.5, 72 * mm), FB)
    for a in buyer["addr"]:
        ro.left(ro.clip(a, F, 6.8, 72 * mm), F, 6.8, 3.2)
    ro.left("GSTIN: " + buyer["gstin"], F, 7)
    ro.left("Place of Supply: " + buyer["state"], F, 6.8)
    ro.rule("dash")
    ro.cols([(L, "Item", "l"), (L + 32 * mm, "Qty", "l"),
             (L + 56 * mm, "Rate", "r"), (R, "Amount", "r")], FB, 7, 3.2)
    ro.rule("dash")
    for i, r in enumerate(rows, 1):
        ro.para("%d. %s" % (i, r["desc"]), F, 7.5, 3.4)
        ro.cols([(L + 3 * mm, "HSN %s  GST %g%%" % (r["hsn"], r["gst"]), "l"),
                 (L + 32 * mm, "%g %s" % (r["qty"], r["uom"]), "l"),
                 (L + 56 * mm, fmt(r["rate"]), "r"), (R, fmt(r["tv"]), "r")],
                F, 6.8, 4.6)
    ro.rule("dash")
    lbl = slab_label(rows)
    ro.pair("Sub Total", fmt(taxable))
    ro.pair("CGST @ " + lbl, fmt(half))
    ro.pair("SGST @ " + lbl, fmt(half))
    ro.pair("Round Off", ("%+.2f" % round_off) if round_off else "0.00")
    ro.rule("dash")
    ro.pair("GRAND TOTAL", "Rs. " + fmt(total), FB, 9.5, 5)
    ro.rule("dash")
    total_y = ro.y
    ro.para(rupees_in_words(total), F, 6.5, 3.1)
    ro.gap(1)
    ro.rule("dash")
    ro.cols([(L, "HSN", "l"), (L + 24 * mm, "Taxable", "r"),
             (L + 42 * mm, "CGST", "r"), (L + 58 * mm, "SGST", "r"),
             (R, "Total Tax", "r")], FB, 6.5, 3.2)
    for hsn, g, tv, h, tx in summary_rows(rows):
        ro.cols([(L, hsn, "l"), (L + 24 * mm, fmt(tv), "r"),
                 (L + 42 * mm, fmt(h), "r"), (L + 58 * mm, fmt(h), "r"),
                 (R, fmt(tx), "r")], F, 6.5, 3.2)
    ro.rule("dash")
    ro.pair("Payment Mode", bill["pay_mode"])
    ro.pair("Items", str(len(rows)))
    ro.gap(1.5)
    ro.centre("Goods once sold will not be taken back", F, 6.5, 3.2)
    ro.centre("Subject to Mumbai Jurisdiction", F, 6.5, 3.2)
    ro.centre("E. & O.E.", F, 6.5, 4)
    ro.centre("*** Thank You, Visit Again ***", FB, 7.5, 4)
    ro.centre("For " + seller["name"], F, 6.5, 3.2)
    return total_y


def mall(ro, seller, buyer, bill, fig):
    """A mall apparel store: Times, solid rules, a boxed net payable."""
    rows, taxable, half, gross, round_off, total = fig
    L, R, W = ro.L, ro.R, ro.W
    ro.gap(1)
    ro.centre(seller["name"], TB, 10.5, 4.6)
    for a in seller["addr"]:
        ro.centre(a, T, 7, 3.2)
    ro.centre("GSTIN : " + seller["gstin"], T, 7.2, 3.8)
    ro.rule("solid", 3.6, lw=0.7)
    ro.cols([(L, "RETAIL TAX INVOICE", "l"),
             (R, "Original for Recipient", "r")], TB, 8, 4)
    ro.rule("solid", 3.4, lw=0.4)
    ro.left("Invoice No.  : " + bill["number"], T, 7.5, 3.5)
    ro.left("Invoice Date : %s   %s" % (bill["date"], bill["time"]), T, 7.5, 3.5)
    ro.left("Counter / Cashier : %s / SAN%02d" % (bill["cashier"],
            random.Random(bill["number"]).randint(3, 19)), T, 7.5, 3.5)
    ro.rule("solid", 3.4, lw=0.4)
    ro.left("Customer", TB, 7.5, 3.5)
    ro.left(ro.clip(buyer["name"], T, 7.5, 72 * mm), T, 7.5, 3.5)
    ro.para(", ".join(buyer["addr"]), T, 6.8, 3.1)
    ro.left("GSTIN : " + buyer["gstin"], T, 7.2, 3.3)
    ro.left("Place of Supply : " + buyer["state"], T, 7.2, 3.5)
    ro.rule("solid", 3.6, lw=0.7)
    ro.cols([(L, "Description", "l"), (L + 40 * mm, "Qty", "r"),
             (L + 56 * mm, "Rate", "r"), (R, "Amount", "r")], TB, 7.2, 3.4)
    ro.rule("solid", 3.4, lw=0.4)
    for r in rows:
        ro.para(r["desc"], T, 7.5, 3.4, width=70 * mm)
        ro.cols([(L, "HSN %s | GST %g%%" % (r["hsn"], r["gst"]), "l"),
                 (L + 40 * mm, "%g" % r["qty"], "r"),
                 (L + 56 * mm, fmt(r["rate"]), "r"), (R, fmt(r["tv"]), "r")],
                T, 7.2, 4.2)
    ro.rule("solid", 3.6, lw=0.4)
    lbl = slab_label(rows)
    ro.pair("Gross Amount", fmt(taxable), T, 7.5, 3.6)
    ro.pair("CGST " + lbl, fmt(half), T, 7.5, 3.6)
    ro.pair("SGST " + lbl, fmt(half), T, 7.5, 3.6)
    if round_off:
        ro.pair("Round Off", "%+.2f" % round_off, T, 7.5, 3.6)
    ro.gap(3.2)
    ro.box(L, ro.y - 2.2 * mm, R - L, 7 * mm, lw=0.8)
    ro.pair("NET PAYABLE", "Rs " + fmt(total), TB, 10.5, 6.4, lf=TB)
    total_y = ro.y + 2 * mm
    ro.para("Amount in words : " + rupees_in_words(total), T, 6.8, 3.1)
    ro.gap(1)
    ro.rule("solid", 3.4, lw=0.4)
    ro.left("Tax Summary", TB, 7.2, 3.4)
    ro.cols([(L, "HSN", "l"), (L + 20 * mm, "GST%", "r"),
             (L + 38 * mm, "Taxable", "r"), (L + 54 * mm, "CGST", "r"),
             (R, "SGST", "r")], TB, 6.8, 3.2)
    for hsn, g, tv, h, tx in summary_rows(rows):
        ro.cols([(L, hsn, "l"), (L + 20 * mm, "%g" % g, "r"),
                 (L + 38 * mm, fmt(tv), "r"), (L + 54 * mm, fmt(h), "r"),
                 (R, fmt(h), "r")], T, 6.8, 3.2)
    ro.rule("solid", 3.4, lw=0.4)
    ro.pair("Tender : " + bill["pay_mode"], fmt(total), T, 7.5, 3.6)
    ro.pair("Total Qty : %g" % sum(r["qty"] for r in rows),
            "Items : %d" % len(rows), T, 7.5, 3.8)
    ro.rule("solid", 3.6, lw=0.7)
    ro.centre("Exchange within 7 days with bill & tags intact", T, 6.8, 3.1)
    ro.centre("No exchange on altered or sale merchandise", T, 6.8, 3.1)
    ro.centre("Subject to Mumbai jurisdiction", T, 6.8, 3.9)
    ro.centre("Thank you for shopping with us", TB, 8, 4)
    ro.centre("Customer Copy", T, 7, 3.2)
    return total_y


def digital(ro, seller, buyer, bill, fig):
    """A large chain's till: dense Helvetica, '=' rules, a bar code."""
    rows, taxable, half, gross, round_off, total = fig
    L, R, W = ro.L, ro.R, ro.W
    rng = random.Random(bill["number"])
    ro.gap(1)
    ro.centre(seller["name"], HB, 10, 4.8)
    for a in seller["addr"]:
        ro.centre(a, H, 6.3, 3.0)
    ro.centre("GSTIN No : " + seller["gstin"], H, 6.6, 3.8)
    ro.rule("=", 3.6, H, 7)
    ro.centre("TAX INVOICE", HB, 8.5, 4.4)
    ro.rule("=", 3.6, H, 7)
    ro.cols([(L, "Bill No  : " + bill["number"], "l"),
             (R, "Date : " + bill["date"], "r")], H, 6.8, 3.4)
    ro.cols([(L, "Till No  : %02d" % rng.randint(1, 9), "l"),
             (R, "Time : " + bill["time"], "r")], H, 6.8, 3.4)
    ro.cols([(L, "Cashier  : %d" % rng.randint(30000, 89999), "l"),
             (R, "Store : %d" % rng.randint(2000, 4999), "r")], H, 6.8, 3.4)
    ro.rule("-", 3.4, H, 7)
    ro.left("Customer Details", HB, 6.8, 3.4)
    ro.left("Name    : " + ro.clip(buyer["name"], H, 6.8, 60 * mm), H, 6.8, 3.2)
    ro.left("GSTIN   : " + buyer["gstin"], H, 6.8, 3.2)
    ro.para("Address : " + ", ".join(buyer["addr"]), H, 6.3, 3.0)
    ro.left("POS     : " + buyer["state"], H, 6.8, 3.4)
    ro.rule("-", 3.4, H, 7)
    ro.cols([(L, "Sr", "l"), (L + 5 * mm, "Item Description", "l"),
             (R, "Amount", "r")], HB, 6.8, 3.4)
    ro.rule("-", 3.4, H, 7)
    for i, r in enumerate(rows, 1):
        lines = wrap(r["desc"], H, 6.8, R - L - 5 * mm)
        ro.cols([(L, str(i), "l"), (L + 5 * mm, lines[0], "l")], H, 6.8, 3.2)
        for s in lines[1:]:
            ro.left(s, H, 6.8, 3.2, L + 5 * mm)
        ro.cols([(L + 5 * mm, "HSN %s   %g x %s" % (r["hsn"], r["qty"],
                                                     fmt(r["rate"])), "l"),
                 (R, fmt(r["tv"]), "r")], H, 6.8, 3.2)
        ro.left("GST %g%%  Tax %s" % (r["gst"], fmt(r["tx"])), H, 6.3, 4.0,
                L + 5 * mm)
    ro.rule("-", 3.4, H, 7)
    ro.pair("Total Items : %d" % len(rows),
            "Total Qty : %g" % sum(r["qty"] for r in rows), H, 6.8, 3.6)
    ro.rule("=", 3.6, H, 7)
    lbl = slab_label(rows)
    ro.pair("Sub Total", fmt(taxable), H, 7.2, 3.6)
    ro.pair("CGST @ " + lbl, fmt(half), H, 7.2, 3.6)
    ro.pair("SGST @ " + lbl, fmt(half), H, 7.2, 3.6)
    if round_off:
        ro.pair("Round Off", "%+.2f" % round_off, H, 7.2, 3.6)
    ro.rule("-", 3.4, H, 7)
    ro.pair("TOTAL AMOUNT", fmt(total), HB, 10, 5.4, lf=HB)
    ro.rule("=", 3.6, H, 7)
    total_y = ro.y + 2 * mm
    ro.pair(bill["pay_mode"], fmt(total), H, 7, 3.6)
    ro.pair("Change Due", "0.00", H, 7, 3.8)
    ro.para(rupees_in_words(total), H, 6.3, 3.0)
    ro.gap(0.8)
    ro.rule("-", 3.4, H, 7)
    ro.left("GST Breakup", HB, 6.8, 3.4)
    ro.cols([(L, "HSN", "l"), (L + 20 * mm, "Rate", "r"),
             (L + 38 * mm, "Taxable", "r"), (L + 56 * mm, "CGST", "r"),
             (R, "SGST", "r")], HB, 6.3, 3.1)
    for hsn, g, tv, h, tx in summary_rows(rows):
        ro.cols([(L, hsn, "l"), (L + 20 * mm, "%g%%" % g, "r"),
                 (L + 38 * mm, fmt(tv), "r"), (L + 56 * mm, fmt(h), "r"),
                 (R, fmt(h), "r")], H, 6.3, 3.1)
    ro.rule("=", 3.6, H, 7)
    ro.gap(1.5)
    ro.barcode(bill["number"], 7 * mm, 9)
    ro.centre(bill["number"], H, 6.5, 4)
    ro.centre("Goods can be exchanged within 7 days of purchase", H, 6.2, 3.0)
    ro.centre("with original invoice. T&C apply.", H, 6.2, 3.6)
    ro.centre("Thank you for shopping with us!", HB, 7.5, 4)
    return total_y


def mini(ro, seller, buyer, bill, fig):
    """A small mart's 58mm printer: Lucida Console, upper case, '=' rules."""
    rows, taxable, half, gross, round_off, total = fig
    L, R, W = ro.L, ro.R, ro.W
    up = lambda s: str(s).upper()

    def rs(v):                       # a cheap till prints no thousands commas
        return "%.2f" % money(v)

    ro.centre(up(seller["name"]), M, 9, 4.2)
    for a in seller["addr"]:
        ro.para(up(a), M, 5.6, 2.8)
    ro.centre("GSTIN " + seller["gstin"], M, 6, 3.2)
    ro.rule("=", 3.2, M, 6)
    ro.centre("TAX INVOICE", M, 7.5, 3.8)
    ro.rule("=", 3.2, M, 6)
    ro.left("BILL NO : " + bill["number"], M, 6.2, 3)
    ro.left("DATE    : %s %s" % (bill["date"], bill["time"]), M, 6.2, 3)
    ro.rule("-", 3, M, 6)
    ro.left("CUSTOMER:", M, 6.2, 3)
    ro.para(up(buyer["name"]), M, 6.2, 3)
    ro.para(up(", ".join(buyer["addr"])), M, 5.4, 2.7)
    ro.left("GSTIN " + buyer["gstin"], M, 6, 3)
    ro.left("POS " + buyer["state"], M, 6, 3)
    ro.rule("-", 3, M, 6)
    ro.cols([(L, "ITEM", "l"), (R, "AMOUNT", "r")], M, 6.2, 3)
    ro.rule("-", 3, M, 6)
    for r in rows:
        ro.para(up(r["desc"]), M, 6.2, 2.9)
        ro.cols([(L, "%g X %s" % (r["qty"], rs(r["rate"])), "l"),
                 (R, rs(r["tv"]), "r")], M, 6.2, 3)
        ro.left("HSN %s GST %g%%" % (r["hsn"], r["gst"]), M, 5.4, 3.6)
    ro.rule("-", 3, M, 6)
    lbl = slab_label(rows)
    ro.pair("SUBTOTAL", rs(taxable), M, 6.2, 3)
    ro.pair("CGST " + lbl, rs(half), M, 6.2, 3)
    ro.pair("SGST " + lbl, rs(half), M, 6.2, 3)
    if round_off:
        ro.pair("R/OFF", "%+.2f" % round_off, M, 6.2, 3)
    ro.rule("=", 3.2, M, 6)
    ro.pair("TOTAL", "RS " + rs(total), M, 8.5, 4.4)
    ro.rule("=", 3.2, M, 6)
    total_y = ro.y + 2 * mm
    ro.para(up(rupees_in_words(total)), M, 5.4, 2.7)
    ro.gap(0.6)
    ro.rule("-", 3, M, 6)
    ro.left("TAX SUMMARY", M, 6, 3)
    for hsn, g, tv, h, tx in summary_rows(rows):
        ro.left("%s @%g%%  TXBL %s" % (hsn, g, rs(tv)), M, 5.4, 2.7)
        ro.left("     CGST %s SGST %s" % (rs(h), rs(h)), M, 5.4, 3)
    ro.rule("-", 3, M, 6)
    ro.left("PAID BY: " + up(bill["pay_mode"]), M, 6.2, 3)
    ro.left("ITEMS: %d  QTY: %g" % (len(rows), sum(r["qty"] for r in rows)),
            M, 6.2, 3.6)
    ro.centre("NO EXCHANGE  NO RETURN", M, 6, 3)
    ro.centre("THANK YOU VISIT AGAIN", M, 6.5, 3.4)
    return total_y


LAYOUTS = {"classic": (classic, 80, 3), "mall": (mall, 80, 4),
           "digital": (digital, 80, 3.5), "mini": (mini, 58, 2.5)}


def draw_a4(path, seller, buyer, bill, fig):
    """The house A4 tax invoice (invoicegen/render.py), stamped afterwards."""
    from invoicegen.model import Line
    from invoicegen.render import render
    rows, taxable, half, gross, round_off, total = fig
    class RegLine(Line):
        """A line whose tax is the register's: the two 9% halves, each
        rounded, rather than 18% rounded once. 70,769.40 at 18% is
        12,738.49, but the register's CGST and SGST are 6,369.25 each."""
        @property
        def tax(self):
            return half_tax(money(self.taxable * self.gst / 100)) * 2

    lines = [RegLine(r["desc"], r["hsn"], r["rate"], r["qty"], r["uom"],
                     r["gst"]) for r in rows]
    # the Line model derives taxable from rate x qty; it must agree with
    # the register to the paisa or the bill is wrong
    for ln, r in zip(lines, rows):
        assert ln.taxable == r["tv"], (bill["number"], ln.taxable, r["tv"])
    d, m, y = bill["date"].split("-")
    import datetime
    date = datetime.date(int(y), int(m), int(d))
    inv = {
        "number": bill["number"], "date": date.strftime("%d %b %Y"),
        "date_iso": date.isoformat(), "doc_title": "TAX INVOICE",
        "place_of_supply": buyer["state"],
        "jurisdiction": "Navi Mumbai",
        # descriptions print at a readable size and wrap, never shrink
        "desc_size": 8,
        "hide_party_label": True,
        "buyer": {"name": buyer["name"], "gstin": buyer["gstin"],
                  "state": "MAHARASHTRA", "bill": buyer["addr"],
                  "ship": buyer["addr"], "phone": None},
        "lines": lines, "charges": [], "scanned": False,
    }
    groups = {}
    for r in rows:
        g = groups.setdefault((r["hsn"], r["gst"]),
                              {"taxable": Decimal(0), "tax": Decimal(0),
                               "cess": Decimal(0)})
        g["taxable"] += r["tv"]
        g["tax"] += half_tax(r["tx"]) * 2
    t = {
        "taxable": taxable, "tax": half * 2, "cess": Decimal(0),
        "discount": Decimal(0), "charges": Decimal(0),
        "round_off": round_off, "total": total, "reverse_charge": False,
        "tds": Decimal(0), "tcs": Decimal(0), "cash_discount": Decimal(0),
        "customs_duty": Decimal(0), "advance": Decimal(0),
        "cgst": half, "sgst": half, "igst": Decimal(0), "interstate": False,
        "summary": [{"code": k[0], "gst": k[1], **v}
                    for k, v in sorted(groups.items())],
        "qty": sum(Decimal(str(r["qty"])) for r in rows),
        "count": len(rows), "rates": sorted({float(r["gst"]) for r in rows}),
        "words": rupees_in_words(total),
    }
    head = {"name": seller["name"], "gstin": seller["gstin"],
            "state": "MAHARASHTRA", "state_code": "27",
            "addr": seller["addr"], "mobile": "", "bank": {}}
    render(inv, t, head, path)
    if bill.get("stamp"):
        stamp_a4(path, bill)


def stamp_a4(path, bill):
    """Press the stamp near the signatory, landing differently per bill."""
    import pymupdf
    from PIL import Image
    rng = random.Random(bill["number"])
    im = Image.open(STAMPS[bill["stamp"]]).convert("RGBA")
    alpha = rng.uniform(0.66, 0.8)
    im.putalpha(im.getchannel("A").point(lambda a: int(a * alpha)))
    im = im.rotate(rng.uniform(-24, 16), expand=True, resample=Image.BICUBIC)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    doc = pymupdf.open(path)
    page = doc[-1]
    # pressed just above the signatory line, clipping it slightly
    hit = page.search_for("Authorized Signatory")
    x1 = hit[0].x1 if hit else page.rect.width - 20 * mm
    y0 = hit[0].y0 if hit else page.rect.height - 60 * mm
    w = rng.uniform(42, 50) * mm
    h = w * im.height / im.width
    cx = x1 - w / 2 - rng.uniform(0, 14) * mm
    cy = y0 - rng.uniform(5, 11) * mm
    page.insert_image(pymupdf.Rect(cx - w / 2, cy - h / 2,
                                   cx + w / 2, cy + h / 2),
                      stream=buf.getvalue(), overlay=True)
    tmp = path + ".tmp"
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    os.replace(tmp, path)


def draw(path, seller=SELLER, buyer=BUYER, bill=BILL):
    fig = compute(bill["items"], bill.get("round", True), bill.get("total"))
    if seller.get("layout") == "a4":
        draw_a4(path, seller, buyer, bill, fig)
        return fig[5]
    layout, width, margin = LAYOUTS[seller.get("layout", "classic")]
    width, margin = width * mm, margin * mm
    # first pass onto a buffer just to measure how far the text runs
    probe = Roll(io.BytesIO(), width, 2000 * mm, bill["number"], margin)
    layout(probe, seller, buyer, bill, fig)
    used = probe.H - probe.y + 6 * mm
    ro = Roll(path, width, used, bill["number"], margin)
    total_y = layout(ro, seller, buyer, bill, fig)
    ro.stamp(bill, total_y)
    ro.done()
    return fig[5]


OUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "Thermal Bills")


if __name__ == "__main__":
    # `python make_thermal.py decure2` draws one bill; no argument draws all
    names = sys.argv[1:] or list(BILLS)
    os.makedirs(OUT_DIR, exist_ok=True)
    for name in names:
        out = os.path.join(OUT_DIR, name + ".pdf")
        # a bill names its own seller only when it is not Decure's
        total = draw(out, seller=BILLS[name].get("seller", SELLER),
                     bill=BILLS[name])
        print("wrote", out, "total", total)
