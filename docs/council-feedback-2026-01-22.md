# Legislative Intelligence System - Product Feedback Council

**Date:** January 22, 2026
**Product:** https://legislative-intelligence-production.up.railway.app/ui

---

## The Council

| Expert | Role | Primary Concerns |
|--------|------|------------------|
| **Sarah** | Senior Legislative Staffer (Senate Commerce) | Accuracy, verification, legislative history |
| **Marcus** | Federal Lobbyist (Tech coalition) | Speed, relevance filtering, client briefings |
| **Dr. Chen** | Think Tank Policy Researcher | Citations, methodology, traceable claims |
| **Jamie** | Engaged Citizen / Journalist | Accessibility, plain English, not getting lost |
| **Patricia** | CRS Analyst | Precision, proper hedging, no hallucinations |
| **Devon** | Product Designer / UX Expert | User flows, information hierarchy, actionability |

---

## ROUND 1: FIRST IMPRESSIONS

### SARAH (Senior Legislative Staffer, Senate Commerce Committee)

First thing I notice: the headline summary is punchy and gets the scope right - $280B, semiconductors, competitiveness against China. That's the elevator pitch I'd give my boss.

**What works:** The "Most Legislative History" section is actually interesting. Seeing that 42 USC 1396a has been amended 91 times tells me something about where the legislative action has been concentrated. That's useful signal.

**What's confusing:** Why is Medicaid (1396a, 1396d) showing up as the most amended sections in a CHIPS and Science Act tool? Either your data is pulling in amendments from unrelated laws, or there's something I'm not understanding about the data model. If I showed this to my Legislative Director, they'd immediately ask "why is Medicaid in my semiconductor bill analysis?"

**Bigger concern:** I clicked into 42 USC 1396a and got an AI-generated explanation of Medicaid. But where's the actual legislative history? Which public laws amended it? What were the changes? A count of "91x amended" is useless without the receipts. I need to verify everything - I can't cite an AI summary in a memo to the Senator.

---

### MARCUS (Federal Lobbyist, Tech Coalition)

**Immediate reaction:** The hero section is solid for a quick client brief. "Congress authorizes $280 billion" - that's the headline my principals want.

**What works:** The Key Provisions breakdown is exactly what I need for a 5-minute exec briefing. Semiconductor incentives, China guardrails, regional hubs - that's the structure of the conversation we're having with clients.

**What's missing:** I don't see dollar amounts attached to each provision. The $39B for manufacturing incentives is mentioned, but I need to quickly say "Regional Tech Hubs: $10B" or whatever the number is. Executives think in dollars.

**Critical gap:** There's no search. If Intel calls me and says "what does CHIPS say about legacy chips?" I need to search for "legacy" and find relevant provisions. Right now I'd have to manually scan 195 sections under "Other." That's a non-starter.

**The "Start Here" tease:** You show one pathway for semiconductors, but the Key Provisions list shows NSF, workforce, supply chain. Where are those pathways? This feels half-built.

---

### DR. CHEN (Think Tank Policy Researcher)

**First impression:** The "Interesting Thread" section immediately concerned me. It claims that including Medicaid amendments in the CHIPS Act "suggests something remarkable: the government is treating healthcare data infrastructure and medical technology advancement as inseparable from semiconductor and computing policy."

That's a bold analytical claim that I suspect is hallucinated. The CHIPS Act is an omnibus - Medicaid provisions could be in there for completely unrelated legislative vehicle reasons. Making this kind of causal inference without evidence is exactly the kind of thing that would get a research paper rejected.

**What works:** The concept of showing legislative history depth (91x amended) is genuinely interesting for research. Amendment frequency is an underexplored signal.

**What's broken:** I cannot trace any claim to a source. The "Historical Context" section makes statements about "bipartisan recognition" and "decades of globalization" - where is this coming from? Is this from committee reports? Floor statements? CRS? Or is the LLM just generating plausible-sounding context?

**For my work to be usable:** I need citation trails. Every factual claim needs a source. The LLM can synthesize, but I need to verify against primary documents.

---

### JAMIE (Engaged Citizen / Journalist)

**Honest first reaction:** This is way better than Congress.gov. The plain English summary actually tells me what the bill does without making me feel stupid.

**What works:** "Congress authorizes $280 billion in federal funding to boost U.S. semiconductor manufacturing and research competitiveness against China" - I can put that in a story. The Key Provisions give me angles: China guardrails (conflict angle), regional hubs (local impact angle), workforce (jobs angle).

**What's confusing:** I clicked on "42 USC 18901" and got a modal that says "Section Name: Unknown" with empty explanations. That's a dead end. If most sections show "Unknown," I'm going to bounce.

**Lost immediately:** "Browse by Topic" shows "Other - 195 sections." That's not browsing by topic, that's just a list. I have no idea which sections are about semiconductors vs. NSF vs. workforce. The promise of the interface doesn't match reality.

**What would help:** If you're going to generate plain-English summaries, generate them for ALL sections, not just the ones with rich amendment history. The new sections created by CHIPS are probably the most interesting to readers, but they're the ones with no content.

---

### PATRICIA (CRS Analyst)

**Professional assessment:** The product is making analytical claims it cannot support.

**Specific problem:** The "Interesting Thread" section states that Medicaid's inclusion in CHIPS "suggests something remarkable" about policy integration. This is not hedged appropriately. A proper CRS-style statement would be: "The CHIPS and Science Act includes provisions affecting multiple policy areas, including healthcare programs. The relationship between these provisions and the Act's primary semiconductor focus warrants further examination."

**Data quality concern:** Showing "Section Name: Unknown" undermines trust immediately. If you can't reliably pull the section heading from USC XML, why should I trust your LLM-generated analysis?

**What's actually useful:** The structural data - 144 sections created, 51 amended - is verifiable and useful. The graph database concept (AMENDS/ENACTS relationships) is sound methodology. But the presentation is mixing verified structural data with unverified AI analysis without distinguishing between them.

**My recommendation:** Clearly label what is source data vs. AI-generated analysis. Use appropriate epistemic hedging. Don't make causal claims without evidence.

---

### DEVON (Product Designer / UX Expert)

**Information hierarchy problem:** The page tries to do too much. You've got a hero summary, stats, pathways, overview, provisions, why it matters, context, interesting thread, topics, most amended, new sections - all on one scrolling page. There's no clear user journey.

**First-time vs. power user:** A first-time user (Jamie) needs the plain English summary and guided pathways. A power user (Sarah, Patricia) needs search, filtering, and source links. Right now you're giving everyone the same interface, which means it's mediocre for both.

**The "Start Here" UX is broken:** You promise "Jump in based on your interests" but only show ONE pathway. The Key Provisions list shows 7 different themes. Why aren't those pathways? The affordance promises more than it delivers.

**Modal detail view:** When I click a section, I get a modal with "Unknown" name and thin AI content. This should be a full page with:
- Actual section text (or link to it)
- Amendment history timeline
- Related sections (from your graph)
- Source links (USC, Congress.gov)

**Call to action:** What do you want users to DO? Explore? Search? Understand? The page doesn't have a clear goal state.

---

## ROUND 2: USE CASES & GAPS

### SARAH (Senior Legislative Staffer)

**My task:** My boss is prepping for a hearing on CHIPS implementation. I need to find all provisions related to "guardrails" on China and understand what enforcement mechanisms exist.

**What I'd do:** Look for search... none. Scan the page for "guardrails"... I see it in Key Provisions: "Prohibits companies receiving federal semiconductor funding from materially expanding semiconductor manufacturing capacity in China."

**Where it helps:** That summary is accurate and useful. I know this is roughly Section 103 territory.

**Where it fails:**
1. No search means I'm manually scanning
2. I can't click "China Guardrails" to see the actual statutory text
3. No link to the enforcement provisions or implementing regulations
4. No connection to Commerce Department guidance on what "materially expanding" means

**What I actually need:** Link me to the USC section. Show me the statutory text. Show me what regulations have been issued. Show me floor debate on this provision. The AI summary is nice, but I need primary sources for my memo.

---

### MARCUS (Federal Lobbyist)

**My task:** Qualcomm wants to know if their existing R&D partnerships in Singapore would be affected by CHIPS guardrails. I need to find relevant provisions fast.

**What I'd do:** Search for "foreign" or "allied" or "partnerships"... no search. Browse by topic for "international"... it's all "Other." Check Key Provisions... "International Partnerships" is listed but I can't click into it.

**Where it helps:** The Key Provisions mention "coordinate semiconductor research and supply chain resilience with allied nations" - that suggests Singapore partnerships might be okay.

**Where it fails:**
1. Can't search for specific terms
2. Can't see which USC sections implement "International Partnerships"
3. No way to distinguish between prohibited China activities and permitted allied-nation activities
4. Can't export or share a specific provision with the client

**What I actually need:** A way to search, filter to relevant sections, see the statutory language, and generate a shareable link or PDF for client communication.

---

### DR. CHEN (Think Tank Policy Researcher)

**My task:** I'm writing a paper on how semiconductor policy has evolved from the 1980s SEMATECH era to CHIPS. I want to understand the legislative lineage.

**What I'd do:** Look for historical amendment data... "Most Legislative History" shows Medicaid sections, which isn't helpful. Check "Historical Context"... it's a generic LLM narrative about globalization.

**Where it helps:** The concept of tracing legislative history through amendment relationships is exactly what I need.

**Where it fails:**
1. The "Most Legislative History" seems to show ALL amendments to that USC section, not just CHIPS-related
2. No timeline visualization of when amendments occurred
3. No connection to predecessor legislation (USICA, Endless Frontier Act, etc.)
4. The "Interesting Thread" makes analytical claims I can't verify and wouldn't cite

**What I actually need:**
- A timeline of amendments to key sections
- Links to the public laws that made those amendments
- Ability to compare statutory text before/after amendments
- Connections to related legislation in the same policy area

---

### JAMIE (Engaged Citizen / Journalist)

**My task:** I'm writing a story about whether CHIPS money is actually going to create jobs in Ohio. I need to understand the workforce provisions.

**What I'd do:** Look for "workforce" or "jobs"... Key Provisions mentions "STEM Workforce Development" with scholarships and training programs.

**Where it helps:** I now know workforce is part of the bill and it's about scholarships/fellowships.

**Where it fails:**
1. I can't click into workforce provisions to learn more
2. No information about how much money is allocated to workforce
3. No information about which agencies implement this
4. No way to find Ohio-specific or regional provisions
5. "Browse by Topic" doesn't have a workforce category - just "Other"

**What I actually need:** A way to click "Workforce" and see all relevant sections with plain-English explanations, dollar amounts, and implementing agencies. Bonus: local angle - which regional tech hubs might affect Ohio?

---

### PATRICIA (CRS Analyst)

**My task:** A Member asked me to verify a claim that CHIPS includes $10 billion for the NSF. I need to find the exact authorization language.

**What I'd do:** Key Provisions says "Increases NSF funding authorization to $15 billion annually by 2027" - that's not $10B, so either the Member's claim is wrong or there's a specific $10B figure somewhere.

**Where it helps:** The Key Provisions give me a starting point - NSF authorization increases.

**Where it fails:**
1. Can't see the actual statutory text with authorization levels
2. "$15 billion annually by 2027" - is that a glide path? What's the year-by-year breakdown?
3. The AI might be summarizing inaccurately - I need to verify against USC text
4. No link to the appropriations that actually fund these authorizations

**What I actually need:** Direct links to statutory text. For budget-related provisions, I need the exact authorization language with fiscal years and amounts. AI summaries are not acceptable for budget verification.

---

### DEVON (Product Designer / UX Expert)

**My task:** Evaluate the user flow for someone who lands on this page from a Google search for "CHIPS Act semiconductor subsidies."

**User journey mapping:**
1. Land on page - see hero summary about $280B. Good hook.
2. Scan stats - 144 sections created, 51 amended. Mildly interesting.
3. See "Start Here" - only one pathway. Disappointing.
4. Scroll to Key Provisions - good scannable list. But can't click items.
5. See "Interesting Thread" - curious but skeptical.
6. Browse by Topic - "Other: 195 sections" - useless.
7. Click a section - get modal with "Unknown" and thin content.
8. Dead end. Bounce.

**Where the flow breaks:**
- No search is fatal for intent-driven visitors
- Non-clickable Key Provisions create frustration
- "Browse by Topic" doesn't deliver on its promise
- Section modals are dead ends, not gateways

**What the flow should be:**
1. Land - immediate value (hero summary)
2. Orient - multiple clear pathways based on interest
3. Drill down - click a pathway, see relevant sections with summaries
4. Deep dive - click a section, see full detail WITH source links
5. Branch out - discover related sections through the graph
6. Export/Share - save or send what you found

---

## ROUND 3: PRIORITY IMPROVEMENTS

### SARAH (Senior Legislative Staffer)

**My ONE thing:** **Add links to primary sources.**

Every section should link directly to the USC text on uscode.house.gov and to the Public Law on Congress.gov. Every claim in the AI summary should be traceable to statutory language. I don't care how pretty your summaries are - if I can't verify them against source text, this tool is useless for professional legislative work.

**Would I use this?** Not yet. Maybe for initial orientation on a new issue. But it would never replace my need to read actual statutory text. If you added source links and search, I'd use it as a starting point.

---

### MARCUS (Federal Lobbyist)

**My ONE thing:** **Add search.**

Full stop. Without search, I cannot use this tool for client work. When a client calls with a question about "legacy chips" or "packaging" or "fabless design," I need to immediately find relevant provisions. I don't have time to scroll through 195 sections labeled "Other."

**Would I use this?** The Key Provisions summary is genuinely useful for exec briefings. If you added search and made provisions clickable with dollar amounts, this would save me 30 minutes on every new client conversation.

---

### DR. CHEN (Think Tank Policy Researcher)

**My ONE thing:** **Fix the "Interesting Thread" and add proper hedging.**

The current analytical claims are a credibility killer. Either remove speculative analysis entirely, or add clear epistemic markers ("This may suggest..." "One possible interpretation..." "Further research needed to confirm..."). Better yet, show me the evidence and let me draw my own conclusions.

**Would I use this?** The legislative history depth concept is interesting for research. If you added source links, amendment timelines, and removed the hallucinated analysis, I'd use it for exploratory research. I'd still verify everything against primary sources.

---

### JAMIE (Engaged Citizen / Journalist)

**My ONE thing:** **Make Key Provisions clickable and populate all section summaries.**

The Key Provisions list is exactly what I need - it's organized by topic and written in plain English. But I can't go deeper. Let me click "Regional Technology Hubs" and see which sections implement it, with plain-English explanations for each. And fix the "Unknown" section names - that kills trust immediately.

**Would I use this?** I already like it more than Congress.gov. If Key Provisions were clickable gateways and sections had actual summaries, I'd use this every time I need to understand what a bill does.

---

### PATRICIA (CRS Analyst)

**My ONE thing:** **Clearly separate source data from AI-generated content.**

Use visual distinctions - maybe a different background color or an "AI-generated" label - so users know what's verified data (USC citation, amendment count, enactment date) vs. what's synthesized by the model (summaries, "why it matters," "interesting thread"). Professionals need to know what they can cite.

**Would I use this?** For quick orientation only. The structural data (sections created, amendment relationships) is useful. But I'd never cite AI-generated content without verification. If you clearly labeled what's verified vs. generated, I'd trust the tool more.

---

### DEVON (Product Designer / UX Expert)

**My ONE thing:** **Make the Key Provisions the primary navigation.**

You already have 7 well-organized topic areas in Key Provisions. Make each one a clickable card that expands to show relevant sections. This solves the "1 pathway vs. 7 topics" problem. This solves the "Other: 195 sections" problem. This gives users clear entry points based on their interests.

**Would I use this?** I'd recommend it to others as a better way to understand legislation than Congress.gov. But the current version has too many dead ends. Fix the navigation hierarchy and make every visible element clickable/actionable, and you have something genuinely useful.

---

## TOP 5 PRIORITIES (SYNTHESIZED)

### 1. ADD SEARCH FUNCTIONALITY
**Supported by:** Marcus (critical), Sarah (important), Dr. Chen (important), Jamie (would help)

Without search, power users cannot do their jobs. This is table stakes for any legislative research tool. Users need to search by keyword, USC citation, topic, or provision name.

**Specific implementation:** Full-text search across section text and summaries, with filters for section type (created vs. amended), topic area, and dollar amounts.

---

### 2. LINK TO PRIMARY SOURCES (USC, Congress.gov, Public Laws)
**Supported by:** Sarah (critical), Patricia (critical), Dr. Chen (important), Marcus (important)

Professional users need to verify every claim against statutory text. Every section should link to:
- USC text on uscode.house.gov
- The Public Law that created/amended it on Congress.gov
- Any implementing regulations or agency guidance

**Specific implementation:** Add source links to every section modal. For AI-generated summaries, add "View source" links to the specific provisions being summarized.

---

### 3. MAKE KEY PROVISIONS CLICKABLE NAVIGATION PATHWAYS
**Supported by:** Devon (primary recommendation), Jamie (critical), Marcus (important), Sarah (would help)

The 7 Key Provisions are already well-organized topic buckets. Convert them into clickable cards that expand to show relevant USC sections. This replaces the broken "Browse by Topic" (which only shows "Other") with meaningful topic navigation.

**Specific implementation:** Each Key Provision becomes a card with:
- Dollar amount (if applicable)
- Section count
- Click to expand and see list of relevant sections
- Each section links to detail view

---

### 4. CLEARLY DISTINGUISH SOURCE DATA FROM AI-GENERATED CONTENT
**Supported by:** Patricia (critical), Dr. Chen (critical), Sarah (important)

Professional users need to know what they can cite. Use visual markers (labels, colors, icons) to distinguish:
- **Verified data:** USC citation, enactment date, amendment count, public law number
- **AI-generated:** Plain English summaries, "Why It Matters," "Interesting Thread," "Historical Context"

**Specific implementation:** Add subtle "AI-generated" badges to synthesized content. Use different background colors for source data vs. analysis. Consider adding confidence indicators.

---

### 5. FIX THE DATA QUALITY ISSUES (Topic Classification, Section Names, Misleading Analysis)
**Supported by:** Patricia (data quality), Dr. Chen ("Interesting Thread"), Jamie ("Unknown" names), Devon (broken topic browse)

Multiple data quality issues undermine trust:
- "Section Name: Unknown" for most sections
- "Browse by Topic" shows only "Other" (topic classification broken)
- "Interesting Thread" makes unsupported causal claims about Medicaid/CHIPS
- 1 Topic Area shown in stats (should be 7+ based on Key Provisions)

**Specific implementation:**
- Pull section names from USC XML properly
- Implement real topic classification (use Key Provisions as taxonomy)
- Rewrite "Interesting Thread" with proper hedging or remove it
- Update stats to reflect actual topic breakdown

---

## ADDITIONAL RECOMMENDATIONS (Lower Priority)

6. **Add amendment timelines** - Show when sections were amended over time (Dr. Chen, Sarah)
7. **Add dollar amounts to all provisions** - Executives think in dollars (Marcus)
8. **Populate AI summaries for all sections** - New sections created by CHIPS have empty content (Jamie)
9. **Add export/share functionality** - Let users save or send specific provisions (Marcus, Jamie)
10. **Improve section modal depth** - Full page view with text, history, related sections, not just thin modal (Devon, Sarah)

---

## COUNCIL VERDICT

**Current state:** Promising concept with genuine value in the executive summary and Key Provisions structure. The LLM-generated content makes the bill accessible in a way Congress.gov doesn't. The graph database approach (tracking AMENDS/ENACTS relationships) is methodologically sound.

**Blocking issues:** No search, no source links, broken topic navigation, and mixing verified data with unhedged AI speculation. These issues make the tool unusable for professional legislative work and undermine trust for everyone.

**Path to product-market fit:** Fix the top 5 priorities. The core insight - making legislation understandable through AI synthesis while maintaining links to primary sources - is valuable. But the current implementation promises more than it delivers. Make Key Provisions the navigation backbone, add search, link to sources, and clearly label AI content. Then you have something professionals would actually use.
