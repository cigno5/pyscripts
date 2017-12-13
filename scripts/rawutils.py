import argparse
import os
import re
from datetime import datetime

import piexif

IMAGE_EXTS = ["cr2"]
DATE_TAGS = [piexif.ExifIFD.DateTimeOriginal, piexif.ImageIFD.DateTime]


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
    return bfile[:dot_idx], bfile[dot_idx + 1:]


class ImageInfo:
    def __init__(self, image_file, new_name_segments):
        self.file = image_file
        self.name, self.ext = split_filename(image_file)

        self.name_segments = new_name_segments

        tags = piexif.load(image_file)
        date_value = None
        for sub_tags in tags.values():
            for date_tag in DATE_TAGS:
                if date_tag in sub_tags:
                    date_value = sub_tags[date_tag].decode('utf8')
                    break
            if date_value:
                break

        self.date = datetime.strptime(date_value, "%Y:%m:%d %H:%M:%S")

        def side_file(file):
            lcase_file = file.lower()
            lcase_name = self.name.lower()
            lcase_ext = self.ext.lower()
            return lcase_file != "%s.%s" % (lcase_name, lcase_ext) and lcase_file.startswith(lcase_name)

        self.side_files = [(f, f[len(self.name):]) for f in os.listdir(os.path.dirname(image_file)) if side_file(f)]

    def get_new_image_filename(self):
        return "".join([fn(self) for fn in self.name_segments] + ['.', self.ext])

    def get_filename_transformations(self, dups):
        new_name = "".join([fn(self) for fn in self.name_segments])
        if dups > 0:
            new_name += "-%i" % dups

        ret = [(os.path.basename(self.file), new_name + "." + self.ext)]
        for side_file, file_rest in self.side_files:
            ret.append((side_file, new_name + file_rest))

        return ret

    def __str__(self):
        for cazzo in dir(self):

            if type(cazzo) != str:
            # if str(cazzo) == 'get_filename_transformations':
                print(type(cazzo))
                # for fregna in dir(cazzo):
                #     print(fregna)

        return ", ".join(["{}={}".format(attr, getattr(self, attr)) for attr in dir(self)
                          if not attr.startswith("__")
                          and attr not in ['name_segments']
                          and not attr.startswith('get_')
                          ])


def rename():
    def name_segments_builder():
        def _const(value):
            return lambda _: value

        # def _seq():
        #     return lambda data: '' if data.name

        _s = 0
        segments = list()
        tpl_vars = {
            'datetime': lambda data: datetime.strftime(data.date, "%Y%m%dT%H%M%S")
        }

        for var_match in re.finditer("\{(.+?)\}", args.name_template):
            tpl_var = var_match.group(1)
            assert tpl_var in tpl_vars, "Var '%s' is not valid (valid ones: %s)" % (tpl_var, tpl_vars)
            segments.append(_const(args.name_template[_s:var_match.start()]))
            segments.append(tpl_vars[tpl_var])
            _s = var_match.end()
        segments.append(_const(args.name_template[_s:]))

        return segments

    name_segments = name_segments_builder()

    def rename_in_folder(target):
        print('Scanning %s/ ...' % target)

        duplicates = dict()

        images_info = sorted([ImageInfo(image_file, name_segments) for image_file in find_images(target)],
                             key=lambda ii: ii.name)
        for image_info in images_info:
            print()
            print(image_info)
            new_name = image_info.get_new_image_filename()

            dups = duplicates[new_name] if new_name in duplicates else 0

            for old, new in image_info.get_filename_transformations(dups):
                print("{orig:20s} -> {new:20s}".format(orig=old, new=new))
                duplicates[new_name] = dups + 1

    # if recursive is better to run the function by each folder, without putting together images from different folders
    if args.recursive:
        for root, dirs, files in os.walk(os.path.expanduser(args.target)):
            rename_in_folder(root)
    else:
        rename_in_folder(os.path.expanduser(args.target))


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
        _parser.add_argument("--recursive", action="store_true", help="Check recursively in sub folders")

    subparsers = parser.add_subparsers()

    rename_parser = subparsers.add_parser("rename", help="Rename RAW files")
    rename_parser.set_defaults(command="rename")
    rename_parser.add_argument("target", help="File or directory to process")
    rename_parser.add_argument("--dry-run", action="store_true", help="Doesn't rename anything")
    rename_parser.add_argument("--name-template", default="IMG_{datetime}",
                               help="The template for the name of the file (default IMG_{creation_date}}")
    rename_parser.add_argument("-d", "--delete-duplicates", action="store_true")
    __add_std_options(rename_parser)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect RAW files")
    inspect_parser.set_defaults(command="inspect")
    inspect_parser.add_argument("target", help="File or directory to process")
    __add_std_options(inspect_parser)

    args = parser.parse_args()

    eval("%s()" % args.command)
