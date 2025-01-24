import requests
from fastapi import FastAPI, HTTPException
from shapely.geometry import LineString
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from urllib.parse import urlencode

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base URLs for external APIs
OSRM_BASE_URL = "http://router.project-osrm.org"
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"
GEOCODING_API_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "MyApp/1.0"

# Initialize FastAPI app
app = FastAPI()

def simplify_route(route_coordinates, tolerance=0.01):
    """
    Simplify a given route to reduce the number of points while maintaining topology.

    Args:
        route_coordinates (list): List of route coordinates (longitude, latitude).
        tolerance (float): Simplification tolerance.

    Returns:
        list: Simplified route coordinates.
    """
    line = LineString(route_coordinates)
    simplified_line = line.simplify(tolerance, preserve_topology=True)
    return list(simplified_line.coords)

def query_overpass(segment):
    """
    Query the Overpass API for fuel stations within a given route segment.

    Args:
        segment (list): List of route coordinates for the segment.

    Returns:
        dict: JSON response from the Overpass API.
    """
    polyline = " ".join(f"{lon} {lat}" for lat, lon in segment)
    overpass_query = f"""
    [out:json];
    node["amenity"="fuel"](poly:"{polyline}");
    out body;
    """
    try:
        response = requests.get(OVERPASS_API_URL, params={"data": overpass_query}, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error querying Overpass API: {e}")
        return {}

def geocode_coordinates(lat, lon):
    """
    Reverse geocode coordinates to obtain address details.

    Args:
        lat (float): Latitude.
        lon (float): Longitude.

    Returns:
        dict: Address details including road, city, and state.
    """
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
    }
    try:
        response = requests.get(GEOCODING_API_URL, headers={"User-Agent": USER_AGENT}, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return {
            "address": data.get("address", {}).get("road", "Unknown"),
            "city": data.get("address", {}).get("city", "Unknown"),
            "state": data.get("address", {}).get("state", "Unknown"),
        }
    except requests.RequestException as e:
        logger.error(f"Error reverse geocoding coordinates ({lat}, {lon}): {e}")
        return {"address": "Unknown", "city": "Unknown", "state": "Unknown"}

def find_petrol_pumps(route_coordinates, segment_length=10):
    """
    Find petrol pumps along a route by querying the Overpass API for each segment.

    Args:
        route_coordinates (list): List of route coordinates (longitude, latitude).
        segment_length (int): Number of points per segment.

    Returns:
        list: List of petrol pump details including name, location, and address.
    """
    petrol_pumps = []
    segments = [route_coordinates[i:i + segment_length] for i in range(0, len(route_coordinates), segment_length)]

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_segment = {executor.submit(query_overpass, segment): segment for segment in segments}
        for future in as_completed(future_to_segment):
            try:
                data = future.result()
                for element in data.get("elements", []):
                    lat = element["lat"]
                    lon = element["lon"]
                    pump_info = {
                        "name": element.get("tags", {}).get("name", "Unknown"),
                        "latitude": lat,
                        "longitude": lon,
                    }

                    # Add reverse geocoded address details
                    address_data = geocode_coordinates(lat, lon)
                    pump_info.update(address_data)

                    petrol_pumps.append(pump_info)
            except Exception as e:
                logger.error(f"Error processing segment: {e}")

    return petrol_pumps

@app.get("/route")
def get_best_route(start: str, destination: str):
    """
    Find the best route between two locations and locate petrol pumps along the way.

    Args:
        start (str): Starting location or coordinates (e.g., "City" or "lat,lon").
        destination (str): Destination location or coordinates (e.g., "City" or "lat,lon").

    Returns:
        dict: Simplified route and petrol pump details.
    """
    try:
        def geocode(location):
            """
            Geocode a location name to coordinates.

            Args:
                location (str): Location name.

            Returns:
                tuple: Latitude and longitude.
            """
            params = {"q": location, "format": "json"}
            url = f"https://nominatim.openstreetmap.org/search?{urlencode(params)}"
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            response.raise_for_status()
            data = response.json()
            if not data:
                raise HTTPException(status_code=400, detail=f"Location '{location}' not found.")
            return float(data[0]["lat"]), float(data[0]["lon"])

        # Parse or geocode start and destination coordinates
        if "," in start and "," in destination:
            start_coords = tuple(map(float, start.split(",")))
            destination_coords = tuple(map(float, destination.split(",")))
        else:
            start_coords = geocode(start)
            destination_coords = geocode(destination)

        # Query OSRM API for route
        route_url = f"{OSRM_BASE_URL}/route/v1/driving/{start_coords[1]},{start_coords[0]};{destination_coords[1]},{destination_coords[0]}"
        route_params = {
            "overview": "full",
            "geometries": "geojson",
            "alternatives": "false",
        }
        route_response = requests.get(route_url, params=route_params, timeout=10)
        route_response.raise_for_status()
        route_data = route_response.json()

        if route_data.get("code") != "Ok":
            raise HTTPException(status_code=400, detail="Unable to find routes.")

        # Simplify route geometry
        best_route = route_data["routes"][0]
        route_geometry = best_route["geometry"]["coordinates"]
        simplified_route = simplify_route(route_geometry)

        # Find petrol pumps along the route
        petrol_pumps = find_petrol_pumps(simplified_route)

        return {
            "route": simplified_route,
            "petrol_pumps": petrol_pumps,
        }

    except Exception as e:
        logger.error(f"Error in get_best_route: {e}")
        raise HTTPException(status_code=500, detail=str(e))
