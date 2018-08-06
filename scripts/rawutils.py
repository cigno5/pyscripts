import argparse
import os
import re
from datetime import datetime, timedelta

import piexif

IMAGE_EXTS = ["cr2"]


def __get_creation_date(tags):
    for key in [piexif.ExifIFD.DateTimeOriginal, piexif.ImageIFD.DateTime]:
        creation_date = datetime.strptime(_get_exif_value(tags, key), "%Y:%m:%d %H:%M:%S")
        creation_date += timedelta(milliseconds=int(_get_exif_value(tags, piexif.ExifIFD.SubSecTimeOriginal)) * 10)
        return creation_date


def __get_model_value(tags):
    for key in [piexif.ImageIFD.Model, piexif.ExifIFD.ImageUniqueID]:
        val = _get_exif_value(tags, key)
        if val:
            return val


FIELD_TAGS = {
    'creation_date': __get_creation_date,
    'model': __get_model_value,
}


def is_image(file):
    return os.path.splitext(file)[-1][1:].lower() in IMAGE_EXTS


def find_images(target):
    if os.path.isfile(target):
        for _image_file in [t for t in [target] if is_image(t)]:
            yield _image_file
    else:
        for _image_file in [f for f in sorted(os.listdir(target)) if is_image(f)]:
            yield os.path.join(target, _image_file)


def split_filename(file):
    bfile = os.path.basename(file)
    dot_idx = bfile.find(".")
    return bfile[:dot_idx], bfile[dot_idx:]


def _get_exif_value(tags, exif_tag):
    for sub_tags in tags.values():
        if type(sub_tags) == dict and exif_tag in sub_tags:
            return sub_tags[exif_tag].decode('utf8')


class ImageInfo:
    def __init__(self, image_file, new_name_segments):
        self.file = image_file
        self.folder = os.path.dirname(image_file)

        # fields loading
        self.fields = {}
        tags = piexif.load(self.file)

        for field in FIELD_TAGS.keys():
            self.fields[field] = FIELD_TAGS[field](tags)

        # retrieve new name, based on fields
        self.new_name = "".join([fn(self) for fn in new_name_segments])

        # retrieve side files
        _name, _ = split_filename(image_file)
        self.side_files = [f for f in os.listdir(self.folder) if not is_image(f) and f.startswith(_name)]

    def get_renames(self, element_count=None):
        """
        Return list of tuples with old names and new names
        :param element_count: number of current duplicate or None if no duplicate
        :return:
        """
        rens = list()

        new_base_name = self.new_name if element_count is None else "%s_%02i" % (self.new_name, element_count)

        old_file = os.path.basename(self.file)
        old_name, old_ext = split_filename(self.file)

        rens.append((old_file, new_base_name + old_ext))

        for sf in self.side_files:
            sf_new_name = new_base_name + sf[len(old_name):]
            rens.append((sf, sf_new_name))

        return rens

    def __str__(self):
        return ", ".join(["{}={}".format(attr, getattr(self, attr)) for attr in dir(self)
                          if not attr.startswith("__")
                          and attr not in ['name_segments']
                          and not attr.startswith('get_')
                          ])


def __const(value):
    return lambda _: value


def __field(field):
    def field_value(data: ImageInfo):
        _v = data.fields[field]
        try:
            t = _v.strftime("%Y%m%dT%H%M%S")
            return t if args.short_date_format else "%s%02d" % (t, _v.microsecond / 10000)
        except AttributeError:
            return _v

    return field_value


class Counters:
    def __init__(self):
        self.original_images = 0
        self.images = 0
        self.side_files = 0
        self.error = 0
        self.ignored = 0

    def __add__(self, other):
        nc = Counters()
        nc.original_images = self.original_images + other.original_images
        nc.images = self.images + other.images
        nc.side_files = self.side_files + other.side_files
        nc.error = self.error + other.error
        nc.ignored = self.ignored + other.ignored
        return nc


def rename():
    _s = 0
    name_segments = list()
    for var_match in re.finditer("\{(.+?)\}", args.name_template):
        tpl_var = var_match.group(1)
        assert tpl_var in FIELD_TAGS, "Var '%s' is not valid (valid ones: %s)" % (tpl_var, str(list(FIELD_TAGS.keys())))
        name_segments.append(__const(args.name_template[_s:var_match.start()]))
        name_segments.append(__field(tpl_var))
        _s = var_match.end()
    name_segments.append(__const(args.name_template[_s:]))

    def rename_in_folder(target):
        target = os.path.abspath(target)
        print('Scanning %s/%s...' % (target, " (dry run) " if args.dry_run else ""))

        folder_count = Counters()

        images_info = dict()
        for image_file in find_images(target):
            folder_count.original_images += 1
            try:
                ii = ImageInfo(image_file, name_segments)
                if ii.new_name not in images_info:
                    images_info[ii.new_name] = list()

                images_info[ii.new_name].append(ii)
            except ValueError as e:
                __filename = os.path.basename(image_file)
                if args.stop_on_fail:
                    raise RuntimeError("Cannot rename file %s " % __filename, e)
                else:
                    print("{orig:30s} -> ERROR ({err}) ".format(orig=__filename, err=str(e)))
                    folder_count.error += 1
                    continue

        for new_name in images_info.keys():
            _alone = len(images_info[new_name]) == 1
            _c = None if _alone else -1
            for ii in images_info[new_name]:

                if not _alone:
                    _c += 1

                _first = True
                for old, new in ii.get_renames(_c):
                    print("{orig:30s} -> {new}".format(orig=old, new=new), end='... ')
                    if old == new:
                        if args.verbose:
                            print("Ignored")
                        else:
                            print("Ignored", end='\r')
                        folder_count.ignored += 1
                        continue

                    if _first:
                        folder_count.images += 1
                        _first = False
                    else:
                        folder_count.side_files += 1

                    if not args.dry_run:
                        os.rename(os.path.join(target, old), os.path.join(target, new))
                    print("Renamed")

        print('...Total %i --> renamed %i images and %i side files; %i files ignored and %i in error\n'
              % (folder_count.original_images,
                 folder_count.images, folder_count.side_files,
                 folder_count.ignored,
                 folder_count.error))
        return folder_count

    target_folder = os.path.expanduser(args.target)
    # if recursive is better to run the function by each folder, without putting together images from different folders
    if args.recursive:
        total_count = Counters()
        for root, dirs, files in os.walk(target_folder):
            total_count += rename_in_folder(root)
        print("""
Summary =======================================
  Total images....: {original_images}
  Ignored.........: {ignored}
  Error...........: {error}

  Renamed.........: {images}
    + side files..: {side_files}
""".format(
            original_images=total_count.original_images,
            images=total_count.images,
            side_files=total_count.side_files,
            ignored=total_count.ignored,
            error=total_count.error,
        ))
    else:
        rename_in_folder(target_folder)
    print('Done.')


def inspect():
    def inspect_file(file):
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

    if args.recursive:
        for root, dirs, files in os.walk(args.target):
            [inspect_file(image_file) for image_file in find_images(root)]

    else:
        [inspect_file(image_file) for image_file in find_images(args.target)]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    def __add_std_options(_parser):
        _parser.add_argument("-r", "--recursive", action="store_true", help="Check recursively in sub folders")
        _parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")


    subparsers = parser.add_subparsers()

    rename_parser = subparsers.add_parser("rename", help="Rename RAW files")
    rename_parser.set_defaults(command="rename")
    rename_parser.add_argument("target", help="File or directory to process")
    rename_parser.add_argument("--dry-run", action="store_true", help="Doesn't rename anything")
    rename_parser.add_argument("--stop-on-fail", action="store_true", help="Raises an exception for any error")
    rename_parser.add_argument("--compact", action="store_true", help="Remove whitespaces in filename")
    rename_parser.add_argument("--name-template", default="IMG_{creation_date}",
                               help="The template for the name of the file (default IMG_{creation_date}}")
    rename_parser.add_argument("--short-date-format", action='store_true',
                               help="Force to use creation date with no subsec time ")
    __add_std_options(rename_parser)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect RAW files")
    inspect_parser.set_defaults(command="inspect")
    inspect_parser.add_argument("target", help="File or directory to process")
    __add_std_options(inspect_parser)

    args = parser.parse_args()

    eval("%s()" % args.command)
