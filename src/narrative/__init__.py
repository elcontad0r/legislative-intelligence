"""
Narrative Generation Module for Legislative Intelligence.

This module generates rich, human-readable narratives about laws and their history,
composing across all 5 trustworthiness tiers with explicit confidence levels.

TRUSTWORTHINESS TIERS:
- Tier 1: Definitive - Source credits with PL citations and dates
- Tier 2: High Confidence - PL titles from Congress.gov, official metadata
- Tier 3: Medium Confidence - Text diff analysis, computed changes
- Tier 4: Low Confidence - LLM-generated summaries (requires hedging)
- Tier 5: Speculative - External sources, news, analysis

Usage:
    from src.narrative import NarrativeGenerator

    generator = NarrativeGenerator(neo4j_store)

    # Generate story for a USC section
    story = generator.generate_section_story("42 USC 18851")
    print(story.to_markdown())

    # Generate story for CHIPS Act
    chips_story = generator.generate_chips_story()
    print(chips_story.to_markdown())
"""

from .generator import (
    NarrativeGenerator,
    NarrativeFact,
    SectionNarrative,
    AmendmentNarrative,
    LawNarrative,
    ChipsNarrative,
    TimelineEntry,
    TopicGroup,
    ConfidenceLevel,
)

__all__ = [
    "NarrativeGenerator",
    "NarrativeFact",
    "SectionNarrative",
    "AmendmentNarrative",
    "LawNarrative",
    "ChipsNarrative",
    "TimelineEntry",
    "TopicGroup",
    "ConfidenceLevel",
]
