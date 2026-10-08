# fhwa-highway-stats

Scrapes state-level highway finance and travel data from the Federal
Highway Administration's Highway Statistics series (2000–2018) and
builds a SQLite database with a state-pair comparison view.

## Data

| Table | Measure | Units |
|-------|---------|-------|
| SF-4 | State highway agency disbursements | Thousands of dollars |
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

## Known data gaps

- SF-4 2008: not published in a structured format
- VM-2 2008, 2014: District of Columbia absent from the published table
- VM-2 2018: Ohio and Massachusetts absent from the published table
- FA-4 2012–2018: read from sheet B due to formula errors in sheet A,
  converted from dollars to thousands for consistency
- 1997–1999: not available in a structured format; excluded

## Implementation notes

FHWA's file locations and layouts changed across years. The scraper
handles three URL patterns, tries both .xls and .xlsx, locates data
rows by searching for state names rather than fixed positions, and
patches `xlrd` to tolerate formula errors in some older files.
