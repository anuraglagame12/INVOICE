"""One purchase invoice: 3 goods, all 18% GST, no line discount,
cash discount taken at the foot of the bill."""
import json
import os
from decimal import Decimal

from invoicegen.model import Charge, Line, money
from invoicegen.render_invoice import render_document
from invoicegen.scenarios import load_data
from invoicegen.transactions import Txn
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "single_pi")
CASH_DISC_PCT = Decimal("2")


def main():
    items, parties = load_data()
    with open(os.path.join(HERE, "invoicegen", "data", "ledgers.json"),
              encoding="utf-8") as f:
        led = json.load(f)
    seller = parties["seller"]
    supplier = dict(parties["suppliers"][0])

    goods = [i for i in items["items"] if i["gst"] == 18][:3]
    t = Txn("purchase_invoice", "purchase_invoice", "PURCHASE INVOICE",
            "AE/PB/26-27/2701", date(2026, 6, 18), supplier)
    # no discount_pct -> nothing in the line-level discount column
    t.lines = [Line(g["desc"], g["hsn"], g["mrp"], q, g["uom"], g["gst"])
               for g, q in zip(goods, (10, 6, 12))]
    t.charges = []

    taxable = money(sum(l.taxable for l in t.lines))
    tax = money(sum(l.tax for l in t.lines))
    cash_disc = money(taxable * CASH_DISC_PCT / 100)
    gross = money(taxable + tax - cash_disc)
    total = Decimal(int(gross.to_integral_value()))
    t.meta.update({
        "taxable": taxable, "charges": Decimal(0), "tax": tax,
        "cash_discount": cash_disc,
        "cash_discount_pct": float(CASH_DISC_PCT),
        "round_off": money(total - gross), "total": total,
        "rcm": False, "zero_rated": False,
        "tds_amount": Decimal(0), "tcs": Decimal(0),
        "advance": Decimal(0), "customs_duty": Decimal(0),
        "supplier_invoice": "SND/2026/0418",
    })

    # posting: purchase and input tax are debits, supplier is credited,
    # the cash discount is income and so a credit
    tr, tx, disc = led["trading"], led["tax"], led["discounts"]
    t.dr(tr["purchase_goods"], taxable)
    half = money(tax / 2)
    t.dr(tx["input_cgst"], half)
    t.dr(tx["input_sgst"], money(tax - half))
    t.cr(disc["cash_received"], cash_disc)
    t.cr(supplier["tally_ledger"], total)
    gap = money(t.total_dr - t.total_cr)
    if gap:
        t.legs.append({"ledger": led["charges"]["round_off"],
                       "dr": float(max(-gap, Decimal(0))),
                       "cr": float(max(gap, Decimal(0)))})
    t.narration = f"Being goods purchased vide {t.number}"

    os.makedirs(OUT, exist_ok=True)
    pdf = os.path.join(OUT, "Purchase Invoice - 3 Goods.pdf")
    render_document(t, seller, pdf)

    rec = {
        "number": t.number, "date": t.date.isoformat(),
        "document_type": t.title, "supplier": supplier["name"],
        "supplier_gstin": supplier["gstin"],
        "lines": [{"description": l.desc, "hsn": l.code, "qty": float(l.qty),
                   "uom": l.uom, "rate": float(l.rate),
                   "line_discount": float(l.discount_pct or 0),
                   "taxable_value": float(l.taxable),
                   "gst_rate": float(l.gst), "tax": float(l.tax)}
                  for l in t.lines],
        "taxable": float(taxable), "gst": float(tax),
        "cash_discount_pct": float(CASH_DISC_PCT),
        "cash_discount": float(cash_disc),
        "round_off": float(t.meta["round_off"]), "total": float(total),
        "voucher": {"entries": t.legs, "total_dr": float(t.total_dr),
                    "total_cr": float(t.total_cr),
                    "balanced": t.balanced, "narration": t.narration},
    }
    with open(os.path.join(OUT, "Purchase Invoice - 3 Goods.json"), "w",
              encoding="utf-8") as f:
        json.dump(rec, f, indent=2)

    print(f"taxable   {taxable:>12,.2f}")
    print(f"GST 18%   {tax:>12,.2f}")
    print(f"cash disc {-cash_disc:>12,.2f}  ({CASH_DISC_PCT}%)")
    print(f"round off {t.meta['round_off']:>12,.2f}")
    print(f"TOTAL     {total:>12,.2f}")
    print(f"balanced: {t.balanced}   Dr {t.total_dr}  Cr {t.total_cr}")
    print("->", pdf)


if __name__ == "__main__":
    main()
