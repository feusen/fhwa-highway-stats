# fhwa-highway-stats

Scrapes state-level highway finance and travel data from the Federal
Highway Administration's Highway Statistics series (2000–2018) and
builds a SQLite database with a state-pair comparison view.

## Data

| Table | Measure | Units |
|-------|---------|-------|
| SF-4 | State highway agency disbursements, total and excluding bond retirement | Thousands of dollars |
| FA-4 | Federal-aid apportionments | Thousands of dollars |
| VM-2 | Interstate and total vehicle miles traveled | Millions of miles |

## Usage

Requires Python 3.10+.

```
pip install -r requirements.txt
python fhwa_data_scraper.py   # writes fhwa_data/*_data.csv
python fhwa_database.py       # builds fhwa_data/fhwa_highway_stats.db
```

## Output

The database contains a `states` table (FIPS crosswalk), one table per
FHWA source, and a `state_pair_gaps` view with absolute differences in
spending, apportionments, and interstate VMT share for every state
pair and year. `fhwa_database.py` also exports the view to
`fhwa_data/friction_vars.csv`.

Spending appears twice: `spending_gap` uses total disbursements, and
`spending_gap_ex_bonds` excludes bond retirement. Debt refinancing can
double a state's total disbursements in a single year (e.g. New Jersey
2005, Utah 2004), so the ex-bonds measure better reflects actual
highway spending.

## Known data gaps

- SF-4 2008: not published in a structured format
- SF-4 (all years): District of Columbia absent from the published table
- FA-4: when sheet A can't be read, sheet B is used and converted from
  dollars to thousands for consistency
- FA-4 year labels are the edition year, not the fiscal year: edition N
  usually covers FY N+1, but the 2015 and 2016 editions both cover FY 2016,
  so those two years are identical. 2013 and 2014 (FY 2014 and FY 2015)
  are also identical because FY 2015 was apportioned at FY 2014 levels
- 1997–1999: not available in a structured format; excluded

## Implementation notes

FHWA's file locations and layouts changed across years. The scraper
handles three URL patterns, tries both .xls and .xlsx, locates data
rows by searching for state names rather than fixed positions, and
patches `xlrd` to tolerate formula errors in some older files.
