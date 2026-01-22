# External Data Sources for Legislative Context (Tier 5)

Research completed: January 21, 2026

This document catalogs external data sources for providing context about why laws were passed, political dynamics, expert analysis, and stakeholder interests. These sources complement the official legislative data in Tiers 1-4.

---

## Table of Contents

1. [CRS Reports (Congressional Research Service)](#1-crs-reports-congressional-research-service)
2. [Committee Reports](#2-committee-reports)
3. [News and Analysis Sources](#3-news-and-analysis-sources)
4. [Lobbying Data](#4-lobbying-data)
5. [CHIPS Act Specific Resources](#5-chips-act-specific-resources)
6. [Integration Recommendations](#6-integration-recommendations)

---

## 1. CRS Reports (Congressional Research Service)

CRS reports provide nonpartisan expert analysis on legislative issues. They are invaluable for understanding the policy context, arguments for/against legislation, and implementation details.

### Primary Sources

#### Official: crsreports.congress.gov

- **URL**: https://crsreports.congress.gov/
- **Authentication**: None required for public access
- **Format**: PDF and HTML
- **API**: Limited - Library of Congress has begun publishing some reports via API
- **Coverage**: Public reports from 2018 onward (when public access was mandated)

#### EveryCRSReport.com (Recommended for bulk access)

- **URL**: https://www.everycrsreport.com/
- **Authentication**: None required
- **Format**: JSON metadata + PDF/HTML files
- **Coverage**: 22,000+ reports, including historical reports pre-2018

**Bulk Download Resources**:
- CSV listing of all reports: `https://www.everycrsreport.com/reports.csv`
- Individual report metadata: `https://www.everycrsreport.com/reports/{REPORT_ID}.json`
- Report PDFs/HTML: Listed in metadata JSON under `formats[].filename`

**JSON Metadata Structure**:
```json
{
  "id": "R47523",
  "versions": [
    {
      "id": "version_id",
      "source": "source_info",
      "date": "2023-04-25",
      "title": "Report Title",
      "summary": "Report summary text",
      "formats": [
        {"format": "PDF", "filename": "files/xxx.pdf"},
        {"format": "HTML", "filename": "files/xxx.html"}
      ],
      "topics": [
        {"source": "IBCList", "name": "Topic Name", "id": "topic_id"}
      ]
    }
  ]
}
```

#### Federation of American Scientists (FAS) Mirror

- **URL**: https://sgp.fas.org/crs/
- **Format**: PDF files organized by topic category
- **Use case**: Backup source, includes some classified/restricted reports

### Limitations

1. **No direct bill/law linking**: CRS metadata does not include bill numbers or public law citations. Linking requires text analysis or manual mapping.
2. **No real-time API**: EveryCRSReport provides bulk download but no live query API.
3. **Version tracking**: Multiple versions exist for updated reports; must track by date.

### Recommended Integration Approach

1. Download the full CSV listing periodically (weekly)
2. Fetch JSON metadata for each new/updated report
3. Extract report text and use keyword matching to link to bills/laws
4. Build a local search index for querying by topic or law reference

---

## 2. Committee Reports

Committee reports explain the committee's findings and recommendations on legislation. They often contain the most detailed explanation of legislative intent.

### Congress.gov API (Primary Source)

- **Base URL**: `https://api.congress.gov/v3/committee-report`
- **Authentication**: API key required (free at https://api.congress.gov/sign-up/)
- **Rate Limit**: 5,000 requests/hour
- **Format**: JSON or XML

**Endpoints**:

| Endpoint | Description | Example |
|----------|-------------|---------|
| `/committee-report` | List all reports | All reports |
| `/committee-report/{congress}` | Filter by Congress | 117th Congress |
| `/committee-report/{congress}/{type}` | Filter by type | House reports |
| `/committee-report/{congress}/{type}/{number}` | Specific report | H.Rept. 117-73 |
| `/committee-report/{congress}/{type}/{number}/text` | Report text | Full text |

**Report Types**:
- `hrpt` - House Report
- `srpt` - Senate Report
- `erpt` - Executive Report

**Key Fields in Response**:
```json
{
  "congress": 117,
  "chamber": "House",
  "sessionNumber": 2,
  "citation": "H. Rept. 117-73",
  "number": 73,
  "associatedBill": {
    "congress": 117,
    "type": "HR",
    "number": 2225,
    "url": "https://api.congress.gov/v3/bill/117/hr/2225"
  },
  "committees": [
    {"systemCode": "hssy00", "name": "Science, Space, and Technology Committee"}
  ]
}
```

**Critical Feature**: The `associatedBill` field directly links reports to their related legislation.

### GovInfo API (Supplementary)

- **Base URL**: `https://api.govinfo.gov`
- **Authentication**: API key from api.data.gov (free)
- **Documentation**: https://api.govinfo.gov/docs/

**Related Documents Endpoint**:
```
https://api.govinfo.gov/related/{packageId}
```

From a bill's packageId (e.g., `BILLS-117hr4346enr`), you can retrieve:
- Congressional Committee Prints
- Congressional Reports
- U.S. Code References
- Statutes at Large References

**Bulk Data**:
- XML bulk downloads: https://www.govinfo.gov/bulkdata
- Committee reports available in bulk

### Limitations

1. **Coverage**: Committee reports may lag in API availability
2. **Text extraction**: Reports are often PDF-based, requiring parsing
3. **Conference reports**: Require separate filtering

### Recommended Integration Approach

1. Use Congress.gov API as primary source (has direct bill linking)
2. Query by Congress and bill number to find associated reports
3. Use GovInfo `/related` endpoint to discover additional linked documents
4. Cache report metadata locally with bill relationship mapping

---

## 3. News and Analysis Sources

### Available APIs

#### LegiScan (Active - Recommended)

- **URL**: https://legiscan.com/legiscan
- **Authentication**: API key required
- **Free Tier**: 30,000 queries/month
- **Format**: JSON
- **Coverage**: All 50 states + Congress

**Features**:
- Bill tracking with status updates
- Sponsor information
- Full bill text
- Roll call votes
- Change notifications (push API available)

**Limitations**: News/analysis not included; focuses on legislative data.

#### ProPublica Congress API (Discontinued)

- **Status**: No longer available as of February 2025
- **Note**: Documentation archived on GitHub for historical reference
- Alternative: Use Congress.gov API

#### GovTrack (Limited)

- **URL**: https://www.govtrack.us/
- **Status**: Bulk data and API discontinued
- **Alternative**: Use official Congress.gov API

#### Quorum (Commercial)

- **URL**: https://www.quorum.us/products/quorum-api/
- **Authentication**: Enterprise license required
- **Format**: REST API, JSON; also SFTP bulk transfer
- **Coverage**: Congress, 50 states, 3,000+ localities, 40+ countries

**Features**:
- Bill status and tracking
- Legislator/staff directories (65,000+ officials)
- AI-powered analysis
- Hourly updates

**Limitations**: Paid enterprise product; not suitable for open-source project.

### News Aggregation Alternatives

For linking news articles to specific laws, no structured API exists. Options include:

1. **Google News API** - General news search, filter by keywords
2. **NewsAPI.org** - 80,000+ sources, keyword search
3. **Manual curation** - Build a database of key articles for major legislation

### Recommended Integration Approach

1. Use LegiScan for supplementary bill tracking data (free tier sufficient)
2. For news linking, implement keyword-based search using bill titles/numbers
3. Consider building a curated database of landmark legislation coverage

---

## 4. Lobbying Data

### OpenSecrets (Primary Source)

- **URL**: https://www.opensecrets.org/open-data
- **API Status**: **Discontinued as of April 15, 2025**
- **Current Access**: Bulk data downloads only

**Bulk Data Available**:
- **URL**: https://www.opensecrets.org/open-data/bulk-data
- **Format**: Compressed CSV files
- **Documentation**: https://www.opensecrets.org/open-data/bulk-data-documentation

**Lobbying Data Fields**:
- Clients (who is lobbying)
- Registrants (lobbying firms)
- Individual lobbyists
- **Bills lobbied** (links lobbying to specific legislation)
- Amounts spent

**Linking to Bills**:
The lobbying bulk data includes bill references, allowing you to:
1. Identify which organizations lobbied on a specific bill
2. Track lobbying expenditures related to legislation
3. See which lobbyists worked on particular issues

**Data Dictionary**: Available for every file at the bulk data documentation page.

### Limitations

1. **No real-time API**: Must download bulk files and process locally
2. **Update frequency**: Quarterly based on disclosure filings
3. **Historical only**: Reflects past lobbying, not current activity

### Senate Lobbying Disclosure Database

- **URL**: https://lda.senate.gov/
- **Format**: Searchable web interface, some bulk download
- **Official source**: Direct from Senate Office of Public Records

### Recommended Integration Approach

1. Download OpenSecrets bulk lobbying data quarterly
2. Build local database with bill-to-lobbying mapping
3. Create queries to retrieve lobbying activity for any given bill/law
4. Supplement with Senate disclosure data for most current filings

---

## 5. CHIPS Act Specific Resources

### Key CRS Reports

| Report ID | Title | Date | PDF URL |
|-----------|-------|------|---------|
| R47523 | Frequently Asked Questions: CHIPS Act of 2022 Provisions and Implementation | April 2023 | https://crsreports.congress.gov/product/pdf/R/R47523 |
| R47558 | Semiconductors and the CHIPS Act: The Global Context | Sept 2023 | https://crsreports.congress.gov/product/pdf/R/R47558 |
| IF12589 | Research Security Policies: An Overview | Dec 2024 | https://crsreports.congress.gov/product/pdf/IF/IF12589 |

**R47523 Summary**: Covers the $52.7 billion in appropriations, four funding mechanisms (CHIPS for America Fund, Defense Fund, International Technology Security Fund, Workforce Fund), and implementation status.

**R47558 Summary**: Places U.S. semiconductor policy in global context, covering actions by Japan, South Korea, Taiwan, China, Europe, India, and Southeast Asia. Essential for understanding competitive dynamics.

### Key Committee Reports

| Report | Title | Committee | Bill |
|--------|-------|-----------|------|
| H. Rept. 117-73 | National Science Foundation for the Future Act | Science, Space, and Technology | H.R. 2225 |
| H. Rept. 117-247 | National Institute of Standards and Technology for the Future Act | Science, Space, and Technology | H.R. 4609 |
| H. Rept. 117-72 | Department of Energy Science for the Future Act | Science, Space, and Technology | H.R. 3593 |
| H. Rept. 117-452 | Microelectronics Research for Energy Innovation Act | Science, Space, and Technology | H.R. 6291 |

**Note**: The CHIPS and Science Act (H.R. 4346) had unusual legislative history - it began as a Legislative Branch appropriations bill, was amended in the Senate with Supreme Court security provisions, then received the semiconductor/science provisions via floor amendment (SA 5135). This means there is no single traditional committee report for the final law.

### API Queries for CHIPS Act Data

**Congress.gov API - Get bill info**:
```
GET https://api.congress.gov/v3/bill/117/hr/4346?api_key=YOUR_KEY
```

**Congress.gov API - Get related committee reports**:
```
GET https://api.congress.gov/v3/bill/117/hr/4346/committees?api_key=YOUR_KEY
```

**GovInfo - Related documents**:
```
GET https://api.govinfo.gov/related/BILLS-117hr4346enr?api_key=YOUR_KEY
```

### Additional CHIPS Context Sources

1. **NSF CHIPS Portal**: https://www.nsf.gov/chips - Official implementation information
2. **Commerce Department CHIPS Office**: Implementation updates and funding announcements
3. **AAAS Analysis**: https://www.aaas.org/programs/office-government-relations/breaking-down-chips-and-science-act

---

## 6. Integration Recommendations

### Priority Order for Implementation

1. **Congress.gov API** (Committee Reports)
   - Direct bill linking via `associatedBill`
   - Official source, reliable
   - Free with generous rate limits

2. **EveryCRSReport.com** (CRS Reports)
   - Bulk download capability
   - JSON metadata format
   - Requires keyword matching for bill linking

3. **GovInfo API** (Document Relationships)
   - `/related` endpoint for cross-referencing
   - Bulk XML downloads available
   - Good for discovering linked documents

4. **OpenSecrets Bulk Data** (Lobbying)
   - Quarterly download
   - Contains bill-to-lobbying links
   - Valuable for "who cares about this law" context

### Architecture Suggestion

```
Tier 5 Data Pipeline:

1. Scheduled Jobs (Weekly/Quarterly):
   - Fetch new CRS reports from EveryCRSReport CSV
   - Download updated OpenSecrets lobbying data
   - Sync committee reports from Congress.gov

2. On-Demand Queries:
   - Given a Public Law number, query Congress.gov for associated bill
   - Use bill number to find committee reports
   - Query local CRS index for matching reports
   - Query local lobbying database for related activity

3. Linking Strategy:
   - Congress.gov API provides bill <-> committee report links
   - CRS reports require text search (bill numbers, law names)
   - Lobbying data includes explicit bill references
```

### Data Storage Schema (Suggested)

```sql
-- CRS Reports
CREATE TABLE crs_reports (
    report_id TEXT PRIMARY KEY,  -- e.g., "R47523"
    title TEXT,
    summary TEXT,
    latest_date DATE,
    pdf_url TEXT,
    html_url TEXT,
    topics JSONB
);

-- CRS Report to Law Mapping (derived via text analysis)
CREATE TABLE crs_law_links (
    report_id TEXT REFERENCES crs_reports,
    public_law TEXT,      -- e.g., "117-167"
    bill_number TEXT,     -- e.g., "HR4346"
    congress INTEGER,
    confidence FLOAT,     -- 0-1 score
    PRIMARY KEY (report_id, public_law)
);

-- Committee Reports (from Congress.gov API)
CREATE TABLE committee_reports (
    citation TEXT PRIMARY KEY,  -- e.g., "H. Rept. 117-73"
    congress INTEGER,
    chamber TEXT,
    report_number INTEGER,
    title TEXT,
    committee_name TEXT,
    associated_bill_type TEXT,
    associated_bill_number INTEGER,
    text_url TEXT
);

-- Lobbying Activity (from OpenSecrets)
CREATE TABLE lobbying_activity (
    id SERIAL PRIMARY KEY,
    registrant TEXT,
    client TEXT,
    lobbyist TEXT,
    amount DECIMAL,
    year INTEGER,
    quarter INTEGER,
    bills_lobbied TEXT[],  -- Array of bill identifiers
    issues TEXT[]
);
```

### Coverage Gaps

1. **Real-time news**: No structured API links news to legislation
2. **Floor debate analysis**: Congressional Record exists but requires NLP to extract relevant portions
3. **Think tank reports**: Scattered across many sites, no central API
4. **State-level context**: Limited to LegiScan for legislative data

### Cost Considerations

| Source | Cost | Notes |
|--------|------|-------|
| Congress.gov API | Free | 5,000 req/hour |
| GovInfo API | Free | Requires api.data.gov key |
| EveryCRSReport | Free | Bulk download |
| OpenSecrets Bulk | Free | Educational use |
| LegiScan | Free tier | 30,000 queries/month |
| Quorum | $$$$ | Enterprise only |

---

## Sources

- [Congress.gov API Documentation](https://github.com/LibraryOfCongress/api.congress.gov)
- [EveryCRSReport Bulk Download](https://www.everycrsreport.com/download.html)
- [GovInfo Developer Hub](https://www.govinfo.gov/developers)
- [OpenSecrets Bulk Data](https://www.opensecrets.org/open-data/bulk-data)
- [LegiScan API](https://legiscan.com/legiscan)
- [Congressional Data Coalition](https://congressionaldata.org/)
