"""Check every generated document by what is actually DRAWN on the page.

pdftotext reflows the two-column footer, so parsing its output gives false
failures. This instead intercepts the drawing calls while the documents are
being generated, groups them by baseline, and reads the totals block by
position - the way the eye does.

That is the check that would have caught the cash-discount bug: it verifies
the printed page adds up on its own terms, independently of the data.

    python check_docs.py                          # every scenario
    python check_docs.py pur_cash_disc sale_tcs   # named scenarios
"""
import json
import os
import re
import shutil
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MONEY = re.compile(r"^\(?-?[\d,]+\.\d{2}\)?$")
TOL = 0.02

# filled while generating: file stem -> [(y, x, text), ...]
DRAWN = {}
CURRENT = [None]


def num(s):
    return float(s.replace(",", "").replace("(", "-").replace(")", ""))


def install_probe():
    """Record every string drawn, tagged with the file being written."""
    from reportlab.pdfgen import canvas as pc

    o_init = pc.Canvas.__init__
    o_ds = pc.Canvas.drawString
    o_drs = pc.Canvas.drawRightString
    o_dcs = pc.Canvas.drawCentredString

    def init(self, filename, *a, **k):
        CURRENT[0] = os.path.splitext(os.path.basename(str(filename)))[0]
        DRAWN.setdefault(CURRENT[0], [])
        return o_init(self, filename, *a, **k)

    def rec(self, x, y, t):
        if CURRENT[0]:
            DRAWN[CURRENT[0]].append((round(y, 1), round(x, 1), t))

    def ds(self, x, y, t, *a, **k):
        rec(self, x, y, t)
        return o_ds(self, x, y, t, *a, **k)

    def drs(self, x, y, t, *a, **k):
        rec(self, x, y, t)
        return o_drs(self, x, y, t, *a, **k)

    def dcs(self, x, y, t, *a, **k):
        rec(self, x, y, t)
        return o_dcs(self, x, y, t, *a, **k)

    pc.Canvas.__init__ = init
    pc.Canvas.drawString = ds
    pc.Canvas.drawRightString = drs
    pc.Canvas.drawCentredString = dcs


def totals_rows(drawn):
    """Label -> figure for the right-hand totals column."""
    anchor = [(y, x) for y, x, t in drawn
              if t.startswith("Amount Payable") or t.startswith("Estimated")]
    if not anchor:
        return {}
    x_min = min(x for _y, x in anchor) - 2
    # The item table's Tax/Amount columns share the same x band, so also cut
    # vertically: the totals block starts at "Taxable Amount".
    tops = [y for y, x, t in drawn
            if t == "Taxable Amount" and x >= x_min]
    y_max = max(tops) + 1 if tops else 10 ** 6
    band = defaultdict(list)
    for y, x, t in drawn:
        if x >= x_min and y <= y_max:
            band[y].append((x, t))
    out = {}
    for y in sorted(band, reverse=True):
        cells = [t for _x, t in sorted(band[y])]
        label = next((c for c in cells if not MONEY.match(c)), None)
        figure = next((c for c in cells if MONEY.match(c)), None)
        if label and figure is not None:
            out.setdefault(label.rstrip(":").strip(), num(figure))
    return out


def check(rec, drawn):
    errs = []
    kind = rec.get("document_kind", "")
    det = rec.get("details", {})
    flat = [t for _y, _x, t in drawn]
    page = " ".join(flat)

    if rec.get("number") and rec["number"] not in page:
        errs.append("document number not on the page")
    if rec.get("document_type") and rec["document_type"] not in flat:
        errs.append("title not on the page")
    party = rec.get("party") or {}
    if party.get("gstin") and party["gstin"] not in page:
        errs.append("party GSTIN not on the page")

    # A document is drawn from the point of view of whoever issued it. We
    # raise sales invoices and purchase orders, so those name the other side
    # as Customer / Supplier. A purchase bill was issued to us BY the
    # supplier, so it must head with THEIR name and call us the customer.
    if kind == "purchase_order":
        if "Supplier Details:" not in flat:
            errs.append("purchase order not labelled 'Supplier Details'")
    elif kind in ("purchase_invoice", "sales_invoice"):
        if "Customer Details:" not in flat:
            errs.append("invoice not labelled 'Customer Details'")
    if kind == "purchase_invoice":
        # the letterhead is the topmost string on the left of page 1
        # the letterhead is the topmost left-hand string, ignoring the
        # reverse-charge banner that sits above it
        # skip the banner and the small "Seller:" / "Buyer:" caption that
        # sit above the name - the letterhead is the name itself
        skip = ("REVERSE CHARGE", "Seller:", "Buyer (")
        top = sorted(((y, x, t) for y, x, t in drawn
                      if x < 200 and not t.startswith(skip)),
                     key=lambda r: -r[0])
        head = top[0][2] if top else ""
        supplier = (rec.get("party") or {}).get("name", "")
        if head.startswith("ABHIDNYA"):
            errs.append("purchase bill headed by us, not by the supplier")
        elif supplier and supplier[:18] not in head:
            errs.append("purchase bill headed '%s', expected the supplier"
                        % head[:32])

    if kind in ("purchase_invoice", "sales_invoice", "credit_note",
                "debit_note", "purchase_order", "sales_order"):
        errs += _totals(rec, det, totals_rows(drawn), kind, page)
    elif kind in ("receipt", "payment", "contra"):
        amt = det.get("amount")
        if amt and ("Rs " + format(float(amt), ",.2f")) not in page:
            errs.append("voucher amount not printed")
        for b in (det.get("bills") or []):
            if b["ref"] not in page:
                errs.append("settled bill %s not printed" % b["ref"])
                break
    return errs


def _totals(rec, det, rows, kind, page):
    errs = []
    if not rows:
        return ["no totals block found"]
    total = rows.get("Amount Payable", rows.get("Estimated Value"))
    if total is None:
        return ["no payable/estimated total printed"]

    parts = rows.get("Taxable Amount")
    if parts is None:
        return ["no taxable amount printed"]

    # "Total Discount" is informational (it restates the line discounts) and
    # under reverse charge the tax is shown for reporting but NOT collected,
    # so neither belongs in the payable total.
    SKIP = {"Taxable Amount", "Amount Payable", "Estimated Value", "Total",
            "Total Discount", "Trade Discount (already deducted)",
            "Tax under RCM (by recipient)"}
    for label, value in rows.items():
        if label in SKIP:
            continue
        if label.startswith("Less:"):
            parts -= abs(value)
        else:
            parts += value

    if abs(parts - total) > 0.5:
        errs.append("printed parts sum to %s but the total says %s (gap %s)"
                    % (format(parts, ",.2f"), format(total, ",.2f"),
                       format(parts - total, ",.2f")))

    if det.get("total") and abs(total - float(det["total"])) > TOL:
        errs.append("printed total %s != data total %s"
                    % (format(total, ",.2f"),
                       format(float(det["total"]), ",.2f")))

    for i, l in enumerate(rec.get("lines", []), 1):
        if format(l["taxable_value"], ",.2f") not in page:
            errs.append("line %d taxable value not printed" % i)
            break

    if kind in ("credit_note", "debit_note"):
        orig = (det.get("original_invoice") or {}).get("number")
        if orig and orig not in page:
            errs.append("note does not cite its original invoice")

    if kind in ("purchase_order", "sales_order") and "Amount Payable" in rows:
        errs.append("order printed as a demand for payment")
    return errs


def main(only=None):
    install_probe()
    from invoicegen import catalogue as cat
    from invoicegen.run_scenarios import run_scenarios

    sids = only or cat.ALL_IDS
    unknown = [s for s in sids if s not in cat.BY_ID]
    if unknown:
        print("unknown scenario(s):", ", ".join(unknown))
        return 2

    tmp = "_doccheck"
    shutil.rmtree(tmp, ignore_errors=True)
    print("generating %d scenario(s)..." % len(sids))
    rows = run_scenarios(sids, count=1, seed=11, outdir=tmp, write_json=True)

    checked = failed = skipped = 0
    for r in rows:
        if not r.get("has_pdf"):
            skipped += 1
            continue
        stem = r["file"]
        drawn = DRAWN.get(stem)
        if not drawn:
            continue
        rec = json.load(open(os.path.join(tmp, "json", stem + ".json"),
                             encoding="utf-8"))
        checked += 1
        errs = check(rec, drawn)
        if errs:
            failed += 1
            print("\nFAIL  %s" % rec.get("scenario", stem))
            print("      %s.pdf" % stem)
            for e in errs:
                print("        - %s" % e)

    print("\n%d/%d printed documents are consistent"
          % (checked - failed, checked))
    if skipped:
        print("%d journal entries skipped (no document by design)" % skipped)
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
