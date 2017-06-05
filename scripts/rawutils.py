#!/home/luca/dev/tools/miniconda3/envs/pyscripts/bin/python
import os

import piexif
import argparse
from PIL import Image
import datetime
import re


def get_date(file):
    tags = piexif.load(file)

    if '0th' in tags and piexif.ImageIFD.DateTime in tags['0th']:
        date = tags['0th'][piexif.ImageIFD.DateTime].decode('utf8')

        match = re.search("(\d{2,4}).(\d{1,2}).(\d{1,2}).*?(\d{1,2}).(\d{1,2}).(\d{1,2})", date)
        if match:
            year, month, day, h, m, s = [int(g) for g in match.groups()]
            return datetime.datetime(year=year, month=month, day=day,
                                     hour=h, minute=m, second=s)


def _run_target(func):
    target = os.path.expanduser(args.target)
    if not os.path.isabs(target):
        target = os.path.join(os.getcwd(), target)
    assert os.path.exists(target), "target %s doesn't exists" % target

    if os.path.isdir(target):
        for file in [os.path.join(target, i) for i in os.listdir(target)]:
            if os.path.isfile(file) and len([e for e in args.ext if file.lower().endswith(e.lower())]) > 0:
                func(os.path.join(target, file))

    elif os.path.isfile(target):
        func(target)
    else:
        raise ValueError("target %s is not valid" % target)


def rename():
    def _rename(source):
        date = get_date(source)

        def _n():
            return "{prefix}_{datetime}{suffix}{ext}".format(
                prefix=args.prefix if args.prefix else "IMG",
                datetime=date.strftime("%Y%m%dT%H%M%S"),
                suffix='' if dups == 0 else "-%i" % dups,
                ext=os.path.splitext(source)[-1]
            )

        for dups in range(0, 100):
            dest = os.path.join(os.path.dirname(source), _n())
            if not os.path.exists(dest):
                print("Rename %s to %s" % (os.path.basename(source), os.path.basename(dest)))
                if not args.dry_run:
                    os.rename(source, dest)
                break
    _run_target(_rename)

# def show_date():
#     _run_target(lambda source: print("%s --> %s" % (os.path.basename(source), str(get_date(source)))))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers()
    rename_parser = subparsers.add_parser("rename", help="Rename RAW files")
    rename_parser.set_defaults(command="rename")
    rename_parser.add_argument("target", help="File or directory to process")
    rename_parser.add_argument("--dry-run", action="store_true", help="Doesn't rename anything")
    rename_parser.add_argument("--prefix")
    rename_parser.add_argument("--ext", type=str, nargs="+", default=["cr2"])

    args = parser.parse_args()

    if args.command == 'rename':
        rename()
