"""
BC Compare GUI - Tkinter frontend for Beyond Compare diff reporting.
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

# ─── Constants ────────────────────────────────────────────────────────────────

APP_TITLE = "BC Compare"
VERSION   = "1.0"

FILTER_OPTIONS = [
    ("*.*  —  No Filters (All files)", "*.*"),
    ("Exclude build artifacts (.exe .ilk .a .lib .exp .o .vcproj debug bin .pdb .tlog .bsc)",
     "-*.exe;-*.ilk;-*.a;-*.lib;-*.exp;-*.o;-*vcproj;-res\\;-debug\\;-bin\\;-.debug\\;-*.pdb;-*.tlog;-*bsc;"),
    ("Exclude build artifacts (no .pdb/.tlog/.bsc)",
     "-*.exe;-*.ilk;-*.a;-*.lib;-*.exp;-*.o;-*vcproj;-res\\;-debug\\;-bin\\;-.debug\\;"),
    ("Custom filter…", "__custom__"),
]

FOLDER_SCRIPT_TEMPLATE = """\
criteria crc
log verbose "configurations\\log.txt"
filter "{filters}"
load %1 %2
expand all
select all
folder-report layout:side-by-side &
    options:display-all,include-file-links,column-size &
    output-to:%3 &
    output-options:html-color
"""

# Colours & fonts
BG       = "#0f1117"
SURFACE  = "#1a1d27"
SURFACE2 = "#22263a"
ACCENT   = "#4f8ef7"
ACCENT2  = "#7c3aed"
SUCCESS  = "#22c55e"
WARNING  = "#f59e0b"
DANGER   = "#ef4444"
TEXT     = "#e8eaf0"
SUBTEXT  = "#8b93a7"
BORDER   = "#2e3347"

FONT_TITLE = ("Courier New", 20, "bold")
FONT_HEAD  = ("Courier New", 11, "bold")
FONT_BODY  = ("Courier New", 10)
FONT_SMALL = ("Courier New", 9)
FONT_MONO  = ("Courier New", 9)

# ─── BC Helpers ───────────────────────────────────────────────────────────────

def resource_path(relative_path):
    base = getattr(sys, '_MEIPASS', Path(__file__).parent)
    return Path(base) / relative_path


def bc_diff_cmd(left: Path, right: Path, bc_path: str, script_path: Path,
                output_path: Path, log_fn=None, proc_holder: list = None) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "<!DOCTYPE html><html><body><p>Generating diff…</p></body></html>",
        encoding="utf-8")
    command = [bc_path, f"@{script_path}", str(left), str(right), str(output_path)]
    try:
        proc = subprocess.Popen(command, shell=False,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        if proc_holder is not None:
            proc_holder[0] = proc
        returncode = proc.wait()
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


# ─── Markup Helpers ───────────────────────────────────────────────────────────

def _get_info(element):
    """Return (tag_name, href) from the first <a href> inside element."""
    for tag in element.find_all("a", href=True):
        return tag.get_text(), tag.get("href")
    return None, None


def _new_cell(soup, row, i: int, text: str):
    """Prepend a <th> or <td class='AlignCenter Wrap'> to row."""
    cell          = soup.new_tag("th" if i == 0 else "td")
    cell["class"] = "AlignCenter Wrap"
    cell.string   = text
    row.insert(0, cell)


def annotate_file_diff(html_filepath, markup_folder_path, output_file_name,
                       log_fn=None) -> int:
    """
    Read a BC per-file diff HTML, insert a change-count column, write result to
    markup_folder_path/markup/reports/<output_file_name>_diff.html.
    Returns number of changes found, or 0 if none / error.
    """
    if not BS4_AVAILABLE:
        if log_fn:
            log_fn("  ✗ beautifulsoup4 not installed")
        return 0
    try:
        content = Path(html_filepath).read_text(encoding="utf-8", errors="ignore")
        soup    = BeautifulSoup(content, "html.parser")
        rows    = soup.find_all("tr")

        count = 1
        for i, row in enumerate(rows):
            diff_cell = row.find("td", class_="AlignCenter Wrap")
            if diff_cell and diff_cell.get_text(strip=True) in ("-+", "<>"):
                _new_cell(soup, row, i, str(count))
                count += 1
            else:
                _new_cell(soup, row, i, "")

        if count == 1:
            return 0

        out = (Path(markup_folder_path) / "markup" / "reports"
               / f"{output_file_name}_diff.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(str(soup), encoding="utf-8")

        if log_fn:
            log_fn(f"  ✓ {output_file_name}: {count - 1} change(s)")
        return count - 1

    except Exception as e:
        if log_fn:
            log_fn(f"  ✗ Error in {output_file_name}: {e}")
        return 0


def folder_markup(filepath, output_path, log_fn=None):
    """
    Read BC folder-level report.html, find DirItemDiff rows,
    follow each file link, call annotate_file_diff on it.
    """
    report = Path(filepath) / "report.html"
    bc_dir = report.parent
    try:
        content   = report.read_text(encoding="utf-8", errors="ignore")
        soup      = BeautifulSoup(content, "html.parser")
        diff_rows = soup.find_all("tr", class_="DirItemDiff")
        if not diff_rows:
            if log_fn:
                log_fn("  No DirItemDiff rows found in report.html")
            return
        if log_fn:
            log_fn(f"  {len(diff_rows)} changed file(s) found")
        for row in diff_rows:
            filename, href = _get_info(row)
            if not filename or not href:
                continue
            num_changes = annotate_file_diff(
                bc_dir / href, output_path, filename, log_fn=log_fn)
            if log_fn and num_changes == 0:
                log_fn(f"  — {filename}: no changes")
    except Exception as e:
        if log_fn:
            log_fn(f"  ✗ folder_markup error: {e}")


def file_markup(folder_path, output_filepath, log_fn=None):
    """Annotate every HTML file in folder_path."""
    try:
        files = [f for f in Path(folder_path).iterdir()
                 if f.is_file() and f.suffix.lower() == ".html"]
        if not files:
            if log_fn:
                log_fn("  No HTML files found in folder.")
            return
        if log_fn:
            log_fn(f"  Processing {len(files)} file(s)…")
        for f in files:
            annotate_file_diff(f, output_filepath, f.stem, log_fn=log_fn)
    except Exception as e:
        if log_fn:
            log_fn(f"  ✗ file_markup error: {e}")


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
    h   = hex_color.lstrip("#")
    rgb = [min(255, int(h[i:i+2], 16) + 30) for i in (0, 2, 4)]
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def folder_row(parent, label_text, var, row):
    tk.Label(parent, text=label_text, bg=SURFACE, fg=SUBTEXT,
             font=FONT_SMALL, anchor="w").grid(row=row, column=0, sticky="w", pady=(6, 0))
    frame = tk.Frame(parent, bg=SURFACE)
    frame.grid(row=row+1, column=0, columnspan=2, sticky="ew", pady=(2, 4))
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

        # Generate state
        self.left_folder   = tk.StringVar()
        self.right_folder  = tk.StringVar()
        self.output_folder = tk.StringVar()
        self.bc_path_var   = tk.StringVar(value="BCompare.exe")
        self.filter_idx    = tk.IntVar(value=0)
        self.custom_filter = tk.StringVar()
        self.do_pdf        = tk.BooleanVar(value=False)

        # Markup state
        self.markup_input_folder  = tk.StringVar()
        self.markup_output_folder = tk.StringVar()
        self.markup_folder_mode   = tk.BooleanVar(value=True)

        # Running state
        self._running  = False
        self._bc_proc  = [None]

        self._build_ui()

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG, pady=16)
        hdr.pack(fill="x", padx=24)
        tk.Label(hdr, text="◈ BC COMPARE", bg=BG, fg=ACCENT,
                 font=FONT_TITLE).pack(side="left")
        tk.Label(hdr, text=f"v{VERSION}", bg=BG, fg=SUBTEXT,
                 font=FONT_SMALL).pack(side="left", padx=(8, 0), pady=(6, 0))

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TNotebook",     background=BG,      borderwidth=0)
        style.configure("TNotebook.Tab", background=SURFACE, foreground=SUBTEXT,
                        font=FONT_HEAD,  padding=[16, 8],    borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", SURFACE2)],
                  foreground=[("selected", ACCENT)])

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=24, pady=(0, 16))

        self._tab_config = self._make_config_tab()
        self._tab_markup = self._make_markup_tab()
        self._tab_run    = self._make_run_tab()

        self.nb.add(self._tab_config, text="  ① Configure  ")
        self.nb.add(self._tab_markup, text="  ② Markup  ")
        self.nb.add(self._tab_run,    text="  ③ Run  ")

    # ── Tab 1: Configure ──────────────────────────────────────────────────────

    def _make_config_tab(self):
        tab    = tk.Frame(self.nb, bg=SURFACE)
        canvas = tk.Canvas(tab, bg=SURFACE, bd=0, highlightthickness=0)
        scroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner  = tk.Frame(canvas, bg=SURFACE)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))

        # Folders
        sec = self._section(inner, "Folders & Paths")
        sec.columnconfigure(0, weight=1)
        folder_row(sec, "Original / Left Folder",  self.left_folder,   0)
        folder_row(sec, "Reviewing / Right Folder", self.right_folder,  2)
        folder_row(sec, "Output Folder",            self.output_folder, 4)
        tk.Label(sec, text="BCompare Path (leave as 'BCompare.exe' if on PATH)",
                 bg=SURFACE2, fg=SUBTEXT, font=FONT_SMALL, anchor="w"
                 ).grid(row=6, column=0, sticky="w", pady=(6, 0))
        bc_entry = tk.Entry(sec, textvariable=self.bc_path_var, bg=SURFACE,
                            fg=TEXT, insertbackground=TEXT, relief="flat",
                            font=FONT_BODY, bd=0, highlightthickness=1,
                            highlightbackground=BORDER, highlightcolor=ACCENT)
        bc_entry.grid(row=7, column=0, sticky="ew", ipady=5, ipadx=6, pady=(2, 4))
        tk.Button(sec, text="Browse", bg=SURFACE, fg=ACCENT,
                  activebackground=BORDER, relief="flat", font=FONT_SMALL,
                  cursor="hand2", bd=0, padx=10, pady=5,
                  command=self._browse_bc).grid(row=7, column=1, padx=(4, 0))

        # Filter
        fsec = self._section(inner, "File Filter")
        for i, (label, _) in enumerate(FILTER_OPTIONS):
            tk.Radiobutton(
                fsec, text=label, variable=self.filter_idx, value=i,
                bg=SURFACE2, fg=TEXT, selectcolor=SURFACE,
                activebackground=SURFACE2, activeforeground=ACCENT,
                font=FONT_BODY, anchor="w", cursor="hand2",
                command=self._on_filter_change).pack(fill="x", pady=1)
        self._custom_frame = tk.Frame(fsec, bg=SURFACE2)
        self._custom_frame.pack(fill="x", pady=(4, 0))
        tk.Label(self._custom_frame, text="Custom filter string:",
                 bg=SURFACE2, fg=SUBTEXT, font=FONT_SMALL).pack(anchor="w")
        tk.Entry(self._custom_frame, textvariable=self.custom_filter,
                 bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
                 font=FONT_MONO, bd=0, highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=ACCENT
                 ).pack(fill="x", ipady=5, ipadx=6)
        self._custom_frame.pack_forget()

        # PDF
        psec = self._section(inner, "Post-Processing")
        tk.Checkbutton(
            psec, text="Convert output HTML reports → PDF (requires weasyprint)",
            variable=self.do_pdf, bg=SURFACE2, fg=TEXT,
            selectcolor=SURFACE, activebackground=SURFACE2,
            activeforeground=ACCENT, font=FONT_BODY, cursor="hand2"
        ).pack(anchor="w")
        tk.Label(psec, text="Install weasyprint:  pip install weasyprint",
                 bg=SURFACE2, fg=SUBTEXT, font=FONT_SMALL).pack(anchor="w", pady=(2, 0))

        # Next
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
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(wid, width=e.width))

        # Mode toggle
        mf = tk.Frame(inner, bg=SURFACE2, bd=0)
        mf.pack(fill="x", padx=28, pady=(20, 4))
        tk.Label(mf, text="Markup Mode", bg=SURFACE2, fg=SUBTEXT,
                 font=FONT_SMALL).pack(anchor="w", padx=12, pady=(8, 2))
        br = tk.Frame(mf, bg=SURFACE2)
        br.pack(fill="x", padx=12, pady=(0, 10))
        self._markup_btn_folder = tk.Button(
            br, text="📁  Folder Report", font=FONT_HEAD,
            bg=ACCENT, fg="white", relief="flat", cursor="hand2",
            padx=14, pady=6, bd=0,
            command=lambda: self._set_markup_mode(True))
        self._markup_btn_folder.pack(side="left", padx=(0, 6))
        self._markup_btn_file = tk.Button(
            br, text="📄  File Folder", font=FONT_HEAD,
            bg=SURFACE, fg=SUBTEXT, relief="flat", cursor="hand2",
            padx=14, pady=6, bd=0,
            command=lambda: self._set_markup_mode(False))
        self._markup_btn_file.pack(side="left")

        # Folder pickers
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
            f.grid(row=row_num+1, column=0, columnspan=2, sticky="ew", pady=(2, 4))
            tk.Entry(f, textvariable=str_var, bg=SURFACE, fg=TEXT,
                     insertbackground=TEXT, relief="flat", font=FONT_BODY,
                     bd=0, highlightthickness=1, highlightbackground=BORDER,
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

        self._run_btn = styled_btn(
            btn_row, "▶  Generate Report", self._start_run,
            color=SUCCESS, width=20)
        self._run_btn.pack(side="left", padx=(0, 8))

        self._markup_run_btn = styled_btn(
            btn_row, "▶  Run Markup", self._run_markup,
            color=ACCENT2, width=16)
        self._markup_run_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = styled_btn(
            btn_row, "■  Stop", self._stop_run,
            color=DANGER, width=10)
        self._stop_btn.pack(side="left")
        self._stop_btn.config(state="disabled")

        # Progress
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
        self.nb.select(2)

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

    def _start_run_ui(self, label: str):
        self._running = True
        self._run_btn.config(state="disabled")
        self._markup_run_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")
        self._progress.start(12)
        self._run_status_label.config(text=label, fg=WARNING)

    def _start_run(self):
        if not self._validate():
            self.nb.select(0)
            return
        self.nb.select(2)
        self._start_run_ui("Running…")
        threading.Thread(target=self._run_compare, daemon=True).start()

    def _run_markup(self):
        if not BS4_AVAILABLE:
            messagebox.showerror(
                "Missing Dependency",
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
        self._start_run_ui("Running markup…")
        threading.Thread(target=self._run_markup_worker,
                         args=(Path(inp), Path(out)), daemon=True).start()

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
        self._markup_run_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        if success:
            self._run_status_label.config(text="✓ Complete", fg=SUCCESS)
        else:
            self._run_status_label.config(text="Stopped / Error", fg=DANGER)

    # ── Generate Report worker ─────────────────────────────────────────────────

    def _run_compare(self):
        try:
            left   = Path(self.left_folder.get())
            right  = Path(self.right_folder.get())
            output = Path(self.output_folder.get())
            bc     = self.bc_path_var.get() or "BCompare.exe"

            fkey    = FILTER_OPTIONS[self.filter_idx.get()][1]
            filters = self.custom_filter.get().strip() or "*.*" \
                if fkey == "__custom__" else fkey

            cfg_dir = output / "configurations"
            cfg_dir.mkdir(parents=True, exist_ok=True)

            script_path = cfg_dir / "folderScript.txt"
            script_path.write_text(
                FOLDER_SCRIPT_TEMPLATE.format(filters=filters),
                encoding="utf-8")

            self._log_msg(f"Left   : {left}")
            self._log_msg(f"Right  : {right}")
            self._log_msg(f"Output : {output}")
            self._log_msg(f"Filter : {filters}")
            self._log_msg("─" * 56)

            out_path = output / "report.html"
            self._log_msg("Running folder compare…")
            ok = bc_diff_cmd(left, right, bc, script_path, out_path,
                             log_fn=self._log_msg, proc_holder=self._bc_proc)
            if ok:
                self._log_msg(f"✓ Report: {out_path.name}")

            if not self._running:
                return

            self._log_msg("─" * 56)
            self._log_msg(f"✓ Report generated in: {output}")

            if self.do_pdf.get():
                self._log_msg("\nConverting to PDF…")
                convert_html_to_pdf(output, output / "PDFs", log_fn=self._log_msg)

            self.after(0, lambda: self._finish_run(success=True))

        except Exception as e:
            self._log_msg(f"\n✗ Exception: {e}")
            self.after(0, lambda: self._finish_run(success=False))

    # ── Markup worker ──────────────────────────────────────────────────────────

    def _run_markup_worker(self, inp: Path, out: Path):
        try:
            self._log_msg(f"Input : {inp}")
            self._log_msg(f"Output: {out}")
            self._log_msg("─" * 56)
            if self.markup_folder_mode.get():
                self._log_msg("Mode: Folder  →  reading report.html")
                folder_markup(inp, out, log_fn=self._log_msg)
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


# ─── Entry ────────────────────────────────────────────────────────────────────

def main():
    app = BCCompareApp()
    app.mainloop()


if __name__ == "__main__":
    main()
