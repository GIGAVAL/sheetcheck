"""
Tiny synthetic bid-set PDFs for fast tests.

Instead of the real 40 MB sets, we generate small PDFs whose title blocks
reproduce the geometry SheetCheck relies on: sheet number in a large font in
the bottom-right corner, sheet title at a template-specific size/orientation,
and a two- or three-column sheet index. This keeps the whole test suite in
memory and runs in well under a second.

Coordinates are in PDF points. reportlab's origin is bottom-left; pdfplumber's
"top" is measured from the top, so we place things by (x, y_from_bottom) and
the numbers below were chosen so they land in SheetCheck's title-block strip.
"""

from reportlab.pdfgen import canvas

PAGE = (3024, 2160)   # same big landscape sheet as the real sets
H = PAGE[1]


def _text(c, x, y_top, size, s):
    """Draw upright text; y_top is distance from the TOP of the page."""
    c.setFont("Helvetica", size)
    c.drawString(x, H - y_top, s)


def _rot_text(c, x, y_top, size, s):
    """Draw text rotated 90deg (reads bottom-to-top), like G&P titles."""
    c.saveState()
    c.setFont("Helvetica", size)
    c.translate(x, H - y_top)
    c.rotate(90)
    c.drawString(0, 0, s)
    c.restoreState()


def smithgroup_sheet(path, sheet_number="A2.2.1", title_words=("ROOF", "PLAN", "-", "OVERALL"),
                     architect="SMITHGROUP.COM"):
    """One SmithGroup-style drawing sheet with a horizontal title."""
    c = canvas.Canvas(path, pagesize=PAGE)
    # Title block sits in the lower-right corner (top ~1870-2100 of 2160).
    _text(c, 2745, 2097, 9, "SHEET NUMBER")
    _text(c, 2740, 2055, 40, "CD")              # decoy: big, but no digit
    _text(c, 2890, 2047, 41, sheet_number)      # the real sheet number
    _text(c, 2745, 1871, 9, "SHEET TITLE")
    # lay the title words left-to-right at 22 pt (title size), spacing each by
    # its real rendered width plus a gap so pdfplumber keeps them separate.
    c.setFont("Helvetica", 22)
    x = 2750
    for w in title_words:
        c.drawString(x, H - 1890, w)
        x += c.stringWidth(w, "Helvetica", 22) + 20
    _text(c, 2745, 2120, 6, architect)          # architect marker for detection
    c.showPage()
    c.save()


def grimm_parker_sheet(path, sheet_number="A-1.1", title="PARTIAL FIRST FLOOR PLAN - AREA A",
                       project="HOLABIRD ACADEMY PK-8", architect="GRIMM AND PARKER"):
    """One Grimm & Parker-style drawing sheet with a rotated title."""
    c = canvas.Canvas(path, pagesize=PAGE)
    _text(c, 2745, 2000, 9, "SHEET NUMBER")
    _text(c, 2846, 2015, 38, sheet_number)      # large number, bottom-right
    # rotated title column (leftmost) + project name column (to its right)
    _rot_text(c, 2820, 1820, 13, title)
    _rot_text(c, 2880, 1820, 13, project)
    _text(c, 2745, 2100, 6, architect)
    c.showPage()
    c.save()


def index_page(path, entries, columns, architect, number_font=9, page_no_note=None):
    """A sheet-index page: `entries` laid out across `columns` x-positions.

    entries: list of (sheet_number, title)
    columns: list of x-positions (one per column); entries fill down each
             column in order.
    """
    c = canvas.Canvas(path, pagesize=PAGE)
    _text(c, columns[0], 250, 6, architect)     # marker so detection works
    per_col = (len(entries) + len(columns) - 1) // len(columns)
    i = 0
    for col_x in columns:
        y = 350
        for _ in range(per_col):
            if i >= len(entries):
                break
            num, title = entries[i]
            _text(c, col_x, y, number_font, num)
            _text(c, col_x + 70, y, number_font, title)
            y += 14
            i += 1
    c.showPage()
    c.save()
