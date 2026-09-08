"""The firm whose documents these are.

Out of the box the tool ships with a sample firm so it works immediately.
A real user sets their own once, and it is saved beside their documents
rather than inside the program - so an update never wipes it, and the
sample data stays exactly that.
"""
import json
import os

APP_DIR = "GST Document Generator"
FILE = "company.json"

FIELDS = ("name", "gstin", "state", "state_code", "addr1", "addr2",
          "mobile", "bank_name", "bank_account", "bank_ifsc", "bank_branch",
          "logo")


def settings_dir():
    """Where a user's own settings live, per platform."""
    base = (os.environ.get("APPDATA")
            or os.path.expanduser("~/.config"))
    d = os.path.join(base, APP_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def path():
    return os.path.join(settings_dir(), FILE)


def load():
    """The saved firm, or None when the user has not set one."""
    try:
        with open(path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if d.get("name") else None
    except (OSError, ValueError):
        return None


def save(d):
    """Store the firm. Returns the file written."""
    clean = {k: str(d.get(k, "")).strip() for k in FIELDS}
    with open(path(), "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)
    return path()


def clear():
    """Go back to the sample firm."""
    try:
        os.remove(path())
        return True
    except OSError:
        return False


def as_seller(d):
    """Turn saved settings into the seller shape every renderer expects."""
    gstin = (d.get("gstin") or "").strip().upper()
    addr = [a for a in (d.get("addr1"), d.get("addr2")) if (a or "").strip()]
    bank = {}
    if (d.get("bank_name") or "").strip():
        bank = {"name": d.get("bank_name", ""),
                "account": d.get("bank_account", ""),
                "ifsc": d.get("bank_ifsc", ""),
                "branch": d.get("bank_branch", "")}
    return {
        "name": (d.get("name") or "").strip(),
        "gstin": gstin,
        "state": (d.get("state") or "").strip(),
        # the first two digits of a GSTIN are the state code
        "state_code": (d.get("state_code") or "").strip() or gstin[:2],
        "addr": addr,
        "mobile": (d.get("mobile") or "").strip(),
        "bank": bank,
        "logo": (d.get("logo") or "").strip() or None,
    }


def active_seller(sample):
    """The firm to put on documents: the user's if set, else the sample."""
    saved = load()
    return as_seller(saved) if saved else sample


def is_sample(seller):
    """True while the shipped sample firm is still in use."""
    return not load()
