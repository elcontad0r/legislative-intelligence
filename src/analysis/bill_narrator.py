"""
Bill Narrator - LLM-powered narrative generation for legislation.

This module generates human-readable narratives about bills and laws,
including executive summaries, "start here" guidance, and interesting
threads to explore.

Uses Claude to synthesize structured data into engaging prose.
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic
from dotenv import load_dotenv

# Ensure env is loaded from the right place
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'), override=True)

logger = logging.getLogger(__name__)


@dataclass
class ExecutiveSummary:
    """High-level summary of a bill."""
    headline: str  # One-line hook
    overview: str  # 2-3 paragraph explanation
    key_provisions: list[str]  # Bullet points of major provisions
    why_it_matters: str  # Significance/impact
    historical_context: str  # What led to this


@dataclass
class NavigationGuide:
    """Guidance on where to start exploring."""

    @dataclass
    class PathwayOption:
        interest: str  # "If you care about..."
        description: str  # Brief explanation
        sections: list[str]  # Key sections to look at
        start_with: str  # Recommended first section

    pathways: list[PathwayOption]
    most_amended: list[dict]  # Sections with most history
    newest: list[dict]  # Recently created sections
    highlight: str  # One interesting thread to pull


@dataclass
class SectionContext:
    """Rich context for a single section."""
    plain_english: str  # What this section does in plain English
    why_exists: str  # Why was this created/what problem does it solve
    connections: list[str]  # How it relates to other sections
    amendment_story: str | None  # Narrative of how it evolved


class BillNarrator:
    """
    Generates narrative content about legislation using LLM.

    This class takes structured data from the graph database and
    synthesizes it into engaging, useful prose.
    """

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"):
        """
        Initialize the narrator.

        Args:
            api_key: Anthropic API key (or uses ANTHROPIC_API_KEY env var)
            model: Model to use for generation
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Anthropic API key required")

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model

    def generate_executive_summary(
        self,
        bill_title: str,
        bill_citation: str,
        enacted_date: str,
        sections_created: int,
        sections_amended: int,
        topic_breakdown: dict[str, int],
        predecessor_laws: list[dict],
        sample_sections: list[dict],
        funding_data: dict | None = None,
    ) -> ExecutiveSummary:
        """
        Generate an executive summary for a bill.

        Args:
            bill_title: Official title (e.g., "CHIPS and Science Act")
            bill_citation: Citation (e.g., "Pub. L. 117-167")
            enacted_date: When signed into law
            sections_created: Number of new sections
            sections_amended: Number of amended sections
            topic_breakdown: Dict of topic -> section count
            predecessor_laws: List of laws this builds upon
            sample_sections: Representative sections for context

        Returns:
            ExecutiveSummary with headline, overview, provisions, etc.
        """
        # Format funding information if available
        funding_section = ""
        if funding_data:
            funding_section = f"""
FUNDING AUTHORIZATIONS:
Total: {funding_data.get('total', 'Not specified')}
{self._format_funding_categories(funding_data.get('categories', []))}
Note: {funding_data.get('note', 'Authorization levels may differ from actual appropriations.')}
"""

        prompt = f"""You are a legislative analyst writing an executive summary for policy professionals.

Generate an executive summary for this legislation:

**{bill_title}** ({bill_citation})
Enacted: {enacted_date}

SCOPE:
- Created {sections_created} new sections of law
- Amended {sections_amended} existing sections
{funding_section}
TOPIC BREAKDOWN:
{self._format_topic_breakdown(topic_breakdown)}

BUILDS UPON THESE PRIOR LAWS:
{self._format_predecessors(predecessor_laws)}

SAMPLE SECTIONS CREATED/AMENDED:
{self._format_sample_sections(sample_sections)}

---

Write an executive summary with these components (use the exact headers):

HEADLINE:
[One punchy sentence that captures what this law does - suitable for a news headline]

OVERVIEW:
[2-3 paragraphs explaining what this law does, written for someone who follows policy but isn't a legal expert. Be specific about what it authorizes or changes. Don't just list topics - explain the substance. Include key funding figures.]

KEY PROVISIONS:
[5-7 bullet points of the most significant provisions, each 1-2 sentences. IMPORTANT: Include specific dollar amounts for provisions that have funding authorizations. Format amounts clearly (e.g., "$52.7 billion for semiconductor manufacturing incentives").]

WHY IT MATTERS:
[One paragraph on the significance and expected impact. Use hedged language for claims about future impact - say "is expected to," "may," "aims to" rather than asserting outcomes as fact.]

HISTORICAL CONTEXT:
[One paragraph on what led to this legislation - the policy problem it addresses, predecessor efforts, why now. Focus on verifiable facts about the legislative history and stated purposes rather than speculative claims.]

Be concrete and specific. Avoid generic language like "landmark legislation" or "historic investment" unless you explain why. Ground claims in the actual provisions. Use appropriate epistemic hedging for predictions and causal claims."""

        response = self._call_api(prompt)
        return self._parse_executive_summary(response)

    def generate_navigation_guide(
        self,
        bill_title: str,
        topic_groups: list[dict],
        most_amended_sections: list[dict],
        newest_sections: list[dict],
    ) -> NavigationGuide:
        """
        Generate a "start here" navigation guide.

        Args:
            bill_title: Title of the bill
            topic_groups: List of {topic, section_count, sample_sections}
            most_amended_sections: Sections with longest amendment history
            newest_sections: Recently created sections

        Returns:
            NavigationGuide with pathways, highlights, etc.
        """
        prompt = f"""You are helping someone navigate a complex piece of legislation: {bill_title}

Here's what the law covers:

TOPICS AND SECTIONS:
{self._format_topic_groups(topic_groups)}

SECTIONS WITH THE MOST LEGISLATIVE HISTORY (most frequently amended):
{self._format_amended_sections(most_amended_sections)}

NEWEST SECTIONS (created by this law):
{self._format_new_sections(newest_sections)}

---

Generate a navigation guide with these components (use exact headers):

PATHWAYS:
[Create 4-5 different "pathways" through the legislation based on different interests. Format each as:]
- IF YOU CARE ABOUT: [interest area]
  [1-2 sentence description of what you'll find]
  START WITH: [specific section citation]
  ALSO SEE: [2-3 other relevant sections]

MOST INTERESTING THREAD:
[One paragraph highlighting a noteworthy pattern or observation in this legislation. IMPORTANT: Use appropriate epistemic hedging - say "appears to suggest," "may indicate," "one possible interpretation," etc. Do NOT make strong causal claims without evidence. Focus on observable facts (amendment frequency, unexpected provisions) rather than speculative claims about intent or policy implications.]

Be specific. Don't just say "if you care about research funding" - say "if you want to understand how NSF's budget authority is changing" and point to the actual sections."""

        response = self._call_api(prompt)
        return self._parse_navigation_guide(response, most_amended_sections, newest_sections)

    def generate_section_context(
        self,
        section_citation: str,
        section_name: str,
        section_text: str,
        amendments: list[dict],
        related_sections: list[dict],
    ) -> SectionContext:
        """
        Generate rich context for a single section.

        Args:
            section_citation: e.g., "42 USC 1863"
            section_name: e.g., "National Science Board"
            section_text: The actual text (can be truncated)
            amendments: List of {public_law, date, title}
            related_sections: Other sections in same chapter/topic

        Returns:
            SectionContext with plain English explanation, etc.
        """
        # Truncate text if too long
        text_for_prompt = section_text[:3000] if section_text else "[Text not available]"

        prompt = f"""You are explaining a section of US law to a policy professional.

SECTION: {section_citation}
NAME: {section_name}

TEXT (may be truncated):
{text_for_prompt}

AMENDMENT HISTORY:
{self._format_amendments(amendments)}

RELATED SECTIONS:
{self._format_related_sections(related_sections)}

---

Generate context with these components (use exact headers):

PLAIN ENGLISH:
[2-3 sentences explaining what this section does in plain English. Be specific.]

WHY THIS EXISTS:
[1-2 sentences on the policy purpose - what problem does this solve or what function does it serve?]

CONNECTIONS:
[2-3 bullet points on how this relates to other sections or laws]

{"AMENDMENT STORY:" if amendments else ""}
{("[One paragraph telling the story of how this section has evolved through its amendments. What patterns do you see?]" if amendments else "")}

Be concrete. If you don't know something, say so rather than being vague."""

        response = self._call_api(prompt)
        return self._parse_section_context(response)

    def _call_api(self, prompt: str) -> str:
        """Make API call to Claude."""
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return message.content[0].text
        except Exception as e:
            logger.error(f"API call failed: {e}")
            raise

    def _format_topic_breakdown(self, topics: dict[str, int]) -> str:
        lines = []
        for topic, count in sorted(topics.items(), key=lambda x: -x[1]):
            lines.append(f"- {topic}: {count} sections")
        return "\n".join(lines)

    def _format_funding_categories(self, categories: list[dict]) -> str:
        """Format funding categories for the prompt."""
        lines = []
        for cat in categories:
            name = cat.get("name", "")
            amount = cat.get("amount", "")
            details = cat.get("details", "")
            lines.append(f"- {name}: {amount} - {details}")
        return "\n".join(lines) if lines else "Not specified"

    def _format_predecessors(self, laws: list[dict]) -> str:
        lines = []
        for law in laws:
            citation = law.get("citation", "Unknown")
            title = law.get("title", "")
            year = law.get("year", "")
            lines.append(f"- {citation}: {title} ({year})" if title else f"- {citation}")
        return "\n".join(lines) if lines else "None identified"

    def _format_sample_sections(self, sections: list[dict]) -> str:
        lines = []
        for s in sections[:10]:  # Limit to 10
            citation = s.get("citation", "")
            name = s.get("name", "")
            lines.append(f"- {citation}: {name}")
        return "\n".join(lines)

    def _format_topic_groups(self, groups: list[dict]) -> str:
        lines = []
        for g in groups:
            topic = g.get("topic", "Other")
            count = g.get("section_count", 0)
            samples = g.get("sample_sections", [])[:3]
            sample_str = ", ".join([s.get("name", s.get("citation", "")) for s in samples])
            lines.append(f"- {topic} ({count} sections): e.g., {sample_str}")
        return "\n".join(lines)

    def _format_amended_sections(self, sections: list[dict]) -> str:
        lines = []
        for s in sections[:5]:
            citation = s.get("citation", "")
            name = s.get("name", "")
            count = s.get("amendment_count", 0)
            lines.append(f"- {citation} ({name}): amended {count} times")
        return "\n".join(lines) if lines else "None identified"

    def _format_new_sections(self, sections: list[dict]) -> str:
        lines = []
        for s in sections[:5]:
            citation = s.get("citation", "")
            name = s.get("name", "")
            lines.append(f"- {citation}: {name}")
        return "\n".join(lines) if lines else "None identified"

    def _format_amendments(self, amendments: list[dict]) -> str:
        lines = []
        for a in amendments:
            pl = a.get("public_law", "")
            title = a.get("title", "")
            date = a.get("date", "")
            lines.append(f"- {date}: {pl} ({title})" if title else f"- {date}: {pl}")
        return "\n".join(lines) if lines else "No amendments recorded"

    def _format_related_sections(self, sections: list[dict]) -> str:
        lines = []
        for s in sections[:5]:
            citation = s.get("citation", "")
            name = s.get("name", "")
            lines.append(f"- {citation}: {name}")
        return "\n".join(lines) if lines else "None identified"

    def _parse_executive_summary(self, response: str) -> ExecutiveSummary:
        """Parse LLM response into ExecutiveSummary."""
        sections = self._split_by_headers(response)

        # Extract key provisions as bullet points
        key_provisions = []
        if "KEY PROVISIONS" in sections:
            for line in sections["KEY PROVISIONS"].split("\n"):
                line = line.strip()
                if line.startswith("- ") or line.startswith("• "):
                    key_provisions.append(line[2:])
                elif line and not line.isupper():
                    key_provisions.append(line)

        return ExecutiveSummary(
            headline=sections.get("HEADLINE", "").strip(),
            overview=sections.get("OVERVIEW", "").strip(),
            key_provisions=key_provisions[:7],
            why_it_matters=sections.get("WHY IT MATTERS", "").strip(),
            historical_context=sections.get("HISTORICAL CONTEXT", "").strip(),
        )

    def _parse_navigation_guide(
        self,
        response: str,
        most_amended: list[dict],
        newest: list[dict],
    ) -> NavigationGuide:
        """Parse LLM response into NavigationGuide."""
        sections = self._split_by_headers(response)
        logger.debug(f"Parsed sections headers: {list(sections.keys())}")

        # Parse pathways
        pathways = []
        if "PATHWAYS" in sections:
            logger.debug(f"PATHWAYS content:\n{sections['PATHWAYS'][:500]}")
            current_pathway = None
            for line in sections["PATHWAYS"].split("\n"):
                line = line.strip()
                # Handle both plain and markdown bold formats
                # e.g., "- IF YOU CARE ABOUT:" or "- **IF YOU CARE ABOUT:**"
                cleaned_line = line.replace("**", "").replace("*", "")
                if "IF YOU CARE ABOUT:" in cleaned_line.upper():
                    if current_pathway:
                        pathways.append(current_pathway)
                    # Extract interest after the colon
                    interest_part = cleaned_line.split(":", 1)[-1].strip() if ":" in cleaned_line else ""
                    current_pathway = NavigationGuide.PathwayOption(
                        interest=interest_part,
                        description="",
                        sections=[],
                        start_with="",
                    )
                elif current_pathway:
                    if "START WITH:" in line.upper():
                        current_pathway.start_with = line.split(":", 1)[-1].strip()
                    elif "ALSO SEE:" in line.upper():
                        also_see = line.split(":", 1)[-1].strip()
                        current_pathway.sections = [s.strip() for s in also_see.split(",")]
                    elif line and not line.startswith("-") and not line.startswith("*"):
                        # Append to description if it's not empty
                        if current_pathway.description:
                            current_pathway.description += " " + line
                        else:
                            current_pathway.description = line
            if current_pathway:
                pathways.append(current_pathway)

        return NavigationGuide(
            pathways=pathways,
            most_amended=most_amended[:5],
            newest=newest[:5],
            highlight=sections.get("MOST INTERESTING THREAD", "").strip(),
        )

    def _parse_section_context(self, response: str) -> SectionContext:
        """Parse LLM response into SectionContext."""
        sections = self._split_by_headers(response)

        # Extract connections as bullet points
        connections = []
        if "CONNECTIONS" in sections:
            for line in sections["CONNECTIONS"].split("\n"):
                line = line.strip()
                if line.startswith("- ") or line.startswith("• "):
                    connections.append(line[2:])

        return SectionContext(
            plain_english=sections.get("PLAIN ENGLISH", "").strip(),
            why_exists=sections.get("WHY THIS EXISTS", "").strip(),
            connections=connections,
            amendment_story=sections.get("AMENDMENT STORY", "").strip() or None,
        )

    def _split_by_headers(self, text: str) -> dict[str, str]:
        """Split response text by headers (handles markdown ## headers too)."""
        sections = {}
        current_header = None
        current_content = []

        for line in text.split("\n"):
            # Strip markdown header markers and clean up
            stripped = line.strip().lstrip("#").strip().rstrip(":")

            # Check if this is a header (all caps, possibly with colon)
            if stripped.isupper() and len(stripped) > 2 and len(stripped) < 50:
                if current_header:
                    sections[current_header] = "\n".join(current_content).strip()
                current_header = stripped
                current_content = []
            else:
                current_content.append(line)

        if current_header:
            sections[current_header] = "\n".join(current_content).strip()

        return sections


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    # Quick test
    narrator = BillNarrator()

    summary = narrator.generate_executive_summary(
        bill_title="CHIPS and Science Act",
        bill_citation="Pub. L. 117-167",
        enacted_date="August 9, 2022",
        sections_created=144,
        sections_amended=51,
        topic_breakdown={
            "NSF/Research": 156,
            "DOE/Energy": 15,
            "NIST/Standards": 7,
            "Semiconductors": 5,
            "Workforce": 6,
        },
        predecessor_laws=[
            {"citation": "Pub. L. 110-69", "title": "America COMPETES Act", "year": "2007"},
            {"citation": "Pub. L. 111-358", "title": "America COMPETES Reauthorization", "year": "2010"},
        ],
        sample_sections=[
            {"citation": "42 USC 18851", "name": "National Semiconductor Technology Center"},
            {"citation": "42 USC 1863", "name": "National Science Board"},
            {"citation": "42 USC 19107", "name": "CHIPS Research and Development"},
        ],
    )

    print("=== EXECUTIVE SUMMARY ===")
    print()
    print(f"HEADLINE: {summary.headline}")
    print()
    print(f"OVERVIEW:\n{summary.overview}")
    print()
    print("KEY PROVISIONS:")
    for p in summary.key_provisions:
        print(f"  • {p}")
    print()
    print(f"WHY IT MATTERS:\n{summary.why_it_matters}")
    print()
    print(f"HISTORICAL CONTEXT:\n{summary.historical_context}")
