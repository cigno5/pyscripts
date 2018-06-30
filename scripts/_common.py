import configparser
import os


class ConfigFileError(Exception):
    pass


def load_configuration(configuration_file, parser=None):
    def _x(var_name):
        return os.environ[var_name] if var_name in os.environ else 'THIS_FOLDER_DOESNT_EXIST'

    lookups = [
        os.path.expanduser(os.path.expandvars(configuration_file)),
        os.path.join(_x('HOME'), configuration_file),
        os.path.join(_x('HOME'), '.config', configuration_file),
        os.path.join(_x('PYSCRIPTS_CONFIG'), configuration_file),
    ]

    path = None

    for _path in lookups:
        if os.path.exists(_path):
            path = _path
            break

    if path:
        if parser is None:
            parser = configparser.ConfigParser()
        parser.read(path)
        return parser
    else:
        raise ConfigFileError("Cannot find configuration file %s. Put file in $HOME, $HOME/.config/ or specify the "
                              "configuration folder using the environment variable $PYSCRIPTS_CONFIG" %
                              configuration_file)
