"""
Core data models for the Legislative Intelligence system.

These Pydantic models define the schema for all entities in our citation graph.
They're used for:
1. Validating data during ingestion
2. Serialization to/from the graph database
3. API response schemas
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================


class USCTitle(int, Enum):
    """US Code titles we care about initially."""

    TITLE_5 = 5  # Government Organization
    TITLE_15 = 15  # Commerce and Trade
    TITLE_26 = 26  # Internal Revenue Code
    TITLE_29 = 29  # Labor
    TITLE_42 = 42  # Public Health and Welfare (Medicare!)
    TITLE_44 = 44  # Public Printing and Documents
    TITLE_50 = 50  # War and National Defense


class BillType(str, Enum):
    """Types of Congressional bills."""

    HR = "hr"  # House Bill
    S = "s"  # Senate Bill
    HJRES = "hjres"  # House Joint Resolution
    SJRES = "sjres"  # Senate Joint Resolution
    HCONRES = "hconres"  # House Concurrent Resolution
    SCONRES = "sconres"  # Senate Concurrent Resolution
    HRES = "hres"  # House Simple Resolution
    SRES = "sres"  # Senate Simple Resolution


class CourtLevel(str, Enum):
    """Federal court levels."""

    SCOTUS = "scotus"
    CIRCUIT = "circuit"
    DISTRICT = "district"
    BANKRUPTCY = "bankruptcy"
    OTHER = "other"


class EntityType(str, Enum):
    """Types of entities in the system."""

    PERSON = "person"
    ORGANIZATION = "organization"
    AGENCY = "agency"
    COMMITTEE = "committee"
    SUBCOMMITTEE = "subcommittee"


# =============================================================================
# Base Models
# =============================================================================


class ProvenanceInfo(BaseModel):
    """Tracks where data came from and when."""

    source_url: str | None = None
    source_name: str  # e.g., "congress.gov", "uscode.house.gov"
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    raw_data: dict[str, Any] | None = None  # Original API response if useful


class TemporalInfo(BaseModel):
    """Tracks when something was effective."""

    effective_date: date | None = None
    end_date: date | None = None  # If superseded
    superseded_by: str | None = None  # Citation to replacement


class BaseNode(BaseModel):
    """Base class for all graph nodes."""

    id: str  # Canonical identifier
    provenance: ProvenanceInfo
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Citation Types (Normalized Forms)
# =============================================================================


class USCCitation(BaseModel):
    """A normalized US Code citation."""

    title: int
    section: str  # String because can be "1395a" etc.
    subsection: str | None = None  # (a)(1)(A) etc.

    @property
    def canonical(self) -> str:
        """Canonical string form: 42 USC 1395"""
        base = f"{self.title} USC {self.section}"
        if self.subsection:
            base += f"({self.subsection})"
        return base

    def __str__(self) -> str:
        return self.canonical

    def __hash__(self) -> int:
        return hash(self.canonical)


class PublicLawCitation(BaseModel):
    """A normalized Public Law citation."""

    congress: int
    law_number: int

    @property
    def canonical(self) -> str:
        return f"Pub. L. {self.congress}-{self.law_number}"

    def __str__(self) -> str:
        return self.canonical

    def __hash__(self) -> int:
        return hash(self.canonical)


class BillCitation(BaseModel):
    """A normalized bill citation."""

    congress: int
    bill_type: BillType
    number: int

    @property
    def canonical(self) -> str:
        return f"{self.bill_type.value.upper()} {self.number} ({self.congress}th)"

    def __str__(self) -> str:
        return self.canonical

    def __hash__(self) -> int:
        return hash(self.canonical)


class CFRCitation(BaseModel):
    """A normalized Code of Federal Regulations citation."""

    title: int
    part: int
    section: str | None = None

    @property
    def canonical(self) -> str:
        base = f"{self.title} CFR {self.part}"
        if self.section:
            base += f".{self.section}"
        return base

    def __str__(self) -> str:
        return self.canonical


class CaseCitation(BaseModel):
    """A normalized case citation."""

    volume: int
    reporter: str  # "U.S.", "F.3d", etc.
    page: int
    year: int | None = None
    name: str | None = None  # e.g., "Brown v. Board of Education"

    @property
    def canonical(self) -> str:
        return f"{self.volume} {self.reporter} {self.page}"

    def __str__(self) -> str:
        return self.canonical


# =============================================================================
# Graph Nodes
# =============================================================================


class USCSection(BaseNode):
    """A section of the United States Code."""

    citation: USCCitation
    title_name: str | None = None  # "Public Health and Welfare"
    chapter: str | None = None
    chapter_name: str | None = None
    section_name: str | None = None  # "Hospital insurance benefits for aged..."
    text: str | None = None  # Full text of the section
    temporal: TemporalInfo = Field(default_factory=TemporalInfo)

    # From history notes in USC
    history_note: str | None = None  # Raw history note text
    source_credit: str | None = None  # Original enacting statute

    @property
    def id(self) -> str:
        return self.citation.canonical


class PublicLaw(BaseNode):
    """An enacted Public Law."""

    citation: PublicLawCitation
    title: str | None = None  # Short title if any
    long_title: str | None = None
    enacted_date: date | None = None
    bill_origin: BillCitation | None = None

    # Metadata
    statutes_at_large_citation: str | None = None  # e.g., "79 Stat. 286"
    signing_statement: str | None = None

    @property
    def id(self) -> str:
        return self.citation.canonical


class Bill(BaseNode):
    """A Congressional bill (may or may not become law)."""

    citation: BillCitation
    title: str | None = None
    short_title: str | None = None
    introduced_date: date | None = None
    status: str | None = None  # "Became Law", "Passed House", etc.

    # Sponsors
    sponsor_id: str | None = None
    cosponsor_ids: list[str] = Field(default_factory=list)

    # Committees
    committee_ids: list[str] = Field(default_factory=list)

    # What it amends
    amends_usc_sections: list[str] = Field(default_factory=list)

    # Full text (if available)
    text: str | None = None
    summary: str | None = None  # CRS summary

    @property
    def id(self) -> str:
        return self.citation.canonical


class CFRSection(BaseNode):
    """A section of the Code of Federal Regulations."""

    citation: CFRCitation
    title_name: str | None = None
    chapter: str | None = None
    part_name: str | None = None
    section_name: str | None = None
    text: str | None = None
    temporal: TemporalInfo = Field(default_factory=TemporalInfo)

    # Authority - what statutes authorize this regulation
    authority_citations: list[str] = Field(default_factory=list)  # USC citations

    # Source - Federal Register citation
    source_citation: str | None = None

    @property
    def id(self) -> str:
        return self.citation.canonical


class Case(BaseNode):
    """A judicial opinion."""

    citation: CaseCitation
    name: str  # e.g., "NFIB v. Sebelius"
    court: str  # e.g., "Supreme Court of the United States"
    court_level: CourtLevel
    decided_date: date | None = None
    docket_number: str | None = None

    # Opinion content
    holding: str | None = None  # Brief summary of holding
    text: str | None = None  # Full opinion text

    # What it cites/interprets
    usc_citations: list[str] = Field(default_factory=list)
    case_citations: list[str] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return self.citation.canonical


class Entity(BaseNode):
    """A person or organization."""

    name: str
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)

    # For people
    bioguide_id: str | None = None  # Congressional bioguide ID
    party: str | None = None
    state: str | None = None

    # For organizations
    opensecrets_id: str | None = None
    agency_id: str | None = None  # For federal agencies

    @property
    def id(self) -> str:
        # Use bioguide_id for members of Congress, otherwise name-based
        if self.bioguide_id:
            return f"person:{self.bioguide_id}"
        return f"{self.entity_type.value}:{self.name.lower().replace(' ', '_')}"


class CommitteeReport(BaseNode):
    """A Congressional committee report."""

    report_number: str  # e.g., "H. Rept. 89-213"
    congress: int
    chamber: str  # "House" or "Senate"
    committee: str
    title: str | None = None
    report_date: date | None = None
    bill_citation: BillCitation | None = None
    text: str | None = None
    summary: str | None = None

    @property
    def id(self) -> str:
        return f"report:{self.report_number}"


class Hearing(BaseNode):
    """A Congressional hearing."""

    hearing_id: str
    congress: int
    chamber: str
    committee: str
    subcommittee: str | None = None
    title: str
    hearing_date: date | None = None
    text: str | None = None  # Transcript if available

    # Related bills
    bill_citations: list[BillCitation] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return f"hearing:{self.hearing_id}"


class CRSReport(BaseNode):
    """A Congressional Research Service report."""

    report_id: str  # e.g., "R45153"
    title: str
    authors: list[str] = Field(default_factory=list)
    publication_date: date | None = None
    topics: list[str] = Field(default_factory=list)
    summary: str | None = None
    text: str | None = None

    # What it discusses
    usc_citations: list[str] = Field(default_factory=list)
    bill_citations: list[str] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return f"crs:{self.report_id}"


class LobbyingRecord(BaseNode):
    """A lobbying disclosure record."""

    filing_id: str
    client: str
    registrant: str  # Lobbying firm
    year: int
    quarter: int | None = None
    amount: float | None = None
    issues: list[str] = Field(default_factory=list)

    # Bills lobbied on
    bill_citations: list[BillCitation] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return f"lobbying:{self.filing_id}"


class RFIComment(BaseNode):
    """A public comment on a regulatory docket."""

    comment_id: str
    docket_id: str
    submitter_name: str
    submitter_type: str | None = None  # Individual, Organization, etc.
    organization: str | None = None
    submission_date: date | None = None
    text: str | None = None

    @property
    def id(self) -> str:
        return f"comment:{self.comment_id}"


# =============================================================================
# Graph Edges
# =============================================================================


class BaseEdge(BaseModel):
    """Base class for relationships between nodes."""

    from_id: str
    to_id: str
    provenance: ProvenanceInfo
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AmendsEdge(BaseEdge):
    """A bill/law amends a USC section."""

    relationship_type: str = "AMENDS"
    effective_date: date | None = None
    old_text: str | None = None
    new_text: str | None = None
    amendment_description: str | None = None


class EnactsEdge(BaseEdge):
    """A public law enacts/creates a USC section."""

    relationship_type: str = "ENACTS"
    effective_date: date | None = None


class ImplementsEdge(BaseEdge):
    """A CFR section implements a USC section."""

    relationship_type: str = "IMPLEMENTS"
    authority_text: str | None = None  # The authority citation text


class InterpretsEdge(BaseEdge):
    """A case interprets a USC section."""

    relationship_type: str = "INTERPRETS"
    interpretation_summary: str | None = None
    holding_type: str | None = None  # "upheld", "struck down", "narrowed", etc.


class CitesEdge(BaseEdge):
    """Generic citation relationship."""

    relationship_type: str = "CITES"
    context: str | None = None  # Brief context of the citation


class LobbiedOnEdge(BaseEdge):
    """A lobbying record relates to a bill."""

    relationship_type: str = "LOBBIED_ON"
    position: str | None = None  # "for", "against", "neutral"


class SponsoredEdge(BaseEdge):
    """An entity sponsored a bill."""

    relationship_type: str = "SPONSORED"
    is_primary: bool = True  # Primary sponsor vs cosponsor


class TestifiedAtEdge(BaseEdge):
    """An entity testified at a hearing."""

    relationship_type: str = "TESTIFIED_AT"
    role: str | None = None  # "witness", "expert", etc.
