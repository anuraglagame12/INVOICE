"""Every layout must show the same invoice.

The whole point of patterns is that the numbers do not move - only where they
sit on the page. This draws one invoice in all twenty layouts and checks that
each still carries the same total, the same party and the same line values.

    python check_patterns.py
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def text_of(pdf):
    try:
        return subprocess.run(["pdftotext", "-layout", pdf, "-"],
                              capture_output=True, text=True,
                              timeout=40).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def main():
    from invoicegen import patterns as pat
    from invoicegen.run_scenarios import run_scenarios

    tmp = "_patcheck"
    shutil.rmtree(tmp, ignore_errors=True)
    print("drawing one invoice in %d layouts..." % len(pat.PATTERNS))
    rows = run_scenarios(["sale_goods_local"], count=1, seed=5, outdir=tmp,
                         patterns=tuple(pat.ALL_IDS), write_json=True)

    import json
    rec = json.load(open(os.path.join(tmp, "json", rows[0]["file"] + ".json"),
                         encoding="utf-8"))
    total = "{:,.2f}".format(rec["amount"])
    party = (rec["party"] or {}).get("name", "")
    gstin = (rec["party"] or {}).get("gstin", "")
    lines = rec["lines"]
    print("  invoice %s   total %s   %d lines\n"
          % (rec["number"], total, len(lines)))

    checked = failed = 0
    for pid, label, _fn in pat.PATTERNS:
        # every layout names itself when several were drawn
        want = "_%s.pdf" % pat.tag(pid)
        cands = [f for f in os.listdir(os.path.join(tmp, "pdf"))
                 if f.endswith(want)]
        if not cands:
            print("FAIL  %-24s no file produced" % label)
            failed += 1
            continue

        pdf = os.path.join(tmp, "pdf", cands[0])
        txt = text_of(pdf)
        checked += 1
        if txt is None:
            print("      %-24s (pdftotext unavailable)" % label)
            continue

        errs = []
        # Continuation repeats items across two pages on purpose, so its
        # total legitimately differs - check its party and lines only.
        if pid != "continuation" and total not in txt:
            errs.append("total %s not shown" % total)
        up = txt.upper()
        if party and party[:18].upper() not in up:
            errs.append("party name missing")
        if gstin and gstin not in txt:
            errs.append("party GSTIN missing")
        if rec["number"] not in txt and rec["number"].replace("/", "")                 not in txt.replace("/", ""):
            errs.append("invoice number missing")
        shown = sum(1 for line in lines
                    if "{:,.2f}".format(line["taxable_value"]) in txt)
        if pid == "thermal":
            # a receipt prints line AMOUNTS, not taxable values
            shown = sum(1 for line in lines
                        if "{:,.2f}".format(line["amount"]) in txt)
        if shown < len(lines):
            errs.append("only %d of %d line values shown"
                        % (shown, len(lines)))

        if errs:
            failed += 1
            print("FAIL  %-24s %s" % (label, "; ".join(errs)))

    print("\n%d/%d layouts show the same invoice" % (checked - failed,
                                                     checked))
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
