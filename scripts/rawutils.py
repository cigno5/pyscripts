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


def _run_on_target(func, recursive=False):
    target = os.path.expanduser(args.target)
    if not os.path.isabs(target):
        target = os.path.join(os.getcwd(), target)
    assert os.path.exists(target), "target %s doesn't exists" % target

    if os.path.isdir(target):
        def _exec():
            if os.path.isfile(file) and len([e for e in args.ext if file.lower().endswith(e.lower())]) > 0:
                func(os.path.join(target, file))

        if recursive:
            for root, dirs, files in os.walk(target):
                for file in [os.path.join(root, i) for i in sorted(files)]:
                    _exec()
        else:
            for file in [os.path.join(target, i) for i in sorted(os.listdir(target))]:
                _exec()

    elif os.path.isfile(target):
        func(target)
    else:
        raise ValueError("target %s is not valid" % target)


def _id(file):
    return "%i%s" % (
        os.stat(file).st_size,
        get_date(file).strftime("%Y%m%dT%H%M%S")
    )


def _has_xmp(file):
    n = os.path.splitext(os.path.basename(file))[0]
    for f in os.listdir(os.path.dirname(file)):
        if f.startswith(n) and f.lower().endswith(".xmp"):
            return True
    return False


def rename():
    index = {}

    def _file_name(f):
        return f if args.dry_run else os.path.basename(f)

    def _rename(source):
        if _has_xmp(source):
            print('Already processed picture %s --> ignored' % (_file_name(source)))
            return

        date = get_date(source)
        if date is None:
            print('Missing Exif data for picture %s --> ignored' % (_file_name(source)))
            return

        source_id = _id(source)
        if source_id in index:
            if args.delete_duplicates:
                print('Duplicated picture %s --> deleted' % (_file_name(source)))
                if not args.dry_run:
                    os.remove(source)
            else:
                print('Duplicated picture %s --> ignored' % (_file_name(source)))
            return

        def _n():
            return "{prefix}_{datetime}{suffix}{ext}".format(
                prefix=args.prefix if args.prefix else "IMG",
                datetime=date.strftime("%Y%m%dT%H%M%S"),
                suffix='' if dups == 0 else "-%i" % dups,
                ext=os.path.splitext(source)[-1]
            )

        dups = 0

        if os.path.basename(source) == _n():
            print('Picture %s already renamed' % _file_name(source))
            index[source_id] = {
                "source": source,
                "destination": source
            }
        else:
            for dups in range(0, 100):
                dest = os.path.join(os.path.dirname(source), _n())
                if not os.path.exists(dest):
                    print("Picture %s ---> %s" % (_file_name(source), _file_name(dest)))
                    if not args.dry_run:
                        os.rename(source, dest)
                    index[source_id] = {
                        "source": source,
                        "destination": dest
                    }
                    break
    _run_on_target(_rename, args.recursive)


def inspect():
    def _inspect(file):
        print("file %s %s" % (file, "-" * 30))
        tags = piexif.load(file)
        for k, v in tags.items():
            if type(v) == bytes:
                print("   Area %s: binary" % k)
            elif v is None:
                print("   Area %s: empty" % k)
            else:
                print("   Area %s" % k)
                for k2, v2 in v.items():
                    print("      %s: %s" % (k2, 'binary?' if len(str(v2)) > 100 else v2))
    _run_on_target(_inspect)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers()

    rename_parser = subparsers.add_parser("rename", help="Rename RAW files")
    rename_parser.set_defaults(command="rename")
    rename_parser.add_argument("target", help="File or directory to process")
    rename_parser.add_argument("--dry-run", action="store_true", help="Doesn't rename anything")
    rename_parser.add_argument("--prefix")
    rename_parser.add_argument("--ext", type=str, nargs="+", default=["cr2"])
    rename_parser.add_argument("--recursive", action="store_true", help="Check recursively in sub folders")
    rename_parser.add_argument("-d", "--delete-duplicates", action="store_true")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect RAW files")
    inspect_parser.set_defaults(command="inspect")
    inspect_parser.add_argument("target", help="File or directory to process")
    inspect_parser.add_argument("--ext", type=str, nargs="+", default=["cr2"])

    args = parser.parse_args()

    if args.command == 'rename':
        rename()
    elif args.command == 'inspect':
        inspect()