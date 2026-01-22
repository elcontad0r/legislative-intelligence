"""
Tests for the LLM summarization layer.

These tests cover both the non-LLM functionality (trivial change detection,
model serialization, etc.) and mock-based tests for the LLM integration.

The summarizer is Tier 4 of the trustworthiness hierarchy - LLM-generated
content that requires appropriate hedging language.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock

from src.analysis.text_diff import SectionDiff, DiffResult, DiffChunk, ChunkType
from src.analysis.llm_summarizer import (
    AmendmentSummarizer,
    SummaryResult,
    ChainSummary,
    TrivialChangeResult,
    Confidence,
    RateLimiter,
    ANTHROPIC_AVAILABLE,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def differ():
    """Create a SectionDiff instance."""
    return SectionDiff()


@pytest.fixture
def sample_context():
    """Sample context for summarization."""
    return {
        "section_id": "42 USC 1395",
        "section_name": "Hospital insurance benefits for aged",
        "public_law_id": "Pub. L. 117-167",
        "public_law_title": "CHIPS and Science Act",
    }


@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic client for testing without API calls."""
    mock_client = Mock()
    mock_response = Mock()
    mock_response.content = [Mock(text=json.dumps({
        "summary": "This amendment appears to expand eligibility requirements.",
        "confidence": "high",
        "key_changes": ["Added new category", "Increased funding"],
        "is_technical": False,
    }))]
    mock_client.messages.create.return_value = mock_response
    return mock_client


# =============================================================================
# Model Serialization Tests
# =============================================================================


class TestSummaryResultSerialization:
    """Test SummaryResult model serialization."""

    def test_basic_serialization(self):
        """Test basic model serialization to dict/JSON."""
        result = SummaryResult(
            summary="This amendment appears to expand definitions.",
            confidence=Confidence.HIGH,
            key_changes=["Added term X", "Removed term Y"],
            hedging_note="Based on text comparison",
            section_id="42 USC 1395",
            public_law_id="Pub. L. 117-167",
        )

        # Test model_dump
        data = result.model_dump()
        assert data["summary"] == "This amendment appears to expand definitions."
        assert data["confidence"] == "high"
        assert len(data["key_changes"]) == 2

        # Test JSON serialization
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["confidence"] == "high"

    def test_optional_fields(self):
        """Test that optional fields default correctly."""
        result = SummaryResult(
            summary="Test summary",
            confidence=Confidence.MEDIUM,
        )

        assert result.key_changes == []
        assert result.hedging_note is None
        assert result.raw_diff_summary is None
        assert result.section_id is None

    def test_confidence_enum_values(self):
        """Test all confidence enum values serialize correctly."""
        for conf in Confidence:
            result = SummaryResult(summary="Test", confidence=conf)
            data = result.model_dump()
            assert data["confidence"] == conf.value


class TestChainSummarySerialization:
    """Test ChainSummary model serialization."""

    def test_basic_chain_summary(self):
        """Test ChainSummary serialization."""
        chain = ChainSummary(
            section_id="42 USC 1395",
            section_name="Hospital insurance",
            total_amendments=5,
            narrative="Section has evolved through 5 amendments.",
            overall_trend="gradual expansion",
        )

        data = chain.model_dump()
        assert data["total_amendments"] == 5
        assert data["overall_trend"] == "gradual expansion"
        assert "hedging_note" in data  # Default hedging note

    def test_chain_with_amendments_list(self):
        """Test ChainSummary with populated amendments list."""
        amendments = [
            {"date": "2020-01-01", "public_law_id": "Pub. L. 116-100", "summary": "First change"},
            {"date": "2022-06-15", "public_law_id": "Pub. L. 117-167", "summary": "Second change"},
        ]

        chain = ChainSummary(
            section_id="42 USC 1395",
            total_amendments=2,
            narrative="Two amendments over two years.",
            amendments=amendments,
        )

        data = chain.model_dump()
        assert len(data["amendments"]) == 2
        assert data["amendments"][0]["public_law_id"] == "Pub. L. 116-100"


class TestTrivialChangeResult:
    """Test TrivialChangeResult model."""

    def test_renumbering_result(self):
        """Test renumbering type result."""
        result = TrivialChangeResult(
            change_type="renumbering",
            description="Redesignation of subsections",
            section_id="42 USC 1395",
        )

        data = result.model_dump()
        assert data["change_type"] == "renumbering"
        assert "Redesignation" in data["description"]

    def test_all_change_types(self):
        """Test all valid change types."""
        valid_types = ["renumbering", "technical", "conforming", "empty"]

        for change_type in valid_types:
            result = TrivialChangeResult(
                change_type=change_type,
                description=f"Test {change_type}",
            )
            assert result.change_type == change_type


# =============================================================================
# Trivial Change Detection Tests (No LLM Required)
# =============================================================================


class TestTrivialChangeDetection:
    """Test trivial change detection without LLM calls."""

    def test_empty_diff_detection(self, differ, sample_context):
        """Test that empty diffs are detected as trivial."""
        # Create a diff with no changes
        diff_result = differ.diff_sections("Same text", "Same text")

        # We need to test the _check_trivial_change method
        # This requires either mocking or using the public interface
        assert not diff_result.has_changes

    def test_high_similarity_detection(self, differ):
        """Test that very high similarity diffs might be trivial."""
        old = "The Secretary shall establish standards for hospitals."
        new = "The Secretary shall establish standards for hospitals"  # Removed period

        diff_result = differ.diff_sections(old, new)

        # Very minor change should have high similarity
        assert diff_result.similarity_score > 0.95

    def test_renumbering_pattern(self, differ):
        """Test pattern detection for renumbering."""
        old = "(a) First item.\n(b) Second item."
        new = "(b) First item.\n(c) Second item."  # Renumbered

        diff_result = differ.diff_sections(old, new)

        # Should detect this as changes
        assert diff_result.has_changes


# =============================================================================
# Rate Limiter Tests
# =============================================================================


class TestRateLimiter:
    """Test rate limiter functionality."""

    def test_rate_limiter_creation(self):
        """Test rate limiter initialization."""
        limiter = RateLimiter(requests_per_minute=60.0)
        assert limiter.min_interval == 1.0  # 60/60 = 1 second

        limiter2 = RateLimiter(requests_per_minute=30.0)
        assert limiter2.min_interval == 2.0  # 60/30 = 2 seconds

    def test_rate_limiter_first_request_no_wait(self):
        """Test that first request doesn't wait."""
        import time

        limiter = RateLimiter(requests_per_minute=60.0)

        start = time.time()
        limiter.wait()
        elapsed = time.time() - start

        # First request should be nearly instant
        assert elapsed < 0.1


# =============================================================================
# LLM Summarizer Tests (Mocked)
# =============================================================================


@pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic package not available")
class TestAmendmentSummarizerMocked:
    """Test AmendmentSummarizer with mocked API calls."""

    def test_summarizer_initialization_requires_key(self):
        """Test that summarizer requires API key."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="API key required"):
                AmendmentSummarizer()

    def test_summarize_diff_with_mock(self, differ, sample_context, mock_anthropic_client):
        """Test summarize_diff with mocked API."""
        old = "(a) The Secretary shall establish standards."
        new = "(a) The Secretary shall establish comprehensive standards for all facilities."

        diff_result = differ.diff_sections(old, new)

        with patch("src.analysis.llm_summarizer.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_anthropic_client

            summarizer = AmendmentSummarizer(api_key="test-key")
            summarizer.client = mock_anthropic_client

            result = summarizer.summarize_diff(diff_result, sample_context)

            assert isinstance(result, (SummaryResult, TrivialChangeResult))
            if isinstance(result, SummaryResult):
                assert result.confidence in [Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW]

    def test_batch_summarize(self, differ, sample_context, mock_anthropic_client):
        """Test batch summarization."""
        diffs = [
            (differ.diff_sections("Old text 1", "New text 1"), sample_context),
            (differ.diff_sections("Old text 2", "New text 2"), sample_context),
        ]

        with patch("src.analysis.llm_summarizer.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_anthropic_client

            summarizer = AmendmentSummarizer(api_key="test-key")
            summarizer.client = mock_anthropic_client

            results = summarizer.batch_summarize(diffs)

            assert len(results) == 2
            for result in results:
                assert isinstance(result, (SummaryResult, TrivialChangeResult))


# =============================================================================
# Hedging Language Tests
# =============================================================================


class TestHedgingLanguage:
    """Test that appropriate hedging language is generated."""

    def test_high_confidence_hedging(self):
        """Test hedging note for high confidence."""
        result = SummaryResult(
            summary="Test summary",
            confidence=Confidence.HIGH,
            hedging_note="Based on text comparison; legislative intent may differ",
        )

        assert "text comparison" in result.hedging_note.lower()

    def test_low_confidence_hedging(self):
        """Test hedging note for low confidence."""
        result = SummaryResult(
            summary="Test summary",
            confidence=Confidence.LOW,
            hedging_note="Low confidence due to complex changes. Verify against legislative record.",
        )

        assert "verify" in result.hedging_note.lower() or "confidence" in result.hedging_note.lower()

    def test_chain_summary_always_has_hedging(self):
        """Test that ChainSummary always includes hedging."""
        chain = ChainSummary(
            section_id="42 USC 1395",
            total_amendments=1,
            narrative="Test narrative",
        )

        assert chain.hedging_note is not None
        assert len(chain.hedging_note) > 0
        # Should mention interpretation limitations
        assert "text analysis" in chain.hedging_note.lower() or "may differ" in chain.hedging_note.lower()


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_amendments_chain(self):
        """Test chain summary with no amendments."""
        chain = ChainSummary(
            section_id="42 USC 1395",
            total_amendments=0,
            narrative="No amendments found.",
            amendments=[],
        )

        assert chain.total_amendments == 0
        assert len(chain.amendments) == 0

    def test_single_amendment_chain(self):
        """Test chain summary with single amendment."""
        amendments = [{"date": "2022-01-01", "public_law_id": "Pub. L. 117-100"}]

        chain = ChainSummary(
            section_id="42 USC 1395",
            total_amendments=1,
            narrative="Single amendment.",
            amendments=amendments,
        )

        assert chain.total_amendments == 1

    def test_summary_result_with_empty_key_changes(self):
        """Test SummaryResult with empty key changes list."""
        result = SummaryResult(
            summary="Minor technical change",
            confidence=Confidence.LOW,
            key_changes=[],
        )

        assert result.key_changes == []
        data = result.model_dump()
        assert data["key_changes"] == []


# =============================================================================
# Integration Tests (Require API Key - Skipped by Default)
# =============================================================================


@pytest.mark.skip(reason="Requires ANTHROPIC_API_KEY - run manually with --run-integration")
class TestIntegration:
    """Integration tests that require actual API access."""

    def test_real_summarization(self, differ, sample_context):
        """Test real API summarization (requires API key)."""
        import os

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            pytest.skip("ANTHROPIC_API_KEY not set")

        old = "(a) The Secretary shall award grants to eligible institutions."
        new = """(a) The Secretary shall award grants to eligible institutions, including
        community colleges and minority-serving institutions."""

        diff_result = differ.diff_sections(old, new)

        summarizer = AmendmentSummarizer(api_key=api_key)
        result = summarizer.summarize_diff(diff_result, sample_context)

        assert isinstance(result, SummaryResult)
        assert result.summary
        assert result.confidence in [Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW]
