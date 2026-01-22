#!/usr/bin/env python3
"""
Congress.gov Enricher - Enrich PublicLaw nodes with titles and metadata from Congress.gov API.

This module:
1. Identifies PublicLaw nodes that need enrichment (have citation but no title)
2. Fetches law data from Congress.gov API
3. Updates Neo4j nodes with title, bill origin, and metadata
4. Handles rate limiting and resumable operations

Usage:
    # From command line
    python -m src.enrichment.congress_gov_enricher --congress 109
    python -m src.enrichment.congress_gov_enricher --all-missing

    # From code
    enricher = CongressGovEnricher()
    enricher.enrich_congress(109)
    enricher.enrich_all_missing()
"""
from __future__ import annotations

import os
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.table import Table

from ..graph.neo4j_store import Neo4jStore
from ..adapters.congress_gov import CongressGovAdapter

console = Console()

# Congress.gov API rate limit: 5,000 requests/hour = ~1.4 requests/second
# We'll be conservative with a 0.75 second delay between requests
REQUEST_DELAY = 0.75

# Pre-93rd Congress (before 1973) data may not be available
MINIMUM_CONGRESS = 93


class CongressGovEnricher:
    """
    Enriches PublicLaw nodes in Neo4j with data from Congress.gov API.

    The enricher:
    - Fetches missing titles and metadata for PublicLaw nodes
    - Updates nodes with bill_origin, source_url, retrieved_at
    - Marks nodes as enrichment_attempted to avoid retrying
    - Handles rate limiting gracefully
    - Can resume if interrupted

    Usage:
        enricher = CongressGovEnricher()

        # Enrich laws from a specific Congress
        enricher.enrich_congress(117)

        # Enrich all laws missing titles
        enricher.enrich_all_missing()

        enricher.close()
    """

    def __init__(
        self,
        graph_store: Neo4jStore | None = None,
        api_key: str | None = None,
    ):
        """
        Initialize the enricher.

        Args:
            graph_store: Neo4j store instance (or creates one from env vars)
            api_key: Congress.gov API key (or uses env var)
        """
        self.graph = graph_store or Neo4jStore()
        self.graph.connect()

        self.api_key = api_key or os.getenv("CONGRESS_GOV_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Congress.gov API key required. "
                "Set CONGRESS_GOV_API_KEY environment variable or pass api_key parameter."
            )

        # Track statistics
        self.stats = {
            "total_checked": 0,
            "enriched": 0,
            "already_enriched": 0,
            "not_found": 0,
            "errors": 0,
        }

    def close(self):
        """Clean up resources."""
        self.graph.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # =========================================================================
    # Query Methods - Find PublicLaws needing enrichment
    # =========================================================================

    def get_unenriched_laws(self, congress: int | None = None) -> list[dict]:
        """
        Get PublicLaw nodes that need enrichment.

        A node needs enrichment if:
        - It has no title, OR
        - It was never attempted (no enrichment_attempted flag)

        Args:
            congress: Filter to specific Congress number, or None for all

        Returns:
            List of dicts with node properties
        """
        with self.graph.session() as session:
            if congress:
                # Filter by congress number
                result = session.run("""
                    MATCH (pl:PublicLaw)
                    WHERE pl.citation_congress = $congress
                      AND (pl.title IS NULL OR pl.enrichment_attempted IS NULL)
                      AND (pl.enrichment_failed IS NULL OR pl.enrichment_failed = false)
                    RETURN pl.id as id,
                           pl.citation_congress as congress,
                           pl.citation_law_number as law_number,
                           pl.title as title
                    ORDER BY pl.citation_law_number
                """, congress=congress)
            else:
                # Get all unenriched
                result = session.run("""
                    MATCH (pl:PublicLaw)
                    WHERE (pl.title IS NULL OR pl.enrichment_attempted IS NULL)
                      AND (pl.enrichment_failed IS NULL OR pl.enrichment_failed = false)
                    RETURN pl.id as id,
                           pl.citation_congress as congress,
                           pl.citation_law_number as law_number,
                           pl.title as title
                    ORDER BY pl.citation_congress, pl.citation_law_number
                """)

            return [dict(r) for r in result]

    def get_laws_by_congress(self, congress: int) -> list[dict]:
        """Get all PublicLaw nodes for a specific Congress."""
        with self.graph.session() as session:
            result = session.run("""
                MATCH (pl:PublicLaw)
                WHERE pl.citation_congress = $congress
                RETURN pl.id as id,
                       pl.citation_congress as congress,
                       pl.citation_law_number as law_number,
                       pl.title as title,
                       pl.enrichment_attempted as enrichment_attempted,
                       pl.enrichment_failed as enrichment_failed
                ORDER BY pl.citation_law_number
            """, congress=congress)
            return [dict(r) for r in result]

    def get_all_congresses_with_laws(self) -> list[int]:
        """Get list of all Congress numbers that have PublicLaw nodes."""
        with self.graph.session() as session:
            result = session.run("""
                MATCH (pl:PublicLaw)
                WHERE pl.citation_congress IS NOT NULL
                RETURN DISTINCT pl.citation_congress as congress
                ORDER BY congress
            """)
            return [r["congress"] for r in result]

    def get_enrichment_stats(self) -> dict:
        """Get statistics about enrichment status of all PublicLaw nodes."""
        with self.graph.session() as session:
            result = session.run("""
                MATCH (pl:PublicLaw)
                RETURN
                    count(*) as total,
                    sum(CASE WHEN pl.title IS NOT NULL THEN 1 ELSE 0 END) as with_title,
                    sum(CASE WHEN pl.title IS NULL THEN 1 ELSE 0 END) as without_title,
                    sum(CASE WHEN pl.enrichment_attempted = true THEN 1 ELSE 0 END) as attempted,
                    sum(CASE WHEN pl.enrichment_failed = true THEN 1 ELSE 0 END) as failed
            """)
            record = result.single()
            return dict(record) if record else {}

    # =========================================================================
    # Update Methods - Write enrichment data to Neo4j
    # =========================================================================

    def update_law_with_enrichment(
        self,
        node_id: str,
        title: str | None,
        bill_origin_congress: int | None = None,
        bill_origin_bill_type: str | None = None,
        bill_origin_number: int | None = None,
        enacted_date: str | None = None,
        source_url: str | None = None,
    ) -> bool:
        """
        Update a PublicLaw node with enrichment data.

        Args:
            node_id: The canonical ID (e.g., "Pub. L. 109-432")
            title: The law's official/short title
            bill_origin_*: Components of the originating bill citation
            enacted_date: ISO date string of when the law was enacted
            source_url: Congress.gov API URL for provenance

        Returns:
            True if updated successfully
        """
        with self.graph.session() as session:
            session.run("""
                MATCH (pl:PublicLaw {id: $id})
                SET pl.title = $title,
                    pl.bill_origin_congress = $bill_origin_congress,
                    pl.bill_origin_bill_type = $bill_origin_bill_type,
                    pl.bill_origin_number = $bill_origin_number,
                    pl.enacted_date = $enacted_date,
                    pl.enrichment_source_url = $source_url,
                    pl.enrichment_retrieved_at = $retrieved_at,
                    pl.enrichment_attempted = true,
                    pl.enrichment_failed = false
            """,
                id=node_id,
                title=title,
                bill_origin_congress=bill_origin_congress,
                bill_origin_bill_type=bill_origin_bill_type,
                bill_origin_number=bill_origin_number,
                enacted_date=enacted_date,
                source_url=source_url,
                retrieved_at=datetime.utcnow().isoformat(),
            )
            return True

    def mark_enrichment_failed(self, node_id: str, reason: str | None = None) -> bool:
        """
        Mark a PublicLaw node as failed enrichment.

        This prevents retrying nodes that are known to not have data
        (e.g., pre-93rd Congress laws not in Congress.gov).
        """
        with self.graph.session() as session:
            session.run("""
                MATCH (pl:PublicLaw {id: $id})
                SET pl.enrichment_attempted = true,
                    pl.enrichment_failed = true,
                    pl.enrichment_failed_reason = $reason,
                    pl.enrichment_retrieved_at = $retrieved_at
            """,
                id=node_id,
                reason=reason,
                retrieved_at=datetime.utcnow().isoformat(),
            )
            return True

    # =========================================================================
    # Enrichment Logic
    # =========================================================================

    def enrich_single_law(
        self,
        congress: int,
        law_number: int,
        adapter: CongressGovAdapter,
    ) -> bool:
        """
        Enrich a single PublicLaw node from Congress.gov.

        Args:
            congress: Congress number
            law_number: Law number within that Congress
            adapter: Congress.gov API adapter instance

        Returns:
            True if enriched successfully, False otherwise
        """
        node_id = f"Pub. L. {congress}-{law_number}"

        # Check if Congress predates available data
        if congress < MINIMUM_CONGRESS:
            self.mark_enrichment_failed(
                node_id,
                f"Pre-{MINIMUM_CONGRESS}rd Congress - data not available in Congress.gov"
            )
            return False

        try:
            # Fetch from API
            law = adapter.get_law(congress, law_number)

            if law is None:
                # API returned 404 - law not found
                self.mark_enrichment_failed(node_id, "Not found in Congress.gov API")
                return False

            # Extract bill origin info if present
            bill_origin_congress = None
            bill_origin_type = None
            bill_origin_number = None

            if law.bill_origin:
                bill_origin_congress = law.bill_origin.congress
                bill_origin_type = law.bill_origin.bill_type.value if law.bill_origin.bill_type else None
                bill_origin_number = law.bill_origin.number

            # Update the node
            self.update_law_with_enrichment(
                node_id=node_id,
                title=law.title,
                bill_origin_congress=bill_origin_congress,
                bill_origin_bill_type=bill_origin_type,
                bill_origin_number=bill_origin_number,
                enacted_date=law.enacted_date.isoformat() if law.enacted_date else None,
                source_url=law.provenance.source_url if law.provenance else None,
            )

            return True

        except Exception as e:
            console.print(f"[red]Error enriching {node_id}: {e}[/red]")
            self.mark_enrichment_failed(node_id, str(e))
            return False

    def enrich_congress(self, congress: int) -> dict:
        """
        Enrich all PublicLaw nodes from a specific Congress.

        This is the most efficient approach when you have many laws from
        one Congress, as Congress.gov's /law/{congress} endpoint returns
        all laws for that Congress in paginated form.

        Args:
            congress: Congress number to enrich

        Returns:
            Dict with enrichment statistics
        """
        console.print(f"\n[bold blue]Enriching Public Laws from {congress}th Congress[/bold blue]")

        # Get laws that need enrichment for this Congress
        laws_to_enrich = self.get_unenriched_laws(congress)

        if not laws_to_enrich:
            console.print("[yellow]No laws need enrichment for this Congress[/yellow]")
            return {"total": 0, "enriched": 0, "failed": 0}

        console.print(f"Found [cyan]{len(laws_to_enrich)}[/cyan] laws needing enrichment")

        # Check if Congress predates available data
        if congress < MINIMUM_CONGRESS:
            console.print(f"[yellow]Congress {congress} predates Congress.gov data (minimum: {MINIMUM_CONGRESS})[/yellow]")
            console.print("Marking all as enrichment_failed...")

            for law in laws_to_enrich:
                self.mark_enrichment_failed(
                    law["id"],
                    f"Pre-{MINIMUM_CONGRESS}rd Congress - data not available"
                )

            return {"total": len(laws_to_enrich), "enriched": 0, "failed": len(laws_to_enrich)}

        # Build lookup set of laws we need
        needed_laws = {(law["congress"], law["law_number"]) for law in laws_to_enrich}

        enriched = 0
        failed = 0

        with CongressGovAdapter(self.api_key) as adapter:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as progress:

                # Fetch all laws from this Congress via the list endpoint
                task = progress.add_task(
                    f"Fetching laws from Congress {congress}...",
                    total=len(laws_to_enrich)
                )

                found_laws = {}

                # The get_laws endpoint returns PublicLaw objects with full data
                for law in adapter.get_laws(congress):
                    if law.citation:
                        key = (law.citation.congress, law.citation.law_number)
                        if key in needed_laws:
                            found_laws[key] = law

                    # Rate limiting
                    time.sleep(REQUEST_DELAY / 10)  # Light delay during iteration

                progress.update(task, description="Processing fetched laws...")

                # Now update the nodes
                for key in needed_laws:
                    congress_num, law_num = key
                    node_id = f"Pub. L. {congress_num}-{law_num}"

                    if key in found_laws:
                        law = found_laws[key]

                        # Extract bill origin info
                        bill_origin_congress = None
                        bill_origin_type = None
                        bill_origin_number = None

                        if law.bill_origin:
                            bill_origin_congress = law.bill_origin.congress
                            bill_origin_type = law.bill_origin.bill_type.value if law.bill_origin.bill_type else None
                            bill_origin_number = law.bill_origin.number

                        self.update_law_with_enrichment(
                            node_id=node_id,
                            title=law.title,
                            bill_origin_congress=bill_origin_congress,
                            bill_origin_bill_type=bill_origin_type,
                            bill_origin_number=bill_origin_number,
                            enacted_date=law.enacted_date.isoformat() if law.enacted_date else None,
                            source_url=law.provenance.source_url if law.provenance else None,
                        )
                        enriched += 1
                    else:
                        # Law not found in bulk fetch - try individual lookup
                        time.sleep(REQUEST_DELAY)
                        if self.enrich_single_law(congress_num, law_num, adapter):
                            enriched += 1
                        else:
                            failed += 1

                    progress.advance(task)

        # Print summary
        console.print(f"\n[bold green]Enrichment complete![/bold green]")
        console.print(f"  Enriched: [green]{enriched}[/green]")
        console.print(f"  Failed/Not found: [yellow]{failed}[/yellow]")

        self.stats["total_checked"] += len(laws_to_enrich)
        self.stats["enriched"] += enriched
        self.stats["not_found"] += failed

        return {"total": len(laws_to_enrich), "enriched": enriched, "failed": failed}

    def enrich_all_missing(self) -> dict:
        """
        Enrich all PublicLaw nodes that are missing titles.

        Groups by Congress for efficient bulk fetching.

        Returns:
            Dict with total enrichment statistics
        """
        console.print("\n[bold blue]Enriching all Public Laws missing titles[/bold blue]")

        # Get all congresses that have laws needing enrichment
        all_unenriched = self.get_unenriched_laws()

        if not all_unenriched:
            console.print("[green]All Public Laws are already enriched![/green]")
            return {"total": 0, "enriched": 0, "failed": 0}

        # Group by Congress
        by_congress: dict[int, list] = {}
        for law in all_unenriched:
            cong = law["congress"]
            if cong:
                by_congress.setdefault(cong, []).append(law)

        console.print(f"Found [cyan]{len(all_unenriched)}[/cyan] laws across [cyan]{len(by_congress)}[/cyan] congresses")

        # Show breakdown
        table = Table(title="Laws by Congress")
        table.add_column("Congress", style="cyan", justify="right")
        table.add_column("Count", style="green", justify="right")
        table.add_column("Status", style="yellow")

        for cong in sorted(by_congress.keys()):
            count = len(by_congress[cong])
            status = "Available" if cong >= MINIMUM_CONGRESS else f"Pre-{MINIMUM_CONGRESS}th (no data)"
            table.add_row(str(cong), str(count), status)

        console.print(table)

        # Process each Congress
        total_enriched = 0
        total_failed = 0

        for cong in sorted(by_congress.keys()):
            result = self.enrich_congress(cong)
            total_enriched += result["enriched"]
            total_failed += result["failed"]

        # Final summary
        console.print(f"\n[bold green]All enrichment complete![/bold green]")
        console.print(f"  Total processed: [cyan]{len(all_unenriched)}[/cyan]")
        console.print(f"  Enriched: [green]{total_enriched}[/green]")
        console.print(f"  Failed/Not found: [yellow]{total_failed}[/yellow]")

        return {
            "total": len(all_unenriched),
            "enriched": total_enriched,
            "failed": total_failed,
        }

    def print_status(self):
        """Print current enrichment status of all PublicLaw nodes."""
        stats = self.get_enrichment_stats()

        table = Table(title="PublicLaw Enrichment Status")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="green", justify="right")

        table.add_row("Total PublicLaw nodes", str(stats.get("total", 0)))
        table.add_row("With title", str(stats.get("with_title", 0)))
        table.add_row("Without title", str(stats.get("without_title", 0)))
        table.add_row("Enrichment attempted", str(stats.get("attempted", 0)))
        table.add_row("Enrichment failed", str(stats.get("failed", 0)))

        console.print(table)

        # Show breakdown by Congress
        congresses = self.get_all_congresses_with_laws()
        if congresses:
            console.print(f"\n[dim]Congresses with PublicLaw nodes: {min(congresses)}-{max(congresses)}[/dim]")


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """CLI entry point for the enricher."""
    parser = argparse.ArgumentParser(
        description="Enrich PublicLaw nodes with Congress.gov metadata",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.enrichment.congress_gov_enricher --congress 109
  python -m src.enrichment.congress_gov_enricher --all-missing
  python -m src.enrichment.congress_gov_enricher --status
        """,
    )

    parser.add_argument(
        "--congress",
        type=int,
        help="Enrich laws from a specific Congress number",
    )
    parser.add_argument(
        "--all-missing",
        action="store_true",
        help="Enrich all PublicLaw nodes missing titles",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current enrichment status",
    )

    args = parser.parse_args()

    # Validate arguments
    if not any([args.congress, args.all_missing, args.status]):
        parser.print_help()
        sys.exit(1)

    # Run enrichment
    try:
        with CongressGovEnricher() as enricher:
            if args.status:
                enricher.print_status()
            elif args.congress:
                enricher.enrich_congress(args.congress)
            elif args.all_missing:
                enricher.enrich_all_missing()

    except ValueError as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        sys.exit(1)
    except ConnectionError as e:
        console.print(f"[red]Database connection error: {e}[/red]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
