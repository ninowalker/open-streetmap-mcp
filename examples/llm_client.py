from mcp.client import Client
import asyncio
import json
from datetime import datetime

class LocationAssistant:
    """A helper class that allows an LLM to interact with location services"""
    
    def __init__(self, mcp_url="http://localhost:8000"):
        self.client = Client(mcp_url)
        
    async def get_location_info(self, query):
        """Get information about a location from a text query"""
        results = await self.client.invoke_tool("geocode_address", {"address": query})
        if results and len(results) > 0:
            return results[0]
        return None
    
    async def find_nearby(self, place, radius=500, categories=None):
        """Find points of interest near a specific place"""
        # First, geocode the place to get coordinates
        location = await self.get_location_info(place)
        if not location:
            return {"error": f"Could not find location: {place}"}
        
        # Now search for nearby places
        if "coordinates" in location:
            nearby = await self.client.invoke_tool(
                "find_nearby_places",
                {
                    "latitude": location["coordinates"]["latitude"],
                    "longitude": location["coordinates"]["longitude"],
                    "radius": radius,
                    "categories": categories
                }
            )
            return {
                "location": location,
                "nearby": nearby
            }
        return {"error": "No coordinates found for location"}
    
    async def get_directions(self, from_place, to_place, mode="car"):
        """Get directions between two places"""
        # Geocode both locations
        from_location = await self.get_location_info(from_place)
        to_location = await self.get_location_info(to_place)
        
        if not from_location or not to_location:
            return {"error": "Could not find one or both locations"}
        
        # Get directions
        if "coordinates" in from_location and "coordinates" in to_location:
            directions = await self.client.invoke_tool(
                "get_route_directions",
                {
                    "from_latitude": from_location["coordinates"]["latitude"],
                    "from_longitude": from_location["coordinates"]["longitude"],
                    "to_latitude": to_location["coordinates"]["latitude"],
                    "to_longitude": to_location["coordinates"]["longitude"],
                    "mode": mode
                }
            )
            
            # Format the response in a way that's easy for an LLM to use
            formatted_directions = {
                "from": from_location["display_name"],
                "to": to_location["display_name"],
                "distance_km": round(directions["summary"]["distance"] / 1000, 2),
                "duration_minutes": round(directions["summary"]["duration"] / 60, 1),
                "steps": [step["instruction"] for step in directions["directions"]],
                "mode": mode
            }
            
            return formatted_directions
        
        return {"error": "No coordinates found for one or both locations"}
    
    async def find_meeting_point(self, locations, venue_type="cafe"):
        """Find a good meeting point for multiple people"""
        # Convert text locations to coordinates
        coords = []
        for place in locations:
            location = await self.get_location_info(place)
            if location and "coordinates" in location:
                coords.append({
                    "name": place,
                    "display_name": location["display_name"],
                    "latitude": location["coordinates"]["latitude"],
                    "longitude": location["coordinates"]["longitude"]
                })
        
        if len(coords) < 2:
            return {"error": "Could not find enough valid locations"}
        
        # Find meeting point
        meeting_point = await self.client.invoke_tool(
            "suggest_meeting_point",
            {
                "locations": [
                    {"latitude": loc["latitude"], "longitude": loc["longitude"]} 
                    for loc in coords
                ],
                "venue_type": venue_type
            }
        )
        
        # Add the original locations to the response
        meeting_point["original_locations"] = coords
        
        return meeting_point
    
    async def explore_neighborhood(self, place):
        """Get comprehensive information about a neighborhood"""
        # First, geocode the place to get coordinates
        location = await self.get_location_info(place)
        if not location:
            return {"error": f"Could not find location: {place}"}
        
        # Now explore the area
        if "coordinates" in location:
            # Start a background task for the exploration
            task = await self.client.start_task(
                "explore_area",
                {
                    "latitude": location["coordinates"]["latitude"],
                    "longitude": location["coordinates"]["longitude"],
                    "radius": 800  # Explore a larger area
                }
            )
            
            # Wait for completion
            while True:
                status = await task.get_status()
                if status.state != "running":
                    break
                await asyncio.sleep(0.5)
            
            # Get the final result
            area_info = await task.get_result()
            
            # Format summary for the LLM
            summary = {
                "name": location["display_name"],
                "coordinates": location["coordinates"],
                "feature_count": area_info["total_features"],
                "categories": {}
            }
            
            # Summarize each category
            for category, subcategories in area_info["categories"].items():
                if subcategories:
                    summary["categories"][category] = {
                        "count": sum(len(places) for places in subcategories.values()),
                        "types": list(subcategories.keys())
                    }
            
            return summary
        
        return {"error": "No coordinates found for location"}


# Example usage of the Location Assistant by an LLM
async def example_llm_interaction():
    """
    This simulates how an LLM like Claude would use the Location Assistant
    to provide location-based services in a conversation.
    """
    assistant = LocationAssistant()
    
    print("\n=== EXAMPLE 1: NEIGHBORHOOD EXPLORATION ===")
    print("User: 'Tell me about the Chelsea neighborhood in New York City'")