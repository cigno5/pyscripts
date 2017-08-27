#!/home/luca/dev/tools/miniconda3/envs/pyscripts/bin/python
import argparse
import os
import subprocess
import shutil
from tempfile import mkdtemp
import sys


def showcase():
    assert os.path.exists(args.target), "Target folder %s doesn't exist" % args.target

    source_files = [os.path.join(r, f) for r, fd, fl in os.walk(os.path.abspath(args.target)) for f in fl
                    if os.path.splitext(f)[1].lower() in ['.jpg']]

    tmp = mkdtemp(prefix="showcase_")
    first = None
    c = 0
    for file in sorted(source_files):
        c += 1
        link_name = "%04i_%s" % (c, os.path.basename(file))
        if not first:
            first = os.path.join(tmp, link_name)
        os.symlink(file, os.path.join(tmp, link_name))
        print("%s -> %s" % (file, os.path.join(tmp, link_name)))

    subprocess.call(["xdg-open", first])


def catalog():
    assert os.path.exists(args.source), "Source folder doesn't exist"

    if not os.path.exists(args.target):
        os.makedirs(args.target, exist_ok=True)

    exts = ['.' + e for e in args.ext.split(",")]

    for root, folders, files in os.walk(args.source):
        if os.path.basename(os.path.normpath(root))[0] == '.':
            continue

        relative_root = root[len(args.source):]
        for file in [f for f in files if os.path.splitext(f)[1].lower() in exts]:
            source_picture = os.path.join(root, file)
            target_picture = os.path.join(args.target, relative_root, file)

            if not os.path.exists(target_picture):
                print("Copying %s..." % os.path.join(relative_root, file), end='')
                sys.stdout.flush()
                os.makedirs(os.path.dirname(target_picture), exist_ok=True)
                shutil.copyfile(source_picture, target_picture)
                print("resizing...", end='')
                sys.stdout.flush()
                subprocess.call(["mogrify", "-resize", args.resize, target_picture])
                print('done')
            else:
                print("File %s already exist, skipped" % target_picture)

    print("done")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers()

    showcase_parser = subparsers.add_parser("showcase", help="Symlink all pictures in folder and open viewer")
    showcase_parser.set_defaults(command="showcase")
    showcase_parser.add_argument("target", help="File or directory to view")

    catalog_parser = subparsers.add_parser("catalog", help="Create catalog with smaller pictures")
    catalog_parser.set_defaults(command="catalog")
    catalog_parser.add_argument("source", help="Original directory from where creating the catalog")
    catalog_parser.add_argument("target", help="Final destination of the catalog")
    catalog_parser.add_argument("--resize", default="1920x1080",
                                help="Resize value of the pictures (default 1920x1080")
    catalog_parser.add_argument("--ext", default="jpg,jpeg",
                                help="Extensions valid to be copied, separated by comma")

    args = parser.parse_args()
    if args.command:
        if args.command == 'showcase':
            showcase()
        elif args.command == 'catalog':
            catalog()
        else:
            parser.print_usage()
    else:
        parser.print_usage()
