"""Put the generator on the internet for a short session.

Starts the web server, then opens a Cloudflare quick tunnel and prints the
public link. Anyone you send that link to can use the generator from any
network - no install, no account, works on Mac, phone, anything.

    python share_online.py

Press Ctrl+C to stop. The link dies with it.

NOTE: the page has no password. Treat the link as the key: send it to the
person who needs it, and stop the tunnel when you are done.
"""
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED = os.path.join(HERE, "tools", "cloudflared.exe")
PORT = 8000

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def start_server():
    """Run the web UI in this process, on a background thread."""
    sys.path.insert(0, HERE)
    from invoicegen.web import serve
    t = threading.Thread(
        target=lambda: serve(PORT, open_browser=False, lan=True),
        daemon=True)
    t.start()
    time.sleep(1.5)
    return t


def start_tunnel():
    """Open a quick tunnel and return (process, public_url)."""
    if not os.path.exists(CLOUDFLARED):
        print("cloudflared is missing. Expected it at:")
        print("   ", CLOUDFLARED)
        print("Download it from:")
        print("    https://github.com/cloudflare/cloudflared/releases/latest"
              "/download/cloudflared-windows-amd64.exe")
        return None, None

    proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", "http://localhost:%d" % PORT,
         "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1)

    url = None
    deadline = time.time() + 45
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        m = URL_RE.search(line)
        if m:
            url = m.group()
            break
    return proc, url


def main():
    # show output straight away rather than buffering it
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    print("Starting the generator...")
    start_server()
    print("Opening a public link (this takes a few seconds)...\n")
    proc, url = start_tunnel()

    if not url:
        print("Could not open the tunnel. The generator is still running")
        print("on this machine at http://localhost:%d/" % PORT)
        if proc:
            proc.terminate()
        return 1

    line = "=" * 60
    print(line)
    print("  SEND THIS LINK TO YOUR FRIEND")
    print()
    print("     %s" % url)
    print()
    print("  It works from any network, on any device.")
    print("  Nothing needs to be installed on their machine.")
    print(line)
    print()
    print("  Keep this window open. Press Ctrl+C to stop sharing.")
    print("  The link stops working the moment you do.")
    print()

    try:
        while proc.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        proc.terminate()
        print("link closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
