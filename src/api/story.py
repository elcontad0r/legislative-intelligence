"""
Story of a Law - The narrative generator.

This module takes a USC citation and generates a comprehensive "story"
of that law - where it came from, how it evolved, how it's implemented,
and how it's been interpreted.

The output can be:
1. Raw data (for programmatic use)
2. Markdown narrative (for human reading)
3. Timeline data (for visualization)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from dotenv import load_dotenv
load_dotenv()

from ..graph.neo4j_store import Neo4jStore
from ..parsers.citations import CitationParser, CitationType


@dataclass
class TimelineEvent:
    """A single event in the law's timeline."""

    date: date | None
    event_type: str  # "enacted", "amended", "interpreted", "implemented", etc.
    title: str
    description: str
    citation: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat() if self.date else None,
            "event_type": self.event_type,
            "title": self.title,
            "description": self.description,
            "citation": self.citation,
            "source_url": self.source_url,
            "metadata": self.metadata,
        }


@dataclass
class LawStory:
    """The complete story of a law."""

    citation: str
    section_name: str | None
    title_name: str | None
    current_text: str | None
    timeline: list[TimelineEvent]
    enacting_law: dict[str, Any] | None
    amendments: list[dict[str, Any]]
    regulations: list[dict[str, Any]]
    cases: list[dict[str, Any]]
    related_sections: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "section_name": self.section_name,
            "title_name": self.title_name,
            "current_text": self.current_text,
            "timeline": [e.to_dict() for e in self.timeline],
            "enacting_law": self.enacting_law,
            "amendments": self.amendments,
            "regulations": self.regulations,
            "cases": self.cases,
            "related_sections": self.related_sections,
        }

    def to_markdown(self) -> str:
        """Generate a markdown narrative of the law's story."""
        lines = []

        # Header
        lines.append(f"# The Story of {self.citation}")
        if self.section_name:
            lines.append(f"## {self.section_name}")
        lines.append("")

        # Introduction
        if self.title_name:
            lines.append(f"*Part of {self.title_name}*")
            lines.append("")

        # Origin
        if self.enacting_law:
            pl = self.enacting_law.get("public_law", {})
            pl_citation = pl.get("id", "Unknown")
            pl_title = pl.get("title", "")
            enacted_date = pl.get("enacted_date", "")

            lines.append("## Origin")
            lines.append("")
            if enacted_date:
                lines.append(f"This section was enacted on **{enacted_date}** by **{pl_citation}**")
            else:
                lines.append(f"This section was enacted by **{pl_citation}**")
            if pl_title:
                lines.append(f"({pl_title})")
            lines.append("")

        # Timeline
        if self.timeline:
            lines.append("## Timeline")
            lines.append("")

            for event in sorted(self.timeline, key=lambda e: e.date or date.min):
                date_str = event.date.strftime("%B %d, %Y") if event.date else "Date unknown"
                emoji = self._get_event_emoji(event.event_type)
                lines.append(f"- **{date_str}** {emoji} {event.title}")
                if event.description:
                    lines.append(f"  - {event.description}")
            lines.append("")

        # Amendments
        if self.amendments:
            lines.append("## Legislative History")
            lines.append("")
            lines.append(f"This section has been amended **{len(self.amendments)} times**:")
            lines.append("")

            for amend in self.amendments:
                pl = amend.get("public_law", {})
                pl_id = pl.get("id", "Unknown")
                pl_title = pl.get("title", "")
                amend_info = amend.get("amendment", {})
                effective = amend_info.get("effective_date", "")

                if effective:
                    lines.append(f"- **{effective}**: {pl_id}")
                else:
                    lines.append(f"- {pl_id}")
                if pl_title:
                    lines.append(f"  - *{pl_title}*")
            lines.append("")

        # Regulations
        if self.regulations:
            lines.append("## Regulatory Implementation")
            lines.append("")
            lines.append(f"This section is implemented by **{len(self.regulations)} CFR sections**:")
            lines.append("")

            for reg in self.regulations:
                cfr = reg.get("cfr", {})
                cfr_id = cfr.get("id", "Unknown")
                cfr_name = cfr.get("section_name", "")

                lines.append(f"- **{cfr_id}**")
                if cfr_name:
                    lines.append(f"  - {cfr_name}")
            lines.append("")

        # Cases
        if self.cases:
            lines.append("## Judicial Interpretation")
            lines.append("")
            lines.append(f"This section has been interpreted in **{len(self.cases)} cases**:")
            lines.append("")

            for case_data in self.cases[:10]:  # Limit to top 10
                case = case_data.get("case", {})
                case_name = case.get("name", "Unknown")
                case_citation = case.get("id", "")
                court = case.get("court", "")
                decided = case.get("decided_date", "")

                interp = case_data.get("interprets", {})
                holding_type = interp.get("holding_type", "")

                lines.append(f"- **{case_name}** ({case_citation})")
                if court and decided:
                    lines.append(f"  - {court}, {decided}")
                if holding_type:
                    lines.append(f"  - *{holding_type}*")
            lines.append("")

        # Current Text (truncated)
        if self.current_text:
            lines.append("## Current Text")
            lines.append("")
            lines.append("```")
            # Truncate to first 2000 chars
            text = self.current_text[:2000]
            if len(self.current_text) > 2000:
                text += "\n... [truncated]"
            lines.append(text)
            lines.append("```")
            lines.append("")

        return "\n".join(lines)

    def _get_event_emoji(self, event_type: str) -> str:
        """Get an emoji for the event type."""
        emojis = {
            "enacted": "📜",
            "amended": "✏️",
            "interpreted": "⚖️",
            "implemented": "📋",
            "repealed": "🗑️",
            "renamed": "🏷️",
        }
        return emojis.get(event_type, "📌")


class StoryOfALaw:
    """
    Main interface for generating law stories.

    Usage:
        story_gen = StoryOfALaw(graph_store)

        # Get story for a citation
        story = story_gen.get_story("42 USC 1395")

        # Print as markdown
        print(story.to_markdown())

        # Get as JSON-serializable dict
        data = story.to_dict()
    """

    def __init__(self, graph_store: Neo4jStore | None = None):
        """
        Initialize the story generator.

        Args:
            graph_store: Neo4j store instance (or creates one from env vars)
        """
        self.graph = graph_store or Neo4jStore()
        self.graph.connect()
        self.citation_parser = CitationParser()

    def close(self):
        """Clean up resources."""
        self.graph.close()

    def get_story(self, citation: str) -> LawStory | None:
        """
        Get the complete story for a USC citation.

        Args:
            citation: A USC citation like "42 USC 1395" or "42 U.S.C. § 1395"

        Returns:
            LawStory object or None if not found
        """
        # Normalize the citation
        normalized = self._normalize_citation(citation)
        if not normalized:
            return None

        # Get the section
        section = self.graph.get_usc_section(normalized)
        if not section:
            return None

        # Get all related data
        enacting_law = self.graph.get_enacting_law(normalized)
        amendments = self.graph.get_amendments(normalized)
        regulations = self.graph.get_implementing_regulations(normalized)
        cases = self.graph.get_interpreting_cases(normalized)

        # Build timeline
        timeline = self._build_timeline(section, enacting_law, amendments, regulations, cases)

        # Get related sections (same chapter)
        related = self._get_related_sections(section)

        return LawStory(
            citation=normalized,
            section_name=section.get("section_name"),
            title_name=section.get("title_name"),
            current_text=section.get("text"),
            timeline=timeline,
            enacting_law=enacting_law,
            amendments=amendments,
            regulations=regulations,
            cases=cases,
            related_sections=related,
        )

    def get_story_markdown(self, citation: str) -> str | None:
        """Get the story as a markdown string."""
        story = self.get_story(citation)
        if story:
            return story.to_markdown()
        return None

    def search_and_get_story(self, query: str) -> list[LawStory]:
        """
        Search for sections and return stories for matches.

        Args:
            query: Search query

        Returns:
            List of LawStory objects for matching sections
        """
        results = self.graph.search_sections(query, limit=10)
        stories = []

        for result in results:
            section = result.get("section", {})
            citation = section.get("id")
            if citation:
                story = self.get_story(citation)
                if story:
                    stories.append(story)

        return stories

    def _normalize_citation(self, citation: str) -> str | None:
        """Normalize a citation to canonical form."""
        # Try to parse it
        parsed = self.citation_parser.parse(citation)

        # Find USC citation
        for cite in parsed:
            if cite.citation_type == CitationType.USC:
                return cite.canonical

        # If parsing didn't work, try simple normalization
        # "42 U.S.C. § 1395" -> "42 USC 1395"
        import re

        match = re.match(r"(\d+)\s*U\.?\s*S\.?\s*C\.?\s*§?\s*(\d+[a-z]*)", citation, re.IGNORECASE)
        if match:
            return f"{match.group(1)} USC {match.group(2)}"

        return None

    def _build_timeline(
        self,
        section: dict,
        enacting_law: dict | None,
        amendments: list[dict],
        regulations: list[dict],
        cases: list[dict],
    ) -> list[TimelineEvent]:
        """Build a chronological timeline of events."""
        events = []

        # Enactment
        if enacting_law:
            pl = enacting_law.get("public_law", {})
            enacted_date = pl.get("enacted_date")
            if enacted_date:
                try:
                    event_date = date.fromisoformat(enacted_date)
                except (ValueError, TypeError):
                    event_date = None
            else:
                event_date = None

            events.append(
                TimelineEvent(
                    date=event_date,
                    event_type="enacted",
                    title=f"Enacted by {pl.get('id', 'Unknown')}",
                    description=pl.get("title", ""),
                    citation=pl.get("id"),
                )
            )

        # Amendments
        for amend in amendments:
            pl = amend.get("public_law", {})
            amend_info = amend.get("amendment", {})

            effective = amend_info.get("effective_date")
            if effective:
                try:
                    event_date = date.fromisoformat(effective)
                except (ValueError, TypeError):
                    event_date = None
            else:
                # Fall back to enacted date
                enacted = pl.get("enacted_date")
                if enacted:
                    try:
                        event_date = date.fromisoformat(enacted)
                    except (ValueError, TypeError):
                        event_date = None
                else:
                    event_date = None

            events.append(
                TimelineEvent(
                    date=event_date,
                    event_type="amended",
                    title=f"Amended by {pl.get('id', 'Unknown')}",
                    description=amend_info.get("amendment_description", pl.get("title", "")),
                    citation=pl.get("id"),
                )
            )

        # Key cases
        for case_data in cases[:5]:  # Top 5 cases
            case = case_data.get("case", {})
            interp = case_data.get("interprets", {})

            decided = case.get("decided_date")
            if decided:
                try:
                    event_date = date.fromisoformat(decided)
                except (ValueError, TypeError):
                    event_date = None
            else:
                event_date = None

            events.append(
                TimelineEvent(
                    date=event_date,
                    event_type="interpreted",
                    title=f"Interpreted in {case.get('name', 'Unknown')}",
                    description=interp.get("interpretation_summary", ""),
                    citation=case.get("id"),
                    metadata={"court": case.get("court"), "holding_type": interp.get("holding_type")},
                )
            )

        # Sort by date
        events.sort(key=lambda e: e.date or date.min)

        return events

    def _get_related_sections(self, section: dict) -> list[dict]:
        """Get other sections in the same chapter."""
        title = section.get("citation_title") or section.get("title")
        chapter = section.get("chapter")

        if not title or not chapter:
            return []

        # Query for sections in the same chapter
        with self.graph.session() as session:
            result = session.run(
                """
                MATCH (usc:USCSection)
                WHERE usc.title = $title AND usc.chapter = $chapter AND usc.id <> $id
                RETURN usc
                LIMIT 20
                """,
                title=title,
                chapter=chapter,
                id=section.get("id"),
            )
            return [dict(r["usc"]) for r in result]


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python story.py <citation>")
        print("Example: python story.py '42 USC 1395'")
        sys.exit(1)

    citation = " ".join(sys.argv[1:])

    story_gen = StoryOfALaw()
    try:
        story = story_gen.get_story(citation)
        if story:
            print(story.to_markdown())
        else:
            print(f"No story found for: {citation}")
    finally:
        story_gen.close()
