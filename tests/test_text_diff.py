"""
Tests for the text diff engine.

The diff engine is critical for Tier 3 trustworthiness - showing users
exactly what changed in statutory text when laws are amended.
"""

import pytest
from src.analysis.text_diff import (
    SectionDiff,
    DiffResult,
    DiffChunk,
    ChunkType,
    AmendmentParser,
    AmendmentInstruction,
    diff_sections,
    diff_from_amendment,
)


@pytest.fixture
def differ():
    return SectionDiff()


@pytest.fixture
def amendment_parser():
    return AmendmentParser()


# =============================================================================
# Basic Diff Tests
# =============================================================================


class TestBasicDiff:
    """Test basic diff functionality."""

    def test_identical_text(self, differ):
        """Test that identical text returns no changes."""
        text = "The Secretary shall establish standards."
        result = differ.diff_sections(text, text)

        assert result.similarity_score == 1.0
        assert not result.has_changes
        assert result.change_magnitude == "none"

    def test_whitespace_only_changes(self, differ):
        """Test that whitespace-only changes are detected but minimal."""
        old = "The   Secretary shall   establish standards."
        new = "The Secretary shall establish standards."

        result = differ.diff_sections(old, new)

        # Should normalize and recognize as effectively unchanged
        assert result.similarity_score == 1.0
        assert "whitespace" in result.summary.lower()

    def test_empty_old_text(self, differ):
        """Test new section (empty old text)."""
        new_text = "This is a new section with 10 words in it."
        result = differ.diff_sections("", new_text)

        assert result.similarity_score == 0.0
        assert len(result.additions) == 1
        assert "New section" in result.summary

    def test_empty_new_text(self, differ):
        """Test deleted section (empty new text)."""
        old_text = "This section has been removed entirely."
        result = differ.diff_sections(old_text, "")

        assert result.similarity_score == 0.0
        assert len(result.deletions) == 1
        assert "deleted" in result.summary.lower()

    def test_both_empty(self, differ):
        """Test both texts empty."""
        result = differ.diff_sections("", "")
        assert "empty" in result.summary.lower()


class TestLegalTextQuirks:
    """Test handling of legal text formatting quirks."""

    def test_subsection_detection(self, differ):
        """Test detection of subsection identifiers."""
        old = "(a) First subsection.\n(b) Second subsection."
        new = "(a) Modified first subsection.\n(b) Second subsection."

        result = differ.diff_sections(old, new)

        assert result.has_changes
        # Should detect the (a) subsection was modified
        modified_subsections = [c.subsection for c in result.modifications if c.subsection]
        # The subsection detection should work
        assert any("(a)" in (s or "") for s in modified_subsections) or len(result.modifications) > 0

    def test_nested_subsections(self, differ):
        """Test handling of deeply nested subsections."""
        old = """
(a)(1)(A) First item.
(a)(1)(B) Second item.
(a)(2) Another item.
"""
        new = """
(a)(1)(A) First item.
(a)(1)(B) Modified second item with new language.
(a)(2) Another item.
"""
        result = differ.diff_sections(old, new)
        assert result.has_changes

    def test_quote_normalization(self, differ):
        """Test that various quote styles are normalized."""
        old = 'The term "qualified" means...'  # straight quotes
        new = 'The term "qualified" means...'  # curly quotes

        result = differ.diff_sections(old, new)
        # Should treat as identical after normalization
        assert result.similarity_score == 1.0

    def test_dash_normalization(self, differ):
        """Test that various dash types are normalized."""
        old = "health care-related factors"  # hyphen
        new = "health care–related factors"  # en-dash

        result = differ.diff_sections(old, new)
        assert result.similarity_score == 1.0


class TestChangeDetection:
    """Test accurate change detection."""

    def test_word_addition(self, differ):
        """Test detection of added words."""
        old = "The Secretary shall establish standards."
        new = "The Secretary shall establish appropriate standards."

        result = differ.diff_sections(old, new)

        assert result.has_changes
        assert result.new_word_count > result.old_word_count

    def test_word_deletion(self, differ):
        """Test detection of removed words."""
        old = "The Secretary shall immediately establish standards."
        new = "The Secretary shall establish standards."

        result = differ.diff_sections(old, new)

        assert result.has_changes
        assert result.old_word_count > result.new_word_count

    def test_word_replacement(self, differ):
        """Test detection of replaced words."""
        old = "shall establish minimum standards"
        new = "shall establish maximum standards"

        result = differ.diff_sections(old, new)

        assert result.has_changes
        # Should be detected as modification since structure is similar
        assert len(result.modifications) > 0 or len(result.additions) > 0

    def test_paragraph_addition(self, differ):
        """Test detection of added paragraph."""
        old = "(a) First paragraph.\n(b) Second paragraph."
        new = "(a) First paragraph.\n(b) Second paragraph.\n(c) Third paragraph."

        result = differ.diff_sections(old, new)

        assert result.has_changes
        assert len(result.additions) > 0

    def test_similarity_score_ranges(self, differ):
        """Test that similarity scores are in reasonable ranges."""
        # Minor change
        old = "The Secretary shall establish standards for qualified health plans."
        new = "The Secretary shall establish standards for all qualified health plans."
        result = differ.diff_sections(old, new)
        assert result.similarity_score > 0.8

        # Major change
        old = "Section one content goes here."
        new = "Completely different unrelated text."
        result = differ.diff_sections(old, new)
        assert result.similarity_score < 0.5


class TestChangeMagnitude:
    """Test change magnitude classification."""

    def test_minor_change(self, differ):
        """Test minor change classification."""
        # Over 95% similar
        old = "The Secretary shall establish standards for all plans."
        new = "The Secretary shall establish standards for every plans."  # tiny change

        result = differ.diff_sections(old, new)
        # High similarity expected for tiny change
        assert result.change_magnitude in ("minor", "moderate", "none")

    def test_substantial_change(self, differ):
        """Test substantial change classification."""
        old = "Short text."
        new = "Short text. With a lot more content added that substantially changes the section."

        result = differ.diff_sections(old, new)
        assert result.change_magnitude in ("substantial", "major", "moderate")


# =============================================================================
# Amendment Parsing Tests
# =============================================================================


class TestAmendmentParsing:
    """Test parsing of Public Law amendment instructions."""

    def test_strike_and_insert(self, amendment_parser):
        """Test parsing 'strike X and insert Y' pattern."""
        text = 'by striking "health status" and inserting "medical condition"'
        instructions = amendment_parser.parse(text)

        assert len(instructions) == 1
        instr = instructions[0]
        assert instr.instruction_type == "strike_insert"
        assert instr.strike_text == "health status"
        assert instr.insert_text == "medical condition"

    def test_insert_after(self, amendment_parser):
        """Test parsing 'insert X after Y' pattern."""
        text = 'by inserting "or guardian" after "parent"'
        instructions = amendment_parser.parse(text)

        assert len(instructions) == 1
        instr = instructions[0]
        assert instr.instruction_type == "insert_after"
        assert instr.insert_text == "or guardian"
        assert "parent" in instr.position_reference

    def test_add_at_end(self, amendment_parser):
        """Test parsing 'add at the end' pattern."""
        text = 'by adding at the end the following: "The Secretary shall issue regulations."'
        instructions = amendment_parser.parse(text)

        assert len(instructions) == 1
        instr = instructions[0]
        assert instr.instruction_type == "add_end"
        assert "regulations" in instr.insert_text

    def test_redesignate(self, amendment_parser):
        """Test parsing redesignation pattern."""
        text = "by redesignating subsection (c) as subsection (d)"
        instructions = amendment_parser.parse(text)

        assert len(instructions) == 1
        instr = instructions[0]
        assert instr.instruction_type == "redesignate"
        assert "(c)" in instr.strike_text
        assert "(d)" in instr.insert_text

    def test_section_reference_extraction(self, amendment_parser):
        """Test extraction of section references."""
        text = """
        Section 2702(a)(1) of the Public Health Service Act is amended
        by striking "factor" and inserting "condition".
        """
        instructions = amendment_parser.parse(text)

        assert len(instructions) == 1
        # Should associate with the section reference
        assert instructions[0].target_section is not None

    def test_multiple_instructions(self, amendment_parser):
        """Test parsing multiple amendment instructions."""
        text = """
        Section 1001 is amended--
        (1) by striking "shall" and inserting "may";
        (2) by inserting "qualified" after "each"; and
        (3) by adding at the end the following: "Effective immediately."
        """
        instructions = amendment_parser.parse(text)

        assert len(instructions) == 3
        types = [i.instruction_type for i in instructions]
        assert "strike_insert" in types
        assert "insert_after" in types
        assert "add_end" in types


class TestDiffFromAmendment:
    """Test reconstructing diffs from amendment instructions."""

    def test_basic_amendment_diff(self, differ):
        """Test creating diff from amendment text."""
        current = "The Secretary may establish standards."
        amendment = 'Section 100 is amended by striking "shall" and inserting "may".'

        result = differ.diff_from_amendment(current, amendment)

        assert "[From amendment instructions]" in result.summary
        assert len(result.modifications) > 0

    def test_amendment_with_additions(self, differ):
        """Test amendment that adds text."""
        current = "Full text here."
        amendment = 'by adding at the end the following: "Effective January 1."'

        result = differ.diff_from_amendment(current, amendment)

        assert len(result.additions) > 0

    def test_unparseable_amendment(self, differ):
        """Test handling of unparseable amendment text."""
        current = "Some text."
        amendment = "This doesn't contain any recognizable amendment patterns."

        result = differ.diff_from_amendment(current, amendment)

        assert "Could not parse" in result.summary


# =============================================================================
# Summary Generation Tests
# =============================================================================


class TestSummaryGeneration:
    """Test human-readable summary generation."""

    def test_summary_content(self, differ):
        """Test that summary contains useful information."""
        old = "Original text here."
        new = "Modified text here with additions."

        result = differ.diff_sections(old, new)

        # Summary should mention the type of change
        assert any(word in result.summary.lower() for word in ["modified", "added", "deleted", "passage"])

    def test_summary_word_counts(self, differ):
        """Test that summary includes word count changes."""
        old = "Short text."
        new = "Short text with many more words added here."

        result = differ.diff_sections(old, new)

        # Should mention word changes if significant
        assert "word" in result.summary.lower() or result.words_added > 0

    def test_summary_for_no_changes(self, differ):
        """Test summary when no changes detected."""
        text = "Identical text."
        result = differ.diff_sections(text, text)

        assert "no" in result.summary.lower() or "unchanged" in result.summary.lower()


# =============================================================================
# Real-World Legal Text Tests
# =============================================================================


class TestRealWorldExamples:
    """Test with realistic legal text examples."""

    def test_aca_style_amendment(self, differ):
        """Test with Affordable Care Act style language."""
        old = """
(a) IN GENERAL.--A health insurance issuer offering group or
individual health insurance coverage may not impose any preexisting
condition exclusion with respect to such coverage.
"""
        new = """
(a) IN GENERAL.--A health insurance issuer offering group or
individual health insurance coverage may not impose any preexisting
condition exclusion or lifetime limit with respect to such coverage.
"""
        result = differ.diff_sections(old, new)

        assert result.has_changes
        assert result.similarity_score > 0.8  # Minor change
        assert "passage" in result.summary.lower() or "modified" in result.summary.lower()

    def test_complex_section_diff(self, differ):
        """Test with complex multi-paragraph section."""
        old = """
SEC. 1001. AMENDMENTS TO THE PUBLIC HEALTH SERVICE ACT.

(a) NO PREEXISTING CONDITION EXCLUSIONS.--
    (1) IN GENERAL.--A group health plan may not impose any
    preexisting condition exclusion.
    (2) DEFINITIONS.--For purposes of this section:
        (A) PREEXISTING CONDITION EXCLUSION.--The term means...

(b) EFFECTIVE DATE.--This section takes effect January 1, 2014.
"""
        new = """
SEC. 1001. AMENDMENTS TO THE PUBLIC HEALTH SERVICE ACT.

(a) NO PREEXISTING CONDITION EXCLUSIONS.--
    (1) IN GENERAL.--A group health plan and individual market
    plan may not impose any preexisting condition exclusion.
    (2) DEFINITIONS.--For purposes of this section:
        (A) PREEXISTING CONDITION EXCLUSION.--The term means...
        (B) INDIVIDUAL MARKET PLAN.--The term means a health plan
        offered in the individual market.

(b) EFFECTIVE DATE.--This section takes effect immediately upon
enactment.

(c) REGULATIONS.--The Secretary shall issue implementing regulations.
"""
        result = differ.diff_sections(old, new)

        assert result.has_changes
        # Should detect additions (new paragraph c, new definition B)
        assert len(result.additions) > 0 or len(result.modifications) > 0


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_diff_sections_function(self):
        """Test the diff_sections convenience function."""
        result = diff_sections("old text", "new text")
        assert isinstance(result, DiffResult)
        assert result.has_changes

    def test_diff_from_amendment_function(self):
        """Test the diff_from_amendment convenience function."""
        result = diff_from_amendment(
            "current text",
            'by striking "old" and inserting "new"'
        )
        assert isinstance(result, DiffResult)


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_very_long_text(self, differ):
        """Test with very long text."""
        old = "Section text. " * 1000
        new = "Section text. " * 1000 + "Added sentence."

        result = differ.diff_sections(old, new)

        assert result.has_changes
        assert result.similarity_score > 0.9  # Minor change relative to size

    def test_special_characters(self, differ):
        """Test handling of special characters."""
        old = "Section 1395(a)(1)(A)(i)(I)."
        new = "Section 1395(a)(1)(A)(i)(II)."

        result = differ.diff_sections(old, new)
        assert result.has_changes

    def test_unicode_text(self, differ):
        """Test handling of unicode text."""
        old = "The term 'qualified' means..."
        new = "The term 'certified' means..."

        result = differ.diff_sections(old, new)
        assert result.has_changes

    def test_multiline_strings(self, differ):
        """Test proper handling of multiline strings."""
        old = """Line 1
Line 2
Line 3"""
        new = """Line 1
Modified Line 2
Line 3"""

        result = differ.diff_sections(old, new)
        assert result.has_changes
