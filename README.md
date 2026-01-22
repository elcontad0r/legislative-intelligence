# Legislative Intelligence System

A proof-of-concept system that traces the story of American laws through their legislative history. Currently focused on the **CHIPS and Science Act** (Pub. L. 117-167).

Built by [SeedAI](https://seedai.org).

## What It Does

- **Parses USC XML** to extract sections, amendments, and source credits
- **Builds a graph database** linking laws, amendments, and citations
- **Generates LLM-powered narratives** that explain legislation in plain English
- **Provides "Start Here" navigation** based on user interests

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   USC XML Data  │────▶│   Neo4j Graph   │────▶│   FastAPI API   │
│  (source_credit │     │  USCSection     │     │  /narrative/*   │
│   parsing)      │     │  PublicLaw      │     │  /chips         │
└─────────────────┘     │  AMENDS/ENACTS  │     └────────┬────────┘
                        └─────────────────┘              │
                                                         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Anthropic API  │◀────│  Bill Narrator  │◀────│   Web UI        │
│  (Claude)       │     │  LLM summaries  │     │  Tailwind CSS   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Data Trustworthiness Tiers

1. **Tier 1 (Definitive)**: Source credits from USC XML - authoritative legislative history
2. **Tier 2 (High)**: Public Law titles from Congress.gov API
3. **Tier 3 (Medium)**: Text diff analysis between law versions
4. **Tier 4 (Low)**: LLM-generated summaries and narratives (hedged appropriately)
5. **Tier 5 (Speculative)**: External sources like CRS reports

## Local Development

### Prerequisites

- Python 3.9+
- Neo4j (local or Aura)
- Anthropic API key

### Setup

```bash
# Clone the repo
git clone https://github.com/seedai/legislative-intelligence.git
cd legislative-intelligence

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env with your credentials

# Start Neo4j (if running locally)
neo4j console

# Run the API server
uvicorn src.api.main:app --reload --port 8080

# Open http://localhost:8080/ui
```

## Deployment

### Neo4j Aura (Free Tier)

1. Go to [Neo4j Aura](https://neo4j.com/cloud/aura-free/)
2. Create a free instance (200k nodes free forever)
3. Save the connection URI and password
4. Export local data:
   ```bash
   python scripts/export_for_aura.py > data/aura_import.cypher
   ```
5. In Aura's Neo4j Browser, run the generated Cypher

### Railway

1. Connect your GitHub repo to [Railway](https://railway.app)
2. Add environment variables:
   - `NEO4J_URI` - your Aura connection string
   - `NEO4J_USER` - neo4j
   - `NEO4J_PASSWORD`
   - `ANTHROPIC_API_KEY`
3. Deploy - Railway auto-detects Python

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `NEO4J_URI` | Neo4j connection | `neo4j+s://xxxx.databases.neo4j.io` |
| `NEO4J_USER` | Username | `neo4j` |
| `NEO4J_PASSWORD` | Password | `your-password` |
| `ANTHROPIC_API_KEY` | Anthropic key | `sk-ant-...` |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /ui` | Web UI |
| `GET /narrative/chips/full` | Full CHIPS narrative |
| `GET /narrative/chips/executive-summary` | Executive summary |
| `GET /narrative/chips/navigation` | Navigation pathways |
| `GET /narrative/section/{citation}` | Section context |
| `GET /chips` | Raw CHIPS data |
| `GET /stats` | Database statistics |

## License

MIT
