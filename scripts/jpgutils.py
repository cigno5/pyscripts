#!/home/luca/dev/tools/miniconda3/envs/pyscripts/bin/python
import argparse
import os
import subprocess
from tempfile import mkdtemp


def showcase():
    assert os.path.exists(args.target), "Target folder %s doesn't exist" % args.target

    tmp = mkdtemp(prefix="showcase_")
    first = None
    c = 0
    for root, folders, files in os.walk(os.path.abspath(args.target)):
        for file in files:
            c += 1
            link_name = "%04i_%s" % (c, file)
            if not first:
                first = os.path.join(tmp, link_name)
            os.symlink(os.path.join(root, file), os.path.join(tmp, link_name))
            print("%s -> %s" % (os.path.join(root, file), os.path.join(tmp, link_name)))

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
