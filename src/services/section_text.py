"""
Section Text Service - Retrieve USC section text on demand.

The Neo4j Aura database stores section metadata but not the full text
(to avoid hitting storage limits). This service retrieves text on-demand
from local XML files or the uscode.house.gov website.

Caches retrieved text to avoid repeated parsing.
"""
from __future__ import annotations

import re
import json
import logging
from pathlib import Path
from typing import Any
from functools import lru_cache

import httpx

# lxml is optional - only needed for local XML parsing
try:
    from lxml import etree
    HAS_LXML = True
except ImportError:
    HAS_LXML = False
    etree = None  # type: ignore

logger = logging.getLogger(__name__)

# Paths
DATA_DIR = Path(__file__).parent.parent.parent / "data"
RAW_USC_DIR = DATA_DIR / "raw" / "usc"
TEXT_CACHE_DIR = DATA_DIR / "cache" / "section_text"

# USLM namespace
USLM_NS = {"uslm": "http://xml.house.gov/schemas/uslm/1.0"}


class SectionTextService:
    """
    Service to retrieve USC section text on-demand.

    Priorities:
    1. Check file cache (fast)
    2. Parse local XML file if available (medium)
    3. Fetch from uscode.house.gov (slow, fallback)
    """

    def __init__(self):
        TEXT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._xml_trees: dict[int, etree._ElementTree] = {}

    def get_section_text(self, citation: str) -> str | None:
        """
        Get the text for a USC section.

        Args:
            citation: Canonical citation like "42 USC 18911"

        Returns:
            Section text or None if not found
        """
        # Parse citation
        match = re.match(r"(\d+) USC (\d+[a-z]*(?:-\d+)?)", citation)
        if not match:
            logger.warning(f"Invalid citation format: {citation}")
            return None

        title = int(match.group(1))
        section = match.group(2)

        # 1. Check cache
        cached = self._get_cached_text(title, section)
        if cached is not None:
            return cached

        # 2. Try local XML
        text = self._get_from_xml(title, section)
        if text:
            self._cache_text(title, section, text)
            return text

        # 3. Fallback to web
        text = self._get_from_web(title, section)
        if text:
            self._cache_text(title, section, text)
            return text

        logger.info(f"Section text not found for {citation}")
        return None

    def _get_cached_text(self, title: int, section: str) -> str | None:
        """Check file cache for section text."""
        cache_file = TEXT_CACHE_DIR / f"t{title}_s{section.replace('-', '_')}.txt"
        if cache_file.exists():
            return cache_file.read_text()
        return None

    def _cache_text(self, title: int, section: str, text: str) -> None:
        """Cache section text to file."""
        cache_file = TEXT_CACHE_DIR / f"t{title}_s{section.replace('-', '_')}.txt"
        try:
            cache_file.write_text(text)
        except Exception as e:
            logger.warning(f"Failed to cache section text: {e}")

    def _get_from_xml(self, title: int, section: str) -> str | None:
        """Parse local XML file to get section text."""
        if not HAS_LXML:
            logger.debug("lxml not available, skipping XML parsing")
            return None

        xml_file = RAW_USC_DIR / f"usc{title:02d}.xml"
        if not xml_file.exists():
            logger.debug(f"XML file not found: {xml_file}")
            return None

        try:
            # Cache the parsed tree for reuse
            if title not in self._xml_trees:
                logger.info(f"Parsing XML file: {xml_file}")
                self._xml_trees[title] = etree.parse(str(xml_file))

            tree = self._xml_trees[title]

            # Find the section by identifier
            # The identifier format is like /us/usc/t42/s18911
            identifier = f"/us/usc/t{title}/s{section}"

            for section_elem in tree.iter("{http://xml.house.gov/schemas/uslm/1.0}section"):
                elem_id = section_elem.get("identifier", "")
                if elem_id == identifier or elem_id.endswith(f"/s{section}"):
                    return self._extract_section_text(section_elem)

            logger.debug(f"Section not found in XML: {identifier}")
            return None

        except Exception as e:
            logger.error(f"Error parsing XML for {title} USC {section}: {e}")
            return None

    def _get_from_web(self, title: int, section: str) -> str | None:
        """Fetch section text from uscode.house.gov."""
        url = f"https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{title}-section{section}&edition=prelim"

        try:
            logger.info(f"Fetching section text from {url}")
            response = httpx.get(url, follow_redirects=True, timeout=30.0)
            response.raise_for_status()

            html = response.text

            # Extract content between statute markers
            # USC pages use <!-- field-start:statute --> and <!-- field-end:statute -->
            statute_match = re.search(
                r'<!-- field-start:statute -->(.*?)<!-- field-end:statute -->',
                html,
                re.DOTALL
            )

            if statute_match:
                statute_html = statute_match.group(1)

                # Strip HTML tags but preserve structure
                # Remove scripts and styles
                text = re.sub(r'<script[^>]*>.*?</script>', '', statute_html, flags=re.DOTALL)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)

                # Convert some HTML elements to text structure
                text = re.sub(r'<h[0-9][^>]*>(.*?)</h[0-9]>', r'\n\1\n', text)
                text = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n', text, flags=re.DOTALL)
                text = re.sub(r'<br\s*/?>', '\n', text)

                # Remove remaining HTML tags
                text = re.sub(r'<[^>]+>', '', text)

                # Decode HTML entities
                import html as html_module
                text = html_module.unescape(text)

                # Clean up whitespace
                text = re.sub(r'\n\s*\n', '\n\n', text)
                text = re.sub(r' +', ' ', text)
                text = text.strip()

                # Limit size for LLM context
                if len(text) > 50000:
                    text = text[:50000] + "... [truncated]"

                if text:
                    return text

            logger.warning(f"Could not extract section text from HTML for {title} USC {section}")
            return None

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching {title} USC {section}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching section from web for {title} USC {section}: {e}")
            return None

    def _extract_section_text(self, elem: etree._Element) -> str:
        """Extract the full text content of a section, excluding notes."""
        text_parts = []

        for child in elem:
            tag = child.tag.replace("{http://xml.house.gov/schemas/uslm/1.0}", "")
            # Skip metadata elements
            if tag in ("sourceCredit", "notes", "note", "amendment"):
                continue
            text_parts.append(self._get_text(child))

        return "\n".join(filter(None, text_parts))

    def _get_text(self, elem: etree._Element | None) -> str:
        """Get all text content from an element, including children."""
        if elem is None:
            return ""
        return "".join(elem.itertext()).strip()

    def preload_title(self, title: int) -> int:
        """
        Preload and cache all sections for a title.

        Returns the number of sections cached.
        """
        if not HAS_LXML:
            logger.warning("lxml not available, cannot preload from XML")
            return 0

        xml_file = RAW_USC_DIR / f"usc{title:02d}.xml"
        if not xml_file.exists():
            logger.warning(f"XML file not found: {xml_file}")
            return 0

        logger.info(f"Preloading sections from {xml_file}")
        tree = etree.parse(str(xml_file))
        count = 0

        for section_elem in tree.iter("{http://xml.house.gov/schemas/uslm/1.0}section"):
            identifier = section_elem.get("identifier", "")
            # Extract section number from identifier like /us/usc/t42/s18911
            match = re.search(r"/s(\d+[a-z]*(?:-\d+)?)", identifier)
            if match:
                section = match.group(1)
                text = self._extract_section_text(section_elem)
                if text:
                    self._cache_text(title, section, text)
                    count += 1

        logger.info(f"Cached {count} sections from Title {title}")
        return count


# Singleton instance
_service: SectionTextService | None = None


def get_section_text_service() -> SectionTextService:
    """Get the singleton section text service."""
    global _service
    if _service is None:
        _service = SectionTextService()
    return _service


def get_section_text(citation: str) -> str | None:
    """Convenience function to get section text."""
    return get_section_text_service().get_section_text(citation)
