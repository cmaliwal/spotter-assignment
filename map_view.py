import requests
from fastapi import FastAPI, HTTPException
from shapely.geometry import LineString
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from urllib.parse import urlencode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OSRM_BASE_URL = "http://router.project-osrm.org"
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"
GEOCODING_API_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "MyApp/1.0"

app = FastAPI()

def simplify_route(route_coordinates, tolerance=0.01):
    line = LineString(route_coordinates)
    simplified_line = line.simplify(tolerance, preserve_topology=True)
    return list(simplified_line.coords)

def query_overpass(segment):
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

                    address_data = geocode_coordinates(lat, lon)
                    pump_info.update(address_data)

                    petrol_pumps.append(pump_info)
            except Exception as e:
                logger.error(f"Error processing segment: {e}")

    return petrol_pumps

@app.get("/route")
def get_best_route(start: str, destination: str):
    try:
        def geocode(location):
            params = {"q": location, "format": "json"}
            url = f"https://nominatim.openstreetmap.org/search?{urlencode(params)}"
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            response.raise_for_status()
            data = response.json()
            if not data:
                raise HTTPException(status_code=400, detail=f"Location '{location}' not found.")
            return float(data[0]["lat"]), float(data[0]["lon"])

        if "," in start and "," in destination:
            start_coords = tuple(map(float, start.split(",")))
            destination_coords = tuple(map(float, destination.split(",")))
        else:
            start_coords = geocode(start)
            destination_coords = geocode(destination)

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

        best_route = route_data["routes"][0]
        route_geometry = best_route["geometry"]["coordinates"]
        simplified_route = simplify_route(route_geometry)

        petrol_pumps = find_petrol_pumps(simplified_route)

        return {
            "route": simplified_route,
            "petrol_pumps": petrol_pumps,
        }

    except Exception as e:
        logger.error(f"Error in get_best_route: {e}")
        raise HTTPException(status_code=500, detail=str(e))
