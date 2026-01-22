"""
Narrative API endpoints - LLM-powered content generation.

These endpoints provide rich, contextualized narratives about legislation
using the BillNarrator for LLM generation.
"""
from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / '.env', override=True)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/narrative", tags=["narrative"])

# Cache directory for generated narratives
CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Response Models
# =============================================================================

class ExecutiveSummaryResponse(BaseModel):
    headline: str
    overview: str
    key_provisions: list[str]
    why_it_matters: str
    historical_context: str
    generated_at: str


class PathwayResponse(BaseModel):
    interest: str
    description: str
    start_with: str
    also_see: list[str]


class NavigationGuideResponse(BaseModel):
    pathways: list[PathwayResponse]
    most_amended: list[dict]
    newest: list[dict]
    highlight: str
    generated_at: str


class SectionContextResponse(BaseModel):
    citation: str
    name: str
    plain_english: str
    why_exists: str
    connections: list[str]
    amendment_story: str | None
    generated_at: str


class ChipsNarrativeResponse(BaseModel):
    """Complete CHIPS narrative with all LLM-generated content."""
    executive_summary: ExecutiveSummaryResponse
    navigation: NavigationGuideResponse
    scope: dict
    topic_groups: list[dict]
    timeline: list[dict]
    generated_at: str


# =============================================================================
# Helper Functions
# =============================================================================

def _get_cached(key: str) -> dict | None:
    """Get cached narrative if it exists and is fresh (< 24 hours)."""
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            generated_at = datetime.fromisoformat(data.get("generated_at", "2000-01-01"))
            age_hours = (datetime.now() - generated_at).total_seconds() / 3600
            if age_hours < 24:
                return data
        except Exception as e:
            logger.warning(f"Cache read error for {key}: {e}")
    return None


def _set_cached(key: str, data: dict) -> None:
    """Cache narrative data."""
    cache_file = CACHE_DIR / f"{key}.json"
    try:
        data["generated_at"] = datetime.now().isoformat()
        cache_file.write_text(json.dumps(data, indent=2, default=str))
    except Exception as e:
        logger.warning(f"Cache write error for {key}: {e}")


def _get_narrator():
    """Get or create BillNarrator instance."""
    from ..analysis.bill_narrator import BillNarrator
    return BillNarrator()


def _get_chips_data() -> dict:
    """Get CHIPS data from the graph for narrative generation."""
    from ..graph.neo4j_store import Neo4jStore
    from ..narrative.generator import NarrativeGenerator

    store = Neo4jStore()
    gen = NarrativeGenerator(store)
    chips = gen.generate_chips_story()

    # Extract data for narrator
    topic_breakdown = {}
    topic_groups_raw = []
    for group in chips.by_topic:
        topic_breakdown[group.topic] = len(group.sections)
        topic_groups_raw.append({
            "topic": group.topic,
            "section_count": len(group.sections),
            "sample_sections": [
                {"citation": s["citation"], "name": s["name"]}
                for s in group.sections[:5]
            ],
        })

    # Get most amended sections THAT CHIPS TOUCHED
    # This prevents showing unrelated sections like Medicare/Medicaid that happen to be heavily amended
    most_amended = []
    with store.session() as session:
        result = session.run("""
            MATCH (chips:PublicLaw {id: "Pub. L. 117-167"})-[:AMENDS]->(usc:USCSection)
            OPTIONAL MATCH (usc)<-[r:AMENDS]-(pl:PublicLaw)
            WITH usc, count(r) as amendment_count
            RETURN usc.id as citation, usc.section_name as name, amendment_count
            ORDER BY amendment_count DESC
            LIMIT 10
        """)
        for r in result:
            most_amended.append({
                "citation": r["citation"],
                "name": r["name"],
                "amendment_count": r["amendment_count"],
            })

    # Get newest sections (CHIPS-enacted)
    newest = []
    with store.session() as session:
        result = session.run("""
            MATCH (pl:PublicLaw {id: "Pub. L. 117-167"})-[:ENACTS]->(usc:USCSection)
            RETURN usc.id as citation, usc.section_name as name
            LIMIT 10
        """)
        for r in result:
            newest.append({
                "citation": r["citation"],
                "name": r["name"],
            })

    store.close()

    return {
        "chips_narrative": chips.to_dict(),
        "topic_breakdown": topic_breakdown,
        "topic_groups": topic_groups_raw,
        "most_amended": most_amended,
        "newest": newest,
        "predecessor_laws": [
            {"citation": p.content.split(":")[0] if ":" in p.content else p.content, "title": p.content.split(": ")[1].split(" (")[0] if ": " in p.content else "", "year": ""}
            for p in chips.predecessors
        ],
        "sample_sections": [
            {"citation": s["citation"], "name": s["name"]}
            for group in chips.by_topic
            for s in group.sections[:2]
        ][:10],
    }


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/chips/executive-summary", response_model=ExecutiveSummaryResponse)
async def get_chips_executive_summary(regenerate: bool = False):
    """
    Get LLM-generated executive summary for CHIPS and Science Act.

    This provides a high-level narrative explaining what the law does,
    why it matters, and the historical context.

    The summary is cached for 24 hours to avoid repeated API calls.
    Use regenerate=true to force a fresh generation.
    """
    cache_key = "chips_executive_summary"

    if not regenerate:
        cached = _get_cached(cache_key)
        if cached:
            return ExecutiveSummaryResponse(**cached)

    # Generate fresh summary
    try:
        from ..narrative.generator import CHIPS_FUNDING

        narrator = _get_narrator()
        data = _get_chips_data()

        summary = narrator.generate_executive_summary(
            bill_title="CHIPS and Science Act",
            bill_citation="Pub. L. 117-167",
            enacted_date="August 9, 2022",
            sections_created=144,
            sections_amended=51,
            topic_breakdown=data["topic_breakdown"],
            predecessor_laws=data["predecessor_laws"],
            sample_sections=data["sample_sections"],
            funding_data=CHIPS_FUNDING,
        )

        result = {
            "headline": summary.headline,
            "overview": summary.overview,
            "key_provisions": summary.key_provisions,
            "why_it_matters": summary.why_it_matters,
            "historical_context": summary.historical_context,
            "generated_at": datetime.now().isoformat(),
        }

        _set_cached(cache_key, result)
        return ExecutiveSummaryResponse(**result)

    except Exception as e:
        logger.error(f"Failed to generate executive summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chips/navigation", response_model=NavigationGuideResponse)
async def get_chips_navigation(regenerate: bool = False):
    """
    Get LLM-generated navigation guide for CHIPS and Science Act.

    This provides "start here" guidance based on different interests,
    highlights the most amended sections, and identifies interesting
    threads to explore.
    """
    cache_key = "chips_navigation"

    if not regenerate:
        cached = _get_cached(cache_key)
        if cached:
            return NavigationGuideResponse(**cached)

    try:
        narrator = _get_narrator()
        data = _get_chips_data()

        guide = narrator.generate_navigation_guide(
            bill_title="CHIPS and Science Act",
            topic_groups=data["topic_groups"],
            most_amended_sections=data["most_amended"],
            newest_sections=data["newest"],
        )

        result = {
            "pathways": [
                {
                    "interest": p.interest,
                    "description": p.description,
                    "start_with": p.start_with,
                    "also_see": p.sections,
                }
                for p in guide.pathways
            ],
            "most_amended": guide.most_amended,
            "newest": guide.newest,
            "highlight": guide.highlight,
            "generated_at": datetime.now().isoformat(),
        }

        _set_cached(cache_key, result)
        return NavigationGuideResponse(**result)

    except Exception as e:
        logger.error(f"Failed to generate navigation guide: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chips/full", response_model=ChipsNarrativeResponse)
async def get_chips_full_narrative(regenerate: bool = False):
    """
    Get complete CHIPS narrative with all LLM-generated content.

    This combines the executive summary, navigation guide, and structured
    data into a single comprehensive response suitable for the UI.
    """
    cache_key = "chips_full_narrative"

    if not regenerate:
        cached = _get_cached(cache_key)
        if cached:
            return ChipsNarrativeResponse(**cached)

    try:
        # Get individual components (they may be cached)
        summary = await get_chips_executive_summary(regenerate=regenerate)
        navigation = await get_chips_navigation(regenerate=regenerate)

        # Get structured data
        data = _get_chips_data()
        chips = data["chips_narrative"]

        result = {
            "executive_summary": summary.dict(),
            "navigation": navigation.dict(),
            "scope": {
                "sections_created": 144,
                "sections_amended": 51,
            },
            "topic_groups": data["topic_groups"],
            "timeline": chips.get("timeline", []),
            "generated_at": datetime.now().isoformat(),
        }

        _set_cached(cache_key, result)
        return ChipsNarrativeResponse(**result)

    except Exception as e:
        logger.error(f"Failed to generate full narrative: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/section/{citation:path}", response_model=SectionContextResponse)
async def get_section_context(citation: str, regenerate: bool = False):
    """
    Get LLM-generated context for a specific section.

    This provides a plain-English explanation of what the section does,
    why it exists, and how it connects to other parts of the law.
    """
    # Normalize citation for cache key
    cache_key = f"section_{citation.replace(' ', '_').replace('.', '_')}"

    if not regenerate:
        cached = _get_cached(cache_key)
        if cached:
            return SectionContextResponse(**cached)

    try:
        from ..graph.neo4j_store import Neo4jStore
        from ..services.section_text import get_section_text

        store = Neo4jStore()
        narrator = _get_narrator()

        # Get section data
        section = store.get_usc_section(citation)
        if not section:
            raise HTTPException(status_code=404, detail=f"Section not found: {citation}")

        # Get section text from XML/cache (not stored in Neo4j Aura)
        section_text = section.get("text") or get_section_text(citation) or ""

        # Get amendments
        amendments = []
        with store.session() as session:
            result = session.run("""
                MATCH (pl:PublicLaw)-[r:AMENDS]->(usc:USCSection {id: $id})
                RETURN pl.id as public_law, pl.title as title, pl.enacted_date as date
                ORDER BY pl.enacted_date
            """, id=citation)
            for r in result:
                amendments.append({
                    "public_law": r["public_law"],
                    "title": r["title"],
                    "date": r["date"],
                })

        # Get related sections (same chapter or linked)
        related = []
        with store.session() as session:
            result = session.run("""
                MATCH (usc:USCSection {id: $id})
                MATCH (other:USCSection)
                WHERE other.chapter = usc.chapter AND other.id <> usc.id
                RETURN other.id as citation, other.section_name as name
                LIMIT 5
            """, id=citation)
            for r in result:
                related.append({
                    "citation": r["citation"],
                    "name": r["name"],
                })

        store.close()

        # Generate context
        context = narrator.generate_section_context(
            section_citation=citation,
            section_name=section.get("section_name", ""),
            section_text=section_text,
            amendments=amendments,
            related_sections=related,
        )

        result = {
            "citation": citation,
            "name": section.get("section_name", ""),
            "plain_english": context.plain_english,
            "why_exists": context.why_exists,
            "connections": context.connections,
            "amendment_story": context.amendment_story,
            "generated_at": datetime.now().isoformat(),
        }

        _set_cached(cache_key, result)
        return SectionContextResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate section context for {citation}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
