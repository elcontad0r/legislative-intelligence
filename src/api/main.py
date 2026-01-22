"""
FastAPI application for Legislative Intelligence System.

Provides REST endpoints for:
- Getting the "Story of a Law" for any USC citation
- Searching US Code sections
- Looking up Public Laws and their amendments
- Graph statistics
- CHIPS and Science Act demo UI and narrative

Run: uvicorn src.api.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Union

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..graph.neo4j_store import Neo4jStore
from ..parsers.citations import CitationParser
from .story import StoryOfALaw, LawStory
from ..narrative.generator import NarrativeGenerator, ChipsNarrative, SectionNarrative
from .narrative_endpoints import router as narrative_router

# Path to web templates
WEB_TEMPLATES_DIR = Path(__file__).parent.parent / "web" / "templates"


# Global instances (initialized on startup)
graph_store: Neo4jStore | None = None
story_generator: StoryOfALaw | None = None
citation_parser: CitationParser | None = None
narrative_generator: NarrativeGenerator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - connect on startup, cleanup on shutdown."""
    global graph_store, story_generator, citation_parser, narrative_generator

    # Startup
    graph_store = Neo4jStore()
    graph_store.connect()
    story_generator = StoryOfALaw(graph_store)
    citation_parser = CitationParser()
    narrative_generator = NarrativeGenerator(graph_store)

    yield

    # Shutdown
    if story_generator:
        story_generator.close()
    if narrative_generator:
        narrative_generator.close()


app = FastAPI(
    title="Legislative Intelligence API",
    description="Trace the story of any law - from enactment through amendments, regulations, and court interpretations.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include narrative router with LLM-powered endpoints
app.include_router(narrative_router)


# =============================================================================
# Response Models
# =============================================================================

class CitationInfo(BaseModel):
    """A parsed citation."""
    type: str
    original: str
    canonical: str


class ParseResponse(BaseModel):
    """Response from citation parsing."""
    input_text: str
    citations: list[CitationInfo]


class SectionSummary(BaseModel):
    """Brief info about a USC section."""
    id: str
    section_name: str | None
    title: str | None


class PublicLawSummary(BaseModel):
    """Brief info about a Public Law."""
    id: str
    title: str | None
    enacted_date: str | None
    congress: int | None


class StoryResponse(BaseModel):
    """The Story of a Law response."""
    citation: str
    section_name: str | None
    title_name: str | None
    timeline: list[dict[str, Any]]
    amendments_count: int
    regulations_count: int
    cases_count: int
    markdown: str | None = None


class SearchResult(BaseModel):
    """A search result."""
    id: str
    section_name: str | None
    score: float | None = None
    snippet: str | None = None


class StatsResponse(BaseModel):
    """Database statistics."""
    nodes: dict[str, int]
    relationships: dict[str, int]
    total_nodes: int
    total_relationships: int


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/")
async def root():
    """API info and available endpoints."""
    return {
        "name": "Legislative Intelligence API",
        "version": "0.1.0",
        "endpoints": {
            "/ui": "Web UI for CHIPS demo",
            "/chips": "Get CHIPS and Science Act narrative",
            "/story/{citation}": "Get the story of a law",
            "/search": "Search US Code sections",
            "/parse": "Parse citations from text",
            "/section/{citation}": "Get a specific section",
            "/public-law/{citation}": "Get a Public Law",
            "/stats": "Database statistics",
        },
    }


@app.get("/story/{citation:path}", response_model=StoryResponse)
async def get_story(
    citation: str,
    include_markdown: bool = Query(default=True, description="Include markdown narrative"),
):
    """
    Get the complete story of a law.

    Provide a USC citation like:
    - 42 USC 1395
    - 42 U.S.C. 1395
    - 42 U.S.C. § 1395

    Returns the origin, amendments, regulations, and court cases for the section.
    """
    if not story_generator:
        raise HTTPException(status_code=503, detail="Service not initialized")

    story = story_generator.get_story(citation)
    if not story:
        raise HTTPException(status_code=404, detail=f"Section not found: {citation}")

    return StoryResponse(
        citation=story.citation,
        section_name=story.section_name,
        title_name=story.title_name,
        timeline=[e.to_dict() for e in story.timeline],
        amendments_count=len(story.amendments),
        regulations_count=len(story.regulations),
        cases_count=len(story.cases),
        markdown=story.to_markdown() if include_markdown else None,
    )


@app.get("/search", response_model=list[SearchResult])
async def search_sections(
    q: str = Query(..., description="Search query"),
    limit: int = Query(default=20, le=100, description="Max results"),
):
    """
    Search US Code sections by name or citation.

    Examples:
    - /search?q=semiconductor
    - /search?q=workforce
    - /search?q=42 USC 18911
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Service not initialized")

    with graph_store.session() as session:
        # Search section name and citation (id)
        # Note: section text is not stored in Aura (too large), so we search names only
        result = session.run("""
            MATCH (usc:USCSection)
            WHERE toLower(usc.section_name) CONTAINS toLower($search_term)
               OR toLower(usc.id) CONTAINS toLower($search_term)
            RETURN usc.id as id, usc.section_name as section_name
            ORDER BY usc.id
            LIMIT $max_results
        """, search_term=q, max_results=limit)

        return [
            SearchResult(
                id=r["id"],
                section_name=r["section_name"],
                snippet=None,  # Text not stored in Aura
            )
            for r in result
        ]


@app.post("/parse", response_model=ParseResponse)
async def parse_citations(text: str):
    """
    Parse legal citations from text.

    Extracts and normalizes:
    - USC citations (42 U.S.C. § 1395)
    - Public Law citations (Pub. L. 89-97)
    - Bill citations (H.R. 1234)
    - CFR citations (42 CFR 405.201)
    """
    if not citation_parser:
        raise HTTPException(status_code=503, detail="Service not initialized")

    citations = citation_parser.parse(text)

    return ParseResponse(
        input_text=text,
        citations=[
            CitationInfo(
                type=c.citation_type.name,
                original=c.original,
                canonical=c.canonical,
            )
            for c in citations
        ],
    )


@app.get("/section/{citation:path}", response_model=Union[SectionSummary, dict])
async def get_section(
    citation: str,
    full: bool = Query(default=False, description="Include full text"),
    narrative: bool = Query(default=True, description="Include narrative with amendments and timeline"),
):
    """
    Get a specific USC section.

    Examples:
    - /section/42 USC 1395
    - /section/42 USC 1395?full=true
    - /section/42 USC 1395?narrative=true (default)
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # If narrative is requested, use the narrative generator
    if narrative and narrative_generator:
        section_narrative = narrative_generator.generate_section_story(citation, include_tiers=[1, 2, 3])
        if section_narrative:
            return section_narrative.to_dict()

    # Fallback to basic section lookup
    section = graph_store.get_usc_section(citation)
    if not section:
        # Try normalizing
        if citation_parser:
            parsed = citation_parser.parse(citation)
            for c in parsed:
                if c.citation_type.name == "USC":
                    section = graph_store.get_usc_section(c.canonical)
                    break

    if not section:
        raise HTTPException(status_code=404, detail=f"Section not found: {citation}")

    if full:
        return section

    return SectionSummary(
        id=section.get("id", ""),
        section_name=section.get("section_name"),
        title=section.get("title_name"),
    )


@app.get("/public-law/{citation:path}", response_model=Union[PublicLawSummary, dict])
async def get_public_law(
    citation: str,
    full: bool = Query(default=False, description="Include full details"),
    amendments: bool = Query(default=False, description="Include sections amended"),
):
    """
    Get a Public Law.

    Examples:
    - /public-law/Pub. L. 117-58
    - /public-law/117-58
    - /public-law/Pub. L. 89-97?amendments=true
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Normalize citation
    if not citation.startswith("Pub"):
        citation = f"Pub. L. {citation}"

    with graph_store.session() as session:
        result = session.run("""
            MATCH (pl:PublicLaw {id: $id})
            RETURN pl
        """, id=citation)
        record = result.single()

        if not record:
            raise HTTPException(status_code=404, detail=f"Public Law not found: {citation}")

        pl = dict(record["pl"])

        if amendments:
            # Get sections this law amends
            amend_result = session.run("""
                MATCH (pl:PublicLaw {id: $id})-[r:AMENDS|ENACTS]->(usc:USCSection)
                RETURN type(r) as rel_type, usc.id as section_id, usc.section_name as section_name
            """, id=citation)
            pl["affected_sections"] = [
                {
                    "relationship": r["rel_type"],
                    "section_id": r["section_id"],
                    "section_name": r["section_name"],
                }
                for r in amend_result
            ]

        if full:
            return pl

        return PublicLawSummary(
            id=pl.get("id", ""),
            title=pl.get("title"),
            enacted_date=pl.get("enacted_date"),
            congress=pl.get("congress"),
        )


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get database statistics."""
    if not graph_store:
        raise HTTPException(status_code=503, detail="Service not initialized")

    with graph_store.session() as session:
        # Count nodes by label
        node_result = session.run("""
            MATCH (n)
            WITH labels(n)[0] as label
            RETURN label, count(*) as count
        """)
        nodes = {r["label"]: r["count"] for r in node_result}

        # Count relationships by type
        rel_result = session.run("""
            MATCH ()-[r]->()
            RETURN type(r) as type, count(*) as count
        """)
        relationships = {r["type"]: r["count"] for r in rel_result}

    return StatsResponse(
        nodes=nodes,
        relationships=relationships,
        total_nodes=sum(nodes.values()),
        total_relationships=sum(relationships.values()),
    )


@app.get("/medicare")
async def get_medicare_sections():
    """
    Get all Medicare sections (42 USC 1395+).

    This is a convenience endpoint for the pilot domain.
    """
    if not graph_store:
        raise HTTPException(status_code=503, detail="Service not initialized")

    with graph_store.session() as session:
        result = session.run("""
            MATCH (usc:USCSection)
            WHERE usc.id STARTS WITH "42 USC 1395"
            RETURN usc.id as id, usc.section_name as section_name
            ORDER BY usc.id
        """)

        return {
            "count": 0,  # Will be updated
            "sections": [
                {"id": r["id"], "section_name": r["section_name"]}
                for r in result
            ]
        }


# =============================================================================
# CHIPS Demo Endpoints
# =============================================================================


@app.get("/ui", response_class=HTMLResponse)
async def serve_ui():
    """
    Serve the CHIPS demo web UI.

    This is a single-page application that visualizes the CHIPS and Science Act
    narrative with topics, timeline, and section details.
    """
    template_path = WEB_TEMPLATES_DIR / "index.html"
    if not template_path.exists():
        raise HTTPException(status_code=500, detail="UI template not found")

    return HTMLResponse(content=template_path.read_text())


@app.get("/chips")
async def get_chips_narrative():
    """
    Get the complete CHIPS and Science Act narrative.

    Returns:
        ChipsNarrative as JSON with:
        - Overview and scope statistics
        - Sections created and amended
        - Topic groupings (NSF, DOE, NIST, etc.)
        - Timeline of events
        - Predecessor laws
        - Confidence tier breakdown
    """
    if not narrative_generator:
        raise HTTPException(status_code=503, detail="Narrative generator not initialized")

    chips = narrative_generator.generate_chips_story()
    return chips.to_dict()


@app.get("/section-narrative/{citation:path}")
async def get_section_narrative(
    citation: str,
    tiers: str = Query(default="1,2,3", description="Comma-separated tiers to include"),
):
    """
    Get a detailed narrative for a specific USC section.

    Args:
        citation: USC citation like "42 USC 18851"
        tiers: Which trustworthiness tiers to include (default: 1,2,3)

    Returns:
        SectionNarrative as JSON with origin, amendments, timeline, and confidence breakdown
    """
    if not narrative_generator:
        raise HTTPException(status_code=503, detail="Narrative generator not initialized")

    # Parse tiers
    try:
        include_tiers = [int(t.strip()) for t in tiers.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tiers format")

    narrative = narrative_generator.generate_section_story(citation, include_tiers=include_tiers)
    if not narrative:
        raise HTTPException(status_code=404, detail=f"Section not found: {citation}")

    return narrative.to_dict()


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health")
async def health_check():
    """Check if the service is healthy."""
    healthy = True
    details = {}

    # Check Neo4j connection
    if graph_store:
        try:
            with graph_store.session() as session:
                session.run("RETURN 1")
            details["neo4j"] = "connected"
        except Exception as e:
            details["neo4j"] = f"error: {e}"
            healthy = False
    else:
        details["neo4j"] = "not initialized"
        healthy = False

    return {
        "status": "healthy" if healthy else "unhealthy",
        "details": details,
    }
