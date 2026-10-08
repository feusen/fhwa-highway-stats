"""
FHWA Highway Statistics Database Builder
=========================================
Reads cleaned CSV outputs from fhwa_data_scraper.py, merges in state
FIPS codes, and builds a normalized SQLite database with state-level
highway finance and VMT data for 2000-2018.

A state_pair_gaps view pre-computes absolute fiscal and VMT asymmetry
between every state pair for use as friction variables in bridge
maintenance analysis.

Inputs:
    fhwa_data/sf4_data.csv
    fhwa_data/fa4_data.csv
    fhwa_data/vm2_data.csv

Output:
    fhwa_data/fhwa_highway_stats.db

Known gaps:
    See README.md for the full list.

Usage:
    python fhwa_database.py

Author: Ayden Young
Date: July 2026
"""

# ===========================================================================
# Imports
# ===========================================================================

import sqlite3
from pathlib import Path

import pandas as pd

from utils import FIPS_XWALK  # type: ignore

# ===========================================================================
# Configuration
# ===========================================================================

OUT_DIR = Path("fhwa_data")
OUT_DIR.mkdir(exist_ok=True)

SF4_CSV = OUT_DIR / "sf4_data.csv"
FA4_CSV = OUT_DIR / "fa4_data.csv"
VM2_CSV = OUT_DIR / "vm2_data.csv"
DB_PATH = OUT_DIR / "fhwa_highway_stats.db"

# ===========================================================================
# Table reads and fips add
# ===========================================================================

def load_data():
    """Load CSVs and merge in FIPS codes."""
    sf4 = pd.read_csv(SF4_CSV)
    fa4 = pd.read_csv(FA4_CSV)
    vm2 = pd.read_csv(VM2_CSV)

    sf4["fips"] = sf4["state"].map(FIPS_XWALK)
    fa4["fips"] = fa4["state"].map(FIPS_XWALK)
    vm2["fips"] = vm2["state"].map(FIPS_XWALK)

    for name, df in [("SF4", sf4), ("FA4", fa4), ("VM2", vm2)]:
        missing = df[df["fips"].isna()]["state"].tolist()
        if missing:
            print(f"WARNING: {name} states with no FIPS match: {missing}")
        else:
            print(f" {name}: all states matched")

    return sf4, fa4, vm2

# ===========================================================================
# Database build
# ===========================================================================

def build_database(sf4, fa4, vm2):
    """Build SQLite database from cleaned dataframes."""

    with sqlite3.connect(DB_PATH) as conn:

        # drop and recreate tables for clean rebuild
        conn.execute("DROP TABLE IF EXISTS states")
        conn.execute("""
            CREATE TABLE states (
                     fips TEXT PRIMARY KEY,
                     state_name TEXT NOT NULL
                     )
        """)

        # insert crosswalk rows
        rows = [(fips, state) for state, fips in FIPS_XWALK.items()]
        conn.executemany("INSERT INTO states VALUES (?, ?)", rows)

        print(f" states table: {len(rows)} rows")

        # adding the three data tables
        sf4.to_sql("sf4_disbursements", conn, if_exists = "replace", index = False)
        fa4.to_sql("fa4_apportionments", conn, if_exists = "replace", index = False)
        vm2.to_sql("vm2_vmt", conn, if_exists = "replace", index = False)

        print(f"  sf4_disbursements: {len(sf4)} rows")
        print(f"  fa4_apportionments: {len(fa4)} rows")
        print(f"  vm2_vmt: {len(vm2)} rows")

        # state pair gaps view
        conn.execute("DROP VIEW IF EXISTS state_pair_gaps")
        conn.execute("""
            CREATE VIEW state_pair_gaps AS
            SELECT 
                -- pair identifier matching border_id format in R
                a.fips || '_' || b.fips as border_id,
                a.year as year,
                
                -- state identifiers
                a.fips as fips_a,
                b.fips as fips_b,
                     
                -- spending gap (SF4)
                ABS(a.total_disbursements - b.total_disbursements) as spending_gap,
                     
                -- apportionment gap (FA4)
                ABS(fa_a.total_apportionment - fa_b.total_apportionment) as apportionment_gap,
                     
                -- interstate VMT share gap (VM2)
                ABS(
                    CAST(vm_a.interstate_vmt AS REAL) / vm_a.total_vmt -
                    CAST(vm_b.interstate_vmt AS REAL) / vm_b.total_vmt
                    ) as interstate_share_gap
                     
            FROM sf4_disbursements a
            JOIN sf4_disbursements b
                ON a.year = b.year
                AND a.fips < b.fips
            
            -- FA4 for both states
            JOIN fa4_apportionments fa_a
                ON a.fips = fa_a.fips
                AND a.year = fa_a.year
            JOIN fa4_apportionments fa_b
                ON b.fips = fa_b.fips
                AND b.year = fa_b.year
            
            -- VM2 for both states
            JOIN vm2_vmt vm_a
                ON a.fips = vm_a.fips
                AND a.year = vm_a.year
            JOIN vm2_vmt vm_b
                ON b.fips = vm_b.fips
                AND b.year = vm_b.year
        """)

        print(" state_pair_gaps view: created")

    print(f"\nDatabase written to {DB_PATH}")

if __name__ == "__main__":
    sf4, fa4, vm2 = load_data()
    build_database(sf4, fa4, vm2)

    with sqlite3.connect(DB_PATH) as conn:
        gaps = pd.read_sql("""
            SELECT border_id, year,
                    spending_gap,
                    apportionment_gap,
                           interstate_share_gap
            FROM state_pair_gaps
            ORDER BY border_id, year
                           """, conn)
        
        out = Path("fhwa_data/friction_vars.csv")
        gaps.to_csv(out, index = False)
        print(f"Exported {len(gaps)} rows to {out}")