"""Prove each checkbox actually changes the invoices it claims to.

For every option, generate a batch with it ON and a batch with it OFF, then
assert the ON batch shows the feature and the OFF batch does not. Run this
whenever you change the generator.

    python check_options.py            # test every option
    python check_options.py tds cess   # test just these
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from invoicegen.generate import run          # noqa: E402
from invoicegen.scenarios import PANELS      # noqa: E402

N = 14        # invoices per batch - enough for a probabilistic option to show
SEED = 4242


def batch(opts):
    """Generate into a temp dir and return the parsed ground-truth records."""
    tmp = tempfile.mkdtemp(prefix="chk_")
    try:
        run(opts, count=N, seed=SEED, outdir=tmp, write_json=True)
        jd = os.path.join(tmp, "json")
        return [json.load(open(os.path.join(jd, f), encoding="utf-8"))
                for f in sorted(os.listdir(jd))]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- how to detect that a feature is present in a batch -------------------
# Each probe returns the number of invoices showing the feature.

def any_line(recs, pred):
    return sum(1 for r in recs if any(pred(l) for l in r["lines"]))


PROBES = {
    "line_discount": lambda rs: sum(any(l["discount_pct"] > 0
                                        for l in r["lines"]) for r in rs),
    "sale":         lambda rs: sum(r["document_type"] == "TAX INVOICE"
                                   for r in rs),
    "purchase":     lambda rs: sum(r["document_type"] == "PURCHASE INVOICE"
                                   for r in rs),
    "tax_invoice":  lambda rs: sum(r["document_type"] == "TAX INVOICE"
                                   for r in rs),
    "credit_note":  lambda rs: sum(r["document_type"] == "CREDIT NOTE"
                                   for r in rs),
    "debit_note":   lambda rs: sum(r["document_type"] == "DEBIT NOTE"
                                   for r in rs),
    "purchase_order": lambda rs: sum(r["document_type"] == "PURCHASE ORDER"
                                     for r in rs),
    "sales_order":  lambda rs: sum(r["document_type"] == "SALES ORDER"
                                   for r in rs),
    "scanned":      lambda rs: sum("scanned" in r["scenario_tags"]
                                   for r in rs),

    "intra":        lambda rs: sum(r["supply_type"] == "intra-state" for r in rs),
    "inter":        lambda rs: sum(r["supply_type"] == "inter-state" for r in rs),

    "rate18":       lambda rs: sum(r["totals"]["gst_rates_present"] == [18.0]
                                   for r in rs),
    "rate_other":   lambda rs: sum(len(r["totals"]["gst_rates_present"]) == 1
                                   and r["totals"]["gst_rates_present"][0]
                                   in (5.0, 12.0, 28.0) for r in rs),
    "mix_12_18":    lambda rs: sum(set(r["totals"]["gst_rates_present"])
                                   == {12.0, 18.0} for r in rs),
    "mix_all":      lambda rs: sum({5.0, 12.0, 18.0, 28.0}
                                   <= set(r["totals"]["gst_rates_present"])
                                   for r in rs),
    "exempt":       lambda rs: any_line(rs, lambda l: l["exempt"]),
    "cess":         lambda rs: sum(r["totals"]["cess"] > 0 for r in rs),
    "rcm":          lambda rs: sum(r["reverse_charge"] for r in rs),

    "goods":        lambda rs: sum(all(l["type"] == "goods" for l in r["lines"])
                                   for r in rs),
    "services":     lambda rs: sum(all(l["type"] == "service"
                                       for l in r["lines"]) for r in rs),
    "both":         lambda rs: sum({"goods", "service"}
                                   == {l["type"] for l in r["lines"]}
                                   for r in rs),

    "freight":      lambda rs: sum(any("Freight" in c["label"]
                                       for c in r["other_charges"]) for r in rs),
    "packing":      lambda rs: sum(any("Packing" in c["label"]
                                       for c in r["other_charges"]) for r in rs),
    "insurance":    lambda rs: sum(any("Insurance" in c["label"]
                                       for c in r["other_charges"]) for r in rs),
    "loading":      lambda rs: sum(any("Loading" in c["label"]
                                       for c in r["other_charges"]) for r in rs),
    "advance":      lambda rs: sum(r["totals"]["advance_adjusted"] > 0
                                   for r in rs),
    "roundoff":     lambda rs: sum(abs(r["totals"]["round_off"]) >= 0.25
                                   for r in rs),

    "registered":   lambda rs: sum(bool(r["buyer"]["gstin"]) for r in rs),
    "unregistered": lambda rs: sum(not r["buyer"]["gstin"] for r in rs),
    "name_variant": lambda rs: sum(r["buyer"]["name"]
                                   != r["buyer"]["tally_ledger"] for r in rs),
    "eway":         lambda rs: sum(bool(r.get("eway_bill")) for r in rs),
    "irn":          lambda rs: sum(bool(r.get("irn")) for r in rs),

    "tds":          lambda rs: sum(r["tds"]["applicable"] for r in rs),
    "tcs":          lambda rs: sum(r["totals"]["tcs_collected"] > 0 for r in rs),
    "billwise":     lambda rs: sum(bool(r.get("bill_wise")) for r in rs),
    "godown":       lambda rs: any_line(rs, lambda l: bool(l["godown"])),
    "batch":        lambda rs: any_line(rs, lambda l: bool(l["batch"])),

    "many_items":   lambda rs: sum(len(r["lines"]) >= 20 for r in rs),
    "long_desc":    lambda rs: any_line(rs, lambda l: len(l["description"]) > 90),
    "large_amount": lambda rs: sum(r["totals"]["total"] > 1000000 for r in rs),
    "odd_paise":    lambda rs: any_line(
                        rs, lambda l: round(l["mrp"] % 1, 2) not in (0.0, 0.5)),
}

# Options that only make sense with a companion ticked, and options whose
# absence cannot be asserted because the generator varies freely by default.
NEEDS = {
    "line_discount": ["intra", "goods"],
    "scanned": ["intra", "goods"],
    "cess": ["intra"], "exempt": ["intra"], "rcm": ["inter"],
    "godown": ["goods"], "batch": ["goods"], "odd_paise": ["goods"],
    "long_desc": ["goods"], "many_items": ["goods"],
    "name_variant": ["registered", "intra"],
    "tds": ["intra", "both"], "tcs": ["intra", "both"],
    "advance": ["intra"], "billwise": ["intra"],
    "freight": ["intra"], "packing": ["intra"], "insurance": ["intra"],
    "loading": ["intra"], "eway": ["intra"], "irn": ["intra"],
    "large_amount": ["intra", "goods"], "unregistered": ["intra"],
}
# For these, "off" means the opposite option is ticked instead.
OPPOSITE = {
    "sale": ["purchase"], "purchase": ["sale"],
    "tax_invoice": ["credit_note"], "credit_note": ["tax_invoice"],
    "debit_note": ["tax_invoice"],
    "purchase_order": ["tax_invoice"], "sales_order": ["tax_invoice"],
    "intra": ["inter"], "inter": ["intra"],
    "goods": ["services"], "services": ["goods"], "both": ["goods"],
    "registered": ["unregistered", "intra"],
    "unregistered": ["registered", "intra"],
    "rate18": ["rate_other"], "rate_other": ["rate18"],
    "mix_12_18": ["rate18"], "mix_all": ["rate18"],
}


def main(only=None):
    ids = [oid for _, _, opts in PANELS for oid, _, _ in opts]
    if only:
        ids = [i for i in ids if i in only]
        unknown = set(only) - set(ids)
        if unknown:
            print(f"unknown option(s): {', '.join(sorted(unknown))}")
            return 2

    print(f"{'option':<14} {'ON':>6} {'OFF':>6}   result")
    print("-" * 52)
    bad = []
    for oid in ids:
        probe = PROBES[oid]
        support = NEEDS.get(oid, [])
        on = batch(sorted(set([oid] + support)))
        off_opts = OPPOSITE.get(oid, support) or ["intra", "goods"]
        off = batch(sorted(set(off_opts) - {oid}))

        n_on, n_off = probe(on), probe(off)
        ok = n_on > 0 and n_on > n_off
        note = "" if ok else ("  <-- never appears" if n_on == 0
                              else "  <-- no different when off")
        if not ok:
            bad.append(oid)
        print(f"{oid:<14} {n_on:>4}/{N} {n_off:>4}/{N}   "
              f"{'ok' if ok else 'FAIL'}{note}")

    print("-" * 52)
    print(f"{len(ids) - len(bad)}/{len(ids)} options verified"
          + (f"  -  failing: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
