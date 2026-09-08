"""Turn a rendered PDF into PNG pages.

The PDF is always the source of truth - the PNG is a picture of it - so the
two can never disagree about what the document says. A multi-page document
becomes one PNG per page, suffixed _p1, _p2 and so on.
"""
import os

DPI = 150          # sharp enough for OCR without huge files


def available():
    """Is a rasteriser installed?"""
    try:
        import pymupdf                                   # noqa: F401
        return True
    except ImportError:
        try:
            import fitz                                  # noqa: F401
            return True
        except ImportError:
            return False


def _open(path):
    try:
        import pymupdf
        return pymupdf.open(path)
    except ImportError:
        import fitz
        return fitz.open(path)


def pdf_to_png(pdf_path, out_dir, stem, dpi=DPI):
    """Write PNG pages for `pdf_path`. Returns the files written."""
    if not available():
        return []
    os.makedirs(out_dir, exist_ok=True)
    doc = _open(pdf_path)
    zoom = dpi / 72.0                       # PDF user units are 72 per inch
    written = []
    try:
        import pymupdf as _mu
    except ImportError:
        import fitz as _mu
    matrix = _mu.Matrix(zoom, zoom)
    try:
        for i, page in enumerate(doc, 1):
            pix = page.get_pixmap(matrix=matrix)
            name = stem if doc.page_count == 1 else "%s_p%d" % (stem, i)
            path = os.path.join(out_dir, name + ".png")
            pix.save(path)
            written.append(path)
    finally:
        doc.close()
    return written
