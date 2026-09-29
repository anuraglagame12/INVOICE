"""Draw a bank statement: header block, transaction table, closing summary.

The statement is a plain passbook-style page - account details at the top,
one row per transaction with a running balance, totals at the foot. Amounts
use Indian digit grouping, which is what a bank prints and what `fmt` in
model.py deliberately does not do.

A transaction row carries a headline (what the entry is, in words), the
counterparty beneath it, and the reference in its own column. The raw
channel string a bank packs into the narration is long and unreadable, so
it sits on the second line rather than crowding the first.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas

W, H = A4
L, R = 12 * mm, W - 12 * mm
BOTTOM = 18 * mm

INK = (0.13, 0.13, 0.13)
MUTED = (0.42, 0.42, 0.42)
RULE = (0.80, 0.80, 0.80)
BAND = (0.945, 0.945, 0.945)
HEAD = (0.88, 0.88, 0.88)

# Column geometry, in mm from the left margin. Every amount column is right
# aligned on its edge, and each edge sits clear of the one before it so a
# long reference can never touch a figure.
C_SR = 0.0
C_DATE = 6.0
C_DESC = 25.0
C_REF = 88.0
C_DR = 136.0        # right edge
C_CR = 161.0        # right edge
C_BAL = 186.0       # right edge

DESC_W = (C_REF - C_DESC - 3) * mm
# The reference shares its band with the withdrawal figure to its right.
# A crore-sized amount is about 18mm at 7.5pt, so the reference is given
# what is left of the band rather than the whole of it.
AMOUNT_W = 19 * mm
REF_W = (C_DR - C_REF) * mm - AMOUNT_W - 2 * mm


def rupees(v):
    """Indian digit grouping, two decimals: 4,84,964.50."""
    neg = v < 0
    ip, dp = f"{abs(v):.2f}".split(".")
    if len(ip) > 3:
        head, tail = ip[:-3], ip[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        ip = ",".join(parts) + "," + tail
    return ("-" if neg else "") + ip + "." + dp


def _x(mm_off):
    return L + mm_off * mm


class StatementRenderer:
    TOP = H - 14 * mm

    def __init__(self, stmt, path):
        self.st = stmt
        self.c = pdfcanvas.Canvas(path, pagesize=A4)
        self.c.setTitle(f"Statement {stmt['account']}")
        self.page = 0
        self.pages_total = 1

    # ---------------------------------------------------------- primitives

    def _fit(self, text, font, size, width):
        """Trim to the column, with an ellipsis when something is lost."""
        c = self.c
        if c.stringWidth(text, font, size) <= width:
            return text
        while text and c.stringWidth(text + "...", font, size) > width:
            text = text[:-1]
        return text + "..."

    def _rule(self, y, weight=0.35, colour=RULE):
        c = self.c
        c.setStrokeColorRGB(*colour)
        c.setLineWidth(weight)
        c.line(L, y, R, y)
        c.setStrokeColorRGB(*INK)

    # ---------------------------------------------------------- page parts

    def masthead(self, y):
        """Bank name and branch, over a rule."""
        c, st = self.c, self.st
        c.setFillColorRGB(*INK)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(L, y, st["bank"])
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(*MUTED)
        c.drawRightString(R, y + 0.8 * mm, st["branch_addr"])
        c.setFillColorRGB(*INK)
        y -= 3.5 * mm
        c.setStrokeColorRGB(*INK)
        c.setLineWidth(1.1)
        c.line(L, y, R, y)
        return y - 8 * mm

    def account_block(self, y):
        """Holder on the left, account particulars on the right."""
        c, st = self.c, self.st
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(L, y, "STATEMENT OF ACCOUNT")
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(*MUTED)
        c.drawRightString(R, y, f"{st['from']}  to  {st['to']}")
        c.setFillColorRGB(*INK)
        y -= 6.5 * mm

        top = y
        pad = 4 * mm
        mid = _x(96)

        # left: who the account belongs to
        ty = top - 5.5 * mm
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(L + pad, ty, st["holder"])
        ty -= 4.6 * mm
        c.setFont("Helvetica", 7.5)
        c.setFillColorRGB(*MUTED)
        for line in st["holder_addr"]:
            c.drawString(L + pad, ty, line)
            ty -= 3.8 * mm
        if st.get("gstin"):
            c.drawString(L + pad, ty, f"GSTIN  {st['gstin']}")
            ty -= 3.8 * mm
        c.setFillColorRGB(*INK)

        # right: the particulars, label left, value right
        py = top - 5.5 * mm
        pairs = [("Account Number", st["account"]),
                 ("Account Type", st["acct_type"]),
                 ("IFSC", st["ifsc"]),
                 ("Branch", st["branch"]),
                 ("Currency", "INR")]
        for label, val in pairs:
            c.setFont("Helvetica", 7.5)
            c.setFillColorRGB(*MUTED)
            c.drawString(mid + pad, py, label)
            c.setFillColorRGB(*INK)
            c.setFont("Helvetica-Bold", 7.5)
            c.drawRightString(R - pad, py, str(val))
            py -= 5.0 * mm

        bot = min(ty, py) - 1.5 * mm
        c.setStrokeColorRGB(*RULE)
        c.setLineWidth(0.5)
        c.rect(L, bot, R - L, top - bot)
        c.line(mid, bot, mid, top)
        c.setStrokeColorRGB(*INK)
        return bot - 9 * mm

    def table_head(self, y):
        c = self.c
        h = 6.2 * mm
        c.setFillColorRGB(*HEAD)
        c.rect(L, y - h, R - L, h, stroke=0, fill=1)
        c.setFillColorRGB(*INK)
        ty = y - 4.2 * mm
        c.setFont("Helvetica-Bold", 7.2)
        c.drawString(_x(C_SR), ty, "#")
        c.drawString(_x(C_DATE), ty, "DATE")
        c.drawString(_x(C_DESC), ty, "PARTICULARS")
        c.drawString(_x(C_REF), ty, "REFERENCE")
        c.drawRightString(_x(C_DR), ty, "WITHDRAWAL")
        c.drawRightString(_x(C_CR), ty, "DEPOSIT")
        c.drawRightString(_x(C_BAL), ty, "BALANCE")
        c.setStrokeColorRGB(*RULE)
        c.setLineWidth(0.5)
        c.rect(L, y - h, R - L, h, stroke=1, fill=0)
        c.setStrokeColorRGB(*INK)
        return y - h

    def row(self, y, r, shade=False):
        """One transaction. Headline, then the detail lines beneath it."""
        c = self.c
        detail = r["desc"][1:]
        h = (5.4 + 3.3 * len(detail)) * mm

        if shade:
            c.setFillColorRGB(*BAND)
            c.rect(L, y - h, R - L, h, stroke=0, fill=1)
            c.setFillColorRGB(*INK)

        base = y - 4.0 * mm
        c.setFont("Helvetica", 7.5)
        c.drawString(_x(C_SR), base, str(r["sr"]))
        c.drawString(_x(C_DATE), base, r["date"])

        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(_x(C_DESC), base,
                     self._fit(r["desc"][0], "Helvetica-Bold", 7.5, DESC_W))

        c.setFont("Helvetica", 6.8)
        c.setFillColorRGB(*MUTED)
        c.drawString(_x(C_REF), base,
                     self._fit(r["ref"], "Helvetica", 6.8, REF_W))
        c.setFillColorRGB(*INK)

        c.setFont("Helvetica", 7.5)
        if r.get("dr") is not None:
            c.drawRightString(_x(C_DR), base, rupees(r["dr"]))
        if r.get("cr") is not None:
            c.drawRightString(_x(C_CR), base, rupees(r["cr"]))
        if r.get("balance") is not None:
            c.drawRightString(_x(C_BAL), base, rupees(r["balance"]))

        dy = base - 3.3 * mm
        c.setFont("Helvetica", 6.6)
        c.setFillColorRGB(*MUTED)
        for line in detail:
            c.drawString(_x(C_DESC), dy,
                         self._fit(line, "Helvetica", 6.6, DESC_W))
            dy -= 3.3 * mm
        c.setFillColorRGB(*INK)

        self._rule(y - h)
        return y - h

    def opening_row(self, y):
        c = self.c
        h = 5.4 * mm
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(_x(C_DESC), y - 4.0 * mm, "Opening Balance")
        c.drawRightString(_x(C_BAL), y - 4.0 * mm, rupees(self.st["opening"]))
        self._rule(y - h)
        return y - h

    def totals_row(self, y):
        c, st = self.c, self.st
        h = 6.2 * mm
        c.setFillColorRGB(*HEAD)
        c.rect(L, y - h, R - L, h, stroke=0, fill=1)
        c.setFillColorRGB(*INK)
        ty = y - 4.2 * mm
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(_x(C_DESC), ty, "Total")
        c.drawRightString(_x(C_DR), ty, rupees(st["total_dr"]))
        c.drawRightString(_x(C_CR), ty, rupees(st["total_cr"]))
        c.drawRightString(_x(C_BAL), ty, rupees(st["closing"]))
        c.setStrokeColorRGB(*RULE)
        c.setLineWidth(0.5)
        c.rect(L, y - h, R - L, h, stroke=1, fill=0)
        c.setStrokeColorRGB(*INK)
        return y - h

    def summary(self, y):
        c, st = self.c, self.st
        y -= 10 * mm
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(L, y, "SUMMARY")
        y -= 5 * mm

        pairs = [("Opening Balance", st["opening"]),
                 ("Total Withdrawals", st["total_dr"]),
                 ("Total Deposits", st["total_cr"]),
                 ("Closing Balance", st["closing"])]
        box_w = 82 * mm
        row_h = 5.6 * mm
        top = y
        yy = y
        for i, (k, v) in enumerate(pairs):
            last = i == len(pairs) - 1
            if last:
                c.setFillColorRGB(*BAND)
                c.rect(L, yy - row_h, box_w, row_h, stroke=0, fill=1)
                c.setFillColorRGB(*INK)
            c.setFont("Helvetica-Bold" if last else "Helvetica", 7.8)
            c.drawString(L + 4 * mm, yy - 3.9 * mm, k)
            c.drawRightString(L + box_w - 4 * mm, yy - 3.9 * mm, rupees(v))
            yy -= row_h
            if not last:
                c.setStrokeColorRGB(*RULE)
                c.setLineWidth(0.35)
                c.line(L, yy, L + box_w, yy)
                c.setStrokeColorRGB(*INK)
        c.setStrokeColorRGB(*RULE)
        c.setLineWidth(0.5)
        c.rect(L, yy, box_w, top - yy)
        c.setStrokeColorRGB(*INK)

        nx = L + box_w + 8 * mm
        c.setFont("Helvetica", 7.2)
        c.setFillColorRGB(*MUTED)
        c.drawString(nx, top - 3.9 * mm,
                     f"{st['txn_count']} transactions in this period.")
        c.drawString(nx, top - 8.5 * mm,
                     "Please report any discrepancy to the branch")
        c.drawString(nx, top - 12.3 * mm, "within 30 days of this statement.")
        c.setFillColorRGB(*INK)
        return yy

    def footer(self):
        c, st = self.c, self.st
        self._rule(BOTTOM + 2 * mm, 0.5)
        c.setFont("Helvetica", 6.5)
        c.setFillColorRGB(*MUTED)
        c.drawString(L, BOTTOM - 2 * mm, st["holder"])
        c.drawCentredString(W / 2, BOTTOM - 2 * mm, f"Account {st['account']}")
        c.drawRightString(R, BOTTOM - 2 * mm,
                          f"Page {self.page} of {self.pages_total}")
        c.drawCentredString(W / 2, BOTTOM - 5.5 * mm,
                            "This is a computer generated statement and does "
                            "not require a signature.")
        c.setFillColorRGB(*INK)

    # ---------------------------------------------------------- the document

    def _row_height(self, r):
        return (5.4 + 3.3 * (len(r["desc"]) - 1)) * mm

    # room the totals strip and summary need below the last row
    CLOSING_H = 46 * mm

    def _paginate(self):
        """Split rows into pages by measured height, not a row count.

        The last page has to carry the totals and the summary, so the run is
        laid out once and then, if the closing block would not fit under the
        final row, enough rows are pushed onto a further page to make room -
        which is tidier than leaving a page holding nothing but the total.
        """
        st = self.st
        first_avail = self.TOP - 62 * mm - BOTTOM - 8 * mm - 5.4 * mm
        next_avail = self.TOP - 16 * mm - BOTTOM - 8 * mm

        pages = []
        cur = []
        avail = first_avail
        for r in st["rows"]:
            h = self._row_height(r)
            if cur and h > avail:
                pages.append(cur)
                cur = []
                avail = next_avail
            cur.append(r)
            avail -= h
        if cur:
            pages.append(cur)
        if not pages:
            return [[]]

        # Make room for the closing block on the final page by moving whole
        # rows off the end until it fits - all in one go, so the spill lands
        # on a single further page rather than cascading.
        if avail < self.CLOSING_H and len(pages[-1]) > 1:
            need = self.CLOSING_H - avail
            moved = []
            while pages[-1] and need > 0:
                r = pages[-1].pop()
                moved.insert(0, r)
                need -= self._row_height(r)
            if moved and pages[-1]:
                pages.append(moved)
            else:
                pages[-1] = moved + pages[-1]
        return pages

    def build(self):
        c, st = self.c, self.st
        pages = self._paginate()
        self.pages_total = len(pages)

        for idx, chunk in enumerate(pages):
            self.page = idx + 1
            first = idx == 0
            last = idx == len(pages) - 1

            y = self.TOP
            y = self.masthead(y)
            if first:
                y = self.account_block(y)
            else:
                c.setFont("Helvetica", 8)
                c.setFillColorRGB(*MUTED)
                c.drawString(L, y, f"{st['holder']}  -  continued")
                c.setFillColorRGB(*INK)
                y -= 6 * mm

            y = self.table_head(y)
            if first:
                y = self.opening_row(y)

            for i, r in enumerate(chunk):
                y = self.row(y, r, shade=(i % 2 == 1))

            if last:
                y = self.totals_row(y)
                self.summary(y)

            self.footer()
            if not last:
                c.showPage()

        c.save()
        return self.pages_total


def render_statement(stmt, path):
    """Write the statement PDF. Returns the page count."""
    return StatementRenderer(stmt, path).build()
