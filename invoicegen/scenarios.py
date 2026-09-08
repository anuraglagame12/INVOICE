"""Turn a set of ticked options into concrete invoices.

The web page and the CLI both funnel through `generate()`. Options are the
checkbox ids from the UI panels; an empty panel means "vary freely", and
several ticks in one panel are spread across the batch rather than crammed
into every invoice.
"""
import json
import os
import random
from datetime import date, timedelta
from decimal import Decimal

from .model import Line, Charge, money

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# Every checkbox, grouped as the UI presents it. `default` marks what is
# ticked when the page first loads.
PANELS = [
    ("Transaction side", "side", [
        ("sale", "Sales - we are selling", False),
        ("purchase", "Purchase - we are buying", False),
    ]),
    ("Document type", "doctype", [
        ("tax_invoice", "Tax Invoice", False),
        ("credit_note", "Credit Note (sales return)", False),
        ("debit_note", "Debit Note (extra charge)", False),
        ("purchase_order", "Purchase Order", False),
        ("sales_order", "Sales Order", False),
    ]),
    ("Supply type", "supply", [
        ("intra", "Intra-state (CGST + SGST)", False),
        ("inter", "Inter-state (IGST)", False),
    ]),
    ("Tax rates", "tax", [
        ("rate18", "Single rate 18%", False),
        ("rate_other", "Single rate 5% / 12% / 28%", False),
        ("mix_12_18", "Mixed 12 + 18", False),
        ("mix_all", "Mixed 5 + 12 + 18 + 28", False),
        ("exempt", "Nil-rated / exempt lines", False),
        ("cess", "Cess", False),
        ("rcm", "Reverse charge (RCM)", False),
    ]),
    ("Content", "content", [
        ("goods", "Goods only", False),
        ("services", "Services only", False),
        ("both", "Goods + services", False),
    ]),
    ("Other charges", "charges", [
        ("line_discount", "Discount on line items", False),
        ("freight", "Freight", False),
        ("packing", "Packing", False),
        ("insurance", "Insurance", False),
        ("loading", "Loading / unloading", False),
        ("advance", "Advance adjusted", False),
        ("roundoff", "Force a large round-off (near half a rupee)", False),
    ]),
    ("Party", "party", [
        ("registered", "Registered buyer (GSTIN)", False),
        ("unregistered", "Unregistered buyer (B2C)", False),
        ("name_variant", "Name differs from ledger", False),
        ("eway", "E-way bill number", False),
        ("irn", "IRN / e-invoice fields", False),
    ]),
    ("Layers", "layers", [
        ("tds", "TDS", False),
        ("tcs", "TCS", False),
        ("billwise", "Bill-wise reference", False),
        ("godown", "Godown", False),
        ("batch", "Batch numbers", False),
    ]),
    ("Volume / shape", "shape", [
        ("many_items", "Many line items (20-40)", False),
        ("long_desc", "Long item descriptions", False),
        ("large_amount", "Large amounts (10L+)", False),
        ("odd_paise", "Awkward paise / rounding", False),
        ("scanned", "Scanned / photocopied look (harder to read)", False),
    ]),
]

ALL_OPTS = {oid for _, _, opts in PANELS for oid, _, _ in opts}
DEFAULT_OPTS = [oid for _, _, opts in PANELS for oid, _, d in opts if d]


def load_data():
    """Sample items and parties, with the user's own firm if they set one.

    Everything downstream reads the seller from here, so overriding it in
    one place puts the right firm on every document.
    """
    with open(os.path.join(DATA, "items.json"), encoding="utf-8") as f:
        items = json.load(f)
    with open(os.path.join(DATA, "parties.json"), encoding="utf-8") as f:
        parties = json.load(f)
    from . import company
    parties["seller"] = company.active_seller(parties["seller"])
    return items, parties


def _panel_choices(opts, panel_key, fallback):
    """What this panel allows. Nothing ticked -> vary freely over `fallback`."""
    keys = [oid for _, key, o in PANELS if key == panel_key
            for oid, _, _ in o]
    picked = [k for k in keys if k in opts]
    return picked or fallback


# ---------------------------------------------------------------- one invoice

def make_invoice(rng, opts, items, parties, seq, fy, used_numbers,
                 detail=None):
    cat = items["items"]
    services = items["services"]
    exempt_pool = items["exempt_items"]
    ledgers = parties["ledgers"]

    side = rng.choice(_panel_choices(opts, "side", ["sale"]))
    buying = side == "purchase"
    detail = detail or {}
    doctype = rng.choice(_panel_choices(opts, "doctype", ["tax_invoice"]))
    supply = rng.choice(_panel_choices(opts, "supply", ["intra", "inter"]))
    content = rng.choice(_panel_choices(opts, "content", ["goods", "both"]))
    taxmode = rng.choice(_panel_choices(opts, "tax", ["rate18", "mix_12_18"]))

    # ---- party
    party_opts = _panel_choices(opts, "party", ["registered"])
    want_unreg = "unregistered" in party_opts and (
        "registered" not in party_opts or rng.random() < 0.35)
    # when we are buying, the other party is a supplier, not a customer
    base = parties["suppliers"] if buying else parties["buyers"]
    if want_unreg and supply == "intra" and not buying:
        buyer = dict(rng.choice(parties["unregistered_buyers"]))
    else:
        pool = [b for b in base
                if (b["state_code"] == "27") == (supply == "intra")]
        if not pool:  # e.g. inter-state asked but no out-of-state party
            pool = base
        buyer = dict(rng.choice(pool))

    interstate = buyer["state_code"] != parties["seller"]["state_code"]

    printed_name = buyer["name"]
    if "name_variant" in opts and buyer.get("ledger_alias") and rng.random() < 0.6:
        printed_name = buyer["ledger_alias"]

    # ---- how many lines, and of what
    fixed_goods = detail.get("goods_lines")
    fixed_serv = detail.get("service_lines")
    if "many_items" in opts:
        n = rng.randint(20, 40)
    elif doctype in ("credit_note", "debit_note"):
        n = rng.randint(1, 3)      # a note usually adjusts a line or two
    else:
        n = rng.randint(3, 8)

    # "rate_other" means ONE non-18% slab for the whole invoice, so the
    # rate is drawn here rather than per line
    single_rate = rng.choice([5, 12, 28]) if taxmode == "rate_other" else None

    def pick_goods():
        if taxmode == "rate18":
            pool = [i for i in cat if i["gst"] == 18]
        elif taxmode == "rate_other":
            pool = [i for i in cat if i["gst"] == single_rate] or \
                   [i for i in cat if i["gst"] == 12]
        elif taxmode == "mix_12_18":
            pool = [i for i in cat if i["gst"] in (12, 18)]
        elif taxmode == "cess":
            pool = [i for i in cat if i["gst"] == 28] or cat
        else:  # mix_all / exempt / rcm - draw from everything
            pool = cat
        return rng.choice(pool)

    lines = []
    godowns = parties["godowns"]
    big = "large_amount" in opts

    n_goods = 0 if content == "services" else n
    if content == "both":
        n_goods = max(2, int(n * 0.7))
    if fixed_goods and n_goods:
        n_goods = int(fixed_goods)

    for _ in range(n_goods):
        it = pick_goods()
        qty = rng.choice([1, 2, 4, 5, 6, 8, 10, 12, 20, 25, 50, 100])
        if big:
            qty *= rng.choice([5, 10, 20])
        mrp = Decimal(str(it["mrp"]))
        if "odd_paise" in opts and rng.random() < 0.7:
            mrp += Decimal(rng.choice(["0.37", "0.55", "0.13", "0.89", "0.61"]))
        desc = it["desc"]
        if "long_desc" in opts:
            desc += (" - Premium Grade ISI Marked, Manufactured as per "
                     "IS:3854 Specification, Supplied with Warranty Card "
                     "and Test Certificate")
        # a discount only appears when the user asks for one
        disc = (rng.choice([10, 15, 20, 25, 30, 40, 50])
                if (detail.get("discount") or "line_discount" in opts)
                else 0)
        cess_pct = 0
        if taxmode == "cess" and it["gst"] == 28:
            cess_pct = rng.choice([1, 3, 12])
        lines.append(Line(
            desc, it["hsn"], mrp, qty, it["uom"], it["gst"],
            discount_pct=disc, kind="goods", cess_pct=cess_pct,
            godown=rng.choice(godowns) if "godown" in opts else None,
            batch=(f"B{rng.randint(1000, 9999)}/{fy[:2]}"
                   if "batch" in opts else None),
        ))

    n_serv = 0
    if content == "services":
        n_serv = rng.randint(2, 5)
    elif content == "both":
        n_serv = max(1, n - n_goods)
    if fixed_serv and n_serv:
        n_serv = int(fixed_serv)
    for _ in range(n_serv):
        sv = rng.choice(services)
        mrp = Decimal(str(sv["mrp"]))
        if big:
            mrp *= rng.choice([3, 5, 8])
        lines.append(Line(sv["desc"], sv["sac"], mrp, rng.choice([1, 1, 1, 2]),
                          sv["uom"], sv["gst"], kind="service"))

    # nil-rated / exempt lines sit alongside taxable ones
    if "exempt" in opts and rng.random() < 0.8:
        ex = rng.choice(exempt_pool)
        lines.append(Line(ex["desc"], ex["hsn"], ex["mrp"],
                          rng.randint(1, 20), ex["uom"], 0,
                          kind="goods", exempt=True))

    if "mix_all" in opts:
        # guarantee all four slabs actually appear
        have = {int(l.gst) for l in lines}
        for want in (5, 12, 18, 28):
            if want in have:
                continue
            pool = [i for i in cat if i["gst"] == want]
            if pool:
                it = rng.choice(pool)
                lines.append(Line(it["desc"], it["hsn"], it["mrp"],
                                  rng.randint(1, 6), it["uom"], it["gst"]))
            elif want == 5:
                sv = [s for s in services if s["gst"] == 5]
                if sv:
                    s0 = sv[0]
                    lines.append(Line(s0["desc"], s0["sac"], s0["mrp"], 1,
                                      s0["uom"], 5, kind="service"))

    rng.shuffle(lines)

    # ---- other charges (Act V: each to its own ledger)
    charges = []
    ch_opts = [o for o in ("freight", "packing", "insurance", "loading")
               if o in opts]
    for o in ch_opts:
        if rng.random() < 0.75:
            amt = rng.choice([250, 450, 600, 850, 1200, 1800, 2500])
            charges.append(Charge(
                {"freight": "Freight Charges", "packing": "Packing Charges",
                 "insurance": "Insurance Charges",
                 "loading": "Loading & Unloading"}[o],
                amt, ledgers[o],
                code="996511" if o == "freight" else None,
                gst=18 if o == "freight" else 0))

    # ---- ledger split (goods vs services go to different ledgers)
    split = {}
    for l in lines:
        # what we buy is a purchase, what we sell is income
        if buying:
            key = ("Purchase - Electrical Goods" if l.kind == "goods"
                   else "Purchase - Services")
        else:
            key = ledgers["goods"] if l.kind == "goods"                 else ledgers["services"]
        split[key] = split.get(key, Decimal(0)) + l.taxable

    # ---- dates and numbering
    start = date(2026, 4, 1)
    d = start + timedelta(days=rng.randint(0, 330))
    series = {"tax_invoice": "PB" if buying else "SI",
              "credit_note": "CN", "debit_note": "DN",
              "purchase_order": "PO", "sales_order": "SO"}[doctype]
    if buying and doctype == "tax_invoice":
        # a bill we receive was numbered by the supplier, in their series
        num = (f"{rng.choice(['SEP', 'INV', 'GST', 'TI', 'BL'])}/"
               f"{fy}/{rng.randint(100, 4999)}")
    else:
        num = f"AE/{series}/{fy}/{26400 + seq}"
    while num in used_numbers:
        seq += 1
        num = (f"{rng.choice(['SEP', 'INV', 'GST'])}/{fy}/"
               f"{rng.randint(100, 4999)}"
               if buying and doctype == "tax_invoice"
               else f"AE/{series}/{fy}/{26400 + seq}")
    used_numbers.add(num)

    # A note must cite the invoice it adjusts, dated earlier than the note.
    orig = None
    if doctype in ("credit_note", "debit_note"):
        od = d - timedelta(days=rng.randint(5, 90))
        orig = {"number": f"AE/SI/{fy}/{26100 + rng.randint(1, 290)}",
                "date": od.strftime("%d %b %Y"), "date_iso": od.isoformat(),
                "reason": rng.choice(
                    ["Goods returned - damaged in transit",
                     "Rate difference as per revised quotation",
                     "Short supply against original invoice",
                     "Quality rejection - material returned"]
                    if doctype == "credit_note" else
                    ["Rate difference - price revision",
                     "Freight charged short in original invoice",
                     "Additional quantity supplied",
                     "Under-billing corrected"])}

    inv = {
        "number": num,
        "date": d.strftime("%d %b %Y"),
        "date_iso": d.isoformat(),
        "scenario": f"{supply}/{taxmode}/{content}",
        "tags": sorted(set(
            [doctype, supply, taxmode, content] + ch_opts +
            [o for o in ("rcm", "tds", "tcs", "billwise", "godown", "batch",
                         "eway", "irn", "exempt", "cess", "many_items",
                         "long_desc", "large_amount", "odd_paise",
                         "scanned",
                         "name_variant", "advance", "roundoff")
             if o in opts])),
        "interstate": interstate,
        "reverse_charge": "rcm" in opts and rng.random() < 0.5,
        # ask build() to land the pre-round total near half a rupee
        "force_roundoff": "roundoff" in opts,
        "scanned": "scanned" in opts,
        "scan_seed": rng.randint(1, 10**9),
        "place_of_supply": f"{buyer['state_code']}-{buyer['state']}",
        "doctype": doctype,
        "side": side,
        "doc_title": {"tax_invoice": ("PURCHASE INVOICE" if buying
                                      else "TAX INVOICE"),
                      "credit_note": "CREDIT NOTE",
                      "debit_note": "DEBIT NOTE",
                      "purchase_order": "PURCHASE ORDER",
                      "sales_order": "SALES ORDER"}[doctype],
        "voucher_type": {"tax_invoice": ("Purchase" if buying
                                         else "Sales"),
                         "credit_note": "Credit Note",
                         "debit_note": "Debit Note",
                         "purchase_order": "Purchase Order",
                         "sales_order": "Sales Order"}[doctype],
        # an order is a commitment, not an accounting entry
        "is_order": doctype in ("purchase_order", "sales_order"),
        "order_terms": ({
            "delivery_date": (d + timedelta(
                days=rng.choice([7, 10, 14, 21, 30]))).isoformat(),
            "payment_terms": rng.choice(
                ["30 days from date of invoice", "45 days credit",
                 "50% advance, balance against delivery",
                 "Against delivery", "15 days from receipt of material"]),
            "delivery_terms": rng.choice(
                ["Ex-works Pune", "FOR site", "Door delivery included",
                 "Freight prepaid"]),
        } if doctype in ("purchase_order", "sales_order") else None),
        "original_invoice": orig,
        "buyer": {
            "name": printed_name, "legal_name": buyer["name"],
            "gstin": buyer.get("gstin"), "state": buyer["state"],
            "bill": buyer["bill"], "ship": buyer["ship"],
            "phone": buyer.get("phone"),
        },
        "party_ledger": buyer["tally_ledger"],
        "ledger_split": split,
        "lines": lines,
        "charges": charges,
        "reference": (None if doctype in ("purchase_order", "sales_order")
                      else f"Challan# : AE/DC/{rng.randint(260000, 269999)}, "
                           f"Dt: {d.strftime('%d.%m.%Y')}"),
    }

    if "eway" in opts and rng.random() < 0.8:
        inv["eway_bill"] = str(rng.randint(10**11, 10**12 - 1))
    if "irn" in opts and rng.random() < 0.8:
        inv["irn"] = "".join(rng.choice("0123456789abcdef") for _ in range(64))
    if "advance" in opts and rng.random() < 0.6:
        inv["advance_adjusted"] = rng.choice([1000, 2500, 5000, 10000])
    if "billwise" in opts:
        inv["bill_wise"] = {
            "method": rng.choice(["New Ref", "Agst Ref"]),
            "reference": num,
            "due_date": (d + timedelta(days=rng.choice([15, 30, 45, 60]))
                         ).isoformat(),
            "credit_days": rng.choice([15, 30, 45, 60]),
        }
    return inv


def apply_layers(inv, t, rng, opts, parties):
    """TDS and TCS depend on the computed taxable value, so they are applied
    after the first pass and the invoice is then rebuilt."""
    changed = False
    if "tds" in opts and rng.random() < 0.7:
        sec = rng.choice(parties["tds_sections"])
        base = t["taxable"]
        if base >= sec["threshold"] or rng.random() < 0.5:
            inv["tds"] = {
                "section": sec["section"], "nature": sec["nature"],
                "rate": Decimal(str(sec["rate"])), "base": base,
                "amount": money(base * Decimal(str(sec["rate"])) / 100),
                "ledger": f"TDS Payable - {sec['section']}",
            }
            changed = True
    if "tcs" in opts and rng.random() < 0.6:
        inv["tcs_amount"] = money(t["gross"] * Decimal("0.1") / 100)
        changed = True
    return changed


def generate(opts, count=20, seed=None, start_at=1, detail=None, seen=None):
    """Yield `count` invoice dicts built from the ticked options.

    `start_at` offsets the numbering so successive batches into one folder
    keep unique invoice numbers.
    """
    opts = set(opts) & ALL_OPTS
    rng = random.Random(seed)
    items, parties = load_data()
    # Callers generating many small batches into one folder can pass a shared
    # set so numbers stay unique across calls, not just within one.
    used = seen if seen is not None else set()
    fy = "26-27"
    out = []
    for i in range(count):
        inv = make_invoice(rng, opts, items, parties, start_at + i, fy,
                           used, detail)
        out.append(inv)
    return out, parties["seller"]
