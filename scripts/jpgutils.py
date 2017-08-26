#!/home/luca/dev/tools/miniconda3/envs/pyscripts/bin/python
import argparse
import os
import subprocess
from tempfile import mkdtemp


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


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers()

    rename_parser = subparsers.add_parser("showcase", help="Symlink all pictures in folder and open viewer")
    rename_parser.set_defaults(command="showcase")
    rename_parser.add_argument("target", help="File or directory to view")

    args = parser.parse_args()

    if args.command == 'showcase':
        showcase()
