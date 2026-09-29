"""Twenty invoices - purchase and sales - drawn from one fixed item pool.

The pool is the 38 line items of Unique_HSN_Invoice, one per HSN/rate pair,
so every line here carries an HSN and a GST rate taken verbatim from that
document. Nothing is invented: an item's rate always travels with its HSN,
including 85044090, which is 12% for the solar inverter and 18% for the
ordinary one.

Each invoice: 7 goods lines, a trade discount on the lines (before GST) and
a cash discount off the total (after GST). Purchase and sales sit together
in one folder, as asked.
"""
import json
import os
import random
import shutil
import sys
from decimal import Decimal

from invoicegen import scenarios as _scen
from invoicegen.generate import run
from invoicegen.model import Line

OUT = os.path.join(os.path.expanduser("~"), "Desktop", "HSN_Pool_Invoices")
SRC = os.path.join(os.path.expanduser("~"), "Desktop", "Unique_HSN_Invoice",
                   "json", "Invoice_001_Goods_Mixed_12_18_28.json")

# Only ledgers that exist in the user's Tally, or the voucher cannot post.
# Registered parties only - the two Tally ledgers without a GSTIN (Ramesh
# Kulkarni, Anil Jadhav) and the two with no master data (Sadanand
# Electricals, Shree Balaji Traders) are left out.
TALLY_LEDGERS = {
    "Balaji Traders", "Deshmukh Electricals", "Gujarat Electro Traders",
    "Himalaya Electricals", "Hind Power Systems", "Krishna Electric Store",
    "Lakshmi Copper Products", "Rajmudra Builders and Developers",
    "Sanghvi Electricals Pvt Ltd", "Shree Samarth Electricals",
    "Sundar Traders", "Tejas Switchgear Company",
    "Thiru Murugan Electricals", "Trimurti Switchgear Industries",
}

COUNT = 20
LINES_PER_INVOICE = 7
QTYS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 50, 100]
DISCOUNTS = [5, 10, 12.5, 15, 20, 25, 30, 40]


def load_pool():
    """The source invoice's lines, as the pool every invoice draws from."""
    with open(SRC, encoding="utf-8") as f:
        d = json.load(f)
    return [{"desc": l["description"], "hsn": l["hsn_sac"],
             "rate": Decimal(str(l["rate"])), "uom": l["uom"],
             "gst": l["gst_rate"]} for l in d["lines"]]


def tally_parties():
    """The Tally-backed parties, split by the side they trade on."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "invoicegen", "data", "parties.json"),
              encoding="utf-8") as f:
        d = json.load(f)
    out = {}
    for grp in ("buyers", "suppliers"):
        out[grp] = [b for b in d[grp]
                    if b["tally_ledger"] in TALLY_LEDGERS and b.get("gstin")]
    return out


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    pool = load_pool()
    parties_ok = tally_parties()

    orig_make = _scen.make_invoice
    state = {"n": 0}

    def make_invoice(rng, opts, items, parties, seq, fy, used, detail=None):
        inv = orig_make(rng, opts, items, parties, seq, fy, used, detail)

        # Replace the party with one that actually exists in Tally. The
        # supply type follows the party's own state rather than the other
        # way round, so an out-of-state ledger always yields IGST.
        buying = inv.get("side") == "purchase"
        pool_p = parties_ok["suppliers" if buying else "buyers"]
        p = random.Random(3300 + state["n"]).choice(pool_p)
        inv["buyer"] = {
            "name": p["name"], "legal_name": p["name"],
            "gstin": p["gstin"], "state": p["state"],
            "bill": p["bill"], "ship": p["ship"], "phone": p.get("phone"),
        }
        inv["party_ledger"] = p["tally_ledger"]
        inv["place_of_supply"] = f"{p['state_code']}-{p['state']}"
        inv["interstate"] = p["state_code"] != "27"

        # Seven distinct items from the pool. The rate and HSN travel
        # together, so a line can never show a rate its code does not carry.
        pick = random.Random(4400 + state["n"]).sample(pool,
                                                       LINES_PER_INVOICE)
        r = random.Random(9900 + state["n"])
        fresh = [Line(it["desc"], it["hsn"], it["rate"], r.choice(QTYS),
                      it["uom"], it["gst"],
                      discount_pct=r.choice(DISCOUNTS), kind="goods")
                 for it in pick]
        inv["lines"] = fresh
        buying = inv.get("side") == "purchase"
        key = ("Purchase - Electrical Goods" if buying
               else parties["ledgers"]["goods"])
        inv["ledger_split"] = {key: sum(l.taxable for l in fresh)}
        inv["charges"] = []
        # A cash discount is settlement terms: tax is charged on the full
        # value and the discount comes off afterwards.
        inv["cash_discount"] = float(_scen.money(
            sum(l.taxable for l in fresh)
            * Decimal(str(r.choice([1, 1.5, 2, 2.5]))) / 100))
        return inv

    _scen.make_invoice = make_invoice
    sys.modules["invoicegen.scenarios"].make_invoice = make_invoice

    seen = set()
    rows = []
    for i in range(COUNT):
        state["n"] = i
        # alternate the two sides through the batch
        side = "purchase" if i % 2 else "sale"
        # No intra/inter tick: the party's own state decides the supply
        # type, so a Gujarat or Delhi ledger correctly yields IGST.
        rows += run([side, "tax_invoice", "registered", "goods",
                     "line_discount"],
                    count=1, seed=5500 + i, outdir=OUT, write_json=True,
                    start_at=i + 1, seen=seen,
                    detail={"discount": True, "always": True},
                    patterns=("classic",))

    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    pur = sum(1 for r in rows if r["file"].startswith("Purchase"))
    print(f"pool items      : {len(pool)}")
    print(f"invoices        : {len(rows)}  "
          f"({pur} purchase, {len(rows) - pur} sales)")
    print(f"lines each      : {LINES_PER_INVOICE}")
    print(f"\ndone: {OUT}")
    return rows


if __name__ == "__main__":
    main()
