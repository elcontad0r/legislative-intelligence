"""
Citation Parser - The linchpin of the entire system.
"""
from __future__ import annotations

"""

This module extracts and normalizes legal citations from text.
It handles the wild variety of formats found in legal documents:

US Code:
  - 42 U.S.C. § 1395
  - 42 USC 1395
  - 42 U.S.C. §1395(a)(1)
  - section 1395 of title 42
  - 42 U.S.C. 1395 et seq.

Public Laws:
  - Pub. L. 111-148
  - P.L. 111-148
  - Public Law 111-148
  - Pub. L. No. 111-148

Bills:
  - H.R. 3590
  - HR3590
  - S. 1234
  - H.R. 3590 (111th Congress)

CFR:
  - 42 CFR 405.1
  - 42 C.F.R. § 405.1
  - 42 CFR Part 405

Federal Register:
  - 78 FR 5566
  - 78 Fed. Reg. 5566

Statutes at Large:
  - 79 Stat. 286
  - 79 Stat 286
"""

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator


class CitationType(Enum):
    """Types of citations we can parse."""

    USC = auto()  # US Code
    PUBLIC_LAW = auto()
    BILL = auto()
    CFR = auto()
    FEDERAL_REGISTER = auto()
    STATUTES_AT_LARGE = auto()
    CASE = auto()  # Judicial opinions
    UNKNOWN = auto()


@dataclass
class ParsedCitation:
    """A citation extracted from text."""

    citation_type: CitationType
    canonical: str  # Normalized form
    original: str  # As found in text
    start: int  # Start position in source text
    end: int  # End position in source text

    # Type-specific fields
    title: int | None = None  # USC title, CFR title
    section: str | None = None  # USC section, CFR section
    subsection: str | None = None  # (a)(1)(A) etc.
    congress: int | None = None  # For public laws and bills
    law_number: int | None = None  # For public laws
    bill_type: str | None = None  # hr, s, hjres, etc.
    bill_number: int | None = None
    volume: int | None = None  # For FR, Stat
    page: int | None = None
    part: int | None = None  # CFR part

    def __hash__(self) -> int:
        return hash(self.canonical)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ParsedCitation):
            return False
        return self.canonical == other.canonical


class CitationParser:
    """
    Extracts and normalizes legal citations from text.

    Usage:
        parser = CitationParser()
        citations = parser.parse("See 42 U.S.C. § 1395 and Pub. L. 111-148.")
        for cite in citations:
            print(f"{cite.citation_type}: {cite.canonical}")
    """

    # ==========================================================================
    # US Code Patterns
    # ==========================================================================

    # Standard forms: "42 U.S.C. § 1395" or "42 USC 1395"
    USC_STANDARD = re.compile(
        r"\b(\d{1,2})\s*"  # Title number
        r"U\.?\s*S\.?\s*C\.?\s*"  # U.S.C. with variations
        r"(?:§+\s*|[Ss]ections?\s+|[Ss]ec\.?\s+)?"  # Optional section symbol
        r"(\d+[a-z]*(?:-\d+[a-z]*)?)"  # Section number (e.g., 1395, 1395a, 1395-1)
        r"(?:\s*\(([^)]+(?:\)\s*\([^)]+)*)\))?"  # Subsections (a)(1)(A)
        r"(?:\s+et\s+seq\.?)?"  # Optional "et seq."
        ,
        re.IGNORECASE,
    )

    # Inverted form: "section 1395 of title 42"
    USC_INVERTED = re.compile(
        r"[Ss]ections?\s+(\d+[a-z]*(?:-\d+[a-z]*)?)"  # Section
        r"(?:\s*\(([^)]+(?:\)\s*\([^)]+)*)\))?"  # Subsections
        r"\s+of\s+[Tt]itle\s+(\d{1,2})"  # Title
        ,
        re.IGNORECASE,
    )

    # ==========================================================================
    # Public Law Patterns
    # ==========================================================================

    PUBLIC_LAW = re.compile(
        r"\b(?:Pub(?:lic)?\.?\s*L(?:aw)?\.?\s*(?:No\.?\s*)?|P\.?\s*L\.?\s*)"
        r"(\d{1,3})\s*[-–—]\s*(\d{1,4})"  # Congress-LawNumber
        ,
        re.IGNORECASE,
    )

    # ==========================================================================
    # Bill Patterns
    # ==========================================================================

    BILL = re.compile(
        r"\b(H\.?\s*R\.?|S\.?|H\.?\s*J\.?\s*Res\.?|S\.?\s*J\.?\s*Res\.?|"
        r"H\.?\s*Con\.?\s*Res\.?|S\.?\s*Con\.?\s*Res\.?|"
        r"H\.?\s*Res\.?|S\.?\s*Res\.?)"  # Bill type
        r"\s*(\d{1,5})"  # Bill number
        r"(?:\s*\((\d{2,3})(?:th|st|nd|rd)?\s*(?:Congress|Cong\.?)?\))?"  # Optional congress
        ,
        re.IGNORECASE,
    )

    # ==========================================================================
    # CFR Patterns
    # ==========================================================================

    CFR = re.compile(
        r"\b(\d{1,2})\s*"  # Title
        r"C\.?\s*F\.?\s*R\.?\s*"  # C.F.R.
        r"(?:§+\s*|[Pp]art\s+|[Ss]ections?\s+|[Ss]ec\.?\s+)?"
        r"(\d+)"  # Part number
        r"(?:\.(\d+[a-z]*))?"  # Optional section
        ,
        re.IGNORECASE,
    )

    # ==========================================================================
    # Federal Register Patterns
    # ==========================================================================

    FEDERAL_REGISTER = re.compile(
        r"\b(\d{1,3})\s*"  # Volume
        r"(?:Fed\.?\s*Reg\.?|FR)\s*"  # Fed. Reg. or FR
        r"(\d{1,6})"  # Page
        ,
        re.IGNORECASE,
    )

    # ==========================================================================
    # Statutes at Large Patterns
    # ==========================================================================

    STATUTES_AT_LARGE = re.compile(
        r"\b(\d{1,3})\s*"  # Volume
        r"Stat\.?\s*"  # Stat.
        r"(\d{1,5})"  # Page
        ,
        re.IGNORECASE,
    )

    # ==========================================================================
    # Bill Type Normalization
    # ==========================================================================

    BILL_TYPE_MAP = {
        "hr": "hr",
        "h.r.": "hr",
        "h.r": "hr",
        "h r": "hr",
        "s": "s",
        "s.": "s",
        "hjres": "hjres",
        "h.j.res.": "hjres",
        "h j res": "hjres",
        "h. j. res.": "hjres",
        "sjres": "sjres",
        "s.j.res.": "sjres",
        "s j res": "sjres",
        "s. j. res.": "sjres",
        "hconres": "hconres",
        "h.con.res.": "hconres",
        "h con res": "hconres",
        "sconres": "sconres",
        "s.con.res.": "sconres",
        "s con res": "sconres",
        "hres": "hres",
        "h.res.": "hres",
        "h res": "hres",
        "sres": "sres",
        "s.res.": "sres",
        "s res": "sres",
    }

    def parse(self, text: str) -> list[ParsedCitation]:
        """
        Extract all citations from text.

        Returns deduplicated list of citations, preserving first occurrence position.
        """
        citations: list[ParsedCitation] = []
        seen: set[str] = set()

        # Parse each citation type
        for cite in self._parse_usc(text):
            if cite.canonical not in seen:
                citations.append(cite)
                seen.add(cite.canonical)

        for cite in self._parse_public_laws(text):
            if cite.canonical not in seen:
                citations.append(cite)
                seen.add(cite.canonical)

        for cite in self._parse_bills(text):
            if cite.canonical not in seen:
                citations.append(cite)
                seen.add(cite.canonical)

        for cite in self._parse_cfr(text):
            if cite.canonical not in seen:
                citations.append(cite)
                seen.add(cite.canonical)

        for cite in self._parse_federal_register(text):
            if cite.canonical not in seen:
                citations.append(cite)
                seen.add(cite.canonical)

        for cite in self._parse_statutes_at_large(text):
            if cite.canonical not in seen:
                citations.append(cite)
                seen.add(cite.canonical)

        # Sort by position in text
        citations.sort(key=lambda c: c.start)
        return citations

    def parse_usc(self, text: str) -> list[ParsedCitation]:
        """Extract only USC citations."""
        return list(self._parse_usc(text))

    def parse_public_laws(self, text: str) -> list[ParsedCitation]:
        """Extract only Public Law citations."""
        return list(self._parse_public_laws(text))

    def normalize_usc(self, title: int, section: str, subsection: str | None = None) -> str:
        """Create canonical USC citation string."""
        canonical = f"{title} USC {section}"
        if subsection:
            # Normalize subsection format
            subsection = self._normalize_subsection(subsection)
            canonical += f"({subsection})"
        return canonical

    def normalize_public_law(self, congress: int, law_number: int) -> str:
        """Create canonical Public Law citation string."""
        return f"Pub. L. {congress}-{law_number}"

    def normalize_bill(self, bill_type: str, number: int, congress: int | None = None) -> str:
        """Create canonical bill citation string."""
        normalized_type = self.BILL_TYPE_MAP.get(bill_type.lower().replace(" ", ""), bill_type)
        canonical = f"{normalized_type.upper()} {number}"
        if congress:
            canonical += f" ({congress}th)"
        return canonical

    def normalize_cfr(self, title: int, part: int, section: str | None = None) -> str:
        """Create canonical CFR citation string."""
        canonical = f"{title} CFR {part}"
        if section:
            canonical += f".{section}"
        return canonical

    # ==========================================================================
    # Internal Parsing Methods
    # ==========================================================================

    def _parse_usc(self, text: str) -> Iterator[ParsedCitation]:
        """Parse USC citations."""
        # Standard form
        for match in self.USC_STANDARD.finditer(text):
            title = int(match.group(1))
            section = match.group(2)
            subsection = match.group(3)

            yield ParsedCitation(
                citation_type=CitationType.USC,
                canonical=self.normalize_usc(title, section, subsection),
                original=match.group(0),
                start=match.start(),
                end=match.end(),
                title=title,
                section=section,
                subsection=self._normalize_subsection(subsection) if subsection else None,
            )

        # Inverted form
        for match in self.USC_INVERTED.finditer(text):
            section = match.group(1)
            subsection = match.group(2)
            title = int(match.group(3))

            yield ParsedCitation(
                citation_type=CitationType.USC,
                canonical=self.normalize_usc(title, section, subsection),
                original=match.group(0),
                start=match.start(),
                end=match.end(),
                title=title,
                section=section,
                subsection=self._normalize_subsection(subsection) if subsection else None,
            )

    def _parse_public_laws(self, text: str) -> Iterator[ParsedCitation]:
        """Parse Public Law citations."""
        for match in self.PUBLIC_LAW.finditer(text):
            congress = int(match.group(1))
            law_number = int(match.group(2))

            yield ParsedCitation(
                citation_type=CitationType.PUBLIC_LAW,
                canonical=self.normalize_public_law(congress, law_number),
                original=match.group(0),
                start=match.start(),
                end=match.end(),
                congress=congress,
                law_number=law_number,
            )

    def _parse_bills(self, text: str) -> Iterator[ParsedCitation]:
        """Parse bill citations."""
        for match in self.BILL.finditer(text):
            bill_type = match.group(1)
            number = int(match.group(2))
            congress = int(match.group(3)) if match.group(3) else None

            normalized_type = self.BILL_TYPE_MAP.get(
                bill_type.lower().replace(" ", "").replace(".", ""), bill_type.lower()
            )

            yield ParsedCitation(
                citation_type=CitationType.BILL,
                canonical=self.normalize_bill(normalized_type, number, congress),
                original=match.group(0),
                start=match.start(),
                end=match.end(),
                bill_type=normalized_type,
                bill_number=number,
                congress=congress,
            )

    def _parse_cfr(self, text: str) -> Iterator[ParsedCitation]:
        """Parse CFR citations."""
        for match in self.CFR.finditer(text):
            title = int(match.group(1))
            part = int(match.group(2))
            section = match.group(3)

            yield ParsedCitation(
                citation_type=CitationType.CFR,
                canonical=self.normalize_cfr(title, part, section),
                original=match.group(0),
                start=match.start(),
                end=match.end(),
                title=title,
                part=part,
                section=section,
            )

    def _parse_federal_register(self, text: str) -> Iterator[ParsedCitation]:
        """Parse Federal Register citations."""
        for match in self.FEDERAL_REGISTER.finditer(text):
            volume = int(match.group(1))
            page = int(match.group(2))

            yield ParsedCitation(
                citation_type=CitationType.FEDERAL_REGISTER,
                canonical=f"{volume} FR {page}",
                original=match.group(0),
                start=match.start(),
                end=match.end(),
                volume=volume,
                page=page,
            )

    def _parse_statutes_at_large(self, text: str) -> Iterator[ParsedCitation]:
        """Parse Statutes at Large citations."""
        for match in self.STATUTES_AT_LARGE.finditer(text):
            volume = int(match.group(1))
            page = int(match.group(2))

            yield ParsedCitation(
                citation_type=CitationType.STATUTES_AT_LARGE,
                canonical=f"{volume} Stat. {page}",
                original=match.group(0),
                start=match.start(),
                end=match.end(),
                volume=volume,
                page=page,
            )

    def _normalize_subsection(self, subsection: str | None) -> str | None:
        """Normalize subsection format: (a)(1)(A) -> a.1.A"""
        if not subsection:
            return None
        # Remove outer parens and normalize
        # "(a)(1)(A)" -> "a)(1)(A" -> ["a", "1", "A"]
        parts = re.split(r"\)\s*\(", subsection.strip("()"))
        return ".".join(parts)


# =============================================================================
# Convenience Functions
# =============================================================================


def extract_citations(text: str) -> list[ParsedCitation]:
    """Extract all citations from text. Convenience wrapper around CitationParser."""
    return CitationParser().parse(text)


def extract_usc_citations(text: str) -> list[ParsedCitation]:
    """Extract only USC citations from text."""
    return CitationParser().parse_usc(text)


def normalize_usc_citation(title: int, section: str, subsection: str | None = None) -> str:
    """Create a canonical USC citation string."""
    return CitationParser().normalize_usc(title, section, subsection)


# =============================================================================
# Testing / Demo
# =============================================================================

if __name__ == "__main__":
    # Test the parser
    test_texts = [
        "See 42 U.S.C. § 1395 and 42 USC 1395a(a)(1).",
        "Pursuant to Pub. L. 111-148, as amended by P.L. 111-152...",
        "H.R. 3590 (111th Congress) was signed into law.",
        "The regulations at 42 CFR 405.1 implement section 1395 of title 42.",
        "Published at 78 FR 5566, effective per 79 Stat. 286.",
        "This amends 26 U.S.C. § 5000A et seq.",
    ]

    parser = CitationParser()
    for text in test_texts:
        print(f"\nText: {text}")
        print("Citations found:")
        for cite in parser.parse(text):
            print(f"  - {cite.citation_type.name}: {cite.canonical} (from '{cite.original}')")
