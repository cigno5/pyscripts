import os
from collections import namedtuple

import piexif
import argparse
from PIL import Image
import datetime
import re


IMAGE_EXTS = ["cr2"]
DATE_TAGS = [piexif.ExifIFD.DateTimeOriginal, piexif.ImageIFD.DateTime]


def extract_date(file):
    tags = piexif.load(file)
    date_value = None
    for sub_tags in tags.values():
        for date_tag in DATE_TAGS:
            if date_tag in sub_tags:
                date_value = sub_tags[date_tag].decode('utf8')
                break
        if date_value:
            break

    return datetime.datetime.strptime(date_value, "%Y:%m:%d %H:%M:%S") if date_value else None


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
            if os.path.isfile(file) and len([e for e in IMAGE_EXTS if file.lower().endswith(e.lower())]) > 0:
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


def _get_xmp_files(file):
    n = os.path.splitext(os.path.basename(file))[0]
    return [f for f in os.listdir(os.path.dirname(file)) if f.startswith(n) and f.lower().endswith(".xmp")]


def rename():
    index = {}

    def _file_name(f):
        return f if args.dry_run else os.path.basename(f)

    def _rename(source):
        # if _has_xmp(source):
        #     print('Already processed picture %s --> ignored' % (_file_name(source)))
        #     return

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

        def new_name():
            return "{prefix}_{datetime}{suffix}{ext}".format(
                prefix=args.prefix if args.prefix else "IMG",
                datetime=date.strftime("%Y%m%dT%H%M%S"),
                suffix='' if dups == 0 else "-%i" % dups,
                ext=os.path.splitext(source)[-1]
            )

        dups = 0

        if os.path.basename(source) == new_name():
            print('Picture %s already renamed' % _file_name(source))
            index[source_id] = {
                "source": source,
                "destination": source
            }
        else:
            for dups in range(0, 100):
                dest = os.path.join(os.path.dirname(source), new_name())
                if not os.path.exists(dest):
                    print("Picture %s ---> %s" % (_file_name(source), _file_name(dest)))
                    if not args.dry_run:
                        os.rename(source, dest)

                    for xmp_file in _get_xmp_files(source):
                        print("   >> XMP %s ---> %s" % (_file_name(xmp_file), _file_name(xmp_file + ".xmp")))
                        # if not args.dry_run:
                        #     os.rename(source + ".xmp", dest + ".xmp")

                    index[source_id] = {
                        "source": source,
                        "destination": dest
                    }
                    break
    _run_on_target(_rename, args.recursive)


def new_rename():

    def side_file(file):
        lcase_file = file.lower()
        lcase_name = name.lower()
        lcase_ext = ext.lower()
        return lcase_file != "%s.%s" % (lcase_name, lcase_ext) and lcase_file.startswith(lcase_name)

    def find_images():
        def is_image(file):
            return os.path.splitext(file)[-1][1:].lower() in IMAGE_EXTS

        if os.path.isfile(target):
            for _image_file in [t for t in [target] if is_image(t)]:
                yield _image_file
        elif args.recursive:
            raise NotImplemented('Need to be re-implemented!')
            for root, dirs, files in os.walk(target):
                for _image_file in [f for f in sorted(files) if is_image(f)]:
                    yield os.path.join(root, _image_file)
        else:
            for _image_file in [f for f in os.listdir(target) if is_image(f)]:
                yield os.path.join(target, _image_file)

    target = os.path.expanduser(args.target)

    image_map = dict
    ImageData = namedtuple('ImageData', 'name, ext, date, side_files')

    for image_file in find_images():
        image_folder = os.path.dirname(image_file)
        spl = os.path.splitext(image_file)
        name = os.path.basename(spl[-2])
        ext = spl[-1][1:]
        date = extract_date(image_file)
        data = ImageData(
            name,
            ext,
            date,
            [f for f in os.listdir(image_folder) if side_file(f)])
        print(data)


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

                tags_ref = piexif.TAGS[k]
                for k2, v2 in v.items():
                    vtype = 'binary?' if len(str(v2)) > 100 else v2
                    if k2 in tags_ref:
                        print("      %s.%s: %s" % (k, tags_ref[k2]['name'], vtype))
                    else:
                        print("      %s: %s" % (k2, vtype))

    _run_on_target(_inspect)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers()

    rename_parser = subparsers.add_parser("rename", help="Rename RAW files")
    rename_parser.set_defaults(command="rename")
    rename_parser.add_argument("target", help="File or directory to process")
    rename_parser.add_argument("--recursive", action="store_true", help="Check recursively in sub folders")
    rename_parser.add_argument("--dry-run", action="store_true", help="Doesn't rename anything")
    rename_parser.add_argument("--name-template", default="IMG_{datetime}",
                               help="The template for the name of the file (default IMG_{creation_date}}")
    rename_parser.add_argument("-d", "--delete-duplicates", action="store_true")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect RAW files")
    inspect_parser.set_defaults(command="inspect")
    inspect_parser.add_argument("target", help="File or directory to process")

    args = parser.parse_args()

    if args.command == 'rename':
        new_rename()
    elif args.command == 'inspect':
        inspect()
