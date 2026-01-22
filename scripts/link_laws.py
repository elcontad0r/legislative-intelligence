#!/usr/bin/env python3
"""
Link Public Laws to USC Sections based on source credits.

This script:
1. Reads all USC sections that have source credits
2. Extracts Public Law citations from the source credits
3. Creates ENACTS/AMENDS relationships where the Public Law exists in the graph
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.progress import Progress

from src.graph.neo4j_store import Neo4jStore
from src.parsers.citations import CitationParser

console = Console()


def link_laws_to_sections():
    """Create edges between Public Laws and USC sections."""
    store = Neo4jStore()
    store.connect()
    parser = CitationParser()

    console.print("[bold]Linking Public Laws to USC Sections[/bold]\n")

    # First, get all Public Laws we have in the graph
    with store.session() as session:
        result = session.run("MATCH (pl:PublicLaw) RETURN pl.id as id")
        known_pls = {r["id"] for r in result}

    console.print(f"Found [cyan]{len(known_pls)}[/cyan] Public Laws in graph")

    # Get all USC sections with source credits
    with store.session() as session:
        result = session.run("""
            MATCH (usc:USCSection)
            WHERE usc.source_credit IS NOT NULL
            RETURN usc.id as id, usc.source_credit as source
        """)
        sections = list(result)

    console.print(f"Found [cyan]{len(sections)}[/cyan] USC sections with source credits\n")

    # Track statistics
    enacts_created = 0
    amends_created = 0
    total_citations = 0
    matched_citations = 0

    with Progress(console=console) as progress:
        task = progress.add_task("Processing sections...", total=len(sections))

        for record in sections:
            usc_id = record["id"]
            source = record["source"]

            # Extract Public Law citations
            pl_citations = parser.parse_public_laws(source)
            total_citations += len(pl_citations)

            for i, pl_cite in enumerate(pl_citations):
                pl_id = pl_cite.canonical

                # Only create edge if we have the Public Law
                if pl_id in known_pls:
                    matched_citations += 1

                    # First citation is typically the enacting law
                    rel_type = "ENACTS" if i == 0 else "AMENDS"

                    with store.session() as session:
                        # Check if edge already exists
                        exists = session.run("""
                            MATCH (pl:PublicLaw {id: $pl_id})-[r]->(usc:USCSection {id: $usc_id})
                            RETURN count(r) as count
                        """, pl_id=pl_id, usc_id=usc_id).single()["count"]

                        if exists == 0:
                            # Create the edge
                            session.run(f"""
                                MATCH (pl:PublicLaw {{id: $pl_id}})
                                MATCH (usc:USCSection {{id: $usc_id}})
                                CREATE (pl)-[:{rel_type} {{source: 'source_credit'}}]->(usc)
                            """, pl_id=pl_id, usc_id=usc_id)

                            if rel_type == "ENACTS":
                                enacts_created += 1
                            else:
                                amends_created += 1

            progress.advance(task)

    console.print(f"\n[bold green]Linking complete![/bold green]")
    console.print(f"  Total PL citations in source credits: [cyan]{total_citations}[/cyan]")
    console.print(f"  Citations matched to loaded PLs: [cyan]{matched_citations}[/cyan]")
    console.print(f"  ENACTS edges created: [green]{enacts_created}[/green]")
    console.print(f"  AMENDS edges created: [green]{amends_created}[/green]")

    # Verify in database
    with store.session() as session:
        result = session.run("""
            MATCH ()-[r]->()
            RETURN type(r) as type, count(*) as count
        """)
        console.print("\n[bold]Relationships in graph:[/bold]")
        for r in result:
            console.print(f"  {r['type']}: {r['count']}")

    store.close()


if __name__ == "__main__":
    link_laws_to_sections()
