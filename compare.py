"""
BC Compare GUI - Tkinter frontend for Beyond Compare diff reporting.
Replaces config.json with folder pickers. BCompare assumed on PATH.
"""

import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# ─── Constants ────────────────────────────────────────────────────────────────

APP_TITLE = "BC Compare"
VERSION = "1.0"

FILTER_OPTIONS = [
    ("*.*  —  No Filters (All files)", "*.*"),
    ("Exclude build artifacts (.exe .ilk .a .lib .exp .o .vcproj debug bin .pdb .tlog .bsc)",
     "-*.exe;-*.ilk;-*.a;-*.lib;-*.exp;-*.o;-*vcproj;-res\\;-debug\\;-bin\\;-.debug\\;-*.pdb;-*.tlog;-*bsc;"),
    ("Exclude build artifacts (no .pdb/.tlog/.bsc)",
     "-*.exe;-*.ilk;-*.a;-*.lib;-*.exp;-*.o;-*vcproj;-res\\;-debug\\;-bin\\;-.debug\\;"),
    ("Custom filter…", "__custom__"),
]

REPORT_OPTIONS = [
    "display-all",
    "display-mismatches",
    "display-no-orphans",
    "display-mismatches-no-orphans",
    "display-orphans",
    "display-left-newer",
    "display-right-newer",
    "display-left-newer-orphans",
    "display-right-newer-orphans",
    "display-left-orphans",
    "display-right-orphans",
    "display-matches",
]

FOLDER_SCRIPT_TEMPLATE = """\
criteria crc
log verbose "configurations\\log.txt"
filter "{filters}"
load %1 %2
expand all
select all
folder-report layout:side-by-side &
    options:{display},include-file-links,column-size &
    output-to:%3 &
    output-options:html-color
"""

FILE_SCRIPT_TEMPLATE = """\
text-report layout:side-by-side options:{{display}} output-to:"%3" output-options:html-color "%1" "%2"
"""

# Colours & fonts
BG        = "#0f1117"
SURFACE   = "#1a1d27"
SURFACE2  = "#22263a"
ACCENT    = "#4f8ef7"
ACCENT2   = "#7c3aed"
SUCCESS   = "#22c55e"
WARNING   = "#f59e0b"
DANGER    = "#ef4444"
TEXT      = "#e8eaf0"
SUBTEXT   = "#8b93a7"
BORDER    = "#2e3347"

FONT_TITLE  = ("Courier New", 20, "bold")
FONT_HEAD   = ("Courier New", 11, "bold")
FONT_BODY   = ("Courier New", 10)
FONT_SMALL  = ("Courier New", 9)
FONT_MONO   = ("Courier New", 9)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def resource_path(relative_path):
    """Handle PyInstaller bundled paths."""
    base = getattr(sys, '_MEIPASS', Path(__file__).parent)
    return Path(base) / relative_path


def make_output_name(filename: str) -> str:
    p = Path(filename)
    return f"{p.stem}_{p.suffix.lstrip('.')}_diff.html"


def has_differences(output_path: Path) -> bool:
    if not output_path.exists():
        return False
    content = output_path.read_text(encoding="utf-8", errors="ignore")
    markers = ['class="SectionDiff"', 'class="TextDiff"',
               'class="DiffChange"', 'Changed', 'Deleted', 'Inserted']
    return any(m in content for m in markers)


def get_files(left: Path, right: Path):
    left_files  = {p.name: p for p in left.iterdir()  if p.is_file()}
    right_files = {p.name: p for p in right.iterdir() if p.is_file()}
    matched, deleted, created = [], [], []
    for name, lp in left_files.items():
        if name in right_files:
            matched.append({'filename': name, 'left': lp, 'right': right_files[name]})
        else:
            deleted.append(lp)
    for name, rp in right_files.items():
        if name not in left_files:
            created.append(rp)
    return matched, deleted, created


def bc_diff_cmd(left: Path, right: Path, bc_path: str, script_path: Path,
                output_path: Path, log_fn=None,
                proc_holder: list = None) -> bool:
    """
    Launch BCompare.exe and wait for it to finish.
    proc_holder: a 1-element list; the Popen object is stored there so the
    caller can kill() it from another thread if the user hits Stop.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "<!DOCTYLE html><html><body><p>Generating diff…</p></body></html>",
        encoding="utf-8"
    )
    command = [bc_path, f"@{script_path}", str(left), str(right), str(output_path)]
    try:
        proc = subprocess.Popen(command, shell=False,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        if proc_holder is not None:
            proc_holder[0] = proc          # expose to Stop button
        returncode = proc.wait()           # blocks until BC exits
        if proc_holder is not None:
            proc_holder[0] = None
        if log_fn:
            log_fn(f"  BC exit code: {returncode}")
        if returncode == 2:
            if log_fn:
                log_fn("  ⚠  BC script error")
            return False
        return True
    except Exception as e:
        if log_fn:
            log_fn(f"  ✗ Error: {e}")
        return False


def convert_html_to_pdf(html_folder: Path, pdf_folder: Path, log_fn=None):
    """Convert all HTMLs in folder to PDF using weasyprint."""
    try:
        from weasyprint import HTML, CSS
    except ImportError:
        if log_fn:
            log_fn("  ✗ weasyprint not installed – skipping PDF conversion")
        return
    css = CSS(string="""
        @page { size: legal landscape; margin-left:1cm; margin-right:1cm; margin-bottom:0.1cm; }
        body  { transform: scale(0.90); transform-origin: top left; }
    """)
    pdf_folder.mkdir(parents=True, exist_ok=True)
    for filename in os.listdir(html_folder):
        if filename.endswith(".html"):
            hp = html_folder / filename
            pp = pdf_folder / filename.replace(".html", ".pdf")
            if log_fn:
                log_fn(f"  Converting {filename} → PDF")
            HTML(filename=str(hp)).write_pdf(str(pp), stylesheets=[css])
    if log_fn:
        log_fn("  ✓ PDF conversion done")




# ─── Markup Helpers ───────────────────────────────────────────
#
# Faithful port of markup.py.
#
# parseHtml  → annotate_file_diff
#   Reads one BC per-file diff HTML, counts changed sections, inserts a
#   count cell at the start of each row, writes to output/markup/reports/.
#
# getDiffReports → folder_markup
#   Reads the BC folder-level report.html, finds DirItemDiff rows,
#   follows their per-file links, calls annotate_file_diff on each.
#
# fileMarkup → file_markup
#   Iterates every HTML in a flat folder, calls annotate_file_diff on each.
#
# Helpers shared by both:
#   _get_info   — extract (filename, href) from the first <a> in an element
#   _new_cell   — create and prepend a count <td>/<th> to a row

SECTION_OPTIONS    = {"SectionBegin", "SectionAll"}
COMPARISON_OPTIONS = {"-+", "<>"}


def _get_info(element):
    """Return (filename, href) from the first <a href> in element."""
    for tag in element.find_all("a", href=True):
        return tag.get_text(), tag.get("href")   # return on first match
    return None, None


def _new_cell(soup, row, i: int, text: str):
    """Prepend a <th> (header row) or <td class='AlignCenter Wrap'> to row."""
    cell          = soup.new_tag("th" if i == 0 else "td")
    cell["class"] = "AlignCenter Wrap"
    cell.string   = text
    row.insert(0, cell)


def _section_type(row) -> str:
    """Return the row's CSS class string, e.g. 'SectionBegin'."""
    classes = row.get("class", [])
    return " ".join(classes) if classes else ""


def _comparison_type(row) -> str:
    """Return text of the AlignCenter Wrap cell, or '' if absent."""
    cell = row.find("td", class_="AlignCenter Wrap")
    return cell.get_text(strip=True) if cell else ""


def annotate_file_diff(html_filepath, markup_folder_path, output_file_name,
                       log_fn=None) -> int:
    """
    Read a BC per-file diff HTML, insert a change-count column, and write
    the result to markup_folder_path/markup/reports/<output_file_name>_diff.html.
    Returns number of changes found, or 0 if none / error.
    """
    if not BS4_AVAILABLE:
        if log_fn: log_fn("  ✗ beautifulsoup4 not installed")
        return 0
    try:
        content = Path(html_filepath).read_text(encoding="utf-8", errors="ignore")
        soup    = BeautifulSoup(content, "html.parser")
        rows    = soup.find_all("tr")

        changes_detected = False
        count            = 1

        for i, row in enumerate(rows):
            stype = _section_type(row)
            ctype = _comparison_type(row)

            if stype in SECTION_OPTIONS:
                # Section start — check whether it's an actual change
                if ctype in COMPARISON_OPTIONS:
                    changes_detected = True
                    _new_cell(soup, row, i, str(count))
                    count += 1
                else:
                    changes_detected = False
                    _new_cell(soup, row, i, "")

            elif stype == "SectionMiddle":
                _new_cell(soup, row, i, "")

            elif stype == "SectionEnd":
                # SectionEnd with TextItemSigMod means a real text change landed here
                if row.find("td", class_="TextItemSigMod Wrap"):
                    _new_cell(soup, row, i, str(count))
                    count += 1
                else:
                    _new_cell(soup, row, i, "")
                changes_detected = False

            else:
                # Regular row — carry count if inside a detected change
                if changes_detected:
                    _new_cell(soup, row, i, str(count))
                    count += 1
                else:
                    _new_cell(soup, row, i, "")

        if count == 1:
            return 0   # nothing was changed, skip writing

        out = (Path(markup_folder_path) / "markup" / "reports"
               / f"{output_file_name}_diff.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(str(soup), encoding="utf-8")

        if log_fn: log_fn(f"  ✓ {output_file_name}: {count - 1} change(s)")
        return count - 1

    except Exception as e:
        if log_fn: log_fn(f"  ✗ Error in {output_file_name}: {e}")
        return 0


def folder_markup(filepath, output_path, log_fn=None):
    """
    Read BC folder-level report.html at filepath/report.html.
    Find DirItemDiff rows, follow each file link, call annotate_file_diff.
    """
    report  = Path(filepath) / "report.html"
    bc_dir  = report.parent
    try:
        content   = report.read_text(encoding="utf-8", errors="ignore")
        soup      = BeautifulSoup(content, "html.parser")
        diff_rows = soup.find_all("tr", class_="DirItemDiff")
        if not diff_rows:
            if log_fn: log_fn("  No DirItemDiff rows found in report.html")
            return
        if log_fn: log_fn(f"  {len(diff_rows)} changed file(s) found")
        for row in diff_rows:
            filename, href = _get_info(row)
            if not filename or not href:
                continue
            num_changes = annotate_file_diff(
                bc_dir / href, output_path, filename, log_fn=log_fn)
            if log_fn and num_changes == 0:
                log_fn(f"  — {filename}: no changes")
    except Exception as e:
        if log_fn: log_fn(f"  ✗ folder_markup error: {e}")


def file_markup(folder_path, output_filepath, log_fn=None):
    """Annotate every HTML file in folder_path."""
    try:
        files = [f for f in Path(folder_path).iterdir()
                 if f.is_file() and f.suffix.lower() == ".html"]
        if not files:
            if log_fn: log_fn("  No HTML files found in folder.")
            return
        if log_fn: log_fn(f"  Processing {len(files)} file(s)…")
        for f in files:
            annotate_file_diff(f, output_filepath, f.stem, log_fn=log_fn)
    except Exception as e:
        if log_fn: log_fn(f"  ✗ file_markup error: {e}")


# ─── BC HTML Parsers ──────────────────────────────────────────────────────────
#
# Beyond Compare folder-report HTML structure:
#   <table class="report"> or similar outer table
#     Each file row has cells: filename | left-status | right-status | etc.
#     CSS classes on <tr>/<td> indicate the diff state:
#       "SectionDiff"  → files differ
#       "Orphan"       → file only on one side (orphan/created/deleted)
#       no diff class  → files match
#
# Beyond Compare text-report (per-file) HTML structure:
#   Side-by-side table with left/right columns
#   Changed lines carry class="TextDiff" or "DiffChange"
#   Each <tr> represents one line pair
#
# ParsedFile  — one file entry from a folder report
# ParsedLine  — one line pair from a per-file report
# BCReportParser — main entry point; auto-detects report type

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ParsedFile:
    """One row from a BC folder-compare report."""
    filename:    str
    status:      str          # "different" | "orphan-left" | "orphan-right" | "identical"
    left_path:   str = ""
    right_path:  str = ""
    diff_link:   str = ""     # href to the per-file diff if BC included links
    raw_classes: List[str] = field(default_factory=list)


@dataclass
class ParsedLine:
    """One line-pair from a BC per-file text-compare report."""
    line_num_left:  Optional[int]
    line_num_right: Optional[int]
    text_left:      str
    text_right:     str
    status:         str   # "changed" | "inserted" | "deleted" | "identical"


@dataclass
class BCParseResult:
    """Everything extracted from one BC HTML report."""
    report_type:    str           # "folder" | "file" | "unknown"
    source_path:    Path
    files:          List[ParsedFile] = field(default_factory=list)   # folder report
    lines:          List[ParsedLine] = field(default_factory=list)   # file report
    total:          int = 0
    different:      int = 0
    orphans:        int = 0
    identical:      int = 0
    parse_error:    str = ""


class BCReportParser:
    """
    Parse a Beyond Compare HTML report (folder or per-file) using BeautifulSoup.

    Usage:
        result = BCReportParser.parse(Path("output/report.html"))
        for f in result.files:
            print(f.filename, f.status)

    Works with both:
      - Folder compare reports  (single HTML, table of all files)
      - Per-file text reports   (side-by-side line diff)
    """

    # CSS class fragments BC uses to mark diff state
    _DIFF_CLASSES    = {"SectionDiff", "TextDiff", "DiffChange"}
    _ORPHAN_CLASSES  = {"Orphan", "OrphanLeft", "OrphanRight"}
    _CHANGED_CLASSES = {"Changed", "DiffChange", "TextDiff", "SectionDiff"}
    _INSERT_CLASSES  = {"Inserted", "OrphanRight"}
    _DELETE_CLASSES  = {"Deleted", "OrphanLeft"}

    @classmethod
    def parse(cls, html_path: Path) -> BCParseResult:
        result = BCParseResult(report_type="unknown", source_path=html_path)
        if not BS4_AVAILABLE:
            result.parse_error = "beautifulsoup4 not installed — pip install beautifulsoup4"
            return result
        if not html_path.exists():
            result.parse_error = f"File not found: {html_path}"
            return result
        try:
            text = html_path.read_text(encoding="utf-8", errors="ignore")
            soup = BeautifulSoup(text, "html.parser")
            # Detect report type by looking for BC folder-report markers
            if cls._is_folder_report(soup):
                result.report_type = "folder"
                cls._parse_folder(soup, result)
            else:
                result.report_type = "file"
                cls._parse_file(soup, result)
        except Exception as e:
            result.parse_error = str(e)
        return result

    @classmethod
    def parse_folder(cls, folder: Path) -> List[BCParseResult]:
        """
        Parse every .html file in a folder.
        Returns a list of BCParseResult, one per file.
        """
        results = []
        if not folder.exists():
            return results
        for p in sorted(folder.glob("*.html")):
            results.append(cls.parse(p))
        return results

    # ── Detection ─────────────────────────────────────────────────────────────

    @classmethod
    def _is_folder_report(cls, soup) -> bool:
        """
        BC folder reports contain a table with file rows.
        BC file reports contain side-by-side line diffs.
        Heuristic: look for the folder-report marker class or structure.
        """
        # BC folder reports have a div or table with class containing "FolderReport"
        # or have multiple file links in the first column
        if soup.find(class_="FolderReport"):
            return True
        if soup.find(class_="folder-report"):
            return True
        # Fallback: if the page has many anchor links to other HTML files it is
        # a folder report (BC links each row to its per-file diff)
        links = soup.find_all("a", href=True)
        html_links = [l for l in links if l["href"].endswith(".html")]
        if len(html_links) >= 2:
            return True
        # If it has line-number columns on both sides it is a file report
        if soup.find(class_="TextDiff") or soup.find(class_="DiffChange"):
            return False
        # Default: treat as folder report if it has a big outer table
        tables = soup.find_all("table")
        return len(tables) == 1 and len(tables[0].find_all("tr")) > 3

    # ── Folder report parser ───────────────────────────────────────────────────

    @classmethod
    def _parse_folder(cls, soup, result: BCParseResult):
        """
        Extract one ParsedFile per row from a BC folder-compare report.
        BC renders each file as a <tr> inside the main report table.
        """
        rows = soup.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if not cells:
                continue   # header row

            # The filename is in the first <td>, possibly inside an <a>
            first_cell = cells[0]
            anchor = first_cell.find("a")
            filename = (anchor.get_text(strip=True) if anchor
                        else first_cell.get_text(strip=True))
            if not filename:
                continue

            diff_link = anchor["href"] if anchor and anchor.get("href") else ""

            # Determine status from CSS classes on the row or its cells
            row_classes = row.get("class", [])
            cell_classes = []
            for c in cells:
                cell_classes.extend(c.get("class", []))
            all_classes = set(row_classes + cell_classes)

            status = cls._classify_folder_row(all_classes)

            pf = ParsedFile(
                filename=filename,
                status=status,
                diff_link=diff_link,
                raw_classes=list(all_classes),
            )
            result.files.append(pf)

            # Tally
            result.total += 1
            if status == "different":
                result.different += 1
            elif status in ("orphan-left", "orphan-right"):
                result.orphans += 1
            else:
                result.identical += 1

    @classmethod
    def _classify_folder_row(cls, classes: set) -> str:
        classes_lower = {c.lower() for c in classes}
        if any(c in classes_lower for c in ("orphanleft", "orphan-left")):
            return "orphan-left"
        if any(c in classes_lower for c in ("orphanright", "orphan-right")):
            return "orphan-right"
        if any(c in classes_lower for c in ("orphan",)):
            return "orphan-left"   # generic orphan — only on left side
        if any(c in classes_lower for c in
               ("sectiondiff", "textdiff", "diffchange", "changed")):
            return "different"
        return "identical"

    # ── Per-file report parser ─────────────────────────────────────────────────

    @classmethod
    def _parse_file(cls, soup, result: BCParseResult):
        """
        Extract one ParsedLine per row from a BC per-file text-compare report.
        BC renders the diff as a 2-column (or 4-column with line numbers) table.
        """
        rows = soup.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            row_classes = set(row.get("class", []))
            cell_classes = set()
            for c in cells:
                cell_classes.update(c.get("class", []))
            all_classes = row_classes | cell_classes

            # BC 4-column layout: linenum-left | text-left | linenum-right | text-right
            # BC 2-column layout: text-left | text-right
            if len(cells) >= 4:
                ln_left  = cls._parse_linenum(cells[0].get_text(strip=True))
                text_left  = cells[1].get_text()
                ln_right = cls._parse_linenum(cells[2].get_text(strip=True))
                text_right = cells[3].get_text()
            else:
                ln_left = ln_right = None
                text_left  = cells[0].get_text()
                text_right = cells[1].get_text()

            status = cls._classify_line(all_classes)
            pl = ParsedLine(
                line_num_left=ln_left,
                line_num_right=ln_right,
                text_left=text_left,
                text_right=text_right,
                status=status,
            )
            result.lines.append(pl)

            result.total += 1
            if status == "changed":
                result.different += 1
            elif status == "inserted":
                result.different += 1
            elif status == "deleted":
                result.different += 1
            else:
                result.identical += 1

    @classmethod
    def _classify_line(cls, classes: set) -> str:
        classes_lower = {c.lower() for c in classes}
        if any(c in classes_lower for c in ("inserted", "orphanright")):
            return "inserted"
        if any(c in classes_lower for c in ("deleted", "orphanleft")):
            return "deleted"
        if any(c in classes_lower for c in
               ("changed", "textdiff", "diffchange", "sectiondiff")):
            return "changed"
        return "identical"

    @staticmethod
    def _parse_linenum(text: str) -> Optional[int]:
        try:
            return int(text.strip())
        except (ValueError, AttributeError):
            return None

    # ── Convenience summary ────────────────────────────────────────────────────

    @staticmethod
    def summary(result: BCParseResult) -> str:
        """Return a human-readable one-line summary of a parse result."""
        if result.parse_error:
            return f"[ERROR] {result.parse_error}"
        name = result.source_path.name
        if result.report_type == "folder":
            return (f"{name}: {result.total} files — "
                    f"{result.different} different, {result.orphans} orphans, "
                    f"{result.identical} identical")
        else:
            return (f"{name}: {result.total} lines — "
                    f"{result.different} changed/inserted/deleted, "
                    f"{result.identical} identical")


# ─── Styled Widgets ───────────────────────────────────────────────────────────

def styled_btn(parent, text, command, color=ACCENT, width=18, **kw):
    btn = tk.Button(
        parent, text=text, command=command,
        bg=color, fg="white", activebackground=color,
        activeforeground="white", relief="flat", cursor="hand2",
        font=FONT_HEAD, padx=12, pady=6, bd=0, width=width, **kw
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=_lighten(color)))
    btn.bind("<Leave>", lambda e: btn.config(bg=color))
    return btn


def _lighten(hex_color):
    """Very simple lighten."""
    h = hex_color.lstrip("#")
    rgb = [min(255, int(h[i:i+2], 16) + 30) for i in (0, 2, 4)]
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def folder_row(parent, label_text, var, row):
    tk.Label(parent, text=label_text, bg=SURFACE, fg=SUBTEXT,
             font=FONT_SMALL, anchor="w").grid(row=row, column=0, sticky="w", pady=(6,0))
    frame = tk.Frame(parent, bg=SURFACE)
    frame.grid(row=row+1, column=0, columnspan=2, sticky="ew", pady=(2,4))
    entry = tk.Entry(frame, textvariable=var, bg=SURFACE2, fg=TEXT,
                     insertbackground=TEXT, relief="flat", font=FONT_BODY,
                     bd=0, highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT)
    entry.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6)
    btn = tk.Button(frame, text="Browse", bg=SURFACE2, fg=ACCENT,
                    activebackground=BORDER, activeforeground=ACCENT,
                    relief="flat", font=FONT_SMALL, cursor="hand2", bd=0,
                    padx=10, pady=5,
                    command=lambda v=var: v.set(
                        filedialog.askdirectory(title=f"Select {label_text}") or v.get()))
    btn.pack(side="right", padx=(4, 0))
    return entry


# ─── Main Application ─────────────────────────────────────────────────────────

class BCCompareApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE}  v{VERSION}")
        self.configure(bg=BG)
        self.minsize(820, 640)
        self.geometry("900x720")
        self.resizable(True, True)

        # State
        self.left_folder   = tk.StringVar()
        self.right_folder  = tk.StringVar()
        self.output_folder = tk.StringVar()
        self.bc_path_var   = tk.StringVar(value="BCompare.exe")
        self.filter_idx    = tk.IntVar(value=0)
        self.custom_filter = tk.StringVar()
        self.display_idx   = tk.IntVar(value=0)
        self.do_pdf        = tk.BooleanVar(value=False)
        self.folder_mode   = tk.BooleanVar(value=True)   # True=folder, False=file

        # Markup state
        self.markup_input_folder  = tk.StringVar()
        self.markup_output_folder = tk.StringVar()
        self.markup_folder_mode   = tk.BooleanVar(value=True)

        # Running state
        self._running = False
        self._all_pages = []
        self._bc_proc = [None]   # holds active Popen so Stop can kill it
        self._parsed_results = []     # BCParseResult list from last parse run

        self._build_ui()

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        hdr = tk.Frame(self, bg=BG, pady=16)
        hdr.pack(fill="x", padx=24)
        tk.Label(hdr, text="◈ BC COMPARE", bg=BG, fg=ACCENT,
                 font=FONT_TITLE).pack(side="left")
        tk.Label(hdr, text=f"v{VERSION}", bg=BG, fg=SUBTEXT,
                 font=FONT_SMALL).pack(side="left", padx=(8, 0), pady=(6, 0))

        # ── Notebook tabs ──
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TNotebook",           background=BG,      borderwidth=0)
        style.configure("TNotebook.Tab",       background=SURFACE, foreground=SUBTEXT,
                        font=FONT_HEAD,        padding=[16, 8],    borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", SURFACE2)],
                  foreground=[("selected", ACCENT)])

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=24, pady=(0, 16))

        self._tab_config  = self._make_config_tab()
        self._tab_markup  = self._make_markup_tab()
        self._tab_run     = self._make_run_tab()

        self.nb.add(self._tab_config,  text="  ① Configure  ")
        self.nb.add(self._tab_markup,  text="  ② Markup  ")
        self.nb.add(self._tab_run,     text="  ③ Run  ")

    # ── Tab 1: Configure ──────────────────────────────────────────────────────

    def _make_config_tab(self):
        tab = tk.Frame(self.nb, bg=SURFACE)

        canvas = tk.Canvas(tab, bg=SURFACE, bd=0, highlightthickness=0)
        scroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=SURFACE)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def on_canvas_resize(e):
            canvas.itemconfig(win_id, width=e.width)
        inner.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", on_canvas_resize)

        pad = {"padx": 28}

        # ── Mode toggle ──
        mode_frame = tk.Frame(inner, bg=SURFACE2, bd=0)
        mode_frame.pack(fill="x", **pad, pady=(20, 4))
        tk.Label(mode_frame, text="Compare Mode", bg=SURFACE2, fg=SUBTEXT,
                 font=FONT_SMALL).pack(anchor="w", padx=12, pady=(8, 2))
        btn_row = tk.Frame(mode_frame, bg=SURFACE2)
        btn_row.pack(fill="x", padx=12, pady=(0, 10))

        self._btn_folder_mode = tk.Button(
            btn_row, text="📁  Folder Compare", font=FONT_HEAD,
            bg=ACCENT, fg="white", relief="flat", cursor="hand2",
            padx=14, pady=6, bd=0,
            command=lambda: self._set_mode(True))
        self._btn_folder_mode.pack(side="left", padx=(0, 6))

        self._btn_file_mode = tk.Button(
            btn_row, text="📄  File Compare", font=FONT_HEAD,
            bg=SURFACE, fg=SUBTEXT, relief="flat", cursor="hand2",
            padx=14, pady=6, bd=0,
            command=lambda: self._set_mode(False))
        self._btn_file_mode.pack(side="left")

        # ── Folders section ──
        sec = self._section(inner, "Folders & Paths")
        sec.columnconfigure(0, weight=1)

        folder_row(sec, "Original / Left Folder",   self.left_folder,   0)
        folder_row(sec, "Reviewing / Right Folder",  self.right_folder,  2)
        folder_row(sec, "Output Folder",             self.output_folder, 4)

        tk.Label(sec, text="BCompare Path (leave as 'BCompare.exe' if on PATH)",
                 bg=SURFACE2, fg=SUBTEXT, font=FONT_SMALL, anchor="w"
                 ).grid(row=6, column=0, sticky="w", pady=(6, 0))
        bc_entry = tk.Entry(sec, textvariable=self.bc_path_var, bg=SURFACE,
                            fg=TEXT, insertbackground=TEXT, relief="flat",
                            font=FONT_BODY, bd=0, highlightthickness=1,
                            highlightbackground=BORDER, highlightcolor=ACCENT)
        bc_entry.grid(row=7, column=0, sticky="ew", ipady=5, ipadx=6, pady=(2, 4))
        bc_browse = tk.Button(sec, text="Browse", bg=SURFACE, fg=ACCENT,
                              activebackground=BORDER, relief="flat",
                              font=FONT_SMALL, cursor="hand2", bd=0, padx=10, pady=5,
                              command=self._browse_bc)
        bc_browse.grid(row=7, column=1, padx=(4, 0))

        # ── Filter section ──
        fsec = self._section(inner, "File Filter")

        for i, (label, _) in enumerate(FILTER_OPTIONS):
            color = ACCENT if i == 0 else TEXT
            rb = tk.Radiobutton(
                fsec, text=label, variable=self.filter_idx, value=i,
                bg=SURFACE2, fg=TEXT, selectcolor=SURFACE,
                activebackground=SURFACE2, activeforeground=ACCENT,
                font=FONT_BODY, anchor="w", cursor="hand2",
                command=self._on_filter_change)
            rb.pack(fill="x", pady=1)

        self._custom_frame = tk.Frame(fsec, bg=SURFACE2)
        self._custom_frame.pack(fill="x", pady=(4, 0))
        tk.Label(self._custom_frame, text="Custom filter string:",
                 bg=SURFACE2, fg=SUBTEXT, font=FONT_SMALL).pack(anchor="w")
        self._custom_entry = tk.Entry(
            self._custom_frame, textvariable=self.custom_filter,
            bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
            font=FONT_MONO, bd=0, highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT)
        self._custom_entry.pack(fill="x", ipady=5, ipadx=6)
        self._custom_frame.pack_forget()   # hidden until selected

        # ── Display section ──
        dsec = self._section(inner, "Display Option")

        cols = tk.Frame(dsec, bg=SURFACE2)
        cols.pack(fill="x")
        for i, opt in enumerate(REPORT_OPTIONS):
            col = i % 3
            row_n = i // 3
            rb = tk.Radiobutton(
                cols, text=opt, variable=self.display_idx, value=i,
                bg=SURFACE2, fg=TEXT, selectcolor=SURFACE,
                activebackground=SURFACE2, activeforeground=ACCENT,
                font=FONT_BODY, anchor="w", cursor="hand2")
            rb.grid(row=row_n, column=col, sticky="w", padx=8, pady=1)

        # ── PDF toggle ──
        psec = self._section(inner, "Post-Processing")
        pdf_cb = tk.Checkbutton(
            psec, text="Convert output HTML reports → PDF (requires weasyprint)",
            variable=self.do_pdf, bg=SURFACE2, fg=TEXT,
            selectcolor=SURFACE, activebackground=SURFACE2,
            activeforeground=ACCENT, font=FONT_BODY, cursor="hand2")
        pdf_cb.pack(anchor="w")
        tk.Label(psec,
                 text="Install weasyprint:  pip install weasyprint",
                 bg=SURFACE2, fg=SUBTEXT, font=FONT_SMALL).pack(anchor="w", pady=(2, 0))

        # ── Next button ──
        btn_frame = tk.Frame(inner, bg=SURFACE)
        btn_frame.pack(fill="x", padx=28, pady=16)
        styled_btn(btn_frame, "Next  →", self._go_to_run, width=20).pack(side="right")

        return tab

    def _section(self, parent, title):
        outer = tk.Frame(parent, bg=SURFACE)
        outer.pack(fill="x", padx=28, pady=(12, 0))
        tk.Label(outer, text=title.upper(), bg=SURFACE, fg=ACCENT,
                 font=("Courier New", 9, "bold")).pack(anchor="w", pady=(0, 4))
        box = tk.Frame(outer, bg=SURFACE2, padx=16, pady=12)
        box.pack(fill="x")
        box.columnconfigure(0, weight=1)
        return box

    # ── Tab 2: Markup ─────────────────────────────────────────────────────────

    def _make_markup_tab(self):
        tab    = tk.Frame(self.nb, bg=SURFACE)
        canvas = tk.Canvas(tab, bg=SURFACE, bd=0, highlightthickness=0)
        scroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner  = tk.Frame(canvas, bg=SURFACE)
        wid    = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))

        # ── Mode toggle ──
        mf = tk.Frame(inner, bg=SURFACE2, bd=0)
        mf.pack(fill="x", padx=28, pady=(20, 4))
        tk.Label(mf, text="Markup Mode", bg=SURFACE2, fg=SUBTEXT,
                 font=FONT_SMALL).pack(anchor="w", padx=12, pady=(8, 2))
        br = tk.Frame(mf, bg=SURFACE2)
        br.pack(fill="x", padx=12, pady=(0, 10))
        self._markup_btn_folder = tk.Button(
            br, text="Folder Report", font=FONT_HEAD,
            bg=ACCENT, fg="white", relief="flat", cursor="hand2",
            padx=14, pady=6, bd=0, command=lambda: self._set_markup_mode(True))
        self._markup_btn_folder.pack(side="left", padx=(0, 6))
        self._markup_btn_file = tk.Button(
            br, text="File Folder", font=FONT_HEAD,
            bg=SURFACE, fg=SUBTEXT, relief="flat", cursor="hand2",
            padx=14, pady=6, bd=0, command=lambda: self._set_markup_mode(False))
        self._markup_btn_file.pack(side="left")

        # ── Folder pickers ──
        def _pick_row(parent, label_var_or_str, str_var, row_num, title="Select"):
            if isinstance(label_var_or_str, str):
                tk.Label(parent, text=label_var_or_str, bg=SURFACE2, fg=SUBTEXT,
                         font=FONT_SMALL, anchor="w").grid(
                             row=row_num, column=0, sticky="w", pady=(6, 0))
            else:
                tk.Label(parent, textvariable=label_var_or_str, bg=SURFACE2,
                         fg=SUBTEXT, font=FONT_SMALL, anchor="w").grid(
                             row=row_num, column=0, sticky="w", pady=(6, 0))
            f = tk.Frame(parent, bg=SURFACE2)
            f.grid(row=row_num + 1, column=0, columnspan=2, sticky="ew", pady=(2, 4))
            tk.Entry(f, textvariable=str_var, bg=SURFACE, fg=TEXT,
                     insertbackground=TEXT, relief="flat", font=FONT_BODY, bd=0,
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT).pack(side="left", fill="x",
                                                 expand=True, ipady=5, ipadx=6)
            tk.Button(f, text="Browse", bg=SURFACE, fg=ACCENT,
                      activebackground=BORDER, relief="flat", font=FONT_SMALL,
                      cursor="hand2", bd=0, padx=10, pady=5,
                      command=lambda v=str_var, t=title: v.set(
                          os.path.normpath(filedialog.askdirectory(title=t) or v.get()))
                      ).pack(side="right", padx=(4, 0))

        sec = self._section(inner, "Folders & Paths")
        sec.columnconfigure(0, weight=1)
        self._markup_input_label_var = tk.StringVar(
            value="Input Folder  (contains report.html from BC folder compare)")
        _pick_row(sec, self._markup_input_label_var,
                  self.markup_input_folder, 0, "Select Input Folder")
        _pick_row(sec, "Output Folder  (markup/ subfolder created here)",
                  self.markup_output_folder, 2, "Select Output Folder")

        # ── Run button ──
        bot = tk.Frame(inner, bg=SURFACE)
        bot.pack(fill="x", padx=28, pady=16)
        styled_btn(bot, "▶  Run Markup", self._run_markup,
                   color=SUCCESS, width=20).pack(side="right")
        return tab

    # ── Tab 3: Run ────────────────────────────────────────────────────────────

    def _make_run_tab(self):
        tab = tk.Frame(self.nb, bg=SURFACE)

        top = tk.Frame(tab, bg=SURFACE)
        top.pack(fill="x", padx=28, pady=(20, 8))

        self._run_status_label = tk.Label(
            top, text="Ready to run.", bg=SURFACE, fg=SUBTEXT, font=FONT_HEAD)
        self._run_status_label.pack(side="left")

        btn_row = tk.Frame(top, bg=SURFACE)
        btn_row.pack(side="right")
        self._run_btn = styled_btn(btn_row, "▶  Run", self._start_run,
                                   color=SUCCESS, width=14)
        self._run_btn.pack(side="left", padx=(0, 8))
        self._stop_btn = styled_btn(btn_row, "■  Stop", self._stop_run,
                                    color=DANGER, width=10)
        self._stop_btn.pack(side="left")
        self._stop_btn.config(state="disabled")
        self._parse_btn = styled_btn(btn_row, "⬡  Parse Reports", self._parse_reports,
                                     color=ACCENT2, width=18)
        self._parse_btn.pack(side="left", padx=(8, 0))
        self._parse_btn.config(state="disabled")

        # Progress bar
        style = ttk.Style()
        style.configure("Accent.Horizontal.TProgressbar",
                        troughcolor=SURFACE2, background=ACCENT,
                        lightcolor=ACCENT, darkcolor=ACCENT)
        self._progress = ttk.Progressbar(
            tab, style="Accent.Horizontal.TProgressbar",
            mode="indeterminate", length=400)
        self._progress.pack(fill="x", padx=28, pady=(0, 8))

        # Log
        log_frame = tk.Frame(tab, bg=SURFACE)
        log_frame.pack(fill="both", expand=True, padx=28, pady=(0, 8))
        tk.Label(log_frame, text="LOG", bg=SURFACE, fg=ACCENT,
                 font=("Courier New", 9, "bold")).pack(anchor="w", pady=(0, 4))
        self._log = scrolledtext.ScrolledText(
            log_frame, bg="#0a0d14", fg=TEXT, insertbackground=TEXT,
            font=FONT_MONO, relief="flat", bd=0, state="disabled",
            wrap="word", highlightthickness=1, highlightbackground=BORDER)
        self._log.pack(fill="both", expand=True)

        return tab

    # ── Logic ─────────────────────────────────────────────────────────────────

    def _set_mode(self, folder_mode: bool):
        self.folder_mode.set(folder_mode)
        if folder_mode:
            self._btn_folder_mode.config(bg=ACCENT, fg="white")
            self._btn_file_mode.config(bg=SURFACE, fg=SUBTEXT)
        else:
            self._btn_folder_mode.config(bg=SURFACE, fg=SUBTEXT)
            self._btn_file_mode.config(bg=ACCENT, fg="white")

    def _on_filter_change(self):
        if FILTER_OPTIONS[self.filter_idx.get()][1] == "__custom__":
            self._custom_frame.pack(fill="x", pady=(4, 0))
        else:
            self._custom_frame.pack_forget()

    def _browse_bc(self):
        path = filedialog.askopenfilename(
            title="Select BCompare.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
        if path:
            self.bc_path_var.set(path)

    def _go_to_run(self):
        if not self._validate():
            return
        self.nb.select(1)

    def _validate(self):
        if not self.left_folder.get():
            messagebox.showerror("Missing Input", "Please select the Left/Original folder.")
            return False
        if not self.right_folder.get():
            messagebox.showerror("Missing Input", "Please select the Right/Reviewing folder.")
            return False
        if not self.output_folder.get():
            messagebox.showerror("Missing Input", "Please select an Output folder.")
            return False
        return True

    def _log_msg(self, msg: str):
        self._log.config(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.config(state="disabled")
        self.update_idletasks()

    def _start_run(self):
        if not self._validate():
            self.nb.select(0)
            return
        self._running = True
        self._all_pages = []
        self._run_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")
        self._progress.start(12)
        self._run_status_label.config(text="Running…", fg=WARNING)

        thread = threading.Thread(target=self._run_compare, daemon=True)
        thread.start()

    def _stop_run(self):
        self._running = False
        if self._bc_proc[0] is not None:
            try:
                self._bc_proc[0].kill()
                self._log_msg("  ✗ BCompare process killed")
            except Exception:
                pass
        self._log_msg("\n⛔  Stopped by user.")
        self._finish_run(success=False)

    def _finish_run(self, success=True):
        self._progress.stop()
        self._running = False
        self._run_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        if success:
            self._run_status_label.config(text="✓ Complete", fg=SUCCESS)
            self._parse_btn.config(state="normal")
        else:
            self._run_status_label.config(text="Stopped / Error", fg=DANGER)

    def _run_compare(self):
        try:
            left   = Path(self.left_folder.get())
            right  = Path(self.right_folder.get())
            output = Path(self.output_folder.get())
            bc     = self.bc_path_var.get() or "BCompare.exe"

            # Resolve filter
            fkey = FILTER_OPTIONS[self.filter_idx.get()][1]
            if fkey == "__custom__":
                filters = self.custom_filter.get().strip() or "*.*"
            else:
                filters = fkey

            display = REPORT_OPTIONS[self.display_idx.get()]

            # Write script files
            cfg_dir = output / "configurations"
            cfg_dir.mkdir(parents=True, exist_ok=True)

            folder_script = cfg_dir / "folderScript.txt"
            folder_script.write_text(
                FOLDER_SCRIPT_TEMPLATE.format(filters=filters, display=display),
                encoding="utf-8")

            file_script = cfg_dir / "fileScript.txt"
            file_script.write_text(FILE_SCRIPT_TEMPLATE.format(display=display), encoding="utf-8")

            self._log_msg(f"Left  : {left}")
            self._log_msg(f"Right : {right}")
            self._log_msg(f"Output: {output}")
            self._log_msg(f"Filter: {filters}")
            self._log_msg(f"Display: {display}")
            self._log_msg("─" * 56)

            if self.folder_mode.get():
                # Single folder-compare report
                out_path = output / "report.html"
                self._log_msg("Running folder compare…")
                ok = bc_diff_cmd(left, right, bc, folder_script, out_path,
                                 log_fn=self._log_msg, proc_holder=self._bc_proc)
                if ok:
                    self._all_pages.append(out_path)
                    self._log_msg(f"✓ Report: {out_path.name}")
            else:
                # Per-file compares
                output.mkdir(parents=True, exist_ok=True)
                matched, deleted, created = get_files(left, right)
                self._log_msg(
                    f"{len(matched)} matched | {len(deleted)} deleted | {len(created)} created")
                self._log_msg("─" * 56)

                temp = cfg_dir / "temp.txt"
                temp.write_text("", encoding="utf-8")

                def run_one(lp, rp, label):
                    if not self._running:
                        return None
                    out = output / make_output_name(label)
                    self._log_msg(f"  {label} …")
                    bc_diff_cmd(lp, rp, bc, file_script, out, log_fn=self._log_msg, proc_holder=self._bc_proc)
                    return out

                if deleted:
                    self._log_msg(f"\nDeleted ({len(deleted)}):")
                    for p in deleted:
                        out = run_one(p, temp, p.name)
                        if out:
                            self._all_pages.append(out)

                if created:
                    self._log_msg(f"\nCreated ({len(created)}):")
                    for p in created:
                        out = run_one(temp, p, p.name)
                        if out:
                            self._all_pages.append(out)

                if matched:
                    self._log_msg(f"\nComparing ({len(matched)}):")
                    for f in matched:
                        out = run_one(f['left'], f['right'], f['filename'])
                        if out:
                            self._all_pages.append(out)

            if not self._running:
                return   # stopped by user — _finish_run already called

            self._log_msg("─" * 56)
            self._log_msg(f"✓ {len(self._all_pages)} report(s) generated in: {output}")

            # PDF conversion
            if self.do_pdf.get():
                self._log_msg("\nConverting to PDF…")
                pdf_out = output / "PDFs"
                convert_html_to_pdf(output, pdf_out, log_fn=self._log_msg)

            self.after(0, lambda: self._finish_run(success=True))

        except Exception as e:
            self._log_msg(f"\n✗ Exception: {e}")
            self.after(0, lambda: self._finish_run(success=False))





    def _set_markup_mode(self, folder_mode: bool):
        self.markup_folder_mode.set(folder_mode)
        if folder_mode:
            self._markup_btn_folder.config(bg=ACCENT, fg="white")
            self._markup_btn_file.config(bg=SURFACE, fg=SUBTEXT)
            self._markup_input_label_var.set(
                "Input Folder  (contains report.html from BC folder compare)")
        else:
            self._markup_btn_folder.config(bg=SURFACE, fg=SUBTEXT)
            self._markup_btn_file.config(bg=ACCENT, fg="white")
            self._markup_input_label_var.set(
                "Input Folder  (folder of per-file BC diff HTMLs)")

    def _run_markup(self):
        if not BS4_AVAILABLE:
            messagebox.showerror("Missing Dependency",
                "beautifulsoup4 not installed.\n\nRun:  pip install beautifulsoup4")
            return
        inp = self.markup_input_folder.get().strip()
        out = self.markup_output_folder.get().strip()
        if not inp:
            messagebox.showerror("Missing Input", "Please select an Input Folder.")
            return
        if not out:
            messagebox.showerror("Missing Output", "Please select an Output Folder.")
            return
        self.nb.select(2)
        self._running = True
        self._run_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")
        self._progress.start(12)
        self._run_status_label.config(text="Running markup…", fg=WARNING)
        threading.Thread(target=self._run_markup_worker,
                         args=(Path(inp), Path(out)), daemon=True).start()

    def _run_markup_worker(self, inp: Path, out: Path):
        try:
            self._log_msg(f"Input : {inp}")
            self._log_msg(f"Output: {out}")
            self._log_msg("─" * 56)
            if self.markup_folder_mode.get():
                self._log_msg("Mode: Folder  →  reading report.html")
                folder_markup(inp / "report.html", out, log_fn=self._log_msg)
            else:
                self._log_msg("Mode: File (per-file diff HTMLs)")
                file_markup(inp, out, log_fn=self._log_msg)
            if not self._running:
                return
            self._log_msg("─" * 56)
            self._log_msg("✓ Markup complete")
            self.after(0, lambda: self._finish_run(success=True))
        except Exception as e:
            self._log_msg(f"\n✗ Exception: {e}")
            self.after(0, lambda: self._finish_run(success=False))

    def _parse_reports(self):
        """Button handler — parse all generated HTML reports in a background thread."""
        if not BS4_AVAILABLE:
            messagebox.showerror(
                "Missing Dependency",
                "beautifulsoup4 is not installed.\n\nRun:  pip install beautifulsoup4")
            return
        output = self.output_folder.get()
        if not output:
            messagebox.showerror("No Output Folder", "No output folder is set.")
            return
        self._parse_btn.config(state="disabled")
        self._log_msg("\n" + "─" * 56)
        self._log_msg("Parsing HTML reports…")
        thread = threading.Thread(target=self._parse_reports_worker,
                                  args=(Path(output),), daemon=True)
        thread.start()

    def _parse_reports_worker(self, output_folder: Path):
        """
        Background worker — reads every .html in the output folder with
        BCReportParser and logs a summary of each.

        self._parsed_results is populated here so your downstream code
        can access the structured data:

            for result in self._parsed_results:
                if result.report_type == "folder":
                    for f in result.files:
                        print(f.filename, f.status)
                else:
                    for line in result.lines:
                        if line.status != "identical":
                            print(line.text_left, "→", line.text_right)
        """
        try:
            results = BCReportParser.parse_folder(output_folder)
            if not results:
                self._log_msg("  No HTML reports found in output folder.")
                self.after(0, lambda: self._parse_btn.config(state="normal"))
                return

            self._parsed_results = results   # store for downstream use

            for r in results:
                self._log_msg("  " + BCReportParser.summary(r))
                if r.parse_error:
                    continue
                # ── YOUR PROCESSING CODE GOES HERE ────────────────────────
                # Example: log every differing file in a folder report
                if r.report_type == "folder":
                    for f in r.files:
                        if f.status != "identical":
                            self._log_msg(f"    ↳ {f.status}: {f.filename}")
                # Example: log changed lines in a per-file report
                elif r.report_type == "file":
                    changed = [l for l in r.lines if l.status != "identical"]
                    if changed:
                        self._log_msg(f"    ↳ {len(changed)} changed lines")
                # ─────────────────────────────────────────────────────────

            self._log_msg(f"✓ Parsed {len(results)} report(s)")
            self.after(0, lambda: self._parse_btn.config(state="normal"))

        except Exception as e:
            self._log_msg(f"✗ Parse error: {e}")
            self.after(0, lambda: self._parse_btn.config(state="normal"))

# ─── Entry ────────────────────────────────────────────────────────────────────

def main():
    app = BCCompareApp()
    app.mainloop()


if __name__ == "__main__":
    main()
