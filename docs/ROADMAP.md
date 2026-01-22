# Legislative Intelligence System - Implementation Roadmap

**Goal**: Build a comprehensive system that traces the "Story of a Law" - from enactment through amendments, regulations, court interpretations, and lobbying activity.

This document captures the original vision, implementation phases, and current progress.

---

## The Vision (Original Brainstorm)

> Input: Any section of US Code
> Output: Visual timeline showing the original bill, every amendment, committee reports, floor debate excerpts, lobbying activity, relevant RFI responses, and how courts have interpreted it

The key insight: **The data exists but isn't connected.** Legal researchers do this manually. We're building the connective tissue.

---

## Available Data Sources

### Currently Using
| Source | Status | Notes |
|--------|--------|-------|
| US Code (XML) | **Working** | 6,651 sections from Title 42, USLM schema |
| Congress.gov API | **Working** | Bills, PLs, 362 laws from 117th Congress |
| Anthropic Claude | **Working** | Narrative generation, summaries |

### Ready to Integrate
| Source | API/Format | Priority | What It Adds |
|--------|------------|----------|--------------|
| Federal Register API | REST (free) | HIGH | Proposed rules, final rules, notices |
| Regulations.gov API | REST (key required) | HIGH | Public comments on rulemakings |
| GovInfo Bulk | XML | MEDIUM | CFR, bills in bulk |
| CourtListener/RECAP | REST (free) | MEDIUM | Court opinions, judicial interpretation |
| OpenSecrets | REST + Bulk | LOWER | Lobbying disclosure, campaign finance |
| CRS Reports | Congress.gov | LOWER | Policy analysis |
| GAO Reports | API | LOWER | Oversight findings |

---

## Implementation Phases

### Phase 0: Infrastructure ✅ COMPLETE

- [x] Graph database (Neo4j Aura cloud)
- [x] FastAPI application
- [x] Railway deployment
- [x] Anthropic API integration
- [x] Basic project structure

### Phase 1: Core Ingestion - US Code ✅ COMPLETE

- [x] Download US Code XML bulk
- [x] Parse USLM schema (`src/adapters/usc_xml.py`)
- [x] Extract: sections, cross-references, history notes
- [x] Build initial citation graph (USCSection nodes)
- [x] On-demand text retrieval from USC.gov

**Current Data**: 6,651 sections from Title 42

### Phase 2: Legislative History Linkage 🔄 IN PROGRESS

- [x] Congress.gov API integration
- [x] Link Public Laws → USC sections (AMENDS/ENACTS edges)
- [x] 362 Public Laws from 117th Congress
- [x] 580 edges connecting laws to sections
- [ ] Committee reports ingestion
- [ ] Congressional Record excerpts
- [ ] SPONSORED edges (members → bills)
- [ ] Older Congresses (116th, 115th, etc.)

**Milestone**: Can trace from a USC section back to its original bill ✅

### Phase 3: Regulatory Layer ⏳ NOT STARTED

- [ ] Federal Register API integration
- [ ] GovInfo CFR bulk download
- [ ] Extract authority citations (CFR → USC)
- [ ] Regulations.gov API for public comments
- [ ] Add IMPLEMENTS, COMMENTED_ON edges

**Milestone**: Can see regulatory implementation of any statute

### Phase 4: Judicial Layer ⏳ NOT STARTED

- [ ] CourtListener API integration
- [ ] Citation extraction from opinions
- [ ] Add INTERPRETS, CITES edges
- [ ] Case metadata (court, date, outcome)

**Milestone**: Can see how courts have interpreted any section

### Phase 5: Influence Layer ⏳ NOT STARTED

- [ ] OpenSecrets bulk data ingestion
- [ ] Link lobbying records to bills
- [ ] CRS reports ingestion + linking
- [ ] GAO reports ingestion + linking
- [ ] CBO estimates linking

**Milestone**: Can see lobbying activity, policy analysis around any provision

### Phase 6: Narrative & UI 🔄 IN PROGRESS

- [x] LLM narrative generation
- [x] Executive summary generation
- [x] Navigation pathways
- [x] Section context/explanation with hedging
- [x] Interactive UI (Tailwind + vanilla JS)
- [x] Topic classification (11 categories)
- [x] Search functionality
- [x] "AI-generated" content labeling
- [x] Source links (USC.gov)
- [ ] Timeline visualization (basic exists, needs work)
- [ ] Amendment diff viewer
- [ ] Dollar amounts on provisions
- [ ] Export/sharing functionality

**Production URL**: https://legislative-intelligence-production.up.railway.app/ui

---

## Current State: CHIPS Act POC

The system demonstrates capabilities on the **CHIPS and Science Act (Pub. L. 117-167)**:

| Metric | Value |
|--------|-------|
| New USC sections created | 144 |
| Existing sections amended | 51 |
| Topic categories | 11 (0 in "Other") |
| Total sections browsable | 195 |

### What's Working Well

1. **Topic-based navigation** - Browse by Workforce/Education, NSF/Research, DOE/Energy, etc.
2. **Search** - Find sections by name or citation
3. **AI summaries** - Plain English explanations with proper epistemic hedging
4. **Source links** - "View on USC.gov" for primary text
5. **Trust signals** - Clear "AI-generated" labels distinguish synthesis from source

### Known Gaps (from Expert Council)

1. **No full-text search** - Only searches names, not content
2. **Key Provisions not clickable to specific sections** - Links to topics, not sections
3. **No dollar amounts** - Provision summaries lack budget figures
4. **Timeline not interactive** - Exists but not useful
5. **No export/sharing** - Can't save or share views

---

## Technical Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                            │
├─────────────┬─────────────┬─────────────┬─────────────┬────────┤
│  USC.gov    │ Congress.gov│ Fed Register│ Regulations │ Courts │
│  (XML)      │    (API)    │    (API)    │    (API)    │  (API) │
└──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┴───┬────┘
       │             │             │             │           │
       ▼             ▼             ▼             ▼           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      INGESTION LAYER                            │
│  Citation Parser │ USLM Parser │ API Adapters │ Graph Builder  │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                       NEO4J GRAPH                               │
│                                                                 │
│  USCSection ──AMENDS──▶ PublicLaw ──ENACTS──▶ USCSection      │
│       │                     │                                   │
│       │                     └──SPONSORED──▶ Entity (Members)   │
│       │                                                         │
│       ├──IMPLEMENTS──▶ CFRSection (future)                     │
│       └──INTERPRETS──▶ Case (future)                           │
│                                                                 │
│  Current: 6,651 sections, 362 PLs, 580 edges                   │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER                           │
│                                                                 │
│  FastAPI ──▶ Narrative Generator ──▶ Claude API                │
│     │                                                           │
│     └──▶ Section Text Service ──▶ USC.gov (on-demand)          │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                         UI LAYER                                │
│                                                                 │
│  Jinja2 + Tailwind + Vanilla JS                                │
│  - Executive Summary      - Topic Browse                        │
│  - Navigation Pathways    - Section Detail Modal               │
│  - Search                 - AI Content Labels                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Caching Strategy

| Cache Type | Location | TTL | Purpose |
|------------|----------|-----|---------|
| Section text | `data/cache/section_text/` | Permanent | Avoid repeated USC.gov requests |
| LLM narratives | `data/cache/*.json` | 24 hours | Avoid repeated Claude calls |
| Graph queries | None (fast) | N/A | Neo4j Aura handles this |

Regenerate LLM cache: Add `?regenerate=true` to any `/narrative/*` endpoint

---

## SeedAI-Specific Applications

Given focus on science policy and AI governance:

1. **RFI Response Analyzer** - For OSTP, NIST AI frameworks, NAIRR comments
   - Who submits? What arguments recur? What influenced outcomes?

2. **Science Funding Tracker** - Appropriations bills → agency budgets → program outcomes
   - Connects CHIPS R&D authorizations to actual appropriations

3. **AI Regulatory Map** - Federal AI guidance → statutory authority → pending legislation
   - Useful for tracking AI governance landscape

---

## Recommended Next Steps

### Immediate (Current POC Polish)

1. **Amendment timelines** - Make the timeline section interactive and useful
2. **Dollar amounts** - Add budget figures to Key Provisions
3. **Provision → Section mapping** - Make Key Provisions link to specific USC sections

### Near-term (Phase 2 Completion)

4. **Older Congresses** - Load 116th, 115th for more legislative history coverage
5. **Committee reports** - Add to the legislative genealogy
6. **Member sponsorship** - SPONSORED edges to complete the picture

### Medium-term (Phase 3 Start)

7. **Federal Register integration** - Proposed/final rules
8. **CFR integration** - Show implementing regulations
9. **Regulations.gov comments** - For RFI analysis use case

---

## Technical Considerations

### Neo4j Aura Free Tier Limits
- 200K nodes (using ~7,500)
- 400K relationships (using ~600)
- Plenty of room for Phases 3-5

### API Rate Limits
- Congress.gov: 5,000 req/hour
- Federal Register: No formal limit
- Regulations.gov: Requires API key
- CourtListener: 5,000 req/day

### Why Text Isn't in Neo4j
Section text was intentionally excluded from Aura migration to stay under storage limits. The `section_text.py` service fetches from USC.gov on demand and caches locally. This works well but means:
- No full-text search in the graph
- First request for a section is slower (fetches text)
- Cached text persists until manually cleared

---

## Original Tier 1 Project Ideas (From Brainstorm)

1. **"The Story of a Law"** ← THIS IS WHAT WE'RE BUILDING
2. **Regulatory Comment Pattern Analyzer** - Useful for SeedAI's AI policy work
3. **"What Changed?" - Code Delta Tracker** - Amendment alerts and diffs

All three are achievable with the current architecture by completing the roadmap.

---

*Last updated: 2026-01-22*
