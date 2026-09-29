"""Build an invoice from data typed into the form.

Everything else in the tool invents its data; this takes what the user
entered and puts it through the same pipeline, so all twenty layouts and
both output formats work unchanged.
"""
import os
from datetime import date
from decimal import Decimal, InvalidOperation

from .model import Charge, Line, half_tax, money, rupees_in_words

CH = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_ok(g):
    """True if `g` has the shape and check digit of a real GSTIN.

    Only ever a warning - a malformed GSTIN is a legitimate thing to test a
    parser with, so the form allows it.
    """
    g = (g or "").strip().upper()
    if len(g) != 15 or not all(c in CH for c in g):
        return False
    total = 0
    for i, ch in enumerate(g[:14]):
        v = CH.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return CH[(36 - total % 36) % 36] == g[14]


def _dec(v, default="0"):
    try:
        return Decimal(str(v).strip() or default)
    except (InvalidOperation, ValueError):
        return Decimal(default)


class ManualForm:
    """What the user typed, and whether it is usable yet."""

    def __init__(self):
        self.logo = None                    # path to an image, or None
        self.supplier = {"name": "", "gstin": "", "addr1": "", "addr2": "",
                         "phone": ""}
        self.buyer = {"name": "", "gstin": "", "addr1": "", "addr2": ""}
        self.invoice = {"number": "", "date": "", "pos": ""}
        self.items = []                     # list of dicts, see blank_item
        self.charges = []                   # freight, packing, anything

    # ------------------------------------------------------------ items

    @staticmethod
    def blank_item():
        return {"desc": "", "hsn": "", "qty": "", "uom": "PCS", "rate": "",
                "gst": "18", "disc": ""}

    @staticmethod
    def blank_charge():
        return {"label": "", "amount": "", "gst": "0"}

    def real_charges(self):
        """Charge rows with both a label and an amount."""
        return [c for c in self.charges
                if c["label"].strip() and _dec(c["amount"]) > 0]

    def charge_objects(self):
        """Each charge carries its own ledger, so it posts separately."""
        return [Charge(c["label"].strip(), _dec(c["amount"]),
                       c["label"].strip(), gst=_dec(c["gst"]))
                for c in self.real_charges()]

    def real_items(self):
        """Rows with enough filled in to be worth printing."""
        out = []
        for it in self.items:
            if not it["desc"].strip():
                continue
            if _dec(it["qty"]) <= 0 or _dec(it["rate"]) <= 0:
                continue
            out.append(it)
        return out

    # ------------------------------------------------------------ checks

    def problems(self):
        """What still needs filling in before this can be generated."""
        p = []
        if not self.supplier["name"].strip():
            p.append("supplier name")
        if not self.buyer["name"].strip():
            p.append("buyer name")
        if not self.invoice["number"].strip():
            p.append("invoice number")
        if not self.real_items():
            p.append("at least one item with a quantity and rate")
        return p

    def warnings(self):
        """Things that look wrong but are allowed."""
        w = []
        for who, d in (("Supplier", self.supplier), ("Buyer", self.buyer)):
            g = d["gstin"].strip()
            if g and not gstin_ok(g):
                w.append("%s GSTIN does not look valid" % who)
        return w

    # ------------------------------------------------------------ totals

    def lines(self):
        out = []
        for it in self.real_items():
            out.append(Line(
                it["desc"].strip(), it["hsn"].strip() or "-",
                _dec(it["rate"]), _dec(it["qty"]),
                it["uom"].strip() or "PCS", _dec(it["gst"]),
                discount_pct=_dec(it["disc"]),
            ))
        return out

    def totals(self):
        """Live figures for the form, recomputed on every keystroke."""
        lines = self.lines()
        chg = self.charge_objects()
        taxable = money(sum(l.taxable for l in lines))
        charges = money(sum(c.amount for c in chg))
        tax = money(sum(l.tax for l in lines) + sum(c.tax for c in chg))
        # No rounding: a typed invoice keeps its exact paise, matching every
        # other tab, so there is no Round Off line to explain.
        gross = money(taxable + charges + tax)
        return {"taxable": taxable, "charges": charges, "tax": tax,
                "round_off": money(0), "total": gross,
                "count": len(lines), "n_charges": len(chg)}


# ---------------------------------------------------------------- building

def build(form, interstate=None):
    """Turn the form into (inv, t, seller) - the shape every renderer takes."""
    lines = form.lines()
    chg = form.charge_objects()
    taxable = money(sum(l.taxable for l in lines))
    charges = money(sum(c.amount for c in chg))
    tax = money(sum(l.tax for l in lines) + sum(c.tax for c in chg))
    gross = money(taxable + charges + tax)
    total = gross
    round_off = money(0)

    # Inter-state when the two GSTINs start with different state codes; if
    # either is missing, assume local.
    sg = form.supplier["gstin"].strip()
    bg = form.buyer["gstin"].strip()
    if interstate is None:
        interstate = bool(sg and bg and sg[:2] != bg[:2])

    # CGST and SGST are always printed equal - see half_tax()
    half = half_tax(tax)
    pos = form.invoice["pos"].strip()
    if not pos and bg:
        pos = bg[:2]

    sup_addr = [a for a in (form.supplier["addr1"], form.supplier["addr2"])
                if a.strip()]
    buy_addr = [a for a in (form.buyer["addr1"], form.buyer["addr2"])
                if a.strip()]

    seller = {
        "name": form.supplier["name"].strip(),
        "gstin": sg, "state": "", "addr": sup_addr,
        "mobile": form.supplier["phone"].strip(),
        "bank": {},
    }
    inv = {
        "number": form.invoice["number"].strip(),
        "date": form.invoice["date"].strip() or date.today().strftime(
            "%d %b %Y"),
        "date_iso": date.today().isoformat(),
        "doc_title": "TAX INVOICE",
        "is_order": False, "is_purchase": False,
        "place_of_supply": pos,
        "buyer": {"name": form.buyer["name"].strip(), "gstin": bg,
                  "state": "", "bill": buy_addr, "ship": buy_addr,
                  "phone": ""},
        "lines": lines, "charges": chg,
        "reference": None, "original_invoice": None, "order_terms": None,
        "scanned": False, "tds": None,
        "logo": form.logo if form.logo and os.path.exists(form.logo) else None,
    }
    summary = {}
    for l in lines:
        s = summary.setdefault((l.code, l.gst), {"taxable": Decimal(0),
                                                 "tax": Decimal(0),
                                                 "cess": Decimal(0)})
        s["taxable"] += l.taxable
        s["tax"] += l.tax
    for c in chg:
        if c.gst:
            s = summary.setdefault((c.label, c.gst),
                                   {"taxable": Decimal(0), "tax": Decimal(0),
                                    "cess": Decimal(0)})
            s["taxable"] += c.amount
            s["tax"] += c.tax
    t = {
        "taxable": taxable, "tax": tax, "cess": Decimal(0),
        "discount": money(sum(l.discount_value for l in lines)),
        "charges": charges, "round_off": round_off, "total": total,
        "reverse_charge": False, "tds": Decimal(0), "tcs": Decimal(0),
        "advance": Decimal(0), "cash_discount": Decimal(0),
        "customs_duty": Decimal(0),
        "cgst": Decimal(0) if interstate else half,
        "sgst": Decimal(0) if interstate else half,
        "igst": tax if interstate else Decimal(0),
        "interstate": interstate,
        "summary": [{"code": k[0], "gst": k[1],
                     **{kk: money(vv) for kk, vv in v.items()}}
                    for k, v in sorted(summary.items(),
                                       key=lambda kv: kv[0])],
        "qty": sum(l.qty for l in lines), "count": len(lines),
        "rates": sorted({float(l.gst) for l in lines}),
    }
    t["words"] = rupees_in_words(total)
    return inv, t, seller


def generate(form, outdir, patterns=("classic",), formats=("pdf",)):
    """Draw the typed invoice in each ticked layout. Returns the files made."""
    from .render import render as render_classic
    from . import patterns as P

    inv, t, seller = build(form)
    pdf_dir = os.path.join(outdir, "pdf")
    png_dir = os.path.join(outdir, "png")
    want_pdf, want_png = "pdf" in formats, "png" in formats
    os.makedirs(pdf_dir if want_pdf else outdir, exist_ok=True)
    if want_png:
        os.makedirs(png_dir, exist_ok=True)
    if not want_pdf:
        import tempfile
        pdf_dir = tempfile.mkdtemp(prefix="manual_")

    base = _safe(inv["number"]) or "Invoice"
    multi = len(patterns) > 1
    made = []
    for pat in patterns:
        name = base if pat == "classic" and not multi else "%s_%s" % (
            base, P.tag(pat))
        path = os.path.join(pdf_dir, name + ".pdf")
        if pat == "classic":
            render_classic(inv, t, seller, path)
        else:
            P.draw(pat, inv, t, seller, path)
        made.append(path)
        if want_png:
            from .images import pdf_to_png
            pdf_to_png(path, png_dir, name)
    if not want_pdf:
        import shutil
        shutil.rmtree(pdf_dir, ignore_errors=True)
    return made


def _safe(s):
    import re
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(s)).strip("_")[:80]
