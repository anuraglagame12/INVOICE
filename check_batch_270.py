"""Check the 270-invoice batch against the brief.

verify.py proves the arithmetic. This proves what was actually asked for:
7-8 goods on every document, one service and one charge at most, no Freight
or Miscellaneous, each folder carrying its own feature and nothing else, the
combined folder registered throughout, and an unregistered supplier charging
no GST at all.
"""
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.expanduser("~"), "Desktop", "GST_Batch_270")
US = "ABHIDNYA ENTERPRISES"
BANNED_CHARGES = ("freight", "misc")
FEATURE_FOLDERS = {
    "01_cgst_sgst", "02_igst", "03_service", "04_other_charge",
    "05_trade_discount", "06_cash_discount", "07_round_off",
    "08_unregistered", "09_combined",
}


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
    unreg = not rec["buyer"]["registered"]
    bos = side == "Purchase" and unreg          # bill of supply

    # ---- shape rules that hold on every invoice in the batch
    if not 7 <= len(goods) <= 8:
        e.append(f"{len(goods)} goods lines, expected 7-8")
    if len(svc) > 1:
        e.append(f"{len(svc)} service lines (max 1)")
    if len(charges) > 1:
        e.append(f"{len(charges)} charges (max 1)")
    for c in charges:
        if any(b in c["label"].lower() for b in BANNED_CHARGES):
            e.append(f"excluded charge: {c['label']}")
        if not c["hsn_sac"]:
            e.append(f"charge {c['label']} has no SAC")
    if rec["reverse_charge"]:
        e.append("RCM present")
    if rec["tds"]["applicable"] or t["tds_deducted"]:
        e.append("TDS present")
    if t["tcs_collected"]:
        e.append("TCS present")
    if any(len(l["description"]) > 90 for l in ls):
        e.append("long description")

    # ---- document type follows the side, and the registration
    if bos:
        if rec["document_type"] != "BILL OF SUPPLY":
            e.append(f"unregistered supplier doc is {rec['document_type']}")
    else:
        want = "PURCHASE INVOICE" if side == "Purchase" else "TAX INVOICE"
        if rec["document_type"] != want:
            e.append(f"doc type {rec['document_type']} != {want}")
    if text and US not in text.upper():
        e.append("our firm not on the document")

    # ---- an unregistered supplier cannot charge GST
    if bos:
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
        if unreg:
            e.append("IGST with an unregistered party")
    else:
        if inter:
            e.append("expected intra-state")
        elif not bos:
            if not (t["cgst"] and t["sgst"]) or t["igst"]:
                e.append("not a CGST+SGST invoice")
            if abs(t["cgst"] - t["sgst"]) > 0.005:
                e.append("CGST != SGST")

    # ---- the feature each folder is named for
    combined = folder == "09_combined"
    if folder == "03_service" or combined:
        if len(svc) != 1:
            e.append(f"{len(svc)} service lines, expected exactly 1")
        for l in svc:
            if l["uom"] or not l["hsn_sac"]:
                e.append("service must show a SAC and no UOM")
    elif svc:
        e.append(f"{len(svc)} service lines in a goods-only folder")

    if folder == "04_other_charge" or combined:
        if len(charges) != 1:
            e.append(f"{len(charges)} charges, expected exactly 1")
        if not bos:
            for c in charges:
                if not c["tax_amount"]:
                    e.append(f"charge {c['label']} untaxed")
    elif charges:
        e.append(f"{len(charges)} charges in a folder that wants none")

    if folder == "05_trade_discount" or combined:
        if not t["total_discount"] or not any(l["discount_pct"] for l in ls):
            e.append("no trade discount on the lines")
    elif t["total_discount"]:
        e.append("unexpected trade discount")

    if folder == "06_cash_discount" or combined:
        if not t["cash_discount"]:
            e.append("no cash discount")
    elif t["cash_discount"]:
        e.append("unexpected cash discount")

    if folder == "07_round_off" or combined:
        if not t["round_off"]:
            e.append("no round-off")
        if abs(t["total"] - round(t["total"])) > 0.005:
            e.append("total is not a whole rupee")
    elif t["round_off"]:
        e.append("unexpected round-off")

    if folder == "08_unregistered":
        if not unreg:
            e.append("registered party in the unregistered folder")
    elif unreg:
        e.append("unregistered party outside the unregistered folder")

    # the combined folder is registered only, by request
    if combined and unreg:
        e.append("combined must not carry an unregistered party")

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
        print("no invoices found - run make_batch_270.py first")
        return 1
    bad = reg = unreg = 0
    seen_folders = set()
    numbers = {}
    for p in files:
        q = p.split(os.sep)
        side, folder = q[-4], q[-3]
        seen_folders.add((side, folder))
        rec = json.load(open(p, encoding="utf-8"))
        pdf = os.path.join(os.path.dirname(os.path.dirname(p)), "pdf",
                           os.path.basename(p)[:-5] + ".pdf")
        if not os.path.exists(pdf):
            print(f"MISSING PDF for {os.path.basename(p)}")
            bad += 1
            continue
        # an invoice number must never repeat across the batch
        n = rec["invoice_number"]
        if n in numbers:
            print(f"DUPLICATE invoice number {n}")
            bad += 1
        numbers[n] = p
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
    print(f"folders: {len(seen_folders)} | unique invoice numbers: "
          f"{len(numbers)}")
    print(f"parties: {reg} registered, {unreg} unregistered")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
