#!/usr/bin/env python3
"""CLI scraper for TOKI OSN Informatika school statistics."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from tabulate import tabulate

BASE_URL = "https://osn.toki.id"
PROVINCE_INDEX_URL = f"{BASE_URL}/statistik/provinsi"
DEFAULT_DB_PATH = Path("toki_stats.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

RANKING_HEADERS = [
    "#",
    "# National",
    "School ID",
    "Sekolah",
    "I-G",
    "I-S",
    "I-B",
    "I-O",
    "R-G",
    "R-S",
    "R-B",
    "R-O",
    "N-G",
    "N-S",
    "N-B",
    "N-O",
]


@dataclass
class SchoolRecord:
    source_school_id: int
    school_name: str
    level: str
    competition: str
    year: int | None
    rank: int | None
    score: float | None
    medal: str | None
    medal_category: str


def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split()).strip()


def parse_int(value: str) -> int | None:
    value = clean_text(value)
    if not value or value == "-":
        return None
    match = re.search(r"-?\d+", value)
    if not match:
        return None
    return int(match.group(0))


def parse_float(value: str) -> float | None:
    value = clean_text(value).replace(",", ".")
    if not value or value == "-":
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    return float(match.group(0))


def parse_year(competition_name: str) -> int | None:
    match = re.search(r"(19|20)\d{2}", competition_name)
    if not match:
        return None
    return int(match.group(0))


def normalize_level(level: str) -> str:
    normalized = clean_text(level).lower()
    if "internasional" in normalized:
        return "internasional"
    if "regional" in normalized:
        return "regional"
    if "nasional" in normalized:
        return "nasional"
    return normalized


def medal_category(medal: str | None) -> str:
    label = clean_text(medal or "").lower()
    if label in {"emas", "gold"}:
        return "gold"
    if label in {"perak", "silver"}:
        return "silver"
    if label in {"perunggu", "bronze"}:
        return "bronze"
    return "other"


class TokiScraper:
    def __init__(self, delay_seconds: float = 0.1, timeout_seconds: int = 30) -> None:
        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def get_soup(self, url: str) -> BeautifulSoup:
        response = self.session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        time.sleep(self.delay_seconds)
        return BeautifulSoup(response.text, "html.parser")

    def fetch_province_links(self) -> list[str]:
        soup = self.get_soup(PROVINCE_INDEX_URL)
        links: set[str] = set()
        for anchor in soup.select('a[href^="/statistik/provinsi/"]'):
            href = anchor.get("href", "")
            if href.count("/") == 3:
                links.add(urljoin(BASE_URL, href))
        return sorted(links)

    def fetch_school_refs_from_province(self, province_url: str) -> dict[int, str]:
        soup = self.get_soup(province_url)
        schools: dict[int, str] = {}
        for anchor in soup.select('a[href^="/statistik/sekolah/"]'):
            href = anchor.get("href", "")
            match = re.fullmatch(r"/statistik/sekolah/(\d+)", href)
            if not match:
                continue
            school_id = int(match.group(1))
            school_name = clean_text(anchor.get_text(" ", strip=True))
            if school_name:
                schools[school_id] = school_name
        return schools

    def fetch_school_records(self, school_id: int, fallback_name: str = "") -> tuple[str, list[SchoolRecord]]:
        url = f"{BASE_URL}/statistik/sekolah/{school_id}"
        soup = self.get_soup(url)

        header = soup.select_one("div.subcontent h3")
        school_name = clean_text(header.get_text(" ", strip=True)) if isinstance(header, Tag) else fallback_name
        if not school_name:
            school_name = fallback_name or f"School {school_id}"

        records: list[SchoolRecord] = []

        for level_header in soup.select("div.subcontent h4"):
            level = normalize_level(level_header.get_text(" ", strip=True))
            table = level_header.find_next_sibling("table")
            if not isinstance(table, Tag):
                continue

            for row in table.select("tbody tr"):
                cols = row.find_all("td")
                if len(cols) < 4:
                    continue

                competition = clean_text(cols[0].get_text(" ", strip=True))
                rank = parse_int(cols[1].get_text(" ", strip=True))
                year = parse_year(competition)

                score: float | None = None
                medal_text: str | None = None

                if level in {"internasional", "regional"}:
                    medal_text = clean_text(cols[3].get_text(" ", strip=True)) or None
                elif level == "nasional":
                    score = parse_float(cols[-2].get_text(" ", strip=True))
                    medal_text = clean_text(cols[-1].get_text(" ", strip=True)) or None
                else:
                    # Unknown section, still attempt a generic parse.
                    if len(cols) >= 2:
                        score = parse_float(cols[-2].get_text(" ", strip=True))
                    medal_text = clean_text(cols[-1].get_text(" ", strip=True)) or None

                records.append(
                    SchoolRecord(
                        source_school_id=school_id,
                        school_name=school_name,
                        level=level,
                        competition=competition,
                        year=year,
                        rank=rank,
                        score=score,
                        medal=medal_text,
                        medal_category=medal_category(medal_text),
                    )
                )

        return school_name, records


def connect_db(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_school_id INTEGER NOT NULL UNIQUE,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL,
            level TEXT NOT NULL,
            competition TEXT NOT NULL,
            year INTEGER,
            rank INTEGER,
            score REAL,
            medal TEXT,
            medal_category TEXT NOT NULL,
            FOREIGN KEY (school_id) REFERENCES schools(id) ON DELETE CASCADE,
            UNIQUE (school_id, level, competition, rank, score, medal)
        );

        CREATE INDEX IF NOT EXISTS idx_records_school ON records(school_id);
        CREATE INDEX IF NOT EXISTS idx_records_level ON records(level);
        CREATE INDEX IF NOT EXISTS idx_records_year ON records(year);
        """
    )
    connection.commit()


def reset_data(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM records")
    connection.execute("DELETE FROM schools")
    connection.commit()


def upsert_school(connection: sqlite3.Connection, source_school_id: int, name: str) -> int:
    connection.execute(
        """
        INSERT INTO schools (source_school_id, name)
        VALUES (?, ?)
        ON CONFLICT(source_school_id)
        DO UPDATE SET name = excluded.name
        """,
        (source_school_id, name),
    )
    row = connection.execute(
        "SELECT id FROM schools WHERE source_school_id = ?", (source_school_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Failed to upsert school {source_school_id}")
    return int(row[0])


def insert_records(connection: sqlite3.Connection, school_db_id: int, records: Iterable[SchoolRecord]) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO records (
            school_id, level, competition, year, rank, score, medal, medal_category
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                school_db_id,
                record.level,
                record.competition,
                record.year,
                record.rank,
                record.score,
                record.medal,
                record.medal_category,
            )
            for record in records
        ],
    )


def build_national_ranks(connection: sqlite3.Connection) -> dict[int, int]:
    query = """
    SELECT
        s.source_school_id,
        s.name,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS i_gold,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS i_silver,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS i_bronze,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS i_other,

        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS r_gold,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS r_silver,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS r_bronze,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS r_other,

        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS n_gold,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS n_silver,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS n_bronze,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS n_other
    FROM schools s
    LEFT JOIN records r ON r.school_id = s.id
    GROUP BY s.id, s.name
    ORDER BY
        i_gold DESC, i_silver DESC, i_bronze DESC, i_other DESC,
        r_gold DESC, r_silver DESC, r_bronze DESC, r_other DESC,
        n_gold DESC, n_silver DESC, n_bronze DESC, n_other DESC,
        s.name ASC
    """

    rows = connection.execute(query).fetchall()
    national_ranks: dict[int, int] = {}
    for idx, row in enumerate(rows, start=1):
        national_ranks[int(row[0])] = idx
    return national_ranks


def build_year_national_ranks(connection: sqlite3.Connection) -> dict[int, dict[int, int]]:
    query = """
    SELECT
        r.year,
        s.source_school_id,
        s.name,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS i_gold,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS i_silver,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS i_bronze,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS i_other,

        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS r_gold,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS r_silver,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS r_bronze,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS r_other,

        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS n_gold,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS n_silver,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS n_bronze,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS n_other
    FROM schools s
    JOIN records r ON r.school_id = s.id
    WHERE r.year IS NOT NULL
    GROUP BY r.year, s.id, s.name
    ORDER BY
        r.year DESC,
        i_gold DESC, i_silver DESC, i_bronze DESC, i_other DESC,
        r_gold DESC, r_silver DESC, r_bronze DESC, r_other DESC,
        n_gold DESC, n_silver DESC, n_bronze DESC, n_other DESC,
        s.name ASC
    """

    rows = connection.execute(query).fetchall()
    year_ranks: dict[int, dict[int, int]] = {}
    current_year: int | None = None
    current_rank = 0

    for row in rows:
        year = int(row[0])
        school_id = int(row[1])
        if year != current_year:
            current_year = year
            current_rank = 0
            year_ranks[year] = {}
        current_rank += 1
        year_ranks[year][school_id] = current_rank

    return year_ranks


def build_ranking_rows(
    rows: list[sqlite3.Row | tuple[object, ...]],
    national_ranks: dict[int, int] | None = None,
) -> list[list[object]]:
    table_rows: list[list[object]] = []
    for idx, row in enumerate(rows, start=1):
        school_id = int(row[0])
        national_rank = national_ranks.get(school_id, "-") if national_ranks is not None else "-"
        values = [idx, national_rank, school_id, row[1], *row[2:]]
        display_values = ["-" if value == 0 else value for value in values]
        table_rows.append(display_values)
    return table_rows


def command_scrap(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    scraper = TokiScraper(delay_seconds=args.delay, timeout_seconds=args.timeout)

    connection = connect_db(db_path)
    init_db(connection)

    if not args.append:
        reset_data(connection)

    print("Fetching province links...")
    province_links = scraper.fetch_province_links()
    print(f"Found {len(province_links)} provinces")

    schools: dict[int, str] = {}
    for idx, province_url in enumerate(province_links, start=1):
        refs = scraper.fetch_school_refs_from_province(province_url)
        schools.update(refs)
        print(f"[{idx}/{len(province_links)}] {province_url} -> {len(refs)} school refs")

    school_ids = sorted(schools.keys())
    print(f"Unique schools discovered: {len(school_ids)}")

    inserted_records = 0
    for idx, school_id in enumerate(school_ids, start=1):
        fallback_name = schools.get(school_id, "")
        try:
            school_name, school_records = scraper.fetch_school_records(school_id, fallback_name=fallback_name)
        except requests.RequestException as error:
            print(f"[{idx}/{len(school_ids)}] skip school {school_id}: {error}", file=sys.stderr)
            continue

        school_db_id = upsert_school(connection, school_id, school_name)
        before = connection.total_changes
        insert_records(connection, school_db_id, school_records)
        inserted_now = connection.total_changes - before
        inserted_records += inserted_now

        if idx % 20 == 0 or idx == len(school_ids):
            print(
                f"[{idx}/{len(school_ids)}] {school_name} ({school_id}) -> "
                f"{len(school_records)} rows scraped, {inserted_now} inserted"
            )

    connection.commit()

    total_schools = connection.execute("SELECT COUNT(*) FROM schools").fetchone()[0]
    total_records = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    print(f"Done. Schools: {total_schools}, records: {total_records}, newly inserted rows: {inserted_records}")
    return 0


def command_list(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}. Run 'scrap' first.", file=sys.stderr)
        return 1

    connection = connect_db(db_path)
    init_db(connection)
    national_ranks = build_national_ranks(connection)

    name_filter = clean_text(args.filter)
    where_clause = ""
    params: list[object] = []
    if name_filter:
        where_clause = "WHERE LOWER(s.name) LIKE ?"
        params.append(f"%{name_filter.lower()}%")

    query = """
    SELECT
        s.source_school_id,
        s.name,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS i_gold,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS i_silver,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS i_bronze,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS i_other,

        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS r_gold,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS r_silver,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS r_bronze,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS r_other,

        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS n_gold,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS n_silver,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS n_bronze,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS n_other
    FROM schools s
    LEFT JOIN records r ON r.school_id = s.id
    """ + where_clause + """
    GROUP BY s.id, s.name
    ORDER BY
        i_gold DESC, i_silver DESC, i_bronze DESC, i_other DESC,
        r_gold DESC, r_silver DESC, r_bronze DESC, r_other DESC,
        n_gold DESC, n_silver DESC, n_bronze DESC, n_other DESC,
        s.name ASC
    LIMIT ?
    """

    params.append(args.limit)
    rows = connection.execute(query, tuple(params)).fetchall()
    if not rows:
        if name_filter:
            print(f"No data found for filter: {name_filter}")
        else:
            print("No data. Run 'scrap' first.")
        return 0

    table_rows = build_ranking_rows(rows, national_ranks=national_ranks)
    print(tabulate(table_rows, headers=RANKING_HEADERS, tablefmt="github"))
    return 0


def command_list_year(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}. Run 'scrap' first.", file=sys.stderr)
        return 1

    connection = connect_db(db_path)
    init_db(connection)
    year_national_ranks = build_year_national_ranks(connection)

    name_filter = clean_text(args.filter)
    if args.limit_year is not None and args.limit_year < 1:
        print("--limit-year must be >= 1", file=sys.stderr)
        return 1

    where_conditions = ["r.year IS NOT NULL"]
    params: list[object] = []
    if name_filter:
        where_conditions.append("LOWER(s.name) LIKE ?")
        params.append(f"%{name_filter.lower()}%")

    where_clause = "WHERE " + " AND ".join(where_conditions)

    query = """
    SELECT
        r.year,
        s.source_school_id,
        s.name,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS i_gold,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS i_silver,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS i_bronze,
        SUM(CASE WHEN r.level = 'internasional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS i_other,

        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS r_gold,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS r_silver,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS r_bronze,
        SUM(CASE WHEN r.level = 'regional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS r_other,

        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'gold' THEN 1 ELSE 0 END) AS n_gold,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'silver' THEN 1 ELSE 0 END) AS n_silver,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'bronze' THEN 1 ELSE 0 END) AS n_bronze,
        SUM(CASE WHEN r.level = 'nasional' AND r.medal_category = 'other' THEN 1 ELSE 0 END) AS n_other
    FROM schools s
    JOIN records r ON r.school_id = s.id
    """ + where_clause + """
    GROUP BY r.year, s.id, s.name
    ORDER BY
        r.year DESC,
        i_gold DESC, i_silver DESC, i_bronze DESC, i_other DESC,
        r_gold DESC, r_silver DESC, r_bronze DESC, r_other DESC,
        n_gold DESC, n_silver DESC, n_bronze DESC, n_other DESC,
        s.name ASC
    """

    rows = connection.execute(query, tuple(params)).fetchall()
    if not rows:
        if name_filter:
            print(f"No data found for filter: {name_filter}")
        else:
            print("No yearly data. Run 'scrap' first.")
        return 0

    grouped_rows: dict[int, list[tuple[object, ...]]] = {}
    for row in rows:
        year = int(row[0])
        grouped_rows.setdefault(year, []).append(row[1:])

    years = sorted(grouped_rows.keys(), reverse=True)
    if args.limit_year is not None:
        years = years[: args.limit_year]

    for idx, year in enumerate(years, start=1):
        if idx > 1:
            print()
        print(f"Year {year}")
        limited_rows = grouped_rows[year][: args.limit]
        table_rows = build_ranking_rows(limited_rows, national_ranks=year_national_ranks.get(year, {}))
        print(tabulate(table_rows, headers=RANKING_HEADERS, tablefmt="github"))

    return 0


def command_trend(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}. Run 'scrap' first.", file=sys.stderr)
        return 1

    connection = connect_db(db_path)
    init_db(connection)

    school_row = connection.execute(
        "SELECT id, name FROM schools WHERE source_school_id = ?",
        (args.school_id,),
    ).fetchone()
    if school_row is None:
        print(f"School with source ID {args.school_id} was not found in database.", file=sys.stderr)
        print("Run 'scrap' first, or check the school ID.", file=sys.stderr)
        return 1

    school_db_id = int(school_row[0])
    school_name = str(school_row[1])

    categories = [
        ("gold", "Gold (Emas)"),
        ("silver", "Silver (Perak)"),
        ("bronze", "Bronze (Perunggu)"),
        ("other", "Other (No Medal / Juara Harapan / Empty)"),
    ]

    print(f"Trend for school ID {args.school_id}: {school_name}")

    query = """
    SELECT
        r.year,
        SUM(CASE WHEN r.level = 'internasional' THEN 1 ELSE 0 END) AS internasional,
        SUM(CASE WHEN r.level = 'regional' THEN 1 ELSE 0 END) AS regional,
        SUM(CASE WHEN r.level = 'nasional' THEN 1 ELSE 0 END) AS nasional
    FROM records r
    WHERE r.school_id = ?
      AND r.medal_category = ?
      AND r.year IS NOT NULL
    GROUP BY r.year
    ORDER BY r.year ASC
    """

    for medal_key, medal_title in categories:
        rows = connection.execute(query, (school_db_id, medal_key)).fetchall()
        print()
        print(medal_title)

        if not rows:
            print("No records")
            continue

        table_rows = []
        for year, internasional, regional, nasional in rows:
            total = (internasional or 0) + (regional or 0) + (nasional or 0)
            table_rows.append(
                [
                    year,
                    "-" if internasional == 0 else internasional,
                    "-" if regional == 0 else regional,
                    "-" if nasional == 0 else nasional,
                    "-" if total == 0 else total,
                ]
            )

        print(
            tabulate(
                table_rows,
                headers=["Year", "Internasional", "Regional", "Nasional", "Total"],
                tablefmt="github",
            )
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toki-scrapper",
        description="Scrape and list TOKI OSN Informatika school track records.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    scrap_parser = subparsers.add_parser("scrap", help="Scrape all school data into SQLite")
    scrap_parser.add_argument("--append", action="store_true", help="Append without clearing existing data")
    scrap_parser.add_argument("--delay", type=float, default=0.1, help="Delay between requests in seconds")
    scrap_parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout per request in seconds")
    scrap_parser.set_defaults(func=command_scrap)

    list_parser = subparsers.add_parser("list", help="List school ranking table")
    list_parser.add_argument("--limit", type=int, default=100, help="Rows to display")
    list_parser.add_argument("--filter", default="", help="Case-insensitive school name substring filter")
    list_parser.set_defaults(func=command_list)

    list_year_parser = subparsers.add_parser("list-year", help="List school ranking table grouped by year")
    list_year_parser.add_argument("--limit", type=int, default=100, help="Rows to display per year")
    list_year_parser.add_argument("--limit-year", type=int, default=None, help="Most recent years to display")
    list_year_parser.add_argument("--filter", default="", help="Case-insensitive school name substring filter")
    list_year_parser.set_defaults(func=command_list_year)

    trend_parser = subparsers.add_parser("trend", help="Show year-by-year medal trend for a school ID")
    trend_parser.add_argument("school_id", type=int, help="School source ID from TOKI URL")
    trend_parser.set_defaults(func=command_trend)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
