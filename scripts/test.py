import json
import math
import os.path
import random
from math import radians, sin, asin, sqrt, cos, pi

import googlemaps
import requests
import tabulate

from _common import load_configuration

API_KEY = None

T_POI = 'point_of_interest'
T_LOCALITY = 'locality'
T_TOURIST_ATTRACTION = 'tourist_attraction'
T_ROUTE = 'route'

INTERESTING_TYPES = [T_TOURIST_ATTRACTION, T_POI, T_LOCALITY]


class _IntersectionAnalysis:
    def __init__(self, circle_c, circle_r, rect_ne, rect_sw):
        """
        circle_center: tuple (lat, lon)
        radius_km: float
        rect_sw: tuple (lat, lon) - South West corner
        rect_ne: tuple (lat, lon) - North East corner
        """

        self.circle_center = circle_c
        self.circle_radius = circle_r

        num_simulations = 1000
        rect_se = (rect_sw[0], rect_ne[1])
        rect_nw = (rect_ne[0], rect_sw[1])

        # --- PART A: CHECK CONTAINMENT ---
        corners = [rect_sw, rect_se, rect_ne, rect_nw]

        rect_inside_circle = all(_haversine(circle_c, latlon) <= circle_r for latlon in corners)

        # 2. Check if Circle is fully inside Rectangle
        # Logic: Center is inside rect AND distance to closest edge >= radius
        is_center_in_rect = ((rect_sw[0] <= circle_c[0] <= rect_ne[0])
                             and (rect_sw[1] <= circle_c[1] <= rect_ne[1]))

        circle_inside_rect = False
        if is_center_in_rect:
            # Distance to top/bottom borders (Latitude difference)
            # We approximate 1 degree lat ~= 111 km
            dist_to_top = _haversine(circle_c, (rect_ne[0], circle_c[1]))
            dist_to_bottom = _haversine(circle_c, (rect_sw[0], circle_c[1]))

            # Distance to left/right borders (Longitude difference at current lat)
            dist_to_left = _haversine(circle_c, (circle_c[0], rect_sw[1]))
            dist_to_right = _haversine(circle_c, (circle_c[0], rect_ne[1]))

            circle_inside_rect = min(dist_to_top, dist_to_bottom, dist_to_left, dist_to_right) >= circle_r

        rect_c = ((rect_sw[0] + rect_ne[0]) / 2, (rect_sw[1] + rect_ne[1]) / 2)

        # 2. Measure distance from circle center to that closest point
        self.distance_to_center = _haversine(circle_c, rect_c)

        # Check if the two shapes don't intersect at all
        shapes_dont_intersect = self.distance_to_center > circle_r

        if rect_inside_circle:
            self.status = "rect-inside-circle"
        elif circle_inside_rect:
            self.status = "circle-inside-rect"
        elif shapes_dont_intersect:
            self.status = "not-intersecting"
        else:
            self.status = "intersecting"

        # --- PART B: CALCULATE COVERAGE (Monte Carlo) ---
        # Calculate raw areas
        self.circle_area = pi * (circle_r ** 2)
        self.rect_area = _rect_area(rect_sw, rect_ne)

        self.smaller_shape_area = min(self.circle_area, self.rect_area)
        self.bigger_shape_area = max(self.circle_area, self.rect_area)

        # Intersection Calculation
        # We generate random points inside the RECTANGLE and check if they are in the CIRCLE.
        points_in_circle = 0

        for _ in range(num_simulations):
            # Generate random point inside rectangle
            rand = (random.uniform(rect_sw[0], rect_ne[0]), random.uniform(rect_sw[1], rect_ne[1]))

            # Check distance to center
            if _haversine(rand, circle_c) <= circle_r:
                points_in_circle += 1

        # Fix the simulation for the circle within a very big rect
        if circle_inside_rect and points_in_circle == 0:
            points_in_circle = 1

        # The fraction of the rectangle covered by the circle
        fraction_rect_covered = points_in_circle / num_simulations
        self.intersection_area = fraction_rect_covered * self.rect_area

    def get_size_ratio(self):
        if self.status == "intersecting":
            return self.intersection_area / self.circle_area
        elif self.status == 'not-intersecting':
            return 0
        else:
            return self.bigger_shape_area / self.smaller_shape_area

    def get_size_factor(self):
        ratio = self.get_size_ratio()
        return 0 if ratio == 0 else ratio if ratio <= 1 else 1 / ratio

    def get_center_factor(self):
        # def get_bounded_gaussian(distance, radius, min_score_at_radius=0.7):
        # Calculate the center point of the gaussian distribution
        min_score_at_radius = 0.5
        if self.distance_to_center == 0:
            return 1.0

        # 1. Calculate the required sigma for the boundary condition
        # sigma = sqrt( radius^2 / (-2 * ln(min_score)) )
        sigma = math.sqrt((self.circle_radius / 2) ** 2 / (-2 * math.log(min_score_at_radius)))

        # 2. Calculate Gaussian factor
        return 1 + math.exp(-(self.distance_to_center ** 2) / (2 * sigma ** 2))
        # sigma = 5
        # return math.exp(-(self.distance_to_center ** 2) / (2 * sigma ** 2))

    def __str__(self):
        return f"Status: {self.status}; Circle area: {self.circle_area}; Rect area: {self.rect_area}; Intersection area: {self.intersection_area}"


class GeoCodeAddressComponent:
    def __init__(self, address_component, is_geocode=True):
        _t_long = 'long_name' if is_geocode else 'longText'
        _t_short = 'short_name' if is_geocode else 'shortText'

        self.long_name = address_component[_t_long]
        self.short_name = address_component[_t_short] if _t_short in address_component else self.long_name
        self.types = address_component['types'] if 'types' in address_component else []

    def __str__(self):
        return f"{self.short_name} ({', '.join(self.types)})"


class GeoLocation:
    def __init__(self, center, radius, geo_place, is_geocode=True):
        if is_geocode:
            self.source = 'geocode'
            _t_address = 'formatted_address'
            _t_address_components = 'address_components'
            _lat, _lon = 'lat', 'lng'
            _high, _low = 'northeast', 'southwest'
            _viewport = geo_place['geometry']['viewport']
        else:
            self.source = 'gplaces'
            _t_address = 'formattedAddress'
            _t_address_components = 'addressComponents'
            _lat, _lon = 'latitude', 'longitude'
            _high, _low = 'high', 'low'
            _viewport = geo_place['viewport']

        self.center = center
        self.radius = radius
        self.address = geo_place[_t_address]
        self.types = geo_place['types']

        self.primary_type = None if is_geocode or 'primaryType' not in geo_place else geo_place['primaryType']
        self.display_name = geo_place[_t_address] if is_geocode else geo_place['displayName']['text']

        def a(b):
            return (b[_high][_lat], b[_high][_lon]), (b[_low][_lat], b[_low][_lon])

        self.viewport = a(_viewport)
        self.address_chain = [GeoCodeAddressComponent(c, is_geocode) for c in geo_place[_t_address_components]]
        self.intersection_analysis = _IntersectionAnalysis(self.center, self.radius, self.viewport[0], self.viewport[1])

    def is_point_of_interest(self):
        return self._is_something(T_POI)

    def is_locality(self):
        return self._is_something(T_LOCALITY)

    def get_place_score(self):
        def x_score(base_score, _type):
            if _type in INTERESTING_TYPES:
                return base_score * base_score_factor * (len(INTERESTING_TYPES) - INTERESTING_TYPES.index(_type))
            else:
                return 0

        score = x_score(1000, self.primary_type)
        for _type in self.types:
            score += x_score(100, _type)

        for _address_comp in self.address_chain:
            for _type in _address_comp.types:
                if _type in INTERESTING_TYPES:
                    score += x_score(10, _type)

        if use_size_factor:
            score *= self.intersection_analysis.get_size_factor()

        if use_center_factor:
            score *= self.intersection_analysis.get_center_factor()

        return score

    def get_place_name(self):
        def _p(_tp):
            return next((c.short_name for c in self.address_chain if _tp in c.types), None)

        return next((n for n in [self.display_name] if n and self.primary_type in INTERESTING_TYPES),
                    next((_p(it) for it in INTERESTING_TYPES if it in self.types and _p(it)),
                         next((_p(it) for it in INTERESTING_TYPES if _p(it)), None)))

    def _is_something(self, tp):
        return tp in self.types or tp == self.primary_type

    def __str__(self):
        return f"""{self.source} ----------------------------------------------------------------------
  - Place name.....: {self.get_place_name()}
  - Place score....: {self.get_place_score()}
  - Intersection analysis
    - Size factor..: {self.intersection_analysis.get_size_factor()}
    - Center factor: {self.intersection_analysis.get_center_factor()}
  - Address........: {self.address}
  - Primary type...: {self.primary_type}
  - Types..........: {', '.join(self.types)}
  - Geometry.......: {self.viewport}
  - Address Chain..:
""" + '\n'.join([f"    - {str(c)}" for c in self.address_chain])

    def __lt__(self, other):
        return self.get_place_score() < other.get_place_score()


class Location:
    def __init__(self, name, location_center, location_radius):
        self.name = name
        self.center = location_center
        self.radius = location_radius

        geocode = gplaces = None
        try:
            with open(f'{HOME}/{name}-geocode.json', 'r') as gc, open(f'{HOME}/{name}-gplaces.json', 'r') as gp:
                # print(f"Reading cache for {name}...")
                geocode = json.load(gc)
                gplaces = json.load(gp)

        except FileNotFoundError:
            with open(f'{HOME}/{name}-geocode.json', 'w') as gc, open(f'{HOME}/{name}-gplaces.json', 'w') as gp:
                print(f'Loading data for {name} #####################')
                geocode = gmaps.reverse_geocode(self.center)
                json.dump(geocode, gc)
                gplaces = _load_places(self.center, self.radius)
                json.dump(gplaces, gp)

        self.geocode_locations = [GeoLocation(self.center, self.radius, obj) for obj in geocode]
        self.gplaces_locations = [GeoLocation(self.center, self.radius, gp, False) for gp in gplaces]

    def first_guess(self):
        for _locations in [self.geocode_locations, self.gplaces_locations]:
            for _loc in _locations:
                if _loc.get_place_name():
                    return _loc

    def first_guess_places_first(self):
        for _locations in [self.gplaces_locations, self.geocode_locations]:
            for _loc in _locations:
                if _loc.get_place_name():
                    return _loc

    def first_by_score(self) -> GeoLocation:
        return next(
            iter(
                sorted(
                    filter(lambda _loc: _loc.get_place_score() > 0,
                           self.geocode_locations + self.gplaces_locations),
                    key=lambda _loc: _loc.get_place_score(),
                    reverse=True)), None)

    def all_valid(self):
        return sorted(
            filter(lambda _loc: _loc.get_place_score() > 0,
                   self.geocode_locations + self.gplaces_locations),
            key=lambda _loc: _loc.get_place_score(),
            reverse=True)

    def all(self):
        return sorted(self.geocode_locations + self.gplaces_locations, reverse=True)

    def to_geojson(self, loc_filter='first'):
        loc_filters = {
            'first': self.first_guess,
            'all_valid': self.all_valid,
            'all': self.all,
        }
        assert loc_filter in loc_filters

        num_circle_points = 64
        # 1 deg lat is approx 111,320 meters
        meters_per_deg_lat = 111320

        def rect_feature(_geoloc: GeoLocation):
            ne_lat, ne_lon = _geoloc.viewport[0]
            sw_lat, sw_lon = _geoloc.viewport[1]

            # --- 1. Generate Rectangle Coordinates ---
            # GeoJSON requires [lon, lat] order and must close the loop (start == end)
            rect_coords = [[
                [sw_lon, sw_lat],  # SW
                [ne_lon, sw_lat],  # SE
                [ne_lon, ne_lat],  # NE
                [sw_lon, ne_lat],  # NW
                [sw_lon, sw_lat]  # Close loop
            ]]

            return {
                "type": "Feature",
                "properties": {
                    "name": _geoloc.display_name,
                    "description":
                        f"Size factor: {_geoloc.intersection_analysis.get_size_factor():.5f}; Size ratio: {_geoloc.intersection_analysis.get_size_ratio():.5f}; "
                        f"Center factor: {_geoloc.intersection_analysis.get_center_factor():.5f}",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": rect_coords
                }
            }

        def circle_feature():
            # Unpack coordinates (lat, lon)
            c_lat, c_lon = self.center
            # 1 deg lon depends on latitude: 111,320 * cos(lat)
            meters_per_deg_lon = 111320 * math.cos(math.radians(c_lat))

            circle_coords_ring = []
            for i in range(num_circle_points + 1):
                # Calculate angle in radians
                theta = math.radians(i * (360 / num_circle_points))

                # Calculate offset in degrees
                dx = (self.radius * math.cos(theta)) / meters_per_deg_lon
                dy = (self.radius * math.sin(theta)) / meters_per_deg_lat

                circle_coords_ring.append([c_lon + dx, c_lat + dy])

            return {
                "type": "Feature",
                "properties": {
                    "name": f"Supposedly {self.name}",
                    "radius_meters": self.radius,
                    "center": [self.center[0], self.center[1]],
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [circle_coords_ring],
                }
            }

        return {
            "type": "FeatureCollection",
            "features": [
                circle_feature(),
                *[rect_feature(geoloc) for geoloc in loc_filters[loc_filter]()]
            ]
        }


def _load_places(latlon, radius):
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': API_KEY,
        'X-Goog-FieldMask': 'places.displayName,'
                            'places.formattedAddress,'
                            'places.addressComponents,'
                            'places.primaryType,'
                            'places.types,'
                            'places.viewport',
        # 'X-Goog-FieldMask': '*',
    }

    json_data = {
        'includedTypes': [
            'tourist_attraction',
            'historical_landmark',
            'locality',
            'administrative_area_level_1',
        ],
        "maxResultCount": 10,
        'locationRestriction': {
            'circle': {
                'center': {
                    'latitude': latlon[0],
                    'longitude': latlon[1],
                },
                'radius': max(radius, search_radius),
            },
        },
    }

    r = requests.post('https://places.googleapis.com/v1/places:searchNearby', headers=headers, json=json_data)
    r.raise_for_status()
    return r.json()['places']


def _haversine(latlon1, latlon2):
    R = 6371000  # meters
    dlat = radians(latlon2[0] - latlon1[0])
    dlon = radians(latlon2[1] - latlon1[1])

    a = sin(dlat / 2) ** 2 + cos(radians(latlon1[0])) * cos(radians(latlon2[0])) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def _rect_area(sw, ne):
    """Approximates area of a rectangle on Earth in m2."""
    # Height: Distance from SW lat to NE lat (along same longitude)
    height = _haversine(sw, ne)
    # Width: Distance from SW lon to NE lon (along middle latitude for better accuracy)
    mid_lat = (sw[0] + ne[0]) / 2
    width = _haversine((mid_lat, sw[1]), (mid_lat, ne[1]))
    return height * width


def _statistical_circle(_all_points):
    if not _all_points:
        return None, 0
    elif len(_all_points) == 1:
        return _all_points[0], search_radius / 10

    # 1. Compute Mean Center
    center_lat = sum(p[0] for p in _all_points) / len(_all_points)
    center_lon = sum(p[1] for p in _all_points) / len(_all_points)
    center = (center_lat, center_lon)

    # 2. Compute Distances from center
    distances = [_haversine(center, p) for p in _all_points]

    # 3. Use 2 Standard Deviations for the radius (covers ~95% of points)
    # This ignores extreme outliers but covers the main group well
    avg_dist = sum(distances) / len(distances)
    variance = sum((d - avg_dist) ** 2 for d in distances) / len(distances)
    std_dev = math.sqrt(variance)

    # Radius = Average Distance + 2 * Standard Deviation
    # This creates a circle that 'approximately' covers everything.
    radius = avg_dist + (2 * std_dev)

    return center, radius


CLUSTER_CENTER_MAP = {
    'glacier': (64.04994530908286, -16.180322809394184),
    'glacier1': (63.94155887303119, -16.65172446465485),
    'reykjavik': (64.1435230140209, -21.928565669009352),
    'guesthouse': (64.1270527610111, -16.014502651925),
    'vik': (63.41678240672989, -19.00035372327726),
    'skogafoss': (63.53062021541366, -19.512709586930402),
    'jokulsarlon': (64.09515048221232, -16.350906714540788),
    'stokksnes': (64.24980343638836, -14.982873134507942),
    'svínafellsjokull': (64.00278362654856, -16.878436683476444),
}

CLUSTER_POINTS = {
    (64.1270527610111, -16.014502651925): [(64.1270527610111, -16.014502651925)],
    (63.94155887303119, -16.65172446465485): [
        (63.9403540512722, -16.6270270373778),
        (63.9429021053083, -16.6792591446639),
        (63.9420326271556, -16.661435866275),
        (63.9426968118694, -16.6750508704806),
        (63.941489203275, -16.6502963173519),
        (63.9401246056778, -16.6223236722917),
        (63.9409699317, -16.6396518595028),
        (63.9425277466028, -16.6715852330639),
        (63.9419722467167, -16.6601981385528),
        (63.9405110403778, -16.6302451292667),
        (63.9405955729694, -16.6319779480417),
        (63.9424069857944, -16.6691097777525),
        (63.9416824206861, -16.6542570458917)],
    (63.41678240672989, -19.00035372327726): [
        (63.41660119625, -18.9998332571944),
        (63.417064613, -19.0006186319958),
        (63.4167546161993, -19.0007568714),
        (63.4167164808, -18.9997937341889),
        (63.4167751274001, -19.0007661216072)],
    (63.53062021541366, -19.512709586930402): [
        (63.5310416883889, -19.5122614035083),
        (63.5320569432056, -19.5133356340222),
        (63.5308156383556, -19.5124567885944),
        (63.5307132614, -19.5124199648194),
        (63.5301474289833, -19.5133060809028),
        (63.5313287150222, -19.5122091980528),
        (63.5308189639972, -19.5126929118778),
        (63.530048621075, -19.5134501192528),
        (63.5311421892194, -19.5118737089889),
        (63.5308334359861, -19.512447002925),
        (63.5319029103333, -19.5132149489333),
        (63.5313425936, -19.5123288152611),
        (63.5313898661194, -19.5123188809889),
        (63.5295678650528, -19.5129588979222),
        (63.5307807950028, -19.5126419790194),
        (63.5297381639889, -19.5131391167833),
        (63.5297636622639, -19.5131432377972),
        (63.5294249592167, -19.5128612662944),
        (63.5319178874333, -19.5132032875583),
        (63.5309266524, -19.5124031502778),
        (63.5295782868167, -19.5129901663917),
        (63.5308540088389, -19.5124709326139),
        (63.5295678650528, -19.5129588979222),
        (63.5297298799944, -19.5131310610139),
        (63.53095243805, -19.5124526231806),
        (63.5307500422806, -19.5124227419583),
        (63.5311692699667, -19.5119169719167),
        (63.5307930092111, -19.5124736746556),
        (63.5308039882611, -19.5124322324),
        (63.5321289954333, -19.5132984444444),
        (63.529550764, -19.5129735752944),
        (63.5297596985417, -19.5132449161972),
        (63.530746658775, -19.5124097924972),
        (63.5309888369667, -19.5123765696333),
        (63.5307212717694, -19.512435599575),
        (63.5307052510083, -19.5124043300056),
        (63.5295641592917, -19.5129285859972),
        (63.5295015204167, -19.5129767938778)],
    (64.04994530908286, -16.180322809394184): [
        (64.0478419182944, -16.1810295277528),
        (64.0480117049917, -16.1810751479722),
        (64.0492666089667, -16.1808203316194),
        (64.049233365, -16.1807971430139),
        (64.0479455667778, -16.1809405969444),
        (64.0512583480111, -16.1797404590333),
        (64.0512583480111, -16.1797404590333),
        (64.0512591526997, -16.1796410504056),
        (64.0493641788528, -16.1807697003861),
        (64.0515429845003, -16.1794333791222),
        (64.0479371942695, -16.180950111625),
        (64.0512583480111, -16.1797404590333),
        (64.0512641034856, -16.1796595001194),
        (64.0515409163919, -16.1795766061806),
        (64.0493667140139, -16.1808405881222),
        (64.0512583480111, -16.1797404590333),
        (64.0512583480111, -16.1797404590333),
        (64.0512583480111, -16.1797404590333),
        (64.0492069948556, -16.180856128075),
        (64.0492142792667, -16.1808425585972),
        (64.0493329600222, -16.1808123249306),
        (64.0478615269889, -16.1811121019944),
        (64.0512583480111, -16.1797404590333),
        (64.0512583480111, -16.1797404590333),
        (64.0478944393056, -16.1808436985972),
        (64.0480138629917, -16.1810093200028),
        (64.0493465189861, -16.180826281),
        (64.0514090333967, -16.1798801973222),
        (64.0512583480111, -16.1797404590333),
        (64.0493340680111, -16.18087131),
        (64.0515354733989, -16.1795721639472),
        (64.0512400359989, -16.1786467413861),
        (64.0494598978278, -16.180442031675),
        (64.048911676475, -16.180899074075),
        (64.0492126193, -16.1807963892361),
        (64.0493237095361, -16.1808285631889),
        (64.0512583480111, -16.1797404590333),
        (64.0492159246778, -16.1807840831639),
        (64.0512583480111, -16.1797404590333),
        (64.0514376588458, -16.1798525404361),
        (64.0493645753139, -16.1807670319778),
        (64.0497914974278, -16.1800027832083),
        (64.0478518958389, -16.1811013241222),
        (64.0515431329969, -16.1795570640861),
        (64.0493329600222, -16.1808123249306),
        (64.0512583480111, -16.1797404590333),
        (64.04930583445, -16.1808458201889),
        (64.0513258753856, -16.1797368117944),
        (64.0512583480111, -16.1797404590333),
        (64.0479256801055, -16.1810600699528),
        (64.0512583480111, -16.1797404590333),
        (64.0493656229611, -16.1808548070444),
        (64.051452678845, -16.1798680904528),
        (64.0515380757933, -16.1794738465333),
        (64.0512583480111, -16.1797404590333),
        (64.0479320695111, -16.1809792866278),
        (64.0478973669695, -16.1810676890861),
        (64.0479886243389, -16.1810732526889),
        (64.0493324477778, -16.1808196802694),
        (64.0512583480111, -16.1797404590333),
        (64.0512583480111, -16.1797404590333),
        (64.0493605234056, -16.1807516891889),
        (64.0512583480111, -16.1797404590333),
        (64.0512583480111, -16.1797404590333),
        (64.0493505981806, -16.1808129565556),
        (64.0479275532111, -16.1810197491917),
        (64.0493761378, -16.1808091463861),
        (64.0478841669583, -16.1810597019944)],
    (64.1435230140209, -21.928565669009352): [
        (64.1422915126889, -21.9275707671944),
        (64.1419759973972, -21.9270017281111),
        (64.1442093820333, -21.9284867039889),
        (64.1422739820556, -21.9272190220167),
        (64.1420229910556, -21.9274170130222),
        (64.1419833149972, -21.9273602992028),
        (64.1449300172278, -21.9298402373917),
        (64.1420223117944, -21.9275093170389),
        (64.1422825789944, -21.9287295439944),
        (64.1466745150806, -21.9318400349639),
        (64.1419889569944, -21.9275991480056),
        (64.1449134574917, -21.9298707274333),
        (64.1441686579056, -21.9281462218111),
        (64.1442956372, -21.9286701848361),
        (64.1470088532889, -21.9318088271944),
        (64.1422825789944, -21.9287295439944),
        (64.1449399901028, -21.9298822610194),
        (64.1442920179889, -21.928811152025),
        (64.144176335175, -21.9279189338389),
        (64.1443171944, -21.928869210175),
        (64.1423037671444, -21.9285725023917),
        (64.1424532490083, -21.9280933040278),
        (64.1442133909944, -21.9283760799944),
        (64.1419744130278, -21.9274655210778),
        (64.1422825789944, -21.9287295439944),
        (64.1441712075667, -21.9280135219278),
        (64.1445430499806, -21.9299193299889),
        (64.1442944066528, -21.9288143186167),
        (64.1439746649917, -21.9273906301),
        (64.1424294094, -21.9283144409028)],
    (64.09515048221232, -16.350906714540788): [
        (64.0951026185417, -16.3518311335992),
        (64.0951672126667, -16.3507521409992),
        (64.0951051019944, -16.350985905995),
        (64.0951253294111, -16.3509463406008),
        (64.0951225907028, -16.3516591323964),
        (64.0950804247667, -16.3517242433914),
        (64.095055365575, -16.3507876089997),
        (64.0951375709972, -16.3506700190025),
        (64.0952073860333, -16.3516974469942),
        (64.0951271870361, -16.351739677405),
        (64.0950727436583, -16.3510748417925),
        (64.0950926853695, -16.3514217404),
        (64.0950353768083, -16.3514775668072),
        (64.0956139370222, -16.3469466084361),
        (64.0951893250944, -16.3517490780003),
        (64.0950957954806, -16.3508567705925),
        (64.0970561300361, -16.3432083580333),
        (64.0950787136167, -16.351068809005),
        (64.0949778311972, -16.3517459017964),
        (64.095110873525, -16.3514603625983),
        (64.0950867752556, -16.351227118),
        (64.0950205590194, -16.3516213369964),
        (64.0950713490389, -16.3515066920092),
        (64.094957902, -16.3509801173994),
        (64.0949859901944, -16.3514547344033),
        (64.0951519605972, -16.3516600271978),
        (64.0950247757528, -16.3517500008),
        (64.094956458975, -16.3509722470017),
        (64.0956110894194, -16.346928557675),
        (64.0951144137778, -16.3509428768067),
        (64.0950963214167, -16.3509465519997),
        (64.0949828859972, -16.351772978),
        (64.0950399629806, -16.351632883),
        (64.0950442978944, -16.3514836),
        (64.0950118210028, -16.3514075102003),
        (64.0950919672028, -16.350949332805),
        (64.0950188301917, -16.3515569568083),
        (64.0950443653222, -16.3517745079978),
        (64.0951980491945, -16.3518657250014),
        (64.0950618759306, -16.3516587568006),
        (64.0950514150528, -16.3507904390014),
        (64.0950935973944, -16.3515858228108),
        (64.0950758343889, -16.3508801715944),
        (64.0949752390722, -16.3510231460008),
        (64.0951178633861, -16.3514152356042),
        (64.0956351981361, -16.3468905658028),
        (64.0951199460083, -16.3512844740003),
        (64.0950282020556, -16.3517562453956)],
    (64.24980343638836, -14.982873134507942): [
        (64.2480382959722, -14.9795413899944),
        (64.2504591771992, -14.9844017964072),
        (64.2494722309889, -14.9818472010833),
        (64.2516118240033, -14.9869972890139),
        (64.2483942269667, -14.978341183025),
        (64.2494482366333, -14.9846442665989),
        (64.2479646099694, -14.9797338489528),
        (64.2479587507889, -14.9770126231944),
        (64.2518839509944, -14.987591617),
        (64.2519058289983, -14.987542521),
        (64.2515931556017, -14.9869797216222),
        (64.248132538, -14.9801047189833),
        (64.2524726560081, -14.9882876100111),
        (64.2497018330111, -14.9828040321528),
        (64.2498314069972, -14.9849664514061),
        (64.2496707210167, -14.9847498939992),
        (64.2505664480019, -14.9841655664011),
        (64.24897561, -14.9811883431167),
        (64.2478940107972, -14.9769144993722),
        (64.2498178840028, -14.9850105559983),
        (64.2479539578361, -14.9775104223306),
        (64.2482804099472, -14.9805499401028),
        (64.2490096190028, -14.9811480554),
        (64.2522407391997, -14.9872841720111),
        (64.2488554700028, -14.9805667540694),
        (64.2490094352083, -14.980559340975),
        (64.2516196279981, -14.987002622),
        (64.2501915658003, -14.9846842462),
        (64.2479978859667, -14.9797939400167),
        (64.2479026784083, -14.9769636502278),
        (64.2496691621833, -14.9847498939992),
        (64.2478239841778, -14.9770176971333),
        (64.2518953820172, -14.9876421250056),
        (64.2504700269995, -14.9843675690022),
        (64.2480455530556, -14.9796317250222),
        (64.2494610790445, -14.9817568601),
        (64.2478323137889, -14.9770009756667),
        (64.2490197018111, -14.9811592210778),
        (64.2476868089972, -14.9772841780167),
        (64.2501900049999, -14.9846831799953),
        (64.2504850152019, -14.9843489959997),
        (64.2480364869833, -14.9795214709917),
        (64.2505312074044, -14.9842295342),
        (64.2523051962194, -14.9879676426167),
        (64.2485536509778, -14.9784474368278),
        (64.2517743010014, -14.9873031569917),
        (64.2480442919528, -14.9795268010056),
        (64.2518934638108, -14.9876392079917),
        (64.2504697360014, -14.9844020780089),
        (64.2498259490028, -14.9849653850036),
        (64.2478955395528, -14.9769731905111),
        (64.247951783225, -14.9770003923944),
        (64.2518291929978, -14.9872899800028),
        (64.2494743198583, -14.9818272810056),
        (64.2495379040083, -14.9845833386),
        (64.2516182506092, -14.9873336516028),
        (64.2500894240003, -14.985089427),
        (64.2518271029897, -14.9873099009889),
        (64.2524014430014, -14.9880948260028),
        (64.2481020061722, -14.9774845943722),
        (64.2518888826, -14.9876147377889),
        (64.2504655580011, -14.9844419179989),
        (64.2488709074167, -14.9805991847833),
        (64.2517467561992, -14.987431653975),
        (64.2490720355361, -14.9810663561889),
        (64.2485010959361, -14.9784595630778),
        (64.2501932194004, -14.9849661029861),
        (64.248741146525, -14.9802132625833),
        (64.250485589, -14.9843904659983),
        (64.2517896280008, -14.987353665),
        (64.2494938260028, -14.9818379419861),
        (64.24948861615, -14.9818557296111),
        (64.2505256914006, -14.9842353698008),
        (64.2500737731998, -14.9842509825986),
        (64.2478141835028, -14.97708037225),
        (64.2518271029897, -14.9873099009889),
        (64.24955842165, -14.9820875297806),
        (64.2496668239833, -14.9847498939992),
        (64.2479383200083, -14.977447976),
        (64.2479872345972, -14.9797445090444),
        (64.2494656850611, -14.9819467990056),
        (64.2490158542195, -14.9811480554),
        (64.250462233003, -14.9843675690022),
        (64.2495075061278, -14.9821434720944),
        (64.2484498363194, -14.9785200545611),
        (64.2490240486056, -14.9810965452167),
        (64.2505184388003, -14.9842608439992),
        (64.2479891514167, -14.9796337488361),
        (64.2505476059997, -14.9841697729989),
        (64.2494631678972, -14.981736941125),
        (64.2489512569556, -14.9812005200056),
        (64.2523005450069, -14.9873613470056),
        (64.251604019, -14.9869919559694),
        (64.2524135620111, -14.9880961758),
        (64.2518896670028, -14.9876168709917)],
    (64.00278362654856, -16.878436683476444): [
        (64.0042178, -16.8776426537944),
        (63.99961718175, -16.8840055703994),
        (64.0037636179945, -16.8788214515083),
        (64.0039440873667, -16.8790313003222),
        (64.0015765747981, -16.8799594970389),
        (64.0039237060167, -16.8790711199722),
        (64.0037902651722, -16.8787217675944),
        (64.0021468141314, -16.8770508530778),
        (64.00383598, -16.877848907),
        (64.0015494237211, -16.8790328495639),
        (64.0035571839889, -16.8776768159833),
        (64.0027654143733, -16.8767537516528),
        (64.0015443137894, -16.8788428270056),
        (64.0040906826111, -16.8773896947722),
        (64.0026496033647, -16.8768093733556),
        (64.0015899174069, -16.8796950571889),
        (64.0016853077875, -16.8800065407583),
        (64.0037016570055, -16.8774036559583),
        (63.9999480811556, -16.883279965525),
        (64.0034718480028, -16.8771320199278),
        (64.0039191353083, -16.87926778005),
        (64.0006974647994, -16.882516773575),
        (64.0033271935694, -16.876774024025),
        (64.0024292799847, -16.8769151902889),
        (64.0037283380028, -16.8787820661417),
        (64.0018755585981, -16.8774382143972),
        (64.0036286028028, -16.8775719485972),
        (64.0028303815389, -16.8767225493417),
        (64.0041092889806, -16.8774003759389),
        (64.0041146639944, -16.8774258699778),
        (64.0029857377528, -16.8766479348139),
        (64.0041246630083, -16.8775159750417),
        (64.0035182889889, -16.8771616899611),
        (64.0038400694028, -16.8780400149944),
        (64.0035400380028, -16.8773920460333),
        (64.0017257420092, -16.8778432939167),
        (64.0037242708028, -16.8778098261944),
        (64.00156416463, -16.8792810117806),
        (64.0017454941917, -16.8808138636222),
        (64.0039149605917, -16.8791376198528),
        (64.0040404510028, -16.8773137849667),
        (64.0024914224861, -16.8768853445694),
        (64.0037511467889, -16.8778781308),
        (64.0038008840194, -16.8786396198833),
        (64.0015848459047, -16.8796291796056),
        (64.0015461235111, -16.878977290725),
        (64.0015787072136, -16.8799017364778),
        (64.0034662002, -16.8771801480306),
        (64.0016535477983, -16.8800278517194),
        (64.0015789055406, -16.8795291738889),
        (64.0041524420028, -16.8774781761167),
        (64.0036665602056, -16.8774547282028),
        (64.0041363490028, -16.87755913795),
        (64.0015698849822, -16.8793773134139),
        (64.0011605564003, -16.8818045084139),
        (64.0025676882711, -16.87684871565),
        (64.0027795376778, -16.8767469685722),
        (64.0016606565997, -16.8797648141944),
        (64.0032484310361, -16.8765217684861),
        (64.0016089733972, -16.8796822706),
        (64.0038015436083, -16.8786059526056),
        (64.0033303461417, -16.8764824263028),
        (64.0021863593436, -16.8770318603222),
        (64.0028021349611, -16.8767361155806),
        (64.0035966249861, -16.8772440154972),
        (64.0042749342028, -16.8776665230028),
        (63.9997549240722, -16.8836564964003)],
}

search_radius = 3000
HOME = os.path.expanduser('~/tmp/gpslogger/script')
use_size_factor = True
use_center_factor = True
base_score_factor = 10

if __name__ == '__main__':
    conf = load_configuration('.rawsort.ini')
    API_KEY = conf['rawsort']['API_KEY']
    gmaps: googlemaps.Client = googlemaps.Client(key=API_KEY)


    def all_locs(loc: Location):
        for _l in loc.all():
            print(_l)


    def all_valid(loc: Location):
        for _l in loc.all_valid():
            print(_l)


    def to_geojson_all_valid(loc: Location):
        print(json.dumps(loc.to_geojson('all_valid'), indent=2))


    def to_geojson_all(loc: Location):
        print(json.dumps(loc.to_geojson('all'), indent=2))


    def test_first(loc: Location):
        print(loc.first_by_score())
        print(loc.first_guess())
        print(loc.first_guess_places_first())


    def first(loc: Location):
        print(loc.first_by_score())

    def first_summary(loc: Location):
        print(loc.first_by_score().get_place_name())


    # func = all_locs
    # func = all_valid
    # func = to_geojson_all_valid
    # func = to_geojson_all
    # func = test_first
    # func = first
    func = first_summary

    # choice = 'jokulsarlon'
    # choice = 'skogafoss'
    # choice = 'glacier1'
    choice = None

    summary = True
    # summary = False

    def print_location(_place):
        print(f"{_place} --------------------------------------------------------------------------")
        func(Location(_place, *_statistical_circle(CLUSTER_POINTS[CLUSTER_CENTER_MAP[_place]])))

    data = []
    for place, cluster_center in CLUSTER_CENTER_MAP.items():
        if choice is None or choice == place:
            if summary:
                loc = Location(place, *_statistical_circle(CLUSTER_POINTS[CLUSTER_CENTER_MAP[place]]))
                row = [place]
                use_center_factor = use_size_factor = False
                f = loc.first_by_score()
                row.append(f.get_place_name() if f else '-')

                use_size_factor = True
                f = loc.first_by_score()
                row.append(f.get_place_name() if f else '-')

                use_size_factor = False
                use_center_factor = True
                f = loc.first_by_score()
                row.append(f.get_place_name() if f else '-')

                use_size_factor = True
                f = loc.first_guess_places_first()
                row.append(f.get_place_name() if f else '-')

                use_size_factor = True
                f = loc.first_guess()
                row.append(f.get_place_name() if f else '-')

                data.append(row)
            else:
                print_location(place)

    if summary:
        print(tabulate.tabulate(data, headers=['Place', 'Score', 'Score*SF', 'Score*CF', 'First places gplaces', 'First places geocode']))

