"""Tick one scenario, check you get what that scenario says it is.

check_docs.py proves each document is internally consistent. This proves the
right document appeared: tick "Purchase of goods - interstate" and you should
get a purchase, of goods, with IGST - not a sale, not services, not CGST.

    python check_scenarios.py                     # all 102
    python check_scenarios.py pur_rcm sale_export
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def expectations(sid, tags, doc_kind):
    """What must be true of the document this scenario produces.

    Each entry is (description, predicate over the last document's record).
    Only the FINAL document of a chain is judged - the earlier steps are
    supporting documents, checked separately by their own scenario.
    """
    checks = []

    # ---- which side of the business
    if "purchase" in tags:
        checks.append(("is a purchase document", lambda r: r["document_kind"]
                       in ("purchase_invoice", "purchase_order",
                           "debit_note", "credit_note")))
    if "sales" in tags:
        checks.append(("is a sales document", lambda r: r["document_kind"]
                       in ("sales_invoice", "sales_order",
                           "credit_note", "debit_note")))
    if "receipt" in tags:
        checks.append(("is a receipt", lambda r: r["document_kind"]
                       in ("receipt",)))
    if "payment" in tags:
        checks.append(("is a payment", lambda r: r["document_kind"]
                       in ("payment",)))
    if "contra" in tags:
        checks.append(("is a contra", lambda r: r["document_kind"] == "contra"))
    if "journal" in tags:
        checks.append(("is a journal", lambda r: r["document_kind"]
                       == "journal"))

    # ---- document type
    if doc_kind == "order":
        checks.append(("is an order", lambda r: r["document_kind"]
                       in ("purchase_order", "sales_order")))
    if "credit_note" in tags:
        checks.append(("is a credit note", lambda r: r["document_kind"]
                       == "credit_note"))
    if "debit_note" in tags:
        checks.append(("is a debit note", lambda r: r["document_kind"]
                       == "debit_note"))

    # ---- place of supply
    if "intra" in tags:
        checks.append(("is intra-state", lambda r: r["supply_type"]
                       == "intra-state"))
    if "inter" in tags:
        checks.append(("is inter-state", lambda r: r["supply_type"]
                       == "inter-state"))

    # ---- what is being sold
    if "goods" in tags:
        checks.append(("has goods lines", lambda r: any(
            l["type"] == "goods" for l in r["lines"])))
    if "services" in tags and "expense" not in tags:
        checks.append(("has service lines", lambda r: any(
            l["type"] == "service" for l in r["lines"])))

    # ---- tax treatment
    if "rcm" in tags:
        checks.append(("is reverse charge", lambda r: r["details"]["rcm"]))
        checks.append(("collects no tax", lambda r: abs(
            r["details"]["total"] - r["details"]["taxable"]
            - r["details"]["charges"]
            - r["details"]["round_off"]) < 0.02))
    if any(k in tags for k in ("export", "sez", "composition",
                               "unregistered_party")):
        checks.append(("carries no GST", lambda r: r["details"]["tax"] == 0))

    # ---- charges and layers
    for tag, label in (("freight", "Freight"), ("packing", "Packing"),
                       ("insurance", "Insurance"), ("loading", "Loading")):
        if tag in tags:
            checks.append(("has a %s charge" % label.lower(),
                           lambda r, L=label: any(
                               L in c["label"] for c in r["charges"])))
    if "trade_discount" in tags:
        checks.append(("has a trade discount", lambda r: any(
            l["discount_pct"] > 0 for l in r["lines"])))
    if "cash_discount" in tags:
        checks.append(("has a cash discount",
                       lambda r: r["details"].get("cash_discount", 0) > 0))
    if "tds" in tags:
        checks.append(("deducts TDS",
                       lambda r: r["details"].get("tds_amount", 0) > 0))
    if "tcs" in tags:
        checks.append(("collects TCS",
                       lambda r: r["details"].get("tcs", 0) > 0))
    if "advance" in tags:
        checks.append(("adjusts an advance",
                       lambda r: r["details"].get("advance", 0) > 0))
    if "import" in tags:
        checks.append(("party is overseas",
                       lambda r: bool((r["party"] or {}).get("country"))))
    if "unregistered_party" in tags:
        checks.append(("party has no GSTIN",
                       lambda r: not (r["party"] or {}).get("gstin")))
    if "composition" in tags:
        checks.append(("party is a composition dealer",
                       lambda r: (r["party"] or {}).get("composition")))
    if "sez" in tags:
        checks.append(("party is an SEZ unit",
                       lambda r: (r["party"] or {}).get("sez")))
    if "against_order" in tags:
        checks.append(("cites the order",
                       lambda r: bool(r["details"].get("against_order"))))
    if "against_bill" in tags:
        checks.append(("settles a bill",
                       lambda r: bool(r["details"].get("bills"))))
    if "multi_bill" in tags:
        checks.append(("settles several bills",
                       lambda r: len(r["details"].get("bills") or []) > 1))
    if "partial" in tags:
        checks.append(("pays only part of the bill", lambda r: any(
            b["amount"] < b.get("bill_total", b["amount"]) - 0.01
            for b in (r["details"].get("bills") or []))))
    if "cheque" in tags:
        checks.append(("is by cheque",
                       lambda r: r["details"].get("mode") == "Cheque"))
    if "capital" in tags:
        checks.append(("posts to a fixed asset", lambda r: any(
            e["ledger"] in ("Office Equipment", "Plant and Machinery",
                            "Furniture and Fixtures",
                            "Computers and Peripherals", "Motor Vehicles",
                            "Electrical Installations")
            for e in r["expected_voucher"]["entries"])))
    return checks


def chain_checks(sid, chain, recs):
    """A chained scenario must produce its supporting document, linked."""
    errs = []
    if len(chain) < 2:
        return errs
    if len(recs) != len(chain):
        errs.append("expected %d documents, got %d" % (len(chain), len(recs)))
        return errs
    last = recs[-1]
    if not last["chain"]["links_to"]:
        errs.append("final document does not reference the earlier one")
    parties = {(r["party"] or {}).get("tally_ledger")
               for r in recs if r.get("party")}
    if len(parties) > 1:
        errs.append("chain spans %d different parties" % len(parties))
    numbers = {r["number"] for r in recs}
    for link in last["chain"]["links_to"]:
        if link["number"] not in numbers:
            errs.append("references %s, which is not in the batch"
                        % link["number"])
    return errs


def main(only=None):
    from invoicegen import catalogue as cat, chains
    from invoicegen.run_scenarios import run_scenarios

    sids = only or cat.ALL_IDS
    unknown = [s for s in sids if s not in cat.BY_ID]
    if unknown:
        print("unknown scenario(s):", ", ".join(unknown))
        return 2

    tmp = "_scencheck"
    passed = failed = 0
    print("checking %d scenario(s)..." % len(sids))

    for sid in sids:
        shutil.rmtree(tmp, ignore_errors=True)
        rows = run_scenarios([sid], count=1, seed=17, outdir=tmp, write_json=True)
        recs = [json.load(open(os.path.join(tmp, "json", r["file"] + ".json"),
                               encoding="utf-8")) for r in rows]
        chain = chains.CHAINS.get(sid, [sid])

        errs = chain_checks(sid, chain, recs)
        for desc, ok in expectations(sid, cat.tags(sid), cat.doc_kind(sid)):
            try:
                if not ok(recs[-1]):
                    errs.append("not " + desc)
            except Exception as e:
                errs.append("could not check '%s' (%s)" % (desc, e))

        if errs:
            failed += 1
            print("\nFAIL  %s" % cat.label(sid))
            print("      (%s)" % sid)
            for e in errs:
                print("        - %s" % e)
        else:
            passed += 1

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d/%d scenarios produced what they promise"
          % (passed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
