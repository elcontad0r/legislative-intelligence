#!/usr/bin/env python3
"""
Export Neo4j data for migration to Neo4j Aura.

This script exports all nodes and relationships to Cypher statements
that can be run on a fresh Aura instance.

Usage:
    python scripts/export_for_aura.py > data/aura_import.cypher

Then in Aura:
    1. Create a new free instance
    2. Open Neo4j Browser
    3. Run the generated Cypher file (may need to batch it)
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


def export_to_cypher():
    """Export all data to Cypher CREATE statements."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")

    driver = GraphDatabase.driver(uri, auth=(user, password))

    print("// Neo4j Aura Import Script")
    print("// Generated from local Neo4j instance")
    print("// Run this in Neo4j Browser on your Aura instance")
    print("")
    print("// Step 1: Create constraints (run these first)")
    print("CREATE CONSTRAINT usc_section_id IF NOT EXISTS FOR (s:USCSection) REQUIRE s.id IS UNIQUE;")
    print("CREATE CONSTRAINT public_law_id IF NOT EXISTS FOR (p:PublicLaw) REQUIRE p.id IS UNIQUE;")
    print("CREATE CONSTRAINT member_id IF NOT EXISTS FOR (m:Member) REQUIRE m.bioguide_id IS UNIQUE;")
    print("")

    with driver.session() as session:
        # Export USCSection nodes
        print("// Step 2: Create USCSection nodes")
        print("// (Run in batches if needed)")
        result = session.run("""
            MATCH (s:USCSection)
            RETURN s.id as id, s.title as title, s.section as section,
                   s.section_name as section_name, s.text as text, s.source_credit as source_credit,
                   s.enacted_by as enacted_by, s.amendment_count as amendment_count,
                   s.chapter as chapter, s.chapter_name as chapter_name,
                   s.title_name as title_name
            LIMIT 5000
        """)

        batch = []
        for record in result:
            props = {
                "id": record["id"],
                "title": record["title"],
                "section": record["section"],
                "section_name": record["section_name"] or "",
                "source_credit": record["source_credit"] or "",
                "enacted_by": record["enacted_by"] or "",
                "amendment_count": record["amendment_count"] or 0,
                "chapter": record["chapter"] or "",
                "chapter_name": record["chapter_name"] or "",
                "title_name": record["title_name"] or "",
            }
            # Skip text for now - too large
            props_str = ", ".join(f'{k}: {repr(v)}' for k, v in props.items() if v)
            batch.append(f"CREATE (:USCSection {{{props_str}}})")

            if len(batch) >= 100:
                print("\n".join(batch))
                print("")
                batch = []

        if batch:
            print("\n".join(batch))
            print("")

        # Export PublicLaw nodes
        print("// Step 3: Create PublicLaw nodes")
        result = session.run("""
            MATCH (p:PublicLaw)
            RETURN p.id as id, p.congress as congress, p.law_number as law_number,
                   p.title as title, p.enacted_date as enacted_date
        """)

        batch = []
        for record in result:
            props = {
                "id": record["id"],
                "congress": record["congress"],
                "law_number": record["law_number"],
                "title": record["title"] or "",
            }
            if record["enacted_date"]:
                props["enacted_date"] = str(record["enacted_date"])

            props_str = ", ".join(f'{k}: {repr(v)}' for k, v in props.items() if v is not None)
            batch.append(f"CREATE (:PublicLaw {{{props_str}}})")

            if len(batch) >= 100:
                print("\n".join(batch))
                print("")
                batch = []

        if batch:
            print("\n".join(batch))
            print("")

        # Export relationships
        print("// Step 4: Create AMENDS relationships")
        result = session.run("""
            MATCH (p:PublicLaw)-[r:AMENDS]->(s:USCSection)
            RETURN p.id as pl_id, s.id as section_id
            LIMIT 15000
        """)

        batch = []
        for record in result:
            batch.append(f"MATCH (p:PublicLaw {{id: '{record['pl_id']}'}}), (s:USCSection {{id: '{record['section_id']}'}}) CREATE (p)-[:AMENDS]->(s);")

            if len(batch) >= 100:
                print("\n".join(batch))
                print("")
                batch = []

        if batch:
            print("\n".join(batch))
            print("")

        print("// Step 5: Create ENACTS relationships")
        result = session.run("""
            MATCH (p:PublicLaw)-[r:ENACTS]->(s:USCSection)
            RETURN p.id as pl_id, s.id as section_id
            LIMIT 10000
        """)

        batch = []
        for record in result:
            batch.append(f"MATCH (p:PublicLaw {{id: '{record['pl_id']}'}}), (s:USCSection {{id: '{record['section_id']}'}}) CREATE (p)-[:ENACTS]->(s);")

            if len(batch) >= 100:
                print("\n".join(batch))
                print("")
                batch = []

        if batch:
            print("\n".join(batch))
            print("")

        print("// Step 6: Create CITES relationships")
        result = session.run("""
            MATCH (s1:USCSection)-[r:CITES]->(s2:USCSection)
            RETURN s1.id as from_id, s2.id as to_id
            LIMIT 10000
        """)

        batch = []
        for record in result:
            batch.append(f"MATCH (s1:USCSection {{id: '{record['from_id']}'}}), (s2:USCSection {{id: '{record['to_id']}'}}) CREATE (s1)-[:CITES]->(s2);")

            if len(batch) >= 100:
                print("\n".join(batch))
                print("")
                batch = []

        if batch:
            print("\n".join(batch))
            print("")

    driver.close()
    print("// Import complete!")


if __name__ == "__main__":
    export_to_cypher()
