import argparse
import configparser
import getpass
import os
import shutil
import tempfile
import logging
import sh

config = configparser.ConfigParser()


class Mount:
    def __init__(self):
        self.mount_point = tempfile.mkdtemp('.tmp', 'mybkp_')
        self.sudo_passwd = getpass.getpass("Please enter password: ")

    def __enter__(self):
        source_settings = config['source']
        logging.debug("Mounting repository...")
        with sh.contrib.sudo(password=self.sudo_passwd, _with=True):
            sh.mount("-t", "cifs",
                     "//%s%s" % (source_settings.get('server'), source_settings.get('base_folder')),
                     self.mount_point.__str__(),
                     '-o', 'uid=%d' % os.getuid(),
                     '-o', 'gid=%d' % os.getgid(),
                     '-o', 'username=%s,noexec' % source_settings.get('user'),
                     '-o', 'password=%s' % source_settings.get('password'))
        logging.debug("...mounted")
        return self.mount_point.__str__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if os.path.ismount(self.mount_point.__str__()):
            logging.info("Dismounting repository...")
            with sh.contrib.sudo(password=self.sudo_passwd, _with=True):
                sh.umount(self.mount_point.__str__())
            logging.info("...dismounted")

        shutil.rmtree(self.mount_point)


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

    def build_parameters(self, params):
        if args.dry_run:
            params.append('--dry-run')

        if self.delete_missing:
            params.append('--delete')

        if self.exclude:
            params += ["--exclude=%s" % excl for excl in self.exclude]

        return params

    def get_contents(self, mount_point):
        for sub_folder in self.sub_folders:
            yield (os.path.join(self.local_root, sub_folder), os.path.join(mount_point, self.remote_root, sub_folder))


def show():
    if args.subject == 'tasks':
        print("Enabled tasks:")
        [print("  " + s.name) for s in _get_tasks(lambda t: t.enabled)]
        print("\nDisabled tasks:")
        [print("  " + s.name) for s in _get_tasks(lambda t: not t.enabled)]


def backup():
    with Mount() as mount_point, tempfile.NamedTemporaryFile(suffix=".log", prefix="mybkp_", delete=False) as log_file:
        print("Mount point: %s\nLog file: %s" % (mount_point, log_file.name))

        def _to_be_backup(t: Task):
            return t.enabled and (len(args.tasks) == 0 or t.name in args.tasks)

        for task in _get_tasks(_to_be_backup):
            params = task.build_parameters(["-avzhi"])

            for source, destination in task.get_contents(mount_point):
                print(" ".join(['rsync'] + params + [source, destination]))
                sh.rsync(*params, source, destination, _out=log_file)

        sh.less(log_file.name, _fg=True)


def _get_tasks(task_filter=None):
    for task in (Task(config[s]) for s in config.sections() if s != 'source'):
        if not task_filter or task_filter(task):
            yield task


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('-c', '--config', default=os.path.expanduser("~/mybkp.ini"), help='Configuration ini file')
    parser.add_argument('--dry-run', action='store_true', help='Do not synchronize anything', default=True)
    parser.add_argument('--verbose', action='store_true')

    sub_parser = parser.add_subparsers()
    backup_parser = sub_parser.add_parser("backup", help="Execute the backup of the tasks")
    backup_parser.set_defaults(command="backup")
    backup_parser.add_argument('tasks', nargs='*', help='Tasks to be backupped (or empty for all active tasks)')

    show_parser = sub_parser.add_parser("show", help="Show useful information")
    show_parser.set_defaults(command="show")
    show_parser.add_argument("subject", help="Subject of the request", choices=['tasks'])

    args = parser.parse_args()

    logging.basicConfig(
        format='%(message)s',
        level=logging.DEBUG if args.verbose else logging.WARNING)

    if args.verbose:
        logging.getLogger("sh").setLevel(logging.INFO)

    if hasattr(args, 'command'):
        assert os.path.exists(args.config), "Configuration file not found"
        config.read(args.config)

        eval("%s()" % args.command)
    else:
        parser.print_help()
