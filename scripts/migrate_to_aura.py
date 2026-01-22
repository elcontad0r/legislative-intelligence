#!/usr/bin/env python3
"""
Migrate data from local Neo4j to Neo4j Aura.

This script connects to both local and Aura instances and copies all data.

Usage:
    # Set environment variables for Aura:
    export AURA_URI="neo4j+s://xxxxx.databases.neo4j.io"
    export AURA_USER="neo4j"
    export AURA_PASSWORD="your-password"

    # Run migration:
    python scripts/migrate_to_aura.py
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


def migrate():
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
        print("Example:")
        print('  export AURA_URI="neo4j+s://xxxxx.databases.neo4j.io"')
        print('  export AURA_PASSWORD="your-password"')
        sys.exit(1)

    print(f"Source: {local_uri}")
    print(f"Destination: {aura_uri}")
    print()

    # Connect to both
    local_driver = GraphDatabase.driver(local_uri, auth=(local_user, local_password))
    aura_driver = GraphDatabase.driver(aura_uri, auth=(aura_user, aura_password))

    try:
        # Test connections
        with local_driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) as count")
            local_count = result.single()["count"]
            print(f"Local node count: {local_count}")

        with aura_driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) as count")
            aura_count = result.single()["count"]
            print(f"Aura node count: {aura_count}")

        if aura_count > 0:
            response = input(f"\nAura already has {aura_count} nodes. Clear and reimport? (y/N): ")
            if response.lower() != 'y':
                print("Aborted.")
                return

            print("Clearing Aura database...")
            with aura_driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")

        print("\n--- Step 1: Create constraints ---")
        with aura_driver.session() as session:
            session.run("CREATE CONSTRAINT usc_section_id IF NOT EXISTS FOR (s:USCSection) REQUIRE s.id IS UNIQUE")
            session.run("CREATE CONSTRAINT public_law_id IF NOT EXISTS FOR (p:PublicLaw) REQUIRE p.id IS UNIQUE")
            print("Constraints created.")

        print("\n--- Step 2: Migrate USCSection nodes ---")
        with local_driver.session() as local_session:
            result = local_session.run("""
                MATCH (s:USCSection)
                RETURN s.id as id, s.title as title, s.section as section,
                       s.name as name, s.source_credit as source_credit,
                       s.enacted_by as enacted_by, s.amendment_count as amendment_count
            """)
            sections = list(result)
            print(f"Found {len(sections)} sections to migrate")

        batch_size = 500
        with aura_driver.session() as aura_session:
            for i in range(0, len(sections), batch_size):
                batch = sections[i:i+batch_size]
                for record in batch:
                    props = {k: v for k, v in dict(record).items() if v is not None}
                    aura_session.run(
                        "CREATE (s:USCSection) SET s = $props",
                        props=props
                    )
                print(f"  Migrated {min(i+batch_size, len(sections))}/{len(sections)} sections")

        print("\n--- Step 3: Migrate PublicLaw nodes ---")
        with local_driver.session() as local_session:
            result = local_session.run("""
                MATCH (p:PublicLaw)
                RETURN p.id as id, p.congress as congress, p.law_number as law_number,
                       p.title as title, p.enacted_date as enacted_date
            """)
            laws = list(result)
            print(f"Found {len(laws)} public laws to migrate")

        with aura_driver.session() as aura_session:
            for i in range(0, len(laws), batch_size):
                batch = laws[i:i+batch_size]
                for record in batch:
                    props = {k: v for k, v in dict(record).items() if v is not None}
                    # Convert date to string if present
                    if 'enacted_date' in props and props['enacted_date']:
                        props['enacted_date'] = str(props['enacted_date'])
                    aura_session.run(
                        "CREATE (p:PublicLaw) SET p = $props",
                        props=props
                    )
                print(f"  Migrated {min(i+batch_size, len(laws))}/{len(laws)} laws")

        print("\n--- Step 4: Migrate AMENDS relationships ---")
        with local_driver.session() as local_session:
            result = local_session.run("""
                MATCH (p:PublicLaw)-[r:AMENDS]->(s:USCSection)
                RETURN p.id as pl_id, s.id as section_id
            """)
            amends = list(result)
            print(f"Found {len(amends)} AMENDS relationships")

        with aura_driver.session() as aura_session:
            for i in range(0, len(amends), batch_size):
                batch = amends[i:i+batch_size]
                for record in batch:
                    aura_session.run("""
                        MATCH (p:PublicLaw {id: $pl_id}), (s:USCSection {id: $section_id})
                        CREATE (p)-[:AMENDS]->(s)
                    """, pl_id=record['pl_id'], section_id=record['section_id'])
                print(f"  Migrated {min(i+batch_size, len(amends))}/{len(amends)} AMENDS")

        print("\n--- Step 5: Migrate ENACTS relationships ---")
        with local_driver.session() as local_session:
            result = local_session.run("""
                MATCH (p:PublicLaw)-[r:ENACTS]->(s:USCSection)
                RETURN p.id as pl_id, s.id as section_id
            """)
            enacts = list(result)
            print(f"Found {len(enacts)} ENACTS relationships")

        with aura_driver.session() as aura_session:
            for i in range(0, len(enacts), batch_size):
                batch = enacts[i:i+batch_size]
                for record in batch:
                    aura_session.run("""
                        MATCH (p:PublicLaw {id: $pl_id}), (s:USCSection {id: $section_id})
                        CREATE (p)-[:ENACTS]->(s)
                    """, pl_id=record['pl_id'], section_id=record['section_id'])
                print(f"  Migrated {min(i+batch_size, len(enacts))}/{len(enacts)} ENACTS")

        print("\n--- Step 6: Migrate CITES relationships ---")
        with local_driver.session() as local_session:
            result = local_session.run("""
                MATCH (s1:USCSection)-[r:CITES]->(s2:USCSection)
                RETURN s1.id as from_id, s2.id as to_id
            """)
            cites = list(result)
            print(f"Found {len(cites)} CITES relationships")

        with aura_driver.session() as aura_session:
            for i in range(0, len(cites), batch_size):
                batch = cites[i:i+batch_size]
                for record in batch:
                    aura_session.run("""
                        MATCH (s1:USCSection {id: $from_id}), (s2:USCSection {id: $to_id})
                        CREATE (s1)-[:CITES]->(s2)
                    """, from_id=record['from_id'], to_id=record['to_id'])
                print(f"  Migrated {min(i+batch_size, len(cites))}/{len(cites)} CITES")

        print("\n--- Migration complete! ---")
        with aura_driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) as count")
            final_count = result.single()["count"]
            print(f"Aura now has {final_count} nodes")

    finally:
        local_driver.close()
        aura_driver.close()


if __name__ == "__main__":
    migrate()
