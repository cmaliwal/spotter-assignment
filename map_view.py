from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import requests
from shapely.geometry import LineString
from concurrent.futures import ThreadPoolExecutor, as_completed
import folium

app = FastAPI()

OSRM_BASE_URL = "http://router.project-osrm.org"
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"
GEOCODING_API_URL = "https://nominatim.openstreetmap.org/reverse"


def simplify_route(route_coordinates, tolerance=0.01):
    """
    Simplify the route geometry using the Douglas-Peucker algorithm.
    """
    line = LineString(route_coordinates)
    simplified_line = line.simplify(tolerance, preserve_topology=True)
    return list(simplified_line.coords)


def query_overpass(segment):
    """
    Query Overpass API for petrol stations along a segment of the route.
    """
    polyline = " ".join(f"{lon} {lat}" for lat, lon in segment)
    overpass_query = f"""
    [out:json];
    node["amenity"="fuel"](poly:"{polyline}");
    out body;
    """
    response = requests.get(OVERPASS_API_URL, params={"data": overpass_query})
    response.raise_for_status()
    return response.json()


def geocode_coordinates(lat, lon):
    """
    Reverse geocode coordinates to get address, city, and state.
    """
    headers = {
        "User-Agent": "MyApp/1.0"
    }
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
    }
    response = requests.get(GEOCODING_API_URL, headers=headers, params=params)
    if response.status_code == 403:
        raise HTTPException(status_code=403, detail="Nominatim API returned 403 Forbidden. Check your headers or rate limits.")
    response.raise_for_status()
    data = response.json()
    return {
        "address": data.get("address", {}).get("road", "Unknown"),
        "city": data.get("address", {}).get("city", "Unknown"),
        "state": data.get("address", {}).get("state", "Unknown"),
    }


def find_petrol_pumps(route_coordinates, segment_length=10):
    """
    Find petrol pumps along the route by splitting it into smaller segments.
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

                    address_data = geocode_coordinates(lat, lon)
                    pump_info.update(address_data)

                    petrol_pumps.append(pump_info)
            except Exception as e:
                print(f"Error querying segment: {e}")

    return petrol_pumps


@app.get("/routes", response_class=HTMLResponse)
def get_routes(start: str, destination: str):
    """
    Get all optimal routes between two locations and find petrol stations along each route.
    """
    try:
        def geocode(location):
            headers = {
                "User-Agent": "MyApp/1.0"
            }
            url = f"https://nominatim.openstreetmap.org/search"
            params = {"q": location, "format": "json"}
            response = requests.get(url, headers=headers, params=params)
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
            "alternatives": "true",
        }
        route_response = requests.get(route_url, params=route_params)
        route_response.raise_for_status()
        route_data = route_response.json()

        if route_data.get("code") != "Ok":
            raise HTTPException(status_code=400, detail="Unable to find routes.")

        routes = route_data["routes"]
        folium_map = None

        for i, route in enumerate(routes):
            route_geometry = route["geometry"]["coordinates"]
            simplified_route = simplify_route(route_geometry)

            petrol_pumps = find_petrol_pumps(simplified_route)

            if folium_map is None:
                map_center = simplified_route[0]
                folium_map = folium.Map(location=[map_center[1], map_center[0]], zoom_start=12)

            folium.PolyLine(
                [(lat, lon) for lon, lat in simplified_route],
                color=["blue", "green", "red", "orange", "purple"][i % 5],
                weight=5,
                tooltip=f"Route {i + 1}",
            ).add_to(folium_map)

            for pump in petrol_pumps:
                folium.Marker(
                    location=[pump["latitude"], pump["longitude"]],
                    popup=(
                        f"<b>Name:</b> {pump['name']}<br>"
                        f"<b>Address:</b> {pump['address']}<br>"
                        f"<b>City:</b> {pump['city']}<br>"
                        f"<b>State:</b> {pump['state']}<br>"
                        f"<b>Coordinates:</b> ({pump['latitude']}, {pump['longitude']})"
                    ),
                    icon=folium.Icon(color="green", icon="info-sign"),
                ).add_to(folium_map)

        return folium_map._repr_html_()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
