"""
FHWA Highway Statistics Scraper
================================
Scrapes SF-4, FA-4, and VM-2 tables from the FHWA Highway Statistics
series for 2000-2018 and outputs clean CSVs for use in state-pair
friction variable construction.

Data sources:
    SF-4: State highway agency disbursements (thousands of dollars)
    FA-4: Federal-aid apportionments by state (thousands of dollars)
    VM-2: Vehicle miles traveled by functional system (millions of miles)

Coverage:
    2000-2001: https://www.fhwa.dot.gov/ohim/hs{YY}/xls/
    2002-2006: https://www.fhwa.dot.gov/policy/ohim/hs{YY}/xls/
    2007-2018: https://www.fhwa.dot.gov/policyinformation/statistics/{year}/xls/
    1997-1999: Not available in structured format; excluded from dataset.

Known data gaps:
    See README.md for the full list.

Usage:
    python fhwa_data_scraper.py

Output:
    fhwa_data/sf4_data.csv
    fhwa_data/fa4_data.csv
    fhwa_data/vm2_data.csv

Author: Ayden Young
Date: July 2026
"""


# ===========================================================================
# Imports
# ===========================================================================

import io
import re
import time
import traceback
from pathlib import Path
from typing import Literal

import pandas as pd
import requests

from utils import VALID_STATES  # type: ignore

# ===========================================================================
# Patch xlrd to handle formula evaluation errors in certain XLS files
# ===========================================================================

import xlrd.book
import xlrd.formula

_original_evaluate = xlrd.formula.evaluate_name_formula

def _safe_evaluate(bk, nobj, namex, blah=False, level=0):
    try:
        _original_evaluate(bk, nobj, namex, blah=blah, level=level)
    except AssertionError:
        pass

xlrd.formula.evaluate_name_formula = _safe_evaluate
xlrd.book.evaluate_name_formula = _safe_evaluate

# ===========================================================================
# Configuration
# ===========================================================================

OUT_DIR = Path("fhwa_data")
OUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
}

URL_PATTERNS = [
    {
        "years": range(2000, 2002),
        "template": "https://www.fhwa.dot.gov/ohim/hs{yy}/xls/{table}.xls",
        "ext": "xls"
    },
    {
        "years": range(2002, 2007),
        "template": "https://www.fhwa.dot.gov/policy/ohim/hs{yy}/xls/{table}.xls",
        "ext": "xls"
    },
    {
        "years": range(2007, 2019),
        "template": "https://www.fhwa.dot.gov/policyinformation/statistics/{year}/xls/{table}.{ext}",
        "ext": ["xls", "xlsx"]  # try both
    },
]

# ===========================================================================
# Core Utilities
# ===========================================================================

def clean_state_name(raw: str) -> str:
    """remove footnote markers: digits, slashes, asterisks, superscripts"""
    if pd.isna(raw):
        return ""
    cleaned = re.sub(r"[0-9/\*\†]+$", "", raw).strip()
    # standardize DC variants to a single form
    if cleaned.upper() in ("DIST. OF COLUMBIA", "DIST OF COLUMBIA", "DISTRICT OF COLUMBIA", "D.C."):
        return "District of Columbia"
    return cleaned

# ===========================================================================
# Table Parsers
# ===========================================================================

def read_table(xl, year: int, col_map: dict) -> pd.DataFrame | None:
    """
    Parse a single FHWA Excel table into a clean dataframe.

    Args:
        xl: File path or file-like object for the Excel file
        year: Data year (added as a col to the output)
        col_map: Dict mapping output column names to Excel column indices.
                    Use -1 for the last column. Example: {"total": 7}

    Returns:
        Dataframe with cols [state] + col_map.keys() + [year]
    """
            
    # read in raw data
    # try sheet A, then B, with xlrd and then openpyxl as a fallback
    sheet = None
    sheet_used = None
    for sheet_name in ['A', 'B']:
        engines: list[Literal["xlrd", "openpyxl"]] = ["xlrd", "openpyxl"]
        for engine in engines:
            try:
                xl.seek(0)
                candidate = pd.read_excel(xl, header=None,
                                        sheet_name=sheet_name,
                                        engine=engine)
                candidate = candidate.replace("", float("nan"))
                candidate = candidate.dropna(axis=1, how='all')
                candidate.columns = list(range(candidate.shape[1]))
                
                alabama_found = False
                for c in candidate.columns:
                    col_vals = candidate[c].fillna("").astype(str).tolist()
                    if any(v.upper().startswith("ALABAMA") for v in col_vals):
                        alabama_found = True
                        break

                if alabama_found:
                    sheet = candidate
                    sheet_used = sheet_name
                    break
            except Exception:
                continue
        if sheet is not None:
            break

    if sheet is None:
        print(f" WARNING: No sheet with state rows found for {year}")
        return None

    n_cols = sheet.shape[1]
    resolved_cols = {
        k: (v if v >= 0 else n_cols + v)
        for k, v in col_map.items()
    }

    state_col: int | None = None
    for col in range(n_cols):
        col_vals = sheet[col].fillna("").astype(str).tolist()
        if any(v.upper().startswith("ALABAMA") for v in col_vals):
            state_col = col
            break

    if state_col is None:
        print(f" WARNING: Could not find state column in {year}")
        return None

    # find the starting row for each table (data may be formatted slightly differently throughout the data years)
    col0 = sheet[state_col].fillna("").astype(str).tolist()

    try:
        starting_row = next(i for i, v in enumerate(col0) if v.upper().startswith("ALABAMA"))
        last_row = next(i for i, v in enumerate(col0) if v.upper().startswith("WYOMING"))
    except StopIteration:
        print(f" WARNING: Could not find state rows in {year}")
        return None

    # selecting just state names and total disbursements
    cols_to_select: list[int] = [state_col] + list(resolved_cols.values())
    sheet = sheet.iloc[(starting_row):(last_row + 1), cols_to_select]

    # renaming remaining columns
    sheet.columns = ["state"] + list(resolved_cols.keys())

    # stripping any whitespace on state names
    sheet['state'] = sheet['state'].str.strip().str.title().apply(clean_state_name)

    # adding source sheet
    sheet["_source_sheet"] = sheet_used

    # adding data year
    sheet['year'] = year

    # ensuring rows are for valid states (/districts)
    sheet = sheet[sheet['state'].str.lower().isin(VALID_STATES)].reset_index(drop=True)

    return sheet

def read_sf4(xl, year: int) -> pd.DataFrame | None:
    """Parse SF-4 disbursements table."""
    col_map = {"total_disbursements": 7}
    return read_table(xl, year, col_map)

def read_fa4(xl, year: int) -> pd.DataFrame | None:
    """Parse FA-4 apportionments table."""
    col_map = {"total_apportionment": -1}
    df = read_table(xl, year, col_map)

    if df is not None:
        # sheet B reports in dollars not thousands
        if "_source_sheet" in df.columns and \
        df["_source_sheet"].iloc[0] == "B":
            df["total_apportionment"] = df["total_apportionment"] / 1000
        df = df.drop(columns=["_source_sheet"])

    return df

def read_vm2(xl, year: int) -> pd.DataFrame | None:
    """Parse VM-2 vehicle miles traveled table."""
    col_map = {"rural_interstate": 1, "urban_interstate": 8, "total_vmt": -1}
    df = read_table(xl, year, col_map)

    if df is not None:
        df["interstate_vmt"] = df["rural_interstate"] + df["urban_interstate"]
        df = df.drop(columns=['rural_interstate', 'urban_interstate'])
        df = df[["state", "interstate_vmt", "total_vmt", "year"]]

    return df

# ===========================================================================
# Download Logic
# ===========================================================================

def get_urls(year: int, table: str) -> list:
    """Return list of URLs to try for a given year and table."""
    yy = str(year)[-2:]
    candidates = []
    for pattern in URL_PATTERNS:
        if year in pattern["years"]:
            if isinstance(pattern["ext"], list):
                # multiple extensions; generate one URL per extension
                for ext in pattern["ext"]:
                    candidates.append(pattern["template"].format(yy = yy, year = year, table = table, ext = ext))
            else:
                # single extension
                candidates.append(pattern["template"].format(yy = yy, year = year, table = table, ext = pattern["ext"]))

    return candidates



def download_table(year: int, table: str) -> pd.DataFrame | None:
    """
    Download and parse a single table for a given year.
    Tries each URL in order, returns None if all fail.
    """

    readers = {
        "sf4": read_sf4,
        "fa4": read_fa4,
        "vm2": read_vm2
    }

    for url in get_urls(year, table):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                print(f" {year} {table}: {url.split('/')[-1]}")
                content = io.BytesIO(r.content)
                df = readers[table](content, year)
                return df
        except Exception as e:
            print(f"  {year} {table}: failed ({type(e).__name__}: {e})")
            traceback.print_exc()
            continue

    return None



# ===========================================================================
# Main Pipeline
# ===========================================================================

def scrape_all(years = range(2000, 2019), tables = ["sf4", "fa4", "vm2"]) -> None:
    """Scrape all three tables for all years and write CSVs."""

    for table in tables:
        path = OUT_DIR / f"{table}_data.csv"
        if path.exists():
            path.unlink() # deletes the file
        
        print(f"\n=== Scraping {table.upper()} ===")

        for year in years:
            df = download_table(year, table)

            if df is None:
                print(f" {year} {table}: MISSING")
                continue

            print(f" {year}: {len(df)} rows")

            header = not path.exists()
            df.to_csv(path, mode = "a", header = header, index = False)

            time.sleep(0.5)



if __name__ == "__main__":
    scrape_all()