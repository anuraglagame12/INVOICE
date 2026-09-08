"""Every purchase-invoice combination the generator can express.

Fixed by request:
    side        purchase only          (no sales)
    doctype     tax invoice only
    party       registered supplier only
    layers      none (no TDS/TCS/bill-wise/godown/batch)

Varied exhaustively:
    supply      intra / inter                                  2
    tax         18 / other / mix12-18 / mix-all / exempt        7
                / cess / rcm
    content     goods / services / both                        3
    charges     every subset of line_discount, freight,        64
                packing, insurance, loading, roundoff
                (advance adjusted deliberately excluded)

    2 x 7 x 3 x 64 = 2,688 invoices

`many_items` and `long_desc` are sprinkled over a share of the batch rather
than forced onto every invoice, so the set carries some long documents
without every one of them being long.
"""
import itertools
import os
import shutil

from invoicegen.generate import run
from invoicegen import scenarios as _scen

OUT = r"C:\Users\Anurag L\Desktop\Purchase_All_Scenarios"

SUPPLY = ["intra", "inter"]
TAX = ["rate18", "rate_other", "mix_12_18", "mix_all", "exempt", "cess", "rcm"]
CONTENT = ["goods", "services", "both"]
CHARGES = ["line_discount", "freight", "packing", "insurance", "loading",
           "roundoff"]
# every subset of the charge flags, smallest first
CHARGE_SETS = [c for n in range(len(CHARGES) + 1)
               for c in itertools.combinations(CHARGES, n)]


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)

    combos = list(itertools.product(SUPPLY, TAX, CONTENT, CHARGE_SETS))
    print(f"combinations: {len(combos)}")

    rows = []
    seen = set()   # shared across calls so invoice numbers stay unique
    for i, (sup, tax, cont, chg) in enumerate(combos, 1):
        opts = ["purchase", "tax_invoice", "registered", sup, tax, cont]
        opts += list(chg)
        # shape: give roughly a fifth of the batch long descriptions and
        # a fifth many line items, deterministically by position
        if i % 5 == 0:
            opts.append("long_desc")
        if i % 7 == 0:
            opts.append("many_items")
        rows += run(opts, count=1, seed=1000 + i, outdir=OUT,
                    write_json=False, start_at=i, seen=seen)
        if i % 200 == 0:
            print(f"  {i}/{len(combos)}")

    # flatten pdf/ into the folder root
    pdf_dir = os.path.join(OUT, "pdf")
    if os.path.isdir(pdf_dir):
        for f in os.listdir(pdf_dir):
            shutil.move(os.path.join(pdf_dir, f), os.path.join(OUT, f))
        os.rmdir(pdf_dir)

    n = len([f for f in os.listdir(OUT) if f.endswith(".pdf")])
    print(f"done: {n} PDFs in {OUT}")
    return rows


if __name__ == "__main__":
    main()
