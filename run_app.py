"""Entry point for the desktop app and the packaged .exe."""
import os
import sys


def _selftest(out):
    """Prove the bundle works on a machine with no Python installed.

    A --windowed exe has no console, so the result is written to a file:
        "GST Document Generator.exe" --selftest C:\\some\\folder
    """
    from invoicegen.generate import run
    from invoicegen.run_scenarios import run_scenarios

    # the custom-mix path
    rows = run(["credit_note", "debit_note", "tax_invoice", "scanned",
                "intra", "inter", "mix_12_18", "both", "freight", "tds"],
               count=6, seed=1, outdir=out, write_json=True)

    # the scenario catalogue, including a chain and a journal-only event
    srows = run_scenarios(["pur_advance", "sale_goods_local",
                           "fa_depreciation", "cash_to_bank"],
                          count=1, seed=1, outdir=out,
                          formats=("pdf", "png"), write_json=True)

    # the browser UI: the page must render and its offline assets must be
    # inside the bundle, or a friend with no internet gets an unstyled page
    from invoicegen import web
    page = web.render_page()
    assets = web.static_dir()
    web_ok = ("<title>" in page
              and "__SCEN__" not in page  # every placeholder filled in
              and os.path.isfile(os.path.join(assets, "tailwind.js"))
              and os.path.isfile(os.path.join(assets, "fonts.css"))
              and os.path.isdir(os.path.join(assets, "fonts")))

    n_pdf = len(os.listdir(os.path.join(out, "pdf")))
    n_json = len(os.listdir(os.path.join(out, "json")))
    n_png = (len(os.listdir(os.path.join(out, "png")))
             if os.path.isdir(os.path.join(out, "png")) else 0)
    chained = any(r["chain_step"] != "1/1" for r in srows)
    balanced = all(r["balanced"] for r in srows)
    # pur_advance expands to two documents, so four scenarios give five rows;
    # depreciation writes JSON but no PDF, hence the one-file difference
    ok = (len(rows) == 6 and len(srows) == 5 and chained and balanced
          and n_json == n_pdf + 1 and n_png >= 4 and web_ok)

    with open(os.path.join(out, "selftest.txt"), "w", encoding="utf-8") as f:
        f.write(f"custom={len(rows)} scenarios={len(srows)} "
                f"chained={chained} balanced={balanced} "
                f"pdf={n_pdf} json={n_json} web={web_ok}\n")
        f.write("SELFTEST " + ("PASS" if ok else "FAIL") + "\n")
    return 0 if ok else 1


def _serve(lan):
    """Start the local server. Returns (server, port) or (None, None).

    Something else may already hold 8000 - a stale copy of this program, or
    any other tool - so take the next free port rather than failing to start.
    """
    from http.server import ThreadingHTTPServer
    from invoicegen import web

    host = "0.0.0.0" if lan else "127.0.0.1"
    for port in range(8000, 8020):
        try:
            return ThreadingHTTPServer((host, port), web.Handler), port
        except OSError:
            continue
    return None, None


def _fail(msg):
    import tkinter as tk
    import tkinter.messagebox as mb
    tk.Tk().withdraw()
    mb.showerror("GST Document Generator", msg)
    return 1


def _web(lan):
    """Open the generator in its own application window.

    The interface is a web page, so it is drawn by the Edge engine that ships
    with Windows - no browser window, no address bar, and closing the window
    stops the program. Where that engine is missing we fall back to the
    user's browser rather than refusing to start.
    """
    import threading

    srv, port = _serve(lan)
    if srv is None:
        return _fail("Could not start: ports 8000-8019 are all in use.\n\n"
                     "Close any other copy of this program and try again.")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    local = "http://127.0.0.1:%d/" % port

    # Sharing over WiFi means other people open it in their own browser, and
    # they need to be told the address - which only the small window shows.
    if lan:
        return _browser(srv, local, lan, port)

    try:
        import webview
    except ImportError:
        return _browser(srv, local, lan, port)

    try:
        webview.create_window("GST Document Generator", local,
                              width=1500, height=940,
                              min_size=(1000, 640),
                              background_color="#090b14")
        webview.start()
    except Exception:
        # no WebView2 runtime on this machine
        return _browser(srv, local, lan, port)
    srv.shutdown()
    return 0


def _browser(srv, local, lan, port):
    """Fallback: open the user's browser and keep a small window to stop it.

    A --windowed build has no console, so there is nowhere to print the
    address and no Ctrl+C to stop with. This window does both.
    """
    import threading
    import tkinter as tk
    import webbrowser
    from invoicegen import web

    root = tk.Tk()
    root.title("GST Document Generator")
    root.configure(bg="#0e1322")
    tk.Label(root, text="The generator is open in your browser.",
             bg="#0e1322", fg="#e6ebf7",
             font=("Segoe UI", 11, "bold")).pack(padx=28, pady=(22, 6))
    tk.Label(root, text=local, bg="#0e1322", fg="#a78bfa",
             font=("Consolas", 11)).pack()
    if lan:
        tk.Label(root, text="on this WiFi:  http://%s:%d/" % (web.lan_ip(),
                                                              port),
                 bg="#0e1322", fg="#8b98c4",
                 font=("Consolas", 10)).pack(pady=(4, 0))
    tk.Label(root, text="Keep this window open while you use it.",
             bg="#0e1322", fg="#8b98c4",
             font=("Segoe UI", 9)).pack(pady=(10, 4))
    tk.Button(root, text="Stop and close", command=root.destroy,
              bg="#7c3aed", fg="white", relief="flat",
              font=("Segoe UI", 10, "bold"), padx=18,
              pady=6).pack(pady=(6, 22))
    threading.Timer(0.6, lambda: webbrowser.open(local)).start()
    root.mainloop()
    srv.shutdown()
    return 0


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        return _selftest(sys.argv[2])

    # The browser UI is the real one - it gets the current design. The old
    # desktop window stays available with --desktop for a machine where a
    # browser cannot be opened.
    if "--desktop" in sys.argv:
        from invoicegen.app import main as gui
        gui()
        return 0
    return _web("--lan" in sys.argv)


if __name__ == "__main__":
    sys.exit(main())
