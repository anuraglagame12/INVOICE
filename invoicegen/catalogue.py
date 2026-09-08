"""The Tally transaction catalogue.

One entry per accounting event. Each says what document (if any) is printed,
what voucher Tally should end up with, and which ledgers move.

`doc` values:
    invoice   - a tax invoice / bill, printed
    note      - credit or debit note, printed
    order     - purchase or sales order, printed
    voucher   - receipt / payment / contra slip, printed
    none      - a journal-only event: no document exists in real life

Entries with doc="none" still produce ground-truth JSON so the posting logic
can be tested; they simply have no PDF.
"""

# Categories in the order the UI shows them.
CATEGORIES = [
    ("purchase", "Purchase"),
    ("sales", "Sales"),
    ("receipt", "Receipts (money in)"),
    ("payment", "Payments (money out)"),
    ("bank", "Bank & Cash"),
    ("expense", "Expenses"),
    ("asset", "Fixed Assets"),
]

# id, label, category, doc kind, tags driving how it is built
SCENARIOS = [
    # ---------------------------------------------------------- purchase
    ("pur_goods_local", "Purchase of goods - local", "purchase", "invoice",
     ["purchase", "goods", "intra"]),
    ("pur_goods_inter", "Purchase of goods - interstate", "purchase",
     "invoice", ["purchase", "goods", "inter"]),
    ("pur_serv_local", "Purchase of services - local", "purchase", "invoice",
     ["purchase", "services", "intra"]),
    ("pur_serv_inter", "Purchase of services - interstate", "purchase",
     "invoice", ["purchase", "services", "inter"]),
    ("pur_capital", "Purchase of capital asset", "purchase", "invoice",
     ["purchase", "capital", "intra"]),
    ("pur_freight", "Purchase with freight / transport", "purchase",
     "invoice", ["purchase", "goods", "intra", "freight"]),
    ("pur_charges", "Purchase with additional charges", "purchase", "invoice",
     ["purchase", "goods", "intra", "packing", "insurance", "loading"]),
    ("pur_trade_disc", "Purchase with trade discount", "purchase", "invoice",
     ["purchase", "goods", "intra", "trade_discount"]),
    ("pur_cash_disc", "Purchase with cash discount", "purchase", "invoice",
     ["purchase", "goods", "intra", "cash_discount"]),
    ("pur_rcm", "Purchase under reverse charge", "purchase", "invoice",
     ["purchase", "services", "intra", "rcm"]),
    ("pur_import_goods", "Import of goods", "purchase", "invoice",
     ["purchase", "goods", "import"]),
    ("pur_import_serv", "Import of services", "purchase", "invoice",
     ["purchase", "services", "import", "rcm"]),
    ("pur_advance", "Purchase against advance", "purchase", "invoice",
     ["purchase", "goods", "intra", "advance"]),
    ("pur_against_po", "Purchase against purchase order", "purchase",
     "invoice", ["purchase", "goods", "intra", "against_order"]),
    ("pur_tds", "Purchase with TDS deduction", "purchase", "invoice",
     ["purchase", "services", "intra", "tds"]),
    ("pur_roundoff", "Purchase with round-off", "purchase", "invoice",
     ["purchase", "goods", "intra", "roundoff"]),
    ("pur_unregistered", "Purchase from unregistered supplier", "purchase",
     "invoice", ["purchase", "goods", "intra", "unregistered_party"]),
    ("pur_composition", "Purchase from composition dealer", "purchase",
     "invoice", ["purchase", "goods", "intra", "composition"]),
    ("pur_return_goods", "Purchase return - goods", "purchase", "note",
     ["purchase", "goods", "intra", "debit_note"]),
    ("pur_return_serv", "Purchase return - services", "purchase", "note",
     ["purchase", "services", "intra", "debit_note"]),
    ("pur_order", "Purchase order", "purchase", "order",
     ["purchase", "goods", "intra", "order"]),

    # ------------------------------------------------------------- sales
    ("sale_goods_local", "Sale of goods - local", "sales", "invoice",
     ["sales", "goods", "intra"]),
    ("sale_goods_inter", "Sale of goods - interstate", "sales", "invoice",
     ["sales", "goods", "inter"]),
    ("sale_serv_local", "Sale of services - local", "sales", "invoice",
     ["sales", "services", "intra"]),
    ("sale_serv_inter", "Sale of services - interstate", "sales", "invoice",
     ["sales", "services", "inter"]),
    ("sale_export_goods", "Export sale - goods", "sales", "invoice",
     ["sales", "goods", "export"]),
    ("sale_export_serv", "Export sale - services", "sales", "invoice",
     ["sales", "services", "export"]),
    ("sale_sez", "SEZ sale", "sales", "invoice", ["sales", "goods", "sez"]),
    ("sale_freight", "Sale with freight charges", "sales", "invoice",
     ["sales", "goods", "intra", "freight"]),
    ("sale_charges", "Sale with other charges", "sales", "invoice",
     ["sales", "goods", "intra", "packing", "insurance"]),
    ("sale_trade_disc", "Sale with trade discount", "sales", "invoice",
     ["sales", "goods", "intra", "trade_discount"]),
    ("sale_cash_disc", "Sale with cash discount", "sales", "invoice",
     ["sales", "goods", "intra", "cash_discount"]),
    ("sale_advance", "Sale against advance", "sales", "invoice",
     ["sales", "goods", "intra", "advance"]),
    ("sale_against_so", "Sale against sales order", "sales", "invoice",
     ["sales", "goods", "intra", "against_order"]),
    ("sale_unregistered", "Sale to unregistered customer", "sales", "invoice",
     ["sales", "goods", "intra", "unregistered_party"]),
    ("sale_composition", "Sale to composition dealer", "sales", "invoice",
     ["sales", "goods", "intra", "composition"]),
    ("sale_fixed_asset", "Sale of fixed asset", "sales", "invoice",
     ["sales", "capital", "intra", "asset_sale"]),
    ("sale_scrap", "Sale of scrap", "sales", "invoice",
     ["sales", "scrap", "intra"]),
    ("sale_tcs", "Sale with TCS applicability", "sales", "invoice",
     ["sales", "goods", "intra", "tcs"]),
    ("sale_return_goods", "Sales return - goods", "sales", "note",
     ["sales", "goods", "intra", "credit_note"]),
    ("sale_cancel", "Sales cancellation / reversal", "sales", "note",
     ["sales", "goods", "intra", "credit_note", "cancellation"]),
    ("sale_order", "Sales order", "sales", "order",
     ["sales", "goods", "intra", "order"]),

    # ---------------------------------------------------------- receipts
    ("rcpt_advance", "Customer advance received", "receipt", "voucher",
     ["receipt", "advance_received"]),
    ("rcpt_against_inv", "Customer receipt against invoice", "receipt",
     "voucher", ["receipt", "against_bill"]),
    ("rcpt_partial", "Customer partial receipt", "receipt", "voucher",
     ["receipt", "against_bill", "partial"]),
    ("rcpt_multi", "Customer receipt against multiple invoices", "receipt",
     "voucher", ["receipt", "against_bill", "multi_bill"]),
    ("rcpt_on_account", "Customer receipt on account", "receipt", "voucher",
     ["receipt", "on_account"]),
    ("rcpt_adv_adjust", "Customer advance adjustment", "receipt", "none",
     ["journal", "advance_adjust", "customer"]),
    ("rcpt_debit_note", "Customer debit note", "receipt", "note",
     ["sales", "goods", "intra", "debit_note"]),
    ("rcpt_credit_note", "Customer credit note", "receipt", "note",
     ["sales", "goods", "intra", "credit_note"]),
    ("rcpt_discount", "Customer discount allowed", "receipt", "none",
     ["journal", "discount_allowed"]),
    ("rcpt_bad_debt", "Customer bad debt write-off", "receipt", "none",
     ["journal", "bad_debt"]),

    # ---------------------------------------------------------- payments
    ("pay_advance", "Vendor advance paid", "payment", "voucher",
     ["payment", "advance_paid"]),
    ("pay_against_inv", "Vendor payment against invoice", "payment",
     "voucher", ["payment", "against_bill"]),
    ("pay_partial", "Vendor partial payment", "payment", "voucher",
     ["payment", "against_bill", "partial"]),
    ("pay_multi", "Vendor payment against multiple invoices", "payment",
     "voucher", ["payment", "against_bill", "multi_bill"]),
    ("pay_on_account", "Vendor payment on account", "payment", "voucher",
     ["payment", "on_account"]),
    ("pay_adv_adjust", "Vendor advance adjustment", "payment", "none",
     ["journal", "advance_adjust", "vendor"]),
    ("pay_debit_note", "Vendor debit note", "payment", "note",
     ["purchase", "goods", "intra", "debit_note"]),
    ("pay_credit_note", "Vendor credit note", "payment", "note",
     ["purchase", "goods", "intra", "credit_note"]),
    ("pay_discount", "Vendor discount received", "payment", "none",
     ["journal", "discount_received"]),
    ("pay_writeback", "Vendor payable write-back", "payment", "none",
     ["journal", "write_back"]),

    # ------------------------------------------------------- bank & cash
    ("cash_receipt", "Cash receipt", "bank", "voucher", ["receipt", "cash"]),
    ("cash_payment", "Cash payment", "bank", "voucher", ["payment", "cash"]),
    ("bank_receipt", "Bank receipt", "bank", "voucher", ["receipt", "bank"]),
    ("bank_payment", "Bank payment", "bank", "voucher", ["payment", "bank"]),
    ("cash_to_bank", "Cash deposited into bank", "bank", "voucher",
     ["contra", "deposit"]),
    ("bank_to_cash", "Cash withdrawn from bank", "bank", "voucher",
     ["contra", "withdrawal"]),
    ("bank_transfer", "Bank-to-bank transfer", "bank", "voucher",
     ["contra", "transfer"]),
    ("bank_charges", "Bank charges", "bank", "none", ["journal", "bank_chg"]),
    ("bank_int_recd", "Bank interest received", "bank", "none",
     ["journal", "interest_income"]),
    ("bank_int_paid", "Bank interest charged", "bank", "none",
     ["journal", "interest_expense"]),
    ("cheque_issued", "Cheque issued", "bank", "voucher",
     ["payment", "bank", "cheque"]),
    ("cheque_deposited", "Cheque deposited", "bank", "voucher",
     ["receipt", "bank", "cheque"]),
    ("cheque_bounce_cust", "Cheque bounced - customer", "bank", "none",
     ["journal", "bounce", "customer"]),
    ("cheque_bounce_vend", "Cheque bounced - vendor", "bank", "none",
     ["journal", "bounce", "vendor"]),
    ("bank_reco", "Bank reconciliation adjustment", "bank", "none",
     ["journal", "reconciliation"]),

    # ---------------------------------------------------------- expenses
    ("exp_direct", "Direct expense booking", "expense", "invoice",
     ["purchase", "expense", "intra", "direct"]),
    ("exp_indirect", "Indirect expense booking", "expense", "invoice",
     ["purchase", "expense", "intra", "indirect"]),
    ("exp_gst", "Expense with GST", "expense", "invoice",
     ["purchase", "expense", "intra"]),
    ("exp_tds", "Expense with TDS", "expense", "invoice",
     ["purchase", "expense", "intra", "tds"]),
    ("exp_accrual", "Expense accrual", "expense", "none",
     ["journal", "accrual"]),
    ("exp_outstanding", "Outstanding expense", "expense", "none",
     ["journal", "outstanding"]),
    ("exp_prepaid_create", "Prepaid expense creation", "expense", "none",
     ["journal", "prepaid_create"]),
    ("exp_prepaid_amort", "Prepaid expense amortisation", "expense", "none",
     ["journal", "prepaid_amort"]),
    ("exp_provision", "Provision creation", "expense", "none",
     ["journal", "provision"]),
    ("exp_provision_rev", "Provision reversal", "expense", "none",
     ["journal", "provision_reversal"]),
    ("exp_reclass", "Expense reclassification", "expense", "none",
     ["journal", "reclass"]),
    ("exp_correction", "Expense correction", "expense", "none",
     ["journal", "correction"]),
    ("exp_reimburse", "Expense reimbursement to employee", "expense",
     "voucher", ["payment", "reimbursement"]),
    ("emp_advance", "Employee advance", "expense", "voucher",
     ["payment", "employee_advance"]),
    ("emp_adv_adjust", "Employee advance adjustment", "expense", "none",
     ["journal", "employee_adjust"]),
    ("petty_cash", "Petty cash expense", "expense", "voucher",
     ["payment", "cash", "petty"]),
    ("imprest", "Imprest replenishment", "expense", "voucher",
     ["payment", "imprest"]),
    ("exp_misc", "Miscellaneous expense", "expense", "invoice",
     ["purchase", "expense", "intra", "misc"]),
    ("exp_prior_period", "Prior-period expense adjustment", "expense", "none",
     ["journal", "prior_period"]),
    ("exp_audit_adj", "Audit expense adjustment", "expense", "none",
     ["journal", "audit_adjust"]),

    # ----------------------------------------------------- fixed assets
    ("fa_purchase", "Fixed asset purchase", "asset", "invoice",
     ["purchase", "capital", "intra"]),
    ("fa_capitalise", "Asset capitalisation", "asset", "none",
     ["journal", "capitalise"]),
    ("fa_depreciation", "Depreciation booking", "asset", "none",
     ["journal", "depreciation"]),
    ("fa_transfer", "Fixed asset transfer", "asset", "none",
     ["journal", "asset_transfer"]),
    ("fa_disposal", "Fixed asset disposal", "asset", "none",
     ["journal", "asset_disposal"]),
]

BY_ID = {s[0]: s for s in SCENARIOS}
ALL_IDS = [s[0] for s in SCENARIOS]


def by_category():
    """Scenarios grouped for the UI, in catalogue order."""
    out = []
    for key, title in CATEGORIES:
        items = [(sid, label, doc)
                 for sid, label, cat, doc, _ in SCENARIOS if cat == key]
        out.append((key, title, items))
    return out


def tags(sid):
    return BY_ID[sid][4]


def doc_kind(sid):
    return BY_ID[sid][3]


def label(sid):
    return BY_ID[sid][1]


def makes_pdf(sid):
    return BY_ID[sid][3] != "none"
