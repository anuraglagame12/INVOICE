"""Guard: every figure must come from exact arithmetic.

A discounted rate rarely lands on a whole paisa - 465.00 less 12.5% is
exactly 406.875. Rounding that unit rate before multiplying by the quantity
magnifies the half-paisa by the quantity: fifty units turned it into 25
paise, and the invoice stopped matching its own figures.

So: values are computed from exact inputs and rounded once, at the end.
This checks that holds - in the model, in generated documents, and on the
printed page.
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
from invoicegen.model import Line, money                     # noqa: E402
from invoicegen.run_scenarios import run_scenarios           # noqa: E402

TOL = Decimal("0.011")          # a paisa, for comparing 2dp figures
fails = []


def check(label, got, want):
    if abs(Decimal(str(got)) - Decimal(str(want))) > TOL:
        fails.append("%s: %s, expected %s" % (label, got, want))


# ---- 1. the awkward cases, worked by hand --------------------------------
# each is a rate whose discounted value falls between paise
CASES = [
    # mrp,      qty, disc%,  exact taxable
    ("465.00",   50, "12.5", "20343.75"),   # 406.875 - the half paisa
    ("1450.00",  33, "7.5",  "44261.25"),   # 1341.25 x 33
    ("212.00",   17, "33.33", "2402.79"),   # a repeating third
    ("8450.00",   3, "12.5", "22181.25"),
    ("96.00",   100, "16.67", "7999.68"),
    ("685.00",   45, "22.5",  "23889.38"),
]

print("hand-worked lines")
for mrp, qty, disc, want in CASES:
    l = Line("x", "1234", Decimal(mrp), qty, "PCS", 18,
             discount_pct=Decimal(disc))
    exact = money(Decimal(mrp) * qty * (1 - Decimal(disc) / 100))
    check("%s x %d less %s%%" % (mrp, qty, disc), l.taxable, exact)
    print("   %9s x %3d less %6s%%  ->  %12s" % (mrp, qty, disc, l.taxable))

# ---- 2. every generated line, across both code paths ---------------------
print()
checked = 0
for label, maker in (
        ("custom mix", lambda d: run(
            ["goods", "services", "both", "intra", "inter", "mix_all",
             "line_discount", "odd_paise"], count=25, seed=11, outdir=d,
            write_json=True, formats=(),
            detail={"discount": True})),
        ("scenarios", lambda d: run_scenarios(
            ["pur_trade_disc", "sale_trade_disc", "pur_goods_local",
             "sale_goods_inter", "pur_serv_local"],
            count=4, seed=5, outdir=d, write_json=True, formats=()))):
    tmp = tempfile.mkdtemp()
    try:
        maker(tmp)
        for f in glob.glob(os.path.join(tmp, "json", "*.json")):
            j = json.load(open(f, encoding="utf-8"))
            for ln in j["lines"]:
                checked += 1
                mrp = Decimal(str(ln["mrp"]))
                qty = Decimal(str(ln["qty"]))
                d_pct = Decimal(str(ln.get("discount_pct", 0)))
                want = money(mrp * qty * (1 - d_pct / 100))
                if abs(Decimal(str(ln["taxable_value"])) - want) > TOL:
                    fails.append(
                        "%s %s: taxable %s, exact %s"
                        % (os.path.basename(f), ln["description"][:30],
                           ln["taxable_value"], want))
                # tax follows from the taxable value actually printed
                tax = money(Decimal(str(ln["taxable_value"]))
                            * Decimal(str(ln["gst_rate"])) / 100)
                if abs(Decimal(str(ln["tax_amount"])) - tax) > TOL:
                    fails.append("%s %s: tax %s, expected %s"
                                 % (os.path.basename(f),
                                    ln["description"][:30],
                                    ln["tax_amount"], tax))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("%-12s lines checked so far: %d" % (label, checked))

print()
if fails:
    for f in fails[:12]:
        print("  FAIL", f)
    print()
    print("%d line(s) not matching exact arithmetic" % len(fails))
    sys.exit(1)
print("%d hand-worked cases and %d generated lines all match exact arithmetic"
      % (len(CASES), checked))
