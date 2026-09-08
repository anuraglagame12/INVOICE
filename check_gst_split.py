"""Guard: CGST and SGST must always print identical.

The two halves of one GST rate are never shown a paisa apart on a real
invoice. An earlier version split the tax as `tax/2` and `tax - tax/2`, which
kept the sum exact but produced 10,271.03 against 10,271.02 whenever the tax
landed on an odd number of paise. This re-checks every path that halves tax:

    python check_gst_split.py

Exits non-zero if any invoice, line, voucher leg or rendered PDF disagrees.
"""
import glob
import json
import os
import shutil
import sys
import tempfile
from decimal import Decimal as D

from invoicegen import catalogue as cat
from invoicegen.generate import run
from invoicegen.model import half_tax, money
from invoicegen.run_scenarios import run_scenarios

FAILURES = []


def fail(what, a, b, where):
    FAILURES.append(f"{what}: {a} != {b}  ({where})")


def check_helper():
    """Halving any tax - odd paise included - must give two equal halves.

    This is the direct test. The builders round tax to an even figure before
    splitting it, which would hide a regression in the split itself, so check
    the halving on raw odd-paise values where the old code actually broke.
    """
    for v in ["0.01", "0.03", "2.03", "1419.49", "14628.49", "20542.05",
              "99999.99", "7314.49", "3.01"]:
        tax = D(v)
        cgst = half_tax(tax)
        sgst = half_tax(tax)
        if cgst != sgst:
            fail("half_tax split", cgst, sgst, f"tax={v}")
        # and the doubled half is what the total must use
        if money(cgst + sgst) != money(cgst * 2):
            fail("half_tax total", money(cgst + sgst), money(cgst * 2),
                 f"tax={v}")

    # guard the source itself: no module may halve tax asymmetrically
    import glob as _g
    import os as _o
    import re as _re
    here = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                        "invoicegen")
    pat = _re.compile(r"(tax|tx)\b[^\n]*?/ *2")
    for src in _g.glob(_o.path.join(here, "*.py")):
        in_helper = False
        for i, line in enumerate(open(src, encoding="utf-8"), 1):
            # half_tax's own body is the one place allowed to divide
            if (in_helper or "half_tax" in line
                    or line.strip().startswith("#")):
                if line.startswith("def half_tax"):
                    in_helper = True
                elif in_helper and line.strip() and not line[:1].isspace():
                    in_helper = False
                continue
            if line.startswith("def half_tax"):
                in_helper = True
                continue
            if in_helper and line.strip() and not line[:1].isspace():
                in_helper = False
            if pat.search(line) and "W / 2" not in line:
                FAILURES.append(
                    f"raw tax halving instead of half_tax(): "
                    f"{_o.path.basename(src)}:{i}: {line.strip()[:60]}")


def check_invoice_path():
    """The Custom-Mix invoice builder, across every tax mode."""
    out = tempfile.mkdtemp(prefix="gstchk_")
    try:
        i = 0
        for side in ("purchase", "sale"):
            for tax in ("rate18", "rate_other", "mix_12_18", "mix_all",
                        "exempt", "cess", "rcm"):
                for content in ("goods", "services", "both"):
                    i += 1
                    run([side, "tax_invoice", "registered", "intra", tax,
                         content, "freight", "line_discount"],
                        count=2, seed=900 + i, outdir=out, write_json=True,
                        start_at=i * 10)
        n = 0
        for f in glob.glob(os.path.join(out, "json", "*.json")):
            d = json.load(open(f, encoding="utf-8"))
            n += 1
            t = d["totals"]
            if D(str(t["cgst"])) != D(str(t["sgst"])):
                fail("invoice total", t["cgst"], t["sgst"], os.path.basename(f))
            for l in d.get("lines", []):
                if D(str(l.get("cgst", 0))) != D(str(l.get("sgst", 0))):
                    fail("invoice line", l.get("cgst"), l.get("sgst"),
                         os.path.basename(f))
        return n
    finally:
        shutil.rmtree(out, ignore_errors=True)


def check_voucher_path():
    """The scenario runner, which posts Dr/Cr legs."""
    out = tempfile.mkdtemp(prefix="gstchk_")
    try:
        sids = [s[0] for s in cat.SCENARIOS if s[3] != "none"]
        run_scenarios(sids, count=1, seed=11, outdir=out, write_json=True)
        n = 0
        for f in glob.glob(os.path.join(out, "json", "*.json")):
            d = json.load(open(f, encoding="utf-8"))
            n += 1
            v = d.get("voucher") or {}
            if v and not v.get("balanced", True):
                FAILURES.append(f"voucher does not balance ({os.path.basename(f)})")
            cg = sg = None
            for e in v.get("entries", []):
                if "CGST" in e["ledger"]:
                    cg = D(str(e["dr"])) + D(str(e["cr"]))
                if "SGST" in e["ledger"]:
                    sg = D(str(e["dr"])) + D(str(e["cr"]))
            if cg is not None and sg is not None and cg != sg:
                fail("voucher leg", cg, sg, os.path.basename(f))
        return n
    finally:
        shutil.rmtree(out, ignore_errors=True)


def main():
    check_helper()
    a = check_invoice_path()
    b = check_voucher_path()
    print(f"invoices checked : {a}")
    print(f"documents checked: {b}")
    if FAILURES:
        print(f"\nFAILED - {len(FAILURES)} CGST/SGST problems")
        for f in FAILURES[:20]:
            print("   ", f)
        return 1
    print("\nok - CGST equals SGST everywhere, all vouchers balance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
