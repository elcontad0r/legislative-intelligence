# Paste this into a new Claude Code session

---

I'm continuing work on the **Legislative Intelligence System** - a POC that traces the "Story of a Law" for the CHIPS and Science Act.

**Production**: https://legislative-intelligence-production.up.railway.app/ui

## What's Done

Last session completed the council's top 3 priorities:
1. **Dollar amounts on Key Provisions** - Executive summary now shows "$52.7B for semiconductors", etc.
2. **Sparkline amendment indicators** - Sections show "New" badge or Nx sparkline bars
3. **Modal to slide-out panel** - Section details now in right-side panel
4. **Topic classification fixed** - Reduced "Other" from 49 to 0 sections

## What's Next (Council Priority Order)

1. **Make Key Provisions clickable** - Link provisions to specific USC sections, not just topics
2. **Interactive timeline** - The timeline exists but isn't useful
3. **Full-text search** - Currently only searches section names

## Key Files

- `src/narrative/generator.py` - CHIPS_FUNDING data, TOPIC_KEYWORDS for classification
- `src/analysis/bill_narrator.py` - LLM narrative generation
- `src/api/narrative_endpoints.py` - API endpoints
- `src/web/templates/index.html` - UI (Tailwind + vanilla JS)

## Technical Context

- Neo4j Aura (cloud) - doesn't store section text
- Section text fetched on-demand from USC.gov and cached
- Pushes to `main` auto-deploy to Railway (~90 sec)
- Add `?regenerate=true` to refresh LLM cache

## Start Here

Read `docs/handoff-2026-01-22-v2.md` for full context, then `docs/ROADMAP.md` for the vision.

---
