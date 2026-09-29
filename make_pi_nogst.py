"""One purchase invoice: 3 goods, no GST at all.

The supplier is a composition dealer, who by law cannot collect tax, so the
document is a Bill of Supply - no tax column, no tax summary, no CGST/SGST
rows in the totals. The posting is correspondingly plain: the whole value
goes to purchases, with no input tax to claim.
"""
import json
import os
from decimal import Decimal

from invoicegen.model import Line, money
from invoicegen.render_invoice import render_document
from invoicegen.scenarios import load_data
from invoicegen.transactions import Txn
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "single_pi")


def main():
    items, parties = load_data()
    with open(os.path.join(HERE, "invoicegen", "data", "ledgers.json"),
              encoding="utf-8") as f:
        led = json.load(f)
    seller = parties["seller"]
    supplier = dict(parties["composition_dealers"][0])

    goods = items["items"][:3]
    t = Txn("purchase_invoice", "purchase_invoice", "BILL OF SUPPLY",
            "AE/PB/26-27/2702", date(2026, 6, 18), supplier)
    # gst=0 on every line: no tax is charged, so none is shown
    t.lines = [Line(g["desc"], g["hsn"], g["mrp"], q, g["uom"], 0)
               for g, q in zip(goods, (10, 6, 12))]
    t.charges = []

    taxable = money(sum(l.taxable for l in t.lines))
    total = Decimal(int(taxable.to_integral_value()))
    t.meta.update({
        "taxable": taxable, "charges": Decimal(0), "tax": Decimal(0),
        "no_tax": True,
        "round_off": money(total - taxable), "total": total,
        "rcm": False, "zero_rated": False,
        "tds_amount": Decimal(0), "tcs": Decimal(0),
        "advance": Decimal(0), "customs_duty": Decimal(0),
        "supplier_invoice": "SHS/2026/0119",
    })

    # no input tax to split out - purchases are debited with the full value
    # and the supplier is credited the same, so the entry is a simple pair
    t.dr(led["trading"]["purchase_goods"], taxable)
    t.cr(supplier["tally_ledger"], total)
    gap = money(t.total_dr - t.total_cr)
    if gap:
        t.legs.append({"ledger": led["charges"]["round_off"],
                       "dr": float(max(-gap, Decimal(0))),
                       "cr": float(max(gap, Decimal(0)))})
    t.narration = f"Being goods purchased vide {t.number}"

    os.makedirs(OUT, exist_ok=True)
    pdf = os.path.join(OUT, "Purchase Invoice - 3 Goods No GST.pdf")
    render_document(t, seller, pdf)

    rec = {
        "number": t.number, "date": t.date.isoformat(),
        "document_type": t.title, "supplier": supplier["name"],
        "supplier_gstin": supplier["gstin"],
        "lines": [{"description": l.desc, "hsn": l.code, "qty": float(l.qty),
                   "uom": l.uom, "rate": float(l.rate),
                   "taxable_value": float(l.taxable),
                   "gst_rate": 0, "tax": 0}
                  for l in t.lines],
        "taxable": float(taxable), "gst": 0,
        "round_off": float(t.meta["round_off"]), "total": float(total),
        "voucher": {"entries": t.legs, "total_dr": float(t.total_dr),
                    "total_cr": float(t.total_cr),
                    "balanced": t.balanced, "narration": t.narration},
    }
    with open(os.path.join(OUT, "Purchase Invoice - 3 Goods No GST.json"),
              "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2)

    for l in t.lines:
        print(f"{l.desc[:34]:<34} {l.qty:>5g} x {l.rate:>9,.2f} "
              f"= {l.taxable:>12,.2f}")
    print(f"{'taxable':<34} {taxable:>32,.2f}")
    print(f"{'GST':<34} {'nil (composition supplier)':>32}")
    print(f"{'round off':<34} {t.meta['round_off']:>32,.2f}")
    print(f"{'TOTAL':<34} {total:>32,.2f}")
    print(f"balanced: {t.balanced}   Dr {t.total_dr}  Cr {t.total_cr}")
    print("->", pdf)


if __name__ == "__main__":
    main()
