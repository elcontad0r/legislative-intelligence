"""
Tests for the citation parser.

The citation parser is the linchpin of the system - it must correctly handle
all the weird variations of legal citations found in the wild.
"""

import pytest
from src.parsers.citations import CitationParser, CitationType, ParsedCitation


@pytest.fixture
def parser():
    return CitationParser()


class TestUSCCitations:
    """Test US Code citation parsing."""

    def test_standard_form(self, parser):
        """Test standard 'X U.S.C. § Y' format."""
        text = "See 42 U.S.C. § 1395 for details."
        citations = parser.parse(text)

        assert len(citations) == 1
        cite = citations[0]
        assert cite.citation_type == CitationType.USC
        assert cite.canonical == "42 USC 1395"
        assert cite.title == 42
        assert cite.section == "1395"

    def test_no_section_symbol(self, parser):
        """Test format without section symbol."""
        text = "Under 42 USC 1395a..."
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].canonical == "42 USC 1395a"

    def test_with_subsection(self, parser):
        """Test citation with subsection."""
        text = "Per 42 U.S.C. § 1395(a)(1)..."
        citations = parser.parse(text)

        assert len(citations) == 1
        cite = citations[0]
        assert cite.section == "1395"
        assert cite.subsection == "a.1"  # Normalized format

    def test_multiple_subsections(self, parser):
        """Test citation with multiple levels of subsection."""
        text = "See 42 U.S.C. § 1395(a)(1)(A)..."
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].subsection == "a.1.A"

    def test_et_seq(self, parser):
        """Test citation with 'et seq.'"""
        text = "Governed by 26 U.S.C. § 5000A et seq."
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].canonical == "26 USC 5000A"

    def test_inverted_form(self, parser):
        """Test 'section X of title Y' format."""
        text = "section 1395 of title 42"
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].canonical == "42 USC 1395"

    def test_letter_suffix(self, parser):
        """Test section numbers with letter suffixes."""
        text = "42 U.S.C. 1395a, 1395b-1, and 1395cc"
        citations = parser.parse(text)

        assert len(citations) >= 2
        canonicals = [c.canonical for c in citations]
        assert "42 USC 1395a" in canonicals
        assert "42 USC 1395cc" in canonicals

    def test_various_spacing(self, parser):
        """Test various spacing in citations."""
        texts = [
            "42 U.S.C. § 1395",
            "42 U.S.C. §1395",
            "42 U.S.C.§1395",
            "42U.S.C.§1395",
            "42 USC 1395",
            "42USC1395",
        ]

        for text in texts[:5]:  # First 5 should parse
            citations = parser.parse(text)
            assert len(citations) >= 1, f"Failed to parse: {text}"
            assert citations[0].title == 42
            assert citations[0].section == "1395"


class TestPublicLawCitations:
    """Test Public Law citation parsing."""

    def test_standard_form(self, parser):
        """Test standard 'Pub. L. X-Y' format."""
        text = "Enacted by Pub. L. 111-148"
        citations = parser.parse(text)

        assert len(citations) == 1
        cite = citations[0]
        assert cite.citation_type == CitationType.PUBLIC_LAW
        assert cite.canonical == "Pub. L. 111-148"
        assert cite.congress == 111
        assert cite.law_number == 148

    def test_pl_abbreviation(self, parser):
        """Test P.L. abbreviation."""
        text = "P.L. 111-148"
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].canonical == "Pub. L. 111-148"

    def test_public_law_full(self, parser):
        """Test full 'Public Law' text."""
        text = "Public Law 111-148"
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].congress == 111
        assert citations[0].law_number == 148

    def test_with_no(self, parser):
        """Test 'Pub. L. No.' format."""
        text = "Pub. L. No. 89-97"
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].congress == 89
        assert citations[0].law_number == 97

    def test_various_dashes(self, parser):
        """Test different dash types."""
        texts = [
            "Pub. L. 111-148",  # Hyphen
            "Pub. L. 111–148",  # En dash
            "Pub. L. 111—148",  # Em dash
        ]

        for text in texts:
            citations = parser.parse(text)
            assert len(citations) >= 1, f"Failed to parse: {text}"


class TestBillCitations:
    """Test bill citation parsing."""

    def test_house_bill(self, parser):
        """Test H.R. format."""
        text = "H.R. 3590"
        citations = parser.parse(text)

        assert len(citations) == 1
        cite = citations[0]
        assert cite.citation_type == CitationType.BILL
        assert cite.bill_type == "hr"
        assert cite.bill_number == 3590

    def test_senate_bill(self, parser):
        """Test S. format."""
        text = "S. 1234"
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].bill_type == "s"
        assert citations[0].bill_number == 1234

    def test_with_congress(self, parser):
        """Test bill with congress number."""
        text = "H.R. 3590 (111th Congress)"
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].congress == 111

    def test_joint_resolution(self, parser):
        """Test joint resolution format."""
        text = "H.J. Res. 114"
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].bill_type == "hjres"

    def test_concurrent_resolution(self, parser):
        """Test concurrent resolution format."""
        text = "S. Con. Res. 70"
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].bill_type == "sconres"


class TestCFRCitations:
    """Test Code of Federal Regulations citation parsing."""

    def test_standard_form(self, parser):
        """Test standard CFR format."""
        text = "42 CFR 405.1"
        citations = parser.parse(text)

        assert len(citations) == 1
        cite = citations[0]
        assert cite.citation_type == CitationType.CFR
        assert cite.canonical == "42 CFR 405.1"
        assert cite.title == 42
        assert cite.part == 405
        assert cite.section == "1"

    def test_with_section_symbol(self, parser):
        """Test CFR with section symbol."""
        text = "42 C.F.R. § 405.1"
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].title == 42
        assert citations[0].part == 405

    def test_part_only(self, parser):
        """Test CFR part without section."""
        text = "42 CFR Part 405"
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].canonical == "42 CFR 405"


class TestFederalRegisterCitations:
    """Test Federal Register citation parsing."""

    def test_fr_format(self, parser):
        """Test FR format."""
        text = "78 FR 5566"
        citations = parser.parse(text)

        assert len(citations) == 1
        cite = citations[0]
        assert cite.citation_type == CitationType.FEDERAL_REGISTER
        assert cite.volume == 78
        assert cite.page == 5566

    def test_fed_reg_format(self, parser):
        """Test Fed. Reg. format."""
        text = "78 Fed. Reg. 5566"
        citations = parser.parse(text)

        assert len(citations) == 1
        assert citations[0].volume == 78


class TestStatutesAtLargeCitations:
    """Test Statutes at Large citation parsing."""

    def test_standard_form(self, parser):
        """Test standard Stat. format."""
        text = "79 Stat. 286"
        citations = parser.parse(text)

        assert len(citations) == 1
        cite = citations[0]
        assert cite.citation_type == CitationType.STATUTES_AT_LARGE
        assert cite.volume == 79
        assert cite.page == 286


class TestMixedCitations:
    """Test parsing text with multiple citation types."""

    def test_complex_paragraph(self, parser):
        """Test parsing a complex paragraph with multiple citations."""
        text = """
        Section 1395 of title 42 was enacted by Pub. L. 89-97, 79 Stat. 286.
        It has been amended multiple times, most recently by P.L. 111-148.
        See also 42 CFR 405.1 for implementing regulations and 78 FR 5566
        for the latest rulemaking. The bill H.R. 3590 (111th Congress) was
        the vehicle for the Affordable Care Act amendments.
        """

        citations = parser.parse(text)

        # Should find: USC, 2 Public Laws, Stat., CFR, FR, Bill
        types_found = {c.citation_type for c in citations}

        assert CitationType.USC in types_found
        assert CitationType.PUBLIC_LAW in types_found
        assert CitationType.CFR in types_found
        assert CitationType.FEDERAL_REGISTER in types_found
        assert CitationType.BILL in types_found
        assert CitationType.STATUTES_AT_LARGE in types_found

    def test_deduplication(self, parser):
        """Test that duplicate citations are deduplicated."""
        text = "42 U.S.C. § 1395 is important. See also 42 USC 1395."

        citations = parser.parse(text)

        # Should only have one citation
        usc_citations = [c for c in citations if c.citation_type == CitationType.USC]
        assert len(usc_citations) == 1


class TestNormalization:
    """Test citation normalization functions."""

    def test_normalize_usc(self, parser):
        """Test USC normalization."""
        assert parser.normalize_usc(42, "1395") == "42 USC 1395"
        assert parser.normalize_usc(42, "1395", "a.1") == "42 USC 1395(a.1)"

    def test_normalize_public_law(self, parser):
        """Test Public Law normalization."""
        assert parser.normalize_public_law(111, 148) == "Pub. L. 111-148"

    def test_normalize_bill(self, parser):
        """Test bill normalization."""
        assert parser.normalize_bill("hr", 3590, 111) == "HR 3590 (111th)"
        assert parser.normalize_bill("H.R.", 3590) == "HR 3590"

    def test_normalize_cfr(self, parser):
        """Test CFR normalization."""
        assert parser.normalize_cfr(42, 405) == "42 CFR 405"
        assert parser.normalize_cfr(42, 405, "1") == "42 CFR 405.1"


class TestEdgeCases:
    """Test edge cases and potential issues."""

    def test_empty_string(self, parser):
        """Test empty string."""
        citations = parser.parse("")
        assert len(citations) == 0

    def test_no_citations(self, parser):
        """Test text with no citations."""
        text = "This is just regular text with no legal citations."
        citations = parser.parse(text)
        assert len(citations) == 0

    def test_partial_citations(self, parser):
        """Test that partial/invalid citations are not matched."""
        text = "Section 42 is not a USC citation. Neither is USC alone."
        citations = parser.parse(text)
        # Should not match partial citations
        usc = [c for c in citations if c.citation_type == CitationType.USC]
        assert len(usc) == 0

    def test_citation_in_url(self, parser):
        """Test that we handle citations that might look like URLs."""
        text = "See https://example.com/42-usc-1395 but also 42 USC 1395."
        citations = parser.parse(text)
        # Should find the real citation
        assert any(c.canonical == "42 USC 1395" for c in citations)
