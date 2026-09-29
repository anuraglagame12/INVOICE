"""Prove no document can carry a number longer than the field allows.

Tally's voucher number is the binding constraint, so a number over
model.MAX_NUMBER_LEN cannot be imported. This exercises every document type
the generator can produce and fails if any number - the invoice's own, the
original it adjusts, or a bill-wise reference - is too long.

Run after touching anything that builds a document number.
"""
import glob
import json
import os
import shutil
import sys
import tempfile

from invoicegen.generate import run
from invoicegen.model import (MAX_NUMBER_LEN, check_number, our_number,
                              supplier_number)

# every side x document type the UI can ask for
COMBOS = [
    ["sale", "tax_invoice", "registered", "intra", "goods"],
    ["sale", "tax_invoice", "unregistered", "intra", "both"],
    ["sale", "credit_note", "registered", "inter", "goods"],
    ["sale", "debit_note", "registered", "intra", "services"],
    ["sale", "sales_order", "registered", "intra", "goods"],
    ["purchase", "tax_invoice", "registered", "intra", "goods"],
    ["purchase", "tax_invoice", "registered", "inter", "both"],
    ["purchase", "credit_note", "registered", "intra", "goods"],
    ["purchase", "debit_note", "registered", "inter", "goods"],
    ["purchase", "purchase_order", "registered", "intra", "goods"],
]


def numbers_in(rec):
    """Every field on a document that carries a document number."""
    out = [("invoice_number", rec["invoice_number"])]
    oi = rec.get("original_invoice")
    if oi and oi.get("number"):
        out.append(("original_invoice", oi["number"]))
    bw = rec.get("bill_wise")
    if bw and bw.get("reference"):
        out.append(("bill_wise", bw["reference"]))
    v = rec.get("expected_voucher") or {}
    for b in (v.get("bills") or []):
        if b.get("ref"):
            out.append(("bill ref", b["ref"]))
    return out


def main():
    # the helpers themselves
    bad = []
    for seq in (0, 1, 99, 999, 3599):
        n = our_number("SI", seq)
        if len(n) > MAX_NUMBER_LEN:
            bad.append(("our_number", n))
    import random
    r = random.Random(7)
    for _ in range(200):
        n = supplier_number(r)
        if len(n) > MAX_NUMBER_LEN:
            bad.append(("supplier_number", n))

    # the guard must refuse, not truncate
    try:
        check_number("AE/SI/26-27/26401")
        bad.append(("guard", "accepted a 17-character number"))
    except ValueError:
        pass

    # and every document the generator can actually build
    out = tempfile.mkdtemp(prefix="numlen_")
    total = 0
    try:
        seen = set()
        for i, opts in enumerate(COMBOS):
            run(opts, count=5, seed=400 + i, outdir=out, write_json=True,
                start_at=1 + i * 20, seen=seen)
        for p in glob.glob(os.path.join(out, "json", "*.json")):
            rec = json.load(open(p, encoding="utf-8"))
            total += 1
            for field, num in numbers_in(rec):
                if len(num) > MAX_NUMBER_LEN:
                    bad.append((f"{os.path.basename(p)} [{field}]", num))
    finally:
        shutil.rmtree(out, ignore_errors=True)

    print(f"limit {MAX_NUMBER_LEN} chars | {len(COMBOS)} document types | "
          f"{total} documents checked")
    if bad:
        print(f"\n{len(bad)} NUMBER(S) TOO LONG:")
        for where, num in bad[:20]:
            print(f"  {where}: {num!r} ({len(num)})")
        return 1
    print("all document numbers within the limit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
