"""Check every generated invoice: arithmetic, tax split, and voucher balance.

Run after a batch to prove the ground-truth JSON is internally consistent and
that each PDF's text layer carries the key figures.
"""
import glob
import json
import os
import subprocess
import sys

TOL = 0.011  # a paisa, for float comparison of 2dp values


def close(a, b):
    return abs(a - b) < TOL


def check(path):
    d = json.load(open(path, encoding="utf-8"))
    t, ls = d["totals"], d["lines"]
    errs = []

    # --- per line
    for l in ls:
        exp_tax = round(l["taxable_value"] * l["gst_rate"] / 100, 2)
        if not close(round(l["rate"] * l["qty"], 2), l["taxable_value"]):
            errs.append(f"L{l['sr']} rate*qty != taxable")
        if not close(exp_tax, l["tax_amount"]):
            errs.append(f"L{l['sr']} tax wrong")
        if not close(l["taxable_value"] + l["tax_amount"] + l["cess_amount"],
                     l["amount"]):
            errs.append(f"L{l['sr']} amount != taxable+tax+cess")
        # the CGST/SGST/IGST split must match the supply type
        if d["supply_type"] == "inter-state":
            if not close(l["igst"], l["tax_amount"]) or l["cgst"] or l["sgst"]:
                errs.append(f"L{l['sr']} interstate split wrong")
        else:
            if l["igst"] or not close(l["cgst"] + l["sgst"], l["tax_amount"]):
                errs.append(f"L{l['sr']} intrastate split wrong")

    # --- line sums vs totals
    if not close(sum(l["taxable_value"] for l in ls), t["taxable_amount"]):
        errs.append("sum(lines.taxable) != totals.taxable_amount")

    line_tax = sum(l["tax_amount"] for l in ls)
    chg_tax = sum(c["tax_amount"] for c in d["other_charges"])
    split = t["cgst"] + t["sgst"] + t["igst"]
    if not close(line_tax + chg_tax, split):
        errs.append(f"tax {line_tax + chg_tax:.2f} != split {split:.2f}")

    # --- tax summary reconciles
    smy = sum(s["taxable_value"] for s in d["tax_summary"])
    chg = sum(c["amount"] for c in d["other_charges"] if c["hsn_sac"])
    if not close(smy, t["taxable_amount"] + chg):
        errs.append("tax_summary taxable does not reconcile")

    # --- the grand total
    # under RCM neither tax nor cess is collected by the supplier
    tax_in_total = 0.0 if d["reverse_charge"] else split
    cess_in_total = 0.0 if d["reverse_charge"] else t["cess"]
    expect = (t["taxable_amount"] + t["other_charges"] + tax_in_total
              + cess_in_total + t["tcs_collected"] - t["tds_deducted"]
              - t["advance_adjusted"] + t["round_off"])
    if not close(expect, t["total"]):
        errs.append(f"total {t['total']:.2f} != computed {expect:.2f}")

    # round-off never moves more than half a rupee (an exact .50 settles down)
    if abs(t["round_off"]) > 0.5 + TOL:
        errs.append(f"round_off {t['round_off']} out of range")
    if not close(t["total"], round(t["total"])):
        errs.append("total is not a whole rupee")

    # --- voucher balances (Dr == Cr, or Tally rejects it)
    v = d["expected_voucher"]
    dr = round(sum(e["dr"] for e in v["entries"]), 2)
    cr = round(sum(e["cr"] for e in v["entries"]), 2)
    if not close(dr, cr):
        errs.append(f"voucher unbalanced Dr {dr:.2f} vs Cr {cr:.2f}")
    if not v["balanced"]:
        errs.append("voucher flagged unbalanced")

    # --- mandatory fields (Procount minimum dataset)
    for f in ("invoice_number", "invoice_date", "place_of_supply"):
        if not d.get(f):
            errs.append(f"missing {f}")
    if not d["buyer"]["tally_ledger"]:
        errs.append("missing party ledger")
    for l in ls:
        if not l["hsn_sac"]:
            errs.append(f"L{l['sr']} missing HSN/SAC")
        if l["type"] == "goods" and (not l["uom"] or l["qty"] <= 0):
            errs.append(f"L{l['sr']} goods without qty/UOM")

    return errs


def check_pdf(path, rec):
    """Confirm the PDF text layer carries the invoice number and total."""
    try:
        out = subprocess.run(["pdftotext", "-layout", path, "-"],
                             capture_output=True, text=True, timeout=30).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    errs = []
    if rec["invoice_number"] not in out:
        errs.append("invoice number not in PDF text")
    if f"{rec['totals']['total']:,.2f}" not in out:
        errs.append("total not in PDF text")
    if rec["buyer"]["gstin"] and rec["buyer"]["gstin"] not in out:
        errs.append("buyer GSTIN not in PDF text")
    return errs


def main(outdir="out"):
    # JSON and PDF live in sibling folders; fall back to a flat layout
    files = sorted(glob.glob(os.path.join(outdir, "json", "*.json")))
    nested = bool(files)
    if not files:
        files = sorted(glob.glob(os.path.join(outdir, "*.json")))
    if not files:
        print(f"no invoices in {outdir}/")
        return 1
    bad = 0
    pdf_checked = pdf_bad = 0
    for p in files:
        errs = check(p)
        rec = json.load(open(p, encoding="utf-8"))
        pdf = (os.path.join(outdir, "pdf",
                            os.path.basename(p)[:-5] + ".pdf")
               if nested else p[:-5] + ".pdf")
        pe = check_pdf(pdf, rec)
        if pe is not None:
            pdf_checked += 1
            if pe:
                pdf_bad += 1
                errs += [f"PDF: {e}" for e in pe]
        if errs:
            bad += 1
            print(f"\nFAIL {os.path.basename(p)}")
            for e in errs:
                print(f"  - {e}")
    print(f"\n{len(files) - bad}/{len(files)} invoices passed all checks")
    if pdf_checked:
        print(f"{pdf_checked - pdf_bad}/{pdf_checked} PDFs carried the key fields")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "out"))
