# SB OGC MCP — Studio Bereikbaar Mobility Data for Claude

MCP server that gives Claude access to Dutch mobility data via Studio Bereikbaar's OGC API.

## What you get

13 tools for Claude Desktop:

| Tool | What it does |
|------|-------------|
| `list_collections` | List 15 data collections (boundaries, NRM networks, demographics) |
| `describe_collection` | Get schema/properties of a collection |
| `list_processes` | List 7 analysis processes |
| `get_features` | Fetch GeoJSON features with filters |
| `search_boundaries` | Find gemeente/wijk/buurt/pc4 by name |
| `run_odin_query` | ODIN travel survey analysis (20 years, modal split, trends) |
| `run_odin_compare` | Compare two locations side-by-side |
| `run_modal_split` | Generate modal split chart (returns PNG image) |
| `run_odin_spider` | Origin-destination desire lines (GeoJSON) |
| `run_odin_profile` | 7-cluster mobility profiling |
| `run_odin_spider_profile` | Demographics of travelers to/from a municipality |
| `run_accessibility_map` | BOP accessibility map (returns PNG image) |

## Setup voor collega's

### 1. Installeer uv (eenmalig)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Configureer Claude Desktop

Open `~/Library/Application Support/Claude/claude_desktop_config.json` en voeg toe:

```json
{
  "mcpServers": {
    "sb-ogc-api": {
      "command": "uvx",
      "args": ["sb-ogc-mcp"]
    }
  }
}
```

### 3. Herstart Claude Desktop

De tools verschijnen automatisch. Probeer:

> "Welke data collections heeft Studio Bereikbaar?"

> "Laat de modal split zien voor Amsterdam"

> "Vergelijk Rotterdam en Utrecht qua vervoerswijzen"

> "Toon de bereikbaarheidskaart voor fietsen naar supermarkten in Den Haag"

## Data

All data comes from `tools.studiobereikbaar.nl/oapi` (OGC API):
- **ODIN** — CBS travel survey, 20 years (2004–2023), ~3M trips, enriched by Roland Kager
- **NRM** — National traffic model networks (2022 + 4 future scenarios)
- **CBS boundaries** — gemeente, wijk, buurt, pc4, provincie
- **BOP** — accessibility maps (Move Mobility)
- **V500** — 500m population + urbanization grids
