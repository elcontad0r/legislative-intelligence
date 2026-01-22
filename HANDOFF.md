# Legislative Intelligence System - Handoff Document

*Last updated: January 2026*

## What This Project Is

A **RAG system for US law** that combines the US Code with legislative history to tell the "story" of any statute - when it was enacted, how it's been amended, by which Public Laws, and (eventually) how it's been implemented via regulations and interpreted by courts.

**Pilot domain**: Medicare (Title 42, specifically sections 1395+)

**Current state**: Working MVP with CLI demo and REST API. Can ingest USC XML, enrich with Congress.gov data, build a citation graph in Neo4j, and generate narrative "stories" for any section.

---

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Data Sources   │     │   Ingest Layer   │     │   Storage       │
│                 │     │                  │     │                 │
│ • uscode.house  │────▶│ • USLM Parser    │────▶│ • Neo4j Graph   │
│   .gov (XML)    │     │ • Citation       │     │   (citations)   │
│ • Congress.gov  │     │   Parser         │     │                 │
│   API           │     │ • Congress.gov   │     │ (Future:        │
│                 │     │   Adapter        │     │  PostgreSQL +   │
└─────────────────┘     └──────────────────┘     │  pgvector)      │
                                                  └────────┬────────┘
                                                           │
                        ┌──────────────────┐               │
                        │   Query Layer    │◀──────────────┘
                        │                  │
                        │ • StoryOfALaw    │
                        │ • FastAPI        │
                        │   endpoints      │
                        └──────────────────┘
```

---

## Key Files & Their Purposes

### Core Components

| File | Purpose |
|------|---------|
| `src/parsers/citations.py` | Regex-based citation extractor. Handles USC, Public Law, CFR, bill citations. |
| `src/parsers/uslm.py` | Parses USLM XML format from uscode.house.gov. Extracts sections, text, source credits. |
| `src/adapters/congress_gov.py` | Congress.gov API v3 client. Gets Public Laws, bills, members. **Note the gotcha below.** |
| `src/graph/neo4j_store.py` | Neo4j interface. Schema init, node/edge creation, queries. |
| `src/ingest/pipeline.py` | CLI for `init`, `ingest`, `enrich` commands. |
| `src/api/story.py` | `StoryOfALaw` class - builds narratives from graph data. |
| `src/api/main.py` | FastAPI application with REST endpoints. |

### Scripts

| File | Purpose |
|------|---------|
| `scripts/demo.py` | Interactive demo showing all capabilities. Good for testing. |
| `scripts/link_laws.py` | Creates AMENDS/ENACTS edges by parsing source_credit fields. **Run after enrichment.** |

### Configuration

| File | Purpose |
|------|---------|
| `.env` | API keys and Neo4j credentials. **Required.** |
| `pyproject.toml` | Dependencies and project config. Set to Python 3.9+. |
| `PROJECT_NOTES.md` | Detailed technical notes, gotchas, current state. |

---

## Current Database State

```
Nodes:
  - USCSection: 6,651 (all of Title 42)
  - PublicLaw: 362 (117th Congress only)
  - Entity: 557 (Members of Congress)

Relationships:
  - AMENDS: 332
  - ENACTS: 248
```

To verify: `python3 -m src.ingest.pipeline stats`

---

## How to Run Things

### Prerequisites
```bash
# Neo4j must be running
brew services start neo4j
# Or check: brew services list | grep neo4j
```

### Commands

```bash
# Check graph stats
python3 -m src.ingest.pipeline stats

# Run the interactive demo
python3 scripts/demo.py

# Start the API server
python3 -m uvicorn src.api.main:app --host 127.0.0.1 --port 8080

# Get story for a specific section
python3 -m src.api.story "42 USC 10303"
```

### API Endpoints (when server running)
- `GET /story/{citation}` - Full narrative for a USC section
- `GET /search?q=term` - Search sections
- `GET /public-law/{citation}?amendments=true` - Public Law with affected sections
- `GET /stats` - Database statistics
- `GET /docs` - Swagger UI

---

## Critical Gotchas & Failure Points

### 1. Congress.gov API Response Structure

**Problem**: The `/law/{congress}` endpoint doesn't return `laws` - it returns `bills` with embedded law info.

**Location**: `src/adapters/congress_gov.py`, `get_laws()` method

**What the API actually returns**:
```json
{
  "bills": [
    {
      "congress": 117,
      "title": "Infrastructure Investment...",
      "laws": [{"number": "117-58", "type": "Public Law"}]
    }
  ]
}
```

**The fix** (already implemented): Look for `bills` key, iterate, extract `laws` from each bill. See `_parse_law_from_bill()` method.

### 2. Python 3.9 Type Hint Compatibility

**Problem**: System Python is 3.9.6. Union types like `str | None` fail at runtime in decorators.

**Solution**:
- All files use `from __future__ import annotations` at the top
- FastAPI decorators use `Union[A, B]` instead of `A | B`
- pyproject.toml set to `requires-python = ">=3.9"`

**If you add new files**: Always include `from __future__ import annotations` as first import.

### 3. Attio MCP Checkbox Bug (from CLAUDE.md)

**Not directly relevant here**, but if Austin asks you to update Attio records:
- For **people**: Use boolean `true`/`false` for checkboxes
- For **companies**: Both `"__YES__"` and `true` work
- The `"__YES__"` translation is only implemented for companies

### 4. Neo4j Password

**Current password**: `legislative123`

If you get auth errors:
```bash
# Reset password
neo4j-admin dbms set-initial-password NEW_PASSWORD
# Update .env file
```

### 5. Citation Matching Coverage

**Current limitation**: Only 117th Congress Public Laws are loaded (~362). The USC has citations to PLs from many Congresses, so many citations won't resolve to nodes.

**To improve**: Run enrichment for more Congresses:
```bash
python3 -m src.ingest.pipeline enrich 116
python3 -m src.ingest.pipeline enrich 115
python3 scripts/link_laws.py  # Re-run to create new edges
```

### 6. Source Credit Parsing

The `source_credit` field in USC sections contains the legislative history but is messy text. The `link_laws.py` script extracts Public Law citations from it. First citation = ENACTS, subsequent = AMENDS. This is a heuristic, not perfect.

---

## Dependencies Actually Used vs Declared

**Installed and used**:
- neo4j, pydantic, httpx, rich, lxml, fastapi, uvicorn, python-dotenv

**In pyproject.toml but NOT installed/used yet**:
- pgvector, psycopg (for future vector search)
- openai (for future embeddings)
- eyecite (we built our own citation parser)
- pandas, beautifulsoup4, tqdm, tenacity

These are aspirational. Don't install them unless implementing those features.

---

## What's Not Built Yet

1. **Vector search** - Semantic search via embeddings. Would need PostgreSQL + pgvector + OpenAI embeddings.

2. **Federal Register adapter** - For RFIs, proposed rules, final rules that implement statutes.

3. **CFR adapter** - Code of Federal Regulations, the implementing regulations.

4. **Court case adapter** - CourtListener or similar for judicial interpretations.

5. **More Congresses** - Currently only 117th loaded. Easy to add more.

6. **Full-text indexing** - Current search is naive `CONTAINS`. Could add Elasticsearch or Neo4j full-text indexes.

---

## Environment Variables (.env)

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=legislative123
CONGRESS_GOV_API_KEY=wygUPV7ZomHnFx3t2ycrgn1HN3uTLXAbI9lavsRk
```

---

## Testing the System

Quick smoke test:
```bash
# 1. Check Neo4j is running
curl -s http://localhost:7474 && echo "Neo4j web UI up"

# 2. Check graph has data
python3 -m src.ingest.pipeline stats

# 3. Test story generation
python3 -m src.api.story "42 USC 10303"

# 4. Run demo
python3 scripts/demo.py
```

If something fails, check:
1. Is Neo4j running? `brew services list`
2. Is .env present and correct?
3. Are dependencies installed? `pip3 list | grep neo4j`

---

## Session Recovery

Previous session transcripts are in:
```
~/.claude/projects/-Users-austincarson-Documents-SBC/*.jsonl
```

Large files (10MB+) likely had extensive work.

---

## Questions You Might Get Asked

**"Can you show me Medicare sections?"**
```bash
curl "http://localhost:8080/search?q=medicare&limit=20"
# Or in Neo4j: MATCH (u:USCSection) WHERE u.id STARTS WITH "42 USC 1395" RETURN u.id, u.section_name
```

**"What did the Infrastructure Act change?"**
```bash
curl "http://localhost:8080/public-law/Pub.%20L.%20117-58?full=true&amendments=true"
```

**"Add more Congresses"**
```bash
python3 -m src.ingest.pipeline enrich 116
python3 scripts/link_laws.py
```

**"Why aren't all citations resolving?"**
Because only 117th Congress PLs are loaded. A citation to Pub. L. 89-97 (original Medicare act from 1965) won't have a node in the graph.

---

## Code Style Notes

- Austin prefers casual, direct communication
- "Whiz bang" > "totally fine" for deliverables
- Don't pad with filler
- When fabrication is possible (case studies, policy claims), verify meticulously against sources
- Check CLAUDE.md for full working preferences
