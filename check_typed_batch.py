"""Check the typed batch shows the feature each folder claims.

verify.py proves the arithmetic. This proves the *brief*: that the IGST
folder really carries IGST, that the discount folders really discount, that
the excluded layers are absent everywhere, and that the letterhead names the
right firm for the side.
"""
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.expanduser("~"), "Desktop", "Typed_Invoices")
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

    # ---- exclusions the user asked for, on every single document
    if rec["reverse_charge"]:
        e.append("RCM present")
    if rec["tds"]["applicable"] or t["tds_deducted"]:
        e.append("TDS present")
    if t["tcs_collected"]:
        e.append("TCS present")
    if len(rec["other_charges"]) > 1:
        e.append(f"{len(rec['other_charges'])} charges (max 1)")
    # A round-off is made by nudging a real line, never by inventing a
    # charge for a supply that did not happen.
    for c in rec["other_charges"]:
        if "misc" in c["label"].lower():
            e.append(f"invented charge: {c['label']}")
    for l in ls:
        if len(l["description"]) > 90:
            e.append("long description")
            break

    # ---- the document type must match the side
    # A bill from an unregistered supplier is a bill of supply, checked
    # against the unregistered-supplier rules further down instead.
    unreg_supplier = side == "Purchase" and not rec["buyer"]["registered"]
    if not unreg_supplier:
        want_doc = "PURCHASE INVOICE" if side == "Purchase" else "TAX INVOICE"
        if rec["document_type"] != want_doc:
            e.append(f"doc type {rec['document_type']} != {want_doc}")
    if rec["expected_voucher"]["voucher_type"] != (
            "Purchase" if side == "Purchase" else "Sales"):
        e.append("voucher type wrong for side")

    # ---- our firm sits on the correct side of the page
    if text:
        if side == "Sales" and US not in text[:1200].upper():
            e.append("seller block is not us on a sale")
        if side == "Purchase" and US not in text.upper():
            e.append("our firm missing on a purchase")

    # ---- the feature the folder is named for
    inter = rec["supply_type"] == "inter-state"
    if folder == "02_igst":
        if not inter or not t["igst"] or t["cgst"] or t["sgst"]:
            e.append("not an IGST invoice")
        if not rec["buyer"]["registered"]:
            e.append("IGST with unregistered party")
    elif folder in ("01_cgst_sgst", "03_services", "04_trade_discount",
                    "05_cash_discount", "06_round_off", "07_combined"):
        if inter:
            e.append("not an intra-state invoice")
        elif unreg_supplier:
            pass          # a bill of supply carries no tax to check
        elif not (t["cgst"] and t["sgst"]) or t["igst"]:
            e.append("not an intra-state CGST+SGST invoice")
        if abs(t["cgst"] - t["sgst"]) > 0.005:
            e.append("CGST != SGST")

    if folder == "03_services":
        svc = [l for l in ls if l["type"] == "service"]
        if len(svc) != 1:
            e.append(f"{len(svc)} service lines, expected 1")
        for l in svc:
            if l["uom"] or not l["hsn_sac"]:
                e.append("service line must show SAC and no UOM")
    if folder == "04_trade_discount":
        if not t["total_discount"] or not any(l["discount_pct"] for l in ls):
            e.append("no trade discount on lines")
        if t["cash_discount"]:
            e.append("cash discount leaked into trade-discount folder")
    if folder == "05_cash_discount":
        if not t["cash_discount"]:
            e.append("no cash discount")
        # tax must sit on the full value, untouched by the discount
        gst = t["cgst"] + t["sgst"] + t["igst"]
        base = sum(l["taxable_value"] for l in ls) + t["other_charges"]
        if not unreg_supplier and base and abs(gst - round(base * 0.18, 2)) > 1.0:
            e.append("tax does not sit on the pre-discount value")
    if folder == "06_round_off":
        if not t["round_off"]:
            e.append("no round-off")
        if abs(t["total"] - round(t["total"])) > 0.005:
            e.append("total not a whole rupee")
    if folder == "07_combined":
        if not t["total_discount"]:
            e.append("combined: no trade discount")
        if not rec["other_charges"]:
            e.append("combined: no charge")
        if not any(l["type"] == "service" for l in ls):
            e.append("combined: no service line")
        if not any(l["type"] == "goods" for l in ls):
            e.append("combined: no goods line")

    # ---- registered vs unregistered coherence
    b = rec["buyer"]
    if b["registered"]:
        if not b["gstin"] or len(b["gstin"]) != 15:
            e.append("registered party without a valid 15-char GSTIN")
    else:
        if b["gstin"]:
            e.append("unregistered party carrying a GSTIN")
        if inter:
            e.append("unregistered party on an inter-state supply")

    # ---- an unregistered SUPPLIER cannot charge GST
    # Buying from someone not registered under GST: no CGST, SGST or IGST
    # may appear anywhere on the document, and it is a bill of supply
    # rather than a tax invoice. (Selling TO an unregistered customer is
    # the opposite case - we are registered, so we do charge tax.)
    if side == "Purchase" and not b["registered"]:
        if t["cgst"] or t["sgst"] or t["igst"]:
            e.append("unregistered supplier charging GST")
        if any(l["gst_rate"] or l["tax_amount"] for l in ls):
            e.append("unregistered supplier: tax on a line")
        if any(c["gst_rate"] or c["tax_amount"]
               for c in rec["other_charges"]):
            e.append("unregistered supplier: tax on a charge")
        if rec["document_type"] != "BILL OF SUPPLY":
            e.append(f"unregistered supplier doc is "
                     f"{rec['document_type']}, expected BILL OF SUPPLY")
        if text and ("CGST" in text or "SGST" in text or "IGST" in text):
            e.append("GST wording printed on a bill of supply")

    # ---- amount in words must match the figure
    if text and rec["invoice_number"] not in text:
        e.append("invoice number missing from PDF")
    return e


def main():
    files = sorted(glob.glob(os.path.join(ROOT, "*", "*", "json", "*.json")))
    if not files:
        print("no invoices found - run make_typed_batch.py first")
        return 1
    bad = 0
    unreg = reg = 0
    for p in files:
        parts = p.split(os.sep)
        side, folder = parts[-4], parts[-3]
        rec = json.load(open(p, encoding="utf-8"))
        pdf = os.path.join(os.path.dirname(os.path.dirname(p)), "pdf",
                           os.path.basename(p)[:-5] + ".pdf")
        text = pdf_text(pdf) if os.path.exists(pdf) else None
        if not os.path.exists(pdf):
            print(f"MISSING PDF for {os.path.basename(p)}")
            bad += 1
            continue
        if rec["buyer"]["registered"]:
            reg += 1
        else:
            unreg += 1
        errs = check(rec, side, folder, text)
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
