"""Adapt a Txn onto the existing invoice renderer.

The renderer was written against the older invoice dict, so this translates a
catalogue transaction into that shape rather than duplicating the layout.
"""
from decimal import Decimal

from .model import money, half_tax, rupees_in_words
from .render import render as render_legacy


def _summary(txn):
    """HSN-wise tax summary, grouped by code and rate."""
    groups = {}
    for l in txn.lines:
        g = groups.setdefault((l.code, l.gst),
                              {"taxable": Decimal(0), "tax": Decimal(0),
                               "cess": Decimal(0)})
        g["taxable"] += l.taxable
        g["tax"] += l.tax
    for c in txn.charges:
        if c.code:
            g = groups.setdefault((c.code, c.gst),
                                  {"taxable": Decimal(0), "tax": Decimal(0),
                                   "cess": Decimal(0)})
            g["taxable"] += c.amount
            g["tax"] += c.tax
    return [{"code": k[0], "gst": k[1],
             **{kk: money(vv) for kk, vv in v.items()}}
            for k, v in sorted(groups.items(), key=lambda kv: kv[0])]


def _as_letterhead(p):
    """A trading party rendered as the issuer at the top of the page."""
    return {
        "name": p.get("name", ""),
        "gstin": p.get("gstin", ""),
        "state": p.get("state", ""),
        "addr": p.get("bill", []),
        "mobile": p.get("phone", ""),
        "bank": {"name": "-", "account": "-", "ifsc": "-", "branch": "-"},
    }


def _as_party(s):
    """Our own firm rendered as the party being billed."""
    return {
        "name": s["name"], "gstin": s["gstin"], "state": s["state"],
        "state_code": s.get("state_code", s["gstin"][:2]),
        "bill": s["addr"], "ship": s["addr"],
        "phone": s.get("mobile"),
        "tally_ledger": s["name"],
    }


def _build_view(txn, seller):
    """Draw the document from the point of view of whoever ISSUED it.

    We issue our own sales invoices, so we are the letterhead and the buyer
    is the customer. A purchase bill was issued to us BY the supplier, so on
    those the roles swap: the supplier heads the page and we are the party
    being billed.
    """
    m = txn.meta
    party = txn.party or {}
    inter = txn.interstate
    # A purchase invoice is by definition a bill issued TO us, whatever the
    # scenario that produced it. A debit note we raise against a supplier is
    # our own document, so it keeps our letterhead.
    incoming = txn.kind == "purchase_invoice"

    if incoming:
        seller, party = _as_letterhead(party), _as_party(seller)
    tax = m.get("tax", Decimal(0))
    is_order = txn.kind in ("purchase_order", "sales_order")

    inv = {
        "number": txn.number,
        "date": txn.date.strftime("%d %b %Y"),
        "date_iso": txn.date.isoformat(),
        "doc_title": txn.title,
        "is_order": is_order,
        # a bill of supply carries no tax at all, so the renderer drops the
        # tax column, the tax summary columns and the CGST/SGST total rows
        "no_tax": bool(m.get("no_tax")),
        # who stands in the letterhead: on documents we raise ourselves
        # against a supplier we are the buyer, otherwise the seller
        "letterhead_is_buyer": txn.kind in ("purchase_order",
                                            "debit_note") and not incoming,
        # a purchase document arrives from the supplier, so the party block
        # is labelled from our side of the transaction
        # only an order we RAISE is labelled from the supplier's side; an
        # incoming bill names us as its customer
        "is_purchase": (txn.kind == "purchase_order"
                        or (txn.kind in ("purchase_invoice", "debit_note")
                            and not incoming)),
        "place_of_supply": f"{party.get('state_code','27')}-"
                           f"{party.get('state','MAHARASHTRA')}",
        "buyer": {
            "name": party.get("name", ""),
            "gstin": party.get("gstin"),
            "state": party.get("state", ""),
            "bill": party.get("bill", []),
            "ship": party.get("ship", party.get("bill", [])),
            "phone": party.get("phone"),
        },
        "lines": txn.lines,
        "charges": txn.charges,
        "reference": (None if is_order else
                      (f"Against Order: {m['against_order']}"
                       if m.get("against_order") else None)),
        "original_invoice": m.get("original_invoice"),
        "order_terms": m.get("order_terms"),
        "scanned": False,
        "tds": ({"section": m["tds"]["section"],
                 "rate": Decimal(str(m["tds"]["rate"]))}
                if m.get("tds") else None),
    }

    half = half_tax(tax)
    t = {
        "taxable": m.get("taxable", Decimal(0)),
        "tax": tax,
        "cess": Decimal(0),
        "discount": money(sum(l.discount_value for l in txn.lines)),
        "charges": m.get("charges", Decimal(0)),
        "round_off": m.get("round_off", Decimal(0)),
        "total": m.get("total", Decimal(0)),
        "reverse_charge": bool(m.get("rcm")),
        "tds": m.get("tds_amount", Decimal(0)),
        "tcs": m.get("tcs", Decimal(0)),
        "cash_discount": m.get("cash_discount", Decimal(0)),
        "customs_duty": m.get("customs_duty", Decimal(0)),
        "advance": m.get("advance", Decimal(0)),
        "cgst": Decimal(0) if inter else half,
        "sgst": Decimal(0) if inter else half,
        "igst": tax if inter else Decimal(0),
        "interstate": inter,
        "summary": _summary(txn),
        "qty": sum(l.qty for l in txn.lines if l.kind == "goods"),
        "count": len(txn.lines),
        "rates": sorted({float(l.gst) for l in txn.lines}),
    }
    t["words"] = rupees_in_words(t["total"])
    # `seller` may have been swapped above, so return the one to draw with
    return inv, t, seller


def render_document(txn, seller, path, pattern="classic"):
    """Draw the document, in whichever layout was asked for."""
    inv, t, head = _build_view(txn, seller)
    if pattern and pattern != "classic":
        from . import patterns as P
        if pattern in P.BY_ID:
            P.draw(pattern, inv, t, head, path)
            return
    render_legacy(inv, t, head, path)
