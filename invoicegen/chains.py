"""Generate linked sequences of transactions.

Some events only make sense against an earlier one: a purchase that adjusts an
advance, a receipt that settles an invoice, a return against a sale. Rather
than inventing a dangling reference, the chain builder emits the whole
sequence - same party, consistent amounts, and cross-references that point at
documents which actually exist in the batch.

Every transaction in a chain carries:
    chain_id     shared id for the sequence
    chain_step   1-based position
    links_to     documents this one references
    linked_from  documents that reference this one
"""
from datetime import timedelta
from decimal import Decimal

from .model import money
from .transactions import build_txn, FY, SERIES

# scenario -> the chain that produces it, as a list of scenario ids in order.
# The last entry is the scenario the user actually asked for.
CHAINS = {
    "pur_advance":       ["pay_advance", "pur_advance"],
    "sale_advance":      ["rcpt_advance", "sale_advance"],
    "pur_against_po":    ["pur_order", "pur_against_po"],
    "sale_against_so":   ["sale_order", "sale_against_so"],
    "pur_return_goods":  ["pur_goods_local", "pur_return_goods"],
    "pur_return_serv":   ["pur_serv_local", "pur_return_serv"],
    "sale_return_goods": ["sale_goods_local", "sale_return_goods"],
    "sale_cancel":       ["sale_goods_local", "sale_cancel"],
    "rcpt_against_inv":  ["sale_goods_local", "rcpt_against_inv"],
    "rcpt_partial":      ["sale_goods_local", "rcpt_partial"],
    "rcpt_multi":        ["sale_goods_local", "sale_goods_local",
                          "sale_goods_local", "rcpt_multi"],
    "rcpt_adv_adjust":   ["rcpt_advance", "sale_goods_local",
                          "rcpt_adv_adjust"],
    "rcpt_debit_note":   ["sale_goods_local", "rcpt_debit_note"],
    "rcpt_credit_note":  ["sale_goods_local", "rcpt_credit_note"],
    "pay_against_inv":   ["pur_goods_local", "pay_against_inv"],
    "pay_partial":       ["pur_goods_local", "pay_partial"],
    "pay_multi":         ["pur_goods_local", "pur_goods_local",
                          "pur_goods_local", "pay_multi"],
    "pay_adv_adjust":    ["pay_advance", "pur_goods_local", "pay_adv_adjust"],
    "pay_debit_note":    ["pur_goods_local", "pay_debit_note"],
    "pay_credit_note":   ["pur_goods_local", "pay_credit_note"],
    "cheque_bounce_cust": ["sale_goods_local", "rcpt_against_inv",
                           "cheque_bounce_cust"],
    "cheque_bounce_vend": ["pur_goods_local", "pay_against_inv",
                           "cheque_bounce_vend"],
    "fa_capitalise":     ["fa_purchase", "fa_capitalise"],
    "fa_disposal":       ["fa_purchase", "fa_disposal"],
}


def is_chained(sid):
    return sid in CHAINS


def chain_length(sid):
    return len(CHAINS.get(sid, [sid]))


def _doc_amount(t):
    """What this document is worth, whichever kind it is."""
    return money(t.meta.get("total", t.meta.get("amount", 0)))


def build_chain(sid, rng, items, parties, ledgers, seq, chain_no,
                opts=None):
    """Return the ordered list of Txns making up this scenario.

    Unchained scenarios come back as a single-element list.
    """
    steps = CHAINS.get(sid, [sid])
    chain_id = f"CH{chain_no:04d}"
    out = []

    for i, step_sid in enumerate(steps):
        t = build_txn(step_sid, rng, items, parties, ledgers,
                      seq + i, opts)
        t.meta["chain_id"] = chain_id
        t.meta["chain_step"] = i + 1
        t.meta["chain_total"] = len(steps)
        t.meta["chain_scenario"] = sid
        t.meta.setdefault("links_to", [])
        t.meta.setdefault("linked_from", [])
        out.append(t)

    if len(out) > 1:
        _relink(sid, out)
    return out


def _link(a, b, role):
    """Record that `b` references `a`."""
    b.meta["links_to"].append({"number": a.number, "kind": a.kind,
                               "role": role,
                               "date": a.date.isoformat()})
    a.meta["linked_from"].append({"number": b.number, "kind": b.kind,
                                  "role": role,
                                  "date": b.date.isoformat()})


def _same_party(txns):
    """Put every step onto one party - and move its ledger legs with it.

    Each step was built independently, so it may name a different party. The
    leg carrying that party's old ledger has to be renamed too, or the chain
    would post to two unrelated accounts.
    """
    party = next((t.party for t in txns if t.party), None)
    if not party:
        return
    new_led = party["tally_ledger"]
    for t in txns:
        if t.party is None:          # a contra step has no outside party
            continue
        old_led = t.party["tally_ledger"]
        old_name = t.party.get("name", old_led)
        t.party = party
        if old_led != new_led:
            for leg in t.legs:
                if leg["ledger"] == old_led:
                    leg["ledger"] = new_led
            # the narration names the party too - replace both the ledger and
            # the display name, longest first so a partial match cannot win
            if t.narration:
                for old_text in sorted({old_led, old_name}, key=len,
                                       reverse=True):
                    t.narration = t.narration.replace(old_text, party["name"])


def _order_dates(txns):
    """Make each step fall after the one before it."""
    d = txns[0].date
    for i, t in enumerate(txns):
        if i == 0:
            continue
        d = d + timedelta(days=rngdays(t, i))
        t.date = d


def rngdays(t, i):
    # deterministic small gap; avoids needing the rng here
    return 3 + (hash(t.number) % 25)


def _repost(t, ledgers):
    """Rebuild a transaction's legs after its amounts changed."""
    from .transactions import _post_document
    tags = []
    t.legs = []
    return t


def _relink(sid, txns):
    """Wire the steps together: shared party, ordered dates, real references
    and amounts that agree across the chain."""
    _same_party(txns)
    _order_dates(txns)
    last = txns[-1]

    # ---------- advance then invoice
    if sid in ("pur_advance", "sale_advance"):
        adv, inv = txns[0], txns[1]
        # size the advance from the invoice, not the other way round, so it
        # reads like a real part-payment rather than a random figure
        gross = money(inv.meta["taxable"] + inv.meta["charges"]
                      + inv.meta["tax"])
        amount = money(gross * Decimal("0.3"))
        _rewrite_money(adv, amount, [])
        adv.meta["method"] = "Advance"
        _rewrite_advance(inv, amount, adv.number)
        _link(adv, inv, "advance adjusted")

    # ---------- order then invoice
    elif sid in ("pur_against_po", "sale_against_so"):
        order, inv = txns[0], txns[1]
        inv.meta["against_order"] = order.number
        inv.meta["order_date"] = order.date.isoformat()
        _link(order, inv, "order fulfilled")

    # ---------- invoice then return / note
    elif sid in ("pur_return_goods", "pur_return_serv", "sale_return_goods",
                 "sale_cancel", "rcpt_debit_note", "rcpt_credit_note",
                 "pay_debit_note", "pay_credit_note"):
        inv, note = txns[0], txns[1]
        note.meta["original_invoice"] = {
            "number": inv.number, "date": inv.date.strftime("%d %b %Y"),
            "date_iso": inv.date.isoformat(),
            "reason": note.meta.get("original_invoice", {}).get(
                "reason", "Adjustment against original invoice"),
        }
        if sid == "sale_cancel":
            # a cancellation reverses the invoice in full
            _mirror_amounts(note, inv)
            note.meta["original_invoice"]["reason"] = \
                "Invoice cancelled - full reversal"
        _link(inv, note, "adjusted by note")

    # ---------- invoice(s) then receipt / payment
    elif sid in ("rcpt_against_inv", "pay_against_inv", "rcpt_partial",
                 "pay_partial", "rcpt_multi", "pay_multi"):
        invs, money_txn = txns[:-1], txns[-1]
        bills = []
        for inv in invs:
            due = _doc_amount(inv)
            paid = due
            if "partial" in sid:
                paid = money(due * Decimal("0.4"))
            bills.append({"ref": inv.number, "amount": float(paid),
                          "bill_total": float(due),
                          "bill_date": inv.date.isoformat()})
            _link(inv, money_txn, "settled by")
        total = money(sum(Decimal(str(b["amount"])) for b in bills))
        _rewrite_money(money_txn, total, bills)

    # ---------- advance, invoice, then the adjusting journal
    elif sid in ("rcpt_adv_adjust", "pay_adv_adjust"):
        adv, inv, jv = txns
        amount = min(_doc_amount(adv), _doc_amount(inv))
        _rewrite_journal(jv, amount)
        jv.meta["adjusted_advance"] = adv.number
        jv.meta["adjusted_invoice"] = inv.number
        _link(adv, jv, "advance adjusted")
        _link(inv, jv, "against invoice")

    # ---------- invoice, receipt, then the bounce
    elif sid in ("cheque_bounce_cust", "cheque_bounce_vend"):
        inv, rcpt, jv = txns
        # the receipt settles that invoice, so it is worth the same
        _rewrite_money(rcpt, _doc_amount(inv),
                       [{"ref": inv.number, "amount": float(_doc_amount(inv)),
                         "bill_total": float(_doc_amount(inv)),
                         "bill_date": inv.date.isoformat()}])
        _link(inv, rcpt, "settled by")
        rcpt.meta["mode"] = "Cheque"
        rcpt.meta.setdefault("cheque", {
            "number": str(700000 + (hash(rcpt.number) % 99999)),
            "date": rcpt.date.isoformat(), "bank": "HDFC Bank"})
        amount = _doc_amount(rcpt)
        _rewrite_journal(jv, amount)
        jv.meta["bounced_cheque"] = rcpt.meta["cheque"]
        jv.meta["bounced_voucher"] = rcpt.number
        jv.meta["against_invoice"] = inv.number
        _link(rcpt, jv, "cheque dishonoured")
        _link(inv, jv, "remains unpaid")

    # ---------- asset bought, then capitalised or disposed
    elif sid in ("fa_capitalise", "fa_disposal"):
        buy, ev = txns[0], txns[1]
        cost = _doc_amount(buy)
        ev.meta["asset_invoice"] = buy.number
        ev.meta["asset_cost"] = float(cost)
        if sid == "fa_capitalise":
            _rewrite_journal(ev, cost)
        else:
            _rewrite_disposal(ev, cost)
        _link(buy, ev, "asset acquired")


# ------------------------------------------------------------ amount fixes

def _rewrite_advance(inv, amount, ref):
    """Set the invoice's advance to the real one and re-derive its total.

    The advance can never exceed what the invoice is worth, so it is capped at
    the gross value before tax adjustments.
    """
    m = inv.meta
    gross = money(m["taxable"] + m["charges"]
                  + (Decimal(0) if m.get("rcm") else m["tax"])
                  + m.get("customs_duty", 0) + m.get("tcs", 0)
                  - m.get("cash_discount", 0) - m.get("tds_amount", 0))
    amount = min(amount, money(gross * Decimal("0.6")))
    m["advance"] = amount
    m["advance_ref"] = ref

    # rebuild the total from its parts rather than nudging it
    pre = money(gross - amount)
    total = Decimal(int(pre.to_integral_value()))
    m["round_off"] = money(total - pre)
    m["total"] = total

    # Rebuild the three legs the change touches. The round-off leg may not
    # exist yet (or may need removing), so handle it by rebuilding the list.
    party_led = inv.party["tally_ledger"] if inv.party else None
    purchase = inv.kind == "purchase_invoice"
    legs = []
    for leg in inv.legs:
        if leg["ledger"] == "Round Off":
            continue                         # re-added below at its new value
        # On a purchase both the advance and the supplier are credits; on a
        # sale both the advance and the customer are debits (see the unchained
        # posting in transactions._post_document).
        if leg["ledger"] in ("Advance to Suppliers", "Advance from Customers"):
            leg["dr"] = 0.0 if purchase else float(amount)
            leg["cr"] = float(amount) if purchase else 0.0
        elif leg["ledger"] == party_led:
            leg["dr"] = 0.0 if purchase else float(total)
            leg["cr"] = float(total) if purchase else 0.0
        legs.append(leg)
    inv.legs = legs
    # Derive the round-off leg from the actual imbalance rather than from a
    # sign convention - whatever is missing IS the rounding difference.
    gap = money(inv.total_dr - inv.total_cr)
    if gap:
        inv.legs.append({"ledger": "Round Off",
                         "dr": float(max(-gap, Decimal(0))),
                         "cr": float(max(gap, Decimal(0)))})


def _mirror_amounts(note, inv):
    """Make a cancellation exactly reverse its invoice."""
    note.lines = list(inv.lines)
    for k in ("taxable", "charges", "tax", "round_off", "total"):
        note.meta[k] = inv.meta.get(k, Decimal(0))
    scale = None
    note.legs = []
    for leg in inv.legs:
        note.legs.append({"ledger": leg["ledger"], "dr": leg["cr"],
                          "cr": leg["dr"]})
    del scale


def _rewrite_money(t, amount, bills):
    """Point a receipt/payment at real bills and set its amount."""
    old = t.meta["amount"]
    t.meta["amount"] = amount
    t.meta["bills"] = bills
    t.meta["method"] = "Agst Ref"
    if old:
        for leg in t.legs:
            side = "dr" if leg["dr"] else "cr"
            if money(leg[side]) == old:
                leg[side] = float(amount)


def _rewrite_journal(t, amount):
    old = t.meta.get("amount", Decimal(0))
    t.meta["amount"] = amount
    for leg in t.legs:
        side = "dr" if leg["dr"] else "cr"
        if not old or money(leg[side]) == old:
            leg[side] = float(amount)


def _rewrite_disposal(t, cost):
    """Recompute a disposal from the real acquisition cost."""
    accum = money(cost * Decimal("0.5"))
    wdv = money(cost - accum)
    proceeds = money(wdv * Decimal("1.1"))
    gain = money(proceeds - wdv)
    block = t.meta.get("asset_block", "Office Equipment")
    t.legs = []
    t.dr("State Bank of India - 40930926740", proceeds)
    t.dr("Accumulated Depreciation", accum)
    if gain < 0:
        t.dr("Loss on Sale of Asset", -gain)
    t.cr(block, cost)
    if gain > 0:
        t.cr("Profit on Sale of Asset", gain)
    t.meta.update({"amount": proceeds, "asset_cost": float(cost),
                   "accumulated_dep": float(accum), "wdv": float(wdv),
                   "gain_loss": float(gain)})


def _shift_total(t, delta):
    """Move a document's total by `delta`, keeping the party leg in step."""
    if delta == 0:
        return
    m = t.meta
    new_total = money(m["total"] + delta)
    party_led = t.party["tally_ledger"] if t.party else None
    for leg in t.legs:
        if leg["ledger"] == party_led:
            side = "dr" if leg["dr"] else "cr"
            leg[side] = float(new_total)
            break
    m["total"] = new_total
