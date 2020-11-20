import argparse
import os
import shutil
import subprocess
import sys
from tempfile import mkdtemp


def showcase():
    assert os.path.exists(args.target), "Target folder %s doesn't exist" % args.target

    exts = ['.' + e for e in args.ext.split(",")]
    # source_files = [os.path.join(r, f) for r, fd, fl in os.walk(os.path.abspath(args.target)) for f in fl
    #                 if os.path.splitext(f)[1].lower() in exts]

    tmp = mkdtemp(prefix="showcase_")
    first = None
    c = 0
    for r, dirs, files in os.walk(os.path.abspath(args.target)):
        dirs.sort()
        for file in [os.path.join(r, f) for f in sorted(files) if os.path.splitext(f)[1].lower() in exts]:
            c += 1
            link_name = "%04i_%s" % (c, os.path.basename(file))
            if not first:
                first = os.path.join(tmp, link_name)
            os.symlink(file, os.path.join(tmp, link_name))
            print("%s -> %s" % (file, os.path.join(tmp, link_name)))

    subprocess.call(["xdg-open", first])


def permanent_showcase():
    SHOWCASE_NAME = "__showcase"
    target = args.target
    counter = {}

    def create_linker(_folder):
        if _folder not in counter:
            counter[_folder] = 0

        def _linker(item):
            if not args.skip_root or (_folder != target):
                c = counter[_folder]
                counter[_folder] += 1

                showcase_folder = os.path.join(_folder, SHOWCASE_NAME)
                os.makedirs(showcase_folder, exist_ok=True)
                link_name = os.path.join(showcase_folder, "%04d_%s" % (c, os.path.basename(item)))
                path_to_item = os.path.relpath(item, showcase_folder)
                if not os.path.exists(link_name):
                    os.symlink(path_to_item, link_name)

        return _linker

    def picture_list(folder, linkers):

        if args.rebuild or args.remove:
            sc_folder = os.path.join(folder, SHOWCASE_NAME)
            if os.path.exists(sc_folder):
                shutil.rmtree(sc_folder)

        for entry in sorted([e for e in os.scandir(folder) if e.name != SHOWCASE_NAME], key=lambda e: e.name):
            entry_path = os.path.join(folder, entry.name)
            if entry.is_dir():
                picture_list(entry_path, linkers + [create_linker(folder)])
            elif entry.is_file() and not args.remove:
                for linker in linkers:
                    linker(entry_path)

    picture_list(target, [print])


def catalog():
    source = os.path.expanduser(args.source)
    target = os.path.expanduser(args.target)
    assert os.path.exists(source), "Source folder doesn't exist"

    if not os.path.exists(target):
        os.makedirs(target, exist_ok=True)

    exts = ['.' + e for e in args.ext.split(",")]

    for root, folders, files in os.walk(source):
        print('scan %s...' % root)
        if os.path.basename(os.path.normpath(root))[0] == '.':
            continue

        relative_root = root[len(source):]
        for file in [f for f in files if os.path.splitext(f)[1].lower() in exts]:
            print('file %s...' % file)
            source_picture = os.path.join(root, file)
            target_picture = os.path.join(target, relative_root, file)

            target_exists = os.path.exists(target_picture)

            if not target_exists or args.force:
                if target_exists:
                    print('Replacing %s...' % target_picture)
                    os.remove(target_picture)
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


catalog_file = os.path.expanduser("~/.jpgutils-catalog.idx")


def _load_catalog_index():
    index = {}
    if os.path.exists(catalog_file):
        with open(catalog_file, 'r') as f:
            first = True
            for line in f.readlines():
                if first:
                    first = False
                    continue
                path, mtime = line[:-1].split('\t')
                index[path] = float(mtime)

    return index


def _write_catalog_index(index: dict):
    with open(catalog_file, 'w') as f:
        f.write("original_path\ttimestamp%n")

        for path, timestamp in index.items():
            f.write("%s\t%s\n" % (path, timestamp))


def catalog2():
    def path_mtime():
        return os.path.abspath(source_picture), os.path.getmtime(source_picture)

    source = os.path.expanduser(args.source)
    target = os.path.expanduser(args.target)
    assert os.path.exists(source), "Source folder doesn't exist"

    index = _load_catalog_index()

    if not os.path.exists(target):
        os.makedirs(target, exist_ok=True)

    exts = ['.' + e for e in args.ext.split(",")]
    forced_resize = args.force

    sources = 0
    skipped = 0
    replaced = 0

    for root, folders, files in os.walk(source):
        print('scanning %s...' % root)
        if os.path.basename(os.path.normpath(root))[0] == '.':
            continue

        target_root = os.path.join(target, root[len(source):])
        print(' > target root: %s' % target_root)
        for file in [f for f in files if os.path.splitext(f)[1].lower() in exts]:
            source_picture = os.path.join(root, file)
            target_picture = os.path.join(target_root, file)
            print('%s -> ' % file, end='', flush=True)
            sources += 1

            path, mtime = path_mtime()
            source_changed = path in index and index[path] != mtime
            target_exists = os.path.exists(target_picture)

            if source_changed or forced_resize or not target_exists:
                if target_exists:
                    os.remove(target_picture)
                    print('deleted, ', end='', flush=True)
                    replaced += 1
                os.makedirs(os.path.dirname(target_picture), exist_ok=True)
                shutil.copyfile(source_picture, target_picture)
                subprocess.call(["mogrify", "-resize", args.resize, target_picture])
                print('generated.')
            else:
                print("skipped.")
                skipped += 1

            index[os.path.abspath(source_picture)] = os.path.getmtime(source_picture)

    _write_catalog_index(index)
    print("""
Catalog generation done
    Found %d pictures
    Skipped %d pictures
    Generated %d pictures (%d replaced)
""" % (sources, skipped, (sources - skipped), replaced))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers()

    showcase_parser = subparsers.add_parser("showcase", help="Symlink all pictures in folder and open viewer")
    showcase_parser.set_defaults(command="showcase")
    showcase_parser.add_argument("target", help="File or directory to view")
    showcase_parser.add_argument("--ext", default="jpg,jpeg",
                                 help="Extensions valid to be shown, separated by comma")
    showcase_parser.add_argument("--permanent", help="Make showcase permanent")

    catalog_parser = subparsers.add_parser("catalog", help="Create catalog with smaller pictures")
    catalog_parser.set_defaults(command="catalog")
    catalog_parser.add_argument("source", help="Original directory from where creating the catalog")
    catalog_parser.add_argument("target", help="Final destination of the catalog")
    catalog_parser.add_argument("--resize", default="1920x1080",
                                help="Resize value of the pictures (default 1920x1080")
    catalog_parser.add_argument("--ext", default="jpg,jpeg",
                                help="Extensions valid to be copied, separated by comma")
    catalog_parser.add_argument("--force", action='store_true',
                                help='Force resized file to be overridden')

    catalog_parser2 = subparsers.add_parser("catalog2", help="Create catalog with smaller pictures")
    catalog_parser2.set_defaults(command="catalog2")
    catalog_parser2.add_argument("source", help="Original directory from where creating the catalog")
    catalog_parser2.add_argument("target", help="Final destination of the catalog")
    catalog_parser2.add_argument("--resize", default="1920x1080",
                                 help="Resize value of the pictures (default 1920x1080")
    catalog_parser2.add_argument("--ext", default="jpg,jpeg",
                                 help="Extensions valid to be copied, separated by comma")
    catalog_parser2.add_argument("--force", action='store_true',
                                 help='Force resized file to be overridden')

    pshowcase_parser = subparsers.add_parser("permanent-showcase", help="Create permanent showcase")
    pshowcase_parser.set_defaults(command="permanent_showcase")
    pshowcase_parser.add_argument("target", help="Final destination of the catalog")
    pshowcase_parser.add_argument("--skip-root", action="store_true", help="Skip root showcase folder")
    pshowcase_parser.add_argument("--rebuild", action="store_true", help="Delete all showcase folders and then create again")
    pshowcase_parser.add_argument("--remove", action="store_true", help="Delete all showcase folders")

    args = parser.parse_args()
    if args.command:
        if args.command == 'showcase':
            showcase()
        elif args.command == 'catalog':
            catalog()
        elif args.command == 'catalog2':
            catalog2()
        elif args.command == 'permanent_showcase':
            permanent_showcase()
        else:
            parser.print_usage()
    else:
        parser.print_usage()
