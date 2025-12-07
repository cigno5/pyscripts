import math
import random


# --- 1. Math Helpers (Haversine & Area) ---

def get_dist_km(lat1, lon1, lat2, lon2):
    """Calculates distance in km between two lat/lon points."""
    R = 6371  # Earth radius
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def get_rect_area_km2(sw, ne):
    """Approximates area of a rectangle on Earth in km2."""
    # Height: Distance from SW lat to NE lat (along same longitude)
    height = get_dist_km(sw[0], sw[1], ne[0], sw[1])
    # Width: Distance from SW lon to NE lon (along middle latitude for better accuracy)
    mid_lat = (sw[0] + ne[0]) / 2
    width = get_dist_km(mid_lat, sw[1], mid_lat, ne[1])
    return height * width


# --- 2. Main Function ---

def analyze_shapes_km(circle_center, radius_km, rect_sw, rect_ne, num_simulations=1000):
    """
    circle_center: tuple (lat, lon)
    radius_km: float
    rect_sw: tuple (lat, lon) - South West corner
    rect_ne: tuple (lat, lon) - North East corner
    """

    c_lat, c_lon = circle_center
    sw_lat, sw_lon = rect_sw
    ne_lat, ne_ne_lon = rect_ne  # Typo fix in variable name
    ne_lon = rect_ne[1]

    # --- PART A: CHECK CONTAINMENT ---

    # 1. Check if Rectangle is fully inside Circle
    # Logic: All 4 corners must be within radius
    corners = [
        (sw_lat, sw_lon), (sw_lat, ne_lon),
        (ne_lat, ne_lon), (ne_lat, sw_lon)
    ]
    rect_inside_circle = all(get_dist_km(c_lat, c_lon, lat, lon) <= radius_km for lat, lon in corners)

    # 2. Check if Circle is fully inside Rectangle
    # Logic: Center is inside rect AND distance to closest edge >= radius
    is_center_in_rect = (sw_lat <= c_lat <= ne_lat) and (sw_lon <= c_lon <= ne_lon)

    circle_inside_rect = False
    if is_center_in_rect:
        # Distance to top/bottom borders (Latitude difference)
        # We approximate 1 degree lat ~= 111 km
        dist_to_top = get_dist_km(c_lat, c_lon, ne_lat, c_lon)
        dist_to_bottom = get_dist_km(c_lat, c_lon, sw_lat, c_lon)

        # Distance to left/right borders (Longitude difference at current lat)
        dist_to_left = get_dist_km(c_lat, c_lon, c_lat, sw_lon)
        dist_to_right = get_dist_km(c_lat, c_lon, c_lat, ne_lon)

        if min(dist_to_top, dist_to_bottom, dist_to_left, dist_to_right) >= radius_km:
            circle_inside_rect = True

    status = "Intersection/Partial"
    if rect_inside_circle:
        status = "Rectangle inside Circle"
    if circle_inside_rect:
        status = "Circle inside Rectangle"

    # --- PART B: CALCULATE COVERAGE (Monte Carlo) ---

    # Calculate raw areas
    circle_area = math.pi * (radius_km ** 2)
    rect_area = get_rect_area_km2(rect_sw, rect_ne)

    smaller_shape_area = min(circle_area, rect_area)
    bigger_shape_area = max(circle_area, rect_area)

    # Intersection Calculation
    # We generate random points inside the RECTANGLE and check if they are in the CIRCLE.
    points_in_circle = 0

    for _ in range(num_simulations):
        # Generate random point inside rectangle
        rand_lat = random.uniform(sw_lat, ne_lat)
        rand_lon = random.uniform(sw_lon, ne_lon)

        # Check distance to center
        if get_dist_km(rand_lat, rand_lon, c_lat, c_lon) <= radius_km:
            points_in_circle += 1

    # The fraction of the rectangle covered by the circle
    fraction_rect_covered = points_in_circle / num_simulations
    intersection_area = fraction_rect_covered * rect_area

    # # Calculate percentage of the smaller shape covered
    # coverage_percentage = (intersection_area / smaller_shape_area) * 100
    #
    # # Boundary correction: if logic says "Inside", force 100%
    # if rect_inside_circle or circle_inside_rect:
    #     coverage_percentage = 100.0

    return {
        "status": status,
        # "intersection_percentage": round(coverage_percentage, 2),
        "intersection_area": round(intersection_area, 4),
        "rect_area": round(rect_area, 4),
        "circle_area": round(circle_area, 4)
    }


# --- Usage Example ---
center = (64.1435230140209, -21.928565669009352)
radius = 3000  # meters
ne, sw = (64.161928, -21.7214082), (64.09034179999999, -21.9838354)

result = analyze_shapes_km(center, radius / 1000, sw, ne)
print(result)
print((result['intersection_area'] / result['circle_area']) * 100)
