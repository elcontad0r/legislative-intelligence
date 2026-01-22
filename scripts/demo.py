#!/usr/bin/env python3
"""
Legislative Intelligence Demo - Story of a Law

This demo shows how the system traces the legislative history of Medicare.

Run: python scripts/demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich import box

from src.graph.neo4j_store import Neo4jStore
from src.parsers.citations import CitationParser

console = Console()


def demo_citation_parser():
    """Show the citation parser in action."""
    console.print("\n")
    console.print(Panel.fit(
        "[bold cyan]Demo 1: Citation Parser[/bold cyan]\n\n"
        "The citation parser extracts and normalizes legal citations from any text.",
        border_style="cyan"
    ))

    parser = CitationParser()

    # Sample text with multiple citation formats
    sample_text = """
    The Social Security Act was amended by Pub. L. 89-97, which created Medicare
    under 42 U.S.C. § 1395. This was later modified by P.L. 111-148 (the Affordable
    Care Act), affecting sections 42 USC 1395w-4 and 26 U.S.C. 36B. The implementing
    regulations are found at 42 CFR 405.201.
    """

    console.print("\n[bold]Input text:[/bold]")
    console.print(Panel(sample_text.strip(), border_style="dim"))

    citations = parser.parse(sample_text)

    table = Table(title="Extracted Citations", box=box.ROUNDED)
    table.add_column("Type", style="cyan")
    table.add_column("Raw", style="white")
    table.add_column("Canonical Form", style="green")

    for cite in citations:
        table.add_row(
            cite.citation_type.name,
            cite.original,
            cite.canonical
        )

    console.print(table)


def demo_graph_queries():
    """Show graph queries against the loaded US Code."""
    console.print("\n")
    console.print(Panel.fit(
        "[bold cyan]Demo 2: Graph Queries[/bold cyan]\n\n"
        "Querying the Neo4j graph for Medicare sections and their history.",
        border_style="cyan"
    ))

    store = Neo4jStore()
    store.connect()

    try:
        # Count Medicare sections
        with store.session() as session:
            result = session.run("""
                MATCH (usc:USCSection)
                WHERE usc.id STARTS WITH "42 USC 1395"
                RETURN count(usc) as count
            """)
            medicare_count = result.single()["count"]

        console.print(f"\n[bold]Medicare sections in graph:[/bold] {medicare_count}")

        # Show some key sections
        console.print("\n[bold]Key Medicare Sections:[/bold]")

        with store.session() as session:
            result = session.run("""
                MATCH (usc:USCSection)
                WHERE usc.id IN [
                    "42 USC 1395",
                    "42 USC 1395a",
                    "42 USC 1395c",
                    "42 USC 1395d",
                    "42 USC 1395e"
                ]
                RETURN usc.id as id, usc.section_name as name, usc.source_credit as source
                ORDER BY usc.id
            """)

            table = Table(box=box.ROUNDED)
            table.add_column("Citation", style="cyan")
            table.add_column("Section Name", style="white")
            table.add_column("Original Enactment", style="green")

            for r in result:
                # Extract just the Pub. L. from source credit
                source = r["source"] or ""
                if "Pub. L." in source:
                    # Find first Pub. L. citation
                    import re
                    match = re.search(r"Pub\. L\. \d+[–-]\d+", source)
                    pl = match.group(0) if match else "See source"
                else:
                    pl = "See source"

                table.add_row(r["id"], r["name"] or "N/A", pl)

            console.print(table)

        # Show a section with lots of amendments
        console.print("\n[bold]Section with Complex History (42 USC 1395w-4):[/bold]")

        with store.session() as session:
            result = session.run("""
                MATCH (usc:USCSection {id: "42 USC 1395w-4"})
                RETURN usc.section_name as name, usc.source_credit as source
            """)
            record = result.single()

            if record:
                console.print(f"[cyan]{record['name']}[/cyan]")

                # Parse amendments from source credit
                source = record["source"] or ""
                parser = CitationParser()
                pls = parser.parse_public_laws(source)

                if pls:
                    console.print(f"\n[dim]This section has been amended by {len(pls)} Public Laws:[/dim]")
                    for i, pl in enumerate(pls[:10]):  # Show first 10
                        console.print(f"  {i+1}. {pl.canonical}")
                    if len(pls) > 10:
                        console.print(f"  ... and {len(pls) - 10} more")

    finally:
        store.close()


def demo_story_output():
    """Show the Story of a Law output."""
    console.print("\n")
    console.print(Panel.fit(
        "[bold cyan]Demo 3: Story of a Law[/bold cyan]\n\n"
        "Generating a narrative for 42 USC 10303 (Water Resources Research).\n"
        "This section was amended by the Infrastructure Investment and Jobs Act!",
        border_style="cyan"
    ))

    from src.api.story import StoryOfALaw
    import warnings
    warnings.filterwarnings("ignore")  # Suppress Neo4j warnings for demo

    story_gen = StoryOfALaw()
    try:
        # Use a section that has amendments from our loaded Public Laws
        story = story_gen.get_story("42 USC 10303")

        if story:
            # Show the markdown output
            md = story.to_markdown()
            console.print(Markdown(md))
        else:
            console.print("[red]Section not found[/red]")

    finally:
        story_gen.close()


def demo_search():
    """Show semantic search capabilities."""
    console.print("\n")
    console.print(Panel.fit(
        "[bold cyan]Demo 4: Search Capabilities[/bold cyan]\n\n"
        "Searching the US Code for specific topics.",
        border_style="cyan"
    ))

    store = Neo4jStore()
    store.connect()

    try:
        # Full-text search on section names
        searches = [
            ("hospital", "Hospital-related provisions"),
            ("physician", "Physician-related provisions"),
            ("fraud", "Anti-fraud provisions"),
        ]

        for term, description in searches:
            console.print(f"\n[bold]Search: '{term}'[/bold] - {description}")

            with store.session() as session:
                result = session.run("""
                    MATCH (usc:USCSection)
                    WHERE toLower(usc.section_name) CONTAINS toLower($term)
                    OR toLower(usc.text) CONTAINS toLower($term)
                    RETURN usc.id as id, usc.section_name as name
                    LIMIT 5
                """, term=term)

                for r in result:
                    console.print(f"  - [cyan]{r['id']}[/cyan]: {r['name']}")

    finally:
        store.close()


def main():
    console.print(Panel.fit(
        "[bold white on blue] Legislative Intelligence System [/bold white on blue]\n\n"
        "[bold]The Story of a Law[/bold] - Demo\n\n"
        "This demo shows how we trace the legislative history of Medicare,\n"
        "from its creation in 1965 to its current form.",
        border_style="blue",
        padding=(1, 4)
    ))

    # Check Neo4j connection first
    console.print("\n[dim]Checking Neo4j connection...[/dim]")
    try:
        store = Neo4jStore()
        store.connect()
        store.close()
        console.print("[green]✓ Neo4j connected[/green]")
    except Exception as e:
        console.print(f"[red]✗ Neo4j connection failed: {e}[/red]")
        console.print("\n[yellow]Start Neo4j with: brew services start neo4j[/yellow]")
        return

    # Run demos
    demo_citation_parser()
    demo_graph_queries()
    demo_story_output()
    demo_search()

    # Summary
    console.print("\n")
    console.print(Panel.fit(
        "[bold green]Demo Complete![/bold green]\n\n"
        "[bold]What you've seen:[/bold]\n"
        "1. Citation parser extracting legal citations from text\n"
        "2. Graph queries against 6,651 USC sections\n"
        "3. Story generation with real legislative history\n"
        "4. Full-text search across the US Code\n\n"
        "[bold]Current Graph Stats:[/bold]\n"
        "- 6,651 USC Sections from Title 42\n"
        "- 362 Public Laws from 117th Congress\n"
        "- 557 Members of Congress\n"
        "- 580 AMENDS/ENACTS relationships\n\n"
        "[bold]Try it yourself:[/bold]\n"
        "python3 -m src.api.story '42 USC 1395'    # Medicare\n"
        "python3 -m src.api.story '42 USC 1103'    # Unemployment",
        border_style="green",
        padding=(1, 2)
    ))


if __name__ == "__main__":
    main()
