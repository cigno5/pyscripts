import argparse
import json
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
from collections import namedtuple
from datetime import datetime
from functools import reduce
from math import radians, asin, sqrt, cos, sin, pi, exp, log

import googlemaps
import requests
import tabulate
from unidecode import unidecode

from _common import load_configuration

SUPPORTED_RAW_EXT = ["arw"]
EARTH_RADIUS = 6371000

AddressSegment = namedtuple("AddressSegment", "name, types")


class PictureInfo:
    T_DATE_TIME_ORIGINAL = "DateTimeOriginal"
    T_SEQUENCE_NUMBER = "SequenceNumber"
    T_GPS_LATITUDE = "GPSLatitude"
    T_GPS_LONGITUDE = "GPSLongitude"

    TAGS = {
        T_DATE_TIME_ORIGINAL: lambda x: datetime.strptime(x, "%Y:%m:%d %H:%M:%S"),
        T_SEQUENCE_NUMBER: lambda x: int(x),
        T_GPS_LATITUDE: lambda x: float(x),
        T_GPS_LONGITUDE: lambda x: float(x),
    }

    TAG_RE = re.compile(r"(?P<tag>\w+)\s*:\s*(?P<value>.+)$")

    def __init__(self, file):
        self.file = file

        # exiftool -n -DateTimeOriginal -SequenceNumber -GPSLatitude -GPSLongitude
        out = subprocess.check_output(["exiftool", "-n", "-s",
                                       *['-' + t for t in PictureInfo.TAGS.keys()],
                                       file])

        self.tags = {}
        for line in out.decode('utf-8').splitlines():
            tag, value = PictureInfo.TAG_RE.search(line).groups()
            self.tags[tag] = PictureInfo.TAGS[tag](value)

        self.sequence = None
        if PictureInfo.T_SEQUENCE_NUMBER in self.tags and self.tags[PictureInfo.T_SEQUENCE_NUMBER] > 0:
            self.sequence = self.tags[PictureInfo.T_SEQUENCE_NUMBER]

        self.get_place_name = None

    def get_extension(self):
        return os.path.splitext(self.file)[-1]

    def get_date_time(self):
        return self.tags[PictureInfo.T_DATE_TIME_ORIGINAL]

    def get_sequence_number(self):
        return self.sequence

    def has_latlon(self):
        return PictureInfo.T_GPS_LATITUDE in self.tags and PictureInfo.T_GPS_LONGITUDE in self.tags

    def get_latlon(self):
        return (self.tags[PictureInfo.T_GPS_LATITUDE],
                self.tags[PictureInfo.T_GPS_LONGITUDE]) if self.has_latlon() else None

    def get_distance(self, latlon1):
        return _haversine(self.get_latlon(), latlon1) if self.has_latlon() else None

    def __str__(self):
        return (f"File: {os.path.basename(self.file)}; "
                f"Sequence: {self.sequence}; "
                f"Geolocation: {'yes' if self.has_latlon() else 'no'};")

    def __hash__(self):
        return hash(self.file)

    def __eq__(self, other):
        return self.file == other.file


class PictureCluster:
    def __init__(self, name, first_picture: PictureInfo = None):
        self.name = name
        self.center = (0, 0)
        self.radius = 0
        self.pictures: set[PictureInfo] = set()
        if first_picture:
            self.add_picture(first_picture)

    def is_in_range(self, picture: PictureInfo) -> bool:
        return picture.get_distance(self.center) < max(collector.search_radius, self.radius)

    def contains(self, picture: PictureInfo) -> bool:
        return picture in self.pictures

    def add_picture(self, picture: PictureInfo):
        self.pictures.add(picture)

        # compute new center
        _new_center = reduce(lambda l1, l2: (l1[0] + l2[0], l1[1] + l2[1]), [i.get_latlon() for i in self.pictures])
        _new_center = (_new_center[0] / len(self.pictures), _new_center[1] / len(self.pictures))
        self.center = _new_center

        # compute new statistical circle (to cover the area of all pictures)

        if len(self.pictures) == 1:
            self.radius = collector.search_radius / 10
        else:
            _distances = [_haversine(self.center, p.get_latlon()) for p in self.pictures]

            # 3. Use 2 Standard Deviations for the radius (covers ~95% of points)
            # This ignores extreme outliers but covers the main group well
            _avg_dist = sum(_distances) / len(_distances)
            _variance = sum((d - _avg_dist) ** 2 for d in _distances) / len(_distances)
            _std_dev = sqrt(_variance)

            # Radius = Average Distance + 2 * Standard Deviation
            # This creates a circle that 'approximately' covers everything.
            self.radius = _avg_dist + (2 * _std_dev)


class _IntersectionAnalysis:
    def __init__(self, circle_c, circle_r, rect_ne, rect_sw):
        self.circle_center = circle_c
        self.circle_radius = circle_r

        num_simulations = 1000
        rect_se = (rect_sw[0], rect_ne[1])
        rect_nw = (rect_ne[0], rect_sw[1])

        # --- PART A: CHECK CONTAINMENT ---
        corners = [rect_sw, rect_se, rect_ne, rect_nw]

        rect_inside_circle = all(_haversine(circle_c, latlon) <= circle_r for latlon in corners)

        # 2. Check if Circle is fully inside Rectangle
        # Logic: Center is inside rect AND distance to the closest edge >= radius
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
        sigma = sqrt((self.circle_radius / 2) ** 2 / (-2 * log(min_score_at_radius)))

        # 2. Calculate Gaussian factor
        return 1 + exp(-(self.distance_to_center ** 2) / (2 * sigma ** 2))
        # sigma = 5
        # return math.exp(-(self.distance_to_center ** 2) / (2 * sigma ** 2))

    def __str__(self):
        return f"Status: {self.status}; Circle area: {self.circle_area}; Rect area: {self.rect_area}; Intersection area: {self.intersection_area}"


class GeoTraits:
    T_POI = 'point_of_interest'
    T_LOCALITY = 'locality'
    T_TOURIST_ATTRACTION = 'tourist_attraction'
    T_ROUTE = 'route'

    INTERESTING_TYPES = [T_TOURIST_ATTRACTION, T_POI, T_LOCALITY]

    def __init__(self, center, radius, geo_service, geo_data):
        self.service = geo_service
        if geo_service == 'geocode':
            _t_address = 'formatted_address'
            _t_address_components = 'address_components'
            _lat, _lon = 'lat', 'lng'
            _high, _low = 'northeast', 'southwest'
            _viewport = geo_data['geometry']['viewport']
            _t_long_name = 'long_name'
            _t_short_name = 'short_name'
        elif geo_service == 'gplaces':
            _t_address = 'formattedAddress'
            _t_address_components = 'addressComponents'
            _lat, _lon = 'latitude', 'longitude'
            _high, _low = 'high', 'low'
            _viewport = geo_data['viewport']
            _t_long_name = 'longText'
            _t_short_name = 'shortText'
        else:
            raise NotImplementedError(f"Service {geo_service} not implemented")

        self.center = center
        self.radius = radius
        self.address = geo_data[_t_address]
        self.types = geo_data['types']

        self.primary_type = geo_data['primaryType'] if geo_service == 'gplaces' and 'primaryType' in geo_data else None
        self.display_name = geo_data['displayName']['text'] if geo_service == 'gplaces' else geo_data[_t_address]

        self.viewport = (_viewport[_high][_lat], _viewport[_high][_lon]), (_viewport[_low][_lat], _viewport[_low][_lon])

        self.address_chain: list[AddressSegment] = [
            AddressSegment(
                c[_t_short_name] if _t_short_name in c else c[_t_long_name],
                c['types'] if 'types' in c else []
            )
            for c in geo_data[_t_address_components]
        ]

        self.intersection_analysis = _IntersectionAnalysis(self.center, self.radius, self.viewport[0],
                                                           self.viewport[1])

    def get_place_score(self, use_size_factor, use_center_factor):
        def x_score(base_score, _type):
            if _type in GeoTraits.INTERESTING_TYPES:
                return base_score * 10 * (len(GeoTraits.INTERESTING_TYPES) - GeoTraits.INTERESTING_TYPES.index(_type))
            else:
                return 0

        score = x_score(1000, self.primary_type)
        for _type in self.types:
            score += x_score(100, _type)

        for _address_comp in self.address_chain:
            for _type in _address_comp.types:
                if _type in GeoTraits.INTERESTING_TYPES:
                    score += x_score(10, _type)

        if use_size_factor:
            score *= self.intersection_analysis.get_size_factor()

        if use_center_factor:
            score *= self.intersection_analysis.get_center_factor()

        return score

    def get_place_name(self):
        def _p(_tp):
            return next((c.name for c in self.address_chain if _tp in c.types), None)

        return next((n for n in [self.display_name] if n and self.primary_type in GeoTraits.INTERESTING_TYPES),
                    next((_p(it) for it in GeoTraits.INTERESTING_TYPES if it in self.types and _p(it)),
                         next((_p(it) for it in GeoTraits.INTERESTING_TYPES if _p(it)), None)))

    def _is_something(self, tp):
        return tp in self.types or tp == self.primary_type

    def __str__(self):
        return f"""{self.service} ----------------------------------------------------------------------
  - Place name........: {self.get_place_name()}
  - Place score.......: {self.get_place_score(False, False)}
  - Place score SF....: {self.get_place_score(True, False)}
  - Place score CF....: {self.get_place_score(False, True)}
  - Place score SF+CF.: {self.get_place_score(True, True)}
  - Intersection analysis
    - Size factor.....: {self.intersection_analysis.get_size_factor()}
    - Center factor...: {self.intersection_analysis.get_center_factor()}
  - Address...........: {self.address}
  - Primary type......: {self.primary_type}
  - Types.............: {', '.join(self.types)}
  - Geometry..........: {self.viewport}
  - Address Chain.....:
""" + '\n'.join([f"    - {str(c)}" for c in self.address_chain])


class PictureLocation:
    def __init__(self, cluster: PictureCluster):
        self.cluster = cluster

        self.geocode_traits = _geo_decode(cluster, 'geocode')
        self.gplaces_traits = _geo_decode(cluster, 'gplaces')

    def first_by_service(self, service) -> GeoTraits:
        def flt(t: GeoTraits):
            return t.get_place_name() is not None

        _traits = None

        if service == 'gplaces':
            _traits = self.gplaces_traits

        if service == 'geocode':
            _traits = self.geocode_traits

        return next(iter(filter(flt, _traits)), None)

    def first_by_score(self, use_size_factor=False, use_center_factor=False, services=None) -> GeoTraits:
        def _srt(t: GeoTraits):
            return t.get_place_score(use_size_factor, use_center_factor)

        def _flt(t: GeoTraits):
            return _srt(t) > 0

        _traits = []
        if services is None or 'geocode' in services:
            _traits += self.geocode_traits
        if services is None or 'gplaces' in services:
            _traits += self.gplaces_traits

        return next(iter(sorted(filter(_flt, _traits), key=_srt, reverse=True)), None)


class PictureCollector:
    def __init__(self, search_radius=3000):
        self.search_radius = search_radius
        self.not_geo_pictures: set[PictureInfo] = set()
        self.geo_clusters: list[PictureCluster] = []
        self.locations: list[PictureLocation] = []

    def add_picture(self, picture: PictureInfo):
        if picture.has_latlon():
            cluster_found = False
            for cluster in self.geo_clusters:
                if cluster.is_in_range(picture):
                    cluster.add_picture(picture)
                    cluster_found = True
                    break

            if not cluster_found:
                self.geo_clusters.append(PictureCluster(f"cluster{len(self.geo_clusters) + 1}", picture))
        else:
            self.not_geo_pictures.add(picture)

    def build_picture_list(self, location_strategy='full'):
        self.locations = [PictureLocation(c) for c in self.geo_clusters]

        def place_none():
            return None

        def place_full_strategy():
            traits = [
                _location.first_by_service('gplaces'),
                _location.first_by_service('geocode'),
                _location.first_by_score(use_center_factor=True, use_size_factor=False)
            ]

            _places = list(dict.fromkeys([unidecode(t.get_place_name()) for t in traits if t]))
            return ", ".join(_places)

        for _info in self.not_geo_pictures:
            _info.get_place_name = place_none
            yield _info

        for _cluster in self.geo_clusters:
            _location = next((_l for _l in collector.locations if _l.cluster == _cluster), None)
            for _info in _cluster.pictures:
                _info.get_place_name = place_full_strategy
                yield _info

    def __add__(self, pict: PictureInfo):
        self.add_picture(pict)
        return self


def _haversine(latlon1, latlon2):
    d_lat = radians(latlon2[0] - latlon1[0])
    d_lon = radians(latlon2[1] - latlon1[1])

    a = sin(d_lat / 2) ** 2 + cos(radians(latlon1[0])) * cos(radians(latlon2[0])) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS * asin(sqrt(a))


def _rect_area(sw, ne):
    """Approximates area of a rectangle on Earth in m2."""
    # Height: Distance from SW lat to NE lat (along same longitude)
    height = _haversine(sw, ne)
    # Width: Distance from SW lon to NE lon (along middle latitude for better accuracy)
    mid_lat = (sw[0] + ne[0]) / 2
    width = _haversine((mid_lat, sw[1]), (mid_lat, ne[1]))
    return height * width


def _geo_decode(cluster: PictureCluster, service):
    assert service in ['geocode', 'gplaces', 'nominatim']

    conf = load_configuration('.pyscripts-google.ini')
    api_key = conf['google']['api-key']
    gmaps: googlemaps.Client = googlemaps.Client(api_key)

    _tmp_fld = os.path.join(tempfile.gettempdir(), 'phototripping')
    os.makedirs(_tmp_fld, exist_ok=True)

    _data_file = os.path.join(_tmp_fld, f'{cluster.center}-{service}.json')

    try:
        with open(_data_file, 'r') as df:
            data = json.load(df)

    except FileNotFoundError:
        with open(_data_file, 'w') as df:
            if service == 'geocode':
                data = gmaps.reverse_geocode(cluster.center)
            elif service == 'gplaces':
                headers = {
                    'Content-Type': 'application/json',
                    'X-Goog-Api-Key': api_key,
                    'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.addressComponents,'
                                        'places.primaryType,places.types,places.viewport'
                }

                json_data = {
                    'includedTypes': ['tourist_attraction', 'historical_landmark', 'locality',
                                      'administrative_area_level_1', ],
                    "maxResultCount": 10,
                    'locationRestriction': {
                        'circle': {
                            'center': {
                                'latitude': cluster.center[0],
                                'longitude': cluster.center[1],
                            },
                            'radius': max(cluster.radius, collector.search_radius),
                        },
                    },
                }

                r = requests.post('https://places.googleapis.com/v1/places:searchNearby', headers=headers,
                                  json=json_data)
                r.raise_for_status()
                data = r.json()['places']
            elif service == 'nominatim':
                raise NotImplementedError('Nominatim not implemented yet')

            json.dump(data, df)

    return [GeoTraits(cluster.center, cluster.radius, service, obj) for obj in data]


def _traits_to_geojson(cluster, traits):
    num_circle_points = 64
    # 1 deg lat is approx 111,320 meters
    meters_per_deg_lat = 111320

    def rect_feature(_geotraits: GeoTraits):
        ne_lat, ne_lon = _geotraits.viewport[0]
        sw_lat, sw_lon = _geotraits.viewport[1]

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
                "name": _geotraits.display_name,
                "description":
                    f"Size factor: {_geotraits.intersection_analysis.get_size_factor():.5f}; "
                    f"Size ratio: {_geotraits.intersection_analysis.get_size_ratio():.5f}; "
                    f"Center factor: {_geotraits.intersection_analysis.get_center_factor():.5f}",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": rect_coords
            }
        }

    def circle_feature():
        # Unpack coordinates (lat, lon)
        c_lat, c_lon = cluster.center
        # 1 deg lon depends on latitude: 111,320 * cos(lat)
        meters_per_deg_lon = 111320 * cos(radians(c_lat))

        circle_coords_ring = []
        for i in range(num_circle_points + 1):
            # Calculate angle in radians
            theta = radians(i * (360 / num_circle_points))

            # Calculate offset in degrees
            dx = (cluster.radius * cos(theta)) / meters_per_deg_lon
            dy = (cluster.radius * sin(theta)) / meters_per_deg_lat

            circle_coords_ring.append([c_lon + dx, c_lat + dy])

        return {
            "type": "Feature",
            "properties": {
                "name": f"Supposedly {cluster.name}",
                "radius_meters": cluster.radius,
                "center": [cluster.center[0], cluster.center[1]],
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
            *[rect_feature(geotrait) for geotrait in traits]
        ]
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("search_dir", help="Search directory")
    parser.add_argument('-d', "--destination", help="Destination directory")
    parser.add_argument('-f', '--filter')

    parser.add_argument('-r', "--recursive", action='store_true', help="Scan recursively files from root directory")
    parser.add_argument('-v', "--verbose", action='store_true', help="Logs more")

    parser.add_argument("--dry-run", action='store_true', help="Don't move/rename files")

    args = parser.parse_args()

    logging.basicConfig(
        format='%(message)s',
        level=logging.DEBUG if args.verbose else logging.INFO)
    logging.getLogger("geopy").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Main application
    search_dir = os.path.abspath(os.path.expanduser(args.search_dir))
    assert os.path.isdir(search_dir) and os.path.exists(search_dir), "Search directory is invalid or it doesn't exist"
    dest_dir = os.path.abspath(os.path.expanduser(args.destination)) if args.destination else search_dir

    logging.info(f'Scanning {args.search_dir}...')
    if args.destination:
        logging.info(f'Destination directory: {args.destination}')

    # initial checks
    if not shutil.which("exiftool"):
        raise ValueError("Exiftool is not found in this system")

    collector = PictureCollector()

    # collects all pictures and read their properties
    for _root, _dirs, _files in os.walk(search_dir):
        for picture_file in [os.path.join(_root, f) for f in _files if f[-3:].lower() in SUPPORTED_RAW_EXT]:
            if not args.filter or args.filter in picture_file:
                collector += PictureInfo(picture_file)

        if not args.recursive:
            break

    SummaryRow = namedtuple("SummaryRow", 'file, date, place, new_folder, new_filename')
    summary_rows = []

    for info in collector.build_picture_list(location_strategy='full'):
        day = datetime.strftime(info.get_date_time(), "%d")
        date = datetime.strftime(info.get_date_time(), "%Y-%m-%dT%H:%M:%S")
        suffix = f"_{info.get_sequence_number():02d}" if info.get_sequence_number() else ""
        place = info.get_place_name()

        new_folder = os.path.join(dest_dir, f"{day} - {place}" if place else day)
        new_filename = f"IMG_{date}{suffix}{info.get_extension()}"

        destination_file = os.path.join(new_folder, new_filename)

        summary_rows.append(SummaryRow(os.path.basename(info.file), date, place, new_folder, new_filename))

        # logging.info(f"file: {file} -> {destination_file}")
        # if not args.dry_run:
        #     os.makedirs(new_folder, exist_ok=True)
        #     if os.path.exists(destination_file):
        #         raise ValueError(f"Destination file already exists")
        #
        #     os.rename(file, destination_file)

    print(tabulate.tabulate(summary_rows, headers=SummaryRow._fields))
