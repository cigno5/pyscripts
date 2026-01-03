from datetime import datetime
import re

VARS_RE = re.compile(r"(?P<prefix>[\s\-_]+)?(\{(?P<var>\w+)(:(?P<format>\w+))?\})")

VARS = {
    'datetime': lambda pic, fmt: datetime.strftime(pic.get_date_time(), fmt),
    'date': lambda pic, fmt: datetime.strftime(pic.get_date_time(), fmt),
    'time': lambda pic, fmt: datetime.strftime(pic.get_date_time(), fmt),
    'day': lambda pic, _=None: datetime.strftime(pic.get_date_time(), "%d"),
    'month': lambda pic, fmt: datetime.strftime(pic.get_date_time(), fmt),
    'year': lambda pic, _=None: datetime.strftime(pic.get_date_time(), "%Y"),
    'sequence': lambda pic, _=None: f"{pic.get_sequence_number():02d}" if pic.get_sequence_number() else None,
    'place': lambda pic, _=None: pic.get_place_name(),
}

VARS_FORMAT = {
    'datetime': {
        'extended': "%Y-%m-%dT%H:%M:%S",
        'compact': "%Y%m%dT%H%M%S",
        '$default': 'compact'
    },
    'date': {
        'extended': "%Y-%m-%d",
        'compact': "%Y%m%d",
        '$default': 'compact'
    },
    'time': {
        'extended': "%H:%M:%S",
        'compact': "%H%M%S",
        '$default': 'compact'
    },
    'month': {
        'simple': "%m",
        'name': "%B",
        '$default': 'simple'
    }
}

class P:
    def __init__(self, _datetime, sequence, place):
        self.datetime = _datetime
        self.sequence = sequence
        self.place = place

    def get_date_time(self):
        return self.datetime

    def get_sequence_number(self):
        return self.sequence

    def get_place_name(self):
        return self.place


dt = datetime(2023, 3, 15, 14, 30, 0)


def parse_format(template, p):
    m = VARS_RE.search(template)
    while m:
        _var = m.group('var')
        _fmt = m.group('format')
        _prefix = m.group('prefix')

        print(f"found {_var}:{_fmt} with prefix {_prefix}")

        if _var in VARS:
            if _fmt:
                if _var in VARS_FORMAT and _fmt in VARS_FORMAT[_var]:
                    _fmt = VARS_FORMAT[_var][_fmt]
                else:
                    raise ValueError(f"Unknown format {_fmt} for variable {_var}")
            else:
                if _var in VARS_FORMAT:
                    _fmt = VARS_FORMAT[_var][VARS_FORMAT[_var]['$default']]

            replacement = VARS[_var](p, _fmt)
            if replacement:
                template = template.replace(m.group(0), f"{_prefix if _prefix else ''}{replacement}", 1)
            else:
                template = template.replace(m.group(0), "", 1)
        else:
            raise ValueError(f"Unknown variable: {_var}")

        m = VARS_RE.search(template)

    return template

_pattern = '{year}/{month} - {month:name}/{day} - {place}/IMG_{datetime}_{sequence}'

print(parse_format(_pattern, P(datetime(2023, 3, 15, 14, 30, 0), 5, 'New York')))
print(parse_format(_pattern, P(datetime(2023, 3, 15, 14, 30, 0), None, 'New York')))
print(parse_format(_pattern, P(datetime(2023, 3, 15, 14, 30, 0), None, None)))
print(parse_format(_pattern, P(datetime(2023, 3, 15, 14, 30, 0), 5, None)))
