"""
Text Diff Engine for comparing USC section versions.

This module provides tools for computing and representing differences between
versions of statutory text. It's designed for Tier 3 of the trustworthiness
hierarchy - showing WHAT actually changed in statutory language.

IMPORTANT LIMITATION:
====================
As of this implementation, we only have ONE version of each USC section stored
in Neo4j (the current version from uscode.house.gov). To show historical diffs,
we would need to either:

1. FETCH HISTORICAL VERSIONS (Recommended for completeness):
   - uscode.house.gov publishes "release points" tied to Public Laws
   - URL pattern: https://uscode.house.gov/download/releasepoints/
   - Each release point is named by the Public Law that triggered it
   - We could store multiple versions keyed by release point
   - Pro: Authoritative source, complete history
   - Con: Requires significant storage, historical downloads

2. PARSE PUBLIC LAW TEXT (Good for recent changes):
   - Public Laws contain explicit amendment instructions like:
     "Section 1395(a)(1) is amended by striking 'X' and inserting 'Y'"
   - We can parse these instructions to reconstruct what changed
   - Pro: Works with existing data, shows legislative intent
   - Con: Doesn't give us the full before/after text, just the delta

3. HYBRID APPROACH (Proposed solution):
   - For recent changes: Parse amendment instructions from Public Law text
   - For historical analysis: Fetch release points on demand
   - Cache fetched historical versions in Neo4j with temporal metadata
   - Use diff engine to compare any two cached versions

This module implements the diff engine itself. The version fetching/caching
would be implemented in a separate module (src/adapters/usc_versions.py).

Usage:
    from src.analysis.text_diff import SectionDiff

    differ = SectionDiff()
    result = differ.diff_sections(old_text, new_text)

    print(f"Similarity: {result.similarity_score:.1%}")
    print(result.summary)

    for addition in result.additions:
        print(f"+ {addition.text}")
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Iterator

from pydantic import BaseModel, Field


# =============================================================================
# Enums and Data Classes
# =============================================================================


class ChunkType(str, Enum):
    """Type of diff chunk."""
    ADDITION = "addition"
    DELETION = "deletion"
    MODIFICATION = "modification"
    UNCHANGED = "unchanged"


class DiffChunk(BaseModel):
    """
    A chunk of text that was added, removed, or modified.

    Attributes:
        chunk_type: Whether this is an addition, deletion, or modification
        text: The text content of this chunk
        old_text: For modifications, the original text (None for additions)
        position: Character position in the original/new text
        line_number: Approximate line number (1-indexed)
        context: Surrounding text for context (optional)
        subsection: If this chunk is within a numbered subsection, its identifier
    """
    chunk_type: ChunkType
    text: str
    old_text: str | None = None  # For modifications
    position: int = 0
    line_number: int = 1
    context: str | None = None
    subsection: str | None = None  # e.g., "(a)(1)(A)"

    def __str__(self) -> str:
        prefix = {
            ChunkType.ADDITION: "+",
            ChunkType.DELETION: "-",
            ChunkType.MODIFICATION: "~",
            ChunkType.UNCHANGED: " ",
        }[self.chunk_type]
        return f"{prefix} {self.text[:80]}{'...' if len(self.text) > 80 else ''}"


class DiffResult(BaseModel):
    """
    Result of comparing two versions of statutory text.

    Attributes:
        additions: List of added text chunks
        deletions: List of removed text chunks
        modifications: List of modified chunks (old_text -> text)
        similarity_score: Ratio of unchanged to total content (0-1)
        summary: Human-readable summary of changes
        old_word_count: Word count in original text
        new_word_count: Word count in new text
        words_added: Net words added
        words_removed: Net words removed
        paragraphs_affected: Number of paragraphs with changes
    """
    additions: list[DiffChunk] = Field(default_factory=list)
    deletions: list[DiffChunk] = Field(default_factory=list)
    modifications: list[DiffChunk] = Field(default_factory=list)
    similarity_score: float = 1.0
    summary: str = "No changes"

    # Statistics
    old_word_count: int = 0
    new_word_count: int = 0
    words_added: int = 0
    words_removed: int = 0
    paragraphs_affected: int = 0

    @property
    def has_changes(self) -> bool:
        """Returns True if any changes were detected."""
        return bool(self.additions or self.deletions or self.modifications)

    @property
    def change_magnitude(self) -> str:
        """Categorize the magnitude of changes."""
        if not self.has_changes:
            return "none"
        if self.similarity_score >= 0.95:
            return "minor"
        if self.similarity_score >= 0.80:
            return "moderate"
        if self.similarity_score >= 0.50:
            return "substantial"
        return "major"


# =============================================================================
# Amendment Instruction Parser
# =============================================================================


@dataclass
class AmendmentInstruction:
    """
    A parsed amendment instruction from Public Law text.

    Common patterns:
    - "by striking 'X' and inserting 'Y'"
    - "by inserting 'X' after 'Y'"
    - "by adding at the end the following: ..."
    - "is amended to read as follows: ..."
    - "by redesignating subsection (X) as subsection (Y)"
    """
    instruction_type: str  # strike_insert, insert_after, add_end, replace_all, redesignate
    target_section: str | None = None  # e.g., "(a)(1)"
    strike_text: str | None = None
    insert_text: str | None = None
    position_reference: str | None = None  # "after 'X'", "at the end"
    raw_text: str = ""


class AmendmentParser:
    """
    Parse amendment instructions from Public Law text.

    These instructions describe how to modify statutory text. This is useful
    when we don't have the actual before/after text, but we do have the
    Public Law that made the changes.
    """

    # Pattern: "by striking 'X' and inserting 'Y'"
    STRIKE_INSERT = re.compile(
        r"by\s+striking\s+['\"]([^'\"]+)['\"]\s+and\s+inserting\s+['\"]([^'\"]+)['\"]",
        re.IGNORECASE | re.DOTALL
    )

    # Pattern: "by inserting 'X' after 'Y'"
    INSERT_AFTER = re.compile(
        r"by\s+inserting\s+['\"]([^'\"]+)['\"]\s+after\s+['\"]([^'\"]+)['\"]",
        re.IGNORECASE | re.DOTALL
    )

    # Pattern: "by adding at the end the following:"
    ADD_END = re.compile(
        r"by\s+adding\s+at\s+the\s+end\s+(?:thereof\s+)?the\s+following[:\s]+['\"]?([^'\"]+)['\"]?",
        re.IGNORECASE | re.DOTALL
    )

    # Pattern: "is amended to read as follows:"
    REPLACE_ALL = re.compile(
        r"is\s+amended\s+to\s+read\s+as\s+follows[:\s]+['\"]?(.+?)['\"]?(?=\n\n|\Z)",
        re.IGNORECASE | re.DOTALL
    )

    # Pattern: "by redesignating subsection (X) as subsection (Y)"
    REDESIGNATE = re.compile(
        r"by\s+redesignating\s+(?:subsection|paragraph|subparagraph)\s+\(([^)]+)\)\s+as\s+(?:subsection|paragraph|subparagraph)\s+\(([^)]+)\)",
        re.IGNORECASE
    )

    # Pattern for section references: "Section 1395(a)(1) is amended"
    SECTION_REF = re.compile(
        r"[Ss]ection\s+(\d+[a-z]*(?:\([^)]+\))*)\s+(?:of\s+(?:title\s+\d+|the\s+\w+\s+\w+)\s+)?is\s+amended",
        re.IGNORECASE
    )

    def parse(self, text: str) -> list[AmendmentInstruction]:
        """
        Parse amendment instructions from Public Law text.

        Args:
            text: The text of a Public Law section describing amendments

        Returns:
            List of parsed amendment instructions
        """
        instructions = []

        # Find section references to associate with instructions
        current_section = None
        section_match = self.SECTION_REF.search(text)
        if section_match:
            current_section = section_match.group(1)

        # Strike and insert
        for match in self.STRIKE_INSERT.finditer(text):
            instructions.append(AmendmentInstruction(
                instruction_type="strike_insert",
                target_section=current_section,
                strike_text=match.group(1),
                insert_text=match.group(2),
                raw_text=match.group(0)
            ))

        # Insert after
        for match in self.INSERT_AFTER.finditer(text):
            instructions.append(AmendmentInstruction(
                instruction_type="insert_after",
                target_section=current_section,
                insert_text=match.group(1),
                position_reference=f"after '{match.group(2)}'",
                raw_text=match.group(0)
            ))

        # Add at end
        for match in self.ADD_END.finditer(text):
            instructions.append(AmendmentInstruction(
                instruction_type="add_end",
                target_section=current_section,
                insert_text=match.group(1),
                position_reference="at the end",
                raw_text=match.group(0)
            ))

        # Replace all
        for match in self.REPLACE_ALL.finditer(text):
            instructions.append(AmendmentInstruction(
                instruction_type="replace_all",
                target_section=current_section,
                insert_text=match.group(1),
                raw_text=match.group(0)
            ))

        # Redesignate
        for match in self.REDESIGNATE.finditer(text):
            instructions.append(AmendmentInstruction(
                instruction_type="redesignate",
                target_section=current_section,
                strike_text=f"({match.group(1)})",
                insert_text=f"({match.group(2)})",
                raw_text=match.group(0)
            ))

        return instructions


# =============================================================================
# Main Diff Engine
# =============================================================================


class SectionDiff:
    """
    Compute and represent differences between versions of statutory text.

    This class handles the quirks of legal text:
    - Subsection numbering like (a)(1)(A)(i)
    - Paragraph/subparagraph structure
    - Common amendment patterns

    Usage:
        differ = SectionDiff()
        result = differ.diff_sections(old_text, new_text)

        # Get a narrative summary
        print(result.summary)

        # Iterate over changes
        for chunk in result.additions:
            print(f"Added: {chunk.text}")
    """

    # Pattern for subsection identifiers
    SUBSECTION_PATTERN = re.compile(
        r"^\s*(\([a-zA-Z0-9]+\)(?:\s*\([a-zA-Z0-9]+\))*)",
        re.MULTILINE
    )

    def __init__(self, context_lines: int = 2):
        """
        Initialize the diff engine.

        Args:
            context_lines: Number of context lines to include around changes
        """
        self.context_lines = context_lines
        self.amendment_parser = AmendmentParser()

    def diff_sections(self, old_text: str, new_text: str) -> DiffResult:
        """
        Compare two versions of statutory text.

        Args:
            old_text: The original version of the text
            new_text: The modified version of the text

        Returns:
            DiffResult containing structured diff information
        """
        if not old_text and not new_text:
            return DiffResult(summary="Both versions are empty")

        if not old_text:
            return self._handle_new_section(new_text)

        if not new_text:
            return self._handle_deleted_section(old_text)

        # Normalize whitespace for comparison
        old_normalized = self._normalize_text(old_text)
        new_normalized = self._normalize_text(new_text)

        # If identical after normalization, no changes
        if old_normalized == new_normalized:
            return DiffResult(
                similarity_score=1.0,
                summary="No substantive changes (whitespace only)",
                old_word_count=len(old_text.split()),
                new_word_count=len(new_text.split())
            )

        # Compute diff at the line level for structure
        old_lines = old_normalized.split('\n')
        new_lines = new_normalized.split('\n')

        # Use SequenceMatcher for similarity score
        matcher = difflib.SequenceMatcher(None, old_normalized, new_normalized)
        similarity = matcher.ratio()

        # Get structured diff
        additions, deletions, modifications = self._extract_chunks(
            old_lines, new_lines, old_text, new_text
        )

        # Calculate statistics
        old_words = len(old_text.split())
        new_words = len(new_text.split())

        added_text = ' '.join(c.text for c in additions)
        removed_text = ' '.join(c.text for c in deletions)

        words_added = len(added_text.split()) if added_text else 0
        words_removed = len(removed_text.split()) if removed_text else 0

        # Count affected paragraphs
        affected_subsections = set()
        for chunk in additions + deletions + modifications:
            if chunk.subsection:
                affected_subsections.add(chunk.subsection)

        # Generate summary
        summary = self._generate_summary(
            additions, deletions, modifications,
            words_added, words_removed, len(affected_subsections)
        )

        return DiffResult(
            additions=additions,
            deletions=deletions,
            modifications=modifications,
            similarity_score=similarity,
            summary=summary,
            old_word_count=old_words,
            new_word_count=new_words,
            words_added=words_added,
            words_removed=words_removed,
            paragraphs_affected=len(affected_subsections)
        )

    def diff_from_amendment(
        self,
        current_text: str,
        amendment_text: str
    ) -> DiffResult:
        """
        Reconstruct changes from Public Law amendment instructions.

        When we don't have the old version, we can parse the amendment
        instructions to understand what changed.

        Args:
            current_text: The current version of the section
            amendment_text: The Public Law text describing the amendment

        Returns:
            DiffResult with changes inferred from amendment instructions
        """
        instructions = self.amendment_parser.parse(amendment_text)

        if not instructions:
            return DiffResult(
                summary="Could not parse amendment instructions from provided text"
            )

        # Build diff chunks from instructions
        additions = []
        deletions = []
        modifications = []

        for instr in instructions:
            if instr.instruction_type == "strike_insert":
                modifications.append(DiffChunk(
                    chunk_type=ChunkType.MODIFICATION,
                    text=instr.insert_text or "",
                    old_text=instr.strike_text,
                    subsection=instr.target_section
                ))
            elif instr.instruction_type in ("insert_after", "add_end"):
                additions.append(DiffChunk(
                    chunk_type=ChunkType.ADDITION,
                    text=instr.insert_text or "",
                    context=instr.position_reference,
                    subsection=instr.target_section
                ))
            elif instr.instruction_type == "replace_all":
                # This is a complete replacement
                modifications.append(DiffChunk(
                    chunk_type=ChunkType.MODIFICATION,
                    text=instr.insert_text or "",
                    old_text="[entire section]",
                    subsection=instr.target_section
                ))
            elif instr.instruction_type == "redesignate":
                # Renumbering
                modifications.append(DiffChunk(
                    chunk_type=ChunkType.MODIFICATION,
                    text=f"Redesignated as {instr.insert_text}",
                    old_text=f"Was {instr.strike_text}",
                    subsection=instr.target_section
                ))

        # Calculate approximate word changes
        words_added = sum(len(c.text.split()) for c in additions)
        words_added += sum(
            len(c.text.split()) - len((c.old_text or "").split())
            for c in modifications if c.old_text
        )

        summary = self._generate_summary(
            additions, deletions, modifications,
            words_added, 0, len(set(c.subsection for c in additions + modifications if c.subsection))
        )

        return DiffResult(
            additions=additions,
            deletions=deletions,
            modifications=modifications,
            similarity_score=0.0,  # Unknown without original text
            summary=f"[From amendment instructions] {summary}",
            new_word_count=len(current_text.split()) if current_text else 0
        )

    def _normalize_text(self, text: str) -> str:
        """Normalize whitespace and formatting for comparison."""
        # Normalize various whitespace
        text = re.sub(r'\s+', ' ', text)
        # Normalize quotes
        text = text.replace('"', '"').replace('"', '"')
        text = text.replace(''', "'").replace(''', "'")
        # Normalize dashes
        text = text.replace('–', '-').replace('—', '-')
        return text.strip()

    def _extract_chunks(
        self,
        old_lines: list[str],
        new_lines: list[str],
        old_text: str,
        new_text: str
    ) -> tuple[list[DiffChunk], list[DiffChunk], list[DiffChunk]]:
        """Extract diff chunks from line-level comparison."""
        additions = []
        deletions = []
        modifications = []

        # Use unified diff for structured output
        differ = difflib.unified_diff(old_lines, new_lines, lineterm='')

        current_line = 0
        pending_deletion = None

        for line in differ:
            if line.startswith('@@'):
                # Parse hunk header for line numbers
                match = re.match(r'@@ -(\d+)', line)
                if match:
                    current_line = int(match.group(1))
                continue

            if line.startswith('---') or line.startswith('+++'):
                continue

            # Detect subsection context
            subsection = self._detect_subsection(line)

            if line.startswith('-'):
                content = line[1:].strip()
                if content:
                    if pending_deletion is None:
                        pending_deletion = DiffChunk(
                            chunk_type=ChunkType.DELETION,
                            text=content,
                            line_number=current_line,
                            subsection=subsection
                        )
                    else:
                        pending_deletion.text += ' ' + content
                current_line += 1

            elif line.startswith('+'):
                content = line[1:].strip()
                if content:
                    if pending_deletion:
                        # This is likely a modification
                        modifications.append(DiffChunk(
                            chunk_type=ChunkType.MODIFICATION,
                            text=content,
                            old_text=pending_deletion.text,
                            line_number=pending_deletion.line_number,
                            subsection=subsection or pending_deletion.subsection
                        ))
                        pending_deletion = None
                    else:
                        additions.append(DiffChunk(
                            chunk_type=ChunkType.ADDITION,
                            text=content,
                            line_number=current_line,
                            subsection=subsection
                        ))
            else:
                # Unchanged line
                if pending_deletion:
                    deletions.append(pending_deletion)
                    pending_deletion = None
                current_line += 1

        # Don't forget pending deletion
        if pending_deletion:
            deletions.append(pending_deletion)

        return additions, deletions, modifications

    def _detect_subsection(self, text: str) -> str | None:
        """Detect subsection identifier from text line."""
        match = self.SUBSECTION_PATTERN.match(text)
        if match:
            return match.group(1).strip()
        return None

    def _handle_new_section(self, new_text: str) -> DiffResult:
        """Handle case where section is entirely new."""
        words = len(new_text.split())
        return DiffResult(
            additions=[DiffChunk(
                chunk_type=ChunkType.ADDITION,
                text=new_text,
                line_number=1
            )],
            similarity_score=0.0,
            summary=f"New section added ({words} words)",
            new_word_count=words,
            words_added=words
        )

    def _handle_deleted_section(self, old_text: str) -> DiffResult:
        """Handle case where section is entirely deleted."""
        words = len(old_text.split())
        return DiffResult(
            deletions=[DiffChunk(
                chunk_type=ChunkType.DELETION,
                text=old_text,
                line_number=1
            )],
            similarity_score=0.0,
            summary=f"Section deleted ({words} words removed)",
            old_word_count=words,
            words_removed=words
        )

    def _generate_summary(
        self,
        additions: list[DiffChunk],
        deletions: list[DiffChunk],
        modifications: list[DiffChunk],
        words_added: int,
        words_removed: int,
        paragraphs_affected: int
    ) -> str:
        """Generate human-readable summary of changes."""
        parts = []

        if modifications:
            parts.append(f"Modified {len(modifications)} passage{'s' if len(modifications) != 1 else ''}")

        if additions:
            parts.append(f"Added {len(additions)} passage{'s' if len(additions) != 1 else ''}")

        if deletions:
            parts.append(f"Deleted {len(deletions)} passage{'s' if len(deletions) != 1 else ''}")

        if not parts:
            return "No changes detected"

        summary = ", ".join(parts)

        # Add word count info
        word_info = []
        if words_added > 0:
            word_info.append(f"+{words_added} words")
        if words_removed > 0:
            word_info.append(f"-{words_removed} words")

        if word_info:
            summary += f" ({', '.join(word_info)})"

        if paragraphs_affected > 0:
            summary += f" affecting {paragraphs_affected} subsection{'s' if paragraphs_affected != 1 else ''}"

        return summary


# =============================================================================
# Convenience Functions
# =============================================================================


def diff_sections(old_text: str, new_text: str) -> DiffResult:
    """
    Compare two versions of statutory text.

    Convenience wrapper around SectionDiff.diff_sections().
    """
    return SectionDiff().diff_sections(old_text, new_text)


def diff_from_amendment(current_text: str, amendment_text: str) -> DiffResult:
    """
    Reconstruct changes from Public Law amendment instructions.

    Convenience wrapper around SectionDiff.diff_from_amendment().
    """
    return SectionDiff().diff_from_amendment(current_text, amendment_text)


# =============================================================================
# CLI / Testing
# =============================================================================


if __name__ == "__main__":
    # Example usage with sample legal text

    old_section = """
(a) GENERAL RULE.--Every individual shall have access to health insurance
coverage through an Exchange established under this title.

(1) QUALIFIED INDIVIDUALS.--A qualified individual means an individual who--
    (A) is a citizen or national of the United States or an alien lawfully
    present in the United States;
    (B) is not incarcerated; and
    (C) resides in the State that established the Exchange.

(2) EMPLOYER REQUIREMENTS.--Nothing in this section shall be construed to
require an employer to offer health insurance coverage.
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

(2) EMPLOYER REQUIREMENTS.--Nothing in this section shall be construed to
require an employer to offer health insurance coverage.

(3) AFFORDABILITY WAIVER.--The Secretary may waive requirements under this
subsection for individuals for whom coverage would exceed 8 percent of
household income.
"""

    print("=" * 70)
    print("SECTION DIFF ENGINE - DEMONSTRATION")
    print("=" * 70)

    differ = SectionDiff()
    result = differ.diff_sections(old_section, new_section)

    print(f"\nSimilarity Score: {result.similarity_score:.1%}")
    print(f"Change Magnitude: {result.change_magnitude}")
    print(f"\nSummary: {result.summary}")

    print(f"\nStatistics:")
    print(f"  Old word count: {result.old_word_count}")
    print(f"  New word count: {result.new_word_count}")
    print(f"  Words added: {result.words_added}")
    print(f"  Words removed: {result.words_removed}")

    if result.additions:
        print(f"\n--- ADDITIONS ({len(result.additions)}) ---")
        for chunk in result.additions:
            print(f"  Line {chunk.line_number}: {chunk.text[:100]}...")

    if result.deletions:
        print(f"\n--- DELETIONS ({len(result.deletions)}) ---")
        for chunk in result.deletions:
            print(f"  Line {chunk.line_number}: {chunk.text[:100]}...")

    if result.modifications:
        print(f"\n--- MODIFICATIONS ({len(result.modifications)}) ---")
        for chunk in result.modifications:
            print(f"  Line {chunk.line_number}:")
            print(f"    OLD: {(chunk.old_text or '')[:60]}...")
            print(f"    NEW: {chunk.text[:60]}...")

    # Test amendment parsing
    print("\n" + "=" * 70)
    print("AMENDMENT PARSING - DEMONSTRATION")
    print("=" * 70)

    amendment_text = """
SEC. 1001. AMENDMENTS TO THE PUBLIC HEALTH SERVICE ACT.

(a) Section 2702(a)(1) of the Public Health Service Act (42 U.S.C. 300gg-1)
is amended--
    (1) by striking "any health status-related factor" and inserting
    "health status, medical condition, claims experience, receipt of health
    care, medical history, genetic information, evidence of insurability,
    disability, or any other health status-related factor determined
    appropriate by the Secretary";
    (2) by inserting ", including a dependent," after "individual"; and
    (3) by adding at the end the following: "The Secretary shall issue
    regulations to implement this section within 180 days of enactment."
"""

    result2 = differ.diff_from_amendment("", amendment_text)
    print(f"\nParsed Amendment Summary: {result2.summary}")

    if result2.modifications:
        print(f"\n--- PARSED MODIFICATIONS ---")
        for chunk in result2.modifications:
            if chunk.old_text and chunk.old_text != "[entire section]":
                print(f"  Strike: {chunk.old_text}")
                print(f"  Insert: {chunk.text}")
                print()

    if result2.additions:
        print(f"\n--- PARSED ADDITIONS ---")
        for chunk in result2.additions:
            print(f"  {chunk.context}: {chunk.text[:80]}...")
