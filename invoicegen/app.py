"""Desktop window for the document generator.

Two tabs: the Tally scenario catalogue (102 named events) and the original
custom option builder. Written for someone who has never opened a terminal -
tick, choose a folder, click Generate.
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from . import catalogue as cat
from . import chains
from . import patterns as pat
from .generate import run as run_custom
from .run_scenarios import run_scenarios
from .scenarios import PANELS

APP_NAME = "GST Document Generator"
AUTHOR = ""

# ---- palette -------------------------------------------------------------
INK = "#0f1720"          # primary text
MUTED = "#68727e"        # secondary text
FAINT = "#96a0ac"        # tertiary text
BG = "#eceff4"           # window
CARD = "#ffffff"         # panels
STRIP = "#f7f9fc"        # panel title bar
EDGE = "#dbe1e9"         # hairlines
ACCENT = "#2563eb"       # brand
ACCENT_D = "#1d4ed8"
ACCENT_L = "#eff4ff"
HEAD_BG = "#0f1c30"      # header band
HEAD_INK = "#ffffff"
HEAD_SUB = "#9db2d0"
OK_BG = "#e9f7ef"
OK_INK = "#0b6b3a"
ERR_BG = "#fdecec"
ERR_INK = "#a51f19"

# one colour per group, so the eye can find a section quickly
GROUP_TINT = {
    "purchase": "#2f6fd0", "sales": "#0f8a6a", "receipt": "#7a4fd0",
    "payment": "#c2456b", "bank": "#1f7fa8", "expense": "#c07a12",
    "asset": "#5b6b8c",
}
PANEL_TINT = ["#2f6fd0", "#0f8a6a", "#7a4fd0", "#c2456b",
              "#1f7fa8", "#c07a12", "#5b6b8c", "#3f7d5a"]


def default_outdir():
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    base = desktop if os.path.isdir(desktop) else os.path.expanduser("~")
    return os.path.join(base, "Generated Documents")


def open_folder(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)                                # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


class Scroller(ttk.Frame):
    """A vertically scrolling area that tracks the window width."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical",
                                 command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._win,
                                                          width=e.width))
        # wheel scrolling only while the pointer is over this area
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _):
        self.canvas.bind_all("<MouseWheel>", self._wheel)

    def _unbind_wheel(self, _):
        self.canvas.unbind_all("<MouseWheel>")

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 60), "units")


class App:
    def __init__(self, root):
        self.root = root
        self.scen_vars = {}       # scenario id -> BooleanVar
        self.opt_vars = {}        # custom option id -> BooleanVar
        self.pat_vars = {}        # pattern id -> BooleanVar
        self.q = queue.Queue()
        self.busy = False
        self._last_out = None
        self._last_gen_tab = True

        root.title(APP_NAME)
        root.configure(bg=BG)
        root.minsize(1060, 740)
        try:
            root.state("zoomed")
        except tk.TclError:
            pass

        self._style()
        self._header()
        self._tabs()
        self._controls()
        self._status()
        self._update_count()
        root.after(80, self._drain)

    # -------------------------------------------------------------- chrome

    def _style(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", background=BG, foreground=INK, font=("Segoe UI", 10))
        s.configure("TFrame", background=BG)
        s.configure("TCheckbutton", background=CARD, foreground=INK,
                    font=("Segoe UI", 9), focuscolor=CARD)
        s.map("TCheckbutton", background=[("active", CARD)],
              foreground=[("active", ACCENT)])

        s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=0)
        s.configure("TNotebook.Tab", padding=(24, 11), background=BG,
                    foreground=MUTED, font=("Segoe UI", 10, "bold"),
                    borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", CARD)],
              foreground=[("selected", ACCENT)])

        s.configure("Go.TButton", font=("Segoe UI", 11, "bold"),
                    padding=(34, 11), background=ACCENT, foreground="#fff",
                    borderwidth=0, focuscolor=ACCENT)
        s.map("Go.TButton", background=[("pressed", ACCENT_D),
                                        ("active", ACCENT_D),
                                        ("disabled", "#a9c0ee")])
        s.configure("Ghost.TButton", font=("Segoe UI", 9), padding=(11, 6),
                    background=CARD, foreground=ACCENT, borderwidth=1,
                    focuscolor=CARD)
        s.map("Ghost.TButton", background=[("active", ACCENT_L)])
        s.configure("Mini.TButton", font=("Segoe UI", 8), padding=(7, 2),
                    background=STRIP, foreground=MUTED, borderwidth=1,
                    focuscolor=STRIP)
        s.map("Mini.TButton", background=[("active", ACCENT_L)],
              foreground=[("active", ACCENT)])
        s.configure("Thin.Horizontal.TProgressbar", troughcolor=EDGE,
                    background=ACCENT, borderwidth=0, thickness=6)

    def _header(self):
        bar = tk.Frame(self.root, bg=HEAD_BG)
        bar.pack(fill="x")
        inner = tk.Frame(bar, bg=HEAD_BG)
        inner.pack(fill="x", padx=28, pady=(15, 14))

        left = tk.Frame(inner, bg=HEAD_BG)
        left.pack(side="left", anchor="w")
        tk.Label(left, text=APP_NAME, bg=HEAD_BG, fg=HEAD_INK,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(left, bg=HEAD_BG, fg=HEAD_SUB, font=("Segoe UI", 10),
                 text="Pick the documents you need, choose a folder, "
                      "and click Generate.").pack(anchor="w", pady=(2, 0))

        tk.Label(inner, text=AUTHOR, bg=HEAD_BG, fg=HEAD_SUB,
                 font=("Segoe UI", 9)).pack(side="right", anchor="se")
        tk.Frame(self.root, bg=ACCENT, height=3).pack(fill="x")

    # --------------------------------------------------------------- tabs

    def _tabs(self):
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill="both", expand=True, padx=20, pady=(12, 0))
        self.nb = ttk.Notebook(wrap)
        self.nb.pack(fill="both", expand=True)

        self.tab_co = tk.Frame(self.nb, bg=CARD)
        self.nb.add(self.tab_co, text="  My Company  ")
        self.tab_scen = tk.Frame(self.nb, bg=CARD)
        self.tab_opt = tk.Frame(self.nb, bg=CARD)
        self.tab_pat = tk.Frame(self.nb, bg=CARD)
        self.nb.add(self.tab_scen, text="  Tally Scenarios  ")
        self.nb.add(self.tab_opt, text="  Custom Mix  ")
        self.nb.add(self.tab_pat, text="  Patterns  ")
        self.tab_man = tk.Frame(self.nb, bg=CARD)
        self.nb.add(self.tab_man, text="  Manual Entry  ")
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._update_count())

        self._build_company(self.tab_co)
        self._build_scenarios(self.tab_scen)
        self._build_options(self.tab_opt)
        self._build_patterns(self.tab_pat)
        self._build_manual(self.tab_man)

    def _card(self, parent, title, tint, count=None, all_ids=None):
        """A titled panel with a coloured spine."""
        card = tk.Frame(parent, bg=CARD, highlightbackground=EDGE,
                        highlightthickness=1)
        head = tk.Frame(card, bg=STRIP)
        head.pack(fill="x")
        tk.Frame(head, bg=tint, width=4).pack(side="left", fill="y")
        tk.Label(head, text=title.upper(), bg=STRIP, fg=tint,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=8,
                                                    pady=7)
        if count is not None:
            tk.Label(head, text=str(count), bg=STRIP, fg=FAINT,
                     font=("Segoe UI", 8)).pack(side="left")
        if all_ids:
            ttk.Button(head, text="all", style="Mini.TButton",
                       command=lambda k=all_ids: self._set_some(k, True)
                       ).pack(side="right", padx=(0, 6))
        body = tk.Frame(card, bg=CARD)
        body.pack(fill="both", expand=True, padx=9, pady=(6, 9))
        return card, body

    def _toolbar(self, parent, text, store):
        bar = tk.Frame(parent, bg=CARD)
        bar.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(bar, bg=CARD, fg=MUTED, font=("Segoe UI", 9),
                 text=text, justify="left").pack(side="left")
        ttk.Button(bar, text="Clear all", style="Mini.TButton",
                   command=lambda: self._set(store, False)).pack(side="right",
                                                                 padx=3)
        ttk.Button(bar, text="Select all", style="Mini.TButton",
                   command=lambda: self._set(store, True)).pack(side="right",
                                                                padx=3)

    def _build_scenarios(self, parent):
        self._toolbar(parent,
                      "Each box is one Tally event. Events that need an "
                      "earlier document generate the whole linked set.",
                      self.scen_vars)

        sc = Scroller(parent, bg=CARD)
        sc.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        grid = sc.body
        cols = 3
        for i in range(cols):
            grid.columnconfigure(i, weight=1, uniform="sc")

        for n, (key, title, items) in enumerate(cat.by_category()):
            r, c = divmod(n, cols)
            tint = GROUP_TINT.get(key, ACCENT)
            ids = [i[0] for i in items]
            card, body = self._card(grid, title, tint, len(items), ids)
            card.grid(row=r, column=c, sticky="nsew", padx=6, pady=6)

            for sid, label, doc in items:
                v = tk.BooleanVar(value=False)
                v.trace_add("write", lambda *_: self._update_count())
                self.scen_vars[sid] = v
                row = tk.Frame(body, bg=CARD)
                row.pack(fill="x", anchor="w")
                ttk.Checkbutton(row, text=label, variable=v).pack(side="left")
                # say what this scenario actually produces
                if doc == "none":
                    tk.Label(row, text="no PDF", bg=CARD, fg=FAINT,
                             font=("Segoe UI", 8)).pack(side="right")
                elif chains.is_chained(sid):
                    tk.Label(row, text="+%d" % (chains.chain_length(sid) - 1),
                             bg=CARD, fg=tint,
                             font=("Segoe UI", 8, "bold")).pack(side="right")

        legend = tk.Frame(parent, bg=CARD)
        legend.pack(fill="x", padx=18, pady=(0, 10))
        tk.Label(legend, text="+1", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(legend, text="also creates the linked earlier document",
                 bg=CARD, fg=FAINT, font=("Segoe UI", 8)).pack(side="left",
                                                               padx=(4, 22))
        tk.Label(legend, text="no PDF", bg=CARD, fg=FAINT,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Label(legend, text="journal entry - data file only, no document",
                 bg=CARD, fg=FAINT, font=("Segoe UI", 8)).pack(side="left",
                                                               padx=(4, 0))

    def _build_options(self, parent):
        self._toolbar(parent,
                      "Mix your own invoices. Leave a group empty and it "
                      "varies freely across the batch.", self.opt_vars)

        sc = Scroller(parent, bg=CARD)
        sc.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        grid = sc.body
        cols = 4
        for i in range(cols):
            grid.columnconfigure(i, weight=1, uniform="op")

        for n, (title, _key, opts) in enumerate(PANELS):
            r, c = divmod(n, cols)
            card, body = self._card(grid, title,
                                    PANEL_TINT[n % len(PANEL_TINT)])
            card.grid(row=r, column=c, sticky="nsew", padx=6, pady=6)
            for oid, label, default in opts:
                v = tk.BooleanVar(value=default)
                v.trace_add("write", lambda *_: self._update_count())
                self.opt_vars[oid] = v
                ttk.Checkbutton(body, text=label, variable=v).pack(
                    anchor="w", pady=1)

    def _build_patterns(self, parent):
        self._toolbar(parent,
                      "Every invoice is drawn in each layout you tick. Same "
                      "numbers, different appearance - so a parser has to "
                      "cope with all of them.", self.pat_vars)

        sc = Scroller(parent, bg=CARD)
        sc.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        grid = sc.body
        cols = 3
        for i in range(cols):
            grid.columnconfigure(i, weight=1, uniform="pt")

        card, body = self._card(grid, "Invoice layouts", PANEL_TINT[0],
                                len(pat.PATTERNS))
        card.grid(row=0, column=0, columnspan=cols, sticky="nsew",
                  padx=6, pady=6)
        inner = tk.Frame(body, bg=CARD)
        inner.pack(fill="both", expand=True)
        for i in range(cols):
            inner.columnconfigure(i, weight=1, uniform="pl")
        for n, (pid, label, _fn) in enumerate(pat.PATTERNS):
            v = tk.BooleanVar(value=False)
            v.trace_add("write", lambda *_: self._update_count())
            self.pat_vars[pid] = v
            r, c = divmod(n, cols)
            ttk.Checkbutton(inner, text=label, variable=v).grid(
                row=r, column=c, sticky="w", padx=4, pady=2)

        note = tk.Frame(parent, bg=CARD)
        note.pack(fill="x", padx=18, pady=(0, 10))
        tk.Label(note, bg=CARD, fg=FAINT, font=("Segoe UI", 8),
                 text="Layouts apply to invoices, notes and orders. "
                      "Receipts, payments and journals keep their own look."
                 ).pack(side="left")


    # ------------------------------------------------------ manual entry

    def _field(self, parent, label, row, col, width=26, span=1):
        """One labelled entry box in a grid."""
        tk.Label(parent, text=label, bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8)).grid(row=row, column=col, sticky="w",
                                            padx=(0, 6), pady=(4, 0))
        v = tk.StringVar()
        e = tk.Entry(parent, textvariable=v, font=("Segoe UI", 9), width=width,
                     relief="solid", bd=1, highlightthickness=0)
        e.grid(row=row, column=col + 1, columnspan=span, sticky="we",
               padx=(0, 14), pady=(4, 0), ipady=2)
        v.trace_add("write", lambda *_: self._manual_changed())
        return v

    def _build_manual(self, parent):
        from .manual import ManualForm
        self.form = ManualForm()
        self.item_rows = []

        sc = Scroller(parent, bg=CARD)
        sc.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        body = sc.body

        # ---- logo
        card, inner = self._card(body, "Logo", PANEL_TINT[6])
        card.pack(fill="x", padx=6, pady=(6, 4))
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x")
        self.logo_var = tk.StringVar(value="No logo chosen")
        ttk.Button(row, text="Choose image...", style="Ghost.TButton",
                   command=self._pick_logo).pack(side="left")
        ttk.Button(row, text="Remove", style="Mini.TButton",
                   command=self._clear_logo).pack(side="left", padx=(6, 0))
        tk.Label(row, textvariable=self.logo_var, bg=CARD, fg=FAINT,
                 font=("Segoe UI", 8)).pack(side="left", padx=(12, 0))
        tk.Label(inner, bg=CARD, fg=FAINT, font=("Segoe UI", 8),
                 text="Printed in the top-left corner of the invoice. "
                      "PNG, JPG or GIF.").pack(anchor="w", pady=(4, 0))

        # ---- supplier
        card, inner = self._card(body, "Supplier  (whose letterhead)",
                                 PANEL_TINT[0])
        card.pack(fill="x", padx=6, pady=4)
        g = tk.Frame(inner, bg=CARD)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)
        g.columnconfigure(3, weight=1)
        self.f_sup_name = self._field(g, "Name", 0, 0, 30)
        self.f_sup_gstin = self._field(g, "GSTIN", 0, 2, 22)
        self.f_sup_a1 = self._field(g, "Address", 1, 0, 30)
        self.f_sup_a2 = self._field(g, "", 2, 0, 30)
        self.f_sup_phone = self._field(g, "Phone", 1, 2, 22)

        # ---- buyer
        card, inner = self._card(body, "Buyer  (the customer)", PANEL_TINT[1])
        card.pack(fill="x", padx=6, pady=4)
        g = tk.Frame(inner, bg=CARD)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)
        g.columnconfigure(3, weight=1)
        self.f_buy_name = self._field(g, "Name", 0, 0, 30)
        self.f_buy_gstin = self._field(g, "GSTIN", 0, 2, 22)
        self.f_buy_a1 = self._field(g, "Address", 1, 0, 30)
        self.f_buy_a2 = self._field(g, "", 2, 0, 30)

        # ---- invoice
        card, inner = self._card(body, "Invoice", PANEL_TINT[2])
        card.pack(fill="x", padx=6, pady=4)
        g = tk.Frame(inner, bg=CARD)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)
        g.columnconfigure(3, weight=1)
        g.columnconfigure(5, weight=1)
        self.f_inv_no = self._field(g, "Number", 0, 0, 20)
        self.f_inv_date = self._field(g, "Date", 0, 2, 16)
        self.f_inv_pos = self._field(g, "Place of Supply", 0, 4, 20)
        tk.Label(inner, bg=CARD, fg=FAINT, font=("Segoe UI", 8),
                 text="Leave the date blank for today. Inter-state is worked "
                      "out from the two GSTINs.").pack(anchor="w", pady=(4, 0))

        # ---- items
        card, inner = self._card(body, "Items", PANEL_TINT[3])
        card.pack(fill="both", expand=True, padx=6, pady=4)
        heads = [("", 3), ("Description", 34), ("HSN/SAC", 11), ("Qty", 7),
                 ("UOM", 6), ("Rate", 11), ("GST%", 6), ("Disc%", 6)]
        hdr = tk.Frame(inner, bg=CARD)
        hdr.pack(fill="x")
        for i, (h, w) in enumerate(heads):
            tk.Label(hdr, text=h, bg=CARD, fg=MUTED, width=w, anchor="w",
                     font=("Segoe UI", 8, "bold")).grid(row=0, column=i,
                                                        padx=1, sticky="w")
        self.items_frame = tk.Frame(inner, bg=CARD)
        self.items_frame.pack(fill="x")
        for _ in range(4):
            self._add_item_row()
        bar = tk.Frame(inner, bg=CARD)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="+ Add row", style="Ghost.TButton",
                   command=self._add_item_row).pack(side="left")

        # ---- other charges
        card, inner = self._card(body, "Other charges", PANEL_TINT[5])
        card.pack(fill="x", padx=6, pady=4)
        chd = tk.Frame(inner, bg=CARD)
        chd.pack(fill="x")
        for i, (h, w) in enumerate((("", 3), ("Label", 34), ("Amount", 13),
                                    ("GST%", 6))):
            tk.Label(chd, text=h, bg=CARD, fg=MUTED, width=w, anchor="w",
                     font=("Segoe UI", 8, "bold")).grid(row=0, column=i,
                                                        padx=1, sticky="w")
        self.charge_frame = tk.Frame(inner, bg=CARD)
        self.charge_frame.pack(fill="x")
        self.charge_rows = []
        for _ in range(2):
            self._add_charge_row()
        bar = tk.Frame(inner, bg=CARD)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="+ Add row", style="Ghost.TButton",
                   command=self._add_charge_row).pack(side="left")
        tk.Label(inner, bg=CARD, fg=FAINT, font=("Segoe UI", 8),
                 text="Freight, packing, insurance - anything you name. "
                      "Leave GST% at 0 if the charge is not taxed."
                 ).pack(anchor="w", pady=(4, 0))

        # ---- live totals
        card, inner = self._card(body, "Totals", PANEL_TINT[4])
        card.pack(fill="x", padx=6, pady=(4, 8))
        self.man_totals = tk.Label(inner, bg=CARD, fg=INK, justify="left",
                                   font=("Consolas", 10),
                                   text="nothing entered yet")
        self.man_totals.pack(anchor="w")
        self.man_note = tk.Label(inner, bg=CARD, fg=ERR_INK, justify="left",
                                 font=("Segoe UI", 8), text="")
        self.man_note.pack(anchor="w", pady=(4, 0))

    def _add_item_row(self):
        """One row of item entry boxes."""
        widths = [34, 11, 7, 6, 11, 6, 6]
        keys = ["desc", "hsn", "qty", "uom", "rate", "gst", "disc"]
        r = len(self.item_rows)
        tk.Label(self.items_frame, text=str(r + 1), bg=CARD, fg=FAINT,
                 width=3, anchor="w", font=("Segoe UI", 8)).grid(
            row=r, column=0, padx=1, pady=1)
        vars_ = {}
        for i, (k, w) in enumerate(zip(keys, widths)):
            v = tk.StringVar(value="PCS" if k == "uom"
                             else "18" if k == "gst" else "")
            e = tk.Entry(self.items_frame, textvariable=v, width=w,
                         font=("Segoe UI", 9), relief="solid", bd=1,
                         highlightthickness=0)
            e.grid(row=r, column=i + 1, padx=1, pady=1, sticky="we")
            v.trace_add("write", lambda *_: self._manual_changed())
            vars_[k] = v
        self.item_rows.append(vars_)
        self._manual_changed()

    def _add_charge_row(self):
        """One row of charge entry boxes."""
        r = len(self.charge_rows)
        tk.Label(self.charge_frame, text=str(r + 1), bg=CARD, fg=FAINT,
                 width=3, anchor="w", font=("Segoe UI", 8)).grid(
            row=r, column=0, padx=1, pady=1)
        vars_ = {}
        for i, (k, w) in enumerate((("label", 34), ("amount", 13),
                                    ("gst", 6))):
            v = tk.StringVar(value="0" if k == "gst" else "")
            tk.Entry(self.charge_frame, textvariable=v, width=w,
                     font=("Segoe UI", 9), relief="solid", bd=1,
                     highlightthickness=0).grid(row=r, column=i + 1, padx=1,
                                                pady=1, sticky="we")
            v.trace_add("write", lambda *_: self._manual_changed())
            vars_[k] = v
        self.charge_rows.append(vars_)
        self._manual_changed()

    def _pick_logo(self):
        p = filedialog.askopenfilename(
            title="Choose a logo image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp"),
                       ("All files", "*.*")])
        if p:
            self.form.logo = p
            self.logo_var.set(os.path.basename(p))
            self._manual_changed()

    def _clear_logo(self):
        self.form.logo = None
        self.logo_var.set("No logo chosen")
        self._manual_changed()

    def _read_form(self):
        """Copy what is on screen into the form object."""
        f = self.form
        f.supplier.update(name=self.f_sup_name.get(),
                          gstin=self.f_sup_gstin.get(),
                          addr1=self.f_sup_a1.get(), addr2=self.f_sup_a2.get(),
                          phone=self.f_sup_phone.get())
        f.buyer.update(name=self.f_buy_name.get(),
                       gstin=self.f_buy_gstin.get(),
                       addr1=self.f_buy_a1.get(), addr2=self.f_buy_a2.get())
        f.invoice.update(number=self.f_inv_no.get(),
                         date=self.f_inv_date.get(), pos=self.f_inv_pos.get())
        f.items = [{k: v.get() for k, v in row.items()}
                   for row in self.item_rows]
        f.charges = [{k: v.get() for k, v in row.items()}
                     for row in getattr(self, "charge_rows", [])]
        return f

    def _manual_changed(self, *_):
        """Recompute the live totals on every keystroke."""
        if not hasattr(self, "man_totals"):
            return
        try:
            f = self._read_form()
            t = f.totals()
            fig = lambda v: "{:,.2f}".format(v)
            head = "  %d item%s" % (t["count"],
                                  "" if t["count"] == 1 else "s")
            if t.get("n_charges"):
                head += " + %d charge%s" % (
                    t["n_charges"], "" if t["n_charges"] == 1 else "s")
            parts = [head, "  Taxable %14s" % fig(t["taxable"])]
            if t.get("charges"):
                parts.append("  Charges %14s" % fig(t["charges"]))
            parts += ["  Tax     %14s" % fig(t["tax"]),
                      "  Round   %14s" % fig(t["round_off"]),
                      "  TOTAL   %14s" % fig(t["total"])]
            self.man_totals.configure(text="\n".join(parts))
            notes = []
            probs = f.problems()
            if probs:
                notes.append("Still needed: " + ", ".join(probs))
            notes += f.warnings()
            self.man_note.configure(text="   ".join(notes))
            self._update_count()
        except Exception:
            pass


    # ---------------------------------------------------------- my company

    def _build_company(self, parent):
        from . import company
        self.co_vars = {}

        sc = Scroller(parent, bg=CARD)
        sc.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        body = sc.body

        tk.Label(body, bg=CARD, fg=MUTED, font=("Segoe UI", 9),
                 justify="left", wraplength=760,
                 text="The firm whose name appears on every document. Until "
                      "you set one, the sample firm is used. Saved on this "
                      "machine, so you only enter it once."
                 ).pack(anchor="w", padx=6, pady=(0, 8))

        def field(g, label, key, row, col, width=30, span=1):
            tk.Label(g, text=label, bg=CARD, fg=MUTED,
                     font=("Segoe UI", 8)).grid(row=row, column=col,
                                                sticky="w", padx=(0, 6),
                                                pady=(4, 0))
            v = tk.StringVar()
            tk.Entry(g, textvariable=v, font=("Segoe UI", 9), width=width,
                     relief="solid", bd=1, highlightthickness=0).grid(
                row=row, column=col + 1, columnspan=span, sticky="we",
                padx=(0, 14), pady=(4, 0), ipady=2)
            v.trace_add("write", lambda *_: self._company_changed())
            self.co_vars[key] = v
            return v

        card, inner = self._card(body, "Firm", PANEL_TINT[0])
        card.pack(fill="x", padx=6, pady=4)
        g = tk.Frame(inner, bg=CARD)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)
        g.columnconfigure(3, weight=1)
        field(g, "Name", "name", 0, 0, 34)
        field(g, "GSTIN", "gstin", 0, 2, 22)
        field(g, "Address", "addr1", 1, 0, 34)
        field(g, "State", "state", 1, 2, 22)
        field(g, "", "addr2", 2, 0, 34)
        field(g, "Phone", "mobile", 2, 2, 22)

        card, inner = self._card(body, "Bank details  (optional)",
                                 PANEL_TINT[1])
        card.pack(fill="x", padx=6, pady=4)
        g = tk.Frame(inner, bg=CARD)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)
        g.columnconfigure(3, weight=1)
        field(g, "Bank", "bank_name", 0, 0, 30)
        field(g, "Account #", "bank_account", 0, 2, 22)
        field(g, "IFSC", "bank_ifsc", 1, 0, 30)
        field(g, "Branch", "bank_branch", 1, 2, 22)

        card, inner = self._card(body, "Logo  (optional)", PANEL_TINT[2])
        card.pack(fill="x", padx=6, pady=4)
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x")
        self.co_logo = tk.StringVar(value="No logo chosen")
        ttk.Button(row, text="Choose image...", style="Ghost.TButton",
                   command=self._pick_co_logo).pack(side="left")
        ttk.Button(row, text="Remove", style="Mini.TButton",
                   command=self._clear_co_logo).pack(side="left", padx=(6, 0))
        tk.Label(row, textvariable=self.co_logo, bg=CARD, fg=FAINT,
                 font=("Segoe UI", 8)).pack(side="left", padx=(12, 0))
        self.co_vars["logo"] = tk.StringVar()

        bar = tk.Frame(body, bg=CARD)
        bar.pack(fill="x", padx=6, pady=(10, 6))
        ttk.Button(bar, text="Save", style="Go.TButton",
                   command=self._save_company).pack(side="left")
        ttk.Button(bar, text="Use the sample firm instead",
                   style="Ghost.TButton",
                   command=self._clear_company).pack(side="left", padx=(10, 0))
        self.co_note = tk.Label(body, bg=CARD, fg=MUTED, justify="left",
                                font=("Segoe UI", 9), text="")
        self.co_note.pack(anchor="w", padx=6, pady=(0, 10))

        saved = company.load()
        if saved:
            for k, v in self.co_vars.items():
                v.set(saved.get(k, ""))
            if saved.get("logo"):
                self.co_logo.set(os.path.basename(saved["logo"]))
        self._company_changed()

    def _pick_co_logo(self):
        p = filedialog.askopenfilename(
            title="Choose your logo",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp"),
                       ("All files", "*.*")])
        if p:
            self.co_vars["logo"].set(p)
            self.co_logo.set(os.path.basename(p))

    def _clear_co_logo(self):
        self.co_vars["logo"].set("")
        self.co_logo.set("No logo chosen")

    def _company_changed(self, *_):
        if not hasattr(self, "co_note"):
            return
        from . import company
        from .manual import gstin_ok
        saved = company.load()
        bits = []
        if saved:
            bits.append("Using your firm: %s" % saved.get("name", ""))
        else:
            bits.append("Using the sample firm until you save your own.")
        g = self.co_vars["gstin"].get().strip()
        if g and not gstin_ok(g):
            bits.append("That GSTIN does not look valid (allowed, but check).")
        self.co_note.configure(text="   ".join(bits))

    def _save_company(self):
        from . import company
        d = {k: v.get() for k, v in self.co_vars.items()}
        if not d.get("name", "").strip():
            self.co_note.configure(text="Enter a firm name before saving.",
                                   fg=ERR_INK)
            return
        company.save(d)
        self.co_note.configure(fg=OK_INK,
                               text="Saved. Every document now carries %s."
                                    % d["name"].strip())

    def _clear_company(self):
        from . import company
        company.clear()
        for v in self.co_vars.values():
            v.set("")
        self.co_logo.set("No logo chosen")
        self.co_note.configure(fg=MUTED,
                               text="Back to the sample firm.")

    # ----------------------------------------------------------- controls

    def _controls(self):
        card = tk.Frame(self.root, bg=CARD, highlightbackground=EDGE,
                        highlightthickness=1)
        card.pack(fill="x", padx=20, pady=(10, 4))
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=16, pady=13)
        row.columnconfigure(1, weight=1)

        tk.Label(row, text="HOW MANY OF EACH", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=0,
                                                    sticky="w")
        self.count = tk.StringVar(value="1")
        self.count.trace_add("write", lambda *_: self._update_count())
        tk.Spinbox(row, from_=1, to=200, textvariable=self.count, width=6,
                   font=("Segoe UI", 12), justify="center", relief="solid",
                   bd=1, highlightthickness=0, buttondownrelief="flat",
                   buttonuprelief="flat").grid(row=1, column=0, sticky="w",
                                               pady=(4, 0))

        # per-document detail: how many lines, and whether to show a discount
        detail = tk.Frame(row, bg=CARD)
        detail.grid(row=0, column=1, rowspan=2, sticky="w", padx=(26, 0))

        tk.Label(detail, text="LINES PER DOCUMENT", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=0,
                                                    columnspan=5, sticky="w")
        tk.Label(detail, text="Goods", bg=CARD, fg=INK,
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w",
                                            pady=(4, 0))
        self.goods_lines = tk.StringVar(value="Any")
        ttk.Combobox(detail, textvariable=self.goods_lines, width=5,
                     state="readonly", font=("Segoe UI", 10),
                     values=("Any", "1", "2", "3", "4", "5", "6", "8", "10",
                             "15", "20")).grid(row=1, column=1, sticky="w",
                                               padx=(6, 16), pady=(4, 0))
        tk.Label(detail, text="Services", bg=CARD, fg=INK,
                 font=("Segoe UI", 9)).grid(row=1, column=2, sticky="w",
                                            pady=(4, 0))
        self.service_lines = tk.StringVar(value="Any")
        ttk.Combobox(detail, textvariable=self.service_lines, width=5,
                     state="readonly", font=("Segoe UI", 10),
                     values=("Any", "1", "2", "3", "4", "5", "6", "8", "10",
                             "15", "20")).grid(row=1, column=3, sticky="w",
                                               padx=(6, 18), pady=(4, 0))
        self.want_discount = tk.BooleanVar(value=False)
        ttk.Checkbutton(detail, text="Show discount on lines",
                        variable=self.want_discount).grid(
            row=1, column=4, sticky="w", pady=(4, 0))

        # output format - a PNG is a picture of the PDF, so both can be had
        tk.Label(detail, text="SAVE AS", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=5,
                                                    sticky="w", padx=(22, 0))
        fmt = tk.Frame(detail, bg=CARD)
        fmt.grid(row=1, column=5, sticky="w", padx=(22, 0), pady=(4, 0))
        self.want_pdf = tk.BooleanVar(value=True)
        self.want_png = tk.BooleanVar(value=False)
        ttk.Checkbutton(fmt, text="PDF", variable=self.want_pdf,
                        command=self._keep_one_format).pack(side="left")
        ttk.Checkbutton(fmt, text="PNG", variable=self.want_png,
                        command=self._keep_one_format).pack(side="left",
                                                            padx=(10, 0))

        tk.Label(row, text="SAVE TO FOLDER", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(row=2, column=1,
                                                    sticky="w", padx=(26, 0))
        self.outdir = tk.StringVar(value=default_outdir())
        tk.Entry(row, textvariable=self.outdir, font=("Segoe UI", 10),
                 relief="solid", bd=1, highlightthickness=0).grid(
            row=3, column=1, sticky="we", padx=(26, 8), pady=(4, 0), ipady=5)
        ttk.Button(row, text="Browse...", style="Ghost.TButton",
                   command=self._browse).grid(row=3, column=2, pady=(4, 0))

        right = tk.Frame(row, bg=CARD)
        right.grid(row=0, column=3, rowspan=4, sticky="e",
                   padx=(18, 0), pady=(4, 0))
        self.summary = tk.Label(right, text="", bg=CARD, fg=MUTED,
                                font=("Segoe UI", 9))
        self.summary.pack(side="left", padx=(0, 14))
        self.go = ttk.Button(right, text="Generate", style="Go.TButton",
                             command=self._start)
        self.go.pack(side="left")

    def _status(self):
        self.status = tk.Frame(self.root, bg=BG)
        self.status.pack(fill="x", padx=20, pady=(0, 4))
        self.bar = ttk.Progressbar(self.status,
                                   style="Thin.Horizontal.TProgressbar")
        self.note = tk.Frame(self.status, bg=BG)
        self.msg = tk.Label(self.note, text="", bg=BG, fg=MUTED,
                            font=("Segoe UI", 10), anchor="w", justify="left")
        self.msg.pack(side="left", padx=12, pady=9)
        self.openbtn = ttk.Button(self.note, text="Open folder",
                                  style="Ghost.TButton", command=self._open)

        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill="x", padx=22, pady=(2, 10))
        tk.Label(foot, bg=BG, fg=FAINT, font=("Segoe UI", 8),
                 text="Documents are saved into the folder you chose, with a "
                      "summary in manifest.csv.  Sample data - not for real "
                      "billing."
                 ).pack(side="left")
        tk.Label(foot, text=AUTHOR, bg=BG, fg=FAINT,
                 font=("Segoe UI", 8)).pack(side="right")

    # ------------------------------------------------------------ actions

    def _manual_tab(self):
        return self.nb.index(self.nb.select()) == 4

    def _scenario_tab(self):
        # 0 My Company, 1 Scenarios, 2 Custom Mix, 3 Patterns, 4 Manual.
        # Only 1 and 2 generate; the others fall back to whichever was last.
        idx = self.nb.index(self.nb.select())
        if idx in (0, 3, 4):
            return self._last_gen_tab
        self._last_gen_tab = idx == 1
        return idx == 1

    def _set(self, store, val):
        for v in store.values():
            v.set(val)

    def _set_some(self, ids, val):
        for i in ids:
            if i in self.scen_vars:
                self.scen_vars[i].set(val)

    def _update_count(self):
        """Tell the user up front how many files this will produce.

        Checkbox traces fire while the tabs are still being built, before the
        controls exist, so this must be safe to call at any point.
        """
        if not hasattr(self, "summary"):
            return
        try:
            n = max(1, int(self.count.get()))
        except (ValueError, tk.TclError, AttributeError):
            n = 1
        try:
            if self.nb.index(self.nb.select()) == 0:
                # My Company is a settings tab, not a generator
                self.summary.configure(
                    text="set your firm here, then use the other tabs")
                self.go.configure(state="disabled")
                return
            if self.nb.index(self.nb.select()) == 3:
                # Patterns is a modifier, so it reports what it will apply
                n = sum(1 for v in self.pat_vars.values() if v.get())
                self.summary.configure(
                    text=("%d layout%s selected" % (n, "" if n == 1 else "s"))
                    if n else "no layout selected - Classic will be used")
                self.go.configure(state="normal")
                return
            if self._manual_tab():
                npat = max(1, sum(1 for v in self.pat_vars.values()
                                  if v.get()))
                ready = not self._read_form().problems()
                self.summary.configure(
                    text=("1 invoice  ->  %d file%s" % (npat, "" if npat == 1
                                                        else "s"))
                    if ready else "fill in the form to generate")
                self.go.configure(state="normal" if ready else "disabled")
                return
            if self._scenario_tab():
                picked = [s for s, v in self.scen_vars.items() if v.get()]
                docs = sum(chains.chain_length(s) for s in picked) * n
                pdfs = sum(sum(1 for step in chains.CHAINS.get(s, [s])
                               if cat.doc_kind(step) != "none")
                           for s in picked) * n
                npat = max(1, sum(1 for v in self.pat_vars.values()
                                  if v.get()))
                txt = "%d selected  ->  %d documents" % (len(picked), docs)
                if npat > 1:
                    txt += "  x %d layouts = %d files" % (npat, pdfs * npat)
                elif pdfs != docs:
                    txt += "  (%d PDFs)" % pdfs
                self.go.configure(state="normal" if picked else "disabled")
            else:
                picked = [o for o, v in self.opt_vars.items() if v.get()]
                npat = max(1, sum(1 for v in self.pat_vars.values()
                                  if v.get()))
                txt = "%d options  ->  %d invoices" % (len(picked), n)
                if npat > 1:
                    txt += "  x %d layouts = %d files" % (npat, n * npat)
                self.go.configure(state="normal")
            self.summary.configure(text=txt)
        except Exception:
            pass

    def _browse(self):
        d = filedialog.askdirectory(title="Choose where to save the documents",
                                    initialdir=self.outdir.get() or "~")
        if d:
            self.outdir.set(d)

    def _open(self):
        if self._last_out:
            open_folder(self._last_out)

    def _say(self, text, kind="info"):
        bg, fg = {"info": (BG, MUTED), "ok": (OK_BG, OK_INK),
                  "err": (ERR_BG, ERR_INK)}[kind]
        self.note.configure(bg=bg)
        self.msg.configure(text=text, bg=bg, fg=fg)
        self.note.pack(fill="x", pady=(4, 0))

    def _start(self):
        if self.busy:
            return
        if self._manual_tab():
            return self._start_manual()
        scen = self._scenario_tab()
        picked = [k for k, v in (self.scen_vars if scen
                                 else self.opt_vars).items() if v.get()]
        if scen and not picked:
            self._say("Please tick at least one scenario.", "err")
            return
        try:
            n = int(self.count.get())
        except ValueError:
            n = 0
        if not 1 <= n <= 200:
            self._say("Please enter a number between 1 and 200.", "err")
            return
        out = self.outdir.get().strip()
        if not out:
            self._say("Please choose a folder to save into.", "err")
            return
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            self._say("Cannot use that folder - %s" % e, "err")
            return

        self.busy = True
        self.go.configure(state="disabled")
        self.openbtn.pack_forget()
        self.bar.pack(fill="x", pady=(6, 2))
        self.bar.configure(maximum=max(1, len(picked) * n if scen else n),
                           value=0)
        def as_int(v):
            return None if v.get() == "Any" else int(v.get())

        opts = {"goods_lines": as_int(self.goods_lines),
                "service_lines": as_int(self.service_lines),
                "discount": self.want_discount.get()}
        formats = tuple(f for f, v in (("pdf", self.want_pdf),
                                       ("png", self.want_png)) if v.get())
        if not formats:
            formats = ("pdf",)
        pats = tuple(k for k, v in self.pat_vars.items() if v.get())
        if not pats:
            pats = ("classic",)

        self._say("Generating...")
        threading.Thread(target=self._work,
                         args=(scen, picked, n, out, opts, formats, pats),
                         daemon=True).start()

    def _keep_one_format(self):
        """At least one output format must stay ticked."""
        if not self.want_pdf.get() and not self.want_png.get():
            self.want_pdf.set(True)

    def _start_manual(self):
        """Generate the one invoice typed into the form."""
        f = self._read_form()
        probs = f.problems()
        if probs:
            self._say("Still needed: " + ", ".join(probs), "err")
            return
        out = self.outdir.get().strip()
        if not out:
            self._say("Please choose a folder to save into.", "err")
            return
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            self._say("Cannot use that folder - %s" % e, "err")
            return
        pats = tuple(k for k, v in self.pat_vars.items() if v.get())             or ("classic",)
        formats = tuple(x for x, v in (("pdf", self.want_pdf),
                                       ("png", self.want_png))
                        if v.get()) or ("pdf",)

        self.busy = True
        self.go.configure(state="disabled")
        self.openbtn.pack_forget()
        self.bar.pack(fill="x", pady=(6, 2))
        self.bar.configure(maximum=len(pats), value=0)
        self._say("Generating...")
        threading.Thread(target=self._work_manual,
                         args=(f, out, pats, formats), daemon=True).start()

    def _work_manual(self, form, out, pats, formats):
        try:
            from .manual import generate as gen_manual
            made = gen_manual(form, out, patterns=pats, formats=formats)
            self.q.put(("done", (len(made), len(made), len(made), out)))
        except Exception as e:
            self.q.put(("error", "%s: %s" % (type(e).__name__, e)))

    def _work(self, scen, picked, n, out, opts=None,
              formats=("pdf",), pats=("classic",)):
        try:
            def tick(i, t):
                self.q.put(("tick", i))

            if scen:
                rows = run_scenarios(picked, count=n, seed=None, outdir=out,
                                     progress=tick, opts=opts,
                                     formats=formats, patterns=pats)
            else:
                rows = run_custom(picked, count=n, seed=None, outdir=out,
                                  progress=tick, detail=opts,
                                  formats=formats, patterns=pats)
            # count whichever format was actually produced
            ext = ".pdf" if "pdf" in formats else ".png"
            folder = os.path.join(out, ext[1:])
            total_now = (len([f for f in os.listdir(folder)
                              if f.lower().endswith(ext)])
                         if os.path.isdir(folder) else 0)
            npdf = sum(1 for r in rows if r.get("has_pdf", True))
            self.q.put(("done", (len(rows), npdf, total_now, out)))
        except Exception as e:
            self.q.put(("error", "%s: %s" % (type(e).__name__, e)))

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "tick":
                    self.bar.configure(value=payload)
                elif kind == "done":
                    made, npdf, total_now, out = payload
                    self.busy = False
                    self.go.configure(state="normal")
                    self.bar.pack_forget()
                    self._last_out = out
                    jn = made - npdf
                    jtxt = ""
                    if jn:
                        jtxt = ("  (%d journal %s - data only)"
                                % (jn, "entry" if jn == 1 else "entries"))
                    extra = ""
                    if total_now > npdf:
                        extra = "   %d files in the folder now." % total_now
                    self._say("Done  -  %d document%s created%s.%s"
                              % (made, "" if made == 1 else "s", jtxt, extra),
                              "ok")
                    self.openbtn.pack(side="right", padx=12, pady=6)
                elif kind == "error":
                    self.busy = False
                    self.go.configure(state="normal")
                    self.bar.pack_forget()
                    self._say("Something went wrong - %s" % payload, "err")
        except queue.Empty:
            pass
        self.root.after(80, self._drain)


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
