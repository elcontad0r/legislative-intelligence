"""
Ingestion Pipeline - Orchestrates data loading into the citation graph.

This module:
1. Coordinates adapters to fetch data from various sources
2. Extracts citations and creates relationships
3. Loads nodes and edges into the graph database
4. Tracks ingestion progress and handles errors
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from ..adapters.usc_xml import USCodeXMLAdapter
from ..adapters.congress_gov import CongressGovAdapter
from ..graph.neo4j_store import Neo4jStore
from ..parsers.citations import CitationParser
from ..models import (
    USCSection,
    PublicLaw,
    Bill,
    Entity,
    ProvenanceInfo,
    AmendsEdge,
    EnactsEdge,
    SponsoredEdge,
)

console = Console()


class IngestionPipeline:
    """
    Main ingestion pipeline for building the citation graph.

    Usage:
        pipeline = IngestionPipeline()

        # Ingest US Code Title 42 (Medicare)
        pipeline.ingest_usc_title("/path/to/usc42.xml")

        # Enrich with Congress.gov data
        pipeline.enrich_with_congress_data(congress=117)

        # Get stats
        pipeline.print_stats()
    """

    def __init__(
        self,
        graph_store: Neo4jStore | None = None,
        congress_api_key: str | None = None,
    ):
        """
        Initialize the pipeline.

        Args:
            graph_store: Neo4j store instance (or creates one from env vars)
            congress_api_key: Congress.gov API key (or uses env var)
        """
        self.graph = graph_store or Neo4jStore()
        self.graph.connect()

        self.congress_api_key = congress_api_key or os.getenv("CONGRESS_GOV_API_KEY")

        self.citation_parser = CitationParser()
        self.usc_adapter = USCodeXMLAdapter()

        # Track what we've ingested
        self.stats = {
            "usc_sections": 0,
            "public_laws": 0,
            "bills": 0,
            "entities": 0,
            "amends_edges": 0,
            "enacts_edges": 0,
            "sponsored_edges": 0,
        }

    def close(self):
        """Clean up resources."""
        self.graph.close()

    # =========================================================================
    # US Code Ingestion
    # =========================================================================

    def ingest_usc_title(self, filepath: str | Path, batch_size: int = 100) -> int:
        """
        Ingest a US Code title from XML.

        Args:
            filepath: Path to the USC XML file
            batch_size: Number of sections to batch for database writes

        Returns:
            Number of sections ingested
        """
        filepath = Path(filepath)
        console.print(f"\n[bold blue]Ingesting US Code from {filepath.name}[/bold blue]")

        sections: list[USCSection] = []
        public_law_links: list[tuple[str, str, str]] = []  # (pl_citation, usc_id, type)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            # Parse XML
            task = progress.add_task("Parsing XML...", total=None)

            for section in self.usc_adapter.parse_title_file(filepath):
                sections.append(section)

                # Extract public law citations for linking
                pl_citations = self.usc_adapter.extract_public_law_citations(section)

                # First citation is typically the enacting law
                for i, pl_cite in enumerate(pl_citations):
                    link_type = "ENACTS" if i == 0 else "AMENDS"
                    public_law_links.append((pl_cite.canonical, section.id, link_type))

                progress.update(task, advance=1, description=f"Parsing... ({len(sections)} sections)")

            progress.update(task, completed=True, description=f"Parsed {len(sections)} sections")

            # Insert sections into graph
            task2 = progress.add_task("Inserting into graph...", total=len(sections))

            count = self.graph.upsert_nodes_batch(sections, batch_size=batch_size)
            progress.update(task2, completed=len(sections))

        self.stats["usc_sections"] += count
        console.print(f"[green]✓[/green] Inserted {count} USC sections")

        # Store the links for later (we'll create PublicLaw nodes when we have congress.gov data)
        self._pending_pl_links = public_law_links
        console.print(f"[dim]Found {len(public_law_links)} Public Law citations to link[/dim]")

        return count

    def ingest_usc_directory(self, dirpath: str | Path) -> int:
        """Ingest all USC XML files in a directory."""
        dirpath = Path(dirpath)
        total = 0

        for xml_file in sorted(dirpath.glob("usc*.xml")):
            count = self.ingest_usc_title(xml_file)
            total += count

        return total

    # =========================================================================
    # Congress.gov Enrichment
    # =========================================================================

    def enrich_with_congress_data(
        self,
        congress: int,
        include_laws: bool = True,
        include_members: bool = True,
        include_reports: bool = False,  # Can be slow
    ) -> dict[str, int]:
        """
        Enrich the graph with data from Congress.gov.

        Args:
            congress: Congress number to fetch data for
            include_laws: Fetch public laws
            include_members: Fetch members
            include_reports: Fetch committee reports (slow)

        Returns:
            Dict of counts by type
        """
        if not self.congress_api_key:
            console.print("[yellow]Warning: No Congress.gov API key, skipping enrichment[/yellow]")
            return {}

        console.print(f"\n[bold blue]Enriching with Congress.gov data (Congress {congress})[/bold blue]")

        counts = {"laws": 0, "members": 0, "reports": 0}

        with CongressGovAdapter(self.congress_api_key) as adapter:
            # Fetch public laws
            if include_laws:
                console.print("Fetching public laws...")
                laws = list(adapter.get_laws(congress))
                if laws:
                    self.graph.upsert_nodes_batch(laws)
                    counts["laws"] = len(laws)
                    self.stats["public_laws"] += len(laws)
                    console.print(f"[green]✓[/green] Inserted {len(laws)} public laws")

            # Fetch members
            if include_members:
                console.print("Fetching members of Congress...")
                members = list(adapter.get_members(congress))
                if members:
                    self.graph.upsert_nodes_batch(members)
                    counts["members"] = len(members)
                    self.stats["entities"] += len(members)
                    console.print(f"[green]✓[/green] Inserted {len(members)} members")

            # Fetch committee reports (optional - can be slow)
            if include_reports:
                console.print("Fetching committee reports...")
                reports = list(adapter.get_committee_reports(congress))
                if reports:
                    self.graph.upsert_nodes_batch(reports)
                    counts["reports"] = len(reports)
                    console.print(f"[green]✓[/green] Inserted {len(reports)} reports")

        return counts

    def link_public_laws_to_sections(self) -> int:
        """
        Create edges between Public Laws and USC sections based on extracted citations.

        Call this after ingesting both USC data and Congress.gov data.
        """
        if not hasattr(self, "_pending_pl_links"):
            console.print("[yellow]No pending links to process[/yellow]")
            return 0

        console.print(f"\n[bold blue]Linking Public Laws to USC sections[/bold blue]")

        edges_created = 0
        enacts_edges = []
        amends_edges = []

        for pl_citation, usc_id, link_type in self._pending_pl_links:
            provenance = ProvenanceInfo(
                source_name="uscode.house.gov",
                retrieved_at=datetime.utcnow(),
            )

            if link_type == "ENACTS":
                edge = EnactsEdge(
                    from_id=pl_citation,
                    to_id=usc_id,
                    provenance=provenance,
                )
                enacts_edges.append(edge)
            else:
                edge = AmendsEdge(
                    from_id=pl_citation,
                    to_id=usc_id,
                    provenance=provenance,
                )
                amends_edges.append(edge)

        # Batch insert edges
        if enacts_edges:
            count = self.graph.upsert_edges_batch(enacts_edges)
            edges_created += count
            self.stats["enacts_edges"] += count
            console.print(f"[green]✓[/green] Created {count} ENACTS edges")

        if amends_edges:
            count = self.graph.upsert_edges_batch(amends_edges)
            edges_created += count
            self.stats["amends_edges"] += count
            console.print(f"[green]✓[/green] Created {count} AMENDS edges")

        # Clear pending links
        del self._pending_pl_links

        return edges_created

    # =========================================================================
    # Bill Ingestion
    # =========================================================================

    def ingest_bill_with_relations(
        self, congress: int, bill_type: str, number: int
    ) -> Bill | None:
        """
        Ingest a specific bill and create all its relationships.

        This fetches:
        - The bill itself
        - Sponsor and cosponsor entities
        - Creates SPONSORED edges
        """
        if not self.congress_api_key:
            console.print("[yellow]No Congress.gov API key[/yellow]")
            return None

        with CongressGovAdapter(self.congress_api_key) as adapter:
            # Get the bill
            bill = adapter.get_bill(congress, bill_type, number)
            if not bill:
                return None

            # Insert bill
            self.graph.upsert_node(bill)
            self.stats["bills"] += 1

            # Get and insert sponsor
            if bill.sponsor_id:
                sponsor = adapter.get_member(bill.sponsor_id)
                if sponsor:
                    self.graph.upsert_node(sponsor)
                    self.stats["entities"] += 1

                    # Create SPONSORED edge
                    edge = SponsoredEdge(
                        from_id=sponsor.id,
                        to_id=bill.id,
                        is_primary=True,
                        provenance=ProvenanceInfo(
                            source_name="congress.gov",
                            retrieved_at=datetime.utcnow(),
                        ),
                    )
                    self.graph.upsert_edge(edge)
                    self.stats["sponsored_edges"] += 1

            # Get cosponsors
            cosponsors = adapter.get_bill_cosponsors(congress, bill_type, number)
            for cosponsor in cosponsors:
                self.graph.upsert_node(cosponsor)
                self.stats["entities"] += 1

                edge = SponsoredEdge(
                    from_id=cosponsor.id,
                    to_id=bill.id,
                    is_primary=False,
                    provenance=ProvenanceInfo(
                        source_name="congress.gov",
                        retrieved_at=datetime.utcnow(),
                    ),
                )
                self.graph.upsert_edge(edge)
                self.stats["sponsored_edges"] += 1

            console.print(f"[green]✓[/green] Ingested {bill.citation} with {len(cosponsors)} cosponsors")
            return bill

    # =========================================================================
    # Utilities
    # =========================================================================

    def init_database(self):
        """Initialize the database schema."""
        console.print("[bold]Initializing database schema...[/bold]")
        self.graph.init_schema()
        console.print("[green]✓[/green] Schema initialized")

    def clear_database(self, confirm: bool = False):
        """Clear all data from the database."""
        if not confirm:
            console.print("[red]Pass confirm=True to clear the database[/red]")
            return

        console.print("[bold red]Clearing database...[/bold red]")
        self.graph.clear_all(confirm=True)
        console.print("[green]✓[/green] Database cleared")

        # Reset stats
        for key in self.stats:
            self.stats[key] = 0

    def print_stats(self):
        """Print ingestion statistics."""
        table = Table(title="Ingestion Statistics")
        table.add_column("Type", style="cyan")
        table.add_column("Count", style="green", justify="right")

        table.add_row("USC Sections", str(self.stats["usc_sections"]))
        table.add_row("Public Laws", str(self.stats["public_laws"]))
        table.add_row("Bills", str(self.stats["bills"]))
        table.add_row("Entities", str(self.stats["entities"]))
        table.add_row("", "")
        table.add_row("ENACTS edges", str(self.stats["enacts_edges"]))
        table.add_row("AMENDS edges", str(self.stats["amends_edges"]))
        table.add_row("SPONSORED edges", str(self.stats["sponsored_edges"]))

        console.print(table)

        # Also get live stats from the database
        try:
            db_stats = self.graph.get_stats()
            console.print("\n[dim]Live database counts:[/dim]")
            console.print(f"  Nodes: {db_stats.get('nodes', {})}")
            console.print(f"  Relationships: {db_stats.get('relationships', {})}")
        except Exception as e:
            console.print(f"[dim]Could not fetch live stats: {e}[/dim]")


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <command> [args]")
        print("Commands:")
        print("  init              Initialize database schema")
        print("  ingest <file>     Ingest USC XML file")
        print("  enrich <congress> Enrich with Congress.gov data")
        print("  stats             Show statistics")
        sys.exit(1)

    pipeline = IngestionPipeline()

    try:
        command = sys.argv[1]

        if command == "init":
            pipeline.init_database()

        elif command == "ingest":
            if len(sys.argv) < 3:
                print("Usage: python pipeline.py ingest <file_or_directory>")
                sys.exit(1)
            path = Path(sys.argv[2])
            if path.is_file():
                pipeline.ingest_usc_title(path)
            else:
                pipeline.ingest_usc_directory(path)

        elif command == "enrich":
            if len(sys.argv) < 3:
                print("Usage: python pipeline.py enrich <congress>")
                sys.exit(1)
            congress = int(sys.argv[2])
            pipeline.enrich_with_congress_data(congress)

        elif command == "stats":
            pipeline.print_stats()

        else:
            print(f"Unknown command: {command}")
            sys.exit(1)

    finally:
        pipeline.close()
