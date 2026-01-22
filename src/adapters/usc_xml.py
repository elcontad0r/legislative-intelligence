"""
US Code XML Adapter - Parse the official USLM XML format.

The Office of the Law Revision Counsel publishes the US Code in XML format
using the United States Legislative Markup (USLM) schema.

Download from: https://uscode.house.gov/download/download.shtml

This adapter:
1. Parses the XML structure to extract sections, chapters, etc.
2. Extracts history notes that tell us which public laws created/amended each section
3. Extracts cross-references between sections
4. Creates USCSection nodes ready for the graph
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator
from datetime import datetime
from lxml import etree

from ..models import USCSection, USCCitation, PublicLawCitation, ProvenanceInfo, TemporalInfo
from ..parsers.citations import CitationParser


# USLM namespace
USLM_NS = {"uslm": "http://xml.house.gov/schemas/uslm/1.0"}


class USCodeXMLAdapter:
    """
    Parser for US Code XML files in USLM format.

    Usage:
        adapter = USCodeXMLAdapter()

        # Parse a single title
        for section in adapter.parse_title_file("usc42.xml"):
            print(f"{section.citation}: {section.section_name}")

        # Parse all titles in a directory
        for section in adapter.parse_directory("/path/to/usc_xml/"):
            graph.upsert_node(section)
    """

    def __init__(self):
        self.citation_parser = CitationParser()
        self._current_file: str | None = None

    def parse_title_file(self, filepath: str | Path) -> Iterator[USCSection]:
        """
        Parse a single US Code title XML file.

        Yields USCSection objects for each section in the title.
        """
        filepath = Path(filepath)
        self._current_file = str(filepath)

        # Parse the XML
        tree = etree.parse(filepath)
        root = tree.getroot()

        # Get title info from the root
        title_num = self._get_title_number(root)
        title_name = self._get_title_name(root)

        if title_num is None:
            raise ValueError(f"Could not determine title number from {filepath}")

        # Find all sections
        # USLM structure: title > chapter > subchapter? > section
        for section_elem in root.iter("{http://xml.house.gov/schemas/uslm/1.0}section"):
            try:
                section = self._parse_section(section_elem, title_num, title_name)
                if section:
                    yield section
            except Exception as e:
                # Log but continue - some sections may have parsing issues
                section_id = section_elem.get("identifier", "unknown")
                print(f"Warning: Failed to parse section {section_id}: {e}")
                continue

    def parse_directory(self, dirpath: str | Path) -> Iterator[USCSection]:
        """
        Parse all US Code XML files in a directory.

        Expects files named like usc01.xml, usc02.xml, etc.
        """
        dirpath = Path(dirpath)

        for xml_file in sorted(dirpath.glob("usc*.xml")):
            print(f"Parsing {xml_file.name}...")
            yield from self.parse_title_file(xml_file)

    def parse_title_from_url(self, title: int) -> Iterator[USCSection]:
        """
        Download and parse a title directly from uscode.house.gov.

        Note: For bulk operations, better to download files first.
        """
        import httpx

        url = f"https://uscode.house.gov/download/releasepoints/us/pl/119/69/xml_usc{title:02d}@119-69.zip"

        # This would need to download, unzip, and parse
        # For now, raise NotImplemented - use local files
        raise NotImplementedError(
            f"Direct URL parsing not yet implemented. "
            f"Download from {url} and use parse_title_file() instead."
        )

    def _parse_section(
        self, elem: etree._Element, title_num: int, title_name: str | None
    ) -> USCSection | None:
        """Parse a single section element into a USCSection model."""

        # Get section identifier (e.g., "/us/usc/t42/s1395")
        identifier = elem.get("identifier", "")

        # Extract section number from identifier
        section_match = re.search(r"/s(\d+[a-z]*(?:-\d+)?)", identifier)
        if not section_match:
            return None

        section_num = section_match.group(1)

        # Get section heading/name
        heading_elem = elem.find("uslm:heading", USLM_NS)
        section_name = self._get_text(heading_elem) if heading_elem is not None else None

        # Get chapter info by walking up the tree
        chapter_num, chapter_name = self._get_chapter_info(elem)

        # Get the full text content
        text = self._extract_section_text(elem)

        # Get history note (source credits, amendments)
        history_note = self._extract_history_note(elem)

        # Extract source credit (original enacting statute)
        source_credit = self._extract_source_credit(elem)

        # Parse effective date if available
        effective_date = self._extract_effective_date(elem)

        # Create the citation
        citation = USCCitation(title=title_num, section=section_num)

        # Create provenance
        provenance = ProvenanceInfo(
            source_name="uscode.house.gov",
            source_url=f"https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{title_num}-section{section_num}",
            retrieved_at=datetime.utcnow(),
        )

        # Create temporal info
        temporal = TemporalInfo(effective_date=effective_date)

        return USCSection(
            id=citation.canonical,
            citation=citation,
            title_name=title_name,
            chapter=chapter_num,
            chapter_name=chapter_name,
            section_name=section_name,
            text=text,
            history_note=history_note,
            source_credit=source_credit,
            temporal=temporal,
            provenance=provenance,
        )

    def _get_title_number(self, root: etree._Element) -> int | None:
        """Extract the title number from the root element."""
        # Try identifier attribute
        identifier = root.get("identifier", "")
        match = re.search(r"/t(\d+)", identifier)
        if match:
            return int(match.group(1))

        # Try title element
        title_elem = root.find(".//uslm:title", USLM_NS)
        if title_elem is not None:
            num = title_elem.get("number")
            if num:
                return int(num)

        return None

    def _get_title_name(self, root: etree._Element) -> str | None:
        """Extract the title name."""
        # Look for the title's heading
        title_elem = root.find(".//uslm:title", USLM_NS)
        if title_elem is not None:
            heading = title_elem.find("uslm:heading", USLM_NS)
            if heading is not None:
                return self._get_text(heading)
        return None

    def _get_chapter_info(self, section_elem: etree._Element) -> tuple[str | None, str | None]:
        """Walk up the tree to find chapter information."""
        parent = section_elem.getparent()
        while parent is not None:
            if parent.tag == "{http://xml.house.gov/schemas/uslm/1.0}chapter":
                num = parent.get("number")
                heading = parent.find("uslm:heading", USLM_NS)
                name = self._get_text(heading) if heading is not None else None
                return num, name
            parent = parent.getparent()
        return None, None

    def _extract_section_text(self, elem: etree._Element) -> str:
        """Extract the full text content of a section, excluding notes."""
        # Get text from content elements, skip sourceCredit and notes
        text_parts = []

        for child in elem:
            tag = child.tag.replace("{http://xml.house.gov/schemas/uslm/1.0}", "")
            if tag in ("sourceCredit", "notes", "note", "amendment"):
                continue
            text_parts.append(self._get_text(child))

        return "\n".join(filter(None, text_parts))

    def _extract_history_note(self, elem: etree._Element) -> str | None:
        """Extract the history/amendments note."""
        # Look for notes section
        notes_elem = elem.find("uslm:notes", USLM_NS)
        if notes_elem is not None:
            return self._get_text(notes_elem)

        # Also check for inline amendment notes
        amendment_elems = elem.findall(".//uslm:note[@type='amendment']", USLM_NS)
        if amendment_elems:
            return "\n".join(self._get_text(a) for a in amendment_elems)

        return None

    def _extract_source_credit(self, elem: etree._Element) -> str | None:
        """Extract the source credit (original enacting statute citation)."""
        source_elem = elem.find("uslm:sourceCredit", USLM_NS)
        if source_elem is not None:
            return self._get_text(source_elem)
        return None

    def _extract_effective_date(self, elem: etree._Element) -> None:
        """Extract effective date if available. Returns None for now - needs more work."""
        # Effective dates are often embedded in notes or amendments
        # This would require parsing natural language dates
        # For now, return None and handle in a later pass
        return None

    def _get_text(self, elem: etree._Element | None) -> str:
        """Get all text content from an element, including children."""
        if elem is None:
            return ""
        return "".join(elem.itertext()).strip()

    def extract_public_law_citations(self, section: USCSection) -> list[PublicLawCitation]:
        """
        Extract Public Law citations from a section's history note and source credit.

        This is crucial for linking sections back to their legislative origins.
        """
        citations = []

        # Combine all text that might contain citations
        text_to_parse = ""
        if section.source_credit:
            text_to_parse += section.source_credit + " "
        if section.history_note:
            text_to_parse += section.history_note

        if not text_to_parse:
            return citations

        # Parse citations
        parsed = self.citation_parser.parse_public_laws(text_to_parse)

        for cite in parsed:
            if cite.congress and cite.law_number:
                citations.append(
                    PublicLawCitation(congress=cite.congress, law_number=cite.law_number)
                )

        return citations


# =============================================================================
# Convenience Functions
# =============================================================================


def parse_usc_title(filepath: str | Path) -> list[USCSection]:
    """Parse a US Code title XML file and return all sections."""
    adapter = USCodeXMLAdapter()
    return list(adapter.parse_title_file(filepath))


def parse_usc_directory(dirpath: str | Path) -> list[USCSection]:
    """Parse all US Code XML files in a directory."""
    adapter = USCodeXMLAdapter()
    return list(adapter.parse_directory(dirpath))


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python usc_xml.py <path_to_xml_file_or_directory>")
        sys.exit(1)

    path = Path(sys.argv[1])

    adapter = USCodeXMLAdapter()

    if path.is_file():
        sections = list(adapter.parse_title_file(path))
    else:
        sections = list(adapter.parse_directory(path))

    print(f"\nParsed {len(sections)} sections")

    # Show first few
    for section in sections[:5]:
        print(f"\n{section.citation.canonical}: {section.section_name}")
        if section.source_credit:
            print(f"  Source: {section.source_credit[:100]}...")

        # Extract public law citations
        pl_cites = adapter.extract_public_law_citations(section)
        if pl_cites:
            print(f"  Public Laws: {', '.join(str(c) for c in pl_cites[:5])}")
