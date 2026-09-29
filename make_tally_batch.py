"""Twenty invoices whose every ledger exists in the user's Tally.

Items come from the 38 lines of Unique_HSN_Invoice, so each line's HSN and
GST rate are taken verbatim from that document. Parties are drawn only from
ledgers present in the Tally master, and the tax legs use the rate-specific
ledgers Tally actually carries:

    18%  ->  CGST 9%  + SGST 9%   |  IGST 18%
    12%  ->  CGST 6%  + SGST 6%   |  IGST 12%
    28%  ->  CGST 14% + SGST 14%  |  IGST 28%

An invoice mixing rates therefore posts one tax leg per rate, not one lump.
Seventeen invoices carry a single rate; three mix two or three of them.

The trade ledger follows the rate as well: an all-18% document posts to
Sales 18% / Purchase 18%, anything else to Sales - General /
Purchase - General, both of which exist in the master.
"""
import calendar
import json
import os
import random
import shutil
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal

from invoicegen import scenarios as _scen
from invoicegen.generate import run
from invoicegen.model import Line, half_tax, money

DESK = os.path.join(os.path.expanduser("~"), "Desktop", "GST_Invoices")

# A second run into a new folder needs its own seeds and numbering, or it
# would reproduce the first batch invoice for invoice.
BATCH = int(os.environ.get("BATCH", "1"))
SEED0 = 5500 + (BATCH - 1) * 1000
FIRST = 1 + (BATCH - 1) * 100

# Set MONTH to "YYYY-MM" to land every invoice in that one month; left
# unset, dates fall anywhere in the financial year as before.
MONTH = os.environ.get("MONTH")

OUT = os.path.join(DESK, "Tally_Invoices" if BATCH == 1
                   else f"Tally_Invoices_{BATCH}")
SRC = os.path.join(DESK, "Unique_HSN_Invoice", "json",
                   "Invoice_001_Goods_Mixed_12_18_28.json")

COUNT = 20
MIXED = 3                  # how many carry more than one GST rate
LINES = 7
QTYS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 50]
DISCOUNTS = [5, 10, 12.5, 15, 20, 25, 30]

# Party ledgers that exist in Tally and carry a GSTIN.
TALLY_PARTIES = {
    "Balaji Traders", "Deshmukh Electricals", "Gujarat Electro Traders",
    "Himalaya Electricals", "Hind Power Systems", "Krishna Electric Store",
    "Lakshmi Copper Products", "Meghdoot Cables and Wires",
    "Narayan Power Systems", "Rajmudra Builders and Developers",
    "Sanghvi Electricals Pvt Ltd", "Shree Samarth Electricals",
    "Sundar Traders", "Tejas Switchgear Company",
    "Thiru Murugan Electricals", "Trimurti Switchgear Industries",
}

# GST rate -> the half-rate Tally names its CGST/SGST ledgers by.
HALF = {12: "6%", 18: "9%", 28: "14%"}


def load_pool():
    with open(SRC, encoding="utf-8") as f:
        d = json.load(f)
    return [{"desc": l["description"], "hsn": l["hsn_sac"],
             "rate": Decimal(str(l["rate"])), "uom": l["uom"],
             "gst": l["gst_rate"]} for l in d["lines"]]


def tally_parties():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "invoicegen", "data", "parties.json"),
              encoding="utf-8") as f:
        d = json.load(f)
    return {g: [b for b in d[g] if b["tally_ledger"] in TALLY_PARTIES
                and b.get("gstin")]
            for g in ("buyers", "suppliers")}


def retax_voucher(rec, buying):
    """Rewrite the voucher's tax legs to Tally's rate-specific ledgers.

    The model posts one lump per tax head. Tally keeps a ledger per rate, so
    the lump is split back out over the rates the invoice actually carries -
    a 12%-and-18% invoice posts to both CGST 6% and CGST 9%.
    """
    v = rec["expected_voucher"]
    side = "Input" if buying else "Output"
    inter = rec["supply_type"] == "inter-state"

    # tax per rate, from the lines themselves
    per_rate = defaultdict(Decimal)
    for l in rec["lines"]:
        per_rate[int(l["gst_rate"])] += Decimal(str(l["tax_amount"]))
    for c in rec["other_charges"]:
        if c["gst_rate"]:
            per_rate[int(c["gst_rate"])] += Decimal(str(c["tax_amount"]))

    keep = [e for e in v["entries"]
            if not any(h in e["ledger"] for h in ("CGST", "SGST", "IGST"))]
    legs = []
    for rate in sorted(per_rate):
        tax = money(per_rate[rate])
        if not tax:
            continue
        if inter:
            legs.append((f"{side} IGST {rate}%", tax))
        else:
            h = half_tax(tax)
            legs.append((f"{side} CGST {HALF[rate]}", h))
            legs.append((f"{side} SGST {HALF[rate]}", h))

    # tax follows the trade side: debited on a purchase, credited on a sale
    for ledger, amt in legs:
        keep.append({"ledger": ledger,
                     "dr": float(amt) if buying else 0.0,
                     "cr": 0.0 if buying else float(amt)})

    keep.sort(key=lambda e: e["ledger"])
    dr = round(sum(e["dr"] for e in keep), 2)
    cr = round(sum(e["cr"] for e in keep), 2)
    v["entries"] = keep
    v["total_dr"], v["total_cr"] = dr, cr
    v["balanced"] = abs(dr - cr) < 0.005
    return v


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    pool = load_pool()
    parties = tally_parties()

    by_rate = defaultdict(list)
    for it in pool:
        by_rate[int(it["gst"])].append(it)

    orig_make = _scen.make_invoice
    state = {"n": 0}

    def make_invoice(rng, opts, items, ps, seq, fy, used, detail=None):
        inv = orig_make(rng, opts, items, ps, seq, fy, used, detail)
        n = state["n"]
        buying = inv.get("side") == "purchase"

        p = random.Random(3300 + SEED0 + n).choice(
            parties["suppliers" if buying else "buyers"])
        inv["buyer"] = {
            "name": p["name"], "legal_name": p["name"], "gstin": p["gstin"],
            "state": p["state"], "bill": p["bill"], "ship": p["ship"],
            "phone": p.get("phone"),
        }
        inv["party_ledger"] = p["tally_ledger"]
        inv["place_of_supply"] = f"{p['state_code']}-{p['state']}"
        inv["interstate"] = p["state_code"] != "27"

        r = random.Random(9900 + SEED0 + n)
        # The last MIXED invoices carry several rates; the rest keep to one
        # so they post to a single pair of tax ledgers.
        if n >= COUNT - MIXED:
            rates = r.choice([[12, 18], [18, 28], [12, 18, 28]])
            pick = []
            for i in range(LINES):
                pick.append(r.choice(by_rate[rates[i % len(rates)]]))
        else:
            rate = [18, 18, 18, 12, 28][n % 5]
            pick = [r.choice(by_rate[rate]) for _ in range(LINES)]

        seen_desc, lines = set(), []
        for it in pick:
            if it["desc"] in seen_desc:          # keep the lines distinct
                alt = [x for x in by_rate[int(it["gst"])]
                       if x["desc"] not in seen_desc]
                if alt:
                    it = r.choice(alt)
            seen_desc.add(it["desc"])
            lines.append(Line(it["desc"], it["hsn"], it["rate"],
                              r.choice(QTYS), it["uom"], it["gst"],
                              discount_pct=r.choice(DISCOUNTS),
                              kind="goods"))
        inv["lines"] = lines

        # Tally names the trade ledger by rate, so an all-18% invoice posts
        # to Sales/Purchase 18% and anything else to the General ledger.
        rates_on = {int(l.gst) for l in lines}
        if rates_on == {18}:
            key = "Purchase 18%" if buying else "Sales 18%"
        else:
            key = "Purchase - General" if buying else "Sales - General"
        inv["ledger_split"] = {key: sum(l.taxable for l in lines)}
        inv["charges"] = []
        inv["cash_discount"] = float(money(
            sum(l.taxable for l in lines)
            * Decimal(str(r.choice([1, 1.5, 2, 2.5]))) / 100))

        # Pin the date into one month when asked, spreading the batch over
        # its days rather than stacking every invoice on the same date.
        if MONTH:
            y, mo = (int(x) for x in MONTH.split("-"))
            last = calendar.monthrange(y, mo)[1]
            day = 1 + (n * max(1, last // COUNT) + r.randint(0, 1)) % last
            d = date(y, mo, day)
            inv["date"] = d.strftime("%d %b %Y")
            inv["date_iso"] = d.isoformat()
            ref = inv.get("reference")
            if ref and ", Dt: " in ref:
                inv["reference"] = (ref.split(", Dt: ")[0] + ", Dt: "
                                    + d.strftime("%d.%m.%Y"))
        return inv

    _scen.make_invoice = make_invoice
    sys.modules["invoicegen.scenarios"].make_invoice = make_invoice

    seen = set()
    rows = []
    for i in range(COUNT):
        state["n"] = i
        side = "purchase" if i % 2 else "sale"
        rows += run([side, "tax_invoice", "registered", "goods",
                     "line_discount"],
                    count=1, seed=SEED0 + i, outdir=OUT, write_json=True,
                    start_at=FIRST + i, seen=seen,
                    detail={"discount": True, "always": True},
                    patterns=("classic",))

    # Rewrite each voucher's tax legs onto Tally's per-rate ledgers, and
    # rename the discount leg to the ledger the master actually carries.
    for f in sorted(os.listdir(os.path.join(OUT, "json"))):
        p = os.path.join(OUT, "json", f)
        rec = json.load(open(p, encoding="utf-8"))
        buying = rec["document_type"] == "PURCHASE INVOICE"
        for e in rec["expected_voucher"]["entries"]:
            if e["ledger"] == "Discount Received":
                e["ledger"] = "Discount"
        retax_voucher(rec, buying)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)

    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    pur = sum(1 for r in rows if r["file"].startswith("Purchase"))
    print(f"invoices : {len(rows)} ({pur} purchase, {len(rows) - pur} sales)")
    print(f"mixed    : {MIXED}   single-rate: {COUNT - MIXED}")
    print(f"\ndone: {OUT}")
    return rows


if __name__ == "__main__":
    main()
