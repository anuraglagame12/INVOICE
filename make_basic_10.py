"""Ten plain invoices - five purchase, five sales.

Basic means no discounts, no other charges, no round-off and no services:
goods, GST, total. Items come from the all-HSN invoice, so each line's HSN and rate are taken
verbatim from that document, and the parties are ledgers that exist in the
user's Tally.
"""
import json
import os
import random
import shutil
import sys
from decimal import Decimal

from invoicegen import scenarios as _scen
from invoicegen.generate import run
from invoicegen.model import Line, half_tax, money

DESK = os.path.join(os.path.expanduser("~"), "Desktop")
OUT = os.path.join(DESK, "Basic_Invoices")
SRC = os.path.join(DESK, "YP", "All_HSN_Invoices", "json",
                   "Invoice_001_Goods_Mixed_12_18_28.json")

COUNT = 10
# Tally keeps a tax ledger per rate, so the model's single lump per head has
# to be split back out over the rates the invoice carries.
HALF = {12: "6%", 18: "9%", 28: "14%"}
LINES = 6
QTYS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25]

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


def retax(rec, buying):
    """Point the voucher's tax legs at Tally's rate-specific ledgers."""
    v = rec["expected_voucher"]
    side = "Input" if buying else "Output"
    inter = rec["supply_type"] == "inter-state"
    per_rate = {}
    for l in rec["lines"]:
        r = int(l["gst_rate"])
        per_rate[r] = per_rate.get(r, Decimal(0)) + Decimal(str(l["tax_amount"]))

    keep = [e for e in v["entries"]
            if not any(h in e["ledger"] for h in ("CGST", "SGST", "IGST"))]
    for rate in sorted(per_rate):
        tax = money(per_rate[rate])
        if not tax:
            continue
        legs = ([(f"{side} IGST {rate}%", tax)] if inter
                else [(f"{side} CGST {HALF[rate]}", half_tax(tax)),
                      (f"{side} SGST {HALF[rate]}", half_tax(tax))])
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


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    pool = load_pool()
    parties = tally_parties()
    by_rate = {}
    for it in pool:
        by_rate.setdefault(int(it["gst"]), []).append(it)

    orig_make = _scen.make_invoice
    state = {"n": 0}

    def make_invoice(rng, opts, items, ps, seq, fy, used, detail=None):
        inv = orig_make(rng, opts, items, ps, seq, fy, used, detail)
        n = state["n"]
        buying = inv.get("side") == "purchase"
        r = random.Random(2200 + n)

        p = r.choice(parties["suppliers" if buying else "buyers"])
        inv["buyer"] = {
            "name": p["name"], "legal_name": p["name"], "gstin": p["gstin"],
            "state": p["state"], "bill": p["bill"], "ship": p["ship"],
            "phone": p.get("phone"),
        }
        inv["party_ledger"] = p["tally_ledger"]
        inv["place_of_supply"] = f"{p['state_code']}-{p['state']}"
        inv["interstate"] = p["state_code"] != "27"

        # One rate per invoice keeps it basic and posts to a single pair of
        # tax ledgers; no discount is applied to any line.
        rate = [18, 18, 18, 12, 28][n % 5]
        seen_d, lines = set(), []
        for _ in range(LINES):
            choices = [x for x in by_rate[rate] if x["desc"] not in seen_d]
            it = r.choice(choices or by_rate[rate])
            seen_d.add(it["desc"])
            lines.append(Line(it["desc"], it["hsn"], it["rate"],
                              r.choice(QTYS), it["uom"], it["gst"],
                              kind="goods"))
        inv["lines"] = lines
        key = ("Purchase 18%" if rate == 18 else "Purchase - General") \
            if buying else ("Sales 18%" if rate == 18 else "Sales - General")
        inv["ledger_split"] = {key: sum(l.taxable for l in lines)}
        inv["charges"] = []
        inv.pop("cash_discount", None)
        return inv

    _scen.make_invoice = make_invoice
    sys.modules["invoicegen.scenarios"].make_invoice = make_invoice

    seen, rows = set(), []
    for i in range(COUNT):
        state["n"] = i
        side = "purchase" if i % 2 else "sale"
        rows += run([side, "tax_invoice", "registered", "goods"],
                    count=1, seed=7700 + i, outdir=OUT, write_json=True,
                    start_at=i + 1, seen=seen, patterns=("classic",))

    for f in sorted(os.listdir(os.path.join(OUT, "json"))):
        fp = os.path.join(OUT, "json", f)
        rec = json.load(open(fp, encoding="utf-8"))
        retax(rec, rec["document_type"] == "PURCHASE INVOICE")
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)

    pur = sum(1 for r in rows if r["file"].startswith("Purchase"))
    print(f"invoices : {len(rows)} ({pur} purchase, {len(rows) - pur} sales)")
    print(f"lines    : {LINES} goods each, no discount/charge/round-off")
    print(f"\ndone: {OUT}")
    return rows


if __name__ == "__main__":
    main()
