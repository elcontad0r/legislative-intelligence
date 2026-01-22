"""
Congress.gov API Adapter - Access legislative data from the Library of Congress.

API Documentation: https://api.congress.gov/
GitHub: https://github.com/LibraryOfCongress/api.congress.gov

This adapter provides access to:
- Bills and resolutions
- Amendments
- Public Laws
- Committee reports
- Congressional Record
- Members of Congress
- CRS reports

Rate limit: 5,000 requests per hour
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Iterator
from enum import Enum

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models import (
    Bill,
    BillCitation,
    BillType,
    PublicLaw,
    PublicLawCitation,
    CommitteeReport,
    Entity,
    EntityType,
    CRSReport,
    ProvenanceInfo,
)


class CongressGovAdapter:
    """
    Adapter for the Congress.gov API.

    Usage:
        adapter = CongressGovAdapter(api_key="your_key")

        # Get a specific bill
        bill = adapter.get_bill(congress=117, bill_type="hr", number=3076)

        # Get laws from a Congress
        for law in adapter.get_laws(congress=117):
            print(law.citation)

        # Search bills
        for bill in adapter.search_bills("medicare"):
            print(bill.title)
    """

    BASE_URL = "https://api.congress.gov/v3"

    def __init__(self, api_key: str | None = None):
        """Initialize with API key (or use CONGRESS_GOV_API_KEY env var)."""
        self.api_key = api_key or os.getenv("CONGRESS_GOV_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Congress.gov API key required. "
                "Set CONGRESS_GOV_API_KEY environment variable or pass api_key parameter."
            )

        self.client = httpx.Client(
            base_url=self.BASE_URL,
            params={"api_key": self.api_key},
            timeout=30.0,
        )

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # =========================================================================
    # Bills
    # =========================================================================

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_bill(self, congress: int, bill_type: str, number: int) -> Bill | None:
        """
        Get a specific bill by congress, type, and number.

        Args:
            congress: Congress number (e.g., 117)
            bill_type: Type of bill (hr, s, hjres, sjres, hconres, sconres, hres, sres)
            number: Bill number

        Returns:
            Bill object or None if not found
        """
        url = f"/bill/{congress}/{bill_type.lower()}/{number}"

        try:
            response = self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

        data = response.json().get("bill", {})
        return self._parse_bill(data, congress)

    def get_bills(
        self,
        congress: int | None = None,
        bill_type: str | None = None,
        limit: int = 250,
        offset: int = 0,
    ) -> Iterator[Bill]:
        """
        Get bills with optional filtering.

        Args:
            congress: Filter by Congress number
            bill_type: Filter by bill type
            limit: Max results per page (up to 250)
            offset: Starting offset for pagination

        Yields:
            Bill objects
        """
        params: dict[str, Any] = {"limit": min(limit, 250), "offset": offset}

        if congress:
            url = f"/bill/{congress}"
            if bill_type:
                url += f"/{bill_type.lower()}"
        else:
            url = "/bill"

        while True:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            bills = data.get("bills", [])
            if not bills:
                break

            for bill_data in bills:
                # Need to fetch full bill details
                bill = self._parse_bill_summary(bill_data)
                if bill:
                    yield bill

            # Check for more pages
            pagination = data.get("pagination", {})
            if not pagination.get("next"):
                break

            params["offset"] = params.get("offset", 0) + len(bills)

    def search_bills(self, query: str, congress: int | None = None, limit: int = 100) -> Iterator[Bill]:
        """
        Search bills by keyword.

        Args:
            query: Search query
            congress: Optional Congress to limit search
            limit: Max results

        Yields:
            Bill objects matching the query
        """
        # The Congress.gov API doesn't have a direct search endpoint
        # We'd need to use their search functionality differently
        # For now, this is a placeholder that lists bills
        # Real implementation would use the congress.gov search or filter locally

        if congress:
            yield from self.get_bills(congress=congress, limit=limit)
        else:
            # Get recent bills from last few congresses
            for c in range(118, 115, -1):
                count = 0
                for bill in self.get_bills(congress=c):
                    if count >= limit:
                        return
                    # Basic text matching (would be better with proper search)
                    if query.lower() in (bill.title or "").lower():
                        yield bill
                        count += 1

    def get_bill_actions(self, congress: int, bill_type: str, number: int) -> list[dict]:
        """Get the action history for a bill."""
        url = f"/bill/{congress}/{bill_type.lower()}/{number}/actions"

        response = self.client.get(url, params={"limit": 250})
        response.raise_for_status()

        return response.json().get("actions", [])

    def get_bill_amendments(self, congress: int, bill_type: str, number: int) -> list[dict]:
        """Get amendments to a bill."""
        url = f"/bill/{congress}/{bill_type.lower()}/{number}/amendments"

        response = self.client.get(url, params={"limit": 250})
        response.raise_for_status()

        return response.json().get("amendments", [])

    def get_bill_cosponsors(self, congress: int, bill_type: str, number: int) -> list[Entity]:
        """Get cosponsors of a bill."""
        url = f"/bill/{congress}/{bill_type.lower()}/{number}/cosponsors"

        response = self.client.get(url, params={"limit": 250})
        response.raise_for_status()

        entities = []
        for cosponsor in response.json().get("cosponsors", []):
            entity = self._parse_member(cosponsor)
            if entity:
                entities.append(entity)

        return entities

    def get_bill_related_bills(self, congress: int, bill_type: str, number: int) -> list[dict]:
        """Get bills related to a bill."""
        url = f"/bill/{congress}/{bill_type.lower()}/{number}/relatedbills"

        response = self.client.get(url, params={"limit": 250})
        response.raise_for_status()

        return response.json().get("relatedBills", [])

    def get_bill_subjects(self, congress: int, bill_type: str, number: int) -> list[str]:
        """Get legislative subjects for a bill."""
        url = f"/bill/{congress}/{bill_type.lower()}/{number}/subjects"

        response = self.client.get(url, params={"limit": 250})
        response.raise_for_status()

        subjects = response.json().get("subjects", {})
        policy_area = subjects.get("policyArea", {}).get("name")
        legislative_subjects = [
            s.get("name") for s in subjects.get("legislativeSubjects", [])
        ]

        result = []
        if policy_area:
            result.append(policy_area)
        result.extend(filter(None, legislative_subjects))

        return result

    def get_bill_text_versions(self, congress: int, bill_type: str, number: int) -> list[dict]:
        """Get available text versions of a bill."""
        url = f"/bill/{congress}/{bill_type.lower()}/{number}/text"

        response = self.client.get(url, params={"limit": 250})
        response.raise_for_status()

        return response.json().get("textVersions", [])

    # =========================================================================
    # Public Laws
    # =========================================================================

    def get_law(self, congress: int, law_number: int) -> PublicLaw | None:
        """
        Get a specific public law.

        Args:
            congress: Congress number
            law_number: Law number within that Congress

        Returns:
            PublicLaw object or None
        """
        url = f"/law/{congress}/pub/{law_number}"

        try:
            response = self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

        data = response.json().get("law", {})
        return self._parse_law(data)

    def get_laws(self, congress: int, limit: int = 250) -> Iterator[PublicLaw]:
        """
        Get all public laws from a Congress.

        The /law endpoint returns bills that became laws, with law info embedded.

        Args:
            congress: Congress number
            limit: Max results per page

        Yields:
            PublicLaw objects
        """
        url = f"/law/{congress}"
        params: dict[str, Any] = {"limit": min(limit, 250), "offset": 0}

        while True:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            # API returns 'bills' that became laws, not 'laws' directly
            bills = data.get("bills", [])
            if not bills:
                break

            for bill_data in bills:
                # Extract law info from the bill
                laws_list = bill_data.get("laws", [])
                for law_info in laws_list:
                    law = self._parse_law_from_bill(bill_data, law_info)
                    if law:
                        yield law

            pagination = data.get("pagination", {})
            if not pagination.get("next"):
                break

            params["offset"] = params.get("offset", 0) + len(bills)

    # =========================================================================
    # Members
    # =========================================================================

    def get_member(self, bioguide_id: str) -> Entity | None:
        """
        Get a member of Congress by bioguide ID.

        Args:
            bioguide_id: Bioguide identifier (e.g., "P000197" for Pelosi)

        Returns:
            Entity object or None
        """
        url = f"/member/{bioguide_id}"

        try:
            response = self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

        data = response.json().get("member", {})
        return self._parse_member(data)

    def get_members(self, congress: int | None = None, chamber: str | None = None) -> Iterator[Entity]:
        """
        Get members of Congress.

        Args:
            congress: Optional Congress number to filter
            chamber: Optional "house" or "senate"

        Yields:
            Entity objects for each member
        """
        if congress:
            url = f"/member/congress/{congress}"
            if chamber:
                url += f"/{chamber.lower()}"
        else:
            url = "/member"

        params: dict[str, Any] = {"limit": 250, "offset": 0}

        while True:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            members = data.get("members", [])
            if not members:
                break

            for member_data in members:
                member = self._parse_member(member_data)
                if member:
                    yield member

            pagination = data.get("pagination", {})
            if not pagination.get("next"):
                break

            params["offset"] = params.get("offset", 0) + len(members)

    # =========================================================================
    # Committee Reports
    # =========================================================================

    def get_committee_reports(
        self, congress: int, report_type: str | None = None
    ) -> Iterator[CommitteeReport]:
        """
        Get committee reports from a Congress.

        Args:
            congress: Congress number
            report_type: Optional "hrpt", "srpt", "erpt"

        Yields:
            CommitteeReport objects
        """
        url = f"/committee-report/{congress}"
        if report_type:
            url += f"/{report_type.lower()}"

        params: dict[str, Any] = {"limit": 250, "offset": 0}

        while True:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            reports = data.get("reports", [])
            if not reports:
                break

            for report_data in reports:
                report = self._parse_committee_report(report_data, congress)
                if report:
                    yield report

            pagination = data.get("pagination", {})
            if not pagination.get("next"):
                break

            params["offset"] = params.get("offset", 0) + len(reports)

    # =========================================================================
    # Summaries (Bill summaries from CRS)
    # =========================================================================

    def get_bill_summaries(self, congress: int, bill_type: str, number: int) -> list[dict]:
        """Get CRS summaries for a bill."""
        url = f"/bill/{congress}/{bill_type.lower()}/{number}/summaries"

        response = self.client.get(url)
        response.raise_for_status()

        return response.json().get("summaries", [])

    # =========================================================================
    # Internal Parsers
    # =========================================================================

    def _parse_bill(self, data: dict, congress: int | None = None) -> Bill | None:
        """Parse API response into a Bill object."""
        if not data:
            return None

        # Determine bill type
        bill_type_str = data.get("type", "").lower()
        try:
            bill_type = BillType(bill_type_str)
        except ValueError:
            bill_type = BillType.HR  # Default

        number = data.get("number")
        if not number:
            return None

        cong = congress or data.get("congress")
        if not cong:
            return None

        citation = BillCitation(
            congress=cong,
            bill_type=bill_type,
            number=int(number),
        )

        # Parse dates
        introduced = data.get("introducedDate")
        introduced_date = None
        if introduced:
            try:
                introduced_date = date.fromisoformat(introduced)
            except ValueError:
                pass

        # Get sponsor info
        sponsors = data.get("sponsors", [])
        sponsor_id = None
        if sponsors:
            sponsor_id = sponsors[0].get("bioguideId")

        # Get cosponsors
        cosponsors = data.get("cosponsors", {})
        cosponsor_count = cosponsors.get("count", 0)

        # Latest action for status
        latest_action = data.get("latestAction", {})
        status = latest_action.get("text", "")

        provenance = ProvenanceInfo(
            source_name="congress.gov",
            source_url=data.get("url"),
            retrieved_at=datetime.utcnow(),
        )

        return Bill(
            id=citation.canonical,
            citation=citation,
            title=data.get("title"),
            short_title=data.get("shortTitle"),
            introduced_date=introduced_date,
            status=status,
            sponsor_id=sponsor_id,
            summary=None,  # Would need separate call
            provenance=provenance,
        )

    def _parse_bill_summary(self, data: dict) -> Bill | None:
        """Parse a bill summary (from list endpoints) into a Bill object."""
        # List endpoints return less data, so we parse what's available
        return self._parse_bill(data)

    def _parse_law_from_bill(self, bill_data: dict, law_info: dict) -> PublicLaw | None:
        """
        Parse a PublicLaw from bill data and embedded law info.

        The /law endpoint returns bills with law info like:
        {
            "congress": 117,
            "title": "Advancing Education on Biosimilars Act",
            "laws": [{"number": "117-8", "type": "Public Law"}],
            ...
        }
        """
        if not bill_data or not law_info:
            return None

        # Parse law number from "117-8" format
        law_number_str = law_info.get("number", "")
        if "-" in law_number_str:
            parts = law_number_str.split("-")
            congress = int(parts[0])
            law_num = int(parts[1])
        else:
            return None

        citation = PublicLawCitation(congress=congress, law_number=law_num)

        # Parse enacted date from latestAction
        enacted_date = None
        latest_action = bill_data.get("latestAction", {})
        action_date = latest_action.get("actionDate")
        if action_date:
            try:
                enacted_date = date.fromisoformat(action_date)
            except ValueError:
                pass

        # Get origin bill citation
        origin_bill = None
        bill_type_str = bill_data.get("type", "").lower()
        bill_number = bill_data.get("number")
        if bill_type_str and bill_number:
            # Map type codes to BillType
            type_map = {
                "hr": "hr", "h.r.": "hr",
                "s": "s", "s.": "s",
                "hjres": "hjres", "h.j.res.": "hjres",
                "sjres": "sjres", "s.j.res.": "sjres",
                "hconres": "hconres", "h.con.res.": "hconres",
                "sconres": "sconres", "s.con.res.": "sconres",
                "hres": "hres", "h.res.": "hres",
                "sres": "sres", "s.res.": "sres",
            }
            mapped_type = type_map.get(bill_type_str.lower(), bill_type_str.lower())
            try:
                origin_bill = BillCitation(
                    congress=congress,
                    bill_type=BillType(mapped_type),
                    number=int(bill_number),
                )
            except ValueError:
                pass  # Unknown bill type

        provenance = ProvenanceInfo(
            source_name="congress.gov",
            source_url=bill_data.get("url"),
            retrieved_at=datetime.utcnow(),
        )

        return PublicLaw(
            id=citation.canonical,
            citation=citation,
            title=bill_data.get("title"),
            enacted_date=enacted_date,
            bill_origin=origin_bill,
            provenance=provenance,
        )

    def _parse_law(self, data: dict) -> PublicLaw | None:
        """Parse API response into a PublicLaw object (legacy format)."""
        if not data:
            return None

        congress = data.get("congress")
        law_num = data.get("number")

        if not congress or not law_num:
            return None

        citation = PublicLawCitation(congress=congress, law_number=int(law_num))

        # Parse enacted date
        enacted_str = data.get("dateIssued") or data.get("approvedDate")
        enacted_date = None
        if enacted_str:
            try:
                enacted_date = date.fromisoformat(enacted_str.split("T")[0])
            except ValueError:
                pass

        # Get origin bill
        origin_bill = None
        origin = data.get("originChamber")
        origin_number = data.get("originBillNumber")
        if origin and origin_number:
            bill_type = "hr" if origin.lower() == "house" else "s"
            origin_bill = BillCitation(
                congress=congress,
                bill_type=BillType(bill_type),
                number=int(origin_number),
            )

        provenance = ProvenanceInfo(
            source_name="congress.gov",
            source_url=data.get("url"),
            retrieved_at=datetime.utcnow(),
        )

        return PublicLaw(
            id=citation.canonical,
            citation=citation,
            title=data.get("title"),
            enacted_date=enacted_date,
            bill_origin=origin_bill,
            provenance=provenance,
        )

    def _parse_member(self, data: dict) -> Entity | None:
        """Parse API response into an Entity (person) object."""
        if not data:
            return None

        bioguide_id = data.get("bioguideId")
        if not bioguide_id:
            return None

        # Build name
        name_parts = []
        if data.get("firstName"):
            name_parts.append(data["firstName"])
        if data.get("lastName"):
            name_parts.append(data["lastName"])
        name = " ".join(name_parts) or data.get("name", "Unknown")

        # Get party and state
        party = data.get("partyName") or data.get("party")
        state = data.get("state")

        provenance = ProvenanceInfo(
            source_name="congress.gov",
            source_url=data.get("url"),
            retrieved_at=datetime.utcnow(),
        )

        return Entity(
            id=f"person:{bioguide_id}",
            name=name,
            entity_type=EntityType.PERSON,
            bioguide_id=bioguide_id,
            party=party,
            state=state,
            provenance=provenance,
        )

    def _parse_committee_report(self, data: dict, congress: int) -> CommitteeReport | None:
        """Parse API response into a CommitteeReport object."""
        if not data:
            return None

        report_type = data.get("type", "").upper()
        report_num = data.get("number")

        if not report_num:
            return None

        # Build report number string (e.g., "H. Rept. 117-123")
        if report_type == "HRPT":
            report_number = f"H. Rept. {congress}-{report_num}"
            chamber = "House"
        elif report_type == "SRPT":
            report_number = f"S. Rept. {congress}-{report_num}"
            chamber = "Senate"
        else:
            report_number = f"{report_type} {congress}-{report_num}"
            chamber = "Unknown"

        # Parse date
        report_date_str = data.get("updateDate")
        report_date = None
        if report_date_str:
            try:
                report_date = date.fromisoformat(report_date_str.split("T")[0])
            except ValueError:
                pass

        # Get associated bill if any
        associated_bills = data.get("associatedBill", [])
        bill_citation = None
        if associated_bills:
            ab = associated_bills[0] if isinstance(associated_bills, list) else associated_bills
            if ab.get("type") and ab.get("number"):
                try:
                    bill_citation = BillCitation(
                        congress=congress,
                        bill_type=BillType(ab["type"].lower()),
                        number=int(ab["number"]),
                    )
                except (ValueError, KeyError):
                    pass

        provenance = ProvenanceInfo(
            source_name="congress.gov",
            source_url=data.get("url"),
            retrieved_at=datetime.utcnow(),
        )

        return CommitteeReport(
            id=f"report:{report_number}",
            report_number=report_number,
            congress=congress,
            chamber=chamber,
            committee=data.get("committee", {}).get("name", "Unknown"),
            title=data.get("title"),
            report_date=report_date,
            bill_citation=bill_citation,
            provenance=provenance,
        )


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    import sys

    api_key = os.getenv("CONGRESS_GOV_API_KEY")
    if not api_key:
        print("Set CONGRESS_GOV_API_KEY environment variable")
        sys.exit(1)

    with CongressGovAdapter(api_key) as adapter:
        # Test: Get a famous bill (ACA)
        print("Fetching H.R. 3590 (111th Congress) - Affordable Care Act...")
        bill = adapter.get_bill(111, "hr", 3590)
        if bill:
            print(f"  Title: {bill.title}")
            print(f"  Status: {bill.status}")
            print(f"  Introduced: {bill.introduced_date}")

        # Test: Get some public laws
        print("\nFetching recent public laws from 117th Congress...")
        for i, law in enumerate(adapter.get_laws(117)):
            if i >= 5:
                break
            print(f"  {law.citation}: {law.title}")
