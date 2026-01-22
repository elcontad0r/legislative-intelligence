#!/usr/bin/env python3
"""
Extract Historical Public Laws from USC Source Credits.

This script extracts ALL Public Law citations from USC section source_credit fields
and creates "skeleton" PublicLaw nodes in Neo4j, along with ENACTS/AMENDS edges.

Source credits look like:
    (Pub. L. 109-58, title IX, sect. 952, Aug. 8, 2005, 119 Stat. 885;
     Pub. L. 115-248, sect. 2(b)(1), Sept. 28, 2018, 132 Stat. 3155; ...)

For each unique PL citation, we:
1. Parse congress and law_number
2. Extract the associated date (Month Day, Year format)
3. Extract the Statutes at Large citation if present
4. Create a skeleton PublicLaw node if it doesn't exist
5. Create ENACTS (first PL) or AMENDS (subsequent PLs) edges to the USC section

Usage:
    python scripts/extract_historical_pls.py
    python scripts/extract_historical_pls.py --dry-run   # Preview without writing
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from src.graph.neo4j_store import Neo4jStore
from src.parsers.citations import CitationParser

console = Console()

# =============================================================================
# Month name mapping for date parsing
# =============================================================================

MONTH_MAP = {
    "jan": 1, "jan.": 1, "january": 1,
    "feb": 2, "feb.": 2, "february": 2,
    "mar": 3, "mar.": 3, "march": 3,
    "apr": 4, "apr.": 4, "april": 4,
    "may": 5,
    "jun": 6, "jun.": 6, "june": 6,
    "jul": 7, "jul.": 7, "july": 7,
    "aug": 8, "aug.": 8, "august": 8,
    "sep": 9, "sep.": 9, "sept": 9, "sept.": 9, "september": 9,
    "oct": 10, "oct.": 10, "october": 10,
    "nov": 11, "nov.": 11, "november": 11,
    "dec": 12, "dec.": 12, "december": 12,
}


@dataclass
class ExtractedPL:
    """A Public Law extracted from a source credit."""
    congress: int
    law_number: int
    canonical_id: str  # "Pub. L. {congress}-{law_number}"
    enacted_date: date | None = None
    statutes_at_large: str | None = None  # "{volume} Stat. {page}"
    source_section_ids: set[str] = field(default_factory=set)  # USC sections this PL appears in
    position_in_source: dict[str, int] = field(default_factory=dict)  # section_id -> position (0=first)


# =============================================================================
# Enhanced parsing for source credits
# =============================================================================

# Pattern to match a PL citation followed by optional date and Stat citation
# Example: "Pub. L. 109-58, title IX, sect. 952, Aug. 8, 2005, 119 Stat. 885"
PL_WITH_CONTEXT = re.compile(
    r"Pub(?:lic)?\.?\s*L(?:aw)?\.?\s*(?:No\.?\s*)?(\d{1,3})\s*[-\u2013\u2014]\s*(\d{1,4})"  # PL citation
    r"[^;]*?"  # Non-greedy match of anything until date or semicolon
    r"(?:,\s*([A-Za-z]+\.?\s+\d{1,2},\s+\d{4}))?"  # Optional date: "Aug. 8, 2005"
    r"[^;]*?"  # More stuff
    r"(?:,\s*(\d{1,3})\s*Stat\.?\s*(\d{1,5}))?"  # Optional Stat citation: "119 Stat. 885"
    ,
    re.IGNORECASE
)

# Simpler pattern to find dates near a PL citation
DATE_PATTERN = re.compile(
    r"([A-Za-z]+\.?)\s+(\d{1,2}),\s+(\d{4})"
)

# Pattern for Statutes at Large
STAT_PATTERN = re.compile(
    r"(\d{1,3})\s*Stat\.?\s*(\d{1,5})"
)


def parse_date(date_str: str) -> date | None:
    """Parse a date string like 'Aug. 8, 2005' into a date object."""
    if not date_str:
        return None

    match = DATE_PATTERN.match(date_str.strip())
    if not match:
        return None

    month_str = match.group(1).lower().rstrip(".")
    day = int(match.group(2))
    year = int(match.group(3))

    month = MONTH_MAP.get(month_str) or MONTH_MAP.get(month_str + ".")
    if not month:
        return None

    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_pls_from_source_credit(source_credit: str, section_id: str) -> list[ExtractedPL]:
    """
    Extract all Public Law citations from a source credit string.

    Returns a list of ExtractedPL objects with associated dates and Stat citations.
    """
    parser = CitationParser()
    results: list[ExtractedPL] = []

    # First, get all PL citations with their positions
    pl_citations = parser.parse_public_laws(source_credit)

    for position, pl_cite in enumerate(pl_citations):
        congress = pl_cite.congress
        law_number = pl_cite.law_number

        if congress is None or law_number is None:
            continue

        canonical_id = f"Pub. L. {congress}-{law_number}"

        # Now try to find the date and Stat citation near this PL
        # Look for the text segment starting from this PL until the next semicolon or PL
        start_pos = pl_cite.start

        # Find the next semicolon or end of string
        semicolon_pos = source_credit.find(";", start_pos)
        if semicolon_pos == -1:
            semicolon_pos = len(source_credit)

        segment = source_credit[start_pos:semicolon_pos]

        # Extract date from this segment
        date_match = DATE_PATTERN.search(segment)
        enacted_date = None
        if date_match:
            date_str = date_match.group(0)
            enacted_date = parse_date(date_str)

        # Extract Stat citation from this segment
        stat_match = STAT_PATTERN.search(segment)
        statutes_at_large = None
        if stat_match:
            volume = stat_match.group(1)
            page = stat_match.group(2)
            statutes_at_large = f"{volume} Stat. {page}"

        extracted = ExtractedPL(
            congress=congress,
            law_number=law_number,
            canonical_id=canonical_id,
            enacted_date=enacted_date,
            statutes_at_large=statutes_at_large,
        )
        extracted.source_section_ids.add(section_id)
        extracted.position_in_source[section_id] = position

        results.append(extracted)

    return results


def merge_extracted_pls(all_extracted: list[ExtractedPL]) -> dict[str, ExtractedPL]:
    """
    Merge extracted PLs by canonical_id, combining source sections and keeping
    the best available metadata (date, stat citation).
    """
    merged: dict[str, ExtractedPL] = {}

    for pl in all_extracted:
        if pl.canonical_id in merged:
            existing = merged[pl.canonical_id]
            # Merge source sections
            existing.source_section_ids.update(pl.source_section_ids)
            existing.position_in_source.update(pl.position_in_source)
            # Keep date if we don't have one
            if existing.enacted_date is None and pl.enacted_date is not None:
                existing.enacted_date = pl.enacted_date
            # Keep stat citation if we don't have one
            if existing.statutes_at_large is None and pl.statutes_at_large is not None:
                existing.statutes_at_large = pl.statutes_at_large
        else:
            merged[pl.canonical_id] = pl

    return merged


# =============================================================================
# Main extraction logic
# =============================================================================

def extract_historical_pls(dry_run: bool = False):
    """
    Extract all historical Public Laws from USC source credits and create
    skeleton nodes + edges in Neo4j.
    """
    store = Neo4jStore()
    store.connect()

    console.print("[bold blue]Extracting Historical Public Laws from USC Source Credits[/bold blue]\n")

    # Step 1: Get all existing PublicLaw nodes
    console.print("[dim]Checking existing PublicLaw nodes...[/dim]")
    with store.session() as session:
        result = session.run("MATCH (pl:PublicLaw) RETURN pl.id as id")
        existing_pls = {r["id"] for r in result}

    console.print(f"Found [cyan]{len(existing_pls)}[/cyan] existing PublicLaw nodes\n")

    # Step 2: Get all USC sections with source credits
    console.print("[dim]Fetching USC sections with source credits...[/dim]")
    with store.session() as session:
        result = session.run("""
            MATCH (usc:USCSection)
            WHERE usc.source_credit IS NOT NULL AND usc.source_credit <> ''
            RETURN usc.id as id, usc.source_credit as source_credit
        """)
        sections = list(result)

    console.print(f"Found [cyan]{len(sections)}[/cyan] USC sections with source credits\n")

    if not sections:
        console.print("[yellow]No sections with source credits found. Exiting.[/yellow]")
        store.close()
        return

    # Step 3: Extract all PL citations from source credits
    console.print("[bold]Extracting Public Law citations...[/bold]")
    all_extracted: list[ExtractedPL] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing source credits...", total=len(sections))

        for record in sections:
            section_id = record["id"]
            source_credit = record["source_credit"]

            extracted = extract_pls_from_source_credit(source_credit, section_id)
            all_extracted.extend(extracted)

            progress.advance(task)

    console.print(f"Extracted [cyan]{len(all_extracted)}[/cyan] total PL citations\n")

    # Step 4: Merge by canonical_id
    merged_pls = merge_extracted_pls(all_extracted)
    console.print(f"Found [cyan]{len(merged_pls)}[/cyan] unique Public Laws\n")

    # Step 5: Identify new PLs (not already in graph)
    new_pls = {pl_id: pl for pl_id, pl in merged_pls.items() if pl_id not in existing_pls}
    console.print(f"[green]{len(new_pls)}[/green] new Public Laws to create\n")

    # Show statistics about the new PLs
    pls_with_dates = sum(1 for pl in new_pls.values() if pl.enacted_date is not None)
    pls_with_stat = sum(1 for pl in new_pls.values() if pl.statutes_at_large is not None)

    table = Table(title="New Public Law Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="green")
    table.add_row("Total new PLs", str(len(new_pls)))
    table.add_row("With enacted date", str(pls_with_dates))
    table.add_row("With Stat citation", str(pls_with_stat))
    console.print(table)
    console.print()

    # Congress distribution
    congress_counts: dict[int, int] = defaultdict(int)
    for pl in new_pls.values():
        congress_counts[pl.congress] += 1

    # Show top congresses
    sorted_congresses = sorted(congress_counts.items(), key=lambda x: -x[1])[:10]
    if sorted_congresses:
        table2 = Table(title="Top Congresses by PL Count")
        table2.add_column("Congress", style="cyan")
        table2.add_column("PLs", style="green")
        for congress, count in sorted_congresses:
            table2.add_row(str(congress), str(count))
        console.print(table2)
        console.print()

    if dry_run:
        console.print("[yellow]DRY RUN - no changes will be made[/yellow]\n")

        # Show sample PLs that would be created
        console.print("[bold]Sample of Public Laws that would be created:[/bold]")
        for pl_id, pl in list(new_pls.items())[:10]:
            date_str = pl.enacted_date.isoformat() if pl.enacted_date else "unknown"
            stat_str = pl.statutes_at_large or "none"
            sections_count = len(pl.source_section_ids)
            console.print(f"  {pl_id}: date={date_str}, stat={stat_str}, affects {sections_count} sections")

        if len(new_pls) > 10:
            console.print(f"  ... and {len(new_pls) - 10} more")

        store.close()
        return

    # Step 6: Create skeleton PublicLaw nodes
    console.print("[bold]Creating skeleton PublicLaw nodes...[/bold]")
    nodes_created = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Creating nodes...", total=len(new_pls))

        with store.session() as session:
            for pl_id, pl in new_pls.items():
                # Create the node with skeleton data
                props = {
                    "id": pl.canonical_id,
                    "citation_congress": pl.congress,
                    "citation_law_number": pl.law_number,
                    "source_name": "usc_source_credit",
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                }

                if pl.enacted_date:
                    props["enacted_date"] = pl.enacted_date.isoformat()

                if pl.statutes_at_large:
                    props["statutes_at_large_citation"] = pl.statutes_at_large

                session.run("""
                    MERGE (pl:PublicLaw {id: $id})
                    ON CREATE SET pl += $props
                """, id=pl.canonical_id, props=props)

                nodes_created += 1
                progress.advance(task)

    console.print(f"Created [green]{nodes_created}[/green] PublicLaw nodes\n")

    # Step 7: Create ENACTS/AMENDS edges
    console.print("[bold]Creating ENACTS/AMENDS edges...[/bold]")
    enacts_created = 0
    amends_created = 0

    # We need to process ALL merged PLs (including existing ones) for edge creation
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Creating edges...", total=len(merged_pls))

        with store.session() as session:
            for pl_id, pl in merged_pls.items():
                for section_id, position in pl.position_in_source.items():
                    # Determine relationship type
                    rel_type = "ENACTS" if position == 0 else "AMENDS"

                    # Check if edge already exists
                    exists_result = session.run("""
                        MATCH (pl:PublicLaw {id: $pl_id})-[r]->(usc:USCSection {id: $section_id})
                        RETURN count(r) as count
                    """, pl_id=pl_id, section_id=section_id)
                    exists = exists_result.single()["count"]

                    if exists == 0:
                        # Create the edge
                        session.run(f"""
                            MATCH (pl:PublicLaw {{id: $pl_id}})
                            MATCH (usc:USCSection {{id: $section_id}})
                            CREATE (pl)-[:{rel_type} {{source: 'usc_source_credit'}}]->(usc)
                        """, pl_id=pl_id, section_id=section_id)

                        if rel_type == "ENACTS":
                            enacts_created += 1
                        else:
                            amends_created += 1

                progress.advance(task)

    console.print(f"Created [green]{enacts_created}[/green] ENACTS edges")
    console.print(f"Created [green]{amends_created}[/green] AMENDS edges\n")

    # Step 8: Summary statistics
    console.print("[bold green]Extraction complete![/bold green]\n")

    final_table = Table(title="Final Summary")
    final_table.add_column("Metric", style="cyan")
    final_table.add_column("Count", style="green")
    final_table.add_row("New PublicLaw nodes created", str(nodes_created))
    final_table.add_row("ENACTS edges created", str(enacts_created))
    final_table.add_row("AMENDS edges created", str(amends_created))
    final_table.add_row("Total edges created", str(enacts_created + amends_created))
    console.print(final_table)

    # Verify in database
    console.print("\n[bold]Current graph statistics:[/bold]")
    with store.session() as session:
        # Node counts
        node_result = session.run("""
            MATCH (n)
            RETURN labels(n)[0] as label, count(*) as count
            ORDER BY count DESC
        """)

        node_table = Table(title="Nodes")
        node_table.add_column("Type", style="cyan")
        node_table.add_column("Count", style="green")
        for r in node_result:
            node_table.add_row(r["label"], str(r["count"]))
        console.print(node_table)

        # Relationship counts
        rel_result = session.run("""
            MATCH ()-[r]->()
            RETURN type(r) as type, count(*) as count
            ORDER BY count DESC
        """)

        rel_table = Table(title="Relationships")
        rel_table.add_column("Type", style="cyan")
        rel_table.add_column("Count", style="green")
        for r in rel_result:
            rel_table.add_row(r["type"], str(r["count"]))
        console.print(rel_table)

    store.close()


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract historical Public Laws from USC source credits"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be created without making changes"
    )

    args = parser.parse_args()

    try:
        extract_historical_pls(dry_run=args.dry_run)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
