"""Generate one complete Tally cycle as a single connected story.

    Purchase Order -> Purchase -> Purchase Return / Debit Note -> Payment
    -> Sales Order -> Sales -> Sales Return / Credit Note -> Receipt
    -> Contra -> Journal -> Stock Journal -> GST -> Outstanding
    -> Trial Balance -> P&L -> Balance Sheet

One supplier, one customer, amounts flowing through, and closing reports
derived from the vouchers actually posted - so the Trial Balance genuinely
agrees with the documents beside it.
"""
import json
import os
import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from .model import Charge, Line, half_tax, money, fmt, rupees_in_words
from .render_invoice import render_document
from .render_voucher import render_voucher
from .report import render_report
from .scenarios import load_data
from .transactions import Txn

FY = "26-27"
START = date(2026, 4, 1)
HERE = os.path.dirname(os.path.abspath(__file__))


def _ledgers():
    with open(os.path.join(HERE, "data", "ledgers.json"),
              encoding="utf-8") as f:
        return json.load(f)


def _mk(sid, kind, title, num, d, party=None):
    return Txn(sid, kind, title, num, d, party)


def build_cycle(seed=None):
    """Return the ordered list of (step_no, label, txn_or_spec)."""
    rng = random.Random(seed)
    items, parties = load_data()
    led = _ledgers()
    seller = parties["seller"]

    supplier = dict(rng.choice(parties["suppliers"]))
    customer = dict(rng.choice([b for b in parties["buyers"]
                                if b["state_code"] == "27"]))
    tr, tx, ch = led["trading"], led["tax"], led["charges"]
    bank = led["banking"]

    goods = [i for i in items["items"] if i["gst"] == 18][:40]
    cap = led["capital"]
    out = []
    d = START + timedelta(days=rng.randint(5, 60))

    # ------------------------------------------- 00 Opening Balance
    # The firm has to be funded before it can pay anyone. Without this
    # the bank runs negative and the Balance Sheet shows a negative
    # Capital Account, which no real set of books would.
    open_bank = money(Decimal(rng.randrange(500000, 900000, 25000)))
    open_cash = money(Decimal(rng.randrange(40000, 90000, 5000)))
    open_tot = money(open_bank + open_cash)
    ob = _mk("journal", "journal", "OPENING BALANCE",
             f"AE/OB/26400", START)
    ob.meta["amount"] = open_tot
    ob.dr(bank["bank_primary"], open_bank)
    ob.dr(bank["cash"], open_cash)
    ob.cr(cap["capital_account"], open_tot)
    ob.narration = "Being opening balances brought forward as on 1 April 2026"
    out.append(("00", "Opening Balance", ob))

    # ---------------------------------------------------------- 01 PO
    po_lines = [Line(g["desc"], g["hsn"], g["mrp"], q, g["uom"], g["gst"],
                     discount_pct=20)
                for g, q in zip(rng.sample(goods, 4), (20, 15, 30, 10))]
    po = _mk("purchase_order", "purchase_order", "PURCHASE ORDER",
             f"AE/PO/26401", d, supplier)
    po.lines = po_lines
    po.meta["order_terms"] = {
        "delivery_date": (d + timedelta(days=14)).isoformat(),
        "payment_terms": "30 days from date of invoice",
        "delivery_terms": "FOR our godown, Pune",
    }
    _price(po)
    out.append(("01", "Purchase Order", po))

    # ---------------------------------------------------- 02 Purchase
    d2 = d + timedelta(days=12)
    pur = _mk("purchase_invoice", "purchase_invoice", "PURCHASE INVOICE",
              f"AE/PB/26402", d2, supplier)
    pur.lines = [Line(l.desc, l.code, l.mrp, l.qty, l.uom, l.gst,
                      discount_pct=l.discount_pct) for l in po_lines]
    pur.charges = [Charge("Freight Charges", 1800, ch["freight_in"],
                          code="996511", gst=18)]
    pur.meta["against_order"] = po.number
    pur.meta["supplier_invoice"] = f"SEP/{rng.randint(1000, 9999)}"
    _price(pur)
    _post_trade(pur, led, purchase=True)
    out.append(("02", "Purchase", pur))

    # ------------------------------------- 03 Purchase Return / DN
    d3 = d2 + timedelta(days=6)
    dn = _mk("debit_note", "debit_note", "DEBIT NOTE",
             f"AE/DN/26403", d3, supplier)
    ret = po_lines[0]
    dn.lines = [Line(ret.desc, ret.code, ret.mrp, money(ret.qty * Decimal("0.25")),
                     ret.uom, ret.gst, discount_pct=ret.discount_pct)]
    dn.meta["original_invoice"] = {
        "number": pur.number, "date": d2.strftime("%d %b %Y"),
        "date_iso": d2.isoformat(),
        "reason": "Goods returned - damaged in transit",
    }
    _price(dn)
    _post_trade(dn, led, purchase=True, note=True)
    out.append(("03", "Purchase Return - Debit Note", dn))

    # ----------------------------------------------------- 04 Payment
    d4 = d3 + timedelta(days=15)
    due = money(pur.meta["total"] - dn.meta["total"])
    pay = _mk("payment", "payment", "PAYMENT VOUCHER",
              f"AE/PY/26404", d4, supplier)
    pay.meta.update({
        "amount": due, "mode": "NEFT", "instrument": bank["bank_primary"],
        "method": "Agst Ref",
        "bills": [{"ref": pur.number, "amount": float(pur.meta["total"]),
                   "bill_total": float(pur.meta["total"])},
                  {"ref": dn.number, "amount": -float(dn.meta["total"]),
                   "bill_total": float(dn.meta["total"])}],
    })
    pay.dr(supplier["tally_ledger"], due)
    pay.cr(bank["bank_primary"], due)
    pay.narration = f"Being amount paid to {supplier['name']}"
    out.append(("04", "Payment", pay))

    # -------------------------------------------------- 05 Sales Order
    d5 = d4 + timedelta(days=4)
    so_lines = [Line(g["desc"], g["hsn"], g["mrp"], q, g["uom"], g["gst"])
                for g, q in zip(rng.sample(goods, 4), (12, 8, 20, 6))]
    so = _mk("sales_order", "sales_order", "SALES ORDER",
             f"AE/SO/26405", d5, customer)
    so.lines = so_lines
    so.meta["order_terms"] = {
        "delivery_date": (d5 + timedelta(days=10)).isoformat(),
        "payment_terms": "15 days from invoice",
        "delivery_terms": "Door delivery included",
    }
    _price(so)
    out.append(("05", "Sales Order", so))

    # ------------------------------------------------------- 06 Sales
    d6 = d5 + timedelta(days=9)
    sale = _mk("sales_invoice", "sales_invoice", "TAX INVOICE",
               f"AE/SI/26406", d6, customer)
    sale.lines = [Line(l.desc, l.code, l.mrp, l.qty, l.uom, l.gst)
                  for l in so_lines]
    sale.charges = [Charge("Freight Charges", 950, ch["freight_out"],
                           code="996511", gst=18)]
    sale.meta["against_order"] = so.number
    _price(sale)
    _post_trade(sale, led, purchase=False)
    out.append(("06", "Sales", sale))

    # ----------------------------------------- 07 Sales Return / CN
    d7 = d6 + timedelta(days=5)
    cn = _mk("credit_note", "credit_note", "CREDIT NOTE",
             f"AE/CN/26407", d7, customer)
    sret = so_lines[1]
    cn.lines = [Line(sret.desc, sret.code, sret.mrp,
                     money(sret.qty * Decimal("0.5")), sret.uom, sret.gst)]
    cn.meta["original_invoice"] = {
        "number": sale.number, "date": d6.strftime("%d %b %Y"),
        "date_iso": d6.isoformat(),
        "reason": "Quality rejection - material returned by customer",
    }
    _price(cn)
    _post_trade(cn, led, purchase=False, note=True)
    out.append(("07", "Sales Return - Credit Note", cn))

    # ----------------------------------------------------- 08 Receipt
    d8 = d7 + timedelta(days=11)
    recd = money(sale.meta["total"] - cn.meta["total"])
    rcpt = _mk("receipt", "receipt", "RECEIPT VOUCHER",
               f"AE/RC/26408", d8, customer)
    rcpt.meta.update({
        "amount": recd, "mode": "Cheque", "instrument": bank["bank_primary"],
        "method": "Agst Ref",
        "cheque": {"number": str(rng.randint(100000, 999999)),
                   "date": d8.isoformat(), "bank": "HDFC Bank"},
        "bills": [{"ref": sale.number, "amount": float(sale.meta["total"]),
                   "bill_total": float(sale.meta["total"])},
                  {"ref": cn.number, "amount": -float(cn.meta["total"]),
                   "bill_total": float(cn.meta["total"])}],
    })
    rcpt.dr(bank["bank_primary"], recd)
    rcpt.cr(customer["tally_ledger"], recd)
    rcpt.narration = f"Being amount received from {customer['name']}"
    out.append(("08", "Receipt", rcpt))

    # ------------------------------------------------------ 09 Contra
    d9 = d8 + timedelta(days=2)
    camt = money(Decimal(rng.randrange(20000, 60000, 500)))
    con = _mk("contra", "contra", "CONTRA VOUCHER",
              f"AE/CT/26409", d9)
    con.meta.update({"amount": camt, "mode": "Contra",
                     "instrument": bank["cash"]})
    con.dr(bank["cash"], camt)
    con.cr(bank["bank_primary"], camt)
    con.narration = "Being cash withdrawn from bank for office use"
    out.append(("09", "Contra", con))

    # ----------------------------------------------------- 10 Journal
    d10 = d9 + timedelta(days=3)
    jamt = money(Decimal(rng.randrange(8000, 25000, 500)))
    jv = _mk("journal", "journal", "JOURNAL VOUCHER",
             f"AE/JV/26410", d10)
    head = "Office Rent"
    jv.meta["amount"] = jamt
    jv.dr(head, jamt)
    jv.cr(led["expenses"]["outstanding"], jamt)
    jv.narration = "Being office rent for the month provided for"
    out.append(("10", "Journal", jv))

    # ----------------------------------------------- 11 Stock Journal
    d11 = d10 + timedelta(days=1)
    sj = _mk("stock_journal", "stock_journal", "STOCK JOURNAL",
             f"AE/SJ/26411", d11)
    consumed = po_lines[2]
    produced = po_lines[3]
    sj.meta.update({
        "amount": money(consumed.taxable),
        "source": [{"item": consumed.desc, "qty": float(consumed.qty),
                    "uom": consumed.uom, "rate": float(consumed.rate),
                    "value": float(consumed.taxable)}],
        "destination": [{"item": produced.desc, "qty": float(produced.qty),
                         "uom": produced.uom, "rate": float(produced.rate),
                         "value": float(consumed.taxable)}],
        "godown_from": "Main Store - Nana Peth",
        "godown_to": "Warehouse - Bhosari",
    })
    sj.narration = "Being material transferred between godowns"
    out.append(("11", "Stock Journal", sj))

    vouchers = [t for _, _, t in out]
    reports = _reports(vouchers, seller, supplier, customer, led,
                       d11 + timedelta(days=5))
    for i, (label, spec) in enumerate(reports, 12):
        out.append((f"{i:02d}", label, spec))

    return out, seller, supplier, customer


# ---------------------------------------------------------------- pricing

def _price(t):
    """Totals for a document with line items."""
    taxable = money(sum(l.taxable for l in t.lines))
    charges = money(sum(c.amount for c in t.charges))
    tax = money(sum(l.tax for l in t.lines) + sum(c.tax for c in t.charges))
    gross = money(taxable + charges + tax)
    total = Decimal(int(gross.to_integral_value()))
    t.meta.update({
        "taxable": taxable, "charges": charges, "tax": tax,
        "round_off": money(total - gross), "total": total,
        "rcm": False, "zero_rated": False, "cash_discount": Decimal(0),
        "tds_amount": Decimal(0), "tcs": Decimal(0),
        "advance": Decimal(0), "customs_duty": Decimal(0),
    })


def _post_trade(t, led, purchase, note=False):
    """Dr/Cr legs for a purchase, sale or the note that reverses one."""
    m, tr, tx = t.meta, led["trading"], led["tax"]
    trade_dr = purchase if not note else not purchase

    if purchase:
        acc = tr["purchase_return"] if note else tr["purchase_goods"]
        side = "input"
    else:
        acc = tr["sales_return"] if note else tr["sales_goods"]
        side = "output"

    t._leg(acc, m["taxable"], trade_dr)
    for c in t.charges:
        t._leg(c.ledger, c.amount, trade_dr)
    half = half_tax(m["tax"])
    t._leg(tx[f"{side}_cgst"], half, trade_dr)
    t._leg(tx[f"{side}_sgst"], half, trade_dr)
    if m["round_off"]:
        gap = money(t.total_dr - t.total_cr + m["total"]
                    * (1 if trade_dr else -1) * 0)
    t._leg(t.party["tally_ledger"], m["total"], not trade_dr)
    gap = money(t.total_dr - t.total_cr)
    if gap:
        t.legs.append({"ledger": led["charges"]["round_off"],
                       "dr": float(max(-gap, Decimal(0))),
                       "cr": float(max(gap, Decimal(0)))})
    t.narration = (f"Being {'purchase' if purchase else 'sales'}"
                   f"{' return' if note else ''} vide {t.number}")


# ---------------------------------------------------------------- reports

def _reports(vouchers, seller, supplier, customer, led, asof):
    """Derive the closing statements from the vouchers just posted."""
    bal = defaultdict(lambda: Decimal(0))
    for v in vouchers:
        for leg in v.legs:
            bal[leg["ledger"]] += (Decimal(str(leg["dr"]))
                                   - Decimal(str(leg["cr"])))
    bal = {k: money(v) for k, v in bal.items() if money(v) != 0}
    period = f"1 April 2026 to {asof.strftime('%d %B %Y')}"
    out = []

    # ---- GST summary
    tax = led["tax"]
    inp = money(bal.get(tax["input_cgst"], 0) + bal.get(tax["input_sgst"], 0))
    outp = money(-(bal.get(tax["output_cgst"], 0)
                   + bal.get(tax["output_sgst"], 0)))
    net = money(outp - inp)
    rows = [
        ["Output CGST", "", fmt(-bal.get(tax["output_cgst"], 0))],
        ["Output SGST", "", fmt(-bal.get(tax["output_sgst"], 0))],
        ["Input CGST", fmt(bal.get(tax["input_cgst"], 0)), ""],
        ["Input SGST", fmt(bal.get(tax["input_sgst"], 0)), ""],
    ]
    out.append(("GST Summary", {
        "title": "GST SUMMARY", "subtitle": period,
        "columns": [("Particulars", 88, "l"), ("Input Credit", 46, "r"),
                    ("Output Tax", 46, "r")],
        "sections": [(None, rows)],
        "totals": [["Total", fmt(inp), fmt(outp)],
                   ["Net GST Payable", "", fmt(net)]],
        "note": "Input credit is set off against output tax; the balance is "
                "payable in cash.",
    }))

    # ---- Outstanding
    sup_bal = money(-bal.get(supplier["tally_ledger"], 0))
    cus_bal = money(bal.get(customer["tally_ledger"], 0))
    out.append(("Outstanding", {
        "title": "OUTSTANDING BALANCES", "subtitle": f"As at {asof:%d %B %Y}",
        "columns": [("Party", 88, "l"), ("Receivable", 46, "r"),
                    ("Payable", 46, "r")],
        "sections": [
            ("Sundry Debtors",
             [[customer["name"], fmt(cus_bal) if cus_bal else "Nil", ""]]),
            ("Sundry Creditors",
             [[supplier["name"], "", fmt(sup_bal) if sup_bal else "Nil"]]),
        ],
        "totals": [["Total", fmt(max(cus_bal, Decimal(0))),
                    fmt(max(sup_bal, Decimal(0)))]],
        "note": "All bills settled in full where the balance shows Nil.",
    }))

    # ---- Trial Balance
    rows, tdr, tcr = [], Decimal(0), Decimal(0)
    for name in sorted(bal):
        v = bal[name]
        dr = v if v > 0 else Decimal(0)
        cr = -v if v < 0 else Decimal(0)
        tdr += dr
        tcr += cr
        rows.append([name, fmt(dr) if dr else "", fmt(cr) if cr else ""])
    out.append(("Trial Balance", {
        "title": "TRIAL BALANCE", "subtitle": period,
        "columns": [("Ledger", 88, "l"), ("Debit", 46, "r"),
                    ("Credit", 46, "r")],
        "sections": [(None, rows)],
        "totals": [["Total", fmt(tdr), fmt(tcr)]],
        "note": "Derived from the vouchers in this folder. Debit equals "
                "credit, so the books are in balance.",
    }))

    # ---- Profit & Loss
    tr = led["trading"]
    purchases = money(bal.get(tr["purchase_goods"], 0)
                      + bal.get(tr["purchase_return"], 0))
    sales = money(-(bal.get(tr["sales_goods"], 0)
                    + bal.get(tr["sales_return"], 0)))
    direct = money(bal.get(led["charges"]["freight_in"], 0))

    # Every ledger that is not a balance-sheet account belongs in the P&L.
    # Listing them by name rather than filtering on sign keeps recovered
    # income (freight charged out, for instance) from being dropped.
    bs_led = {led["banking"]["bank_primary"], led["banking"]["cash"],
              led["capital"]["capital_account"],
              led["expenses"]["outstanding"],
              supplier["tally_ledger"], customer["tally_ledger"],
              tr["purchase_goods"], tr["purchase_return"],
              tr["sales_goods"], tr["sales_return"],
              led["charges"]["freight_in"]}
    bs_led |= {v for k, v in tax.items() if isinstance(v, str)}

    other = [(k, v) for k, v in bal.items() if k not in bs_led]
    ro = led["charges"]["round_off"]
    exp_rows = [[k, fmt(v), ""] for k, v in sorted(other)
                if v > 0 or k == ro]
    inc_rows = [[k, "", fmt(-v)] for k, v in sorted(other)
                if v < 0 and k != ro]
    indirect = money(sum(v for _, v in other))

    gross_profit = money(sales - purchases - direct)
    net_profit = money(gross_profit - indirect)

    pl_sections = [
        ("Trading Account", [
            ["Sales (net of returns)", "", fmt(sales)],
            ["Less: Purchases (net of returns)", fmt(purchases), ""],
            ["Less: Direct Expenses - Freight Inward", fmt(direct), ""],
            ["Gross Profit", "", fmt(gross_profit)],
        ]),
    ]
    if exp_rows:
        pl_sections.append(("Indirect Expenses", exp_rows))
    if inc_rows:
        pl_sections.append(("Indirect Income", inc_rows))

    out.append(("Profit and Loss", {
        "title": "PROFIT AND LOSS ACCOUNT", "subtitle": f"For {period}",
        "columns": [("Particulars", 88, "l"), ("Amount", 46, "r"),
                    ("Total", 46, "r")],
        "sections": pl_sections,
        "totals": [["Net Profit for the period", "", fmt(net_profit)]],
        "note": "Prepared from the vouchers in this folder.",
    }))

    # ---- Balance Sheet
    bank_bal = money(bal.get(led["banking"]["bank_primary"], 0))
    cash_bal = money(bal.get(led["banking"]["cash"], 0))
    gst_net = money(-net) if net < 0 else Decimal(0)
    outstanding = money(-bal.get(led["expenses"]["outstanding"], 0))
    assets = money(cus_bal + bank_bal + cash_bal + gst_net)
    # Capital is what was actually brought in, plus the profit the period
    # earned - not a plug. Assets then equal liabilities because every
    # voucher behind these numbers was itself balanced.
    opening_cap = money(-bal.get(led["capital"]["capital_account"], 0))
    capital = money(opening_cap + net_profit)
    liab = money(sup_bal + outstanding + max(net, Decimal(0)))
    out.append(("Balance Sheet", {
        "title": "BALANCE SHEET", "subtitle": f"As at {asof:%d %B %Y}",
        "columns": [("Particulars", 88, "l"), ("Amount", 46, "r"),
                    ("Total", 46, "r")],
        "sections": [
            ("Liabilities", [
                ["Capital Account", fmt(opening_cap), ""],
                ["Add: Net Profit for the period", fmt(net_profit), ""],
                ["Sundry Creditors", fmt(sup_bal), ""],
                ["Outstanding Expenses", fmt(outstanding), ""],
                ["GST Payable", fmt(max(net, Decimal(0))), ""],
            ]),
            ("Assets", [
                ["Sundry Debtors", fmt(cus_bal), ""],
                ["Bank Account", fmt(bank_bal), ""],
                ["Cash-in-Hand", fmt(cash_bal), ""],
                ["GST Input Credit carried forward", fmt(gst_net), ""],
            ]),
        ],
        "totals": [["Total Liabilities", "", fmt(money(capital + liab))],
                   ["Total Assets", "", fmt(assets)]],
        "note": "Capital is the amount introduced plus the period's profit. Assets equal liabilities because every voucher behind these figures balances.",
    }))
    return out


# ------------------------------------------------------------------ output

def _render(step, label, obj, seller, path):
    if isinstance(obj, dict):
        render_report(obj, seller, path)
    elif obj.kind in ("receipt", "payment", "contra", "journal"):
        render_voucher(obj, seller, path)
    elif obj.kind == "stock_journal":
        render_report(_stock_spec(obj), seller, path)
    else:
        render_document(obj, seller, path)


def _stock_spec(t):
    m = t.meta
    return {
        "title": "STOCK JOURNAL",
        "subtitle": f"No: {t.number}    Date: {t.date:%d %b %Y}",
        "columns": [("Item", 95, "l"), ("Quantity", 25, "r"),
                    ("Rate", 25, "r"), ("Value", 30, "r")],
        "sections": [
            (f"Source (consumed)  -  {m['godown_from']}",
             [[s["item"], f"{s['qty']:g} {s['uom']}", fmt(s["rate"]),
               fmt(s["value"])] for s in m["source"]]),
            (f"Destination (produced)  -  {m['godown_to']}",
             [[s["item"], f"{s['qty']:g} {s['uom']}", fmt(s["rate"]),
               fmt(s["value"])] for s in m["destination"]]),
        ],
        "totals": [["Total Value Transferred", "", "", fmt(m["amount"])]],
        "note": t.narration,
    }


def _record(step, label, obj, seller):
    if isinstance(obj, dict):
        return {"step": step, "label": label, "document_type": obj["title"],
                "kind": "report", "has_pdf": True}
    m = obj.meta
    return {
        "step": step, "label": label, "document_type": obj.title,
        "kind": obj.kind, "number": obj.number,
        "date": obj.date.isoformat(),
        "party": (obj.party or {}).get("name"),
        "party_ledger": (obj.party or {}).get("tally_ledger"),
        "amount": float(m.get("total", m.get("amount", 0))),
        "links_to": [v for v in (m.get("against_order"),
                                 (m.get("original_invoice") or {}).get("number"))
                     if v],
        "bills": m.get("bills"),
        "lines": [{"description": l.desc, "hsn_sac": l.code,
                   "qty": float(l.qty), "uom": l.uom,
                   "rate": float(l.rate),
                   "taxable_value": float(l.taxable),
                   "gst_rate": float(l.gst),
                   "tax_amount": float(l.tax)} for l in obj.lines],
        "voucher": {"entries": obj.legs,
                    "total_dr": float(obj.total_dr),
                    "total_cr": float(obj.total_cr),
                    "balanced": obj.balanced,
                    "narration": obj.narration},
        "has_pdf": True,
    }


def generate_cycle(outdir, seed=None):
    """Write the whole cycle into `outdir`. Returns the manifest rows."""
    steps, seller, supplier, customer = build_cycle(seed)
    # documents and ground truth in sibling folders, so a parser can be
    # pointed at pdf/ without seeing the answers
    pdf_dir = os.path.join(outdir, "pdf")
    json_dir = os.path.join(outdir, "json")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(json_dir, exist_ok=True)
    rows = []
    for step, label, obj in steps:
        name = f"{step} - {label.replace('/', '-')}"
        _render(step, label, obj, seller,
                os.path.join(pdf_dir, name + ".pdf"))
        rec = _record(step, label, obj, seller)
        rec["file"] = name
        with open(os.path.join(json_dir, name + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump(rec, f, indent=2)
        rows.append(rec)

    with open(os.path.join(outdir, "00 - Cycle Summary.txt"), "w",
              encoding="utf-8") as f:
        f.write("TALLY DOCUMENT CYCLE\n")
        f.write("=" * 66 + "\n\n")
        f.write(f"Supplier : {supplier['name']}  ({supplier['gstin']})\n")
        f.write(f"Customer : {customer['name']}  ({customer['gstin']})\n\n")
        for r in rows:
            num = r.get("number", "-")
            amt = r.get("amount")
            f.write(f"{r['step']}  {r['label']:<32} {num:<20} "
                    f"{('Rs ' + format(amt, ',.2f')) if amt else ''}\n")
            for lk in r.get("links_to") or []:
                f.write(f"{'':4}    -> against {lk}\n")
    return rows
