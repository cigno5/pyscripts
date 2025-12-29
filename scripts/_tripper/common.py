from collections import namedtuple
from math import radians, cos, sin, asin, sqrt

EARTH_RADIUS = 6371000

LocationSettings = namedtuple("LocationSettings", "strategy, search_radius, cache_dir")
LoggingSettings = namedtuple("LoggingSettings", "verbose, print_summary, debug")
FileSettings = namedtuple("FileSettings", "search_dir, recursive_search, dest_dir, dry_run, rename_only")

class Context:
    context: 'Context' = None

    def __init__(self, 
                 location_settings: LocationSettings,
                 logging_settings: LoggingSettings,
                 file_settings: FileSettings,
                 gmaps, api_key):
        
        self.location_settings: LocationSettings = location_settings
        self.logging_settings: LoggingSettings = logging_settings
        self.file_settings: FileSettings = file_settings
        self.gmaps = gmaps
        self.api_key = api_key

    @staticmethod
    def set(ctx: 'Context'):
        if Context.context is not None:
            raise RuntimeError("Context has already been initalized")
        Context.context = ctx

    @staticmethod
    def get() -> 'Context':
        if Context.context is None:
            raise RuntimeError("Context has not been initalized yet")
        return Context.context
    
def haversine(latlon1, latlon2):
    d_lat = radians(latlon2[0] - latlon1[0])
    d_lon = radians(latlon2[1] - latlon1[1])

    a = sin(d_lat / 2) ** 2 + cos(radians(latlon1[0])) * cos(radians(latlon2[0])) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS * asin(sqrt(a))
