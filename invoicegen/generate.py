"""Batch driver: options in, PDFs + ground-truth JSON + manifest out."""
import csv
import json
import os
import re
import shutil
import tempfile

from .model import Charge, build, rupees_in_words, to_record
from .render import render
from .scenarios import apply_layers, generate as build_invoices, ALL_OPTS

import random


def run(opts, count=20, seed=None, outdir="out", progress=None,
        start_at=None, detail=None, formats=("pdf",), write_json=False,
        patterns=("classic",), seen=None):
    """Generate `count` invoices into `outdir`. Returns the manifest rows.

    `start_at` fixes the first invoice number; when omitted it continues past
    whatever is already in `outdir`, so generating twice into the same folder
    adds to the batch instead of overwriting it.
    """
    # PDFs and ground-truth JSON live in separate folders so a parser can be
    # pointed at pdf/ without seeing the answers
    # A PNG is a picture of the PDF, so the PDF is always drawn first. When
    # only PNG was asked for it goes to a temp folder and is deleted after.
    want_pdf = "pdf" in formats
    want_png = "png" in formats
    json_dir = os.path.join(outdir, "json")
    png_dir = os.path.join(outdir, "png")
    pdf_dir = (os.path.join(outdir, "pdf") if want_pdf
               else tempfile.mkdtemp(prefix="pdftmp_"))
    os.makedirs(pdf_dir, exist_ok=True)
    if write_json:
        os.makedirs(json_dir, exist_ok=True)
    if want_png:
        os.makedirs(png_dir, exist_ok=True)
    if start_at is None:
        start_at = _next_serial(pdf_dir)
    invoices, seller = build_invoices(opts, count=count, seed=seed,
                                      start_at=start_at, detail=detail,
                                      seen=seen)
    rng = random.Random((seed or 0) + 7919)
    _, parties = _load_parties()

    rows = []
    for n, inv in enumerate(invoices, 1):
        t = build(inv)
        # TDS/TCS depend on the taxable value, so apply then recompute
        if apply_layers(inv, t, rng, set(opts), parties):
            t = build(inv)
        # "roundoff" adds a real miscellaneous charge sized so the invoice
        # lands near half a rupee, giving a clearly visible round-off
        if inv.pop("force_roundoff", False):
            frac = t["gross"] - int(t["gross"])
            inv["charges"].append(Charge(
                "Miscellaneous Charges", _to_half(frac),
                "Miscellaneous Income"))
            t = build(inv)
        t["words"] = rupees_in_words(t["total"])

        rec = to_record(inv, t, seller)
        # name the file after what the document contains, numbered in
        # sequence, and never collide with a file already in the folder
        slug = describe(rec, t, inv) % (start_at + n - 1)
        slug = _unique(pdf_dir, json_dir, slug)
        rec["file"] = slug
        # A purchase bill was issued to us BY the supplier, so their name
        # heads the page and ours moves into the customer block.
        if inv.get("side") == "purchase":
            head, inv["buyer"] = _swap_roles(seller, inv["buyer"])
        else:
            head = seller
        # Draw the invoice once per ticked layout - same numbers, different
        # appearance. Classic keeps the plain filename.
        from . import patterns as P
        multi = len(patterns or ("classic",)) > 1
        for pat in (patterns or ("classic",)):
            # name every layout when several were asked for, so the set is
            # obvious in the folder; a lone Classic keeps the plain name
            name = (slug if pat == "classic" and not multi
                    else "%s_%s" % (slug, P.tag(pat)))
            pdf_path = os.path.join(pdf_dir, name + ".pdf")
            if pat == "classic":
                render(inv, t, head, pdf_path)
            else:
                from . import patterns as P
                P.draw(pat, inv, t, head, pdf_path)
            if want_png:
                from .images import pdf_to_png
                pdf_to_png(pdf_path, png_dir, name)
        first = (patterns or ("classic",))[0]
        if first != "classic" or multi:
            slug = "%s_%s" % (slug, P.tag(first))
            rec["file"] = slug
        if write_json:
            with open(os.path.join(json_dir, f"{slug}.json"), "w",
                      encoding="utf-8") as f:
                json.dump(rec, f, indent=2)

        rows.append({
            "file": slug,
            "invoice_number": inv["number"],
            "invoice_date": inv["date_iso"],
            "buyer": rec["buyer"]["name"],
            "buyer_gstin": rec["buyer"]["gstin"] or "",
            "supply_type": rec["supply_type"],
            "gst_rates": "|".join(str(r) for r in t["rates"]),
            "line_count": t["count"],
            "taxable": rec["totals"]["taxable_amount"],
            # taxable_amount is the line total only; charges are taxed at
            # their own rate, so record the base the tax figures actually
            # sit on or the columns cannot be reconciled.
            "tax_base": round(
                float(rec["totals"]["taxable_amount"])
                + float(rec["totals"]["other_charges"]), 2),
            "cgst": rec["totals"]["cgst"],
            "sgst": rec["totals"]["sgst"],
            "igst": rec["totals"]["igst"],
            "cess": rec["totals"]["cess"],
            "charges": rec["totals"]["other_charges"],
            "tds": rec["totals"]["tds_deducted"],
            "tcs": rec["totals"]["tcs_collected"],
            "total": rec["totals"]["total"],
            "reverse_charge": rec["reverse_charge"],
            "post_ready": rec["expected_post_ready"],
            "tags": "|".join(inv["tags"]),
        })
        if progress:
            progress(n, len(invoices))

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


def describe(rec, t, inv):
    """Build a filename that says what the document actually contains.

    Mirrors how a person would label these by hand:
        Invoice_007_Single_goods_GST_18
        Invoice_012_Goods_service_freight
        CreditNote_003_Mixed_12_18_IGST
    """
    doc = {"TAX INVOICE": "Invoice", "PURCHASE INVOICE": "Purchase",
           "CREDIT NOTE": "CreditNote", "DEBIT NOTE": "DebitNote",
           "PURCHASE ORDER": "PurchaseOrder",
           "SALES ORDER": "SalesOrder"}.get(rec["document_type"], "Document")
    bits = []

    kinds = {l["type"] for l in rec["lines"]}
    goods, svc = "goods" in kinds, "service" in kinds
    rates = [r for r in rec["totals"]["gst_rates_present"] if r > 0]
    exempt = any(l["exempt"] for l in rec["lines"])

    # what is being sold
    if goods and svc:
        bits.append("Goods_service")
    elif svc:
        sacs = sorted({l["hsn_sac"] for l in rec["lines"]
                       if l["type"] == "service"})
        bits.append("Single_service_SAC_" + sacs[0] if len(sacs) == 1
                    else "Services")
    elif len(rates) == 1:
        bits.append(f"Single_goods_GST_{rates[0]:g}")
    else:
        bits.append("Goods")

    # tax shape, when it is the interesting part
    if len(rates) > 1:
        bits.append("Mixed_" + "_".join(f"{r:g}" for r in rates))
    if exempt:
        bits.append("Tax_free_taxable" if rates else "Tax_free")

    # charges and extras, in the order a reader would expect
    labels = {"Freight Charges": "freight", "Packing Charges": "P",
              "Insurance Charges": "F", "Loading & Unloading": "loading",
              "Miscellaneous Charges": "misc"}
    for c in rec["other_charges"]:
        tag = labels.get(c["label"])
        if tag:
            bits.append(tag)
    if rec["reverse_charge"]:
        bits.append("RCM")
    if rec["tds"]["applicable"]:
        bits.append("TDS")
    if rec["totals"]["tcs_collected"]:
        bits.append("TCS")
    if rec["totals"]["cess"]:
        bits.append("cess")
    if "scanned" in rec["scenario_tags"]:
        bits.append("scanned")

    # supply type only when it is inter-state, since intra is the norm
    if rec["supply_type"] == "inter-state":
        bits.append("IGST")

    name = "_".join(bits)
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
    # Windows tolerates long paths poorly; trim on a separator so the name
    # still ends on a whole word rather than mid-token
    limit = 74
    if len(name) > limit:
        cut = name[:limit].rsplit("_", 1)[0]
        name = (cut or name[:limit]) + "_etc"
    return f"{doc}_%03d_{name}"


def _unique(pdf_dir, json_dir, slug):
    """Append a suffix if this exact name is already taken."""
    base, i = slug, 2
    while (os.path.exists(os.path.join(pdf_dir, base + ".pdf"))
           or os.path.exists(os.path.join(json_dir, base + ".json"))):
        base = f"{slug}_{i}"
        i += 1
    return base


def _next_serial(pdf_dir):
    """Highest invoice serial already in the folder, so a second run in the
    same folder continues the series rather than overwriting it."""
    import re
    top = 0
    if os.path.isdir(pdf_dir):
        for fn in os.listdir(pdf_dir):
            # Invoice_007_... / CreditNote_012_...
            m = re.match(r"(?:Invoice|CreditNote|DebitNote|PurchaseOrder"
                         r"|SalesOrder|Document)_(\d+)_", fn)
            if m:
                top = max(top, int(m.group(1)))
    return top + 1


def _to_half(frac):
    """How much to add so a value ending in `frac` ends near .46 instead."""
    from decimal import Decimal
    target = Decimal("0.46")
    d = target - Decimal(str(frac))
    return d if d > 0 else d + 1


def _swap_roles(seller, party):
    """Return (letterhead, party) for a bill issued to us by `party`."""
    letterhead = {
        "name": party.get("name", ""), "gstin": party.get("gstin", ""),
        "state": party.get("state", ""), "addr": party.get("bill", []),
        "mobile": party.get("phone", ""),
        "bank": {"name": "-", "account": "-", "ifsc": "-", "branch": "-"},
    }
    us = {
        "name": seller["name"], "gstin": seller["gstin"],
        "state": seller["state"], "bill": seller["addr"],
        "ship": seller["addr"], "phone": seller.get("mobile"),
    }
    return letterhead, us


def _load_parties():
    from .scenarios import load_data
    return load_data()


def main(argv=None):
    import argparse
    from .scenarios import PANELS, DEFAULT_OPTS

    p = argparse.ArgumentParser(
        prog="invoicegen",
        description="Generate GST tax invoices with Tally-posting ground truth.")
    p.add_argument("-n", "--count", type=int, default=20,
                   help="how many invoices (default 20)")
    p.add_argument("-s", "--seed", type=int, default=None,
                   help="random seed; same seed gives the same batch")
    p.add_argument("-o", "--outdir", default="out", help="output directory")
    p.add_argument("--opts", default=None,
                   help="comma-separated option ids (default: a sensible set)")
    p.add_argument("--all", action="store_true",
                   help="enable every option")
    p.add_argument("--list", action="store_true",
                   help="list every option id and exit")
    p.add_argument("--json", action="store_true",
                   help="also write the ground-truth JSON (used by the tests)")
    p.add_argument("--png", action="store_true",
                   help="also save each document as a PNG image")
    p.add_argument("--scenarios", default=None,
                   help="comma-separated Tally scenario ids, or 'all'")
    p.add_argument("--patterns", default=None,
                   help="comma-separated layout ids, or 'all'")
    p.add_argument("--list-scenarios", action="store_true",
                   help="list every Tally scenario id and exit")
    p.add_argument("--list-patterns", action="store_true",
                   help="list every layout id and exit")
    a = p.parse_args(argv)

    if a.list_scenarios:
        from . import catalogue as cat
        for _key, title, items in cat.by_category():
            print()
            print(title)
            for sid, label, doc in items:
                tag = "  (no PDF)" if doc == "none" else ""
                print("  %-18s %s%s" % (sid, label, tag))
        return 0

    if a.list_patterns:
        from . import patterns as P
        for pid, label, _fn in P.PATTERNS:
            print("  %-14s %s" % (pid, label))
        return 0

    if a.list:
        for title, key, opts in PANELS:
            print(f"\n{title}")
            for oid, label, d in opts:
                print(f"  {oid:<14} {label}{'  (default)' if d else ''}")
        return 0

    if a.all:
        opts = sorted(ALL_OPTS)
    elif a.opts:
        opts = [o.strip() for o in a.opts.split(",") if o.strip()]
        bad = set(opts) - ALL_OPTS
        if bad:
            p.error(f"unknown option(s): {', '.join(sorted(bad))}. "
                    "Run --list to see valid ids.")
    else:
        opts = list(DEFAULT_OPTS)

    fmts = ("pdf", "png") if a.png else ("pdf",)
    pats = ("classic",)
    if a.patterns:
        from . import patterns as P
        pats = (tuple(P.ALL_IDS) if a.patterns.strip() == "all"
                else tuple(x.strip() for x in a.patterns.split(",")
                           if x.strip() in P.BY_ID))
        if not pats:
            p.error("no valid layout ids. Try --list-patterns.")

    if a.scenarios:
        from . import catalogue as cat
        from .run_scenarios import run_scenarios
        sids = (list(cat.ALL_IDS) if a.scenarios.strip() == "all"
                else [x.strip() for x in a.scenarios.split(",")
                      if x.strip() in cat.BY_ID])
        if not sids:
            p.error("no valid scenario ids. Try --list-scenarios.")
        rows = run_scenarios(sids, count=a.count, seed=a.seed,
                             outdir=a.outdir, formats=fmts,
                             write_json=a.json, patterns=pats)
        print("wrote %d documents to %s/" % (len(rows), a.outdir))
        print("  scenarios: %d" % len(sids))
        print("  layouts  : %d" % len(pats))
        print("  seed     : %s" % a.seed)
        return 0

    rows = run(opts, count=a.count, seed=a.seed, outdir=a.outdir,
               formats=fmts, write_json=a.json, patterns=pats)
    total = sum(r["total"] for r in rows)
    print(f"wrote {len(rows)} invoices to {a.outdir}/")
    print(f"  options : {', '.join(opts)}")
    print(f"  seed    : {a.seed}")
    print(f"  value   : {total:,.2f}")
    print(f"  manifest: {os.path.join(a.outdir, 'manifest.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
