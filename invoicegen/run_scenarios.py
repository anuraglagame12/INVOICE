"""Generate documents for ticked catalogue scenarios.

Each ticked scenario produces its whole chain, so a purchase-against-advance
yields both the advance and the purchase, linked to each other.
"""
import csv
import json
import os
import random
import re
import shutil
import tempfile
from decimal import Decimal

from . import catalogue as cat
from . import chains
from .model import money, rupees_in_words
from .render_voucher import render_voucher
from .scenarios import load_data

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_ledgers():
    with open(os.path.join(HERE, "data", "ledgers.json"),
              encoding="utf-8") as f:
        return json.load(f)


def _dec(o):
    """JSON cannot hold Decimal; dates and Lines need flattening too."""
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, dict):
        return {k: _dec(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_dec(v) for v in o]
    return o


def _slug(txn, n):
    """Filename: what the document is, numbered, safe for Windows."""
    kind = {"purchase_invoice": "Purchase", "sales_invoice": "Sale",
            "credit_note": "CreditNote", "debit_note": "DebitNote",
            "purchase_order": "PurchaseOrder", "sales_order": "SalesOrder",
            "receipt": "Receipt", "payment": "Payment",
            "contra": "Contra", "journal": "Journal"}[txn.kind]
    name = cat.label(txn.meta.get("chain_scenario", txn.sid))
    name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    if txn.meta.get("chain_total", 1) > 1:
        name += f"_step{txn.meta['chain_step']}"
    return f"{kind}_{n:03d}_{name}"[:110]


def _record(txn, seller):
    """Ground truth for one transaction."""
    m = txn.meta
    amount = m.get("total", m.get("amount", Decimal(0)))
    party = txn.party or {}

    rec = {
        "document_type": txn.title,
        "document_kind": txn.kind,
        "scenario_id": m.get("chain_scenario", txn.sid),
        "scenario": m.get("scenario_label", cat.label(txn.sid)),
        "number": txn.number,
        "date": txn.date.strftime("%d %b %Y"),
        "date_iso": txn.date.isoformat(),

        "chain": {
            "id": m.get("chain_id"),
            "step": m.get("chain_step", 1),
            "of": m.get("chain_total", 1),
            "links_to": m.get("links_to", []),
            "linked_from": m.get("linked_from", []),
        },

        "seller": {"name": seller["name"], "gstin": seller["gstin"],
                   "state": seller["state"]},
        "party": {
            "name": party.get("name"),
            "gstin": party.get("gstin"),
            "state": party.get("state"),
            "state_code": party.get("state_code"),
            "registered": bool(party.get("gstin")),
            "tally_ledger": party.get("tally_ledger"),
            "composition": bool(party.get("composition")),
            "sez": bool(party.get("sez")),
            "country": party.get("country"),
        } if party else None,
        "supply_type": ("inter-state" if txn.interstate else "intra-state"),

        "lines": [{
            "sr": i, "description": l.desc, "hsn_sac": l.code,
            "type": l.kind, "qty": float(l.qty), "uom": l.uom,
            "mrp": float(l.mrp), "discount_pct": float(l.discount_pct),
            "rate": float(l.rate), "taxable_value": float(l.taxable),
            "gst_rate": float(l.gst), "tax_amount": float(l.tax),
            "amount": float(l.amount),
        } for i, l in enumerate(txn.lines, 1)],

        "charges": [{"label": c.label, "amount": float(c.amount),
                     "gst_rate": float(c.gst), "tax_amount": float(c.tax),
                     "tally_ledger": c.ledger} for c in txn.charges],

        "amount": float(money(amount)),
        "details": _dec({k: v for k, v in m.items()
                         if k not in ("chain_id", "chain_step", "chain_total",
                                      "chain_scenario", "links_to",
                                      "linked_from", "scenario_label")}),

        "expected_voucher": {
            "voucher_type": {
                "purchase_invoice": "Purchase", "sales_invoice": "Sales",
                "credit_note": "Credit Note", "debit_note": "Debit Note",
                "purchase_order": "Purchase Order",
                "sales_order": "Sales Order", "receipt": "Receipt",
                "payment": "Payment", "contra": "Contra",
                "journal": "Journal"}[txn.kind],
            "voucher_date": txn.date.isoformat(),
            "party_ledger": party.get("tally_ledger"),
            "narration": txn.narration,
            "entries": txn.legs,
            "total_dr": float(txn.total_dr),
            "total_cr": float(txn.total_cr),
            "balanced": txn.balanced,
            "posts_to_tally": txn.posts_to_tally,
        },
        "has_pdf": cat.doc_kind(m.get("chain_scenario", txn.sid)) != "none"
                   or txn.kind != "journal",
    }
    if amount:
        rec["amount_in_words"] = rupees_in_words(amount)
    return rec


def _next_serial(pdf_dir, json_dir):
    top = 0
    for d in (pdf_dir, json_dir):
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            m = re.match(r"[A-Za-z]+_(\d+)_", fn)
            if m:
                top = max(top, int(m.group(1)))
    return top + 1


def run_scenarios(sids, count=1, seed=None, outdir="out", progress=None,
                  opts=None, formats=("pdf",), write_json=False,
                  patterns=("classic",)):
    """Generate `count` runs of each ticked scenario.

    Returns manifest rows. A scenario that needs a prior document emits its
    whole chain, so the file count exceeds `count * len(sids)`.
    """
    sids = [s for s in sids if s in cat.BY_ID]
    if not sids:
        sids = ["sale_goods_local"]

    # A PNG is a picture of the PDF, so the PDF is always drawn first. When
    # only PNG was asked for it goes to a temp folder and is deleted after.
    want_pdf = "pdf" in formats
    want_png = "png" in formats
    # Ground-truth JSON is written only when asked for - the test suites use
    # it, everyday use does not.
    json_dir = os.path.join(outdir, "json")
    png_dir = os.path.join(outdir, "png")
    pdf_dir = (os.path.join(outdir, "pdf") if want_pdf
               else tempfile.mkdtemp(prefix="pdftmp_"))
    os.makedirs(pdf_dir, exist_ok=True)
    if write_json:
        os.makedirs(json_dir, exist_ok=True)
    if want_png:
        os.makedirs(png_dir, exist_ok=True)

    rng = random.Random(seed)
    items, parties = load_data()
    ledgers = _load_ledgers()
    seller = parties["seller"]

    n = _next_serial(pdf_dir, png_dir if want_png else json_dir)
    chain_no = n
    rows = []
    jobs = [(s, i) for s in sids for i in range(count)]

    for done, (sid, _) in enumerate(jobs, 1):
        txns = chains.build_chain(sid, rng, items, parties, ledgers,
                                  n, chain_no, opts)
        chain_no += 1
        for txn in txns:
            rec = _record(txn, seller)
            slug = _slug(txn, n)
            rec["file"] = slug

            if txn.kind == "journal":
                rec["has_pdf"] = False       # journals have no document
            else:
                # Patterns are an invoice idea. Receipts, payments, contras
                # and reports keep their own single layout.
                pats = (patterns if txn.kind in INVOICE_KINDS
                        else ("classic",))
                from . import patterns as P
                multi = len(pats) > 1
                for pat in pats:
                    name = (slug if pat == "classic" and not multi
                            else "%s_%s" % (slug, P.tag(pat)))
                    pdf_path = os.path.join(pdf_dir, name + ".pdf")
                    _render(txn, seller, pdf_path, pat)
                    if want_png:
                        from .images import pdf_to_png
                        pdf_to_png(pdf_path, png_dir, name)
                    if pat != pats[0] and write_json:
                        extra = dict(rec)
                        extra["file"] = name
                        extra["pattern"] = pat
                        with open(os.path.join(json_dir, name + ".json"), "w",
                                  encoding="utf-8") as f:
                            json.dump(extra, f, indent=2)
                slug = (slug if txn.kind not in INVOICE_KINDS
                        or (pats[0] == "classic" and not multi)
                        else "%s_%s" % (slug, P.tag(pats[0])))
                rec["file"] = slug
                rec["pattern"] = pats[0]
                rec["has_pdf"] = True

            if write_json:
                with open(os.path.join(json_dir, slug + ".json"), "w",
                          encoding="utf-8") as f:
                    json.dump(rec, f, indent=2)

            rows.append({
                "file": slug,
                "scenario": rec["scenario"],
                "document": txn.title,
                "number": txn.number,
                "date": txn.date.isoformat(),
                "party": (txn.party or {}).get("name", ""),
                "amount": rec["amount"],
                "chain_id": txn.meta.get("chain_id", ""),
                "chain_step": f"{txn.meta.get('chain_step',1)}"
                              f"/{txn.meta.get('chain_total',1)}",
                "links_to": "|".join(l["number"]
                                     for l in txn.meta.get("links_to", [])),
                "has_pdf": rec["has_pdf"],
                "posts_to_tally": txn.posts_to_tally,
                "balanced": txn.balanced,
            })
            n += 1
        if progress:
            progress(done, len(jobs))

    man = os.path.join(outdir, "manifest.csv")
    fresh = not os.path.exists(man)
    with open(man, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if fresh:
            w.writeheader()
        w.writerows(rows)
    if not want_pdf:
        shutil.rmtree(pdf_dir, ignore_errors=True)
    return rows


INVOICE_KINDS = ("purchase_invoice", "sales_invoice", "credit_note",
                 "debit_note", "purchase_order", "sales_order")


def _render(txn, seller, path, pattern="classic"):
    """Draw whichever document this transaction is."""
    if txn.kind in ("receipt", "payment", "contra"):
        render_voucher(txn, seller, path)
    else:
        from .render_invoice import render_document
        render_document(txn, seller, path, pattern)
