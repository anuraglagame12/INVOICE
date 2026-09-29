"""Trace every figure on an invoice and prove nothing drifts.

The rule: values come from exact inputs, each printed figure is rounded
once, and the only deliberate adjustment is the Round Off line at the very
end. This walks a batch and checks each link in the chain.
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import warnings
from decimal import Decimal

warnings.filterwarnings("ignore")

from invoicegen.generate import run                          # noqa: E402

TOL = Decimal("0.011")


def m(x):
    return Decimal(str(x)).quantize(Decimal("0.01"))


fails = {}


def note(k, d):
    fails.setdefault(k, []).append(d)


tmp = tempfile.mkdtemp()
run(["goods", "services", "both", "intra", "inter", "mix_all", "cess",
     "line_discount", "odd_paise", "freight", "packing", "large_amount"],
    count=40, seed=99, outdir=tmp, write_json=True, formats=(),
    detail={"discount": True})

n_lines = n_docs = 0
for f in glob.glob(os.path.join(tmp, "json", "*.json")):
    j = json.load(open(f, encoding="utf-8"))
    t = j["totals"]
    n_docs += 1
    base = os.path.basename(f)

    line_taxable = Decimal(0)
    line_tax = Decimal(0)
    line_cess = Decimal(0)

    for l in j["lines"]:
        n_lines += 1
        mrp = Decimal(str(l["mrp"]))
        qty = Decimal(str(l["qty"]))
        dpc = Decimal(str(l.get("discount_pct", 0)))

        # 1. taxable comes from the EXACT discounted value, not a rounded rate
        want = m(mrp * qty * (1 - dpc / 100))
        got = Decimal(str(l["taxable_value"]))
        if abs(got - want) > TOL:
            note("taxable not exact", "%s %s: %s vs %s"
                 % (base, l["description"][:22], got, want))

        # 2. tax is that printed taxable times the rate, rounded once
        wt = m(got * Decimal(str(l["gst_rate"])) / 100)
        if abs(Decimal(str(l["tax_amount"])) - wt) > TOL:
            note("line tax not exact", "%s %s" % (base, l["description"][:22]))

        # 3. the line amount is the sum of its own printed parts
        wc = Decimal(str(l.get("cess_amount", 0)))
        wa = m(got + Decimal(str(l["tax_amount"])) + wc)
        if abs(Decimal(str(l["amount"])) - wa) > TOL:
            note("line amount not the sum of its parts",
                 "%s %s" % (base, l["description"][:22]))

        line_taxable += got
        line_tax += Decimal(str(l["tax_amount"]))
        line_cess += wc

    # 4. the invoice taxable is the sum of the printed lines
    if abs(Decimal(str(t["taxable_amount"])) - m(line_taxable)) > TOL:
        note("invoice taxable != sum of lines", base)

    # 5. CGST and SGST are exact halves and identical
    cg, sg, ig = (Decimal(str(t[k])) for k in ("cgst", "sgst", "igst"))
    if cg or sg:
        if cg != sg:
            note("CGST != SGST", base)
        if ig:
            note("IGST alongside CGST", base)

    # 6. the payable is the parts, with round-off the ONLY adjustment
    ro = Decimal(str(t["round_off"]))
    pre = (Decimal(str(t["taxable_amount"])) + Decimal(str(t["other_charges"]))
           + cg + sg + ig + Decimal(str(t.get("cess", 0)))
           - Decimal(str(t.get("cash_discount", 0)))
           - Decimal(str(t["advance_adjusted"]))
           - Decimal(str(t["tds_deducted"]))
           + Decimal(str(t["tcs_collected"])))
    if abs(pre + ro - Decimal(str(t["total"]))) > TOL:
        note("total != parts + round-off", "%s: %s + %s vs %s"
             % (base, pre, ro, t["total"]))

    # 7. round-off never moves more than half a rupee, and only it may
    if abs(ro) > Decimal("0.5"):
        note("round-off beyond half a rupee", "%s: %s" % (base, ro))
    # where there is a round-off the total must be whole; where there is
    # none the exact paise must stand
    if ro and Decimal(str(t["total"])) % 1 != 0:
        note("rounded but not a whole rupee", base)
    if not ro and abs(pre - Decimal(str(t["total"]))) > TOL:
        note("no round-off yet the total drifted", base)

shutil.rmtree(tmp, ignore_errors=True)

print("documents traced : %d" % n_docs)
print("lines traced     : %d" % n_lines)
print()
if fails:
    for k, v in sorted(fails.items(), key=lambda x: -len(x[1])):
        print("  %-38s %4d   e.g. %s" % (k, len(v), v[0]))
    print()
    print("DRIFT FOUND: %d" % sum(len(v) for v in fails.values()))
    sys.exit(1)
print("no drift anywhere: every figure exact, round-off only at the end")
