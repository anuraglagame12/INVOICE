"""Check the by-type batch shows the feature each folder claims.

verify.py proves the arithmetic. This proves the brief: one service line and
one charge at most, each folder carrying its own feature, the excluded layers
absent, and an unregistered supplier charging no GST.
"""
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.expanduser("~"), "Desktop", "GST_Invoices_ByType")
US = "ABHIDNYA ENTERPRISES"


def pdf_text(path):
    try:
        return subprocess.run(["pdftotext", "-layout", path, "-"],
                              capture_output=True, text=True,
                              timeout=30).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def check(rec, side, folder, text):
    t, ls = rec["totals"], rec["lines"]
    e = []
    svc = [l for l in ls if l["type"] == "service"]
    goods = [l for l in ls if l["type"] == "goods"]
    charges = rec["other_charges"]
    unreg_supplier = side == "Purchase" and not rec["buyer"]["registered"]

    # ---- caps that apply to every invoice in the batch
    if len(svc) > 1:
        e.append(f"{len(svc)} service lines (max 1)")
    if len(charges) > 1:
        e.append(f"{len(charges)} charges (max 1)")
    for c in charges:
        if "misc" in c["label"].lower():
            e.append(f"invented charge: {c['label']}")

    # ---- exclusions
    if rec["reverse_charge"]:
        e.append("RCM present")
    if rec["tds"]["applicable"] or t["tds_deducted"]:
        e.append("TDS present")
    if t["tcs_collected"]:
        e.append("TCS present")
    if any(len(l["description"]) > 90 for l in ls):
        e.append("long description")

    # ---- document type / side
    if unreg_supplier:
        if rec["document_type"] != "BILL OF SUPPLY":
            e.append(f"unregistered supplier doc is {rec['document_type']}")
    else:
        want = "PURCHASE INVOICE" if side == "Purchase" else "TAX INVOICE"
        if rec["document_type"] != want:
            e.append(f"doc type {rec['document_type']} != {want}")
    if text and US not in text.upper():
        e.append("our firm not on the document")

    # ---- an unregistered supplier cannot charge GST
    if unreg_supplier:
        if t["cgst"] or t["sgst"] or t["igst"]:
            e.append("unregistered supplier charging GST")
        if any(l["gst_rate"] or l["tax_amount"] for l in ls):
            e.append("unregistered supplier: tax on a line")
        if text and any(w in text for w in ("CGST", "SGST", "IGST")):
            e.append("GST wording on a bill of supply")

    # ---- supply type
    inter = rec["supply_type"] == "inter-state"
    if folder == "02_igst":
        if not inter or not t["igst"] or t["cgst"] or t["sgst"]:
            e.append("not an IGST invoice")
        if not rec["buyer"]["registered"]:
            e.append("IGST with an unregistered party")
    else:
        if inter:
            e.append("expected intra-state")
        elif not unreg_supplier:
            if not (t["cgst"] and t["sgst"]) or t["igst"]:
                e.append("not a CGST+SGST invoice")
            if abs(t["cgst"] - t["sgst"]) > 0.005:
                e.append("CGST != SGST")

    # ---- the feature the folder is named for
    if folder in ("03_service", "07_combined"):
        if len(svc) != 1:
            e.append(f"{len(svc)} service lines, expected exactly 1")
        for l in svc:
            if l["uom"] or not l["hsn_sac"]:
                e.append("service must show a SAC and no UOM")
        if not goods:
            e.append("no goods line alongside the service")
    if folder in ("04_other_charge", "07_combined"):
        if len(charges) != 1:
            e.append(f"{len(charges)} charges, expected exactly 1")
        for c in charges:
            if not c["hsn_sac"]:
                e.append(f"charge {c['label']} has no SAC")
            if not unreg_supplier and not c["tax_amount"]:
                e.append(f"charge {c['label']} untaxed")
    if folder in ("05_discount", "07_combined"):
        if not t["total_discount"] or not any(l["discount_pct"] for l in ls):
            e.append("no trade discount on the lines")
        if not t["cash_discount"]:
            e.append("no cash discount")
    if folder in ("06_round_off", "07_combined"):
        if not t["round_off"]:
            e.append("no round-off")
        if abs(t["total"] - round(t["total"])) > 0.005:
            e.append("total is not a whole rupee")

    # ---- party coherence
    b = rec["buyer"]
    if b["registered"]:
        if not b["gstin"] or len(b["gstin"]) != 15:
            e.append("registered party without a valid GSTIN")
    elif b["gstin"]:
        e.append("unregistered party carrying a GSTIN")

    if text and rec["invoice_number"] not in text:
        e.append("invoice number missing from the PDF")
    return e


def main():
    files = sorted(glob.glob(os.path.join(ROOT, "*", "*", "json", "*.json")))
    if not files:
        print("no invoices found - run make_typed_v2.py first")
        return 1
    bad = reg = unreg = 0
    for p in files:
        q = p.split(os.sep)
        side, folder = q[-4], q[-3]
        rec = json.load(open(p, encoding="utf-8"))
        pdf = os.path.join(os.path.dirname(os.path.dirname(p)), "pdf",
                           os.path.basename(p)[:-5] + ".pdf")
        if not os.path.exists(pdf):
            print(f"MISSING PDF for {os.path.basename(p)}")
            bad += 1
            continue
        if rec["buyer"]["registered"]:
            reg += 1
        else:
            unreg += 1
        errs = check(rec, side, folder, pdf_text(pdf))
        if errs:
            bad += 1
            print(f"\nFAIL {side}/{folder}/{os.path.basename(p)}")
            for x in errs:
                print(f"  - {x}")
    print(f"\n{len(files) - bad}/{len(files)} invoices match the brief")
    print(f"parties: {reg} registered, {unreg} unregistered")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
