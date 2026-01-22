"""
Enhanced Narrative Generator - Composing across all 5 trustworthiness tiers.

This module generates rich, engaging narratives about legislation by combining
data from multiple sources with explicit confidence levels. Each fact in the
narrative is tagged with its tier and appropriate hedging language.

TRUSTWORTHINESS TIERS:
======================
Tier 1 (Definitive): Source credits parsed from USC XML - direct PL citations
                     with enacted dates. These are authoritative and verifiable.

Tier 2 (High): Public Law titles from Congress.gov, official metadata like
               bill numbers, Congress numbers. Highly reliable but could have
               minor transcription issues.

Tier 3 (Medium): Text diff analysis showing what changed between versions.
                 Computed from official sources but represents interpretation.

Tier 4 (Low): LLM-generated summaries explaining what amendments mean in
              plain English. Requires hedging language.

Tier 5 (Speculative): External sources like CRS reports, news articles,
                      lobbying data. Valuable context but not authoritative.

Usage:
    from src.narrative.generator import NarrativeGenerator

    generator = NarrativeGenerator(neo4j_store)

    # Get section story with tiers 1-2 only (no LLM)
    story = generator.generate_section_story("42 USC 18851", include_tiers=[1, 2])

    # Get full CHIPS story
    chips = generator.generate_chips_story()
    print(chips.to_markdown())
"""
from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# Import conditionally to support running without full dependencies
try:
    from ..graph.neo4j_store import Neo4jStore
except ImportError:
    Neo4jStore = None  # type: ignore

try:
    from ..analysis.llm_summarizer import AmendmentSummarizer, SummaryResult
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    AmendmentSummarizer = None  # type: ignore
    SummaryResult = None  # type: ignore

try:
    from ..analysis.text_diff import SectionDiff, DiffResult
    DIFF_AVAILABLE = True
except ImportError:
    DIFF_AVAILABLE = False
    SectionDiff = None  # type: ignore
    DiffResult = None  # type: ignore


# =============================================================================
# Constants
# =============================================================================

CHIPS_PL_CITATION = "Pub. L. 117-167"
CHIPS_ENACTED_DATE = date(2022, 8, 9)
CHIPS_TITLE = "CHIPS and Science Act"

# Known predecessor laws that CHIPS built upon
CHIPS_PREDECESSORS = [
    {"citation": "Pub. L. 111-358", "title": "America COMPETES Reauthorization Act of 2010"},
    {"citation": "Pub. L. 110-69", "title": "America COMPETES Act"},
    {"citation": "Pub. L. 114-329", "title": "American Innovation and Competitiveness Act"},
    {"citation": "Pub. L. 115-368", "title": "National Quantum Initiative Act"},
]

# CHIPS Act funding authorizations (from Pub. L. 117-167)
# These are authorization levels, not appropriations - actual spending requires separate bills
# Note: The $280B figure is often cited but includes authorizations across different timeframes
CHIPS_FUNDING = {
    "total": "$280 billion (five-year authorization, FY2023-2027)",
    "categories": [
        {
            "name": "Semiconductor Manufacturing Incentives",
            "amount": "$52.7 billion",
            "details": "CHIPS for America Fund for domestic fab construction and equipment",
            "section": "Division A, Title I",
        },
        {
            "name": "Semiconductor R&D",
            "amount": "$11 billion",
            "details": "National Semiconductor Technology Center, National Advanced Packaging Manufacturing Program, and NIST metrology R&D",
            "section": "Division A, Title I",
        },
        {
            "name": "NSF Reauthorization",
            "amount": "$81 billion",
            "details": "Five-year authorization for National Science Foundation including new Directorate for Technology, Innovation, and Partnerships (TIP)",
            "section": "Division E",
        },
        {
            "name": "DOE Science Programs",
            "amount": "$67 billion",
            "details": "Five-year authorization for Department of Energy Office of Science research programs",
            "section": "Division B",
        },
        {
            "name": "Regional Innovation Hubs",
            "amount": "$10 billion",
            "details": "Regional Technology and Innovation Hub Program via EDA",
            "section": "Division B, Title VI",
        },
        {
            "name": "STEM Workforce Programs",
            "amount": "$13 billion",
            "details": "STEM education, workforce training, and scholarship programs",
            "section": "Division E, Title III",
        },
        {
            "name": "Wireless Supply Chain Innovation",
            "amount": "$1.5 billion",
            "details": "Public Wireless Supply Chain Innovation Fund",
            "section": "Division A, Title III",
        },
    ],
    "note": "Authorization levels represent spending ceilings; actual appropriations may differ.",
}

# Topic mappings for grouping CHIPS sections
# Keywords are matched against section names (case-insensitive)
# Order matters: more specific topics should come BEFORE general ones
# because the classifier uses first-match
from collections import OrderedDict
TOPIC_KEYWORDS = OrderedDict([
    # Specific topics first
    ("Semiconductors", [
        "semiconductor", "chip", "microelectronics", "fab", "foundry",
        "integrated circuit", "wafer", "supply chain",
    ]),
    ("Cybersecurity", [
        "cybersecurity", "cyber workforce", "cyber education", "software security",
        "authentication", "biometric",
    ]),
    ("Manufacturing", [
        "manufacturing", "manufacturing usa", "domestic production",
        "small business", "advocacy", "assistance",
    ]),
    ("Workforce/Education", [
        "workforce", "education", "training", "fellowship", "scholarship",
        "apprentice", "talent", "skills", "career", "student", "stem",
        "prek", "undergraduate", "graduate", "teacher", "includes",
        "participation", "broadening", "cost-sharing", "sharing",
        "nondiscrimination", "hiring authority", "personnel",
        "presidential awards", "teaching excellence", "award",
    ]),
    ("Security", [
        "security", "defense", "classified", "intelligence",
        "critical infrastructure", "secure data", "controlled information",
        "background screening", "confucius", "foreign influence",
        "concern", "prohibition", "entity of concern",
    ]),
    ("International", [
        "international", "foreign", "export", "ally", "partner",
        "cooperation", "treaty", "agreement", "bilateral",
    ]),
    ("DOE/Energy", [
        "department of energy", "doe", "energy", "laboratory", "national lab",
        "clean energy", "fusion", "nuclear", "renewable", "basic energy",
        "neutron", "scattering", "accelerator", "synchrotron", "helium",
        "applied laboratories", "infrastructure restoration", "modernization",
    ]),
    ("NIST/Standards", [
        "nist", "standards", "metrology", "measurement", "calibration",
    ]),
    ("Funding/Appropriations", [
        "authorization of appropriations", "appropriation",
    ]),
    ("Governance/Administration", [
        "rule of construction", "authorities", "reports", "roadmap",
        "coordination", "administration", "oversight", "inspector general",
        "definitions", "definition", "reporting to congress", "online resource",
        "operation", "maintenance", "reviews", "review", "policy",
        "strategy", "plan", "implementation", "establishment", "purposes",
        "purpose", "requirements", "assistant director", "director", "advisory",
        "committee", "council", "board", "findings", "limitation",
        "responsibilities", "agency",
    ]),
    # General catchall last - this should be broad to catch most remaining sections
    ("NSF/Research", [
        "national science foundation", "nsf", "research", "science",
        "computing", "data service", "capacity building", "assessment",
        "program", "study", "grant", "impact", "impacts", "broader",
        "biological", "field station", "marine laboratory", "iot",
        "agriculture", "precision", "capabilities", "foundation",
        "institutions", "centers", "institute", "activity", "activities",
        "astronomy", "satellite", "constellation", "microgravity", "space",
        "utilization", "modeling", "data", "observatory", "challenges",
        "focus areas", "innovation", "engines", "test bed", "testbed",
        "ethical", "societal", "considerations", "evaluation", "pilot",
        "demonstration", "prototype", "regional", "quantum", "networking",
        "communications",
    ]),
])


# =============================================================================
# Enums and Types
# =============================================================================


class ConfidenceLevel(str, Enum):
    """Confidence levels for narrative facts."""
    DEFINITIVE = "definitive"     # Tier 1 - Direct from authoritative source
    HIGH = "high"                 # Tier 2 - Official metadata, verifiable
    MEDIUM = "medium"             # Tier 3 - Computed/analyzed from official sources
    LOW = "low"                   # Tier 4 - LLM-generated, requires hedging
    SPECULATIVE = "speculative"  # Tier 5 - External sources, context


TIER_TO_CONFIDENCE: dict[int, ConfidenceLevel] = {
    1: ConfidenceLevel.DEFINITIVE,
    2: ConfidenceLevel.HIGH,
    3: ConfidenceLevel.MEDIUM,
    4: ConfidenceLevel.LOW,
    5: ConfidenceLevel.SPECULATIVE,
}

CONFIDENCE_TO_TIER: dict[ConfidenceLevel, int] = {v: k for k, v in TIER_TO_CONFIDENCE.items()}


# =============================================================================
# Output Models
# =============================================================================


class NarrativeFact(BaseModel):
    """
    A single fact within a narrative, tagged with confidence metadata.

    Each fact knows where it came from and how confident we should be in it.
    Facts with lower confidence include hedging language.
    """
    content: str = Field(description="The factual content")
    tier: int = Field(ge=1, le=5, description="Trustworthiness tier (1=highest, 5=lowest)")
    confidence: ConfidenceLevel = Field(description="Confidence level for this fact")
    source: str = Field(description="Where this fact came from")
    hedging: str | None = Field(
        default=None,
        description="Hedging language to use when presenting this fact"
    )

    @classmethod
    def from_tier(
        cls,
        content: str,
        tier: int,
        source: str,
        hedging: str | None = None
    ) -> "NarrativeFact":
        """Create a fact with confidence derived from tier."""
        confidence = TIER_TO_CONFIDENCE.get(tier, ConfidenceLevel.SPECULATIVE)

        # Auto-generate hedging for lower tiers
        if hedging is None and tier >= 4:
            if tier == 4:
                hedging = "Based on text analysis"
            elif tier == 5:
                hedging = "According to external sources"

        return cls(
            content=content,
            tier=tier,
            confidence=confidence,
            source=source,
            hedging=hedging,
        )

    def to_prose(self, include_hedging: bool = True) -> str:
        """Convert to readable prose, optionally with hedging."""
        if include_hedging and self.hedging:
            return f"{self.hedging}: {self.content}"
        return self.content

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "content": self.content,
            "tier": self.tier,
            "confidence": self.confidence.value,
            "source": self.source,
            "hedging": self.hedging,
        }


class TimelineEntry(BaseModel):
    """A single entry in a chronological timeline."""
    date: date | None
    event_type: str  # "enacted", "amended", "interpreted", etc.
    title: str
    description: NarrativeFact
    citation: str | None = None
    source_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat() if self.date else None,
            "event_type": self.event_type,
            "title": self.title,
            "description": self.description.to_dict(),
            "citation": self.citation,
            "source_url": self.source_url,
        }


class AmendmentNarrative(BaseModel):
    """Narrative description of a single amendment."""
    public_law: NarrativeFact  # Citation + optional title
    date: NarrativeFact  # When the amendment took effect
    description: NarrativeFact | None = None  # What it did (may be LLM-generated)
    key_changes: list[NarrativeFact] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "public_law": self.public_law.to_dict(),
            "date": self.date.to_dict(),
            "description": self.description.to_dict() if self.description else None,
            "key_changes": [c.to_dict() for c in self.key_changes],
        }

    def to_markdown(self) -> str:
        """Render as markdown."""
        lines = []
        date_str = self.date.content if self.date else "Date unknown"
        lines.append(f"**{date_str}**: {self.public_law.content}")

        if self.description:
            desc = self.description.to_prose(include_hedging=True)
            lines.append(f"  - {desc}")

        for change in self.key_changes:
            lines.append(f"  - {change.to_prose()}")

        return "\n".join(lines)


class SectionNarrative(BaseModel):
    """Complete narrative for a USC section."""
    citation: str
    section_name: str | None = None
    summary: str  # 1-2 sentence overview
    origin: NarrativeFact  # When/how enacted
    amendments: list[AmendmentNarrative] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    full_text: str | None = None
    confidence_breakdown: dict[int, int] = Field(
        default_factory=dict,
        description="Count of facts by tier"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "section_name": self.section_name,
            "summary": self.summary,
            "origin": self.origin.to_dict(),
            "amendments": [a.to_dict() for a in self.amendments],
            "timeline": [t.to_dict() for t in self.timeline],
            "full_text": self.full_text,
            "confidence_breakdown": self.confidence_breakdown,
        }

    def to_markdown(self) -> str:
        """Render as readable markdown narrative."""
        lines = []

        # Header
        lines.append(f"# {self.citation}")
        if self.section_name:
            lines.append(f"## {self.section_name}")
        lines.append("")

        # Summary
        lines.append(self.summary)
        lines.append("")

        # Origin
        lines.append("### Origin")
        lines.append(self.origin.to_prose())
        lines.append("")

        # Amendments
        if self.amendments:
            lines.append(f"### Legislative History ({len(self.amendments)} amendments)")
            lines.append("")
            for amend in self.amendments:
                lines.append(amend.to_markdown())
                lines.append("")

        # Timeline
        if self.timeline:
            lines.append("### Timeline")
            lines.append("")
            for entry in sorted(self.timeline, key=lambda e: e.date or date.min):
                date_str = entry.date.strftime("%B %d, %Y") if entry.date else "Date unknown"
                lines.append(f"- **{date_str}**: {entry.title}")
                if entry.description:
                    lines.append(f"  - {entry.description.to_prose()}")
            lines.append("")

        # Confidence breakdown
        lines.append("---")
        lines.append("*Confidence breakdown:*")
        for tier in sorted(self.confidence_breakdown.keys()):
            count = self.confidence_breakdown[tier]
            conf = TIER_TO_CONFIDENCE[tier].value
            lines.append(f"- Tier {tier} ({conf}): {count} facts")

        return "\n".join(lines)

    def to_html(self) -> str:
        """Render as basic HTML."""
        # Convert markdown to simple HTML
        md = self.to_markdown()

        # Simple conversions
        html = md
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        html = re.sub(r'(<li>.*</li>\n)+', r'<ul>\g<0></ul>', html)
        html = html.replace('\n\n', '</p><p>')
        html = f'<div class="section-narrative"><p>{html}</p></div>'

        return html


class TopicGroup(BaseModel):
    """A group of sections organized by topic."""
    topic: str
    description: str | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)
    section_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "description": self.description,
            "sections": self.sections,
            "section_count": self.section_count,
        }


class LawNarrative(BaseModel):
    """Complete narrative for a Public Law - what it created and amended."""
    citation: str
    title: NarrativeFact | None = None
    enacted_date: NarrativeFact | None = None
    overview: str
    sections_created: list[NarrativeFact] = Field(default_factory=list)
    sections_amended: list[NarrativeFact] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    confidence_breakdown: dict[int, int] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "title": self.title.to_dict() if self.title else None,
            "enacted_date": self.enacted_date.to_dict() if self.enacted_date else None,
            "overview": self.overview,
            "sections_created": [s.to_dict() for s in self.sections_created],
            "sections_amended": [s.to_dict() for s in self.sections_amended],
            "timeline": [t.to_dict() for t in self.timeline],
            "confidence_breakdown": self.confidence_breakdown,
        }

    def to_markdown(self) -> str:
        lines = []

        # Header
        lines.append(f"# {self.citation}")
        if self.title:
            lines.append(f"## {self.title.content}")
        lines.append("")

        # Overview
        lines.append(self.overview)
        lines.append("")

        # Enacted date
        if self.enacted_date:
            lines.append(f"**Enacted**: {self.enacted_date.content}")
            lines.append("")

        # Sections created
        if self.sections_created:
            lines.append(f"### Sections Created ({len(self.sections_created)})")
            for sec in self.sections_created[:20]:  # Limit display
                lines.append(f"- {sec.content}")
            if len(self.sections_created) > 20:
                lines.append(f"- *...and {len(self.sections_created) - 20} more*")
            lines.append("")

        # Sections amended
        if self.sections_amended:
            lines.append(f"### Sections Amended ({len(self.sections_amended)})")
            for sec in self.sections_amended[:20]:
                lines.append(f"- {sec.content}")
            if len(self.sections_amended) > 20:
                lines.append(f"- *...and {len(self.sections_amended) - 20} more*")
            lines.append("")

        return "\n".join(lines)

    def to_html(self) -> str:
        md = self.to_markdown()
        html = md
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        return f'<div class="law-narrative">{html}</div>'


class ChipsNarrative(BaseModel):
    """
    Special narrative structure for the CHIPS and Science Act POC demo.

    This provides a comprehensive view of CHIPS: what it created, what it amended,
    its predecessor laws, and organization by topic.
    """
    citation: str = CHIPS_PL_CITATION
    title: str = CHIPS_TITLE
    enacted_date: date = CHIPS_ENACTED_DATE
    overview: str
    scope: NarrativeFact  # "Created X sections, amended Y sections"
    predecessors: list[NarrativeFact] = Field(default_factory=list)
    by_topic: list[TopicGroup] = Field(default_factory=list)
    sections_created: list[dict[str, Any]] = Field(default_factory=list)
    sections_amended: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    confidence_breakdown: dict[int, int] = Field(default_factory=dict)
    learn_more: list[dict[str, str]] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "title": self.title,
            "enacted_date": self.enacted_date.isoformat(),
            "overview": self.overview,
            "scope": self.scope.to_dict(),
            "predecessors": [p.to_dict() for p in self.predecessors],
            "by_topic": [t.to_dict() for t in self.by_topic],
            "sections_created": self.sections_created,
            "sections_amended": self.sections_amended,
            "timeline": [t.to_dict() for t in self.timeline],
            "confidence_breakdown": self.confidence_breakdown,
            "learn_more": self.learn_more,
        }

    def to_markdown(self) -> str:
        lines = []

        # Header
        lines.append(f"# {self.title}")
        lines.append(f"## {self.citation}")
        lines.append("")

        # Overview
        lines.append(self.overview)
        lines.append("")

        # Key facts
        lines.append(f"**Enacted**: {self.enacted_date.strftime('%B %d, %Y')}")
        lines.append(f"**Scope**: {self.scope.content}")
        lines.append("")

        # Predecessors
        if self.predecessors:
            lines.append("### Built Upon")
            lines.append("")
            lines.append("The CHIPS and Science Act builds upon decades of science policy:")
            for pred in self.predecessors:
                lines.append(f"- {pred.content}")
            lines.append("")

        # By topic
        if self.by_topic:
            lines.append("### By Topic")
            lines.append("")
            for topic_group in self.by_topic:
                lines.append(f"#### {topic_group.topic} ({topic_group.section_count} sections)")
                if topic_group.description:
                    lines.append(f"_{topic_group.description}_")
                for sec in topic_group.sections[:5]:
                    citation = sec.get("citation", "Unknown")
                    name = sec.get("name", "")
                    if name:
                        lines.append(f"- **{citation}**: {name}")
                    else:
                        lines.append(f"- {citation}")
                if topic_group.section_count > 5:
                    lines.append(f"- *...and {topic_group.section_count - 5} more*")
                lines.append("")

        # Timeline
        if self.timeline:
            lines.append("### Timeline")
            lines.append("")
            for entry in sorted(self.timeline, key=lambda e: e.date or date.min):
                date_str = entry.date.strftime("%B %d, %Y") if entry.date else "Date unknown"
                lines.append(f"- **{date_str}**: {entry.title}")
            lines.append("")

        # Learn more
        if self.learn_more:
            lines.append("### Learn More")
            lines.append("")
            for link in self.learn_more:
                lines.append(f"- [{link['title']}]({link['url']})")
            lines.append("")

        # Confidence breakdown
        lines.append("---")
        lines.append("*Data confidence breakdown:*")
        for tier in sorted(self.confidence_breakdown.keys()):
            count = self.confidence_breakdown[tier]
            conf = TIER_TO_CONFIDENCE[tier].value
            lines.append(f"- Tier {tier} ({conf}): {count} facts")

        return "\n".join(lines)

    def to_html(self) -> str:
        """Render as structured HTML suitable for web display."""
        lines = []
        lines.append('<div class="chips-narrative">')

        # Header
        lines.append(f'<header>')
        lines.append(f'<h1>{self.title}</h1>')
        lines.append(f'<h2 class="citation">{self.citation}</h2>')
        lines.append(f'</header>')

        # Overview section
        lines.append('<section class="overview">')
        lines.append(f'<p class="lead">{self.overview}</p>')
        lines.append(f'<p><strong>Enacted:</strong> {self.enacted_date.strftime("%B %d, %Y")}</p>')
        lines.append(f'<p><strong>Scope:</strong> {self.scope.content}</p>')
        lines.append('</section>')

        # Predecessors
        if self.predecessors:
            lines.append('<section class="predecessors">')
            lines.append('<h3>Built Upon</h3>')
            lines.append('<p>The CHIPS and Science Act builds upon decades of science policy:</p>')
            lines.append('<ul>')
            for pred in self.predecessors:
                lines.append(f'<li>{pred.content}</li>')
            lines.append('</ul>')
            lines.append('</section>')

        # By topic
        if self.by_topic:
            lines.append('<section class="by-topic">')
            lines.append('<h3>Sections by Topic</h3>')
            for topic_group in self.by_topic:
                lines.append(f'<div class="topic-group">')
                lines.append(f'<h4>{topic_group.topic} <span class="count">({topic_group.section_count} sections)</span></h4>')
                if topic_group.description:
                    lines.append(f'<p class="description">{topic_group.description}</p>')
                lines.append('<ul>')
                for sec in topic_group.sections[:5]:
                    citation = sec.get("citation", "Unknown")
                    name = sec.get("name", "")
                    if name:
                        lines.append(f'<li><strong>{citation}</strong>: {name}</li>')
                    else:
                        lines.append(f'<li>{citation}</li>')
                if topic_group.section_count > 5:
                    lines.append(f'<li class="more">...and {topic_group.section_count - 5} more</li>')
                lines.append('</ul>')
                lines.append('</div>')
            lines.append('</section>')

        # Timeline
        if self.timeline:
            lines.append('<section class="timeline">')
            lines.append('<h3>Timeline</h3>')
            lines.append('<ul class="timeline-list">')
            for entry in sorted(self.timeline, key=lambda e: e.date or date.min):
                date_str = entry.date.strftime("%B %d, %Y") if entry.date else "Date unknown"
                lines.append(f'<li><time>{date_str}</time> {entry.title}</li>')
            lines.append('</ul>')
            lines.append('</section>')

        # Learn more
        if self.learn_more:
            lines.append('<section class="learn-more">')
            lines.append('<h3>Learn More</h3>')
            lines.append('<ul>')
            for link in self.learn_more:
                lines.append(f'<li><a href="{link["url"]}" target="_blank">{link["title"]}</a></li>')
            lines.append('</ul>')
            lines.append('</section>')

        # Confidence footer
        lines.append('<footer class="confidence-breakdown">')
        lines.append('<p><em>Data confidence breakdown:</em></p>')
        lines.append('<ul>')
        for tier in sorted(self.confidence_breakdown.keys()):
            count = self.confidence_breakdown[tier]
            conf = TIER_TO_CONFIDENCE[tier].value
            lines.append(f'<li>Tier {tier} ({conf}): {count} facts</li>')
        lines.append('</ul>')
        lines.append('</footer>')

        lines.append('</div>')

        return "\n".join(lines)


# =============================================================================
# Main Generator Class
# =============================================================================


class NarrativeGenerator:
    """
    Generates rich narratives with explicit confidence tiers.

    This class queries the Neo4j graph for legislative data and composes
    human-readable narratives that clearly indicate the confidence level
    of each piece of information.

    Usage:
        generator = NarrativeGenerator(neo4j_store)

        # Generate section story (tiers 1-2 only, no LLM)
        story = generator.generate_section_story("42 USC 18851", include_tiers=[1, 2])

        # Generate law story
        law_story = generator.generate_law_story("Pub. L. 117-167")

        # Generate CHIPS demo story
        chips = generator.generate_chips_story()
    """

    def __init__(
        self,
        neo4j_store: "Neo4jStore",
        llm_summarizer: "AmendmentSummarizer | None" = None,
    ):
        """
        Initialize the narrative generator.

        Args:
            neo4j_store: Connected Neo4j store instance
            llm_summarizer: Optional LLM summarizer for Tier 4 content.
                           If not provided, Tier 4 content will be skipped.
        """
        self.graph = neo4j_store
        self.llm = llm_summarizer
        self._confidence_counts: dict[int, int] = {}

    def _reset_confidence_counts(self) -> None:
        """Reset confidence tracking for a new narrative."""
        self._confidence_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    def _track_fact(self, fact: NarrativeFact) -> NarrativeFact:
        """Track a fact's tier for confidence breakdown."""
        self._confidence_counts[fact.tier] = self._confidence_counts.get(fact.tier, 0) + 1
        return fact

    def _get_confidence_breakdown(self) -> dict[int, int]:
        """Get the current confidence breakdown, excluding zeros."""
        return {k: v for k, v in self._confidence_counts.items() if v > 0}

    def close(self) -> None:
        """Clean up resources."""
        if hasattr(self.graph, 'close'):
            self.graph.close()

    # =========================================================================
    # Section Story Generation
    # =========================================================================

    def generate_section_story(
        self,
        citation: str,
        include_tiers: list[int] | None = None,
    ) -> SectionNarrative | None:
        """
        Generate a narrative for a USC section.

        Args:
            citation: USC citation like "42 USC 18851"
            include_tiers: Which tiers to include (default: [1, 2, 3]).
                          Tier 4 (LLM) requires llm_summarizer to be set.

        Returns:
            SectionNarrative or None if section not found
        """
        if include_tiers is None:
            include_tiers = [1, 2, 3]

        self._reset_confidence_counts()

        # Get section from graph
        section = self.graph.get_usc_section(citation)
        if not section:
            return None

        section_name = section.get("section_name")
        full_text = section.get("text")

        # Build origin fact (Tier 1 if from source_credit, Tier 2 otherwise)
        origin = self._build_origin_fact(citation, section)

        # Build amendment narratives
        amendments = self._build_amendment_narratives(citation, include_tiers)

        # Build timeline
        timeline = self._build_section_timeline(citation, section, amendments)

        # Generate summary
        summary = self._generate_section_summary(citation, section_name, origin, len(amendments))

        return SectionNarrative(
            citation=citation,
            section_name=section_name,
            summary=summary,
            origin=origin,
            amendments=amendments,
            timeline=timeline,
            full_text=full_text if 1 in include_tiers else None,
            confidence_breakdown=self._get_confidence_breakdown(),
        )

    def _build_origin_fact(self, citation: str, section: dict) -> NarrativeFact:
        """Build the origin fact for a section."""
        enacting = self.graph.get_enacting_law(citation)

        if enacting:
            pl = enacting.get("public_law", {})
            pl_id = pl.get("id", "Unknown")
            pl_title = pl.get("title", "")
            enacted_date = pl.get("enacted_date")

            content_parts = [f"Enacted by {pl_id}"]
            if pl_title:
                content_parts.append(f"({pl_title})")
            if enacted_date:
                try:
                    date_obj = date.fromisoformat(enacted_date)
                    content_parts.append(f"on {date_obj.strftime('%B %d, %Y')}")
                except (ValueError, TypeError):
                    pass

            content = " ".join(content_parts)

            # Tier 1 if we have the date from source_credit, Tier 2 otherwise
            tier = 1 if enacted_date else 2
            return self._track_fact(NarrativeFact.from_tier(
                content=content,
                tier=tier,
                source="Neo4j ENACTS relationship"
            ))

        # Fallback: no enacting law found
        return self._track_fact(NarrativeFact.from_tier(
            content="Origin information not available",
            tier=2,
            source="Neo4j query (no ENACTS found)"
        ))

    def _build_amendment_narratives(
        self,
        citation: str,
        include_tiers: list[int],
    ) -> list[AmendmentNarrative]:
        """Build amendment narratives for a section."""
        amendments_data = self.graph.get_amendments(citation)
        narratives = []

        for amend_data in amendments_data:
            pl = amend_data.get("public_law", {})
            amend_info = amend_data.get("amendment", {})

            # Public law fact (Tier 1 for citation, Tier 2 for title)
            pl_id = pl.get("id", "Unknown")
            pl_title = pl.get("title")

            if pl_title:
                pl_content = f"{pl_id} - {pl_title}"
                pl_tier = 2  # Title comes from Congress.gov
            else:
                pl_content = pl_id
                pl_tier = 1  # Just the citation from source_credit

            pl_fact = self._track_fact(NarrativeFact.from_tier(
                content=pl_content,
                tier=pl_tier,
                source="PublicLaw node"
            ))

            # Date fact (Tier 1 from source_credit)
            effective_date = amend_info.get("effective_date") or pl.get("enacted_date")
            if effective_date:
                try:
                    date_obj = date.fromisoformat(effective_date)
                    date_content = date_obj.strftime("%B %d, %Y")
                except (ValueError, TypeError):
                    date_content = effective_date
            else:
                date_content = "Date unknown"

            date_fact = self._track_fact(NarrativeFact.from_tier(
                content=date_content,
                tier=1 if effective_date else 2,
                source="AMENDS relationship"
            ))

            # Description fact (Tier 3 for diff, Tier 4 for LLM)
            description = None
            key_changes: list[NarrativeFact] = []

            if 3 in include_tiers:
                # Try to get amendment description from edge
                amend_desc = amend_info.get("amendment_description")
                if amend_desc:
                    description = self._track_fact(NarrativeFact.from_tier(
                        content=amend_desc,
                        tier=3,
                        source="Amendment edge description",
                        hedging="Based on amendment text"
                    ))

            if 4 in include_tiers and self.llm and description is None:
                # TODO: Generate LLM summary if we have diff data
                # This would require text diff capability
                pass

            narratives.append(AmendmentNarrative(
                public_law=pl_fact,
                date=date_fact,
                description=description,
                key_changes=key_changes,
            ))

        return narratives

    def _build_section_timeline(
        self,
        citation: str,
        section: dict,
        amendments: list[AmendmentNarrative],
    ) -> list[TimelineEntry]:
        """Build a chronological timeline for a section."""
        entries = []

        # Enactment event
        enacting = self.graph.get_enacting_law(citation)
        if enacting:
            pl = enacting.get("public_law", {})
            enacted_date = pl.get("enacted_date")
            if enacted_date:
                try:
                    date_obj = date.fromisoformat(enacted_date)
                except (ValueError, TypeError):
                    date_obj = None
            else:
                date_obj = None

            entries.append(TimelineEntry(
                date=date_obj,
                event_type="enacted",
                title=f"Enacted by {pl.get('id', 'Unknown')}",
                description=self._track_fact(NarrativeFact.from_tier(
                    content=pl.get("title", "Section created"),
                    tier=1 if enacted_date else 2,
                    source="ENACTS relationship"
                )),
                citation=pl.get("id"),
            ))

        # Amendment events
        for amend in amendments:
            try:
                date_obj = datetime.strptime(amend.date.content, "%B %d, %Y").date()
            except (ValueError, TypeError):
                date_obj = None

            entries.append(TimelineEntry(
                date=date_obj,
                event_type="amended",
                title=f"Amended by {amend.public_law.content.split(' - ')[0]}",
                description=amend.description or amend.public_law,
                citation=amend.public_law.content.split(" - ")[0],
            ))

        return sorted(entries, key=lambda e: e.date or date.min)

    def _generate_section_summary(
        self,
        citation: str,
        section_name: str | None,
        origin: NarrativeFact,
        amendment_count: int,
    ) -> str:
        """Generate a 1-2 sentence summary for a section."""
        parts = []

        if section_name:
            parts.append(f"{citation} ({section_name})")
        else:
            parts.append(citation)

        # Add origin info
        if "Enacted by" in origin.content:
            parts.append(origin.content.lower().replace("enacted", "was enacted"))
        else:
            parts.append("is a section of the United States Code")

        summary = " ".join(parts) + "."

        if amendment_count > 0:
            summary += f" It has been amended {amendment_count} time{'s' if amendment_count != 1 else ''}."

        return summary

    # =========================================================================
    # Law Story Generation
    # =========================================================================

    def generate_law_story(self, pl_citation: str) -> LawNarrative | None:
        """
        Generate a narrative for a Public Law - what it created and amended.

        Args:
            pl_citation: Public Law citation like "Pub. L. 117-167"

        Returns:
            LawNarrative or None if law not found
        """
        self._reset_confidence_counts()

        # Get the law from graph
        law = self.graph.get_node("PublicLaw", pl_citation)
        if not law:
            return None

        # Build title fact
        title_content = law.get("title")
        title_fact = None
        if title_content:
            title_fact = self._track_fact(NarrativeFact.from_tier(
                content=title_content,
                tier=2,
                source="Congress.gov"
            ))

        # Build enacted date fact
        enacted_date = law.get("enacted_date")
        enacted_fact = None
        if enacted_date:
            try:
                date_obj = date.fromisoformat(enacted_date)
                date_content = date_obj.strftime("%B %d, %Y")
            except (ValueError, TypeError):
                date_content = enacted_date

            enacted_fact = self._track_fact(NarrativeFact.from_tier(
                content=date_content,
                tier=1,
                source="Source credits"
            ))

        # Query for sections created/amended by this law
        sections_created = self._get_sections_created_by_law(pl_citation)
        sections_amended = self._get_sections_amended_by_law(pl_citation)

        # Build overview
        overview = self._build_law_overview(
            pl_citation, title_content, enacted_fact,
            len(sections_created), len(sections_amended)
        )

        # Build timeline
        timeline = self._build_law_timeline(pl_citation, law, sections_created, sections_amended)

        return LawNarrative(
            citation=pl_citation,
            title=title_fact,
            enacted_date=enacted_fact,
            overview=overview,
            sections_created=[
                self._track_fact(NarrativeFact.from_tier(
                    content=f"{s['id']}" + (f" - {s.get('section_name', '')}" if s.get('section_name') else ""),
                    tier=1,
                    source="ENACTS relationship"
                ))
                for s in sections_created
            ],
            sections_amended=[
                self._track_fact(NarrativeFact.from_tier(
                    content=f"{s['id']}" + (f" - {s.get('section_name', '')}" if s.get('section_name') else ""),
                    tier=1,
                    source="AMENDS relationship"
                ))
                for s in sections_amended
            ],
            timeline=timeline,
            confidence_breakdown=self._get_confidence_breakdown(),
        )

    def _get_sections_created_by_law(self, pl_citation: str) -> list[dict]:
        """Get USC sections created by a law."""
        with self.graph.session() as session:
            result = session.run(
                """
                MATCH (pl:PublicLaw {id: $pl_id})-[:ENACTS]->(usc:USCSection)
                RETURN usc
                ORDER BY usc.id
                """,
                pl_id=pl_citation,
            )
            return [dict(r["usc"]) for r in result]

    def _get_sections_amended_by_law(self, pl_citation: str) -> list[dict]:
        """Get USC sections amended by a law."""
        with self.graph.session() as session:
            result = session.run(
                """
                MATCH (pl:PublicLaw {id: $pl_id})-[:AMENDS]->(usc:USCSection)
                RETURN DISTINCT usc
                ORDER BY usc.id
                """,
                pl_id=pl_citation,
            )
            return [dict(r["usc"]) for r in result]

    def _build_law_overview(
        self,
        pl_citation: str,
        title: str | None,
        enacted_fact: NarrativeFact | None,
        created_count: int,
        amended_count: int,
    ) -> str:
        """Build overview paragraph for a law."""
        parts = []

        if title:
            parts.append(f"The {title} ({pl_citation})")
        else:
            parts.append(f"{pl_citation}")

        if enacted_fact:
            parts.append(f"was enacted on {enacted_fact.content}")
        else:
            parts.append("is a federal law")

        overview = " ".join(parts) + "."

        if created_count > 0 or amended_count > 0:
            scope_parts = []
            if created_count > 0:
                scope_parts.append(f"created {created_count} new section{'s' if created_count != 1 else ''}")
            if amended_count > 0:
                scope_parts.append(f"amended {amended_count} existing section{'s' if amended_count != 1 else ''}")

            overview += f" This law {' and '.join(scope_parts)} of the United States Code."

        return overview

    def _build_law_timeline(
        self,
        pl_citation: str,
        law: dict,
        sections_created: list[dict],
        sections_amended: list[dict],
    ) -> list[TimelineEntry]:
        """Build timeline for a law."""
        entries = []

        enacted_date = law.get("enacted_date")
        if enacted_date:
            try:
                date_obj = date.fromisoformat(enacted_date)
            except (ValueError, TypeError):
                date_obj = None

            entries.append(TimelineEntry(
                date=date_obj,
                event_type="enacted",
                title=f"{pl_citation} enacted",
                description=self._track_fact(NarrativeFact.from_tier(
                    content=law.get("title", "Became law"),
                    tier=1,
                    source="Source credits"
                )),
                citation=pl_citation,
            ))

        return entries

    # =========================================================================
    # CHIPS Story Generation
    # =========================================================================

    def generate_chips_story(self) -> ChipsNarrative:
        """
        Generate the comprehensive CHIPS and Science Act narrative.

        This is the key method for the POC demo, showing:
        - Overview of what CHIPS did
        - Full scope: sections created and amended
        - Historical context: predecessor laws
        - Organization by topic (NSF, DOE, NIST, etc.)
        - Chronological timeline
        """
        self._reset_confidence_counts()

        # Get sections created and amended by CHIPS
        sections_created = self._get_sections_created_by_law(CHIPS_PL_CITATION)
        sections_amended = self._get_sections_amended_by_law(CHIPS_PL_CITATION)

        # Build scope fact
        scope_content = f"Created {len(sections_created)} new sections, amended {len(sections_amended)} existing sections"
        scope = self._track_fact(NarrativeFact.from_tier(
            content=scope_content,
            tier=1,
            source="Neo4j ENACTS/AMENDS relationships"
        ))

        # Build overview
        overview = (
            f"The {CHIPS_TITLE} ({CHIPS_PL_CITATION}) was enacted on "
            f"{CHIPS_ENACTED_DATE.strftime('%B %d, %Y')}. It represents a historic investment in "
            f"American semiconductor manufacturing, scientific research, and STEM workforce development. "
            f"The law authorizes over $280 billion in funding over the next decade."
        )

        # Build predecessor facts
        predecessors = self._build_predecessor_facts()

        # Group sections by topic
        by_topic = self._group_sections_by_topic(sections_created + sections_amended)

        # Build timeline
        timeline = self._build_chips_timeline(sections_created, sections_amended)

        # Build learn more links
        learn_more = [
            {
                "title": "Congress.gov - CHIPS and Science Act",
                "url": "https://www.congress.gov/bill/117th-congress/house-bill/4346"
            },
            {
                "title": "CRS Report: CHIPS Act FAQ",
                "url": "https://crsreports.congress.gov/product/pdf/R/R47523"
            },
            {
                "title": "NSF CHIPS Portal",
                "url": "https://www.nsf.gov/chips"
            },
            {
                "title": "Commerce CHIPS Office",
                "url": "https://www.commerce.gov/chips"
            },
        ]

        return ChipsNarrative(
            overview=overview,
            scope=scope,
            predecessors=predecessors,
            by_topic=by_topic,
            sections_created=[
                {
                    "citation": s["id"],
                    "name": s.get("section_name", ""),
                    "title": s.get("title"),
                }
                for s in sections_created
            ],
            sections_amended=[
                {
                    "citation": s["id"],
                    "name": s.get("section_name", ""),
                    "title": s.get("title"),
                }
                for s in sections_amended
            ],
            timeline=timeline,
            confidence_breakdown=self._get_confidence_breakdown(),
            learn_more=learn_more,
        )

    def _build_predecessor_facts(self) -> list[NarrativeFact]:
        """Build facts about CHIPS predecessor laws."""
        facts = []

        for pred in CHIPS_PREDECESSORS:
            # Check if we have this law in the graph
            law = self.graph.get_node("PublicLaw", pred["citation"])

            if law:
                # We have graph data - Tier 1
                enacted = law.get("enacted_date", "")
                if enacted:
                    try:
                        date_obj = date.fromisoformat(enacted)
                        year = date_obj.year
                    except (ValueError, TypeError):
                        year = ""
                else:
                    year = ""

                content = f"{pred['citation']}: {pred['title']}"
                if year:
                    content += f" ({year})"

                facts.append(self._track_fact(NarrativeFact.from_tier(
                    content=content,
                    tier=1,
                    source="PublicLaw node in graph"
                )))
            else:
                # Using hardcoded data - Tier 5
                facts.append(self._track_fact(NarrativeFact.from_tier(
                    content=f"{pred['citation']}: {pred['title']}",
                    tier=5,
                    source="Curated external reference",
                    hedging="Historical context"
                )))

        return facts

    def _group_sections_by_topic(self, sections: list[dict]) -> list[TopicGroup]:
        """Group sections by topic based on keywords in names."""
        topic_sections: dict[str, list[dict]] = {topic: [] for topic in TOPIC_KEYWORDS.keys()}
        other_sections: list[dict] = []

        for section in sections:
            section_name = (section.get("section_name") or "").lower()
            section_text = (section.get("text") or "").lower()[:500]  # Check first 500 chars
            combined = section_name + " " + section_text

            matched = False
            for topic, keywords in TOPIC_KEYWORDS.items():
                if any(kw in combined for kw in keywords):
                    topic_sections[topic].append({
                        "citation": section["id"],
                        "name": section.get("section_name", ""),
                    })
                    matched = True
                    break  # Only match to first topic

            if not matched:
                other_sections.append({
                    "citation": section["id"],
                    "name": section.get("section_name", ""),
                })

        # Build TopicGroup objects for non-empty topics
        groups = []
        for topic, secs in topic_sections.items():
            if secs:
                groups.append(TopicGroup(
                    topic=topic,
                    sections=secs,
                    section_count=len(secs),
                ))

        # Add "Other" category if there are unmatched sections
        if other_sections:
            groups.append(TopicGroup(
                topic="Other",
                description="Sections not matching primary topic categories",
                sections=other_sections,
                section_count=len(other_sections),
            ))

        # Sort by section count descending
        groups.sort(key=lambda g: g.section_count, reverse=True)

        return groups

    def _build_chips_timeline(
        self,
        sections_created: list[dict],
        sections_amended: list[dict],
    ) -> list[TimelineEntry]:
        """Build timeline for CHIPS narrative."""
        entries = []

        # CHIPS enactment
        entries.append(TimelineEntry(
            date=CHIPS_ENACTED_DATE,
            event_type="enacted",
            title=f"{CHIPS_TITLE} signed into law",
            description=self._track_fact(NarrativeFact.from_tier(
                content="President Biden signed the CHIPS and Science Act",
                tier=1,
                source="Historical record"
            )),
            citation=CHIPS_PL_CITATION,
            source_url="https://www.congress.gov/bill/117th-congress/house-bill/4346",
        ))

        # Add predecessor law milestones
        for pred in CHIPS_PREDECESSORS:
            law = self.graph.get_node("PublicLaw", pred["citation"])
            if law:
                enacted = law.get("enacted_date")
                if enacted:
                    try:
                        date_obj = date.fromisoformat(enacted)
                        entries.append(TimelineEntry(
                            date=date_obj,
                            event_type="predecessor",
                            title=f"{pred['title']} enacted",
                            description=self._track_fact(NarrativeFact.from_tier(
                                content=f"Predecessor legislation: {pred['citation']}",
                                tier=1,
                                source="PublicLaw node"
                            )),
                            citation=pred["citation"],
                        ))
                    except (ValueError, TypeError):
                        pass

        return sorted(entries, key=lambda e: e.date or date.min)


# =============================================================================
# CLI Entry Point
# =============================================================================


def main():
    """CLI entry point for testing the narrative generator."""
    import argparse
    import sys

    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Generate legislative narratives",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.narrative.generator --section "42 USC 18851"
  python -m src.narrative.generator --law "Pub. L. 117-167"
  python -m src.narrative.generator --chips
  python -m src.narrative.generator --chips --format html > chips.html
        """,
    )

    parser.add_argument("--section", type=str, help="USC section citation")
    parser.add_argument("--law", type=str, help="Public Law citation")
    parser.add_argument("--chips", action="store_true", help="Generate CHIPS story")
    parser.add_argument(
        "--format",
        choices=["markdown", "html", "json"],
        default="markdown",
        help="Output format",
    )
    parser.add_argument(
        "--tiers",
        type=str,
        default="1,2,3",
        help="Comma-separated tiers to include (default: 1,2,3)",
    )

    args = parser.parse_args()

    if not any([args.section, args.law, args.chips]):
        parser.print_help()
        sys.exit(1)

    # Parse tiers
    include_tiers = [int(t.strip()) for t in args.tiers.split(",")]

    # Connect to Neo4j
    try:
        from ..graph.neo4j_store import Neo4jStore
        store = Neo4jStore()
        store.connect()
    except Exception as e:
        print(f"Error connecting to Neo4j: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        generator = NarrativeGenerator(store)

        if args.section:
            narrative = generator.generate_section_story(args.section, include_tiers)
            if not narrative:
                print(f"Section not found: {args.section}", file=sys.stderr)
                sys.exit(1)

        elif args.law:
            narrative = generator.generate_law_story(args.law)
            if not narrative:
                print(f"Law not found: {args.law}", file=sys.stderr)
                sys.exit(1)

        elif args.chips:
            narrative = generator.generate_chips_story()

        # Output
        if args.format == "markdown":
            print(narrative.to_markdown())
        elif args.format == "html":
            print(narrative.to_html())
        elif args.format == "json":
            import json
            print(json.dumps(narrative.to_dict(), indent=2, default=str))

    finally:
        store.close()


if __name__ == "__main__":
    main()
