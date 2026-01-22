#!/usr/bin/env python3
"""
Fix section names in Neo4j Aura.

The original migration used the wrong property name (s.name instead of s.section_name).
This script copies section_name from local Neo4j to Aura.

Usage:
    # Set environment variables for Aura:
    export AURA_URI="neo4j+s://xxxxx.databases.neo4j.io"
    export AURA_USER="neo4j"
    export AURA_PASSWORD="your-password"

    # Run fix:
    python scripts/fix_section_names_aura.py
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


def fix_section_names():
    # Local connection (source)
    local_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    local_user = os.getenv("NEO4J_USER", "neo4j")
    local_password = os.getenv("NEO4J_PASSWORD", "password")

    # Aura connection (destination)
    aura_uri = os.getenv("AURA_URI")
    aura_user = os.getenv("AURA_USER", "neo4j")
    aura_password = os.getenv("AURA_PASSWORD")

    if not aura_uri or not aura_password:
        print("Error: Set AURA_URI and AURA_PASSWORD environment variables")
        sys.exit(1)

    print(f"Source: {local_uri}")
    print(f"Destination: {aura_uri}")
    print()

    # Connect to both
    local_driver = GraphDatabase.driver(local_uri, auth=(local_user, local_password))
    aura_driver = GraphDatabase.driver(aura_uri, auth=(aura_user, aura_password))

    try:
        # Get section names from local
        print("Fetching section names from local Neo4j...")
        with local_driver.session() as session:
            result = session.run("""
                MATCH (s:USCSection)
                WHERE s.section_name IS NOT NULL AND s.section_name <> ''
                RETURN s.id as id, s.section_name as section_name,
                       s.chapter as chapter, s.chapter_name as chapter_name,
                       s.title_name as title_name
            """)
            sections = list(result)
            print(f"Found {len(sections)} sections with names")

        # Update Aura
        print("\nUpdating Aura with section names...")
        batch_size = 100
        updated = 0

        with aura_driver.session() as session:
            for i in range(0, len(sections), batch_size):
                batch = sections[i:i+batch_size]
                for record in batch:
                    session.run("""
                        MATCH (s:USCSection {id: $id})
                        SET s.section_name = $section_name,
                            s.chapter = $chapter,
                            s.chapter_name = $chapter_name,
                            s.title_name = $title_name
                    """,
                    id=record['id'],
                    section_name=record['section_name'],
                    chapter=record['chapter'],
                    chapter_name=record['chapter_name'],
                    title_name=record['title_name']
                    )
                    updated += 1
                print(f"  Updated {min(i+batch_size, len(sections))}/{len(sections)} sections")

        print(f"\n--- Complete! Updated {updated} sections ---")

        # Verify
        print("\nVerifying...")
        with aura_driver.session() as session:
            result = session.run("""
                MATCH (s:USCSection)
                WHERE s.section_name IS NOT NULL AND s.section_name <> ''
                RETURN count(s) as count
            """)
            count = result.single()["count"]
            print(f"Aura now has {count} sections with names")

    finally:
        local_driver.close()
        aura_driver.close()


if __name__ == "__main__":
    fix_section_names()
