"""
Neo4j Graph Store - The citation graph database layer.

This module provides:
1. Connection management to Neo4j
2. Schema initialization (constraints, indexes)
3. CRUD operations for nodes and edges
4. Query helpers for common traversal patterns

The graph schema mirrors our Pydantic models:
- Nodes: USCSection, PublicLaw, Bill, CFRSection, Case, Entity, etc.
- Edges: AMENDS, ENACTS, IMPLEMENTS, INTERPRETS, CITES, LOBBIED_ON, etc.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterator

from neo4j import GraphDatabase, Driver, Session, Result
from neo4j.exceptions import ServiceUnavailable

from ..models import (
    USCSection,
    PublicLaw,
    Bill,
    CFRSection,
    Case,
    Entity,
    CommitteeReport,
    Hearing,
    CRSReport,
    LobbyingRecord,
    RFIComment,
    BaseNode,
    BaseEdge,
    AmendsEdge,
    EnactsEdge,
    ImplementsEdge,
    InterpretsEdge,
    CitesEdge,
)


class Neo4jStore:
    """
    Neo4j graph database interface for the legislative citation graph.

    Usage:
        store = Neo4jStore()
        store.connect()

        # Add a USC section
        section = USCSection(citation=USCCitation(title=42, section="1395"), ...)
        store.upsert_node(section)

        # Add a relationship
        edge = AmendsEdge(from_id="Pub. L. 111-148", to_id="42 USC 1395", ...)
        store.upsert_edge(edge)

        # Query
        amendments = store.get_amendments("42 USC 1395")

        store.close()
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        """Initialize with connection parameters (or use env vars)."""
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "password")
        self._driver: Driver | None = None

    def connect(self) -> None:
        """Establish connection to Neo4j."""
        if self._driver is not None:
            return

        self._driver = GraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
        )
        # Verify connectivity
        try:
            self._driver.verify_connectivity()
        except ServiceUnavailable as e:
            raise ConnectionError(
                f"Could not connect to Neo4j at {self.uri}. "
                "Make sure Neo4j is running and credentials are correct."
            ) from e

    def close(self) -> None:
        """Close the connection."""
        if self._driver:
            self._driver.close()
            self._driver = None

    @property
    def driver(self) -> Driver:
        """Get the driver, ensuring connection."""
        if self._driver is None:
            self.connect()
        return self._driver  # type: ignore

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Get a session context manager."""
        session = self.driver.session()
        try:
            yield session
        finally:
            session.close()

    # =========================================================================
    # Schema Management
    # =========================================================================

    def init_schema(self) -> None:
        """
        Initialize the graph schema with constraints and indexes.

        Call this once when setting up a new database.
        """
        with self.session() as session:
            # Node uniqueness constraints (also creates indexes)
            constraints = [
                ("USCSection", "id"),
                ("PublicLaw", "id"),
                ("Bill", "id"),
                ("CFRSection", "id"),
                ("Case", "id"),
                ("Entity", "id"),
                ("CommitteeReport", "id"),
                ("Hearing", "id"),
                ("CRSReport", "id"),
                ("LobbyingRecord", "id"),
                ("RFIComment", "id"),
            ]

            for label, prop in constraints:
                try:
                    session.run(
                        f"CREATE CONSTRAINT {label.lower()}_{prop}_unique "
                        f"IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                    )
                except Exception:
                    # Constraint might already exist
                    pass

            # Additional indexes for common queries
            indexes = [
                ("USCSection", "title"),
                ("USCSection", "section"),
                ("PublicLaw", "congress"),
                ("Bill", "congress"),
                ("Bill", "status"),
                ("Case", "court_level"),
                ("Entity", "entity_type"),
            ]

            for label, prop in indexes:
                try:
                    session.run(
                        f"CREATE INDEX {label.lower()}_{prop}_idx "
                        f"IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
                    )
                except Exception:
                    pass

            # Full-text indexes for search
            try:
                session.run(
                    "CREATE FULLTEXT INDEX usc_text_idx IF NOT EXISTS "
                    "FOR (n:USCSection) ON EACH [n.text, n.section_name]"
                )
            except Exception:
                pass

    def clear_all(self, confirm: bool = False) -> None:
        """
        Delete all nodes and relationships. Requires explicit confirmation.

        USE WITH CAUTION - this deletes everything!
        """
        if not confirm:
            raise ValueError("Must pass confirm=True to clear the database")

        with self.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    # =========================================================================
    # Node Operations
    # =========================================================================

    def upsert_node(self, node: BaseNode) -> None:
        """
        Insert or update a node in the graph.

        Uses MERGE to avoid duplicates based on the node's id.
        """
        label = type(node).__name__
        props = self._node_to_props(node)

        with self.session() as session:
            session.run(
                f"MERGE (n:{label} {{id: $id}}) "
                f"SET n += $props",
                id=node.id,
                props=props,
            )

    def upsert_nodes_batch(self, nodes: list[BaseNode], batch_size: int = 1000) -> int:
        """
        Batch upsert multiple nodes of the same type.

        Returns the number of nodes upserted.
        """
        if not nodes:
            return 0

        label = type(nodes[0]).__name__
        count = 0

        with self.session() as session:
            for i in range(0, len(nodes), batch_size):
                batch = nodes[i : i + batch_size]
                props_list = [{"id": n.id, "props": self._node_to_props(n)} for n in batch]

                session.run(
                    f"UNWIND $batch AS item "
                    f"MERGE (n:{label} {{id: item.id}}) "
                    f"SET n += item.props",
                    batch=props_list,
                )
                count += len(batch)

        return count

    def get_node(self, label: str, node_id: str) -> dict[str, Any] | None:
        """Get a single node by label and id."""
        with self.session() as session:
            result = session.run(
                f"MATCH (n:{label} {{id: $id}}) RETURN n",
                id=node_id,
            )
            record = result.single()
            if record:
                return dict(record["n"])
            return None

    def delete_node(self, label: str, node_id: str) -> bool:
        """Delete a node and all its relationships."""
        with self.session() as session:
            result = session.run(
                f"MATCH (n:{label} {{id: $id}}) DETACH DELETE n RETURN count(n) as deleted",
                id=node_id,
            )
            record = result.single()
            return record["deleted"] > 0 if record else False

    # =========================================================================
    # Edge Operations
    # =========================================================================

    def upsert_edge(self, edge: BaseEdge) -> None:
        """
        Insert or update an edge between two nodes.

        The from_id and to_id should be canonical citation strings that match
        the id property of existing nodes.
        """
        rel_type = edge.relationship_type
        props = self._edge_to_props(edge)

        with self.session() as session:
            # We need to find the nodes by id regardless of their label
            session.run(
                f"MATCH (from {{id: $from_id}}) "
                f"MATCH (to {{id: $to_id}}) "
                f"MERGE (from)-[r:{rel_type}]->(to) "
                f"SET r += $props",
                from_id=edge.from_id,
                to_id=edge.to_id,
                props=props,
            )

    def upsert_edges_batch(self, edges: list[BaseEdge], batch_size: int = 1000) -> int:
        """Batch upsert multiple edges of the same type."""
        if not edges:
            return 0

        rel_type = edges[0].relationship_type
        count = 0

        with self.session() as session:
            for i in range(0, len(edges), batch_size):
                batch = edges[i : i + batch_size]
                edge_data = [
                    {
                        "from_id": e.from_id,
                        "to_id": e.to_id,
                        "props": self._edge_to_props(e),
                    }
                    for e in batch
                ]

                session.run(
                    f"UNWIND $batch AS item "
                    f"MATCH (from {{id: item.from_id}}) "
                    f"MATCH (to {{id: item.to_id}}) "
                    f"MERGE (from)-[r:{rel_type}]->(to) "
                    f"SET r += item.props",
                    batch=edge_data,
                )
                count += len(batch)

        return count

    # =========================================================================
    # Query Helpers - Common Traversal Patterns
    # =========================================================================

    def get_usc_section(self, canonical: str) -> dict[str, Any] | None:
        """Get a USC section by its canonical citation (e.g., '42 USC 1395')."""
        return self.get_node("USCSection", canonical)

    def get_amendments(self, usc_canonical: str) -> list[dict[str, Any]]:
        """
        Get all amendments to a USC section, ordered by date.

        Returns list of {public_law: {...}, amendment: {...}} dicts.
        """
        with self.session() as session:
            result = session.run(
                """
                MATCH (pl:PublicLaw)-[a:AMENDS]->(usc:USCSection {id: $id})
                RETURN pl, a
                ORDER BY a.effective_date
                """,
                id=usc_canonical,
            )
            return [
                {"public_law": dict(r["pl"]), "amendment": dict(r["a"])} for r in result
            ]

    def get_enacting_law(self, usc_canonical: str) -> dict[str, Any] | None:
        """Get the public law that originally enacted a USC section."""
        with self.session() as session:
            result = session.run(
                """
                MATCH (pl:PublicLaw)-[e:ENACTS]->(usc:USCSection {id: $id})
                RETURN pl, e
                """,
                id=usc_canonical,
            )
            record = result.single()
            if record:
                return {"public_law": dict(record["pl"]), "enacts": dict(record["e"])}
            return None

    def get_implementing_regulations(self, usc_canonical: str) -> list[dict[str, Any]]:
        """Get CFR sections that implement a USC section."""
        with self.session() as session:
            result = session.run(
                """
                MATCH (cfr:CFRSection)-[i:IMPLEMENTS]->(usc:USCSection {id: $id})
                RETURN cfr, i
                """,
                id=usc_canonical,
            )
            return [{"cfr": dict(r["cfr"]), "implements": dict(r["i"])} for r in result]

    def get_interpreting_cases(self, usc_canonical: str) -> list[dict[str, Any]]:
        """Get cases that interpret a USC section."""
        with self.session() as session:
            result = session.run(
                """
                MATCH (c:Case)-[i:INTERPRETS]->(usc:USCSection {id: $id})
                RETURN c, i
                ORDER BY c.decided_date DESC
                """,
                id=usc_canonical,
            )
            return [{"case": dict(r["c"]), "interprets": dict(r["i"])} for r in result]

    def get_related_lobbying(self, bill_canonical: str) -> list[dict[str, Any]]:
        """Get lobbying records related to a bill."""
        with self.session() as session:
            result = session.run(
                """
                MATCH (lr:LobbyingRecord)-[l:LOBBIED_ON]->(b:Bill {id: $id})
                RETURN lr, l
                ORDER BY lr.year DESC, lr.amount DESC
                """,
                id=bill_canonical,
            )
            return [{"lobbying": dict(r["lr"]), "lobbied_on": dict(r["l"])} for r in result]

    def get_bill_sponsors(self, bill_canonical: str) -> list[dict[str, Any]]:
        """Get sponsors of a bill."""
        with self.session() as session:
            result = session.run(
                """
                MATCH (e:Entity)-[s:SPONSORED]->(b:Bill {id: $id})
                RETURN e, s
                ORDER BY s.is_primary DESC
                """,
                id=bill_canonical,
            )
            return [{"entity": dict(r["e"]), "sponsored": dict(r["s"])} for r in result]

    def get_full_lineage(self, usc_canonical: str) -> dict[str, Any]:
        """
        Get the complete "story" of a USC section.

        Returns a dict with:
        - section: The USC section itself
        - enacting_law: The law that created it
        - amendments: All amendments in order
        - regulations: CFR sections implementing it
        - cases: Cases interpreting it
        - crs_reports: CRS reports discussing it
        """
        section = self.get_usc_section(usc_canonical)
        if not section:
            return {"error": f"Section {usc_canonical} not found"}

        return {
            "section": section,
            "enacting_law": self.get_enacting_law(usc_canonical),
            "amendments": self.get_amendments(usc_canonical),
            "regulations": self.get_implementing_regulations(usc_canonical),
            "cases": self.get_interpreting_cases(usc_canonical),
        }

    def get_sections_by_title(self, title: int) -> list[dict[str, Any]]:
        """Get all USC sections in a title."""
        with self.session() as session:
            result = session.run(
                """
                MATCH (usc:USCSection)
                WHERE usc.title = $title
                RETURN usc
                ORDER BY usc.section
                """,
                title=title,
            )
            return [dict(r["usc"]) for r in result]

    def search_sections(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Full-text search across USC sections."""
        with self.session() as session:
            result = session.run(
                """
                CALL db.index.fulltext.queryNodes('usc_text_idx', $query)
                YIELD node, score
                RETURN node, score
                ORDER BY score DESC
                LIMIT $limit
                """,
                query=query,
                limit=limit,
            )
            return [{"section": dict(r["node"]), "score": r["score"]} for r in result]

    def get_stats(self) -> dict[str, int]:
        """Get counts of nodes and relationships."""
        with self.session() as session:
            # Node counts
            node_result = session.run(
                """
                MATCH (n)
                RETURN labels(n)[0] as label, count(*) as count
                """
            )
            nodes = {r["label"]: r["count"] for r in node_result}

            # Relationship counts
            rel_result = session.run(
                """
                MATCH ()-[r]->()
                RETURN type(r) as type, count(*) as count
                """
            )
            rels = {r["type"]: r["count"] for r in rel_result}

            return {"nodes": nodes, "relationships": rels}

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _node_to_props(self, node: BaseNode) -> dict[str, Any]:
        """Convert a Pydantic model to Neo4j-compatible properties dict."""
        data = node.model_dump(exclude={"provenance"})

        # Flatten nested models and convert types
        props = {}
        for key, value in data.items():
            if value is None:
                continue
            elif isinstance(value, datetime):
                props[key] = value.isoformat()
            elif isinstance(value, date):
                props[key] = value.isoformat()
            elif isinstance(value, dict):
                # Flatten nested dicts (like citation objects)
                for k, v in value.items():
                    if v is not None:
                        props[f"{key}_{k}"] = v
            elif isinstance(value, list):
                # Neo4j supports lists of primitives
                if value and not isinstance(value[0], dict):
                    props[key] = value
                # Skip lists of dicts (would need different handling)
            else:
                props[key] = value

        # Add provenance as JSON string if needed
        if node.provenance:
            props["source_name"] = node.provenance.source_name
            props["source_url"] = node.provenance.source_url
            props["retrieved_at"] = node.provenance.retrieved_at.isoformat()

        return props

    def _edge_to_props(self, edge: BaseEdge) -> dict[str, Any]:
        """Convert an edge to Neo4j-compatible properties dict."""
        data = edge.model_dump(exclude={"from_id", "to_id", "provenance", "relationship_type"})

        props = {}
        for key, value in data.items():
            if value is None:
                continue
            elif isinstance(value, (datetime, date)):
                props[key] = value.isoformat()
            else:
                props[key] = value

        # Add provenance
        if edge.provenance:
            props["source_name"] = edge.provenance.source_name

        return props


# =============================================================================
# Context Manager Support
# =============================================================================


@contextmanager
def neo4j_store(**kwargs) -> Iterator[Neo4jStore]:
    """Context manager for Neo4jStore."""
    store = Neo4jStore(**kwargs)
    store.connect()
    try:
        yield store
    finally:
        store.close()
