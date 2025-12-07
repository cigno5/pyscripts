import json
import math


def create_shapes_geojson(circle_center, circle_radius, rect_ne, rect_sw, num_circle_points=64):
    """
    Generates a GeoJSON FeatureCollection containing a circle (approximated) and a rectangle.

    Parameters:
    - circle_center: tuple (lat, lon)
    - circle_radius: float (meters)
    - rect_ne: tuple (lat, lon) for North East corner
    - rect_sw: tuple (lat, lon) for South West corner
    - num_circle_points: int, number of vertices for the circle approximation (default 64)
    """

    # Unpack coordinates (lat, lon)
    c_lat, c_lon = circle_center or (0, 0)
    ne_lat, ne_lon = rect_ne
    sw_lat, sw_lon = rect_sw

    # --- 1. Generate Rectangle Coordinates ---
    # GeoJSON requires [lon, lat] order and must close the loop (start == end)
    rect_coords = [[
        [sw_lon, sw_lat],  # SW
        [ne_lon, sw_lat],  # SE
        [ne_lon, ne_lat],  # NE
        [sw_lon, ne_lat],  # NW
        [sw_lon, sw_lat]  # Close loop
    ]]

    # --- 2. Generate Circle Coordinates ---
    circle_coords_ring = []

    # Conversion factors for meters to degrees
    # 1 deg lat is approx 111,320 meters
    meters_per_deg_lat = 111320
    # 1 deg lon depends on latitude: 111,320 * cos(lat)
    meters_per_deg_lon = 111320 * math.cos(math.radians(c_lat))

    for i in range(num_circle_points + 1):
        # Calculate angle in radians
        theta = math.radians(i * (360 / num_circle_points))

        # Calculate offset in degrees
        dx = (circle_radius * math.cos(theta)) / meters_per_deg_lon
        dy = (circle_radius * math.sin(theta)) / meters_per_deg_lat

        circle_coords_ring.append([c_lon + dx, c_lat + dy])

    # --- 3. Build GeoJSON Structure ---
    geojson_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "Rectangle Area",
                    "description": "Bounding box defined by SW and NE points"
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": rect_coords
                }
            },
        ]
    }

    if circle_center:
        geojson_data['features'].append({
            "type": "Feature",
            "properties": {
                "name": "Circle Area",
                "radius_meters": circle_radius,
                "center": [c_lon, c_lat]
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [circle_coords_ring]
            }
        })

    return json.dumps(geojson_data, indent=2)


# --- Example Usage ---
if __name__ == "__main__":
    # Inputs
    center = None
    # center = (64.09515048221232, -16.350906714540788)
    radius = 3000  # meters
    ne, sw = (64.6999893, -14.4927657), (64.0190203, -16.6527273)

    # Generate
    geojson_output = create_shapes_geojson(center, radius, ne, sw)

    # Print or Save
    print(geojson_output)

    # Optional: Save to file
    # with open("shapes.geojson", "w") as f:
    #     f.write(geojson_output)
