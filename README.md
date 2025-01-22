# FastAPI Best Route Petrol Pumps API

This project is a FastAPI-based application that retrieves the best route between two locations and identifies petrol pumps along the route using Overpass API and OpenStreetMap data.

---

## Features

- **Best Route Discovery**: Fetch the most optimal route between two locations.
- **Petrol Pumps Data**: Identify and provide details about petrol pumps along the best route.
- **Multi-threading**: Efficiently query APIs to minimize latency.
- **Simplified Routes**: Use geometry simplification for optimized data handling.

---

## Requirements

Install the dependencies listed in `requirements.txt` using:

```bash
pip install -r requirements.txt
```

---

## Usage

### Running the Application

Run the server with Uvicorn:

```bash
uvicorn map_view:app --reload
```

### API Endpoint

#### **GET** `/route`

- **Query Parameters**:
  - `start`: Starting location (can be a name or coordinates in the format `lat,lon`).
  - `destination`: Destination location (similar format as `start`).

- **Response**:
  - A JSON object containing the best route and corresponding petrol pumps along the route.

Example:

```bash
curl -X GET "http://127.0.0.1:8000/route?start=New+York&destination=Boston"
```

Example Response:

```json
{
  "route_index": 0,
  "route": [
    [40.7128, -74.006],
    [42.3601, -71.0589]
  ],
  "petrol_pumps": [
    {
      "name": "Fuel Station A",
      "latitude": 40.789,
      "longitude": -73.935,
      "address": "123 Main St",
      "city": "New York",
      "state": "NY"
    },
    {
      "name": "Fuel Station B",
      "latitude": 42.355,
      "longitude": -71.065,
      "address": "456 Elm St",
      "city": "Boston",
      "state": "MA"
    }
  ]
}
```

---

## Notes

- Ensure adequate rate limits for the APIs (Overpass and Nominatim) to avoid errors.
- The current implementation supports JSON responses for easier integration with frontend applications or data analysis pipelines.

---

## License

This project is licensed under the MIT License.
