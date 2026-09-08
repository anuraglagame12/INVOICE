"""PostToolUse hook: run the CGST/SGST guard after any edit to invoicegen/.

Blocks (exit 2) if the tax-split regression is reintroduced, so the bug that
printed CGST 10,271.03 against SGST 10,271.02 cannot come back unnoticed.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    path = ((data.get("tool_input") or {}).get("file_path") or "")
    norm = path.replace("\\", "/")
    if "invoicegen/" not in norm or not norm.endswith(".py"):
        return 0
    r = subprocess.run([sys.executable, "check_gst_split.py"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode == 0:
        return 0
    sys.stderr.write("CGST/SGST guard failed - the tax split is wrong:\n")
    sys.stderr.write(r.stdout + r.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
