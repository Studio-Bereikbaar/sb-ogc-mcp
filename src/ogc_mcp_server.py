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
    municipality: Optional[str] = None,
    postcode: Optional[str] = None,
    province: Optional[str] = None,
    location_type: str = "departure",
    transport_mode: Optional[str] = None,
    trip_purpose: Optional[str] = None,
    year_min: int = 2004,
    year_max: int = 2023,
    include_trends: bool = True,
) -> str:
    """Run ODIN travel survey analysis for a location.
    Returns modal split, trip purposes, distance distribution, and 20-year trends.
    Provide at least one of: municipality, postcode, or province.

    Args:
        municipality: Dutch municipality name (e.g. 'Amsterdam', 'Utrecht', "'s-Gravenhage")
        postcode: 4-digit postcode (e.g. '1012', '3013')
        province: Province code (e.g. 'NH', 'ZH', 'UT')
        location_type: 'departure' or 'arrival'
        transport_mode: filter by mode (e.g. 'Fiets', 'Auto-best', 'Trein', 'Lopen')
        trip_purpose: filter by purpose (e.g. 'Werken', 'Winkelen/boodschappen doen')
        year_min: start year (2004-2023)
        year_max: end year (2004-2023)
        include_trends: include yearly trend data
    """
    inputs = {"location_type": location_type, "year_min": year_min, "year_max": year_max, "include_trends": include_trends}
    if municipality: inputs["municipality"] = municipality
    if postcode: inputs["postcode"] = postcode
    if province: inputs["province"] = province
    if transport_mode: inputs["transport_mode"] = transport_mode
    if trip_purpose: inputs["trip_purpose"] = trip_purpose
    data = await _post("/processes/odin-query/execution", {"inputs": inputs})
    return json.dumps(data, indent=2, default=str)[:4000]


@mcp.tool()
async def run_odin_compare(
    location_a_municipality: Optional[str] = None,
    location_a_postcode: Optional[str] = None,
    location_b_municipality: Optional[str] = None,
    location_b_postcode: Optional[str] = None,
) -> str:
    """Compare ODIN travel survey data between two locations side-by-side.
    Provide municipality name or postcode for each location.

    Args:
        location_a_municipality: first location municipality (e.g. 'Amsterdam')
        location_a_postcode: first location postcode (e.g. '1012')
        location_b_municipality: second location municipality (e.g. 'Rotterdam')
        location_b_postcode: second location postcode (e.g. '3013')
    """
    inputs = {}
    if location_a_municipality: inputs["location_a_municipality"] = location_a_municipality
    if location_a_postcode: inputs["location_a_postcode"] = location_a_postcode
    if location_b_municipality: inputs["location_b_municipality"] = location_b_municipality
    if location_b_postcode: inputs["location_b_postcode"] = location_b_postcode
    data = await _post("/processes/odin-compare/execution", {"inputs": inputs})
    return json.dumps(data, indent=2, default=str)[:4000]


@mcp.tool()
async def run_modal_split(
    municipality: Optional[str] = None,
    postcode: Optional[str] = None,
    province: Optional[str] = None,
    year_min: int = 2004,
    year_max: int = 2023,
) -> str:
    """Generate modal split analysis (Marimekko chart) for a location.
    Returns base64-encoded PNG image. Provide municipality, postcode, or province.

    Args:
        municipality: Dutch municipality name (e.g. 'Amsterdam')
        postcode: 4-digit postcode (e.g. '1012')
        province: Province code (e.g. 'NH')
        year_min: start year (2004-2023)
        year_max: end year (2004-2023)
    """
    inputs = {"year_min": year_min, "year_max": year_max}
    if municipality: inputs["municipality"] = municipality
    if postcode: inputs["postcode"] = postcode
    if province: inputs["province"] = province
    data = await _post("/processes/modal-split-analysis/execution", {"inputs": inputs})
    return json.dumps(data, indent=2, default=str)[:4000]


@mcp.tool()
async def run_odin_spider(
    gemeente: str,
    mode: str = "AllModes",
    motive: str = "AllMotives",
    top_n: int = 15,
    include_internal: bool = False,
) -> str:
    """Generate origin-destination desire lines (spider diagram) for a municipality.
    Returns GeoJSON with arc geometries showing trip flows between municipalities.

    Args:
        gemeente: Municipality name (e.g. 'Rotterdam', 'Amsterdam', "'s-Gravenhage")
        mode: Transport mode filter: AllModes, Auto, OV, Btm, Trein, Fiets, Lopen, Overig
        motive: Trip purpose: AllMotives, ToWork, ToHome, Shopping, ToEducation, etc.
        top_n: Number of top connections to return (1-100)
        include_internal: Include trips within the same municipality
    """
    data = await _post("/processes/odin-spider/execution", {"inputs": {
        "gemeente": gemeente,
        "mode": mode,
        "motive": motive,
        "top_n": top_n,
        "include_internal": include_internal,
    }})
    features = data.get("features", [])
    return f"Spider diagram: {len(features)} desire lines.\n\n" + json.dumps(data, indent=2, default=str)[:4000]


@mcp.tool()
async def run_accessibility_map(
    mode: str,
    amenity: str,
    map_type: str = "traveltime",
    region_type: str = "national",
    region_id: Optional[str] = None,
) -> str:
    """Generate BOP accessibility map showing travel times to amenities.
    Returns base64-encoded PNG image.

    Args:
        mode: Transport mode — car_24h, car_freeflow_24h, cycle, walk, pt_walk, pt_cycle, pt_cycle_walk
        amenity: Amenity type — bo (primary school), vo (secondary), mbo, hbo, wo, eerstehulp, huisarts, supermarkt, jobs, basket
        map_type: Visualization — traveltime (travel time), geen_keuze (no choice), wel_keuze (with choice)
        region_type: Extent — national, province, municipality
        region_id: Province key (e.g. 'noord-holland') or GM code (e.g. 'GM0599'). Required when region_type is province or municipality.
    """
    inputs = {"mode": mode, "amenity": amenity, "map_type": map_type, "region_type": region_type}
    if region_id: inputs["region_id"] = region_id
    data = await _post("/processes/accessibility-map/execution", {"inputs": inputs})
    return json.dumps(data, indent=2, default=str)[:4000]


def main():
    mcp.run()


if __name__ == "__main__":
    main()
