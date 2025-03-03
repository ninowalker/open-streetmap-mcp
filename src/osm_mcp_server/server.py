from mcp.server.fastmcp import FastMCP, Context, ExecutionResult
from dataclasses import dataclass
from typing import AsyncIterator, List, Dict, Optional, Tuple, Any, Union
import aiohttp
import json
import asyncio
from contextlib import asynccontextmanager
import math
from datetime import datetime

# Enhanced OSM Client with location-specific capabilities
class OSMClient:
    def __init__(self, base_url="https://api.openstreetmap.org/api/0.6"):
        self.base_url = base_url
        self.session = None
        self.cache = {}  # Simple in-memory cache
    
    async def connect(self):
        self.session = aiohttp.ClientSession()
        
    async def disconnect(self):
        if self.session:
            await self.session.close()

    async def geocode(self, query: str) -> List[Dict]:
        """Geocode an address or place name"""
        if not self.session:
            raise RuntimeError("OSM client not connected")
        
        nominatim_url = "https://nominatim.openstreetmap.org/search"
        async with self.session.get(
            nominatim_url,
            params={
                "q": query,
                "format": "json",
                "limit": 5
            },
            headers={"User-Agent": "OSM-MCP-Server/1.0"}
        ) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise Exception(f"Failed to geocode '{query}': {response.status}")
    
    async def reverse_geocode(self, lat: float, lon: float) -> Dict:
        """Reverse geocode coordinates to address"""
        if not self.session:
            raise RuntimeError("OSM client not connected")
        
        nominatim_url = "https://nominatim.openstreetmap.org/reverse"
        async with self.session.get(
            nominatim_url,
            params={
                "lat": lat,
                "lon": lon,
                "format": "json"
            },
            headers={"User-Agent": "OSM-MCP-Server/1.0"}
        ) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise Exception(f"Failed to reverse geocode ({lat}, {lon}): {response.status}")

    async def get_route(self, 
                         from_lat: float, 
                         from_lon: float, 
                         to_lat: float, 
                         to_lon: float,
                         mode: str = "car") -> Dict:
        """Get routing information between two points"""
        if not self.session:
            raise RuntimeError("OSM client not connected")
        
        # Use OSRM for routing
        osrm_url = f"http://router.project-osrm.org/route/v1/{mode}/{from_lon},{from_lat};{to_lon},{to_lat}"
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "true",
            "annotations": "true"
        }
        
        async with self.session.get(osrm_url, params=params) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise Exception(f"Failed to get route: {response.status}")

    async def get_nearby_pois(self, 
                             lat: float, 
                             lon: float, 
                             radius: float = 1000,
                             categories: List[str] = None) -> List[Dict]:
        """Get points of interest near a location"""
        if not self.session:
            raise RuntimeError("OSM client not connected")
        
        # Convert radius to bounding box (approximate)
        # 1 degree latitude ~= 111km
        # 1 degree longitude ~= 111km * cos(latitude)
        lat_delta = radius / 111000
        lon_delta = radius / (111000 * math.cos(math.radians(lat)))
        
        bbox = (
            lon - lon_delta,
            lat - lat_delta,
            lon + lon_delta,
            lat + lat_delta
        )
        
        # Build Overpass query
        overpass_url = "https://overpass-api.de/api/interpreter"
        
        # Default to common POI types if none specified
        if not categories:
            categories = ["amenity", "shop", "tourism", "leisure"]
        
        # Build tag filters
        tag_filters = []
        for category in categories:
            tag_filters.append(f'node["{category}"]({{bbox}});')
        
        query = f"""
        [out:json];
        (
            {" ".join(tag_filters)}
        );
        out body;
        """
        
        query = query.replace("{bbox}", f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}")
        
        async with self.session.post(overpass_url, data={"data": query}) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("elements", [])
            else:
                raise Exception(f"Failed to get nearby POIs: {response.status}")

    async def search_features_by_category(self, 
                                         bbox: Tuple[float, float, float, float],
                                         category: str,
                                         subcategories: List[str] = None) -> List[Dict]:
        """Search for OSM features by category and subcategories"""
        if not self.session:
            raise RuntimeError("OSM client not connected")
        
        overpass_url = "https://overpass-api.de/api/interpreter"
        
        # Build query for specified category and subcategories
        if subcategories:
            subcategory_filters = " or ".join([f'"{category}"="{sub}"' for sub in subcategories])
            query_filter = f'({subcategory_filters})'
        else:
            query_filter = f'"{category}"'
        
        query = f"""
        [out:json];
        (
          node[{query_filter}]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
          way[{query_filter}]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
          relation[{query_filter}]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
        );
        out body;
        """
        
        async with self.session.post(overpass_url, data={"data": query}) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("elements", [])
            else:
                raise Exception(f"Failed to search features by category: {response.status}")

# Create application context
@dataclass
class AppContext:
    osm_client: OSMClient

# Define lifespan manager
@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage OSM client lifecycle"""
    osm_client = OSMClient()
    try:
        await osm_client.connect()
        yield AppContext(osm_client=osm_client)
    finally:
        await osm_client.disconnect()

# Create the MCP server
mcp = FastMCP(
    "Location-Based App MCP Server",
    dependencies=["aiohttp", "geojson", "shapely", "haversine"],
    lifespan=app_lifespan
)

# === LOCATION-BASED APPLICATION FEATURES ===

@mcp.tool()
async def geocode_address(address: str, ctx: Context) -> List[Dict]:
    """
    Convert an address or place name to geographic coordinates.
    
    Args:
        address: The address or place name to geocode
        
    Returns:
        List of matching locations with coordinates and metadata
    """
    osm_client = ctx.request_context.lifespan_context.osm_client
    results = await osm_client.geocode(address)
    
    # Enhance results with additional context
    for result in results:
        if "lat" in result and "lon" in result:
            result["coordinates"] = {
                "latitude": float(result["lat"]),
                "longitude": float(result["lon"])
            }
    
    return results

@mcp.tool()
async def reverse_geocode(latitude: float, longitude: float, ctx: Context) -> Dict:
    """
    Convert geographic coordinates to an address.
    
    Args:
        latitude: The latitude coordinate
        longitude: The longitude coordinate
        
    Returns:
        Address information for the specified coordinates
    """
    osm_client = ctx.request_context.lifespan_context.osm_client
    return await osm_client.reverse_geocode(latitude, longitude)

@mcp.tool()
async def find_nearby_places(
    latitude: float,
    longitude: float,
    radius: float = 1000,  # meters
    categories: List[str] = None,
    limit: int = 20,
    ctx: Context
) -> Dict[str, Any]:
    """
    Find places near a specific location.
    
    Args:
        latitude: Center point latitude
        longitude: Center point longitude
        radius: Search radius in meters
        categories: List of place categories to search for (amenity, shop, etc.)
        limit: Maximum number of results to return
        
    Returns:
        Dictionary with nearby places grouped by category
    """
    osm_client = ctx.request_context.lifespan_context.osm_client
    
    # Set default categories if not provided
    if not categories:
        categories = ["amenity", "shop", "tourism", "leisure"]
    
    ctx.info(f"Searching for places within {radius}m of ({latitude}, {longitude})")
    places = await osm_client.get_nearby_pois(latitude, longitude, radius, categories)
    
    # Group results by category
    results_by_category = {}
    
    for place in places[:limit]:
        tags = place.get("tags", {})
        
        # Find the matching category
        for category in categories:
            if category in tags:
                subcategory = tags[category]
                if category not in results_by_category:
                    results_by_category[category] = {}
                
                if subcategory not in results_by_category[category]:
                    results_by_category[category][subcategory] = []
                
                # Add place to appropriate category and subcategory
                place_info = {
                    "id": place.get("id"),
                    "name": tags.get("name", "Unnamed"),
                    "latitude": place.get("lat"),
                    "longitude": place.get("lon"),
                    "tags": tags
                }
                
                results_by_category[category][subcategory].append(place_info)
    
    # Calculate total count
    total_count = sum(
        len(places)
        for category_data in results_by_category.values()
        for places in category_data.values()
    )
    
    return {
        "query": {
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius
        },
        "categories": results_by_category,
        "total_count": total_count
    }

@mcp.tool()
async def get_route_directions(
    from_latitude: float,
    from_longitude: float,
    to_latitude: float,
    to_longitude: float,
    mode: str = "car",
    ctx: Context
) -> Dict[str, Any]:
    """
    Get directions between two locations.
    
    Args:
        from_latitude: Starting point latitude
        from_longitude: Starting point longitude
        to_latitude: Destination latitude
        to_longitude: Destination longitude
        mode: Transportation mode (car, bike, foot)
        
    Returns:
        Routing information including distance, duration, and turn-by-turn directions
    """
    osm_client = ctx.request_context.lifespan_context.osm_client
    
    # Validate transportation mode
    valid_modes = ["car", "bike", "foot"]
    if mode not in valid_modes:
        ctx.warning(f"Invalid mode '{mode}'. Using 'car' instead.")
        mode = "car"
    
    ctx.info(f"Calculating {mode} route from ({from_latitude}, {from_longitude}) to ({to_latitude}, {to_longitude})")
    
    # Get route from OSRM
    route_data = await osm_client.get_route(
        from_latitude, from_longitude,
        to_latitude, to_longitude,
        mode
    )
    
    # Process and simplify the response
    if "routes" in route_data and len(route_data["routes"]) > 0:
        route = route_data["routes"][0]
        
        # Extract turn-by-turn directions
        steps = []
        if "legs" in route:
            for leg in route["legs"]:
                for step in leg.get("steps", []):
                    steps.append({
                        "instruction": step.get("maneuver", {}).get("instruction", ""),
                        "distance": step.get("distance"),
                        "duration": step.get("duration"),
                        "name": step.get("name", "")
                    })
        
        return {
            "summary": {
                "distance": route.get("distance"),  # meters
                "duration": route.get("duration"),  # seconds
                "mode": mode
            },
            "directions": steps,
            "geometry": route.get("geometry"),
            "waypoints": route_data.get("waypoints", [])
        }
    else:
        raise Exception("No route found")

@mcp.tool()
async def search_category(
    category: str,
    min_latitude: float,
    min_longitude: float,
    max_latitude: float,
    max_longitude: float,
    subcategories: List[str] = None,
    ctx: Context
) -> Dict[str, Any]:
    """
    Search for places of a specific category within a bounding box.
    
    Args:
        category: Main category to search for (amenity, shop, etc.)
        min_latitude: Southern boundary
        min_longitude: Western boundary
        max_latitude: Northern boundary
        max_longitude: Eastern boundary
        subcategories: Specific subcategories to filter by
        
    Returns:
        Places matching the category within the bounding box
    """
    osm_client = ctx.request_context.lifespan_context.osm_client
    
    bbox = (min_longitude, min_latitude, max_longitude, max_latitude)
    
    ctx.info(f"Searching for {category} in bounding box")
    features = await osm_client.search_features_by_category(bbox, category, subcategories)
    
    # Process results
    results = []
    for feature in features:
        tags = feature.get("tags", {})
        
        # Get coordinates based on feature type
        coords = {}
        if feature.get("type") == "node":
            coords = {
                "latitude": feature.get("lat"),
                "longitude": feature.get("lon")
            }
        # For ways and relations, use center coordinates if available
        elif "center" in feature:
            coords = {
                "latitude": feature.get("center", {}).get("lat"),
                "longitude": feature.get("center", {}).get("lon")
            }
        
        # Only include features with valid coordinates
        if coords:
            results.append({
                "id": feature.get("id"),
                "type": feature.get("type"),
                "name": tags.get("name", "Unnamed"),
                "coordinates": coords,
                "category": category,
                "subcategory": tags.get(category),
                "tags": tags
            })
    
    return {
        "query": {
            "category": category,
            "subcategories": subcategories,
            "bbox": {
                "min_latitude": min_latitude,
                "min_longitude": min_longitude,
                "max_latitude": max_latitude,
                "max_longitude": max_longitude
            }
        },
        "results": results,
        "count": len(results)
    }

@mcp.tool()
async def suggest_meeting_point(
    locations: List[Dict[str, float]],
    venue_type: str = "cafe",
    ctx: Context
) -> Dict[str, Any]:
    """
    Suggest a meeting point for multiple people based on their locations.
    
    Args:
        locations: List of dictionaries with latitude and longitude for each person
        venue_type: Type of venue to suggest (cafe, restaurant, etc.)
        
    Returns:
        Suggested meeting point and venue information
    """
    osm_client = ctx.request_context.lifespan_context.osm_client
    
    if len(locations) < 2:
        raise ValueError("Need at least two locations to suggest a meeting point")
    
    # Calculate the center point (simple average)
    avg_lat = sum(loc.get("latitude", 0) for loc in locations) / len(locations)
    avg_lon = sum(loc.get("longitude", 0) for loc in locations) / len(locations)
    
    ctx.info(f"Calculating center point for {len(locations)} locations: ({avg_lat}, {avg_lon})")
    
    # Search for venues around this center point
    venues = await osm_client.get_nearby_pois(
        avg_lat, avg_lon, 
        radius=500,  # Search within 500m of center
        categories=["amenity"]
    )
    
    # Filter venues by type
    matching_venues = []
    for venue in venues:
        tags = venue.get("tags", {})
        if tags.get("amenity") == venue_type:
            matching_venues.append({
                "id": venue.get("id"),
                "name": tags.get("name", "Unnamed Venue"),
                "latitude": venue.get("lat"),
                "longitude": venue.get("lon"),
                "tags": tags
            })
    
    # If no venues found, expand search
    if not matching_venues:
        ctx.info(f"No {venue_type} found within 500m, expanding search to 1000m")
        venues = await osm_client.get_nearby_pois(
            avg_lat, avg_lon, 
            radius=1000,
            categories=["amenity"]
        )
        
        for venue in venues:
            tags = venue.get("tags", {})
            if tags.get("amenity") == venue_type:
                matching_venues.append({
                    "id": venue.get("id"),
                    "name": tags.get("name", "Unnamed Venue"),
                    "latitude": venue.get("lat"),
                    "longitude": venue.get("lon"),
                    "tags": tags
                })
    
    # Return the result
    return {
        "center_point": {
            "latitude": avg_lat,
            "longitude": avg_lon
        },
        "suggested_venues": matching_venues[:5],  # Top 5 venues
        "venue_type": venue_type,
        "total_options": len(matching_venues)
    }

@mcp.tool()
async def explore_area(
    latitude: float,
    longitude: float,
    radius: float = 500,
    ctx: Context
) -> Dict[str, Any]:
    """
    Get a comprehensive overview of an area including points of interest, 
    amenities, and geographic features.
    
    Args:
        latitude: Center point latitude
        longitude: Center point longitude
        radius: Search radius in meters
        
    Returns:
        Detailed area information
    """
    osm_client = ctx.request_context.lifespan_context.osm_client
    
    # Categories to search for
    categories = [
        "amenity", "shop", "tourism", "leisure", 
        "natural", "historic", "public_transport"
    ]
    
    results = {}
    for i, category in enumerate(categories):
        await ctx.report_progress(i, len(categories))
        ctx.info(f"Exploring {category} features...")
        
        try:
            # Convert radius to bounding box
            lat_delta = radius / 111000
            lon_delta = radius / (111000 * math.cos(math.radians(latitude)))
            
            bbox = (
                longitude - lon_delta,
                latitude - lat_delta,
                longitude + lon_delta,
                latitude + lat_delta
            )
            
            features = await osm_client.search_features_by_category(bbox, category)
            
            # Group by subcategory
            subcategories = {}
            for feature in features:
                tags = feature.get("tags", {})
                subcategory = tags.get(category)
                
                if subcategory:
                    if subcategory not in subcategories:
                        subcategories[subcategory] = []
                    
                    # Get coordinates based on feature type
                    coords = {}
                    if feature.get("type") == "node":
                        coords = {
                            "latitude": feature.get("lat"),
                            "longitude": feature.get("lon")
                        }
                    elif "center" in feature:
                        coords = {
                            "latitude": feature.get("center", {}).get("lat"),
                            "longitude": feature.get("center", {}).get("lon")
                        }
                    
                    subcategories[subcategory].append({
                        "id": feature.get("id"),
                        "name": tags.get("name", "Unnamed"),
                        "coordinates": coords,
                        "type": feature.get("type"),
                        "tags": tags
                    })
            
            results[category] = subcategories
            
        except Exception as e:
            ctx.warning(f"Error fetching {category} features: {str(e)}")
            results[category] = {}
    
    # Get address information for the center point
    try:
        address_info = await osm_client.reverse_geocode(latitude, longitude)
    except Exception:
        address_info = {"error": "Could not retrieve address information"}
    
    # Report completion
    await ctx.report_progress(len(categories), len(categories))
    
    # Count total features
    total_features = sum(
        len(places)
        for category_data in results.values()
        for places in category_data.values()
    )
    
    return {
        "query": {
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius
        },
        "address": address_info,
        "categories": results,
        "total_features": total_features,
        "timestamp": datetime.now().isoformat()
    }

# Add resource endpoints for common location-based app needs
@mcp.resource("location://place/{query}")
async def get_place_resource(query: str) -> str:
    """
    Get information about a place by name.
    
    Args:
        query: Place name or address to look up
        
    Returns:
        JSON string with place information
    """
    async with aiohttp.ClientSession() as session:
        nominatim_url = "https://nominatim.openstreetmap.org/search"
        async with session.get(
            nominatim_url,
            params={
                "q": query,
                "format": "json",
                "limit": 1
            },
            headers={"User-Agent": "LocationApp-MCP-Server/1.0"}
        ) as response:
            if response.status == 200:
                data = await response.json()
                return json.dumps(data)
            else:
                raise Exception(f"Failed to get place info for {query}: {response.status}")

@mcp.resource("location://map/{style}/{z}/{x}/{y}")
async def get_map_style(style: str, z: int, x: int, y: int) -> Tuple[bytes, str]:
    """
    Get a styled map tile at the specified coordinates.
    
    Args:
        style: Map style (standard, cycle, transport, etc.)
        z: Zoom level
        x: X coordinate
        y: Y coordinate
        
    Returns:
        Tuple of (tile image bytes, mime type)
    """
    # Map styles to their respective tile servers
    tile_servers = {
        "standard": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "cycle": "https://tile.thunderforest.com/cycle/{z}/{x}/{y}.png",
        "transport": "https://tile.thunderforest.com/transport/{z}/{x}/{y}.png",
        "landscape": "https://tile.thunderforest.com/landscape/{z}/{x}/{y}.png",
        "outdoor": "https://tile.thunderforest.com/outdoors/{z}/{x}/{y}.png"
    }
    
    # Default to standard if style not found
    if style not in tile_servers:
        style = "standard"
    
    tile_url = tile_servers[style].replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
    
    async with aiohttp.ClientSession() as session:
        async with session.get(tile_url) as response:
            if response.status == 200:
                tile_data = await response.read()
                return tile_data, "image/png"
            else:
                raise Exception(f"Failed to get {style} tile at {z}/{x}/{y}: {response.status}")

# Main server initialization
if __name__ == "__main__":
    mcp.serve()