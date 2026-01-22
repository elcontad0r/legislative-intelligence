"""
LLM Summarization Layer for Legislative Amendments.

This module provides tools for generating human-readable descriptions of
legislative amendments using LLM (Claude) summarization. It converts technical
diff results into plain English prose.

This is Tier 4 of the trustworthiness hierarchy - LLM-generated content that
requires appropriate hedging language to indicate uncertainty.

TRUSTWORTHINESS TIERS:
- Tier 1: Authoritative data (USC citations, Public Law numbers)
- Tier 2: Verifiable facts (enacted dates, amendment counts)
- Tier 3: Technical analysis (diff results, text comparisons)
- Tier 4: LLM-generated interpretation (this module) - requires hedging

Usage:
    from src.analysis.llm_summarizer import AmendmentSummarizer

    summarizer = AmendmentSummarizer()

    # Summarize a single diff
    result = summarizer.summarize_diff(diff_result, context={
        "section_id": "42 USC 1395",
        "section_name": "Hospital insurance benefits",
        "public_law_id": "Pub. L. 117-167",
        "public_law_title": "CHIPS and Science Act"
    })

    print(result.summary)
    # "This amendment appears to expand eligibility requirements..."
"""
from __future__ import annotations

import os
import time
import asyncio
import logging
from enum import Enum
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

load_dotenv()

# Import Anthropic client - handle import error gracefully
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    anthropic = None

from .text_diff import DiffResult, DiffChunk, ChunkType

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 30.0

# Rate limiting: Anthropic has varying limits, we'll be conservative
# Default tier: 50 requests/minute = ~0.83 requests/second
# We'll use 1 request per 1.2 seconds to be safe
REQUEST_INTERVAL_SECONDS = 1.2


# =============================================================================
# Data Models
# =============================================================================


class Confidence(str, Enum):
    """Confidence level for LLM-generated summaries."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SummaryResult(BaseModel):
    """
    Result of LLM summarization of a diff.

    Attributes:
        summary: 1-2 sentence plain English description of the change
        confidence: Assessment of how clearly the diff conveys meaning
        key_changes: Bullet points of main substantive changes
        hedging_note: Disclaimer about interpretation limitations
        raw_diff_summary: The technical diff summary for reference
        section_id: The USC section this summary is about
        public_law_id: The Public Law that made this change
    """
    summary: str = Field(
        description="1-2 sentence plain English description of what changed"
    )
    confidence: Confidence = Field(
        description="High/Medium/Low based on diff clarity"
    )
    key_changes: list[str] = Field(
        default_factory=list,
        description="Bullet points of main substantive changes"
    )
    hedging_note: str | None = Field(
        default=None,
        description="Disclaimer about interpretation limitations"
    )
    raw_diff_summary: str | None = Field(
        default=None,
        description="The technical diff summary for reference"
    )
    section_id: str | None = None
    public_law_id: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "summary": "This amendment appears to expand the definition of "
                           "eligible research institutions to include community colleges.",
                "confidence": "high",
                "key_changes": [
                    "Added 'community colleges' to list of eligible institutions",
                    "Increased authorization amount from $50M to $75M annually"
                ],
                "hedging_note": "Based on text comparison; legislative intent may differ",
                "section_id": "42 USC 1863",
                "public_law_id": "Pub. L. 117-167"
            }
        }
    }


class ChainSummary(BaseModel):
    """
    Summary of multiple amendments to a single section over time.

    Provides a narrative of how a section has evolved through
    successive legislative changes.
    """
    section_id: str
    section_name: str | None = None
    total_amendments: int
    narrative: str = Field(
        description="Narrative description of how section evolved"
    )
    amendments: list[dict] = Field(
        default_factory=list,
        description="List of individual amendment summaries with dates"
    )
    overall_trend: str | None = Field(
        default=None,
        description="Description of overall direction of changes"
    )
    hedging_note: str = Field(
        default="This narrative is generated from text analysis. "
                "Legislative intent and practical effects may differ from "
                "what text changes alone suggest."
    )


class TrivialChangeResult(BaseModel):
    """Result for trivial/technical amendments that don't need full summarization."""
    change_type: Literal["renumbering", "technical", "conforming", "empty"]
    description: str
    section_id: str | None = None
    public_law_id: str | None = None


# =============================================================================
# Prompts
# =============================================================================

DIFF_SUMMARY_SYSTEM_PROMPT = """You are a legislative analyst summarizing statutory amendments.

Your task is to convert technical text diffs into clear, plain English descriptions
of what changed in the law. Focus on WHAT changed, not WHY (we don't have reliable
information about legislative intent).

Guidelines:
1. Use hedging language for uncertainty: "appears to", "based on the text", "seems to"
2. Extract concrete changes: dollar amounts, dates, definitions, scope expansions/contractions
3. Be concise - 1-2 sentences for the main summary
4. Note when changes are technical (renumbering, conforming amendments) vs substantive
5. Flag when the diff is complex or unclear

Do NOT:
- Speculate about legislative intent or political motivations
- Make claims about practical effects without textual support
- Use legal jargon unnecessarily
- Make definitive statements when the change is ambiguous"""

DIFF_SUMMARY_USER_TEMPLATE = """Summarize this statutory amendment:

CONTEXT:
- Section: {section_id} ({section_name})
- Amended by: {public_law_id} ({public_law_title})

DIFF STATISTICS:
- Similarity score: {similarity_score:.1%}
- Words added: {words_added}
- Words removed: {words_removed}
- Subsections affected: {paragraphs_affected}
- Technical summary: {technical_summary}

CHANGES DETECTED:
{changes_text}

Provide your analysis as JSON with these fields:
- summary: 1-2 sentence plain English description
- confidence: "high", "medium", or "low"
- key_changes: list of bullet points (max 5)
- is_technical: true if this is just renumbering/conforming amendments

Respond ONLY with valid JSON, no other text."""

CHAIN_SUMMARY_SYSTEM_PROMPT = """You are a legislative historian describing how a statute
has evolved over time through multiple amendments.

Your task is to synthesize individual amendment summaries into a coherent narrative
of the section's evolution. Focus on patterns and trends in the changes.

Guidelines:
1. Note the overall direction: expansion, contraction, clarification, etc.
2. Highlight significant turning points
3. Use hedging language - you're interpreting text changes, not legislative intent
4. Keep the narrative accessible to non-lawyers"""

CHAIN_SUMMARY_USER_TEMPLATE = """Create a narrative summary of how this section has evolved:

SECTION: {section_id} ({section_name})

AMENDMENT HISTORY (chronological):
{amendments_text}

Provide your analysis as JSON with these fields:
- narrative: A 2-4 sentence description of how this section evolved
- overall_trend: One phrase describing the direction (e.g., "gradual expansion", "increased specificity")

Respond ONLY with valid JSON, no other text."""


# =============================================================================
# Rate Limiter
# =============================================================================


class RateLimiter:
    """Simple token bucket rate limiter for API calls."""

    def __init__(self, requests_per_minute: float = 50.0):
        self.min_interval = 60.0 / requests_per_minute
        self.last_request_time = 0.0
        self._lock = asyncio.Lock() if asyncio.get_event_loop().is_running() else None

    def wait(self) -> None:
        """Synchronous wait to respect rate limit."""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()

    async def wait_async(self) -> None:
        """Asynchronous wait to respect rate limit."""
        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self.last_request_time = time.time()


# =============================================================================
# Main Summarizer Class
# =============================================================================


class AmendmentSummarizer:
    """
    LLM-powered summarizer for legislative amendments.

    Converts technical diff results into human-readable descriptions
    using Claude. All output includes appropriate hedging language
    to indicate this is Tier 4 (LLM-generated) content.

    Usage:
        summarizer = AmendmentSummarizer()

        result = summarizer.summarize_diff(diff_result, context={
            "section_id": "42 USC 1395",
            "section_name": "Hospital insurance benefits",
            "public_law_id": "Pub. L. 117-167",
            "public_law_title": "CHIPS and Science Act"
        })

        print(result.summary)
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        requests_per_minute: float = 50.0,
    ):
        """
        Initialize the summarizer.

        Args:
            model: Claude model to use (default: claude-sonnet-4-20250514)
            api_key: Anthropic API key (or uses ANTHROPIC_API_KEY env var)
            requests_per_minute: Rate limit for API calls
        """
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "The 'anthropic' package is required for LLM summarization. "
                "Install it with: pip install anthropic"
            )

        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. "
                "Set ANTHROPIC_API_KEY environment variable or pass api_key parameter."
            )

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.rate_limiter = RateLimiter(requests_per_minute)

        # Track statistics
        self.stats = {
            "total_summarized": 0,
            "high_confidence": 0,
            "medium_confidence": 0,
            "low_confidence": 0,
            "trivial_changes": 0,
            "errors": 0,
        }

    def summarize_diff(
        self,
        diff_result: DiffResult,
        context: dict,
    ) -> SummaryResult | TrivialChangeResult:
        """
        Generate a human-readable summary of a diff.

        Args:
            diff_result: The DiffResult from text_diff module
            context: Dict with section_id, section_name, public_law_id, public_law_title

        Returns:
            SummaryResult with LLM-generated summary, or TrivialChangeResult if trivial
        """
        section_id = context.get("section_id", "Unknown section")
        section_name = context.get("section_name", "")
        public_law_id = context.get("public_law_id", "Unknown law")
        public_law_title = context.get("public_law_title", "")

        # Handle trivial cases without LLM call
        trivial_result = self._check_trivial_change(diff_result, context)
        if trivial_result:
            self.stats["trivial_changes"] += 1
            return trivial_result

        # Build changes text for the prompt
        changes_text = self._format_changes_for_prompt(diff_result)

        # Build the user prompt
        user_prompt = DIFF_SUMMARY_USER_TEMPLATE.format(
            section_id=section_id,
            section_name=section_name or "untitled section",
            public_law_id=public_law_id,
            public_law_title=public_law_title or "untitled",
            similarity_score=diff_result.similarity_score,
            words_added=diff_result.words_added,
            words_removed=diff_result.words_removed,
            paragraphs_affected=diff_result.paragraphs_affected,
            technical_summary=diff_result.summary,
            changes_text=changes_text,
        )

        # Make the API call with rate limiting and retries
        try:
            response = self._call_api(
                system_prompt=DIFF_SUMMARY_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )

            # Parse the response
            result = self._parse_summary_response(response, diff_result, context)

            # Update stats
            self.stats["total_summarized"] += 1
            self.stats[f"{result.confidence.value}_confidence"] += 1

            return result

        except Exception as e:
            logger.error(f"Error summarizing diff for {section_id}: {e}")
            self.stats["errors"] += 1

            # Return a fallback result
            return SummaryResult(
                summary=f"Unable to generate summary: {diff_result.summary}",
                confidence=Confidence.LOW,
                key_changes=[],
                hedging_note="Automatic summarization failed. Technical diff summary shown instead.",
                raw_diff_summary=diff_result.summary,
                section_id=section_id,
                public_law_id=public_law_id,
            )

    def summarize_amendment_chain(
        self,
        amendments: list[dict],
        section_id: str,
        section_name: str | None = None,
    ) -> ChainSummary:
        """
        Summarize multiple amendments to one section over time.

        Args:
            amendments: List of dicts with keys: date, public_law_id, summary
            section_id: The USC section being summarized
            section_name: Optional section title

        Returns:
            ChainSummary with narrative of section's evolution
        """
        if not amendments:
            return ChainSummary(
                section_id=section_id,
                section_name=section_name,
                total_amendments=0,
                narrative="No amendments found for this section.",
                amendments=[],
            )

        if len(amendments) == 1:
            amend = amendments[0]
            return ChainSummary(
                section_id=section_id,
                section_name=section_name,
                total_amendments=1,
                narrative=f"This section has been amended once, by {amend.get('public_law_id', 'an unknown law')}. "
                          f"{amend.get('summary', '')}",
                amendments=amendments,
                overall_trend="single amendment",
            )

        # Format amendments for prompt
        amendments_text = "\n".join([
            f"- {amend.get('date', 'Unknown date')}: {amend.get('public_law_id', 'Unknown')}\n"
            f"  {amend.get('summary', 'No summary available')}"
            for amend in amendments
        ])

        user_prompt = CHAIN_SUMMARY_USER_TEMPLATE.format(
            section_id=section_id,
            section_name=section_name or "untitled section",
            amendments_text=amendments_text,
        )

        try:
            response = self._call_api(
                system_prompt=CHAIN_SUMMARY_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )

            return self._parse_chain_response(
                response, amendments, section_id, section_name
            )

        except Exception as e:
            logger.error(f"Error summarizing amendment chain for {section_id}: {e}")

            # Fallback response
            return ChainSummary(
                section_id=section_id,
                section_name=section_name,
                total_amendments=len(amendments),
                narrative=f"This section has been amended {len(amendments)} times. "
                          "Unable to generate detailed narrative.",
                amendments=amendments,
                hedging_note="Automatic narrative generation failed.",
            )

    def batch_summarize(
        self,
        items: list[tuple[DiffResult, dict]],
    ) -> list[SummaryResult | TrivialChangeResult]:
        """
        Efficiently summarize multiple diffs.

        Args:
            items: List of (DiffResult, context) tuples

        Returns:
            List of SummaryResult or TrivialChangeResult objects
        """
        results = []

        for diff_result, context in items:
            result = self.summarize_diff(diff_result, context)
            results.append(result)

        return results

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _check_trivial_change(
        self,
        diff_result: DiffResult,
        context: dict,
    ) -> TrivialChangeResult | None:
        """Check if this is a trivial change that doesn't need LLM summarization."""
        section_id = context.get("section_id")
        public_law_id = context.get("public_law_id")

        # Empty diff
        if not diff_result.has_changes:
            return TrivialChangeResult(
                change_type="empty",
                description="No substantive changes detected.",
                section_id=section_id,
                public_law_id=public_law_id,
            )

        # Very high similarity with only minor modifications
        if diff_result.similarity_score > 0.98:
            # Check if it's just punctuation or whitespace
            total_word_change = diff_result.words_added + diff_result.words_removed
            if total_word_change < 5:
                return TrivialChangeResult(
                    change_type="technical",
                    description="Technical amendment with minimal text changes (punctuation, formatting).",
                    section_id=section_id,
                    public_law_id=public_law_id,
                )

        # Check for renumbering patterns
        if self._is_renumbering(diff_result):
            return TrivialChangeResult(
                change_type="renumbering",
                description="Renumbering or redesignation of subsections.",
                section_id=section_id,
                public_law_id=public_law_id,
            )

        return None

    def _is_renumbering(self, diff_result: DiffResult) -> bool:
        """Check if the diff represents just renumbering of subsections."""
        # Look for patterns like (a) -> (b), (1) -> (2)
        import re
        subsection_pattern = re.compile(r'^\s*\([a-zA-Z0-9]+\)\s*$')

        renumber_count = 0
        total_changes = len(diff_result.modifications)

        if total_changes == 0:
            return False

        for mod in diff_result.modifications:
            old = (mod.old_text or "").strip()
            new = mod.text.strip()

            # Check if both old and new are just subsection labels
            if subsection_pattern.match(old) and subsection_pattern.match(new):
                renumber_count += 1

        # If more than 80% of modifications are just renumbering
        return renumber_count / total_changes > 0.8 if total_changes > 0 else False

    def _format_changes_for_prompt(self, diff_result: DiffResult) -> str:
        """Format the diff changes into text for the LLM prompt."""
        lines = []

        if diff_result.additions:
            lines.append("ADDITIONS:")
            for chunk in diff_result.additions[:10]:  # Limit to avoid huge prompts
                subsection = f" [in {chunk.subsection}]" if chunk.subsection else ""
                lines.append(f"  + {chunk.text[:500]}{subsection}")

        if diff_result.deletions:
            lines.append("\nDELETIONS:")
            for chunk in diff_result.deletions[:10]:
                subsection = f" [in {chunk.subsection}]" if chunk.subsection else ""
                lines.append(f"  - {chunk.text[:500]}{subsection}")

        if diff_result.modifications:
            lines.append("\nMODIFICATIONS:")
            for chunk in diff_result.modifications[:10]:
                subsection = f" [in {chunk.subsection}]" if chunk.subsection else ""
                lines.append(f"  OLD: {(chunk.old_text or '')[:250]}")
                lines.append(f"  NEW: {chunk.text[:250]}{subsection}")
                lines.append("")

        return "\n".join(lines) if lines else "No detailed changes available."

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=BASE_DELAY_SECONDS, max=MAX_DELAY_SECONDS),
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIConnectionError)) if ANTHROPIC_AVAILABLE else (Exception,),
    )
    def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        """Make an API call with rate limiting and retries."""
        self.rate_limiter.wait()

        message = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

        return message.content[0].text

    def _parse_summary_response(
        self,
        response: str,
        diff_result: DiffResult,
        context: dict,
    ) -> SummaryResult:
        """Parse the LLM response into a SummaryResult."""
        import json

        section_id = context.get("section_id")
        public_law_id = context.get("public_law_id")

        try:
            # Try to extract JSON from the response
            # Handle potential markdown code blocks
            response_text = response.strip()
            if response_text.startswith("```"):
                # Remove markdown code blocks
                lines = response_text.split("\n")
                response_text = "\n".join(
                    line for line in lines
                    if not line.startswith("```")
                )

            data = json.loads(response_text)

            # Map confidence string to enum
            confidence_str = data.get("confidence", "medium").lower()
            confidence_map = {
                "high": Confidence.HIGH,
                "medium": Confidence.MEDIUM,
                "low": Confidence.LOW,
            }
            confidence = confidence_map.get(confidence_str, Confidence.MEDIUM)

            # Build key changes list
            key_changes = data.get("key_changes", [])
            if isinstance(key_changes, str):
                key_changes = [key_changes]

            # Determine hedging note based on confidence
            hedging_note = self._generate_hedging_note(confidence, diff_result)

            return SummaryResult(
                summary=data.get("summary", diff_result.summary),
                confidence=confidence,
                key_changes=key_changes[:5],  # Cap at 5
                hedging_note=hedging_note,
                raw_diff_summary=diff_result.summary,
                section_id=section_id,
                public_law_id=public_law_id,
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")

            # Fallback: use the raw response as summary
            return SummaryResult(
                summary=response[:500] if len(response) > 500 else response,
                confidence=Confidence.LOW,
                key_changes=[],
                hedging_note="Response format was unexpected. Summary may be incomplete.",
                raw_diff_summary=diff_result.summary,
                section_id=section_id,
                public_law_id=public_law_id,
            )

    def _parse_chain_response(
        self,
        response: str,
        amendments: list[dict],
        section_id: str,
        section_name: str | None,
    ) -> ChainSummary:
        """Parse the LLM response for chain summary."""
        import json

        try:
            response_text = response.strip()
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(
                    line for line in lines
                    if not line.startswith("```")
                )

            data = json.loads(response_text)

            return ChainSummary(
                section_id=section_id,
                section_name=section_name,
                total_amendments=len(amendments),
                narrative=data.get("narrative", "Unable to generate narrative."),
                amendments=amendments,
                overall_trend=data.get("overall_trend"),
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse chain summary response: {e}")

            return ChainSummary(
                section_id=section_id,
                section_name=section_name,
                total_amendments=len(amendments),
                narrative=response[:500] if len(response) > 500 else response,
                amendments=amendments,
            )

    def _generate_hedging_note(
        self,
        confidence: Confidence,
        diff_result: DiffResult,
    ) -> str:
        """Generate appropriate hedging language based on confidence."""
        if confidence == Confidence.HIGH:
            return "Based on text comparison; legislative intent may differ from textual changes."

        elif confidence == Confidence.MEDIUM:
            if diff_result.change_magnitude == "substantial":
                return (
                    "This summary is based on text analysis of substantial changes. "
                    "The actual scope and effect of the amendment may be broader or "
                    "narrower than what the text comparison suggests."
                )
            else:
                return (
                    "Based on text comparison. Some aspects of this amendment "
                    "may not be fully captured by the textual analysis."
                )

        else:  # LOW
            reasons = []
            if diff_result.change_magnitude == "major":
                reasons.append("extensive restructuring")
            if diff_result.paragraphs_affected > 5:
                reasons.append("many affected subsections")
            if diff_result.similarity_score < 0.5:
                reasons.append("significant text replacement")

            reason_text = ", ".join(reasons) if reasons else "complex changes"
            return (
                f"Low confidence summary due to {reason_text}. "
                "This interpretation should be verified against the full legislative record."
            )


# =============================================================================
# CLI Entry Point
# =============================================================================


def main():
    """CLI entry point for testing the summarizer."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Test LLM summarization of legislative amendments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.analysis.llm_summarizer --section "42 USC 1863" --law "Pub. L. 117-167"
  python -m src.analysis.llm_summarizer --test
        """,
    )

    parser.add_argument(
        "--section",
        type=str,
        help="USC section to summarize (e.g., '42 USC 1863')",
    )
    parser.add_argument(
        "--law",
        type=str,
        help="Public Law that amended it (e.g., 'Pub. L. 117-167')",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run with sample data to test the summarizer",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Claude model to use (default: {DEFAULT_MODEL})",
    )

    args = parser.parse_args()

    if not any([args.section, args.test]):
        parser.print_help()
        sys.exit(1)

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    if args.test:
        # Run with sample data
        console.print("\n[bold blue]Running LLM Summarizer Test[/bold blue]\n")

        from .text_diff import SectionDiff

        # Sample legal text changes
        old_section = """
(a) GENERAL RULE.--Every individual shall have access to health insurance
coverage through an Exchange established under this title.

(1) QUALIFIED INDIVIDUALS.--A qualified individual means an individual who--
    (A) is a citizen or national of the United States or an alien lawfully
    present in the United States;
    (B) is not incarcerated; and
    (C) resides in the State that established the Exchange.
"""

        new_section = """
(a) GENERAL RULE.--Every individual shall have access to affordable health
insurance coverage through an Exchange established under this title.

(1) QUALIFIED INDIVIDUALS.--A qualified individual means an individual who--
    (A) is a citizen or national of the United States or an alien lawfully
    present in the United States;
    (B) is not incarcerated;
    (C) resides in the State that established the Exchange; and
    (D) meets applicable income requirements as determined by the Secretary.

(2) AFFORDABILITY WAIVER.--The Secretary may waive requirements under this
subsection for individuals for whom coverage would exceed 8 percent of
household income.
"""

        # Generate diff
        differ = SectionDiff()
        diff_result = differ.diff_sections(old_section, new_section)

        console.print("[dim]Generated diff:[/dim]")
        console.print(f"  Similarity: {diff_result.similarity_score:.1%}")
        console.print(f"  Changes: {diff_result.summary}\n")

        # Summarize
        try:
            summarizer = AmendmentSummarizer(model=args.model)

            context = {
                "section_id": "42 USC 18031",
                "section_name": "Affordable Care Act Exchange Requirements",
                "public_law_id": "Pub. L. 111-148",
                "public_law_title": "Patient Protection and Affordable Care Act",
            }

            console.print("[dim]Calling LLM for summary...[/dim]\n")
            result = summarizer.summarize_diff(diff_result, context)

            # Display result
            if isinstance(result, TrivialChangeResult):
                console.print(Panel(
                    f"[yellow]Trivial Change Detected[/yellow]\n\n"
                    f"Type: {result.change_type}\n"
                    f"Description: {result.description}",
                    title="Summary Result",
                ))
            else:
                table = Table(title="Amendment Summary")
                table.add_column("Field", style="cyan")
                table.add_column("Value", style="white")

                table.add_row("Summary", result.summary)
                table.add_row("Confidence", result.confidence.value)
                table.add_row("Key Changes", "\n".join(f"- {c}" for c in result.key_changes) or "None")
                table.add_row("Hedging Note", result.hedging_note or "None")

                console.print(table)

            console.print(f"\n[green]Test completed successfully![/green]")

        except ImportError as e:
            console.print(f"[red]Import error: {e}[/red]")
            console.print("[yellow]Install anthropic with: pip install anthropic[/yellow]")
            sys.exit(1)
        except ValueError as e:
            console.print(f"[red]Configuration error: {e}[/red]")
            sys.exit(1)

    else:
        # Real usage with section and law
        if not args.law:
            console.print("[red]--law is required when --section is specified[/red]")
            sys.exit(1)

        console.print(f"\n[bold blue]Summarizing amendment to {args.section}[/bold blue]")
        console.print(f"[dim]By {args.law}[/dim]\n")

        # Note: In real usage, you would fetch the actual diff from Neo4j
        # This is just a demonstration
        console.print("[yellow]Note: This CLI is for testing. In production, diffs would be fetched from the database.[/yellow]")
        console.print("[dim]Use --test to run with sample data.[/dim]")


if __name__ == "__main__":
    main()
