import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import clipboard
import gi
import requests

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk


def _parse_size(str_size):
    m = re.match(r"^(\d+)([mMgGkK])?$", str_size)
    if m:
        _u = (m.group(2) or "m").lower()
        _m = 1024 if _u == 'k' else 1024 * 1024 if _u == 'm' else 1024 * 1024 * 1024
        return int(m.group(1)) * _m
    else:
        raise ValueError("Not valid format for size '%s'" % str_size)


def download_file(url):
    try:
        response = requests.head(url)
        file_size = int(response.headers.get('content-length', 0))
        if file_size >= min_size:
            file_name = url.split('/')[-1]

            if args.prefix_time:
                output_file = os.path.join(output_dir, datetime.now().strftime("%Y-%m-%dT%H.%M.%S") + ' - ' + file_name)
            else:
                output_file = os.path.join(output_dir, file_name)

            print(f"Downloading {file_name} ({file_size} bytes)...")
            with open(output_file, 'wb') as f:
                response = requests.get(url, stream=True)
                downloaded_bytes = 0
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)
                        progress = int((downloaded_bytes / file_size) * 100)
                        print(f"\rProgress: {progress}%   ", end='', flush=True)
            print(f"{file_name} downloaded")
        else:
            print(f"Skipping {url} as it doesn't meet size criteria")
    except Exception as e:
        print(f"Error downloading {url}: {e}")


def monitor_download():
    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        # parser = RequestParser(executor)
        urls_finder = re.compile(
            r"https?://(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+\.~#?&//=]*)")

        def clipboard_listener(*xargs):
            request_text = clip.wait_for_text()
            if request_text:
                print("Request text: %s" % request_text)
                for url_match in urls_finder.finditer(request_text):
                    # executor.submit(download, url_match.group(0))
                    executor.submit(download_file, url_match.group(0))
            else:
                print("Not a text request")

        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.connect('owner-change', clipboard_listener)
        Gtk.main()


def direct_download():
    urls = clipboard.paste().split() if clipboard.paste() else sys.stdin.readlines()
    for url in urls:
        download_file(url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--dest', help='Directory to where download files, default is cwd')
    parser.add_argument('-t', '--prefix-time', action='store_true',
                        help='Prefix filenames with date and time')
    parser.add_argument('-s', '--size',
                        help='Download only bigger than size (format dd[K|M|G]), default is in MB')
    parser.add_argument('-p', '--parallel', type=int, default=3,
                        help='Number of maximum parallel downloads')
    parser.add_argument('-c', '--clipboard', action='store_true',
                        help='Parse directly from clipboard and exit')

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
