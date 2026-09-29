"""Purchase and sales invoices, one folder per feature, Classic layout.

Seven types per side, three invoices each:

    01_cgst_sgst    intra-state goods, CGST + SGST
    02_igst         inter-state goods, IGST
    03_service      goods plus exactly ONE service line (SAC, lump sum)
    04_other_charge goods plus exactly ONE charge (freight/packing/...)
    05_discount     trade discount on the lines AND a cash discount after tax
    06_round_off    total rounded to the rupee, adjustment shown
    07_combined     all of the above on one document

A service line and a charge are capped at one apiece on any invoice - real
documents carry a single freight line, not four.

Our firm is Abhidnya Enterprises throughout: on a sale it heads the page and
the customer is the other party; on a purchase the supplier heads the page
and we are the buyer. Buying from an unregistered supplier means no GST can
be charged, so those come out as a BILL OF SUPPLY.

No RCM, TDS, TCS or long descriptions anywhere.
"""
import json
import os
import shutil
import sys
from decimal import Decimal

from invoicegen import scenarios as _scen
from invoicegen.generate import run

OUT = os.path.join(os.path.expanduser("~"), "Desktop", "GST_Invoices_ByType")

PER_TYPE = 3

# id, folder, extra options, detail overrides
TYPES = [
    ("cgst_sgst", "01_cgst_sgst",
     ["intra", "goods", "rate18"], {}),
    ("igst", "02_igst",
     ["inter", "goods", "rate18"], {}),
    # "both" puts goods and services on the page; service_lines pins it to one
    ("service", "03_service",
     ["intra", "both", "rate18"],
     {"service_lines": 1, "always": True}),
    # every charge kind is allowed, single_charge keeps it to one per document
    ("other_charge", "04_other_charge",
     ["intra", "goods", "rate18", "freight", "packing", "insurance",
      "loading"],
     {"single_charge": True, "always": True}),
    ("discount", "05_discount",
     ["intra", "goods", "rate18", "line_discount"],
     {"discount": True, "cash_discount": True, "always": True}),
    ("round_off", "06_round_off",
     ["intra", "goods", "rate18", "roundoff"], {"always": True}),
    ("combined", "07_combined",
     ["intra", "both", "mix_12_18", "line_discount", "roundoff",
      "freight", "packing", "insurance", "loading"],
     {"service_lines": 1, "single_charge": True, "discount": True,
      "cash_discount": True, "always": True}),
]

SIDES = [("purchase", "Purchase"), ("sale", "Sales")]

# The unregistered counterparty. On a sale this is the customer; on a
# purchase it heads the page as a supplier billing us without a GSTIN.
UNREG = {
    "name": "Shree Balaji Traders",
    "state": "MAHARASHTRA",
    "state_code": "27",
    "bill": ["Shop 7, Laxmi Market, Bhavani Peth",
             "Pune, MAHARASHTRA, 411042"],
    "phone": "9822114477",
}

# Which invoice in a type gets an unregistered party. Never on IGST - an
# unregistered party has no registration, so no inter-state supply.
UNREG_SLOT = 2


def _strip_tax(inv):
    """Turn the invoice into a bill of supply: no GST anywhere on it."""
    for l in inv["lines"]:
        l.gst = Decimal(0)
        l.cess_pct = Decimal(0)
    for c in inv.get("charges", []):
        c.gst = Decimal(0)
    inv["no_tax"] = True
    inv["doc_title"] = "BILL OF SUPPLY"


def _apply_party(inv, side, idx, type_id):
    """Put the fixed unregistered firm on the invoices that call for one."""
    if type_id == "igst" or idx != UNREG_SLOT:
        return
    inv["buyer"] = {
        "name": UNREG["name"], "legal_name": UNREG["name"], "gstin": None,
        "state": UNREG["state"], "bill": UNREG["bill"], "ship": UNREG["bill"],
        "phone": UNREG["phone"],
    }
    inv["party_ledger"] = ("Cash Sales - Unregistered" if side == "sale"
                           else "Cash Purchase - Unregistered")
    inv["place_of_supply"] = f"{UNREG['state_code']}-{UNREG['state']}"
    inv["interstate"] = False
    # A supplier who is not registered cannot charge GST.
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
    _scen_mod = sys.modules["invoicegen.scenarios"]
    _scen_mod.make_invoice = make_invoice

    seen = set()
    manifest = []
    seq = 0
    for side_opt, side_dir in SIDES:
        for type_id, folder, extra, detail in TYPES:
            dest = os.path.join(OUT, side_dir, folder)
            os.makedirs(dest, exist_ok=True)
            for i in range(1, PER_TYPE + 1):
                seq += 1
                state.update(side=side_opt, idx=i, type=type_id)
                opts = [side_opt, "tax_invoice", "registered"] + list(extra)
                if type_id != "igst" and i == UNREG_SLOT:
                    opts.append("unregistered")
                rows = run(opts, count=1, seed=6100 + seq, outdir=dest,
                           write_json=True, start_at=seq, seen=seen,
                           detail=dict(detail), patterns=("classic",))
                manifest += [dict(r, side=side_dir, type=folder)
                             for r in rows]
            print(f"  {side_dir}/{folder}: {PER_TYPE}")

    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\ndone: {len(manifest)} invoices in {OUT}")
    return manifest


if __name__ == "__main__":
    main()
