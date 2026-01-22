"""
Analysis tools for legislative intelligence.

This module provides utilities for analyzing and comparing legal text,
including section diffs, change detection, impact analysis, and
LLM-powered summarization.

Trustworthiness Tiers:
- Tier 3 (text_diff): Technical analysis with verifiable outputs
- Tier 4 (llm_summarizer): LLM-generated interpretations with hedging
"""

from .text_diff import SectionDiff, DiffResult, DiffChunk, ChunkType

# LLM summarizer is optional - requires anthropic package
try:
    from .llm_summarizer import (
        AmendmentSummarizer,
        SummaryResult,
        ChainSummary,
        TrivialChangeResult,
        Confidence,
    )
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False
    AmendmentSummarizer = None
    SummaryResult = None
    ChainSummary = None
    TrivialChangeResult = None
    Confidence = None

__all__ = [
    # Tier 3: Text diff
    "SectionDiff",
    "DiffResult",
    "DiffChunk",
    "ChunkType",
    # Tier 4: LLM summarization (optional)
    "AmendmentSummarizer",
    "SummaryResult",
    "ChainSummary",
    "TrivialChangeResult",
    "Confidence",
]
