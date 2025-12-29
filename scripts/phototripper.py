import argparse
import json
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from collections import namedtuple
from datetime import datetime
from functools import reduce
from math import radians, asin, sqrt, cos, sin, pi, exp, log

import googlemaps
import requests
import tabulate
from unidecode import unidecode

from _common import load_configuration

from _tripper.common import Context, LocationSettings, LoggingSettings, FileSettings
from _tripper.location import GeoTraits, PictureLocation
from _tripper.picture import PictureInfo, PictureCluster

SUPPORTED_RAW_EXT = ["arw"]

SummaryRow = namedtuple("SummaryRow", 'file, date, cluster, place, new_folder, new_filename, moved_files')

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


def collect():
    def add_picture_file(picture_file):
        logging.debug(f"Adding picture file {os.path.basename(picture_file)}")
        picture = PictureInfo(picture_file)

        all_pictures.append(picture)

        if picture.has_latlon():
            cluster_found = False
            for cluster in geo_clusters:
                if cluster.is_in_range(picture):
                    cluster.add_picture(picture)
                    logging.debug(f" > picture falls in cluster {cluster.name} "
                                  f"with center {cluster.center} "
                                  f"together with {len(cluster.pictures)} pictures")
                    cluster_found = True
                    break

            if not cluster_found:
                cluster = PictureCluster(f"cluster{len(geo_clusters) + 1}", picture)
                geo_clusters.append(cluster)
                logging.debug(f" > created new cluster {cluster.name} with center {cluster.center}")

    # collects all pictures and read their properties
    logging.info("Collecting pictures...")
    for _root, _dirs, _files in os.walk(search_dir, topdown=True):
        logging.info(f"Scanning {_root} ({len(_files)} files)...")
        _dirs.sort()
        _files.sort()
        for _pic_file in [os.path.join(_root, f) for f in _files if f[-3:].lower() in SUPPORTED_RAW_EXT]:
            if not args.filter or args.filter in _pic_file:
                logging.debug(f" > {_pic_file[len(_root):]}")
                add_picture_file(_pic_file)

        if not args.recursive:
            break


def move():
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

    _pict_counter = _checkpoint_counter = 0
    _checkpoint_start = time.perf_counter()

    logging.info(f"Loading pictures metadata with location strategy {context.location_settings.strategy}...")
    for info in all_pictures:
        _pict_counter += 1
        _checkpoint_counter += 1
        if _checkpoint_counter > 50 and time.perf_counter() - _checkpoint_start > 10:
            _checkpoint_start = time.perf_counter()
            _checkpoint_counter = 0
            logging.info(f"Processing pictures ({_pict_counter}/{len(all_pictures)})...")

        if info.cluster is None or context.location_settings.strategy == 'none':
            info.get_place_name = place_none
        else:
            _location = next((_l for _l in locations if _l.cluster == info.cluster), None)
            if _location is None:
                _location = PictureLocation(info.cluster)
                locations.append(_location)
            info.get_place_name = place_full_strategy

        day = datetime.strftime(info.get_date_time(), "%d")
        date = datetime.strftime(info.get_date_time(), "%Y-%m-%d_T%H:%M:%S")
        suffix = f"_{info.get_sequence_number():02d}" if info.get_sequence_number() else ""
        place = info.get_place_name()

        destination_folder = os.path.join(dest_dir, f"{day} - {place}" if place else day)
        destination_basename = f"IMG_{date}{suffix}"

        if not args.dry_run:
            os.makedirs(destination_folder, exist_ok=True)

        moved_files = info.move_files(destination_folder, destination_basename)

        summary_rows.append(
            SummaryRow(
                os.path.basename(info.file),
                date,
                info.cluster.name if info.cluster else None,
                place,
                destination_folder[len(dest_dir):],
                destination_basename,
                len(moved_files)))


def print_summary():
    logging.debug('\nSummary ------------------------------------------------------------------------------------------')
    logging.debug(
        tabulate.tabulate(
            summary_rows,
            headers=SummaryRow._fields,
            tablefmt='pipe'))

    SubSummaryRow = namedtuple('SubSummaryRow', 'cluster_name, place, date, moved_files')
    sub_summary_rows = []

    _summary_recap = {}
    _cluster_to_place = {}

    for summary_row in summary_rows:
        _date = summary_row.date[0:10]
        if summary_row.cluster not in _summary_recap:
            _summary_recap[summary_row.cluster] = {}

        if _date not in _summary_recap[summary_row.cluster]:
            _summary_recap[summary_row.cluster][_date] = 0

        _summary_recap[summary_row.cluster][_date] += summary_row.moved_files

        if summary_row.cluster not in _cluster_to_place:
            _cluster_to_place[summary_row.cluster] = summary_row.place

    for cluster, dates in _summary_recap.items():
        _f = True
        for date, counter in dates.items():
            if _f:
                sub_summary_rows.append(SubSummaryRow(cluster, _cluster_to_place[cluster], date, counter))
            else:
                sub_summary_rows.append(SubSummaryRow('', '', date, counter))
            _f = False

    logging.info('\nSummary recap ------------------------------------------------------------------------------------')
    logging.info(
        tabulate.tabulate(
            sub_summary_rows,
            headers=SubSummaryRow._fields, tablefmt="pipe"))


def check():
    # initial checks
    logging.debug("Checking pre-requisites...")
    if not shutil.which("exiftool"):
        raise ValueError("Exiftool is not found in this system")
    
    if args.rename_only and args.destination:
        raise ValueError("Cannot specify both --rename-only and --destination options")


def initialize_context():
    loc_settings = LocationSettings(
        'none' if args.rename_only else 'full', 
        args.search_radius, 
        args.cache if args.cache else tempfile.gettempdir()
    )

    logging_settings = LoggingSettings(
        args.verbose,
        args.summary,
        args.debug
    )

    file_settings = FileSettings(
        search_dir,
        args.recursive,
        dest_dir,
        args.dry_run,
        args.rename_only
    )

    _ctx = Context(
        loc_settings,
        logging_settings,
        file_settings,
        gmaps,
        api_key
    )

    Context.set(_ctx)

    return _ctx


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    file_group = parser.add_argument_group('File options')
    file_group.add_argument('-s', "--search-dir", help="Search directory")
    file_group.add_argument('-d', "--destination", help="Destination directory")
    file_group.add_argument('-f', '--filter', help="Filter files by substring match")
    file_group.add_argument("--recursive", action='store_true', help="Scan recursively files from root directory")
    file_group.add_argument("--rename-only", action='store_true', help="Only renames files (without moving them)")

    log_group = parser.add_argument_group('Logging options')
    log_group.add_argument("--verbose", action='store_true', help="Logs more")
    log_group.add_argument('--summary', action='store_true', help="Show summary")
    log_group.add_argument("--dry-run", action='store_true', help="Don't move/rename files")

    loc_group = parser.add_argument_group('Location service')
    loc_group.add_argument("--search-radius", help="Search radius", type=int, default=3000)
    loc_group.add_argument("--cache", help="JSON service cache folder (default is temp folder)")
    loc_group.add_argument("--debug", action='store_true', help="Debug geocoding decisions")

    args = parser.parse_args()

    logging.basicConfig(
        format='%(message)s',
        level=logging.DEBUG if args.verbose else logging.INFO)
    logging.getLogger("geopy").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # performs checks
    check()

    # Prepare settings
    search_dir = os.path.abspath(os.path.expanduser(args.search_dir)) if args.search_dir else os.getcwd()
    assert os.path.isdir(search_dir) and os.path.exists(search_dir), "Search directory is invalid or it doesn't exist"
    dest_dir = os.path.abspath(os.path.expanduser(args.destination)) if args.destination else search_dir

    logging.debug("Initializing Phototripper...")
    api_key = load_configuration('.pyscripts-google.ini')['google']['api-key']
    gmaps: googlemaps.Client = googlemaps.Client(api_key)

    all_pictures: list[PictureInfo] = []
    geo_clusters: list[PictureCluster] = []
    locations: list[PictureLocation] = []
    summary_rows: list[SummaryRow] = []

    context: Context = initialize_context()

#     logging.info(f"""=====================================================================
# Phototripper, a useless photo organizer!

# Search directory.......: {args.search_dir}
# Recursive scan.........: {'yes' if args.recursive else 'no'}
# Destination directory..: {dest_dir}

# Verbose mode...........: {'yes' if args.verbose else 'no'}
# Dry run................: {'yes' if args.dry_run else 'no'}

# Print summary..........: {'yes' if args.summary else 'no'}
# """)

    start_time = time.perf_counter()

    collect()
    move()

    if args.summary:
        print_summary()

    logging.info(f"Done in {time.perf_counter() - start_time:.3f} seconds")
