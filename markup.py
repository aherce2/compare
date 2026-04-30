#!/usr/bin/env python3

import argparse
import re
import sys
from pathlib import Path

import openpyxl
from bs4 import BeautifulSoup

MARKUP_ID_RE = re.compile(r'^markupID_(\d+)$')

# ============================================================
# 1. READ EXCEL
# ============================================================

def read_excel(path, sheet_name=None):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active

    merged_map = {}
    for rng in ws.merged_cells.ranges:
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                merged_map[(r, c)] = (rng.min_row, rng.min_col)

    def get_val(r, c):
        if (r, c) in merged_map:
            ar, ac = merged_map[(r, c)]
            return ws.cell(ar, ac).value
        return ws.cell(r, c).value

    records = {}
    for r in range(4, ws.max_row + 1):
        id_v = get_val(r, 1)
        if id_v is None:
            continue

        try:
            id_v = int(id_v)
        except:
            continue

        records[id_v] = {
            "s": str(get_val(r, 2) or ""),
            "notes": str(get_val(r, 3) or "")
        }

    return records


# ============================================================
# 2. HTML HELPERS
# ============================================================

def find_table(soup):
    return soup.find("table", class_="fc")


def get_markup_id(tr):
    for td in tr.find_all("td", id=True):
        m = MARKUP_ID_RE.match(td["id"])
        if m:
            return int(m.group(1))
    return None


# ============================================================
# 3. GROUP ROWSPAN (UNCHANGED LOGIC)
# ============================================================

def compute_groups(records, ids):
    ids = sorted(i for i in ids if i in records)
    out = {}

    i = 0
    while i < len(ids):
        base = ids[i]
        rec = records[base]

        span = 1
        j = i + 1
        while j < len(ids) and ids[j] == ids[j-1] + 1 and records[ids[j]] == rec:
            span += 1
            j += 1

        for k in range(span):
            out[ids[i + k]] = {
                "s": rec["s"],
                "notes": rec["notes"],
                "rowspan": span if k == 0 else 1,
                "render": k == 0
            }

        i = j

    return out


# ============================================================
# 4. COLUMN INSERTION (FIXED CORE)
# ============================================================

def insert_at_visual_column(tr, new_cell, target_col):
    """
    Insert cell based on visual column index, respecting colspan.
    """
    col_pos = 0

    for cell in tr.find_all(["td", "th"], recursive=False):
        span = int(cell.get("colspan", 1))

        if col_pos + span > target_col:
            cell.insert_before(new_cell)
            return

        col_pos += span

    tr.append(new_cell)


# ============================================================
# 5. MAIN INJECTION LOGIC
# ============================================================

INSERT_COL = 2  # <-- CHANGE THIS if needed


def inject(soup, table, group_map):
    trs = table.find_all("tr")

    first_row = True

    for tr in trs:
        mid = get_markup_id(tr)

        # HEADER ROW
        if mid is None and first_row:
            th1 = soup.new_tag("th")
            th1.string = "S"

            th2 = soup.new_tag("th")
            th2.string = "Notes"

            insert_at_visual_column(tr, th1, INSERT_COL)
            insert_at_visual_column(tr, th2, INSERT_COL + 1)

            first_row = False
            continue

        # NON-DATA ROW
        if mid is None:
            insert_at_visual_column(tr, soup.new_tag("td"), INSERT_COL)
            insert_at_visual_column(tr, soup.new_tag("td"), INSERT_COL + 1)
            continue

        # DATA ROW NO RECORD
        if mid not in group_map:
            insert_at_visual_column(tr, soup.new_tag("td"), INSERT_COL)
            insert_at_visual_column(tr, soup.new_tag("td"), INSERT_COL + 1)
            continue

        g = group_map[mid]

        # ROWSPAN SKIP
        if not g["render"]:
            continue

        # CREATE CELLS
        s_td = soup.new_tag("td")
        s_td.string = g["s"]

        n_td = soup.new_tag("td")
        n_td.string = g["notes"]

        if g["rowspan"] > 1:
            s_td["rowspan"] = str(g["rowspan"])
            n_td["rowspan"] = str(g["rowspan"])

        insert_at_visual_column(tr, s_td, INSERT_COL)
        insert_at_visual_column(tr, n_td, INSERT_COL + 1)


# ============================================================
# 6. MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("excel")
    parser.add_argument("html")
    parser.add_argument("--sheet", default=None)
    args = parser.parse_args()

    excel = Path(args.excel)
    html = Path(args.html)

    records = read_excel(excel, args.sheet)

    soup = BeautifulSoup(html.read_text(encoding="utf-8"), "lxml")

    table = find_table(soup)
    if not table:
        sys.exit("No BC table found")

    ids = [get_markup_id(tr) for tr in table.find_all("tr")]
    ids = [i for i in ids if i is not None]

    group_map = compute_groups(records, ids)

    inject(soup, table, group_map)

    out = html.with_stem(html.stem + "_annotated")
    out.write_text(str(soup), encoding="utf-8")

    print(f"Saved -> {out}")


if __name__ == "__main__":
    main()
