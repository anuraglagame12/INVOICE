"""Purchase and sales invoices, one folder per feature type, Classic layout.

Fixed by request:
    layout      classic only
    layers      no RCM, no TDS, no TCS, no long descriptions
    charges     at most ONE charge on an invoice, picked at random
    goods       drawn from the 97-item catalogue
    services    the service type carries exactly one service line

Seven types per side, five invoices each:

    01_cgst_sgst      intra-state, goods, CGST + SGST
    02_igst           inter-state, goods, IGST
    03_services       service lines (SAC, lump sum, no qty/UOM)
    04_trade_discount line discount - taxable falls before GST
    05_cash_discount  settlement discount - comes off after GST
    06_round_off      total rounded to the rupee, adjustment shown
    07_combined       all of the above on one document

Registered and unregistered parties are mixed inside every type. Our firm is
always Abhidnya Enterprises: on a sale it heads the page and the customer is
the other party; on a purchase the supplier heads the page and we are the
buyer. An unregistered counterparty is only lawful intra-state, so the IGST
type stays registered throughout.
"""
import json
import os
import shutil
import sys
from decimal import Decimal

from invoicegen import scenarios as _scen
from invoicegen.generate import run

OUT = os.path.join(os.path.expanduser("~"), "Desktop", "Typed_Invoices")

PER_TYPE = 5

# id, folder, extra options, detail overrides
TYPES = [
    ("cgst_sgst", "01_cgst_sgst", ["intra", "goods", "rate18"], {}),
    ("igst", "02_igst", ["inter", "goods", "rate18"], {}),
    ("services", "03_services", ["intra", "services", "rate18"],
     {"service_lines": 1}),
    ("trade_discount", "04_trade_discount",
     ["intra", "goods", "rate18", "line_discount"],
     {"discount": True, "always": True}),
    ("cash_discount", "05_cash_discount", ["intra", "goods", "rate18"],
     {"cash_discount": True, "always": True}),
    ("round_off", "06_round_off", ["intra", "goods", "rate18", "roundoff"],
     {"always": True}),
    # The round-off is made by nudging a line's rate, not by adding a
    # charge, so a real charge is ticked here - one only, picked at random.
    ("combined", "07_combined",
     ["intra", "both", "mix_12_18", "line_discount", "roundoff",
      "freight", "packing", "insurance", "loading"],
     {"discount": True, "cash_discount": True, "single_charge": True,
      "service_lines": 1, "always": True}),
]

SIDES = [("purchase", "Purchase"), ("sale", "Sales")]

# An unregistered counterparty, used on both sides. On a sale this is the
# customer; on a purchase it becomes the letterhead - a supplier billing us
# without a GSTIN.
UNREG = {
    "name": "Shree Balaji Traders",
    "gstin": None,
    "state": "MAHARASHTRA",
    "state_code": "27",
    "bill": ["Shop 7, Laxmi Market, Bhavani Peth",
             "Pune, MAHARASHTRA, 411042"],
    "ship": ["Shop 7, Laxmi Market, Bhavani Peth",
             "Pune, MAHARASHTRA, 411042"],
    "phone": "9822114477",
    "tally_ledger": "Cash Purchase - Unregistered",
}

# Which of the five in a type get an unregistered party. Never on IGST: an
# unregistered party has no GSTIN and so no state registration to cross.
UNREG_SLOTS = {1, 3}


def _strip_tax(inv):
    """Turn an invoice into a bill of supply: no GST anywhere on it.

    A supplier who is not registered under GST cannot collect it, so a bill
    from one carries no CGST, SGST or IGST - and it is not a "tax invoice"
    either. Every rate goes to zero rather than the tax being hidden, so the
    printed document, the HSN summary and the Tally voucher all agree that
    no tax arose.
    """
    for l in inv["lines"]:
        l.gst = Decimal(0)
        l.cess_pct = Decimal(0)
    # A charge follows the supply it belongs to, so it loses its tax too.
    for c in inv.get("charges", []):
        c.gst = Decimal(0)
    inv["no_tax"] = True
    inv["doc_title"] = "BILL OF SUPPLY"


def _apply_party(inv, side, idx, type_id):
    """Force the counterparty for the unregistered slots of a type."""
    if type_id == "igst" or idx not in UNREG_SLOTS:
        return
    party = dict(UNREG)
    if side == "sale":
        party["tally_ledger"] = "Cash Sales - Unregistered"
    inv["buyer"] = {
        "name": party["name"], "legal_name": party["name"],
        "gstin": None, "state": party["state"],
        "bill": party["bill"], "ship": party["ship"],
        "phone": party["phone"],
    }
    inv["party_ledger"] = party["tally_ledger"]
    inv["place_of_supply"] = f"{party['state_code']}-{party['state']}"
    inv["interstate"] = False
    # Buying from an unregistered supplier: they charge no GST, so the
    # document is a bill of supply. Selling to an unregistered customer is
    # the opposite case - we are registered, so we charge tax as normal.
    if side == "purchase":
        _strip_tax(inv)


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)

    # Patch the party selection so our fixed unregistered firm is used, and
    # so a purchase can also come from an unregistered supplier.
    orig_make = _scen.make_invoice
    state = {"side": None, "idx": 0, "type": None}

    def make_invoice(rng, opts, items, parties, seq, fy, used, detail=None):
        inv = orig_make(rng, opts, items, parties, seq, fy, used, detail)
        _apply_party(inv, state["side"], state["idx"], state["type"])
        return inv

    _scen.make_invoice = make_invoice
    # generate() resolved the name at import time, so rebind there too
    import invoicegen.scenarios as S
    S.make_invoice = make_invoice

    seen = set()
    total = 0
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
                if type_id != "igst" and i in UNREG_SLOTS:
                    opts.append("unregistered")
                rows = run(opts, count=1, seed=5000 + seq, outdir=dest,
                           write_json=True, start_at=seq, seen=seen,
                           detail=dict(detail), patterns=("classic",))
                manifest += [dict(r, side=side_dir, type=folder) for r in rows]
                total += 1
            print(f"  {side_dir}/{folder}: {PER_TYPE}")

    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\ndone: {total} invoices in {OUT}")
    return manifest


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
