"""Browser version of the generator, so any machine on the network can use it.

Standard library only - nothing to install. Run it on one PC and anyone on the
same WiFi opens it in a browser: Mac, phone, tablet, whatever.

    python -m invoicegen.web            # this machine only
    python -m invoicegen.web --lan      # anyone on the local network
"""
import io
import json
import os
import shutil
import socket
import tempfile
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import catalogue as cat
from . import chains
from .generate import run as run_custom
from .run_scenarios import run_scenarios
from .scenarios import PANELS, ALL_OPTS

AUTHOR = ""

# True when the page is shown in the app's own window rather than a browser.
# That window has no download manager, so documents are saved to a folder
# instead of offered as a download.
DESKTOP = False

# Set by the app window to a function that opens a native folder picker and
# returns the chosen path, or None if the user cancelled. The page cannot do
# this itself - only the window that owns the dialog can.
PICK_FOLDER = None

# Where the last batch was saved, offered as the starting point next time.
LAST_DIR = None


def output_dir():
    """Where saved documents go: Documents\\GST Documents, or the desktop."""
    home = os.path.expanduser("~")
    for parent in (os.path.join(home, "Documents"), home):
        if os.path.isdir(parent):
            d = os.path.join(parent, "GST Documents")
            os.makedirs(d, exist_ok=True)
            return d
    d = os.path.join(os.getcwd(), "GST Documents")
    os.makedirs(d, exist_ok=True)
    return d


def _save_locally(tmp, n, into=None):
    """Copy a finished batch into a dated folder. Returns its path.

    `into` is the folder the user picked; without one the documents go to
    Documents\\GST Documents. The batch always lands in its own dated
    sub-folder, so two runs into the same place never overwrite each other.
    """
    global LAST_DIR
    import datetime
    parent = into if into and os.path.isdir(into) else output_dir()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    dest = os.path.join(parent, "%s (%d)" % (stamp, n))
    shutil.copytree(tmp, dest)
    LAST_DIR = parent
    return dest


def open_folder(path):
    """Show a folder in the file manager, on whichever platform."""
    import subprocess
    import sys
    try:
        if sys.platform == "win32":
            os.startfile(path)                                # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False

PAGE = r"""<!doctype html>
<html lang="en" class="h-full">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GST Document Generator</title>
<link rel="stylesheet" href="/static/fonts.css">
<script src="/static/tailwind.js"></script>
<script>
tailwind.config = {
  darkMode: 'class',
  theme: { extend: {
    colors: {
      brand:{50:'#f5f3ff',100:'#ede9fe',200:'#ddd6fe',300:'#c4b5fd',
             400:'#a78bfa',500:'#8b5cf6',600:'#7c3aed',700:'#6d28d9',
             800:'#5b21b6',900:'#4c1d95'},
      vib:{pink:'#ec4899',rose:'#f43f5e',coral:'#fb7185',cyan:'#06b6d4',
           teal:'#14b8a6',emerald:'#10b981',amber:'#f59e0b',
           orange:'#f97316',violet:'#8b5cf6',indigo:'#6366f1'},
      surface:{950:'#090b14',900:'#0e1322',850:'#141a2e',800:'#1c243f',
               750:'#242f52',700:'#2e3a63'},
    },
    fontFamily:{
      sans:['"Plus Jakarta Sans"','Inter','system-ui','sans-serif'],
      mono:['"JetBrains Mono"','Consolas','monospace'],
    },
    boxShadow:{
      'glow':'0 0 35px -5px rgba(124,58,237,.45), 0 0 15px rgba(236,72,153,.3)',
      'glow-sm':'0 0 20px -6px rgba(124,58,237,.5)',
      'card':'0 8px 32px -12px rgba(0,0,0,.6)',
    },
    keyframes:{
      rise:{'0%':{opacity:0,transform:'translateY(10px)'},'100%':{opacity:1}},
      breathe:{'0%,100%':{opacity:1},'50%':{opacity:.4}},
    },
    animation:{ rise:'rise .25s ease-out', breathe:'breathe 1.6s infinite' },
  }}
}
</script>
<script>
/* Runs before the page paints, so there is no flash of the wrong theme.
   No saved choice means follow Windows; once the button is used, that
   choice is remembered instead. */
(function(){
  var saved = null;
  try { saved = localStorage.getItem('theme'); } catch(e) {}
  var dark = saved ? saved === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
})();
</script>
<style>
  /* ── theme ────────────────────────────────────────────────
     Every grey in the page comes from these variables, so the
     toggle only has to flip one attribute on <html>.  The accent
     colours (violet, pink, emerald ...) read well on both grounds
     and are deliberately left alone.                          */
  :root{
    --page:#f6f7fb; --panel:#ffffff; --panel2:#f9fafc; --sunk:#ffffff;
    --line:rgba(15,23,42,.10); --line2:rgba(15,23,42,.07);
    --ink:#0f172a; --ink2:#334155; --ink3:#64748b; --ink4:#94a3b8;
    --hover:rgba(15,23,42,.035); --active:rgba(15,23,42,.06);
    --chip:rgba(15,23,42,.05);
    --track:#cbd5e1; --knob:#ffffff; --bar:#94a3b8;
    --shadow:0 8px 26px -14px rgba(15,23,42,.28);
    --wash1:rgba(124,58,237,.07); --wash2:rgba(236,72,153,.05);
    --scroll:#cbd5e1; --scroll-h:#94a3b8;
    --bar-bg:rgba(255,255,255,.85);
  }
  :root[data-theme="dark"]{
    --page:#090b14; --panel:rgba(14,19,34,.7); --panel2:rgba(20,26,46,.6);
    --sunk:#0e1322;
    --line:rgba(255,255,255,.07); --line2:rgba(255,255,255,.06);
    --ink:#ffffff; --ink2:#cbd5e1; --ink3:#94a3b8; --ink4:#64748b;
    --hover:rgba(255,255,255,.035); --active:rgba(255,255,255,.06);
    --chip:rgba(255,255,255,.06);
    --track:#2e3a63; --knob:#8b98c4; --bar:#8b98c4;
    --shadow:0 8px 32px -12px rgba(0,0,0,.6);
    --wash1:rgba(124,58,237,.16); --wash2:rgba(236,72,153,.10);
    --scroll:#2e3a63; --scroll-h:#3d4d80;
    --bar-bg:rgba(9,11,20,.85);
  }

  body{background:var(--page); color:var(--ink2);
    background-image:
      radial-gradient(ellipse 80% 50% at 20% -10%, var(--wash1), transparent),
      radial-gradient(ellipse 60% 40% at 90% 0%, var(--wash2), transparent);
    background-attachment:fixed}
  ::-webkit-scrollbar{width:11px;height:11px}
  ::-webkit-scrollbar-thumb{background:var(--scroll);border-radius:8px;
    border:2px solid var(--page)}
  ::-webkit-scrollbar-thumb:hover{background:var(--scroll-h)}
  ::-webkit-scrollbar-track{background:transparent}

  /* surfaces - these replace the old surface/overlay utilities */
  .bar{background:var(--bar-bg)}
  .panel{background:var(--panel);border:1px solid var(--line);
    box-shadow:var(--shadow)}
  .panel2{background:var(--panel2);border:1px solid var(--line2)}
  .edge{border-color:var(--line2)}
  .chip{background:var(--chip);border:1px solid var(--line)}
  .chip:hover{background:var(--hover)}
  .ink{color:var(--ink)} .ink2{color:var(--ink2)}
  .ink3{color:var(--ink3)} .ink4{color:var(--ink4)}

  /* Accent lettering. The mockup's pale tints are made for a dark ground;
     on white they wash out, so each one darkens by a few steps. */
  .ac-brand{color:#a78bfa} .ac-emerald{color:#6ee7b7}
  .ac-violet{color:#c4b5fd} .ac-amber{color:#fcd34d}
  .ac-rose{color:#fda4af}
  :root:not([data-theme="dark"]) .ac-brand{color:#6d28d9}
  :root:not([data-theme="dark"]) .ac-emerald{color:#047857}
  :root:not([data-theme="dark"]) .ac-violet{color:#6d28d9}
  :root:not([data-theme="dark"]) .ac-amber{color:#b45309}
  :root:not([data-theme="dark"]) .ac-rose{color:#be123c}
  /* the 20%-opacity accent fills need more body on a white ground */
  :root:not([data-theme="dark"]) .pill.bg-brand-600\/20{
    background:#ede9fe}
  :root:not([data-theme="dark"]) b.pill.bg-brand-600\/20{
    background:#ede9fe}

  /* toggle */
  .sw{position:relative;display:inline-block;width:36px;height:20px;flex:none}
  .sw input{opacity:0;width:0;height:0;position:absolute}
  .sw span{position:absolute;inset:0;border-radius:99px;cursor:pointer;
    background:var(--track);transition:background .18s,box-shadow .18s}
  .sw span::before{content:"";position:absolute;height:14px;width:14px;
    left:3px;top:3px;background:var(--knob);border-radius:50%;
    transition:transform .18s,background .18s}
  .sw input:checked + span{background:var(--on,#7c3aed);
    box-shadow:0 0 14px -2px var(--on,#7c3aed)}
  .sw input:checked + span::before{transform:translateX(16px);background:#fff}

  .row{display:flex;align-items:center;gap:11px;padding:6px 8px;
    border-radius:9px;cursor:pointer;transition:background .14s}
  .row:hover{background:var(--hover)}
  .row.on{background:var(--active)}

  .fld{width:100%;padding:9px 12px;border-radius:10px;
    border:1px solid var(--line);background:var(--sunk);color:var(--ink);
    font-size:14px;transition:border-color .15s,box-shadow .15s}
  .fld:focus{outline:none;border-color:#7c3aed;
    box-shadow:0 0 0 3px rgba(124,58,237,.22)}
  .fld::placeholder{color:var(--ink4)}
  select.fld{appearance:none;
    background-image:url("data:image/svg+xml;charset=utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='none' stroke='%2394a3b8' stroke-width='2'%3E%3Cpath d='M2 4l4 4 4-4'/%3E%3C/svg%3E");
    background-repeat:no-repeat;background-position:right 10px center;
    padding-right:28px}
  .pill{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;
    border-radius:99px;font-size:10px;font-weight:700;letter-spacing:.05em}
  .dot{width:6px;height:6px;border-radius:50%;flex:none}

  /* theme switch in the header */
  #theme{display:flex;align-items:center;gap:6px;padding:6px 12px;
    border-radius:99px;cursor:pointer;font-size:11px;font-weight:800;
    letter-spacing:.05em;color:var(--ink3);
    background:var(--chip);border:1px solid var(--line);
    transition:color .15s,background .15s}
  #theme:hover{color:var(--ink);background:var(--hover)}
  #theme svg{width:14px;height:14px}
  :root[data-theme="dark"] #theme .sun{display:none}
  :root:not([data-theme="dark"]) #theme .moon{display:none}
</style>
</head>
<body class="h-full ink font-sans antialiased">

<!-- ── header ───────────────────────────────────────────────── -->
<header class="sticky top-0 z-30 bar backdrop-blur-xl
               border-b edge">
  <div class="max-w-[1720px] mx-auto px-7 py-3.5 flex items-center
              justify-between gap-4 flex-wrap">
    <div class="flex items-center gap-3.5">
      <div class="w-11 h-11 rounded-2xl bg-gradient-to-br from-brand-600
                  to-vib-pink grid place-items-center shadow-glow-sm">
        <svg width="21" height="21" viewBox="0 0 24 24" fill="none"
             stroke="#fff" stroke-width="2" stroke-linecap="round"
             stroke-linejoin="round"><path d="M6 2h9l5 5v15H6z"/>
          <path d="M15 2v5h5"/><path d="M9 12h7M9 16h7"/></svg>
      </div>
      <div>
        <div class="flex items-center gap-2.5">
          <h1 class="text-lg font-extrabold tracking-tight ink">
            GST Document Generator</h1>
          <span class="pill bg-brand-600/20 ac-brand
                       ring-1 ring-brand-500/30 font-mono">v2.4</span>
        </div>
        <p class="ink3 text-[13px] mt-0.5">Realistic GST documents
          for testing accounting software, ERPs and pipelines.</p>
      </div>
    </div>
    <div class="flex items-center gap-2.5">
      <span class="pill bg-vib-emerald/12 text-vib-emerald
                   ring-1 ring-vib-emerald/25">
        <span class="dot bg-vib-emerald animate-breathe"></span>SAMPLE DATA</span>
      <span class="pill chip ink2">
        ACTIVE: <b class="ink ml-0.5" id="cochip">Sample Firm</b></span>
      <button id="theme" onclick="flipTheme()" title="Switch between dark and light">
        <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/>
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20
            12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
        <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/></svg>
        <span id="themetxt">DARK</span></button>
    </div>
  </div>
</header>

<main class="max-w-[1720px] mx-auto px-7 pb-36">
  <!-- sticky under the header, so the tabs cannot slide behind it -->
  <nav class="flex gap-2 pt-5 pb-5 overflow-x-auto sticky top-[68px] z-20 bar"
       id="tabs"></nav>

  <!-- ══ my company ═══════════════════════════════════════════ -->
  <section data-pane="0" class="hidden animate-rise">
    <div class="rounded-3xl panel overflow-hidden">
      <div class="h-1 bg-gradient-to-r from-brand-600 via-vib-pink
                  to-vib-emerald"></div>
      <div class="p-7 border-b edge flex items-start
                  justify-between gap-5 flex-wrap">
        <div class="flex items-start gap-4">
          <div class="w-12 h-12 rounded-2xl bg-brand-600/15 ring-1
                      ring-brand-500/30 grid place-items-center shrink-0">
            <svg width="21" height="21" viewBox="0 0 24 24" fill="none"
                 stroke="#a78bfa" stroke-width="2"><path d="M3 21h18"/>
              <path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6"/></svg>
          </div>
          <div>
            <h2 class="text-xl font-extrabold ink">Your firm profile</h2>
            <p class="text-[13px] ink3 mt-1 max-w-2xl">The seller
              details printed on every generated document. Until you set your
              own, a sample firm is used.</p>
          </div>
        </div>
        <span class="pill bg-vib-cyan/12 text-vib-cyan ring-1
                     ring-vib-cyan/25">SAVED ON THIS MACHINE</span>
      </div>

      <div class="p-7 grid lg:grid-cols-2 gap-6">
        <div class="rounded-2xl panel2 p-5">
          <div class="flex items-center justify-between mb-5">
            <div class="flex items-center gap-2.5">
              <div class="w-7 h-7 rounded-lg bg-brand-600/20 grid
                          place-items-center">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                     stroke="#a78bfa" stroke-width="2.5">
                  <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/></svg>
              </div>
              <h3 class="text-[11px] font-extrabold tracking-widest
                         ink2">FIRM DETAILS</h3>
            </div>
            <span class="pill bg-vib-rose/12 text-vib-rose ring-1
                         ring-vib-rose/25">NAME REQUIRED</span>
          </div>
          <div class="grid sm:grid-cols-2 gap-4" id="co-firm"></div>
          <div id="gstin-hint" class="hidden mt-3 flex items-center gap-2
               text-[11px]"></div>
        </div>

        <div class="rounded-2xl panel2 p-5">
          <div class="flex items-center justify-between mb-5">
            <div class="flex items-center gap-2.5">
              <div class="w-7 h-7 rounded-lg bg-vib-emerald/20 grid
                          place-items-center">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                     stroke="#10b981" stroke-width="2.5">
                  <path d="M3 21h18M5 21V10l7-6 7 6v11M9 21v-5h6v5"/></svg>
              </div>
              <h3 class="text-[11px] font-extrabold tracking-widest
                         ink2">BANK DETAILS</h3>
            </div>
            <span class="pill chip ink3">OPTIONAL</span>
          </div>
          <div class="grid sm:grid-cols-2 gap-4" id="co-bank"></div>
          <div class="mt-4 rounded-xl bg-vib-cyan/[.07] ring-1
                      ring-vib-cyan/20 p-3.5 flex gap-3">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
                 stroke="#06b6d4" stroke-width="2" class="shrink-0 mt-0.5">
              <circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
            <p class="text-[12px] ink3 leading-relaxed">Bank details
              appear in the footer of invoice layouts that print them. Leave
              blank to omit the block entirely.</p>
          </div>
        </div>
      </div>

      <div class="px-7 pb-7 flex items-center gap-3 flex-wrap">
        <button onclick="saveCompany()" class="px-7 py-2.5 rounded-xl
                bg-gradient-to-r from-brand-600 to-vib-pink ink
                font-bold text-sm shadow-glow-sm hover:brightness-110
                active:scale-95 transition">Save firm profile</button>
        <button onclick="clearCompany()" class="px-5 py-2.5 rounded-xl
                chip ink2 font-semibold text-sm transition">
          Use the sample firm</button>
        <span id="co-note" class="text-[13px] ink3"></span>
      </div>
    </div>
  </section>

  <!-- ══ scenarios ════════════════════════════════════════════ -->
  <section data-pane="1" class="hidden animate-rise">
    <div class="flex items-start justify-between gap-4 mb-5 flex-wrap">
      <p class="text-[13px] ink3 max-w-2xl">Each switch is one Tally
        event. Events that need an earlier document generate the whole linked
        set, so a purchase-against-advance gives you the advance too.</p>
      <div class="flex gap-2 shrink-0">
        <button onclick="setAll('s',1)" class="px-3.5 py-1.5 text-[11px]
          font-bold rounded-lg chip hover:!border-brand-500/50 hover:!text-brand-500 transition">SELECT ALL</button>
        <button onclick="setAll('s',0)" class="px-3.5 py-1.5 text-[11px]
          font-bold rounded-lg chip transition">CLEAR</button>
      </div>
    </div>
    <div class="grid md:grid-cols-2 xl:grid-cols-3 gap-5" id="scen"></div>
    <div class="mt-6 flex gap-6 text-[11px] ink3 flex-wrap">
      <span class="flex items-center gap-2"><b class="pill bg-brand-600/20
        ac-brand ring-1 ring-brand-500/30">+1</b>
        also creates the linked earlier document</span>
      <span class="flex items-center gap-2"><b class="pill chip ink3">no PDF</b>
        journal entry - data only</span>
    </div>
  </section>

  <!-- ══ custom mix ═══════════════════════════════════════════ -->
  <section data-pane="2" class="hidden animate-rise">
    <div class="flex items-start justify-between gap-4 mb-5 flex-wrap">
      <p class="text-[13px] ink3 max-w-2xl">Mix your own invoices.
        Leave a group empty and it varies freely across the batch.</p>
      <div class="flex gap-2 shrink-0">
        <button onclick="setAll('o',1)" class="px-3.5 py-1.5 text-[11px]
          font-bold rounded-lg chip hover:!border-brand-500/50 hover:!text-brand-500 transition">SELECT ALL</button>
        <button onclick="setAll('o',0)" class="px-3.5 py-1.5 text-[11px]
          font-bold rounded-lg chip transition">CLEAR</button>
      </div>
    </div>
    <div class="grid md:grid-cols-2 xl:grid-cols-4 gap-5" id="opts"></div>
  </section>

  <!-- ══ patterns ═════════════════════════════════════════════ -->
  <section data-pane="3" class="hidden animate-rise">
    <div class="flex items-start justify-between gap-4 mb-5 flex-wrap">
      <p class="text-[13px] ink3 max-w-2xl">Every invoice is drawn
        in each layout you pick. Same numbers, different appearance - so a
        parser has to cope with all of them.</p>
      <div class="flex gap-2 shrink-0">
        <button onclick="setAll('p',1)" class="px-3.5 py-1.5 text-[11px]
          font-bold rounded-lg chip hover:!border-brand-500/50 hover:!text-brand-500 transition">SELECT ALL</button>
        <button onclick="setAll('p',0)" class="px-3.5 py-1.5 text-[11px]
          font-bold rounded-lg chip transition">CLEAR</button>
      </div>
    </div>
    <div class="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3"
         id="pats"></div>
    <p class="mt-6 text-[11px] ink3">Layouts apply to invoices,
      notes and orders. Receipts, payments and journals keep their own look.</p>
  </section>

  <!-- ══ manual entry ═════════════════════════════════════════ -->
  <section data-pane="4" class="hidden animate-rise space-y-5">
    <div class="grid lg:grid-cols-2 gap-5">
      <div class="rounded-2xl panel overflow-hidden">
        <div class="px-5 py-3 flex items-center gap-2.5
                    bg-gradient-to-r from-brand-600/25 to-transparent
                    border-b edge">
          <span class="dot bg-brand-400"></span>
          <span class="text-[11px] font-extrabold tracking-widest
                       ac-brand">SUPPLIER</span></div>
        <div class="p-5 grid sm:grid-cols-2 gap-4" id="m-sup"></div>
      </div>
      <div class="rounded-2xl panel overflow-hidden">
        <div class="px-5 py-3 flex items-center gap-2.5
                    bg-gradient-to-r from-vib-emerald/25 to-transparent
                    border-b edge">
          <span class="dot bg-vib-emerald"></span>
          <span class="text-[11px] font-extrabold tracking-widest
                       ac-emerald">BUYER</span></div>
        <div class="p-5 grid sm:grid-cols-2 gap-4" id="m-buy"></div>
      </div>
    </div>

    <div class="rounded-2xl panel overflow-hidden">
      <div class="px-5 py-3 flex items-center gap-2.5
                  bg-gradient-to-r from-vib-violet/25 to-transparent
                  border-b edge">
        <span class="dot bg-vib-violet"></span>
        <span class="text-[11px] font-extrabold tracking-widest
                     ac-violet">INVOICE</span></div>
      <div class="p-5 grid sm:grid-cols-3 gap-4" id="m-inv"></div>
    </div>

    <div class="rounded-2xl panel overflow-hidden">
      <div class="px-5 py-3 flex items-center justify-between
                  bg-gradient-to-r from-vib-amber/25 to-transparent
                  border-b edge">
        <span class="flex items-center gap-2.5"><span class="dot bg-vib-amber"></span>
          <span class="text-[11px] font-extrabold tracking-widest
                       ac-amber">ITEMS</span></span>
        <button onclick="addItem()" class="px-3 py-1 rounded-lg chip text-[11px] font-bold transition">
          + ADD ROW</button></div>
      <div class="p-5 overflow-x-auto">
        <table class="w-full text-sm" id="m-items">
          <thead><tr class="text-[10px] uppercase tracking-widest
                            ink3 text-left">
            <th class="w-8 pb-2.5"></th><th class="pb-2.5">Description</th>
            <th class="pb-2.5">HSN/SAC</th><th class="pb-2.5">Qty</th>
            <th class="pb-2.5">UOM</th><th class="pb-2.5">Rate</th>
            <th class="pb-2.5">GST%</th><th class="pb-2.5">Disc%</th>
          </tr></thead><tbody></tbody></table></div>
    </div>

    <div class="rounded-2xl panel overflow-hidden">
      <div class="px-5 py-3 flex items-center justify-between
                  bg-gradient-to-r from-vib-rose/25 to-transparent
                  border-b edge">
        <span class="flex items-center gap-2.5"><span class="dot bg-vib-rose"></span>
          <span class="text-[11px] font-extrabold tracking-widest
                       ac-rose">OTHER CHARGES</span></span>
        <button onclick="addCharge()" class="px-3 py-1 rounded-lg chip text-[11px] font-bold transition">
          + ADD ROW</button></div>
      <div class="p-5 overflow-x-auto">
        <table class="w-full text-sm" id="m-charges">
          <thead><tr class="text-[10px] uppercase tracking-widest
                            ink3 text-left">
            <th class="w-8 pb-2.5"></th><th class="pb-2.5">Label</th>
            <th class="pb-2.5">Amount</th><th class="pb-2.5">GST%</th>
          </tr></thead><tbody></tbody></table></div>
    </div>

    <div class="rounded-2xl panel2 p-6 shadow-card">
      <div class="flex items-center gap-2.5 mb-4">
        <span class="dot bg-vib-cyan animate-breathe"></span>
        <span class="text-[11px] font-extrabold tracking-widest
                     ink3">LIVE TOTALS</span></div>
      <div id="m-tot" class="font-mono text-[13px] leading-loose
           ink3">nothing entered yet</div>
      <p class="mt-3 text-[12px] text-vib-rose" id="m-note"></p>
    </div>
  </section>

  <footer class="pt-10 pb-2 text-center">
    <p class="text-[12px] ink3">__AUTHOR__</p>
  </footer>
</main>

<!-- ══ action bar ═════════════════════════════════════════════ -->
<div class="fixed bottom-0 inset-x-0 z-30 bar backdrop-blur-xl
            border-t edge">
  <div id="status" class="hidden max-w-[1720px] mx-auto px-7 pt-3"></div>
  <div class="max-w-[1720px] mx-auto px-7 py-3 flex items-end gap-6 flex-wrap">
    <label class="flex flex-col gap-1.5">
      <span class="text-[10px] font-extrabold tracking-widest ink3">
        QUANTITY</span>
      <input type="number" id="count" value="1" min="1" max="200"
             class="fld w-20 py-1.5 text-center font-bold font-mono"></label>
    <label class="flex flex-col gap-1.5">
      <span class="text-[10px] font-extrabold tracking-widest ink3">
        GOODS LINES</span>
      <select id="gl" class="fld py-1.5"></select></label>
    <label class="flex flex-col gap-1.5">
      <span class="text-[10px] font-extrabold tracking-widest ink3">
        SERVICE LINES</span>
      <select id="sl" class="fld py-1.5"></select></label>

    <label class="flex flex-col gap-1.5">
      <span class="text-[10px] font-extrabold tracking-widest ink3">
        DISCOUNT</span>
      <span class="flex items-center gap-2 pb-1.5 cursor-pointer">
        <span class="sw" style="--on:#f59e0b">
          <input type="checkbox" id="disc"><span></span></span>
        <span class="text-[13px] font-semibold ink2">Include</span>
      </span></label>

    <div class="flex flex-col gap-1.5">
      <span class="text-[10px] font-extrabold tracking-widest ink3">
        OUTPUT</span>
      <div class="flex gap-3 pb-1.5">
        <label class="flex items-center gap-1.5 cursor-pointer">
          <span class="sw" style="--on:#f43f5e">
            <input type="checkbox" id="fpdf" checked><span></span></span>
          <span class="text-[13px] font-semibold ink2">PDF</span></label>
        <label class="flex items-center gap-1.5 cursor-pointer">
          <span class="sw" style="--on:#06b6d4">
            <input type="checkbox" id="fpng"><span></span></span>
          <span class="text-[13px] font-semibold ink2">PNG</span></label>
      </div>
    </div>

    <div class="flex-1"></div>
    <div class="text-right">
      <div class="text-[10px] font-extrabold tracking-widest ink3
                  mb-1">OUTPUT</div>
      <div id="sum" class="text-[13px] font-semibold ink3"></div>
    </div>
    <button id="go" onclick="go()" class="px-9 py-3 rounded-xl font-extrabold
      ink text-sm transition active:scale-95 flex items-center gap-2.5
      bg-gradient-to-r from-brand-600 to-vib-pink shadow-glow
      hover:brightness-110 disabled:opacity-25 disabled:shadow-none
      disabled:cursor-default">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <path d="M12 3l1.9 5.8H20l-4.9 3.6 1.9 5.8L12 14.6 7 18.2l1.9-5.8L4 8.8h6.1z"/>
      </svg>GENERATE</button>
  </div>
</div>

<script>
const SCEN = __SCEN__, OPTS = __OPTS__, PATS = __PATS__, COMPANY = __COMPANY__;
const TABS = [
  ['My Company','M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6'],
  ['Tally Scenarios','M9 11l3 3L22 4M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11'],
  ['Custom Mix','M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6'],
  ['Patterns','M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z'],
  ['Manual Entry','M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z'],
];
/* group -> [switch colour, header tint class] */
const HUE = {
  purchase:['#6366f1','from-vib-indigo/25'], sales:['#10b981','from-vib-emerald/25'],
  receipt:['#8b5cf6','from-vib-violet/25'],  payment:['#f43f5e','from-vib-rose/25'],
  bank:['#06b6d4','from-vib-cyan/25'],       expense:['#f59e0b','from-vib-amber/25'],
  asset:['#14b8a6','from-vib-teal/25']};
const PT = [['#6366f1','from-vib-indigo/25'],['#10b981','from-vib-emerald/25'],
  ['#8b5cf6','from-vib-violet/25'],['#f43f5e','from-vib-rose/25'],
  ['#06b6d4','from-vib-cyan/25'],['#f59e0b','from-vib-amber/25'],
  ['#14b8a6','from-vib-teal/25'],['#ec4899','from-vib-pink/25']];

const STATES={'01':'Jammu & Kashmir','02':'Himachal Pradesh','03':'Punjab',
 '04':'Chandigarh','05':'Uttarakhand','06':'Haryana','07':'Delhi',
 '08':'Rajasthan','09':'Uttar Pradesh','10':'Bihar','11':'Sikkim',
 '12':'Arunachal Pradesh','13':'Nagaland','14':'Manipur','15':'Mizoram',
 '16':'Tripura','17':'Meghalaya','18':'Assam','19':'West Bengal',
 '20':'Jharkhand','21':'Odisha','22':'Chhattisgarh','23':'Madhya Pradesh',
 '24':'Gujarat','27':'Maharashtra','29':'Karnataka','30':'Goa','32':'Kerala',
 '33':'Tamil Nadu','34':'Puducherry','36':'Telangana','37':'Andhra Pradesh'};

/* ---------- tabs ---------- */
/* ---------- dark / light ---------- */
function themeLabel(){
  document.getElementById('themetxt').textContent =
    document.documentElement.getAttribute('data-theme') === 'dark'
      ? 'DARK' : 'LIGHT';
}
function flipTheme(){
  const el = document.documentElement;
  const dark = el.getAttribute('data-theme') === 'dark';
  el.setAttribute('data-theme', dark ? 'light' : 'dark');
  try { localStorage.setItem('theme', dark ? 'light' : 'dark'); } catch(e) {}
  themeLabel();
}
themeLabel();
/* follow Windows while the user has not chosen for themselves */
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
  let saved = null;
  try { saved = localStorage.getItem('theme'); } catch(x) {}
  if (saved) return;
  document.documentElement.setAttribute('data-theme',
                                        e.matches ? 'dark' : 'light');
  themeLabel();
});

const HASH={'#company':0,'#scenarios':1,'#custom':2,'#patterns':3,'#manual':4};
let tab = HASH[location.hash] ?? (COMPANY.set ? 1 : 0);
const nav=document.getElementById('tabs');
TABS.forEach(([t,d],i)=>{
  const b=document.createElement('button');
  b.innerHTML=`<svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width="2" stroke-linecap="round"
    stroke-linejoin="round"><path d="${d}"/></svg><span>${t}</span>`;
  b.onclick=()=>pick(i);
  nav.appendChild(b);
});
function pick(n){
  tab=n;
  [...nav.children].forEach((b,i)=>{
    b.className='flex items-center gap-2 px-5 py-2.5 rounded-xl text-[13px] '+
      'font-bold whitespace-nowrap transition '+(i===n
      ? 'bg-gradient-to-r from-brand-600 to-vib-pink ink shadow-glow-sm'
      : 'chip ink3 '+
        'hover:!text-[color:var(--ink)]');
  });
  document.querySelectorAll('[data-pane]').forEach(p=>
    p.classList.toggle('hidden', +p.dataset.pane!==n));
  sum();
}

/* ---------- builders ---------- */
function fld(id,label,val,req){
  return `<label class="block">
    <span class="block text-[11px] font-bold ink3 mb-1.5
      tracking-wide">${label?label.toUpperCase():'&nbsp;'}${req
      ?' <span class="text-vib-rose">*</span>':''}</span>
    <input id="${id}" value="${val||''}" class="fld"></label>`;
}
function row(cls,val,label,tag,on){
  return `<label class="row" style="--on:${on[0]}">
    <span class="sw" style="--on:${on[0]}">
      <input type="checkbox" class="${cls}" value="${val}"><span></span></span>
    <span class="text-[13px] leading-tight flex-1 ink2">${label}</span>
    ${tag||''}</label>`;
}
function card(title,on,count,body){
  return `<div class="rounded-2xl panel overflow-hidden flex flex-col">
    <div class="px-4 py-3 flex items-center justify-between border-b
         edge bg-gradient-to-r ${on[1]} to-transparent">
      <span class="flex items-center gap-2.5">
        <span class="dot" style="background:${on[0]}"></span>
        <span class="text-[11px] font-extrabold tracking-widest ink">
          ${title.toUpperCase()}</span></span>
      ${count!=null?`<span class="text-[10px] font-mono font-bold
        ink3">${count}</span>`:''}
    </div><div class="p-2.5 flex-1">${body}</div></div>`;
}
const TAG_PDF='<span class="pill chip ink3 shrink-0">no PDF</span>';
const tagChain=n=>`<span class="pill bg-brand-600/20 ac-brand ring-1 `+
  `ring-brand-500/30 shrink-0">+${n}</span>`;

/* ---------- my company ---------- */
const CO_FIRM=[['name','Firm / trade name',1],['gstin','GSTIN',0],
               ['addr1','Registered address',0],['state','State',0],
               ['addr2','',0],['mobile','Contact phone',0]];
const CO_BANK=[['bank_name','Bank name',0],['bank_account','Account number',0],
               ['bank_ifsc','IFSC code',0],['bank_branch','Branch & city',0]];
document.getElementById('co-firm').innerHTML=
  CO_FIRM.map(([k,l,r])=>fld('co_'+k,l,COMPANY.data[k],r)).join('');
document.getElementById('co-bank').innerHTML=
  CO_BANK.map(([k,l])=>fld('co_'+k,l,COMPANY.data[k])).join('');

/* live GSTIN feedback, as in the mockup */
function gstinCheck(){
  const g=(document.getElementById('co_gstin').value||'').trim().toUpperCase();
  const box=document.getElementById('gstin-hint');
  const inp=document.getElementById('co_gstin');
  if(!g){ box.className='hidden'; inp.style.borderColor=''; return; }
  const ok=/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/.test(g);
  const st=STATES[g.slice(0,2)];
  box.className='mt-3 flex items-center gap-2 text-[11px] flex-wrap';
  inp.style.borderColor = ok ? '#10b981' : '#f43f5e';
  box.innerHTML = ok
    ? `<span class="pill bg-vib-emerald/12 text-vib-emerald ring-1
         ring-vib-emerald/25">FORMAT VALID</span>
       <span class="ink3">State code</span>
       <span class="font-mono ink2">${g.slice(0,2)} =
         ${st||'unknown'}</span>`
    : `<span class="pill bg-vib-rose/12 text-vib-rose ring-1
         ring-vib-rose/25">CHECK FORMAT</span>
       <span class="ink3">15 characters, e.g. 27AAECT3390L1ZX
         - allowed anyway</span>`;
}
document.getElementById('co_gstin').addEventListener('input',gstinCheck);
gstinCheck();

function coChip(){
  document.getElementById('cochip').textContent =
    COMPANY.set ? COMPANY.data.name : 'Sample Firm';
}
document.getElementById('co-note').textContent = COMPANY.set
  ? 'Using your firm: '+COMPANY.data.name
  : 'Using the sample firm until you save your own.';
coChip();

async function saveCompany(){
  const d={}; [...CO_FIRM,...CO_BANK].forEach(([k])=>
    d[k]=document.getElementById('co_'+k).value);
  if(!d.name.trim()){ note('co-note','Enter a firm name before saving.',1); return; }
  const r=await fetch('/company',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
  if(r.ok){ COMPANY.set=true; COMPANY.data=d; coChip(); }
  note('co-note', r.ok?('Saved. Every document now carries '+d.name.trim()+'.')
                     :'Could not save.', !r.ok);
}
async function clearCompany(){
  await fetch('/company',{method:'DELETE'});
  [...CO_FIRM,...CO_BANK].forEach(([k])=>document.getElementById('co_'+k).value='');
  COMPANY.set=false; COMPANY.data={}; coChip(); gstinCheck();
  note('co-note','Back to the sample firm.');
}
function note(id,msg,bad){
  const e=document.getElementById(id);
  e.textContent=msg;
  e.className='text-[13px] font-semibold '+(bad?'text-vib-rose':'text-vib-emerald');
}

/* ---------- panes ---------- */
document.getElementById('scen').innerHTML = SCEN.map(g=>{
  const on=HUE[g.key]||PT[0];
  return card(g.title,on,g.items.length, g.items.map(o=>row('s',o.id,o.label,
    o.doc==='none'?TAG_PDF : o.chain>1?tagChain(o.chain-1):'', on)).join(''));
}).join('');
document.getElementById('opts').innerHTML = OPTS.map((g,i)=>{
  const on=PT[i%PT.length];
  return card(g.title,on,null,
    g.options.map(o=>row('o',o.id,o.label,'',on)).join(''));
}).join('');
document.getElementById('pats').innerHTML = PATS.map((p,i)=>{
  const on=PT[i%PT.length];
  return `<label class="row panel rounded-xl px-3 py-2.5" style="--on:${on[0]}">
    <span class="sw" style="--on:${on[0]}">
      <input type="checkbox" class="p" value="${p.id}"><span></span></span>
    <span class="text-[13px] font-medium ink2">${p.label}</span></label>`;
}).join('');

document.addEventListener('change',e=>{
  if(e.target.matches('.s,.o,.p')){
    const r=e.target.closest('.row');
    if(r) r.classList.toggle('on', e.target.checked);
  }
});

/* ---------- manual entry ---------- */
const M_SUP=[['name','Name'],['gstin','GSTIN'],['addr1','Address'],
             ['addr2',''],['phone','Phone']];
const M_BUY=[['name','Name'],['gstin','GSTIN'],['addr1','Address'],['addr2','']];
const M_INV=[['number','Invoice number'],['date','Date'],['pos','Place of supply']];
document.getElementById('m-sup').innerHTML=M_SUP.map(([k,l])=>fld('ms_'+k,l)).join('');
document.getElementById('m-buy').innerHTML=M_BUY.map(([k,l])=>fld('mb_'+k,l)).join('');
document.getElementById('m-inv').innerHTML=M_INV.map(([k,l])=>fld('mi_'+k,l)).join('');

const CELL='fld py-1.5 text-[13px]';
function addItem(){
  const tb=document.querySelector('#m-items tbody'), n=tb.children.length+1;
  const tr=document.createElement('tr');
  tr.innerHTML=`<td class="text-[11px] font-mono ink4 pr-2 pb-2">${n}</td>`+
    [['desc',''],['hsn',''],['qty',''],['uom','PCS'],['rate',''],
     ['gst','18'],['disc','']]
    .map(([k,v])=>`<td class="pr-2 pb-2"><input class="it-${k} ${CELL}" value="${v}"></td>`)
    .join('');
  tb.appendChild(tr); bind();
}
function addCharge(){
  const tb=document.querySelector('#m-charges tbody'), n=tb.children.length+1;
  const tr=document.createElement('tr');
  tr.innerHTML=`<td class="text-[11px] font-mono ink4 pr-2 pb-2">${n}</td>`+
    [['label',''],['amount',''],['gst','0']]
    .map(([k,v])=>`<td class="pr-2 pb-2"><input class="ch-${k} ${CELL}" value="${v}"></td>`)
    .join('');
  tb.appendChild(tr); bind();
}
for(let i=0;i<4;i++) addItem();
for(let i=0;i<2;i++) addCharge();

function readManual(){
  const g=id=>document.getElementById(id).value;
  return {
    supplier:Object.fromEntries(M_SUP.map(([k])=>[k,g('ms_'+k)])),
    buyer:Object.fromEntries(M_BUY.map(([k])=>[k,g('mb_'+k)])),
    invoice:Object.fromEntries(M_INV.map(([k])=>[k,g('mi_'+k)])),
    items:[...document.querySelectorAll('#m-items tbody tr')].map(tr=>({
      desc:tr.querySelector('.it-desc').value, hsn:tr.querySelector('.it-hsn').value,
      qty:tr.querySelector('.it-qty').value, uom:tr.querySelector('.it-uom').value,
      rate:tr.querySelector('.it-rate').value, gst:tr.querySelector('.it-gst').value,
      disc:tr.querySelector('.it-disc').value})),
    charges:[...document.querySelectorAll('#m-charges tbody tr')].map(tr=>({
      label:tr.querySelector('.ch-label').value,
      amount:tr.querySelector('.ch-amount').value,
      gst:tr.querySelector('.ch-gst').value})),
  };
}
let manTimer=null;
async function manualTotals(){
  clearTimeout(manTimer);
  manTimer=setTimeout(async()=>{
    const r=await fetch('/preview',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(readManual())});
    if(!r.ok) return;
    const j=await r.json();
    document.getElementById('m-tot').innerHTML=j.lines.map((l,i)=>
      i===j.lines.length-1
        ? `<span class="ink font-bold text-base">${l}</span>` : l
      ).join('<br>');
    document.getElementById('m-note').textContent=j.note||'';
    if(tab===4){
      const n=ticked('p').length||1;
      document.getElementById('sum').innerHTML=j.ready
        ? `<b class="ink">1</b> invoice → <b class="ac-brand">${n}</b> file${n===1?'':'s'}`
        : 'fill in the form to generate';
      document.getElementById('go').disabled=!j.ready;
    }
  },180);
}
function bind(){
  document.querySelectorAll('#m-items input,#m-charges input')
    .forEach(e=>{ e.oninput=manualTotals; });
}
['m-sup','m-buy','m-inv'].forEach(id=>
  document.getElementById(id).addEventListener('input',manualTotals));
bind();

/* ---------- shared ---------- */
for(const s of ['gl','sl'])
  document.getElementById(s).innerHTML=
    ['Any',1,2,3,4,5,6,8,10,15,20].map(v=>`<option>${v}</option>`).join('');

function setAll(k,on){
  document.querySelectorAll('.'+k).forEach(c=>{
    c.checked=!!on;
    const r=c.closest('.row'); if(r) r.classList.toggle('on',!!on);
  });
  sum();
}
function ticked(k){
  return [...document.querySelectorAll('.'+k+':checked')].map(c=>c.value); }

function sum(){
  const n=+document.getElementById('count').value||1;
  const np=ticked('p').length||1;
  const go=document.getElementById('go'), out=document.getElementById('sum');
  const W=v=>`<b class="ink">${v}</b>`;
  const B=v=>`<b class="ac-brand">${v}</b>`;
  if(tab===0){ out.textContent='set your firm, then use the other tabs';
    go.disabled=true; return; }
  if(tab===4){ manualTotals(); return; }
  go.disabled=false;
  if(tab===1){
    const p=ticked('s'); let docs=0,pdfs=0;
    for(const g of SCEN) for(const o of g.items) if(p.includes(o.id)){
      docs+=o.chain; pdfs+=o.pdfs; }
    out.innerHTML=`${W(p.length)} selected → ${W(docs*n)} documents`+
      (np>1?` × ${B(np)} layouts = ${B(pdfs*np*n)} files`
           :(pdfs!==docs?`  (${pdfs*n} PDFs)`:''));
    go.disabled=p.length===0;
  } else if(tab===3){
    const k=ticked('p').length;
    out.innerHTML=k?`${B(k)} layout${k===1?'':'s'} selected`
                   :'no layout picked - Classic will be used';
  } else {
    out.innerHTML=`${W(ticked('o').length)} options → ${W(n)} invoices`+
      (np>1?` × ${B(np)} layouts = ${B(n*np)} files`:'');
  }
}
document.addEventListener('change',sum);
document.getElementById('count').addEventListener('input',sum);
pick(tab);

/* URL-safe base64 of a UTF-8 path, which is what /open/ expects */
function b64url(s){
  const bytes = new TextEncoder().encode(s);
  let bin = '';
  bytes.forEach(b => bin += String.fromCharCode(b));
  return btoa(bin).replace(/\+/g,'-').replace(/\//g,'_');
}
async function openFolder(tok){
  try { await fetch('/open/' + tok); } catch(e) {}
}

async function go(){
  const btn=document.getElementById('go'), s=document.getElementById('status');
  const fmt=[]; if(document.getElementById('fpdf').checked) fmt.push('pdf');
  if(document.getElementById('fpng').checked) fmt.push('png');
  const gl=document.getElementById('gl').value, sl=document.getElementById('sl').value;

  /* In the app window, ask where to save before doing the work. A browser
     has no such dialog and answers null, and the download is offered as
     usual. Cancelling the dialog cancels the whole thing. */
  let folder = null;
  try{
    const pr = await fetch('/pick-folder');
    const pj = await pr.json();
    if (pj.desktop && !pj.folder) {             // user pressed Cancel
      s.className='max-w-[1720px] mx-auto px-7 pt-3';
      s.innerHTML='<div class="rounded-xl chip ink3 px-5 py-3 text-[13px] '+
        'font-semibold">Cancelled — nothing was generated.</div>';
      return;
    }
    folder = pj.folder;
  }catch(e){}

  btn.disabled=true;
  s.className='max-w-[1720px] mx-auto px-7 pt-3';
  s.innerHTML='<div class="rounded-xl bg-brand-600/10 ring-1 ring-brand-500/30 '+
    'ac-brand px-5 py-3 text-[13px] font-semibold flex items-center gap-3">'+
    '<span class="dot bg-brand-400 animate-breathe"></span>Generating…</div>';
  try{
    const body={ mode: tab===1?'scenarios': tab===4?'manual':'custom',
      picks: tab===1?ticked('s'):ticked('o'),
      patterns: ticked('p'), formats: fmt.length?fmt:['pdf'],
      count:+document.getElementById('count').value||1,
      detail:{goods_lines:gl==='Any'?null:+gl,
              service_lines:sl==='Any'?null:+sl,
              discount:document.getElementById('disc').checked},
      form: tab===4?readManual():null, folder: folder };
    const r=await fetch('/generate',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok) throw new Error(await r.text());
    const j=await r.json();
    s.innerHTML='<div class="rounded-xl bg-vib-emerald/10 ring-1 '+
      'ring-vib-emerald/30 ac-emerald px-5 py-3 text-[13px] '+
      'font-semibold flex items-center gap-4 flex-wrap">'+
      '<span class="dot bg-vib-emerald"></span>'+
      `<span>Done — <b class="ink">${j.count}</b> document`+
      `${j.count===1?'':'s'}`+
      (j.journals?` (${j.journals} journal entries, data only)`:'')+'</span>'+
      // In the app window there is no download manager, so the documents are
      // already saved and the button just opens the folder holding them.
      (j.folder
        ? `<button onclick="openFolder('${b64url(j.folder)}')" `+
          'class="px-5 py-1.5 rounded-lg bg-vib-emerald text-surface-950 '+
          'text-[12px] font-extrabold hover:brightness-110 transition">'+
          'OPEN FOLDER</button>'+
          `<span class="ink3 text-[11px] font-normal">saved to ${j.folder}</span>`
        : `<a href="${j.url}" download class="px-5 py-1.5 rounded-lg `+
          'bg-vib-emerald text-surface-950 text-[12px] font-extrabold '+
          'hover:brightness-110 transition">DOWNLOAD ZIP</a>')+'</div>';
  }catch(e){
    s.innerHTML='<div class="rounded-xl bg-vib-rose/10 ring-1 ring-vib-rose/30 '+
      `ac-rose px-5 py-3 text-[13px] font-semibold">Failed: ${e.message}</div>`;
  }finally{ btn.disabled=false; }
}
</script>
</body></html>
"""


def static_dir():
    """Where the offline CSS, JS and fonts live, bundled or not."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def render_page():
    """The whole UI with its data baked in, ready to serve."""
    from . import company
    from . import patterns as P

    scen = []
    for key, title, items in cat.by_category():
        rows = []
        for sid, label, doc in items:
            steps = chains.CHAINS.get(sid, [sid])
            rows.append({
                "id": sid, "label": label, "doc": doc,
                "chain": len(steps),
                "pdfs": sum(1 for st in steps if cat.doc_kind(st) != "none"),
                "def": False,
            })
        scen.append({"key": key, "title": title, "items": rows})
    opts = [{"title": t, "options": [{"id": i, "label": l, "def": d}
                                     for i, l, d in o]}
            for t, _k, o in PANELS]
    pats = [{"id": pid, "label": label} for pid, label, _fn in P.PATTERNS]
    saved = company.load() or {}
    co = {"set": bool(saved), "data": saved}
    return (PAGE.replace("__SCEN__", json.dumps(scen))
                .replace("__OPTS__", json.dumps(opts))
                .replace("__PATS__", json.dumps(pats))
                .replace("__COMPANY__", json.dumps(co))
                .replace("__AUTHOR__", AUTHOR))


class Handler(BaseHTTPRequestHandler):
    zips = {}

    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            html = render_page()
            return self._send(200, "text/html; charset=utf-8",
                              html.encode("utf-8"))
        if path.startswith("/static/"):
            root = static_dir()
            # keep sub-folders (fonts/) but refuse to climb out of static/
            parts = [p for p in path[8:].split("/") if p not in ("", ".", "..")]
            f = os.path.join(root, *parts) if parts else root
            if parts and os.path.isfile(f):
                name = parts[-1]
                ctype = ("application/javascript" if name.endswith(".js")
                         else "text/css" if name.endswith(".css")
                         else "font/woff2" if name.endswith(".woff2")
                         else "application/octet-stream")
                with open(f, "rb") as fh:
                    return self._send(200, ctype, fh.read(),
                                      {"Cache-Control": "max-age=86400"})
            return self._send(404, "text/plain", b"not found")
        if path == "/pick-folder":
            # the app window owns the dialog; a browser has no such thing
            if not PICK_FOLDER:
                return self._send(200, "application/json",
                                  json.dumps({"folder": None,
                                              "desktop": False}).encode())
            try:
                chosen = PICK_FOLDER(LAST_DIR or output_dir())
            except Exception:
                chosen = None
            return self._send(200, "application/json",
                              json.dumps({"folder": chosen,
                                          "desktop": True}).encode())
        if path.startswith("/open/"):
            import base64
            try:
                folder = base64.urlsafe_b64decode(path[6:]).decode("utf-8")
            except Exception:
                return self._send(400, "text/plain", b"bad path")
            # only ever open a batch folder we just wrote, never an arbitrary
            # path a stray request might name
            allowed = [output_dir()] + ([LAST_DIR] if LAST_DIR else [])
            here = os.path.abspath(folder)
            if not any(here.startswith(os.path.abspath(a)) for a in allowed):
                return self._send(403, "text/plain", b"refused")
            ok = open_folder(folder)
            return self._send(200, "application/json",
                              json.dumps({"ok": ok}).encode())
        if path.startswith("/zip/"):
            item = self.zips.pop(path[5:], None)
            if not item:
                return self._send(404, "text/plain", b"expired")
            name, blob = item
            return self._send(200, "application/zip", blob,
                              {"Content-Disposition":
                               'attachment; filename="%s"' % name})
        self._send(404, "text/plain", b"not found")

    def do_DELETE(self):
        if urlparse(self.path).path == "/company":
            from . import company
            company.clear()
            return self._send(200, "application/json", b'{"ok":true}')
        return self._send(404, "text/plain", b"not found")

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/company":
            try:
                from . import company
                company.save(self._body())
                return self._send(200, "application/json", b'{"ok":true}')
            except Exception as e:
                return self._send(500, "text/plain", str(e).encode())

        if path == "/preview":
            # live totals for the manual form, recomputed as the user types
            try:
                from .manual import ManualForm
                d = self._body()
                f = ManualForm()
                f.supplier.update(d.get("supplier") or {})
                f.buyer.update(d.get("buyer") or {})
                f.invoice.update(d.get("invoice") or {})
                f.items = d.get("items") or []
                f.charges = d.get("charges") or []
                t = f.totals()
                fig = lambda v: "{:,.2f}".format(v)
                head = "%d item%s" % (t["count"],
                                      "" if t["count"] == 1 else "s")
                if t.get("n_charges"):
                    head += " + %d charge%s" % (
                        t["n_charges"], "" if t["n_charges"] == 1 else "s")
                lines = [head, "Taxable %14s" % fig(t["taxable"])]
                if t.get("charges"):
                    lines.append("Charges %14s" % fig(t["charges"]))
                lines += ["Tax     %14s" % fig(t["tax"]),
                          "Round   %14s" % fig(t["round_off"]),
                          "TOTAL   %14s" % fig(t["total"])]
                probs = f.problems()
                note = ("Still needed: " + ", ".join(probs)) if probs else ""
                warn = f.warnings()
                if warn:
                    note = (note + "   " if note else "") + "   ".join(warn)
                return self._send(200, "application/json", json.dumps({
                    "lines": lines, "note": note,
                    "ready": not probs}).encode())
            except Exception as e:
                return self._send(500, "text/plain", str(e).encode())

        if path != "/generate":
            return self._send(404, "text/plain", b"not found")
        tmp = None
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            count = max(1, min(200, int(req.get("count", 1))))
            detail = req.get("detail") or {}
            picks = req.get("picks") or []

            from . import patterns as P
            pats = tuple(x for x in (req.get("patterns") or [])
                         if x in P.BY_ID) or ("classic",)
            fmts = tuple(x for x in (req.get("formats") or [])
                         if x in ("pdf", "png")) or ("pdf",)
            mode = req.get("mode")

            tmp = tempfile.mkdtemp(prefix="webgen_")
            if mode == "scenarios":
                picks = [p for p in picks if p in cat.BY_ID]
                if not picks:
                    raise ValueError("please tick at least one scenario")
                rows = run_scenarios(picks, count=count, seed=None,
                                     outdir=tmp, opts=detail,
                                     formats=fmts, patterns=pats)
            elif mode == "manual":
                from .manual import ManualForm, generate as gen_manual
                d = req.get("form") or {}
                f = ManualForm()
                f.supplier.update(d.get("supplier") or {})
                f.buyer.update(d.get("buyer") or {})
                f.invoice.update(d.get("invoice") or {})
                f.items = d.get("items") or []
                f.charges = d.get("charges") or []
                probs = f.problems()
                if probs:
                    raise ValueError("still needed: " + ", ".join(probs))
                made = gen_manual(f, tmp, patterns=pats, formats=fmts)
                rows = [{"has_pdf": True} for _ in made]
            else:
                picks = [p for p in picks if p in ALL_OPTS]
                rows = run_custom(picks, count=count, seed=None,
                                  outdir=tmp, detail=detail,
                                  formats=fmts, patterns=pats)

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for root, _d, names in os.walk(tmp):
                    for fn in sorted(names):
                        full = os.path.join(root, fn)
                        z.write(full, os.path.relpath(full, tmp))
            blob = buf.getvalue()

            tok = os.urandom(8).hex()
            self.zips[tok] = ("documents_%d.zip" % len(rows), blob)
            journals = sum(1 for r in rows if not r.get("has_pdf", True))

            # In the app window there is no browser download manager, so the
            # documents are written straight to a folder the user can open.
            saved = (_save_locally(tmp, len(rows), req.get("folder"))
                     if DESKTOP else None)

            self._send(200, "application/json", json.dumps({
                "count": len(rows), "journals": journals,
                "url": "/zip/" + tok, "folder": saved}).encode())
        except Exception as e:
            self._send(500, "text/plain", str(e).encode())
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)


def lan_ip():
    """This machine's address on the local network."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))       # no traffic is actually sent
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def serve(port=8000, open_browser=True, lan=False):
    host = "0.0.0.0" if lan else "127.0.0.1"
    srv = ThreadingHTTPServer((host, port), Handler)
    local = "http://127.0.0.1:%d/" % port
    print("GST Document Generator")
    print("  on this machine : %s" % local)
    if lan:
        print("  on the network  : http://%s:%d/" % (lan_ip(), port))
        print("  (anyone on the same WiFi can open that address)")
    print("\nPress Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(local)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.server_close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(prog="invoicegen.web")
    p.add_argument("-p", "--port", type=int, default=8000)
    p.add_argument("--lan", action="store_true",
                   help="let other machines on the network use it")
    p.add_argument("--no-browser", action="store_true")
    a = p.parse_args()
    serve(a.port, not a.no_browser, a.lan)
