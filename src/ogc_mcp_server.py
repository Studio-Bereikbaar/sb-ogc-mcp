"""
Studio Bereikbaar OGC API — MCP Server
Gives Claude access to Dutch mobility data: boundaries, NRM networks,
ODIN travel survey analysis, accessibility maps, and more.
"""

from mcp.server.fastmcp import FastMCP
import httpx
import json
from typing import Optional

OGC_BASE = "https://tools.studiobereikbaar.nl/oapi"
TIMEOUT = 60.0

mcp = FastMCP("sb-ogc-api")


async def _get(path: str, params: Optional[dict] = None) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{OGC_BASE}{path}", params={**(params or {}), "f": "json"})
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            f"{OGC_BASE}{path}",
            json=body,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()


# ── Discovery ────────────────────────────────────────────────────────────

@mcp.tool()
async def list_collections() -> str:
    """List all available data collections (boundaries, NRM networks, demographics, analysis grids).
    Returns collection ID, title, and description for each."""
    data = await _get("/collections")
    lines = []
    for c in data.get("collections", []):
        desc = c.get("description", "")[:80]
        lines.append(f"- **{c['id']}**: {c.get('title', '')} — {desc}")
    return "\n".join(lines) or "No collections found."


@mcp.tool()
async def describe_collection(collection_id: str) -> str:
    """Get detailed metadata for a collection: description, extent, properties, links.
    Use this before querying to understand available attributes."""
    data = await _get(f"/collections/{collection_id}")
    queryables = await _get(f"/collections/{collection_id}/queryables")
    props = queryables.get("properties", {})
    prop_list = ", ".join(f"{k} ({v.get('type', '?')})" for k, v in list(props.items())[:20])
    return json.dumps({
        "id": data.get("id"),
        "title": data.get("title"),
        "description": data.get("description"),
        "itemType": data.get("itemType"),
        "extent": data.get("extent"),
        "properties": prop_list,
        "property_count": len(props),
    }, indent=2)


@mcp.tool()
async def list_processes() -> str:
    """List all available OGC API Processes (ODIN analysis, modal split, accessibility maps, spider diagrams)."""
    data = await _get("/processes")
    lines = []
    for p in data.get("processes", []):
        desc = p.get("description", "")[:100]
        lines.append(f"- **{p['id']}**: {p.get('title', '')} — {desc}")
    return "\n".join(lines) or "No processes found."


@mcp.tool()
async def describe_process(process_id: str) -> str:
    """Get detailed description of an OGC Process: required inputs, output format, execution mode."""
    data = await _get(f"/processes/{process_id}")
    return json.dumps({
        "id": data.get("id"),
        "title": data.get("title"),
        "description": data.get("description"),
        "inputs": data.get("inputs", {}),
        "outputs": data.get("outputs", {}),
    }, indent=2, default=str)


# ── Data Retrieval ───────────────────────────────────────────────────────

@mcp.tool()
async def get_features(
    collection_id: str,
    limit: int = 10,
    bbox: Optional[str] = None,
    properties: Optional[str] = None,
    filter_param: Optional[str] = None,
) -> str:
    """Fetch features from a collection. Returns GeoJSON.

    Args:
        collection_id: e.g. 'boundaries-gemeente', 'boundaries-pc4', 'bop-facilities'
        limit: max features to return (1-100)
        bbox: bounding box as 'minx,miny,maxx,maxy' (WGS84)
        properties: comma-separated property names to include
        filter_param: property filter e.g. 'statnaam=Amsterdam'
    """
    params = {"limit": min(limit, 100)}
    if bbox:
        params["bbox"] = bbox
    if properties:
        params["properties"] = properties
    if filter_param:
        key, val = filter_param.split("=", 1)
        params[key] = val

    data = await _get(f"/collections/{collection_id}/items", params)
    features = data.get("features", [])
    matched = data.get("numberMatched", "?")
    returned = data.get("numberReturned", len(features))

    summary = f"Returned {returned} of {matched} features from {collection_id}.\n\n"
    for f in features[:5]:
        props = f.get("properties", {})
        geom_type = f.get("geometry", {}).get("type", "?")
        summary += f"- [{geom_type}] {json.dumps({k: v for k, v in list(props.items())[:8]})}\n"
    if len(features) > 5:
        summary += f"\n... and {len(features) - 5} more features."
    return summary


@mcp.tool()
async def search_boundaries(
    name: str,
    level: str = "gemeente",
) -> str:
    """Search for a municipality, district, neighbourhood, or postal code by name.

    Args:
        name: search term (e.g. 'Amsterdam', 'Centrum', '1012')
        level: 'gemeente', 'wijk', 'buurt', 'pc4', or 'provincie'
    """
    collection = f"boundaries-{level}"
    # Determine the name field per collection
    name_field = {
        "gemeente": "statnaam",
        "wijk": "wijknaam",
        "buurt": "buurtnaam",
        "pc4": "postcode",
        "provincie": "statnaam",
    }.get(level, "statnaam")

    params = {"limit": 20}
    params[name_field] = name

    try:
        data = await _get(f"/collections/{collection}/items", params)
    except httpx.HTTPStatusError:
        # Try without exact filter for partial match
        data = await _get(f"/collections/{collection}/items", {"limit": 50})
        features = [
            f for f in data.get("features", [])
            if name.lower() in str(f.get("properties", {}).get(name_field, "")).lower()
        ]
        data["features"] = features

    features = data.get("features", [])
    if not features:
        return f"No {level} found matching '{name}'."

    lines = [f"Found {len(features)} {level} matching '{name}':"]
    for f in features[:10]:
        p = f.get("properties", {})
        lines.append(f"- {p.get(name_field, '?')} (code: {p.get('statcode', p.get('postcode', '?'))})")
    return "\n".join(lines)


# ── OGC Processes (Analysis) ─────────────────────────────────────────────

@mcp.tool()
async def run_odin_query(
    zone_type: str,
    zone_code: str,
    direction: str = "herkomst",
) -> str:
    """Run ODIN travel survey analysis for a location.
    Returns modal split, trip purposes, distance distribution, and trends.

    Args:
        zone_type: 'gemeente', 'wijk', 'buurt', 'pc4', or 'provincie'
        zone_code: CBS code (e.g. 'GM0363' for Amsterdam) or postcode (e.g. '1012')
        direction: 'herkomst' (origin) or 'bestemming' (destination)
    """
    body = {
        "inputs": {
            "zone_type": zone_type,
            "zone_code": zone_code,
            "direction": direction,
        }
    }
    data = await _post("/processes/odin-query/execution", body)
    return json.dumps(data, indent=2, default=str)[:4000]


@mcp.tool()
async def run_odin_compare(
    zone_type: str,
    zone_code_a: str,
    zone_code_b: str,
) -> str:
    """Compare ODIN travel survey data between two locations side-by-side.

    Args:
        zone_type: 'gemeente', 'wijk', 'pc4', or 'provincie'
        zone_code_a: first location code (e.g. 'GM0363')
        zone_code_b: second location code (e.g. 'GM0599')
    """
    body = {
        "inputs": {
            "zone_type": zone_type,
            "zone_code_a": zone_code_a,
            "zone_code_b": zone_code_b,
        }
    }
    data = await _post("/processes/odin-compare/execution", body)
    return json.dumps(data, indent=2, default=str)[:4000]


@mcp.tool()
async def run_modal_split(
    zone_type: str,
    zone_code: str,
) -> str:
    """Generate modal split analysis (Marimekko chart data) for a location.

    Args:
        zone_type: 'gemeente', 'wijk', 'pc4', or 'provincie'
        zone_code: CBS code (e.g. 'GM0363')
    """
    body = {
        "inputs": {
            "zone_type": zone_type,
            "zone_code": zone_code,
        }
    }
    data = await _post("/processes/modal-split-analysis/execution", body)
    return json.dumps(data, indent=2, default=str)[:4000]


@mcp.tool()
async def run_odin_spider(
    zone_type: str,
    zone_code: str,
    direction: str = "herkomst",
) -> str:
    """Generate origin-destination desire lines (spider diagram) for a location.
    Returns GeoJSON with arc geometries showing trip flows.

    Args:
        zone_type: 'gemeente', 'wijk', 'pc4'
        zone_code: CBS code
        direction: 'herkomst' (where do people come from) or 'bestemming' (where do they go)
    """
    body = {
        "inputs": {
            "zone_type": zone_type,
            "zone_code": zone_code,
            "direction": direction,
        }
    }
    data = await _post("/processes/odin-spider/execution", body)
    features = data.get("features", [])
    return f"Spider diagram: {len(features)} desire lines generated.\n\n" + json.dumps(data, indent=2, default=str)[:4000]


@mcp.tool()
async def run_accessibility_map(
    zone_type: str,
    zone_code: str,
) -> str:
    """Generate BOP accessibility map for a location.
    Returns base64-encoded PNG image of accessibility scores.

    Args:
        zone_type: 'gemeente' or 'provincie'
        zone_code: CBS code (e.g. 'GM0363')
    """
    body = {
        "inputs": {
            "zone_type": zone_type,
            "zone_code": zone_code,
        }
    }
    data = await _post("/processes/accessibility-map/execution", body)
    return json.dumps(data, indent=2, default=str)[:4000]


def main():
    mcp.run()


if __name__ == "__main__":
    main()
