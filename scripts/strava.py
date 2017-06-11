#!/home/luca/dev/tools/miniconda3/envs/pyscripts/bin/python

import http.server
import os
import socketserver
import webbrowser
from datetime import datetime
from multiprocessing import Process
from time import sleep
from urllib.parse import urlsplit, parse_qs

from stravalib import Client


class LogHandler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, request, client_address, server):
        super().__init__(request, client_address, server)
        self._server = None

    def do_GET(self):
        query = urlsplit(self.path).query
        params = parse_qs(query)
        if 'code' in params:
            code = params['code'][0]
            print(code)
            with open(".strava", 'w') as f:
                f.write(code)

            self.send_response(http.HTTPStatus.OK)
            self.end_headers()
            self.wfile.write(b'ok. code caught')

            _srv = self._server

            def _close():
                print("Ready to close...")
                sleep(5)
                print("Closing...")
                _srv.shutdown()
                print("closed...")

            Process(target=_close).start()

        else:
            self.send_response(http.HTTPStatus.BAD_REQUEST)
            self.end_headers()
            self.wfile.write(b'Sorry, code not found')


def auth_server():
    port = 8080
    handler = LogHandler

    with socketserver.TCPServer(("", port), handler) as httpd:
        print("serving at port", port)
        handler._server = httpd

        httpd.serve_forever()


def get_token(force=False):
    if force:
        os.remove('.strava')

    # TODO file must be placed in user directory or script directory
    if not os.path.exists('.strava'):
        Process(target=auth_server).start()
        sleep(5)
        print('woke up')

        webbrowser.open(client.authorization_url(client_id=CLIENT_ID,
                                                 redirect_uri='http://localhost:8080/authorized',
                                                 scope="view_private,write"))

    while not os.path.exists('.strava'):
        print("wait...")
        sleep(2)

    with open('.strava', 'r') as f:
        code = f.readline()

    return client.exchange_code_for_token(client_id=CLIENT_ID, client_secret=CLIENT_SECRET, code=code)


def _add_month(date):
    m = date.month + 1
    if m > 12:
        m = 1
        y = date.year + 1
    else:
        y = date.year
    return datetime(year=y, month=m, day=date.day)


def collect_activities(flt=None, flt_collectors=None, collectors=None):
    filtered_activities = list()

    start_date = datetime(2013, 1, 1)
    while start_date < datetime.now():
        end_date = _add_month(start_date)
        for activity in client.get_activities(before=end_date, after=start_date):
            if flt and flt(activity):
                filtered_activities.append(activity)
                if flt_collectors:
                    for c in flt_collectors:
                        c(activity)

            if collectors:
                for c in collectors:
                    c(activity)

        start_date = _add_month(start_date)

    return filtered_activities


def update_wrong_gear():
    get_token()

    all_gears = set()
    gears = set()
    types = set()
    distances = set()
    activities = collect_activities(flt=lambda _a: _a.gear_id == 'g2284462' and _a.start_date.year < 2017,
                                    flt_collectors=[lambda _a: types.add(_a.type),
                                                    lambda _a: distances.add(float(_a.distance)),
                                                    lambda _a: gears.add(_a.gear_id),
                                                    ],
                                    collectors=[lambda _a: all_gears.add(_a.gear_id)])

    print("total activities: %i" % len(activities))
    print("total distance: %f" % sum(distances, 0))
    print("types: " + str(types))
    print("all gears: " + str(all_gears))
    print("gears: " + str(gears))

    for a in activities:
        print("Updating id: %i; date %s; type %s " % (a.id, str(a.start_date), a.type))
        client.update_activity(a.id, gear_id="g1498034")

    print("Done.")


CLIENT_ID = 18401
CLIENT_SECRET = "b82e912a54c6efd49508ea021678d01705fcf438"
token = None
client = Client()

if __name__ == '__main__':
    update_wrong_gear()



