"""Bank statement for a folder of generated invoices.

Reads the ground-truth JSON a batch already wrote, turns each invoice into the
one bank entry that settles it, and prints the statement our firm's bank would
issue - so the paper beside the invoices is the same money, to the paisa.

    python make_bank_statement.py <invoice_dir> [<invoice_dir> ...]

Each `invoice_dir` is a batch folder holding a json/ subfolder. A sales
invoice becomes a deposit, a purchase invoice a withdrawal, dated the credit
period after the invoice. Alongside the PDF goes mapping.csv: bank row to
invoice to bill reference, which is the answer key when checking whether
Tally linked the receipt to the bill.
"""
import csv
import glob
import json
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal as D

from invoicegen.render_bank import render_statement, rupees

# our firm's own account - the statement is this account's
BANK = {
    "bank": "STATE BANK OF INDIA",
    "account": "40930926740",
    "ifsc": "SBIN0007159",
    "branch": "Hingne Khurd, Pune",
    "branch_addr": "Hingne Khurd Branch, Sinhagad Road, Pune - 411051",
    "acct_type": "Current Account",
}

# a counterparty's own bank, for the narration. Anyone not listed falls back
# to the first entry, which keeps a new party from crashing the run.
PARTY_BANK = {
    "Sai Electricals & Hardware": ("HDFC0000240", "HDFC"),
    "Sai Electricals and Hardware": ("HDFC0000240", "HDFC"),
    "Rajmudra Builders and Developers": ("KKBK0001779", "KKBK"),
    "Trimurti Switchgear Industries": ("CBIN0280601", "CBIN"),
    "Sundar Traders": ("INDB0000123", "INDB"),
    "Sanghvi Electricals Pvt Ltd": ("ICIC0000104", "ICIC"),
    "Mayur Traders": ("UTIB0000283", "UTIB"),
    "Meghdoot Cables and Wires": ("HDFC0000240", "HDFC"),
    "MAHADEV AGENCY": ("SBIN0007159", "SBIN"),
    "Deshmukh Electricals": ("BKID0000456", "BKID"),
}
FALLBACK_BANK = ("HDFC0000240", "HDFC")

# RTGS is only for two lakh and above; NEFT above a lakh; IMPS below that.
RTGS_FLOOR = D("200000")
NEFT_FLOOR = D("100000")

# A day book gives a voucher date but not its credit terms, so a settlement
# is assumed to clear a month later.
VOUCHER_CREDIT_DAYS = 30

IMPS_CHARGE_HIGH = D("15")     # per IMPS of a lakh or more
IMPS_CHARGE_LOW = D("5")
GST = D("1.18")

# a month's transfer charges are swept on this day of the following month
CHARGE_LEVY_DAY = 7

OPENING_CUSHION = D("25000")   # keep the account this far above its trough


def _yddd(d):
    """The date stamp an IMPS reference carries: year digit, day of year."""
    return f"{d.year % 10}{d.timetuple().tm_yday:03d}"


def load_invoices(dirs):
    """Every invoice JSON under the given batch folders."""
    docs = []
    for base in dirs:
        pattern = os.path.join(base, "json", "*.json")
        found = sorted(glob.glob(pattern))
        if not found:
            # maybe the folder itself is the json/ one
            found = sorted(glob.glob(os.path.join(base, "*.json")))
        for p in found:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if "invoice_number" not in d or "totals" not in d:
                continue
            bw = d.get("bill_wise") or {}
            sale = d.get("document_type") == "TAX INVOICE"
            docs.append({
                "sale": sale,
                "number": d["invoice_number"],
                # the bill reference Tally will carry. The invoice number is
                # the reference; bill_wise only repeats it.
                "ref": bw.get("reference") or d["invoice_number"],
                "idate": date.fromisoformat(d["invoice_date_iso"]),
                "credit_days": bw.get("credit_days") or 30,
                "amount": D(str(d["totals"]["amount_payable"])),
                "party": d["buyer"]["name"],
                # the ledger name is what Tally matches a bill against, so the
                # sidecar quotes it rather than the printed party name
                "ledger": (d.get("expected_voucher") or {}).get(
                    "party_ledger") or d["buyer"]["name"],
                "source": os.path.basename(p),
            })
    return docs


def load_vouchers(path):
    """Vouchers already posted in Tally, read from a day book export.

    The columns are the ones Tally's day book prints: date, party, voucher
    type, voucher number, then the debit and credit amounts. In a day book
    the party ledger is the subject of the entry, so a purchase credits the
    party - we owe them, and the bank will pay - while a sale debits it.
    """
    docs = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            row = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            party = row.get("particulars") or row.get("party")
            if not party:
                continue
            vtype = (row.get("vch type") or row.get("voucher_type") or "")
            sale = vtype.strip().lower().startswith("sale")
            debit = (row.get("debit amount") or row.get("debit") or "0")
            credit = (row.get("credit amount") or row.get("credit") or "0")
            amount = D((credit if not sale else debit).replace(",", "") or "0")
            if amount <= 0:
                continue
            d = _parse_date(row.get("date"))
            num = row.get("vch no.") or row.get("vch no") or row.get("number")
            # a day book gives the voucher number, not the supplier's bill,
            # so the reference is that number qualified by its type
            ref = f"{'SI' if sale else 'PI'}/{num}" if num else party
            docs.append({
                "sale": sale,
                "number": ref,
                "ref": ref,
                "idate": d,
                "credit_days": VOUCHER_CREDIT_DAYS,
                "amount": amount,
                "party": party,
                "ledger": party,
                "source": os.path.basename(path),
            })
    return docs


def _parse_date(text):
    """Accept the day book's 24-Apr-26 as well as a plain ISO date."""
    text = (text or "").strip()
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise SystemExit(f"cannot read the date {text!r} in the voucher file")


def bank_rows(docs):
    """One settlement entry per invoice, plus the charges those entries incur."""
    rows = []
    seq = {"NEFT": 345324787, "RTGS": 57686499, "IMPS": 7936926}

    for x in sorted(docs, key=lambda y: y["idate"]):
        d = x["idate"] + timedelta(days=x["credit_days"])
        amt = x["amount"]
        ifsc, pfx = PARTY_BANK.get(x["party"], FALLBACK_BANK)
        party = x["party"].upper()

        # The headline says what the entry is; the channel string a bank
        # packs into its narration goes underneath, where its length does
        # not crowd the row.
        if amt >= RTGS_FLOOR:
            mode = "RTGS"
            utr = f"{pfx}R{d.strftime('%Y%m%d')}{seq['RTGS']:08d}"
            channel = f"RTGS {utr}"
            ref = f"RTGSINW-{seq['RTGS']:010d}"
            seq["RTGS"] += 7331
        elif amt >= NEFT_FLOOR:
            mode = "NEFT"
            utr = f"{pfx}H{seq['NEFT']:011d}"
            channel = f"NEFT {utr}"
            ref = f"NEFTINW-{1263080821 + seq['NEFT'] % 1000}"
            seq["NEFT"] += 91
        else:
            mode = "IMPS"
            stamp = f"{_yddd(d)}{seq['IMPS']:08d}"
            verb = "Recd" if x["sale"] else "Sent"
            channel = f"{verb} IMPS/{stamp}/{pfx}"
            ref = f"IMPS-{_yddd(d)}{seq['IMPS'] + 4127:08d}"
            seq["IMPS"] += 4127

        # The counterparty is the headline - it is what a reader scans for -
        # so the direction rides on the detail line instead of eating the
        # width a long firm name needs.
        desc = [
            x["party"],
            f"{'Received' if x['sale'] else 'Paid'} - {channel}",
            f"{'Against invoice' if x['sale'] else 'Against bill'} "
            f"{x['number']}",
        ]
        rows.append({
            "date": d, "desc": desc, "ref": ref, "mode": mode,
            "dr": None if x["sale"] else amt,
            "cr": amt if x["sale"] else None,
            "invoice": x["number"], "billref": x["ref"],
            "ledger": x["ledger"],
            "voucher": "Receipt" if x["sale"] else "Payment",
        })

    # IMPS carries a charge. A bank sweeps a month's transfers into one
    # debit rather than billing each day separately, so the charges are
    # grouped by the month they fall in and levied early in the next one -
    # which is both what a statement looks like and far fewer rows.
    by_month = {}
    for r in rows:
        if r["mode"] == "IMPS":
            key = (r["date"].year, r["date"].month)
            by_month.setdefault(key, []).append(r["dr"] or r["cr"])
    for (yr, mn), amounts in sorted(by_month.items()):
        base = sum(IMPS_CHARGE_HIGH if a >= NEFT_FLOOR else IMPS_CHARGE_LOW
                   for a in amounts)
        month_end = date(yr + (mn == 12), (mn % 12) + 1, 1)
        levied = month_end + timedelta(days=CHARGE_LEVY_DAY - 1)
        rows.append({
            "date": levied,
            "desc": ["Bank charges - IMPS transfers",
                     f"For {len(amounts)} transfer"
                     f"{'s' if len(amounts) != 1 else ''} in "
                     f"{date(yr, mn, 1).strftime('%b %Y')} (incl. GST)"],
            "ref": f"TBMS-17{yr % 100:02d}{mn:02d}{len(amounts):02d}67",
            "mode": "CHG", "dr": (base * GST).quantize(D("0.01")), "cr": None,
            "invoice": "", "billref": "", "ledger": "Bank Charges",
            "voucher": "Payment",
        })

    # a deposit lands before a withdrawal on the same day, which is also what
    # keeps the running balance from dipping on a settlement day
    rows.sort(key=lambda r: (r["date"], 0 if r.get("cr") else 1))
    return rows


def opening_balance(rows):
    """Enough to keep the account above zero all the way through."""
    walk = D("0")
    trough = D("0")
    for r in rows:
        walk += (r.get("cr") or D("0")) - (r.get("dr") or D("0"))
        trough = min(trough, walk)
    if trough >= 0:
        return OPENING_CUSHION
    return (-trough + OPENING_CUSHION).quantize(D("1"))


def build_statement(docs, holder):
    """Assemble what the renderer needs, balance walked in full precision."""
    rows = bank_rows(docs)
    if not rows:
        raise SystemExit("no invoices found - nothing to put on a statement")
    opening = opening_balance(rows)

    bal = opening
    total_dr = total_cr = D("0")
    out = []
    for i, r in enumerate(rows, 1):
        if r.get("cr"):
            bal += r["cr"]
            total_cr += r["cr"]
        if r.get("dr"):
            bal -= r["dr"]
            total_dr += r["dr"]
        out.append({
            "sr": i, "date": r["date"].strftime("%d %b %Y"),
            "desc": r["desc"], "ref": r["ref"],
            "dr": r.get("dr"), "cr": r.get("cr"), "balance": bal,
            "_row": r,
        })

    stmt = dict(BANK)
    stmt.update({
        "holder": holder["name"],
        "holder_addr": holder["addr"],
        "gstin": holder.get("gstin"),
        "from": rows[0]["date"].strftime("%d %b %Y"),
        "to": rows[-1]["date"].strftime("%d %b %Y"),
        "rows": out,
        "opening": opening,
        "closing": bal,
        "total_dr": total_dr,
        "total_cr": total_cr,
        "txn_count": len(out),
    })
    return stmt


def write_mapping(stmt, path):
    """The answer key: which bank row settles which bill."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["bank_row", "bank_date", "invoice_number",
                    "bill_reference", "party_ledger", "dr_cr", "amount",
                    "voucher_type", "mode", "bank_ref"])
        n = 0
        for row in stmt["rows"]:
            r = row["_row"]
            if not r["invoice"]:
                continue
            amt = r.get("dr") or r.get("cr")
            w.writerow([row["sr"], r["date"].isoformat(), r["invoice"],
                        r["billref"], r["ledger"],
                        "Dr" if r.get("dr") else "Cr", f"{amt:.2f}",
                        r["voucher"], r["mode"], r["ref"]])
            n += 1
    return n


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    # a .csv argument is a day book of vouchers already posted in Tally;
    # anything else is a folder of generated invoices
    dirs = [a for a in argv[1:] if not a.lower().endswith(".csv")]
    books = [a for a in argv[1:] if a.lower().endswith(".csv")]

    docs = load_invoices(dirs)
    for b in books:
        docs.extend(load_vouchers(b))
    if not docs:
        print("nothing to settle - no invoice JSON or voucher CSV given")
        return 1

    # the account holder is the firm that issued the sales invoices
    with open(os.path.join("invoicegen", "data", "parties.json"),
              encoding="utf-8") as f:
        holder = json.load(f)["seller"]

    stmt = build_statement(docs, holder)
    outdir = dirs[0] if dirs else os.path.dirname(os.path.abspath(books[0]))
    pdf = os.path.join(outdir, "Bank_Statement.pdf")
    pages = render_statement(stmt, pdf)
    csv_path = os.path.join(outdir, "mapping.csv")
    mapped = write_mapping(stmt, csv_path)

    print(f"invoices read   : {len(docs)}")
    print(f"statement rows  : {stmt['txn_count']}")
    print(f"opening balance : {rupees(stmt['opening'])}")
    print(f"withdrawals     : {rupees(stmt['total_dr'])}")
    print(f"deposits        : {rupees(stmt['total_cr'])}")
    print(f"closing balance : {rupees(stmt['closing'])}")
    check = stmt["opening"] - stmt["total_dr"] + stmt["total_cr"]
    print(f"balance check   : {rupees(check)} "
          f"{'OK' if check == stmt['closing'] else 'MISMATCH'}")
    print(f"statement       : {pdf} ({pages} page{'s' if pages > 1 else ''})")
    print(f"mapping         : {csv_path} ({mapped} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
