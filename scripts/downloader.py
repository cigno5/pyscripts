"""
Downloader using clipboard listener

Things to implement
- clear list with key press
- sort downloads first
- don't download twice a file already downloaded
"""
import argparse
import collections
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from enum import Enum
import tabulate

import clipboard
import gi
import requests

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk

downloads = []
download_urls = set()
fn_re = re.compile(r"(?i)filename=(?P<fn>.+)[\s$]?")


class DStatus(Enum):
    Queued = 1
    Skipped = 2
    Downloading = 3
    Completed = 4
    Error = 5


Meta = collections.namedtuple('Meta', 'id,status,size,downloaded,progress,filename')


def _log(*xargs):
    if args.verbose:
        print(*xargs)


def _file_size(size_in_bytes):
    units = ['b', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    while size_in_bytes >= 1024 and unit_index < len(units) - 1:
        size_in_bytes /= 1024.0
        unit_index += 1
    return f"{size_in_bytes:.1f} {units[unit_index]}"


class Download:
    def __init__(self, url):
        self.id = len(downloads)
        self.url = url
        self.downloaded_bytes = 0
        self.file_size = 0
        self.file_name = ""
        self.status = DStatus.Queued

    def perform_download(self):
        url = self.url
        try:
            response = requests.head(url)
            self.file_size = int(response.headers.get('content-length', 0))

            _fn = response.headers.get('Content-Disposition', None)
            if _fn:
                _m = fn_re.search(_fn)
                if _m:
                    _fn = _m.group(1)
            else:
                _fn = url.split('/')[-1]
            self.file_name = _fn
            print(self.file_name)

            if self.file_size >= min_size:
                _file_name = datetime.now().strftime("%Y%m%dT%H%M%S_") + self.file_name \
                    if args.prefix_time \
                    else self.file_name

                _tmp_file_name = f".{_file_name}"

                tmp_output_file = os.path.join(output_dir, _tmp_file_name)
                output_file = os.path.join(output_dir, _file_name)

                self.status = DStatus.Downloading
                with open(tmp_output_file, 'wb') as f:
                    response = requests.get(url, stream=True)
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
                            self.downloaded_bytes += len(chunk)
                os.rename(tmp_output_file, output_file)
                self.status = DStatus.Completed
            else:
                self.status = DStatus.Skipped
        except Exception as e:
            _log(f"Error downloading {url}: {e}")
            self.status = DStatus.Error

    def meta(self):
        progress = int((self.downloaded_bytes / self.file_size) * 100) if self.file_size > 0 else 0
        return Meta(self.id,
                    self.status.name,
                    _file_size(self.file_size),
                    _file_size(self.downloaded_bytes),
                    f"{progress}%",
                    self.file_name)


def _parse_size(str_size):
    m = re.match(r"^(\d+)([mMgGkK])?$", str_size)
    if m:
        _u = (m.group(2) or "m").lower()
        _m = 1024 if _u == 'k' else 1024 * 1024 if _u == 'm' else 1024 * 1024 * 1024
        return int(m.group(1)) * _m
    else:
        raise ValueError("Not valid format for size '%s'" % str_size)


# def download_file(url):
#     try:
#         response = requests.head(url)
#         file_size = int(response.headers.get('content-length', 0))
#         if file_size >= min_size:
#             file_name = url.split('/')[-1]
#
#             if args.prefix_time:
#                 output_file = os.path.join(output_dir, datetime.now().strftime("%Y-%m-%dT%H.%M.%S") + ' - ' + file_name)
#             else:
#                 output_file = os.path.join(output_dir, file_name)
#
#             print(f"Downloading {file_name} ({file_size} bytes)...")
#             with open(output_file, 'wb') as f:
#                 response = requests.get(url, stream=True)
#                 downloaded_bytes = 0
#                 for chunk in response.iter_content(chunk_size=1024):
#                     if chunk:
#                         f.write(chunk)
#                         downloaded_bytes += len(chunk)
#                         progress = int((downloaded_bytes / file_size) * 100)
#                         print(f"\rProgress: {progress}%   ", end='', flush=True)
#             print(f"{file_name} downloaded")
#         else:
#             print(f"Skipping {url} as it doesn't meet size criteria")
#     except Exception as e:
#         print(f"Error downloading {url}: {e}")


def download_generator(url):
    d = Download(url)
    download_urls.add(url)
    downloads.append(d)
    return (d.perform_download,)


def download_monitor():
    while True:
        if len(downloads) > 0:
            print("\033c", end="", flush=True)
            print(tabulate.tabulate([Meta._fields] + [m.meta() for m in downloads]))

        time.sleep(5)


def monitor_download():
    with ThreadPoolExecutor(max_workers=args.workers) as executor, ThreadPoolExecutor(max_workers=1) as monitor:
        monitor.submit(download_monitor)

        # parser = RequestParser(executor)
        urls_finder = re.compile(
            r"https?://(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+\.~#?&//=]*)")

        def clipboard_listener(*xargs):
            request_text = clip.wait_for_text()
            if request_text:
                _log("Request text: %s" % request_text)
                for url_match in urls_finder.finditer(request_text):
                    url = url_match.group(0)
                    if url not in download_urls:
                        executor.submit(*download_generator(url))
            else:
                _log("Not a text request")

        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.connect('owner-change', clipboard_listener)
        Gtk.main()


def direct_download():
    urls = clipboard.paste().split() if clipboard.paste() else sys.stdin.readlines()
    # for url in urls:
    #     download_file(url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--dest', help='Directory to where download files, default is cwd')
    parser.add_argument('-t', '--prefix-time', action='store_true',
                        help='Prefix filenames with date and time')
    parser.add_argument('-s', '--size',
                        help='Download only bigger than size (format dd[K|M|G]), default is in MB')
    parser.add_argument('-w', '--workers', type=int, default=3,
                        help='Number of maximum workers')
    parser.add_argument('-c', '--clipboard', action='store_true',
                        help='Parse directly from clipboard and exit')
    parser.add_argument('-v', '--verbose', action='store_true', help='Log requests')

    args = parser.parse_args()

    # position validation
    output_dir = args.dest if args.dest else os.getcwd()
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # min size
    min_size = _parse_size(args.size) if args.size else 0

    if args.clipboard:
        direct_download()
    else:
        monitor_download()
