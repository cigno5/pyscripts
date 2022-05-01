import argparse
import collections
import configparser
import getpass
import logging
import os
import re
import shutil
import sys
import tempfile

import sh

import _common

config = configparser.ConfigParser(dict_type=collections.OrderedDict)
all_tasks = []
all_names = set()

__sudo_passwd = None


class Mount:
    def __init__(self, keep_mounted=False):
        self.mount_point = tempfile.mkdtemp('.tmp', 'mybkp_')
        self.keep_mounted = keep_mounted

    def __enter__(self):
        logging.debug("Mounting repository...")
        with _sudo():
            sh.mount(*self.__mount_parameters())
        logging.debug("...mounted")
        return self.mount_point.__str__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.keep_mounted:
            if os.path.ismount(self.mount_point.__str__()):
                logging.info("Dismounting repository...")
                with _sudo():
                    sh.umount(self.mount_point.__str__())
                logging.info("...dismounted")

            shutil.rmtree(self.mount_point)

    def __mount_parameters(self):
        source_settings = config['source']
        if _is_cifs_mount():
            __params = ["-t", "cifs",
                        "//%s%s" % (source_settings.get('server'), source_settings.get('base_folder')),
                        self.mount_point.__str__(),
                        '-o', 'uid=%d' % os.getuid(),
                        '-o', 'gid=%d' % os.getgid(),
                        '-o', 'username=%s,noexec' % source_settings.get('user'),
                        '-o', 'password=%s' % source_settings.get('password')]

        elif _is_nfs_mount():
            __params = ["-t", "nfs",
                        "%s:%s" % (source_settings.get('server'), source_settings.get('base_folder')),
                        self.mount_point.__str__()
                        ]
        else:
            raise ValueError("Mount type '%s' not valid" % source_settings['mount_type'])

        # mount options
        _mnt_opts = config['source']['mount_options']
        if _mnt_opts:
            _mnt_opts = _mnt_opts if isinstance(_mnt_opts, list) else [_mnt_opts]
            for o in _mnt_opts:
                __params.append('-o')
                __params.append(o)

        return __params


class Task:
    """
    Represent task configuration, performs checks and prepare values
    """

    def __init__(self, task_conf):
        def __extract_path(key):
            path = task_conf[key]
            return path if path[-1] == '/' else path + '/'

        self.name = task_conf.name
        self.local_root = os.path.expandvars(os.path.expanduser(__extract_path('local_root')))
        self.remote_root = __extract_path('remote_root')
        self.sub_folders = task_conf.get('content', "").split("\n")
        self.delete_missing = task_conf.getboolean('delete_missing', True)
        self.enabled = task_conf.getboolean('enabled', True)
        self.exclude = [excl for excl in task_conf.get('exclude', '').split('\n') if excl and excl != '']
        _tags = task_conf.get('tags', None)
        if _tags:
            self.tags = [t.lower().strip() for t in _tags.split(',') if t.strip() != '']
        else:
            self.tags = None

    def get_contents(self, mount_point):
        content_filter = re.compile(args.content if args.content else '.*')
        for sub_folder in (f for f in self.sub_folders if content_filter.search(f)):
            destination = sub_folder[1:] if len(sub_folder) > 0 and sub_folder[0] == '.' else sub_folder
            yield (os.path.join(self.local_root, sub_folder), os.path.join(mount_point, self.remote_root, destination))


def show():
    if args.subject == 'tasks':
        print("Enabled tasks:")
        [print("  " + s.name) for s in _get_tasks(lambda t: t.enabled)]
        print("\nDisabled tasks:")
        [print("  " + s.name) for s in _get_tasks(lambda t: not t.enabled)]
    elif args.subject == 'tags':
        tags = {}
        for task in (t for t in _get_tasks() if t.tags):
            for tag in task.tags:
                if tag in tags:
                    tags[tag].append(task)
                else:
                    tags[tag] = [task]

        if tags:
            for tag, tasks in tags.items():
                print("Tag '%s'" % tag)
                for task in tasks:
                    print("  %s" % task.name)
        else:
            print("No tags defined")


def backup():
    backup_restore(False)


def restore():
    backup_restore(True)


def backup_restore(is_backward_direction=False):
    for task_name in args.tasks:
        if task_name not in all_names:
            print("'%s' is not either a valid task or valid tag" % task_name)
            sys.exit(1)

    def eligible(t: Task):
        enabled = t.enabled or args.force
        no_task_specified = len(args.tasks) == 0
        is_specified_task = t.name in args.tasks
        is_tagged_task = t.tags and [t for t in t.tags if t in args.tasks]
        return enabled and (no_task_specified or is_specified_task or is_tagged_task)

    def build_parameters():
        __params = ["-vzhirltoD"] if _is_cifs_mount() else ["-avzhi"]

        if args.verbose:
            __params.append('--verbose')

        if args.dry_run:
            __params.append('--dry-run')

        if not args.avoid_delete and task.delete_missing:
            __params.append('--delete')

        if task.exclude:
            __params += ["--exclude=%s" % excl for excl in task.exclude]

        __filters = list()
        if args.folder:
            __filters.append(("--exclude", "*"))

            for a_folder in args.folder:
                head = a_folder if a_folder[-1] == '/' else a_folder + '/'
                if head[0] == '/':
                    head = head[1:]

                __filters.append(("--include", "%s**" % head))

                while True:
                    head, tail = os.path.split(head)
                    if head == '':
                        break
                    __filters.append(("--include", "%s/" % head))

            for option, value in reversed(__filters):
                __params.append(option)
                __params.append(value)

        return __params

    tasks = list(_get_tasks(eligible))

    if len(tasks) == 0:
        print("No tasks found")
        sys.exit(0)

    with Mount() as mount_point, tempfile.NamedTemporaryFile(suffix=".log", prefix="mybkp_", delete=False) as log_file:
        print("Mount point: %s\nLog file: %s" % (mount_point, log_file.name))

        log_file.write("""
============================================================
Command line tasks/tags : {cl_tasks}
Selected tasks          : {tasks}
============================================================

"""
                       .format(cl_tasks=args.tasks if args.tasks else "*all",
                               tasks=", ".join([t.name for t in tasks]))
                       .encode())

        for task in tasks:
            log_file.write("-------------------------- {task}: {local} -> {remote} {delete} --------------------------"
                           .format(task=task.name,
                                   local=task.local_root,
                                   remote=task.remote_root,
                                   delete="(with delete)" if task.delete_missing else "",
                                   )
                           .encode())

            params = build_parameters()

            for source, destination in task.get_contents(mount_point):
                if is_backward_direction:
                    __s = source
                    source = destination
                    destination = __s

                sync_text = "syncing {} -> {} ...".format(source, destination[len(mount_point):])
                print(sync_text)

                if args.verbose:
                    print(" ".join(['rsync'] + params + [source, destination]))

                log_file.write("\n>> ".encode())
                log_file.write(sync_text.encode())
                log_file.write("\n".encode())
                sh.rsync(*params, source, destination, _out=log_file)

    sh.less(log_file.name, _fg=True)


def mount():
    with Mount(keep_mounted=True) as mount_point:
        print("Remote source mounted at %s ..." % mount_point)


def _sudo():
    global __sudo_passwd
    if __sudo_passwd is None:
        __sudo_passwd = getpass.getpass("Please enter SUDO password: ")

    return sh.contrib.sudo(password=__sudo_passwd, _with=True)


def _get_tasks(task_filter=None):
    for task in all_tasks:
        if not task_filter or task_filter(task):
            yield task


def _is_nfs_mount():
    return config['source']['mount_type'].lower() == 'nfs'


def _is_cifs_mount():
    return config['source']['mount_type'].lower() == 'cifs'


def __check_and_create_tasks():
    _tasks = [Task(config[s]) for s in config.sections() if s != 'source']
    names = {t.name for t in _tasks}
    all_names.update(names)

    for _task in [t for t in _tasks if t.tags]:
        for tag in _task.tags:
            assert tag not in names, "Tag name '%s' conflicts with task name" % tag
        all_names.update(_task.tags)

    return _tasks


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('-c', '--config', help='Configuration ini file. '
                                               "If not specified a file 'mybkp.ini' will be searched in $HOME, "
                                               "$HOME/.config/ or $PYSCRIPTS_CONFIG environment variables")
    parser.add_argument('--verbose', action='store_true')

    sub_parsers = parser.add_subparsers()

    for __cmd, __help in [("backup", "Execute the backup of the tasks"),
                          ("restore", "Execute the restore from backup")]:
        bkp_parser = sub_parsers.add_parser(__cmd, help=__help)
        bkp_parser.set_defaults(command=__cmd)
        bkp_parser.add_argument('--dry-run', action='store_true', help='Do not synchronize anything')
        bkp_parser.add_argument('--force', action='store_true', help='Force backup of disabled tasks')
        bkp_parser.add_argument('--avoid-delete', action='store_true', help="Don't use '--delete' rsync option")
        bkp_parser.add_argument('--folder', nargs='*',
                                help='Folder filter (starting from the root with no leading slash) for rsync')
        bkp_parser.add_argument('--content',
                                help='Content filter (regexp) for selecting sub-folders')
        bkp_parser.add_argument('tasks', nargs='*', help='Tasks to be backupped (or empty for all active tasks)')

    show_parser = sub_parsers.add_parser("show", help="Show useful information")
    show_parser.set_defaults(command="show")
    show_parser.add_argument("subject", help="Subject of the request", choices=['tasks', 'tags'])

    mount_parser = sub_parsers.add_parser("mount", help="Mount remote repository")
    mount_parser.set_defaults(command="mount")

    args = parser.parse_args()

    logging.basicConfig(
        format='%(message)s',
        level=logging.DEBUG if args.verbose else logging.WARNING)

    if args.verbose:
        logging.getLogger("sh").setLevel(logging.INFO)

    if hasattr(args, 'command'):
        _common.load_configuration(args.config if args.config else 'mybkp.ini', parser=config)

        # initialize tasks
        all_tasks = __check_and_create_tasks()

        eval("%s()" % args.command)
    else:
        parser.print_help()
