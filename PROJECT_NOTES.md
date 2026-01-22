# Legislative Intelligence System - Project Notes

This document tracks implementation details, decisions, and gotchas for future reference.

---

## Project Overview

**Goal**: Build a RAG system that combines US Code with legislative history, regulations, court cases, lobbying data, and public comments to tell the "story" of any law.

**First Project**: "Story of a Law" - Given a USC citation like `42 USC 1395` (Medicare), generate a comprehensive narrative showing origin, amendments, regulations, court interpretations, and lobbying activity.

**Pilot Domain**: Medicare (Title 42, sections 1395+)

---

## Architecture

### Core Components

1. **Citation Graph** (Neo4j)
   - Nodes: USCSection, PublicLaw, Bill, CFRSection, Case, Entity, etc.
   - Edges: AMENDS, ENACTS, IMPLEMENTS, INTERPRETS, CITES, LOBBIED_ON, SPONSORED
   - All nodes have provenance (source_url, retrieved_at) and temporal info (effective_date)

2. **Citation Parser** (`src/parsers/citations.py`)
   - The linchpin - extracts and normalizes legal citations from any text
   - Handles USC, Public Laws, Bills, CFR, Federal Register, Statutes at Large
   - Canonical form: `42 USC 1395`, `Pub. L. 89-97`, `H.R. 1234-117`

3. **Adapters** (`src/adapters/`)
   - `usc_xml.py` - Parses USLM XML from uscode.house.gov
   - `congress_gov.py` - Congress.gov API client

4. **Graph Store** (`src/graph/neo4j_store.py`)
   - Neo4j connection management
   - CRUD for nodes/edges
   - Query helpers for traversals

5. **Ingestion Pipeline** (`src/ingest/pipeline.py`)
   - Orchestrates data loading
   - Tracks progress with rich console output

6. **Story Generator** (`src/api/story.py`)
   - Main interface: `StoryOfALaw.get_story("42 USC 1395")`
   - Returns `LawStory` with timeline, amendments, regulations, cases
   - Can output as dict, markdown, or timeline data

---

## Data Sources

### Currently Implemented

| Source | Status | Notes |
|--------|--------|-------|
| US Code (XML) | **Working** | 6,651 sections from Title 42 loaded |
| Congress.gov API | Adapter ready | Need API key for enrichment |

### Planned

| Source | API/Format | Priority |
|--------|------------|----------|
| Federal Register | REST API | High - RFIs, proposed rules |
| Regulations.gov | REST API | High - public comments |
| CourtListener | REST API | Medium - case law |
| GovInfo | Bulk XML | Medium - CFR, bills |
| OpenSecrets | REST API | Lower - lobbying |

---

## Setup & Running

### Prerequisites

```bash
# Neo4j must be running
brew services start neo4j

# Or in console mode:
/opt/homebrew/opt/neo4j/bin/neo4j console
```

### Environment Variables

File: `.env`
```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=legislative123
CONGRESS_GOV_API_KEY=<your_key>
```

### Commands

```bash
# Download US Code title
python3 scripts/download_usc.py 42

# Initialize database schema
python3 -m src.ingest.pipeline init

# Ingest USC XML
python3 -m src.ingest.pipeline ingest data/raw/usc/usc42.xml

# Enrich with Congress.gov data
python3 -m src.ingest.pipeline enrich 117

# Get story for a citation
python3 -m src.api.story "42 USC 1395"

# Show stats
python3 -m src.ingest.pipeline stats
```

---

## Technical Gotchas

### Python 3.9 Compatibility

The system runs on Python 3.9, which doesn't support `X | None` union syntax at runtime. Every file needs:
```python
from __future__ import annotations
```

Also needed `pip3 install eval_type_backport` for Pydantic v2 on 3.9.

### US Code Download URLs

The URL format is tricky. Current working format:
```
https://uscode.house.gov/download/releasepoints/us/pl/119/69not60/xml_usc42@119-69not60.zip
```

Note the `69not60` - this is the release point identifier. It changes over time as new laws are enacted.

### Neo4j Default Password

Fresh Neo4j install uses `neo4j`/`neo4j` but requires password change on first login. We set it to `legislative123` using:
```bash
neo4j-admin dbms set-initial-password legislative123
```

This only works BEFORE first database start. After that, use Neo4j Browser at http://localhost:7474 to change password.

### Citation Parser Edge Cases

- Public Laws: `Pub. L. 89-97`, `P.L. 111-148`, `Public Law 89–97` (em-dash vs hyphen)
- USC: `42 U.S.C. § 1395`, `42 USC 1395`, `42 U.S.C. 1395(a)(1)`
- Bills: `H.R. 1234`, `S. 5678`, `H.R.1234` (with/without space)

The parser handles all these and normalizes to canonical form.

---

## Current State (Jan 2026)

### What's Loaded

- **Title 42**: 6,651 sections (THE PUBLIC HEALTH AND WELFARE)
- **Medicare sections**: 67 sections (1395 family)
- **Public Laws**: 362 from 117th Congress
- **Members of Congress**: 557 entities
- **ENACTS edges**: 248 (Public Law → Section it created)
- **AMENDS edges**: 332 (Public Law → Section it modified)

### Sample Query Results

The system can now show the complete legislative history for sections amended by recent laws:

```
42 USC 10303: Water resources research and technology institutes
  Timeline:
    - August 04, 2022: Amended by Pub. L. 117-58
      (Infrastructure Investment and Jobs Act)

42 USC 1103: Amounts transferred to State accounts
  ← AMENDS ← Pub. L. 117-2: American Rescue Plan Act of 2021
```

### Congress.gov API Fix (Important!)

The `/law/{congress}` endpoint returns `bills` not `laws` in the response. The `_parse_law_from_bill` method was added to handle this. The law number comes from the embedded `laws` array like `{"number": "117-58", "type": "Public Law"}`.

### What's Missing (next phase)

- CFR regulations (regulations.gov)
- Court cases (CourtListener)
- Lobbying data (OpenSecrets)
- Older Public Laws (pre-117th Congress)

---

## API Keys & Accounts

### Congress.gov API
- Sign up: https://api.congress.gov/sign-up/
- Rate limit: 5,000 requests/hour
- Key stored in `.env` as `CONGRESS_GOV_API_KEY`

---

## File Structure

```
legislative-intelligence/
├── data/
│   └── raw/
│       └── usc/
│           └── usc42.xml          # 107MB Title 42
├── scripts/
│   ├── download_usc.py            # USC downloader
│   ├── demo.py                    # Interactive demo
│   └── link_laws.py               # Create PL→USC edges
├── src/
│   ├── adapters/
│   │   ├── congress_gov.py        # Congress.gov API
│   │   └── usc_xml.py             # USLM XML parser
│   ├── api/
│   │   └── story.py               # Story of a Law generator
│   ├── graph/
│   │   └── neo4j_store.py         # Neo4j interface
│   ├── ingest/
│   │   └── pipeline.py            # Ingestion orchestration
│   ├── parsers/
│   │   └── citations.py           # Citation extraction
│   └── models.py                  # Pydantic models
├── tests/
│   └── test_citations.py          # Citation parser tests
├── .env                           # Environment variables
├── pyproject.toml                 # Project config
├── README.md                      # User documentation
└── PROJECT_NOTES.md               # This file
```

---

## Next Steps

1. ~~**Add Congress.gov API key**~~ - DONE
2. ~~**Run enrichment**~~ - DONE (362 PLs, 580 edges)
3. ~~**Build FastAPI endpoints**~~ - DONE (see API section below)
4. **Add Federal Register adapter** - RFIs and proposed rules
5. **Add CFR adapter** - Implementing regulations
6. **Add vector search** - Semantic search alongside graph traversal
7. **Load older Congresses** - 116th, 115th, etc. for more coverage

---

## FastAPI REST API

The system now has a full REST API accessible at `http://localhost:8080`.

### Starting the API Server

```bash
python3 -m uvicorn src.api.main:app --host 127.0.0.1 --port 8080

# With auto-reload for development:
python3 -m uvicorn src.api.main:app --reload
```

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | API info and available endpoints |
| `/story/{citation}` | GET | Get the complete story of a law |
| `/search?q=term` | GET | Search USC sections by name/content |
| `/parse?text=...` | POST | Parse legal citations from text |
| `/section/{citation}` | GET | Get a specific USC section |
| `/public-law/{citation}` | GET | Get a Public Law and its amendments |
| `/medicare` | GET | Get all Medicare sections (pilot domain) |
| `/stats` | GET | Database statistics |
| `/health` | GET | Health check |

### Example Requests

```bash
# Get the story of a law
curl "http://localhost:8080/story/42%20USC%2010303"

# Search for hospital-related sections
curl "http://localhost:8080/search?q=hospital&limit=10"

# Parse citations from text
curl -X POST "http://localhost:8080/parse?text=Pub.%20L.%20111-148%20amended%2042%20USC%201395"

# Get a Public Law with affected sections
curl "http://localhost:8080/public-law/Pub.%20L.%20117-58?amendments=true"

# Database stats
curl "http://localhost:8080/stats"
```

### OpenAPI Documentation

When the server is running, visit:
- Swagger UI: http://localhost:8080/docs
- ReDoc: http://localhost:8080/redoc

---

## Session Recovery Notes

If picking up this project:

1. Check if Neo4j is running: `brew services list | grep neo4j`
2. Test connection: `python3 -c "from neo4j import GraphDatabase; ..."`
3. Check current data: `python3 -m src.ingest.pipeline stats`
4. The `.env` file has all credentials

Key files to understand the system:
- `src/models.py` - Data structures
- `src/parsers/citations.py` - The citation parser (linchpin)
- `src/api/story.py` - Main interface
