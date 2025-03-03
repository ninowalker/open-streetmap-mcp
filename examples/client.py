from mcp.client import Client
import asyncio
import json

async def main():
    # Connect to the OSM MCP server
    client = Client("http://localhost:8000")
    
    # Get information about tools
    schema = await client.get_openapi_schema()
    print(f"Available tools: {list(schema['components']['schemas'].keys())}")
    
    # Example 1: Get information about a specific place
    print("\n--- Example 1: Get Place Info ---")
    place_data = await client.get_resource("osm://place/San Francisco")
    place_info = json.loads(place_data.decode('utf-8'))
    if place_info:
        print(f"Found place: {place_info[0]['display_name']}")
        print(f"Coordinates: {place_info[0]['lat']}, {place_info[0]['lon']}")
    
    # Example 2: Search for features in an area
    print("\n--- Example 2: Search Features ---")
    # Use coordinates from the place we found
    if place_info:
        lat, lon = float(place_info[0]['lat']), float(place_info[0]['lon'])
        # Create a small bounding box around the point
        bbox = {
            "min_lat": lat - 0.01,
            "min_lon": lon - 0.01,
            "max_lat": lat + 0.01,
            "max_lon": lon + 0.01,
        }
        
        # Search for restaurants
        restaurants = await client.invoke_tool(
            "search_osm_features",
            {
                "min_lat": bbox["min_lat"],
                "min_lon": bbox["min_lon"],
                "max_lat": bbox["max_lat"],
                "max_lon": bbox["max_lon"],
                "tags": {"amenity": "restaurant"}
            }
        )
        
        print(f"Found {len(restaurants)} restaurants in the area")
        for i, restaurant in enumerate(restaurants[:5]):  # Show first 5
            print(f"  {i+1}. {restaurant.get('tags', {}).get('name', 'Unnamed')}")
    
    # Example 3: Get comprehensive map data with progress tracking
    print("\n--- Example 3: Comprehensive Map Data ---")
    task = await client.start_task(
        "get_map_data",
        {
            "min_lat": 37.75,
            "min_lon": -122.45,
            "max_lat": 37.78,
            "max_lon": -122.40,
            "feature_types": ["amenity", "building", "highway", "natural"]
        }
    )
    
    # Monitor progress
    while True:
        status = await task.get_status()
        if status.state == "running":
            print(f"Progress: {status.progress.current}/{status.progress.total} feature types processed")
            # Get log messages
            logs = await task.get_logs()
            for log in logs:
                print(f"  • {log.level}: {log.message}")
                
            await asyncio.sleep(0.5)
        else:
            break
    
    # Get the final result
    result = await task.get_result()
    print("\nMap data retrieval complete!")
    print(f"Total features: {result['total_count']}")
    for feature_type, features in result["features"].items():
        print(f"  • {feature_type}: {len(features)} features")

if __name__ == "__main__":
    asyncio.run(main())