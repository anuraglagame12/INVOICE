"""Purchase and sales invoices, one folder per feature, Classic layout.

Nine types per side, fifteen invoices each - 270 documents.

    01_cgst_sgst      intra-state, CGST + SGST
    02_igst           inter-state, IGST
    03_service        goods plus exactly ONE service line
    04_other_charge   goods plus exactly ONE charge
    05_trade_discount discount on the lines, before GST
    06_cash_discount  discount off the total, after GST
    07_round_off      total rounded to the rupee
    08_unregistered   purchase -> BILL OF SUPPLY (no GST can be charged)
                      sale     -> TAX INVOICE (we are registered, so we do)
    09_combined       every feature above, registered parties only

Every invoice carries 7-8 goods lines. A service line and a charge are
capped at one apiece. Charges are Packing, Insurance or Loading - never
Freight, never Miscellaneous. No RCM, TDS, TCS or long descriptions.

Our firm is Abhidnya Enterprises throughout: on a sale it heads the page,
on a purchase the supplier does and we are the buyer.
"""
import json
import os
import shutil
import sys
from decimal import Decimal

from invoicegen import scenarios as _scen
from invoicegen.generate import run

OUT = os.path.join(os.path.expanduser("~"), "Desktop", "GST_Batch_270")

PER_TYPE = 15
GOODS_LINES = (7, 8)       # every invoice carries this many goods lines

# Freight and Miscellaneous are excluded by request.
CHARGE_OPTS = ["packing", "insurance", "loading"]

# id, folder, extra options, detail overrides
TYPES = [
    ("cgst_sgst", "01_cgst_sgst", ["intra", "goods", "rate18"], {}),
    ("igst", "02_igst", ["inter", "goods", "rate18"], {}),
    ("service", "03_service", ["intra", "both", "rate18"],
     {"service_lines": 1, "always": True}),
    ("other_charge", "04_other_charge",
     ["intra", "goods", "rate18"] + CHARGE_OPTS,
     {"single_charge": True, "always": True}),
    ("trade_discount", "05_trade_discount",
     ["intra", "goods", "rate18", "line_discount"],
     {"discount": True, "always": True}),
    ("cash_discount", "06_cash_discount", ["intra", "goods", "rate18"],
     {"cash_discount": True, "always": True}),
    ("round_off", "07_round_off", ["intra", "goods", "rate18", "roundoff"],
     {"always": True}),
    ("unregistered", "08_unregistered", ["intra", "goods", "rate18"], {}),
    ("combined", "09_combined",
     ["intra", "both", "mix_12_18", "line_discount", "roundoff"]
     + CHARGE_OPTS,
     {"service_lines": 1, "single_charge": True, "discount": True,
      "cash_discount": True, "always": True}),
]

SIDES = [("purchase", "Purchase"), ("sale", "Sales")]

# The unregistered counterparties, used only in 08_unregistered. On a sale
# one is the customer; on a purchase it heads the page as a supplier with
# no GSTIN.
UNREG = [
    {"name": "Shree Balaji Traders", "state": "MAHARASHTRA",
     "state_code": "27", "phone": "9822114477",
     "bill": ["Shop 7, Laxmi Market, Bhavani Peth",
              "Pune, MAHARASHTRA, 411042"]},
    {"name": "Ganesh Electricals & Hardware", "state": "MAHARASHTRA",
     "state_code": "27", "phone": "9765332211",
     "bill": ["12, Tulshibaug Road, Budhwar Peth",
              "Pune, MAHARASHTRA, 411002"]},
    {"name": "Sai Traders", "state": "MAHARASHTRA",
     "state_code": "27", "phone": "9890445566",
     "bill": ["Gala 4, Mahatma Phule Market, Hadapsar",
              "Pune, MAHARASHTRA, 411028"]},
]


def _strip_tax(inv):
    """Turn the invoice into a bill of supply: no GST anywhere on it.

    A supplier who is not registered under GST cannot collect it, so every
    rate goes to zero and the document is titled accordingly - the printed
    page, the HSN summary and the Tally voucher then all agree that no tax
    arose.
    """
    for l in inv["lines"]:
        l.gst = Decimal(0)
        l.cess_pct = Decimal(0)
    for c in inv.get("charges", []):
        c.gst = Decimal(0)
    inv["no_tax"] = True
    inv["doc_title"] = "BILL OF SUPPLY"


def _apply_party(inv, side, idx, type_id):
    """Put an unregistered firm on the invoices in the unregistered folder."""
    if type_id != "unregistered":
        return
    party = UNREG[idx % len(UNREG)]
    inv["buyer"] = {
        "name": party["name"], "legal_name": party["name"], "gstin": None,
        "state": party["state"], "bill": party["bill"],
        "ship": party["bill"], "phone": party["phone"],
    }
    inv["party_ledger"] = ("Cash Sales - Unregistered" if side == "sale"
                           else "Cash Purchase - Unregistered")
    inv["place_of_supply"] = f"{party['state_code']}-{party['state']}"
    inv["interstate"] = False
    # Buying from an unregistered supplier: no GST. Selling to an
    # unregistered customer is the opposite - we are registered, so we
    # charge tax as normal and the document stays a tax invoice.
    if side == "purchase":
        _strip_tax(inv)


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)

    orig_make = _scen.make_invoice
    state = {"side": None, "idx": 0, "type": None}

    def make_invoice(rng, opts, items, parties, seq, fy, used, detail=None):
        inv = orig_make(rng, opts, items, parties, seq, fy, used, detail)
        _apply_party(inv, state["side"], state["idx"], state["type"])
        return inv

    _scen.make_invoice = make_invoice
    sys.modules["invoicegen.scenarios"].make_invoice = make_invoice

    seen = set()
    manifest = []
    seq = 0
    for side_opt, side_dir in SIDES:
        for type_id, folder, extra, detail in TYPES:
            dest = os.path.join(OUT, side_dir, folder)
            os.makedirs(dest, exist_ok=True)
            for i in range(PER_TYPE):
                seq += 1
                state.update(side=side_opt, idx=i, type=type_id)
                opts = [side_opt, "tax_invoice", "registered"] + list(extra)
                if type_id == "unregistered":
                    opts.append("unregistered")
                d = dict(detail)
                # 7-8 goods on every document, alternating
                d["goods_lines"] = GOODS_LINES[i % len(GOODS_LINES)]
                rows = run(opts, count=1, seed=8200 + seq, outdir=dest,
                           write_json=True, start_at=seq, seen=seen,
                           detail=d, patterns=("classic",))
                manifest += [dict(r, side=side_dir, type=folder)
                             for r in rows]
            print(f"  {side_dir}/{folder}: {PER_TYPE}")

    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\ndone: {len(manifest)} invoices in {OUT}")
    return manifest


if __name__ == "__main__":
    main()
