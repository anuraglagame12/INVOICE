"""Draw a logo in the top-left corner of a document.

Kept in one place so every layout puts it the same way: scaled to fit a fixed
box, proportions kept, transparency respected. Returns how much horizontal
room it took, so the supplier name can shift right to clear it.
"""
from reportlab.lib.units import mm

BOX_W = 32 * mm          # the most a logo may occupy
BOX_H = 16 * mm


def draw(c, path, x, y_top):
    """Draw `path` with its top-left at (x, y_top). Returns the width used.

    A missing or unreadable file simply draws nothing, so a bad path can
    never stop an invoice being produced.
    """
    if not path:
        return 0
    try:
        from reportlab.lib.utils import ImageReader
        img = ImageReader(path)
        iw, ih = img.getSize()
        if not iw or not ih:
            return 0
        scale = min(BOX_W / iw, BOX_H / ih)
        w, h = iw * scale, ih * scale
        c.drawImage(img, x, y_top - h, width=w, height=h,
                    mask="auto", preserveAspectRatio=True)
        return w + 3 * mm
    except Exception:
        return 0
