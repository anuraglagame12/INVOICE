"""Invoice data model, GST engine, and Tally-posting ground truth.

Built for exercising the Procount invoice -> Tally posting pipeline. Every
invoice carries not just its printed figures but the expected accounting entry,
so a parser can be scored end to end. All generated invoices are valid and are
expected to clear the posting gate.

All money is Decimal; every displayed figure is rounded exactly once, at the
point it is computed, so the PDF and the ground-truth JSON can never disagree.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

# GST slabs in force for the scenarios we generate
SLABS = [Decimal(0), Decimal(5), Decimal(12), Decimal(18), Decimal(28)]



def money(x):
    """Round to 2dp the way an accounting package does (half-up, not banker's)."""
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def half_tax(tax):
    """Half of `tax`, rounded so CGST and SGST come out exactly equal.

    A real invoice never prints CGST 7,314.25 against SGST 7,314.24 - the two
    halves of one rate are always shown identical. Rounding each half
    independently can differ by a paisa, so round the half once and use it for
    both sides; the total tax follows from the halves rather than the reverse.
    """
    return money(money(tax) / 2)


def fmt(x):
    return f"{money(x):,.2f}"


# ---------------------------------------------------------------- words

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
         "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
         "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
         "Eighty", "Ninety"]


def _two(n):
    if n < 20:
        return _ONES[n]
    t, o = divmod(n, 10)
    return _TENS[t] + (" " + _ONES[o] if o else "")


def _three(n):
    h, r = divmod(n, 100)
    out = []
    if h:
        out.append(_ONES[h] + " Hundred")
    if r:
        out.append(_two(r))
    return " ".join(out)


def rupees_in_words(amount):
    """Indian numbering (crore / lakh / thousand), matching the source invoice."""
    amt = money(amount)
    rupees = int(amt)
    paise = int((amt - rupees) * 100)
    if rupees == 0:
        parts = ["Zero"]
    else:
        parts = []
        crore, rest = divmod(rupees, 10000000)
        lakh, rest = divmod(rest, 100000)
        thou, rest = divmod(rest, 1000)
        if crore:
            parts.append(_three(crore) + " Crore")
        if lakh:
            parts.append(_three(lakh) + " Lakh")
        if thou:
            parts.append(_three(thou) + " Thousand")
        if rest:
            parts.append(_three(rest))
    words = ", ".join(p for p in parts if p)
    out = f"INR {words} Rupees"
    if paise:
        out += f" And {_two(paise)} Paise"
    return out + " Only."


# ---------------------------------------------------------------- lines

class Line:
    """One invoice line.

    `code` is an HSN code for goods and a SAC code for services. `gst` is the
    full rate; the CGST/SGST vs IGST split is decided at invoice level from the
    place of supply, never per line.

    Inventory fields (godown, batch) apply to goods only - for services the
    posting gate must not demand quantity/UOM/stock item (Act VI).
    """

    def __init__(self, desc, code, mrp, qty, uom, gst, discount_pct=0,
                 kind="goods", cess_pct=0, exempt=False,
                 stock_item=None, godown=None, batch=None):
        self.desc = desc
        self.code = code
        self.mrp = money(mrp)
        self.qty = Decimal(str(qty))
        self.uom = uom
        self.gst = Decimal(str(gst))
        self.discount_pct = Decimal(str(discount_pct))
        self.kind = kind
        self.cess_pct = Decimal(str(cess_pct))
        self.exempt = exempt  # nil-rated / exempt supply, shown at 0%
        self.stock_item = stock_item or (desc if kind == "goods" else None)
        self.godown = godown
        self.batch = batch

    @property
    def gross(self):
        """Pre-discount value - what Act III calls Gross Amount."""
        return money(self.mrp * self.qty)

    @property
    def rate(self):
        return money(self.mrp * (1 - self.discount_pct / 100))

    @property
    def taxable(self):
        return money(self.rate * self.qty)

    @property
    def tax(self):
        return money(self.taxable * self.gst / 100)

    @property
    def cess(self):
        return money(self.taxable * self.cess_pct / 100)

    @property
    def amount(self):
        return money(self.taxable + self.tax + self.cess)

    @property
    def discount_value(self):
        return money((self.mrp - self.rate) * self.qty)


class Charge:
    """A non-item charge - freight, packing, insurance, loading.

    Act V: these must not be dumped into the purchase/sales ledger; each
    carries its own ledger so the accounting engine posts it separately.
    """

    def __init__(self, label, amount, ledger, code=None, gst=0):
        self.label = label
        self.amount = money(amount)
        self.ledger = ledger
        self.code = code
        self.gst = Decimal(str(gst))

    @property
    def tax(self):
        return money(self.amount * self.gst / 100)

    # --- printed as a row in the item table -----------------------------
    # A charge is billed like any other taxable supply, so it appears in the
    # item table with its SAC. It has no quantity or unit rate, and those
    # columns print "-" rather than a misleading 1.

    desc = property(lambda self: self.label)
    taxable = property(lambda self: self.amount)
    qty = None
    uom = ""
    mrp = None
    rate = None
    discount_pct = 0
    cess_pct = 0
    cess = property(lambda self: money(0))
    godown = None
    batch = None

    @property
    def line_total(self):
        """Charge plus its own tax, matching a line item's Amount column."""
        return money(self.amount + self.tax)


# ---------------------------------------------------------------- totals

def build(inv):
    """Compute totals, the HSN-wise tax summary, and the posting decision.

    Reverse-charge invoices show tax for reporting but exclude it from the
    amount payable - the recipient pays it to the government directly.
    """
    lines = inv["lines"]
    charges = inv.get("charges", [])

    taxable = money(sum(l.taxable for l in lines))
    line_tax = money(sum(l.tax for l in lines))
    cess = money(sum(l.cess for l in lines))
    discount = money(sum(l.discount_value for l in lines))

    charge_amt = money(sum(c.amount for c in charges))
    charge_tax = money(sum(c.tax for c in charges))
    tax = money(line_tax + charge_tax)
    # CGST and SGST must print identical, so on an intra-state supply the tax
    # carried into the total is twice the rounded half - never a paisa that
    # cannot be split evenly.
    if not inv.get("interstate", False):
        tax = money(half_tax(tax) * 2)

    # Under reverse charge the supplier collects neither tax nor cess - the
    # recipient pays both to the government - so neither enters the total.
    rcm = inv.get("reverse_charge", False)
    payable_tax = Decimal(0) if rcm else tax
    payable_cess = Decimal(0) if rcm else cess
    gross = money(taxable + charge_amt + payable_tax + payable_cess)

    # TDS is deducted from what the vendor is paid; TCS is collected on top
    tds = money(inv.get("tds", {}).get("amount", 0))
    tcs = money(inv.get("tcs_amount", 0))

    advance = money(inv.get("advance_adjusted", 0))
    pre_round = money(gross + tcs - tds - advance)


    # round to the nearest rupee, breaking an exact .50 downward so the
    # adjustment always stays strictly under half a rupee
    floor = pre_round.to_integral_value(rounding=ROUND_FLOOR)
    frac = pre_round - floor
    if frac == Decimal("0.5"):
        total = floor          # exact half: settle downward
    elif frac > Decimal("0.5"):
        total = floor + 1
    else:
        total = floor
    round_off = money(total - pre_round)

    # tax summary grouped by (code, rate), as a GST invoice must show
    summary = {}
    for l in lines:
        s = summary.setdefault((l.code, l.gst),
                               {"taxable": Decimal(0), "tax": Decimal(0),
                                "cess": Decimal(0)})
        s["taxable"] += l.taxable
        s["tax"] += l.tax
        s["cess"] += l.cess
    for c in charges:
        if c.code:
            s = summary.setdefault((c.code, c.gst),
                                   {"taxable": Decimal(0), "tax": Decimal(0),
                                    "cess": Decimal(0)})
            s["taxable"] += c.amount
            s["tax"] += c.tax

    inter = inv["interstate"]
    return {
        "taxable": taxable, "tax": tax, "line_tax": line_tax,
        "charge_tax": charge_tax, "cess": cess, "discount": discount,
        "charges": charge_amt, "gross": gross, "round_off": round_off,
        "total": total, "reverse_charge": rcm, "tds": tds, "tcs": tcs,
        "advance": advance,
        # split the odd paisa rather than rounding both halves up, or the
        # two halves can exceed the tax they came from
        "cgst": Decimal(0) if inter else half_tax(tax),
        "sgst": Decimal(0) if inter else half_tax(tax),
        "igst": tax if inter else Decimal(0),
        "interstate": inter,
        "summary": [
            {"code": k[0], "gst": k[1], **{kk: money(vv) for kk, vv in v.items()}}
            for k, v in sorted(summary.items(), key=lambda kv: (kv[0][0], kv[0][1]))
        ],
        "qty": sum(l.qty for l in lines if l.kind == "goods"),
        "count": len(lines),
        "rates": sorted({float(l.gst) for l in lines}),
        "has_goods": any(l.kind == "goods" for l in lines),
        "has_services": any(l.kind == "service" for l in lines),
    }


# ---------------------------------------------------------------- posting

def voucher(inv, t, seller):
    """The Tally voucher this invoice should produce (Act IX).

    Sales: party is debited with the receivable, income and tax ledgers are
    credited. Purchase: the mirror image. Either way Dr must equal Cr or Tally
    refuses the voucher, so every component is placed on exactly one side.
    """
    vtype = inv.get("voucher_type", "Purchase")
    # An order is a commitment, not a transaction: nothing posts to the books
    # until it is fulfilled and invoiced.
    if inv.get("is_order"):
        return {
            "voucher_type": vtype,
            "voucher_date": inv["date_iso"],
            "party_ledger": inv["party_ledger"],
            "narration": f"Order {inv['number']} - no accounting entry until "
                         "fulfilled",
            "entries": [], "total_dr": 0.0, "total_cr": 0.0,
            "balanced": True, "posts_to_tally": False,
        }
    is_purchase = vtype == "Purchase"
    side = "Input" if is_purchase else "Output"
    # A credit note undoes a sale, so every leg flips relative to one.
    credit_note = vtype == "Credit Note"
    legs = []

    def leg(ledger, amount, debit):
        """Add a leg, netting the sign so a negative never lands on a side."""
        a = money(amount)
        if a == 0:
            return
        if a < 0:
            debit, a = not debit, -a
        legs.append({"ledger": ledger, "dr": float(a) if debit else 0.0,
                     "cr": 0.0 if debit else float(a)})

    # On a purchase the goods/expense side is debited; on a sale it is
    # credited. A credit note reverses the sale, so it is debited again.
    trade_dr = is_purchase or credit_note

    for ledger, amt in sorted(inv["ledger_split"].items()):
        leg(ledger, amt, trade_dr)

    # Act V: each charge to its own ledger, never merged into sales/purchase
    for c in inv.get("charges", []):
        leg(c.ledger, c.amount, trade_dr)

    # Tax follows the trade side. Under RCM the supplier charges none, so the
    # invoice carries no tax leg at all.
    if not t["reverse_charge"]:
        if t["interstate"]:
            leg(f"{side} IGST", t["igst"], trade_dr)
        else:
            leg(f"{side} CGST", t["cgst"], trade_dr)
            leg(f"{side} SGST", t["sgst"], trade_dr)
        leg(f"{side} Cess", t["cess"], trade_dr)

    # TCS is collected from the customer on top of the invoice
    leg("TCS Payable", t["tcs"], trade_dr)

    # TDS the customer deducts reduces what they owe us
    if t["tds"]:
        leg(inv["tds"]["ledger"], t["tds"], not trade_dr)

    # An advance already received is set off against this bill
    leg("Advance from Customers" if not is_purchase
        else "Advance to Suppliers", t["advance"], not trade_dr)

    # Round off can fall either way; leg() puts it on the correct side
    leg("Round Off", t["round_off"], trade_dr)

    # The party carries the net receivable/payable
    leg(inv["party_ledger"], t["total"], not trade_dr)

    dr = money(sum(l["dr"] for l in legs))
    cr = money(sum(l["cr"] for l in legs))
    return {
        "voucher_type": vtype,
        "voucher_date": inv["date_iso"],
        "party_ledger": inv["party_ledger"],
        "narration": f"Being {vtype.lower()} vide invoice {inv['number']}",
        "entries": legs,
        "total_dr": float(dr), "total_cr": float(cr),
        "balanced": dr == cr, "posts_to_tally": True,
    }




# ---------------------------------------------------------------- record

def to_record(inv, t, seller):
    """Ground-truth JSON: the full Procount minimum dataset plus the expected
    voucher and posting decision, so a parser can be scored end to end."""
    v = voucher(inv, t, seller)

    return {
        "document_type": inv.get("doc_title", "TAX INVOICE"),
        "invoice_number": inv["number"],
        "invoice_date": inv["date"],
        "original_invoice": inv.get("original_invoice"),
        "is_order": bool(inv.get("is_order")),
        "order_terms": inv.get("order_terms"),
        "invoice_date_iso": inv["date_iso"],
        "scenario": inv["scenario"],
        "scenario_tags": inv.get("tags", []),
        "expected_post_ready": True,
        "expected_exceptions": [],

        "seller": {
            "name": seller["name"], "gstin": seller["gstin"],
            "pan": seller["gstin"][2:12], "state_code": seller["gstin"][:2],
            "state": seller["state"], "address": seller["addr"],
        },
        "buyer": {
            "name": inv["buyer"]["name"], "gstin": inv["buyer"]["gstin"],
            "pan": (inv["buyer"]["gstin"][2:12]
                    if inv["buyer"].get("gstin") else None),
            "state_code": (inv["buyer"]["gstin"][:2]
                           if inv["buyer"].get("gstin") else None),
            "state": inv["buyer"]["state"],
            "registered": bool(inv["buyer"].get("gstin")),
            "address": inv["buyer"]["bill"],
            "tally_ledger": inv.get("party_ledger"),
        },
        "place_of_supply": inv["place_of_supply"],
        "supply_type": "inter-state" if t["interstate"] else "intra-state",
        "reverse_charge": t["reverse_charge"],
        "reference": inv.get("reference"),
        "eway_bill": inv.get("eway_bill"),
        "irn": inv.get("irn"),

        "lines": [{
            "sr": i, "description": l.desc, "hsn_sac": l.code, "type": l.kind,
            "stock_item": l.stock_item, "godown": l.godown, "batch": l.batch,
            "mrp": float(l.mrp), "gross_amount": float(l.gross),
            "discount_pct": float(l.discount_pct),
            "discount_amount": float(l.discount_value),
            "rate": float(l.rate), "qty": float(l.qty), "uom": l.uom,
            "taxable_value": float(l.taxable), "gst_rate": float(l.gst),
            "tax_amount": float(l.tax),
            "cgst": 0.0 if t["interstate"] else float(half_tax(l.tax)),
            "sgst": 0.0 if t["interstate"] else float(half_tax(l.tax)),
            "igst": float(l.tax) if t["interstate"] else 0.0,
            "cess_pct": float(l.cess_pct), "cess_amount": float(l.cess),
            "amount": float(l.amount), "exempt": l.exempt,
        } for i, l in enumerate(inv["lines"], 1)],

        "other_charges": [{
            "label": c.label, "hsn_sac": c.code, "amount": float(c.amount),
            "gst_rate": float(c.gst), "tax_amount": float(c.tax),
            "tally_ledger": c.ledger,
        } for c in inv.get("charges", [])],

        "tax_summary": [{
            "hsn_sac": s["code"], "gst_rate": float(s["gst"]),
            "taxable_value": float(s["taxable"]),
            "tax_amount": float(s["tax"]), "cess_amount": float(s["cess"]),
        } for s in t["summary"]],

        "tds": ({
            "applicable": True, "section": inv["tds"]["section"],
            "nature": inv["tds"]["nature"], "rate": float(inv["tds"]["rate"]),
            "base": float(money(inv["tds"]["base"])), "amount": float(t["tds"]),
            "ledger": inv["tds"]["ledger"],
        } if inv.get("tds") else {"applicable": False}),

        "bill_wise": inv.get("bill_wise"),

        "totals": {
            "taxable_amount": float(t["taxable"]),
            "cgst": float(t["cgst"]), "sgst": float(t["sgst"]),
            "igst": float(t["igst"]), "cess": float(t["cess"]),
            "other_charges": float(t["charges"]),
            "total_discount": float(t["discount"]),
            "tds_deducted": float(t["tds"]), "tcs_collected": float(t["tcs"]),
            "advance_adjusted": float(t["advance"]),
            "round_off": float(t["round_off"]),
            "total": float(t["total"]), "amount_payable": float(t["total"]),
            "total_items": t["count"], "total_qty": float(t["qty"]),
            "gst_rates_present": t["rates"],
            "amount_in_words": t["words"],
        },

        "expected_voucher": v,
    }
