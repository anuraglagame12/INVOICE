"""One sales and one purchase invoice carrying the entire item catalogue.

Every one of the 97 goods in items.json appears as its own line, so between
them the two documents exercise all 37 distinct HSN codes and every GST slab
the catalogue uses. Useful as a single worst-case document for testing HSN
extraction and the HSN-wise tax summary.

Classic layout, registered party on both sides, intra-state so the summary
shows the CGST/SGST split. No RCM, TDS, TCS or discounts - the point of the
document is HSN coverage, not the tax layers, which the typed batch covers.
"""
import json
import os
from collections import Counter
from datetime import date
from decimal import Decimal

from invoicegen.generate import run
from invoicegen import scenarios as _scen
from invoicegen.model import Line

OUT = os.path.join(os.path.expanduser("~"), "Desktop", "All_HSN_Invoices")

# A steady quantity per line: the document is already 97 lines long, so the
# quantities stay small and plausible rather than inflating the total.
QTYS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25]


def all_goods_lines():
    """One Line per catalogue item, in HSN order so the page reads sensibly."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "invoicegen", "data", "items.json"),
              encoding="utf-8") as f:
        items = json.load(f)["items"]
    items = sorted(items, key=lambda i: (i["hsn"], i["desc"]))
    return [
        Line(it["desc"], it["hsn"], Decimal(str(it["mrp"])),
             QTYS[n % len(QTYS)], it["uom"], it["gst"], kind="goods")
        for n, it in enumerate(items)
    ], items


def main():
    os.makedirs(OUT, exist_ok=True)
    lines, items = all_goods_lines()

    # Swap the generated lines for the full catalogue. Everything else -
    # party, numbering, ledgers, dates - comes from the normal path.
    orig_make = _scen.make_invoice

    def make_invoice(rng, opts, its, parties, seq, fy, used, detail=None):
        inv = orig_make(rng, opts, its, parties, seq, fy, used, detail)
        fresh, _ = all_goods_lines()
        inv["lines"] = fresh
        # the ledger split mirrors the lines, so it has to be rebuilt
        buying = inv.get("side") == "purchase"
        key = ("Purchase - Electrical Goods" if buying
               else parties["ledgers"]["goods"])
        inv["ledger_split"] = {key: sum(l.taxable for l in fresh)}
        inv["charges"] = []
        return inv

    _scen.make_invoice = make_invoice

    seen = set()
    rows = []
    for i, side in enumerate(("sale", "purchase"), 1):
        rows += run([side, "tax_invoice", "registered", "intra", "goods"],
                    count=1, seed=9100 + i, outdir=OUT, write_json=True,
                    start_at=i, seen=seen, patterns=("classic",))

    hsn = Counter(it["hsn"] for it in items)
    print(f"items on each invoice : {len(items)}")
    print(f"distinct HSN codes    : {len(hsn)}")
    print(f"GST slabs             : "
          f"{sorted({it['gst'] for it in items})}")
    for r in rows:
        print(f"  {r['file']}: {r['line_count']} lines, "
              f"taxable {r['taxable']:,.2f}, total {r['total']:,.2f}")
    print(f"\ndone: {len(rows)} invoices in {OUT}")
    return rows


if __name__ == "__main__":
    main()
