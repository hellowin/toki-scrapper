# TOKI School Statistics Scraper CLI

A Python CLI tool to scrape and query school track records from TOKI OSN Informatika statistics pages.

Data source starts from:
- https://osn.toki.id/statistik/provinsi


## What This Project Does

- Scrapes all provinces from the province statistics index.
- Discovers all linked schools from each province page.
- Scrapes each school detail page and stores records in SQLite.
- Excludes participant names from stored data.
- Provides a CLI to list school rankings in tabular format.


## Requirements

- Python 3.11+ (recommended)

## Installation

### 1) Clone and enter project

```bash
git clone git@github.com:hellowin/toki-scrapper.git
cd toki-scrapper
```

### 2) (Optional) Use ASDF

If you use ASDF, this project already includes `.tool-versions`.

```bash
asdf install
asdf local python <version-from-tool-versions>
```

You can skip this section and use any Python installation method you prefer.

### 3) Create virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 4) Install dependencies

```bash
pip install -r requirements.txt
```

## CLI Usage

The CLI entrypoint is `main.py`.

General pattern:

```bash
python main.py [--db PATH_TO_DB] <command> [command-options]
```

### Commands

#### scrap

Scrapes all data and stores it into SQLite.

```bash
python main.py scrap
```

By default, `scrap` clears existing data first.

Options:
- `--append` : do not clear existing data before scraping
- `--delay FLOAT` : delay between requests (seconds), default `0.1`
- `--timeout INT` : request timeout per HTTP call (seconds), default `30`

Examples:

```bash
# Fresh scrape (reset then scrape)
python main.py scrap

# Append mode
python main.py scrap --append

# More polite/slow scrape
python main.py scrap --delay 0.25 --timeout 60
```

#### list

Shows ranked school table in terminal (GitHub-style table format).

```bash
python main.py list
```

Options:
- `--limit INT` : number of rows to show, default `100`
- `--filter TEXT` : case-insensitive substring match on school name

Examples:

```bash
# Top 20 schools
python main.py list --limit 20

# Top 200 schools
python main.py list --limit 200

# Filter by school name substring (case-insensitive)
python main.py list --filter malang
python main.py list --filter Malang --limit 50
```

#### list-year

Shows ranked school tables grouped by year. Each year section uses the same medal columns and sorting logic as `list`.

```bash
python main.py list-year
```

Options:
- `--limit INT` : number of rows to show per year section, default `100`
- `--limit-year INT` : show only the most recent N years
- `--filter TEXT` : case-insensitive substring match on school name

Examples:

```bash
# Top 20 schools per year
python main.py list-year --limit 20

# Show only the latest 5 years
python main.py list-year --limit-year 5

# Show top 10 schools for each of the latest 3 years
python main.py list-year --limit 10 --limit-year 3

# Filter yearly ranking by school name substring
python main.py list-year --filter malang
python main.py list-year --filter Malang --limit 50
```

#### trend

Shows school medal achievement trend year-to-year, split into separate tables per medal category.

Input is TOKI school source ID.

```bash
python main.py trend 1
```

The command prints 4 sections:
- Gold (Emas)
- Silver (Perak)
- Bronze (Perunggu)
- Other (No Medal / Juara Harapan / Empty)

Each section includes year-by-year counts for:
- Internasional
- Regional
- Nasional
- Total

Examples:

```bash
# Trend for school ID 1
python main.py trend 1

# Trend using custom DB
python main.py --db data/osn.sqlite trend 185
```

### Global option

- `--db PATH` : path to SQLite database file (default: `toki_stats.db`)

Examples:

```bash
# Use default DB
python main.py scrap
python main.py list
python main.py list-year

# Use custom DB
python main.py --db data/osn.sqlite scrap
python main.py --db data/osn.sqlite list --limit 50
python main.py --db data/osn.sqlite list-year --limit 50
```

## Typical Workflow

1. Install dependencies.
2. Run a full scrape:

```bash
python main.py scrap
```

3. View ranked list:

```bash
python main.py list --limit 100
```

4. Re-run scrape periodically to refresh data.

## Output Table Columns

The ranking output mirrors medal groups used on TOKI school statistics:

- `#` = row rank in current output scope (current list, filter, or year section)
- `# National` (for `list`) = overall national rank from unfiltered all-time `list` ordering
- `# National` (for `list-year`) = national rank within that specific year (unfiltered for that year)
- `I-*` = Internasional
- `R-*` = Regional
- `N-*` = Nasional

Suffix meaning:
- `G` = Gold (Emas)
- `S` = Silver (Perak)
- `B` = Bronze (Perunggu)
- `O` = Other / non-medal entries

Example columns:
- `I-G`, `I-S`, `I-B`, `I-O`
- `R-G`, `R-S`, `R-B`, `R-O`
- `N-G`, `N-S`, `N-B`, `N-O`

## SQLite Notes

Default database file:
- `toki_stats.db`

Main tables:
- `schools`
- `records`

If you want to inspect manually:

```bash
sqlite3 toki_stats.db
.tables
SELECT COUNT(*) FROM schools;
SELECT COUNT(*) FROM records;
```

## Troubleshooting

- Database not found when running list:
  - Run `python main.py scrap` first, or set the correct `--db` path.

- Network errors during scraping:
  - Retry with larger timeout and delay:
    - `python main.py scrap --timeout 60 --delay 0.25`

- Slow scrape:
  - This is expected for full crawl across all schools.

## Legal and Ethics

- Respect source website terms and infrastructure.
- Use sensible delay values.
- Do not overload the target server.

## Quick Command Reference

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Scrape all schools
python main.py scrap

# Show top 100
python main.py list

# Show top 20
python main.py list --limit 20

# Show top 20 per year
python main.py list-year --limit 20

# Trend by school ID
python main.py trend 1

# Use custom DB
python main.py --db data/osn.sqlite scrap
python main.py --db data/osn.sqlite list --limit 50
python main.py --db data/osn.sqlite trend 185
```
