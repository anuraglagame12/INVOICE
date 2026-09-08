"""Build a document and its Tally voucher for any catalogue scenario.

Every scenario resolves to a `Txn`: the printed document (or none), the party,
the lines, and the balanced Dr/Cr legs Tally should end up with. The posting
rules live here rather than in the renderer, so a journal-only event is handled
exactly like an invoice minus the paper.
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from .model import Charge, Line, half_tax, money
from . import catalogue as cat

FY = "26-27"
FY_START = date(2026, 4, 1)

# document series by kind
SERIES = {
    "purchase_invoice": "PB", "sales_invoice": "SI",
    "credit_note": "CN", "debit_note": "DN",
    "purchase_order": "PO", "sales_order": "SO",
    "receipt": "RC", "payment": "PY", "contra": "CT", "journal": "JV",
}

TITLES = {
    "purchase_invoice": "PURCHASE INVOICE", "sales_invoice": "TAX INVOICE",
    "credit_note": "CREDIT NOTE", "debit_note": "DEBIT NOTE",
    "purchase_order": "PURCHASE ORDER", "sales_order": "SALES ORDER",
    "receipt": "RECEIPT VOUCHER", "payment": "PAYMENT VOUCHER",
    "contra": "CONTRA VOUCHER", "journal": "JOURNAL VOUCHER",
}


class Txn:
    """One transaction: what is printed, and what Tally should record."""

    def __init__(self, sid, kind, title, number, d, party=None):
        self.sid = sid
        self.kind = kind                  # purchase_invoice, receipt, journal...
        self.title = title
        self.number = number
        self.date = d
        self.party = party
        self.lines = []
        self.charges = []
        self.legs = []                    # (ledger, amount, is_debit)
        self.narration = ""
        self.meta = {}                    # scenario-specific extras
        self.interstate = False
        self.tax_free = False             # export / SEZ / composition / URD

    # ---- posting helpers

    def dr(self, ledger, amount):
        self._leg(ledger, amount, True)

    def cr(self, ledger, amount):
        self._leg(ledger, amount, False)

    def _leg(self, ledger, amount, debit):
        a = money(amount)
        if a == 0:
            return
        if a < 0:                       # never post a negative; flip the side
            debit, a = not debit, -a
        self.legs.append({"ledger": ledger, "dr": float(a) if debit else 0.0,
                          "cr": 0.0 if debit else float(a)})

    @property
    def total_dr(self):
        return money(sum(l["dr"] for l in self.legs))

    @property
    def total_cr(self):
        return money(sum(l["cr"] for l in self.legs))

    @property
    def balanced(self):
        return self.total_dr == self.total_cr

    @property
    def posts_to_tally(self):
        return self.kind not in ("purchase_order", "sales_order")


# ------------------------------------------------------------------ helpers

def _pick_items(rng, items, tags, count):
    """Choose catalogue rows appropriate to the scenario."""
    goods = items["items"]
    if "capital" in tags:
        pool = [i for i in goods if i["group"] in
                ("appliance", "power", "fans")] or goods
    elif "scrap" in tags:
        pool = [i for i in goods if i["group"] in ("wire", "conduit")] or goods
    elif "expense" in tags:
        pool = [i for i in goods if i["group"] == "consumable"] or goods
    else:
        pool = goods
    return [rng.choice(pool) for _ in range(count)]


def _party_for(rng, tags, parties):
    """Pick a party matching the scenario's nature of supply."""
    if "import" in tags or "export" in tags:
        return dict(rng.choice(parties["foreign_parties"])), True
    if "sez" in tags:
        return dict(rng.choice(parties["sez_parties"])), False
    if "composition" in tags:
        return dict(rng.choice(parties["composition_dealers"])), False
    if "unregistered_party" in tags:
        return dict(rng.choice(parties["unregistered_buyers"])), False

    pool = parties["suppliers"] if "purchase" in tags else parties["buyers"]
    want_inter = "inter" in tags
    matching = [p for p in pool
                if (p["state_code"] != "27") == want_inter]
    return dict(rng.choice(matching or pool)), False


def _amount(rng, small=False, big=False):
    if small:
        return Decimal(rng.randrange(500, 15000, 50))
    if big:
        return Decimal(rng.randrange(100000, 2500000, 500))
    return Decimal(rng.randrange(5000, 250000, 100))


# ------------------------------------------------------------------ builders

def build_txn(sid, rng, items, parties, ledgers, seq, opts=None):
    """Turn one catalogue scenario into a Txn."""
    opts = opts or {}
    tags = cat.tags(sid)
    doc = cat.doc_kind(sid)
    d = FY_START + timedelta(days=rng.randint(0, 330))

    if doc == "none":
        kind = "journal"
    elif doc == "voucher":
        kind = ("contra" if "contra" in tags
                else "receipt" if "receipt" in tags else "payment")
    elif doc == "order":
        kind = "purchase_order" if "purchase" in tags else "sales_order"
    elif doc == "note":
        kind = "credit_note" if "credit_note" in tags else "debit_note"
    else:
        kind = "purchase_invoice" if "purchase" in tags else "sales_invoice"

    # A bill we receive was numbered by the supplier in their own series, so
    # it must not look like one of ours.
    if kind in ("purchase_invoice", "debit_note") and "purchase" in tags:
        num = f"{rng.choice(['SEP', 'INV', 'GST', 'TI', 'BL'])}/"               f"{FY[:2]}-{FY[3:]}/{rng.randint(100, 4999)}"
    else:
        num = f"AE/{SERIES[kind]}/{FY}/{26400 + seq}"
    t = Txn(sid, kind, TITLES[kind], num, d)
    t.meta["scenario_label"] = cat.label(sid)

    if kind == "journal":
        _build_journal(t, sid, tags, rng, ledgers, parties)
    elif kind in ("receipt", "payment", "contra"):
        _build_voucher(t, sid, tags, rng, ledgers, parties)
    else:
        _build_document(t, sid, tags, rng, items, parties, ledgers, opts)
    return t


# ---------------------------------------------------------- trade documents

def _build_document(t, sid, tags, rng, items, parties, ledgers,
                    opts=None):
    """An invoice, note or order: has line items and a tax computation."""
    party, foreign = _party_for(rng, tags, parties)
    t.party = party
    t.interstate = (party["state_code"] != "27") and not foreign
    purchase = "purchase" in tags
    trading = ledgers["trading"]

    # export, SEZ, composition and unregistered supplies carry no GST
    zero = any(k in tags for k in ("export", "sez", "composition",
                                   "unregistered_party"))
    t.tax_free = zero
    rcm = "rcm" in tags

    opts = opts or {}
    services = "services" in tags or "expense" in tags
    # how many lines: the caller may fix it, otherwise vary. A note adjusts
    # one line, so it ignores the setting.
    if t.kind in ("credit_note", "debit_note"):
        n = 1
    elif services:
        n = int(opts.get("service_lines") or 0) or rng.randint(2, 6)
    else:
        n = int(opts.get("goods_lines") or 0) or rng.randint(2, 6)

    # a discount appears only when asked for - either by the scenario itself
    # or by the caller ticking the discount option
    want_disc = "trade_discount" in tags or bool(opts.get("discount"))

    if services:
        pool = items["services"]
        for _ in range(n):
            sv = rng.choice(pool)
            disc = rng.choice([5, 10, 15]) if want_disc else 0
            t.lines.append(Line(sv["desc"], sv["sac"], sv["mrp"],
                                rng.choice([1, 1, 2]), sv["uom"],
                                0 if zero else sv["gst"],
                                discount_pct=disc, kind="service"))
    else:
        for it in _pick_items(rng, items, tags, n):
            qty = rng.choice([1, 2, 4, 5, 10, 20, 25])
            disc = rng.choice([10, 15, 20, 25]) if want_disc else 0
            t.lines.append(Line(it["desc"], it["hsn"], it["mrp"], qty,
                                it["uom"], 0 if zero else it["gst"],
                                discount_pct=disc, kind="goods"))

    ch = ledgers["charges"]
    if "freight" in tags:
        t.charges.append(Charge("Freight Charges",
                                rng.choice([450, 850, 1200, 2500]),
                                ch["freight_in"] if purchase
                                else ch["freight_out"], code="996511", gst=18))
    for tag, label, key in (("packing", "Packing Charges", "packing"),
                            ("insurance", "Insurance Charges", "insurance"),
                            ("loading", "Loading & Unloading", "loading")):
        if tag in tags:
            t.charges.append(Charge(label, rng.choice([250, 600, 900]),
                                    ch[key]))

    # ---- totals
    taxable = money(sum(l.taxable for l in t.lines))
    charge_amt = money(sum(c.amount for c in t.charges))
    tax = money(sum(l.tax for l in t.lines) + sum(c.tax for c in t.charges))
    # CGST and SGST must post identical, so an intra-state tax carries twice
    # the rounded half - never a paisa that cannot be split evenly.
    if not t.interstate:
        tax = money(half_tax(tax) * 2)
    payable_tax = Decimal(0) if rcm else tax

    cash_disc = (money(taxable * Decimal(rng.choice([1, 2]))/100)
                 if "cash_discount" in tags else Decimal(0))
    tds = Decimal(0)
    if "tds" in tags:
        sec = rng.choice(parties["tds_sections"])
        tds = money(taxable * Decimal(str(sec["rate"])) / 100)
        t.meta["tds"] = {"section": sec["section"], "nature": sec["nature"],
                         "rate": sec["rate"], "base": float(taxable),
                         "amount": float(tds),
                         "ledger": f"TDS Payable - {sec['section']}"}
    tcs = money((taxable + payable_tax) * Decimal("0.1") / 100) \
        if "tcs" in tags else Decimal(0)
    advance = money(_amount(rng, small=True)) if "advance" in tags \
        else Decimal(0)
    duty = money(taxable * Decimal(rng.choice([7, 10, 15])) / 100) \
        if "import" in tags and "goods" in tags else Decimal(0)

    gross = money(taxable + charge_amt + payable_tax + duty
                  + tcs - cash_disc - tds - advance)
    total = Decimal(int(gross.to_integral_value()))
    round_off = money(total - gross)

    t.meta.update({
        "taxable": taxable, "charges": charge_amt, "tax": tax,
        "cash_discount": cash_disc, "tds_amount": tds, "tcs": tcs,
        "advance": advance, "customs_duty": duty,
        "round_off": round_off, "total": total, "rcm": rcm, "zero_rated": zero,
    })
    if foreign:
        t.meta["currency"] = party.get("currency", "USD")
        t.meta["exchange_rate"] = party.get("rate", 86.40)
    if "against_order" in tags:
        t.meta["against_order"] = (
            f"AE/{'PO' if purchase else 'SO'}/{FY}/{26100 + rng.randint(1, 280)}")
    if t.kind in ("credit_note", "debit_note"):
        od = t.date - timedelta(days=rng.randint(5, 90))
        t.meta["original_invoice"] = {
            "number": f"AE/{'PB' if purchase else 'SI'}/{FY}/"
                      f"{26100 + rng.randint(1, 280)}",
            "date": od.strftime("%d %b %Y"), "date_iso": od.isoformat(),
            "reason": rng.choice(
                ["Goods returned - damaged in transit",
                 "Rate difference as per revised quotation",
                 "Short supply against original invoice",
                 "Quality rejection - material returned"]),
        }
    if t.kind in ("purchase_order", "sales_order"):
        t.meta["order_terms"] = {
            "delivery_date": (t.date + timedelta(
                days=rng.choice([7, 14, 21, 30]))).isoformat(),
            "payment_terms": rng.choice(
                ["30 days from date of invoice", "45 days credit",
                 "50% advance, balance against delivery"]),
            "delivery_terms": rng.choice(
                ["Ex-works Pune", "FOR site", "Freight prepaid"]),
        }
        return                       # an order posts nothing

    _post_document(t, tags, ledgers, purchase)


def _post_document(t, tags, ledgers, purchase):
    """Dr/Cr legs for an invoice or note."""
    m, tr, tx = t.meta, ledgers["trading"], ledgers["tax"]
    ch, disc = ledgers["charges"], ledgers["discounts"]
    note = t.kind in ("credit_note", "debit_note")

    # a purchase debits the expense side; a sale credits income. A note
    # reverses whichever it adjusts.
    trade_dr = purchase
    if note:
        trade_dr = not trade_dr

    if purchase:
        if "import" in tags:
            acc = tr["purchase_import"]
        elif "composition" in tags:
            acc = tr["purchase_composition"]
        elif "unregistered_party" in tags:
            acc = tr["purchase_urd"]
        elif "capital" in tags:
            acc = rng_asset(t)
        elif "expense" in tags:
            acc = t.meta.get("expense_ledger", "Miscellaneous Expenses")
        elif "services" in tags:
            acc = tr["purchase_services"]
        else:
            acc = tr["purchase_goods"]
        if note:
            acc = tr["purchase_return"]
    else:
        if "export" in tags:
            acc = tr["sales_export"]
        elif "sez" in tags:
            acc = tr["sales_sez"]
        elif "scrap" in tags:
            acc = tr["sales_scrap"]
        elif "asset_sale" in tags:
            acc = ledgers["assets"]["block"][0]["name"]
        elif "services" in tags:
            acc = tr["sales_services"]
        else:
            acc = tr["sales_goods"]
        if note:
            acc = tr["sales_return"]

    t._leg(acc, m["taxable"], trade_dr)

    for c in t.charges:
        t._leg(c.ledger, c.amount, trade_dr)

    if m["customs_duty"]:
        t.dr(ledgers["tax"]["customs_duty"], m["customs_duty"])

    # GST. Under RCM the supplier charges none but the recipient books both
    # sides; on zero-rated supplies there is no tax at all.
    if not m["zero_rated"]:
        side = "input" if purchase else "output"
        if m["rcm"]:
            t.dr(tx[f"{side}_igst" if t.interstate else f"{side}_cgst"],
                 m["tax"] if t.interstate else half_tax(m["tax"]))
            if not t.interstate:
                t.dr(tx[f"{side}_sgst"], half_tax(m["tax"]))
            t.cr(tx["rcm_payable"], m["tax"])
        elif t.interstate:
            t._leg(tx[f"{side}_igst"], m["tax"], trade_dr)
        else:
            half = half_tax(m["tax"])
            t._leg(tx[f"{side}_cgst"], half, trade_dr)
            t._leg(tx[f"{side}_sgst"], half, trade_dr)

    if m["cash_discount"]:
        t._leg(disc["cash_received"] if purchase else disc["cash_allowed"],
               m["cash_discount"], not trade_dr)
    if m["tcs"]:
        t._leg(tx["tcs_payable"], m["tcs"], trade_dr)
    if m["tds_amount"]:
        t._leg(t.meta["tds"]["ledger"], m["tds_amount"], not trade_dr)
    if m["advance"]:
        t._leg(ledgers["control"]["advance_vendor" if purchase
                                 else "advance_customer"],
               m["advance"], not trade_dr)
    if m["round_off"]:
        t._leg(ch["round_off"], m["round_off"], trade_dr)

    t._leg(t.party["tally_ledger"], m["total"], not trade_dr)
    t.narration = (f"Being {t.meta['scenario_label'].lower()} vide "
                   f"{t.number}")


def rng_asset(t):
    return "Office Equipment"


# ------------------------------------------------------- receipts, payments

def _build_voucher(t, sid, tags, rng, ledgers, parties):
    """A money movement: receipt, payment or contra."""
    bank, ctrl = ledgers["banking"], ledgers["control"]
    is_receipt = "receipt" in tags
    cash = "cash" in tags or "petty" in tags

    instrument = (bank["petty_cash"] if "petty" in tags
                  else bank["cash"] if cash else bank["bank_primary"])

    # ---- contra: money between our own accounts, no outside party
    if "contra" in tags:
        amt = money(_amount(rng, small=True))
        if "deposit" in tags:
            t.dr(bank["bank_primary"], amt)
            t.cr(bank["cash"], amt)
            t.narration = "Being cash deposited into bank"
        elif "withdrawal" in tags:
            t.dr(bank["cash"], amt)
            t.cr(bank["bank_primary"], amt)
            t.narration = "Being cash withdrawn from bank"
        else:
            t.dr(bank["bank_secondary"], amt)
            t.cr(bank["bank_primary"], amt)
            t.narration = "Being funds transferred between bank accounts"
        t.meta.update({"amount": amt, "instrument": instrument,
                       "mode": "Contra"})
        return

    # ---- employee-facing vouchers
    if "reimbursement" in tags or "employee_advance" in tags \
            or "imprest" in tags:
        emp = rng.choice(ledgers["employees"])
        amt = money(_amount(rng, small=True))
        t.party = {"name": emp, "gstin": None, "state": "MAHARASHTRA",
                   "state_code": "27", "bill": ["Employee"], "ship": [],
                   "tally_ledger": f"{emp} - Employee"}
        if "employee_advance" in tags:
            t.dr(ctrl["employee_advance"], amt)
            t.narration = f"Being advance paid to {emp}"
        elif "imprest" in tags:
            t.dr(bank["petty_cash"], amt)
            t.narration = "Being imprest replenished"
        else:
            t.dr(ledgers["expenses"]["reimbursement"], amt)
            t.narration = f"Being expenses reimbursed to {emp}"
        t.cr(instrument, amt)
        t.meta.update({"amount": amt, "instrument": instrument,
                       "mode": "Cash" if cash else "Bank Transfer"})
        return

    # ---- plain petty-cash expense
    if "petty" in tags:
        amt = money(rng.randrange(100, 4000, 10))
        head = rng.choice(ledgers["expenses"]["indirect"])
        t.dr(head, amt)
        t.cr(bank["petty_cash"], amt)
        t.narration = f"Being petty cash spent on {head.lower()}"
        t.meta.update({"amount": amt, "instrument": bank["petty_cash"],
                       "mode": "Cash"})
        return

    # ---- customer receipt / vendor payment
    pool = parties["buyers"] if is_receipt else parties["suppliers"]
    party = dict(rng.choice(pool))
    t.party = party
    amt = money(_amount(rng))

    bills = []
    if "multi_bill" in tags:
        for _ in range(rng.randint(2, 4)):
            bills.append({"ref": f"AE/{'SI' if is_receipt else 'PB'}/{FY}/"
                                 f"{26100 + rng.randint(1, 280)}",
                          "amount": float(money(amt / rng.randint(2, 4)))})
        amt = money(sum(b["amount"] for b in bills))
    elif "against_bill" in tags:
        ref = f"AE/{'SI' if is_receipt else 'PB'}/{FY}/{26100 + rng.randint(1, 280)}"
        full = amt
        if "partial" in tags:
            amt = money(full * Decimal(rng.choice(["0.3", "0.4", "0.5"])))
        bills.append({"ref": ref, "amount": float(amt),
                      "bill_total": float(full)})

    if is_receipt:
        t.dr(instrument, amt)
        if "advance_received" in tags:
            t.cr(ctrl["advance_customer"], amt)
            t.narration = f"Being advance received from {party['name']}"
        else:
            t.cr(party["tally_ledger"], amt)
            t.narration = f"Being amount received from {party['name']}"
    else:
        if "advance_paid" in tags:
            t.dr(ctrl["advance_vendor"], amt)
            t.narration = f"Being advance paid to {party['name']}"
        else:
            t.dr(party["tally_ledger"], amt)
            t.narration = f"Being amount paid to {party['name']}"
        t.cr(instrument, amt)

    mode = "Cash" if cash else rng.choice(
        ["NEFT", "RTGS", "UPI", "Cheque"]) if "cheque" not in tags else "Cheque"
    t.meta.update({
        "amount": amt, "instrument": instrument, "mode": mode,
        "bills": bills,
        "method": ("On Account" if "on_account" in tags
                   else "Advance" if "advance" in " ".join(tags)
                   else "Agst Ref" if bills else "On Account"),
    })
    if mode == "Cheque":
        t.meta["cheque"] = {
            "number": str(rng.randint(100000, 999999)),
            "date": (t.date + timedelta(days=rng.randint(0, 5))).isoformat(),
            "bank": rng.choice(["HDFC Bank", "ICICI Bank", "Axis Bank",
                                "Bank of Baroda"]),
        }


# ---------------------------------------------------------------- journals

def _build_journal(t, sid, tags, rng, ledgers, parties):
    """A journal event: no document, but a real accounting entry."""
    bank, ctrl = ledgers["banking"], ledgers["control"]
    exp, ast = ledgers["expenses"], ledgers["assets"]
    amt = money(_amount(rng, small=True))
    t.meta["amount"] = amt

    def party_of(kind):
        pool = parties["buyers"] if kind == "customer" else parties["suppliers"]
        p = dict(rng.choice(pool))
        t.party = p
        return p["tally_ledger"]

    if "advance_adjust" in tags:
        who = "customer" if "customer" in tags else "vendor"
        led = party_of(who)
        adv = ctrl["advance_customer"] if who == "customer" \
            else ctrl["advance_vendor"]
        if who == "customer":
            t.dr(adv, amt)
            t.cr(led, amt)
        else:
            t.dr(led, amt)
            t.cr(adv, amt)
        t.narration = f"Being advance adjusted against {who} bills"

    elif "discount_allowed" in tags:
        led = party_of("customer")
        t.dr(ledgers["discounts"]["cash_allowed"], amt)
        t.cr(led, amt)
        t.narration = "Being discount allowed to customer"

    elif "discount_received" in tags:
        led = party_of("vendor")
        t.dr(led, amt)
        t.cr(ledgers["discounts"]["cash_received"], amt)
        t.narration = "Being discount received from supplier"

    elif "bad_debt" in tags:
        led = party_of("customer")
        t.dr(ctrl["bad_debts"], amt)
        t.cr(led, amt)
        t.narration = "Being balance written off as bad debt"

    elif "write_back" in tags:
        led = party_of("vendor")
        t.dr(led, amt)
        t.cr(ctrl["write_back"], amt)
        t.narration = "Being old credit balance written back"

    elif "bank_chg" in tags:
        amt = money(rng.randrange(50, 2500, 10))
        t.dr(bank["bank_charges"], amt)
        t.cr(bank["bank_primary"], amt)
        t.narration = "Being bank charges debited by bank"
        t.meta["amount"] = amt

    elif "interest_income" in tags:
        t.dr(bank["bank_primary"], amt)
        t.cr(bank["interest_income"], amt)
        t.narration = "Being interest credited by bank"

    elif "interest_expense" in tags:
        t.dr(bank["interest_expense"], amt)
        t.cr(bank["bank_primary"], amt)
        t.narration = "Being interest charged by bank"

    elif "bounce" in tags:
        who = "customer" if "customer" in tags else "vendor"
        led = party_of(who)
        if who == "customer":
            t.dr(led, amt)
            t.cr(bank["bank_primary"], amt)
            t.narration = "Being cheque returned unpaid by bank"
        else:
            t.dr(bank["bank_primary"], amt)
            t.cr(led, amt)
            t.narration = "Being our cheque returned unpaid"

    elif "reconciliation" in tags:
        t.dr(bank["bank_primary"], amt)
        t.cr(ctrl["suspense"], amt)
        t.narration = "Being bank reconciliation difference adjusted"

    elif "accrual" in tags or "outstanding" in tags:
        head = rng.choice(exp["indirect"])
        t.dr(head, amt)
        t.cr(exp["outstanding"], amt)
        t.narration = f"Being {head.lower()} accrued but not paid"

    elif "prepaid_create" in tags:
        head = rng.choice(exp["indirect"])
        t.dr(exp["prepaid"], amt)
        t.cr(head, amt)
        t.narration = "Being prepaid portion carried forward"

    elif "prepaid_amort" in tags:
        head = rng.choice(exp["indirect"])
        t.dr(head, amt)
        t.cr(exp["prepaid"], amt)
        t.narration = "Being prepaid expense amortised for the period"

    elif "provision_reversal" in tags:
        head = rng.choice(exp["indirect"])
        t.dr(exp["provision"], amt)
        t.cr(head, amt)
        t.narration = "Being excess provision reversed"

    elif "provision" in tags:
        head = rng.choice(exp["indirect"])
        t.dr(head, amt)
        t.cr(exp["provision"], amt)
        t.narration = f"Being provision made for {head.lower()}"

    elif "reclass" in tags or "correction" in tags:
        a, b = rng.sample(exp["indirect"], 2)
        t.dr(a, amt)
        t.cr(b, amt)
        t.narration = f"Being amount reclassified from {b} to {a}"

    elif "employee_adjust" in tags:
        emp = rng.choice(ledgers["employees"])
        head = rng.choice(exp["indirect"])
        t.dr(head, amt)
        t.cr(ctrl["employee_advance"], amt)
        t.narration = f"Being advance of {emp} adjusted against expenses"

    elif "prior_period" in tags:
        t.dr(exp["prior_period"], amt)
        t.cr(exp["outstanding"], amt)
        t.narration = "Being prior period expense recorded"

    elif "audit_adjust" in tags:
        head = rng.choice(exp["indirect"])
        t.dr(head, amt)
        t.cr(exp["provision"], amt)
        t.narration = "Being audit adjustment passed"

    elif "capitalise" in tags:
        blk = rng.choice(ast["block"])
        t.dr(blk["name"], amt)
        t.cr(ast["cwip"], amt)
        t.narration = f"Being {blk['name'].lower()} capitalised from CWIP"
        t.meta["asset_block"] = blk["name"]

    elif "depreciation" in tags:
        blk = rng.choice(ast["block"])
        cost = money(_amount(rng, big=True))
        amt = money(cost * Decimal(str(blk["rate"])) / 100)
        t.dr(ast["depreciation"], amt)
        t.cr(ast["accumulated_dep"], amt)
        t.narration = (f"Being depreciation on {blk['name'].lower()} "
                       f"@ {blk['rate']:g}%")
        t.meta.update({"amount": amt, "asset_block": blk["name"],
                       "asset_cost": float(cost), "dep_rate": blk["rate"]})

    elif "asset_transfer" in tags:
        a, b = rng.sample(ast["block"], 2)
        t.dr(b["name"], amt)
        t.cr(a["name"], amt)
        t.narration = f"Being asset transferred from {a['name']} to {b['name']}"

    elif "asset_disposal" in tags:
        blk = rng.choice(ast["block"])
        cost = money(_amount(rng, big=True))
        accum = money(cost * Decimal(rng.choice(["0.3", "0.5", "0.7"])))
        wdv = money(cost - accum)
        proceeds = money(wdv * Decimal(rng.choice(["0.8", "1.0", "1.2"])))
        t.dr(bank["bank_primary"], proceeds)
        t.dr(ast["accumulated_dep"], accum)
        gain = money(proceeds - wdv)
        if gain < 0:
            t.dr(ast["loss_on_sale"], -gain)
        t.cr(blk["name"], cost)
        if gain > 0:
            t.cr(ast["profit_on_sale"], gain)
        t.narration = f"Being {blk['name'].lower()} disposed of"
        t.meta.update({"amount": proceeds, "asset_block": blk["name"],
                       "asset_cost": float(cost),
                       "accumulated_dep": float(accum), "wdv": float(wdv),
                       "gain_loss": float(gain)})
    else:
        t.dr(ctrl["suspense"], amt)
        t.cr(ctrl["suspense"], amt)
        t.narration = "Journal entry"
