"""One invoice carrying every distinct HSN code exactly once.

Each of the 37 HSN codes in the catalogue appears as a single line at its own
GST rate, so the document shows the full spread of codes and slabs without
repeating any. HSN 85044090 carries two rates in the catalogue - 12% for the
solar inverter, 18% for ordinary inverters and UPS - so it contributes one
line per rate; every other code has a single rate and a single line.

The result is one line per (HSN, rate) pair: 38 lines over 37 codes.
"""
import json
import os
from collections import defaultdict
from decimal import Decimal

from invoicegen.generate import run
from invoicegen import scenarios as _scen
from invoicegen.model import Line

OUT = os.path.join(os.path.expanduser("~"), "Desktop", "Unique_HSN_Invoice")

QTYS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25]


def unique_hsn_lines():
    """One line per (HSN, rate), the cheapest item standing for each."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "invoicegen", "data", "items.json"),
              encoding="utf-8") as f:
        items = json.load(f)["items"]

    groups = defaultdict(list)
    for it in items:
        groups[(it["hsn"], it["gst"])].append(it)

    lines = []
    for n, key in enumerate(sorted(groups)):
        # a representative item for the code: the first by name, so the
        # choice is stable run to run rather than random
        it = sorted(groups[key], key=lambda i: i["desc"])[0]
        lines.append(Line(it["desc"], it["hsn"], Decimal(str(it["mrp"])),
                          QTYS[n % len(QTYS)], it["uom"], it["gst"],
                          kind="goods"))
    return lines


def main():
    os.makedirs(OUT, exist_ok=True)

    orig_make = _scen.make_invoice

    def make_invoice(rng, opts, its, parties, seq, fy, used, detail=None):
        inv = orig_make(rng, opts, its, parties, seq, fy, used, detail)
        fresh = unique_hsn_lines()
        inv["lines"] = fresh
        inv["ledger_split"] = {
            parties["ledgers"]["goods"]: sum(l.taxable for l in fresh)}
        inv["charges"] = []
        return inv

    _scen.make_invoice = make_invoice

    rows = run(["sale", "tax_invoice", "registered", "intra", "goods"],
               count=1, seed=7301, outdir=OUT, write_json=True,
               start_at=1, patterns=("classic",))

    lines = unique_hsn_lines()
    codes = {l.code for l in lines}
    print(f"lines           : {len(lines)}")
    print(f"distinct HSN    : {len(codes)}")
    print(f"GST rates       : {sorted({int(l.gst) for l in lines})}")
    for r in rows:
        print(f"  {r['file']}: taxable {r['taxable']:,.2f}, "
              f"total {r['total']:,.2f}")
    print(f"\ndone: {OUT}")
    return rows


if __name__ == "__main__":
    main()
