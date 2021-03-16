import copy
import os

import confu.config
import confu.exceptions
import grainy.core
import munge
import pluginmgr.config
from grainy.core import PermissionSet, int_flags
from pkg_resources import get_distribution

# import to namespace
from ctl.config import BaseSchema
from ctl.exceptions import ConfigError, PermissionDenied
from ctl.log import Log, set_pylogger_config
from ctl.util.template import IgnoreUndefined, filter_escape_regex

__version__ = get_distribution("ctl").version

try:
    import tmpl
except ImportError:
    tmpl = None


# plugins
class PluginManager(pluginmgr.config.ConfigPluginManager):
    """
    ctl plugin manager
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


plugin = PluginManager("ctl.plugins")


def plugin_cli_arguments(ctlr, parser, plugin_config):

    """
    set up cli arguments for the plugin
    """

    # get plugin class

    plugin_class = ctlr.get_plugin_class(plugin_config.get("type"))

    # load plugin config

    config = copy.deepcopy(plugin_config)
    confu.schema.apply_defaults(plugin_class.ConfigSchema(), config)

    confu_cli_args = plugin_class.confu_cli_args_cls()(
        parser, plugin_class.ConfigSchema().config, config.get("config")
    )

    # add any aditional cli args

    if hasattr(plugin_class, "add_arguments"):
        plugin_class.add_arguments(parser, config.get("config"), confu_cli_args)

    # if no confu generated cli parameters were attached / routed
    # add them all to the main parser
    if not confu_cli_args.routes:
        confu_cli_args.add(parser)


def read_config(schema, config_dir, config_name="config", ctx=None):
    """
    read a config file from config_dir
    """
    conf_path = os.path.expanduser(config_dir)
    if not os.path.exists(conf_path):
        raise OSError(f"config dir not found at {conf_path}")

    for codec, filename in munge.find_datafile(config_name, conf_path):

        if tmpl:
            # if twentyc.tmpl was imported, render config before
            # loading it.

            engine = tmpl.get_engine("jinja2")(search_path=os.path.dirname(filename))
            engine.engine.undefined = IgnoreUndefined
            # TODO need a streamlined way to load in template filters
            engine.engine.filters["escape_regex"] = filter_escape_regex
            data = codec().loads(
                engine._render(src=os.path.basename(filename), env=ctx.tmpl["env"])
            )
            ctx.tmpl.update(engine=engine)
        else:
            with open(filename) as fobj:
                data = codec().load(fobj)

        meta = dict(config_dir=config_dir, config_file=filename)
        return confu.config.Config(schema, data, meta)

    raise OSError(f"config dir not found at {conf_path}")


class Context:
    """
    class to hold current context, debug, logging, sandbox, etc
    also holds master config
    """

    app_name = "ctl"

    @classmethod
    def search_path(cls):
        return [
            "$%s_HOME" % cls.app_name.upper(),
            os.path.join(".", cls.app_name.capitalize()),
            os.path.expanduser(os.path.join("~", "." + cls.app_name)),
        ]

    @classmethod
    def pop_options(cls, kwargs):
        keys = ("debug", "home", "verbose", "quiet")
        return {k: kwargs.pop(k, None) for k in keys}

    @classmethod
    def option_list(cls):
        return [
            dict(
                name="--debug",
                help="enable extra debug output",
                is_flag=True,
                default=None,
            ),
            dict(
                name="--home",
                help="specify the home directory, by default will check in order: "
                + ", ".join(cls.search_path()),
                default=None,
            ),
            dict(
                name="--verbose",
                help="enable more verbose output",
                is_flag=True,
                default=None,
            ),
            dict(name="--quiet", help="no output at all", is_flag=True, default=None),
        ]

    def update_options(self, kwargs):
        """
        updates config based on passed options

        too complicated for now, we can just make working_dir as an option and simplify this cluster:
        if config_dir is passed, it will be used to load config from
        if home is passed, it will update config::home
        if home is passed and config_dir isn't set, will try to load config from there
        config_dir and config_file cannot both be passed
        if config_file is passed, home or config::home must be set
        """
        opt = self.__class__.pop_options(kwargs)

        # TODO move this to the pop_options function, use confu
        if opt.get("debug", None) is not None:
            self.debug = opt["debug"]

        if opt.get("verbose", None) is not None:
            self.verbose = opt["verbose"]

        if opt.get("quiet", None) is not None:
            self.quiet = opt["quiet"]

        if opt.get("home", None):
            if "config_dir" in kwargs:
                raise ValueError("config_dir and home are mutually exclusive")
            self._new_home(opt["home"])

        elif kwargs.get("config_dir"):
            self._new_home(kwargs["config_dir"])

        # if no config and home wasn't defined, check search path
        elif not self.home:
            self.find_home()

        self.init()

    def __init__(self, **kwargs):
        self.debug = False
        self.quiet = False
        self.verbose = False

        self.home = None
        self.config = None

        self.tmpl = {"engine": None, "env": {"ctx": self}}

        self.update_options(kwargs)

    def find_home(self):
        for path in self.__class__.search_path():
            if path.startswith("$"):
                if path[1:] not in os.environ:
                    continue
                path = os.environ[path[1:]]
            try:
                return self._new_home(path)

            except OSError:
                pass

    def _new_home(self, home):
        # TODO check config for popped options
        self.home = os.path.abspath(home)

        user_home = os.path.expanduser("~")

        self.tmpdir = os.path.abspath(os.path.join(self.home, "tmp"))
        self.cachedir = os.path.abspath(os.path.join(user_home, ".cache", "ctl"))
        self.user_home = user_home

        if not os.path.exists(self.tmpdir):
            os.makedirs(self.tmpdir)

        if not os.path.exists(self.cachedir):
            os.makedirs(self.cachedir)

        self.read_config()

    def read_config(self):
        if getattr(self, "config", None) and self.tmpl:
            self.tmpl["env"]["config"] = self.config.data
        self.config = read_config(BaseSchema.config(), self.home, ctx=self)

    def init(self):
        """
        call after updating options
        """


def argv_to_grainy_namespace(operation, args=[]):
    """
    create gainy permissioning namespace from argv
    """
    namespace = ["ctl"]
    if operation:
        namespace.append(operation)

    for arg in args:
        # skip options
        if arg[0] == "-":
            continue
        namespace.append(arg)

    return grainy.core.Namespace(namespace)


class Ctl:
    """
    main controller object
    """

    @property
    def config(self):
        return self.ctx.config

    def get_plugin_config(self, name):
        for plugin in self.config.get_nested("ctl", "plugins"):
            if plugin["name"] == name:
                return plugin
        if self.config.errors:
            self.log_config_issues()
        raise ValueError(f"unknown plugin: {name}")

    # don't allow updating the config, there's too many undefined
    # things that could happen
    # def set_config_dir(self):

    def __init__(self, ctx=None, config_dir=None, full_init=True):

        self.init_context(ctx=ctx, config_dir=config_dir)
        self.init_logging()

        if self.config.errors:
            return self.log_config_issues()

        self.init_permissions()
        self.expose_plugin_vars()

        if full_init:
            self.init()

    def init(self):
        # validate config
        self.validate_config()

        # these requrie config
        self.init_plugin_manager()
        self.init_plugins()

    def init_context(self, ctx=None, config_dir=None):
        # TODO check for mutual exclusive
        if not ctx:
            ctx = Context(config_dir=config_dir)
        self.ctx = ctx

        # TODO - should have defaults from confu
        if not self.ctx.config:
            raise RuntimeError("no config found")

        self.home = ctx.home
        self.tmpdir = ctx.tmpdir
        self.cachedir = ctx.cachedir

    def init_plugin_manager(self):
        """
        Initialize the plugin manager and
        set it's apropriate search paths
        """
        # add home/plugins to plugin search path
        # TODO merge with ctl.plugin_path
        plugin_path = self.ctx.config.get_nested("ctl", "plugin_path")
        if plugin_path:
            # path list is relative to home
            plugin.searchpath = plugin_path
        else:
            plugin.searchpath = [os.path.join(self.ctx.home, "plugins")]

    def init_logging(self):
        """
        Apply python logging config and create `log` and `usage_log`
        properties
        """

        # allow setting up python logging from ctl config
        set_pylogger_config(self.ctx.config.get_nested("ctl", "log"))

        # instantiate logger
        self.log = Log("ctl")
        self.usage_log = Log("usage")

    def init_permissions(self):
        """
        Initialize permissions for ctl usage
        """
        # TODO: load permissions from db?
        self.permissions = PermissionSet(
            {
                row.get("namespace"): int_flags(row.get("permission"))
                for row in self.ctx.config.get_nested("ctl", "permissions")
            }
        )

    def init_plugins(self):
        """
        Instantiate plugins
        """
        plugin.import_external()
        plugins_config = self.ctx.config.get_nested("ctl", "plugins")

        # can't lazy init since plugins might double inherit
        if plugins_config:
            plugin.instantiate(plugins_config, self)

    def expose_plugin_vars(self):
        """
        Checks all configured plugins if they have
        the `expose_vars` classmethod.

        If they do those vars will be exposed to the context
        template environment

        This can be done without having to instantiate the plugins
        """
        if "plugin" not in self.ctx.tmpl["env"]:
            self.ctx.tmpl["env"]["plugin"] = {}

        for plugin_config in self.config.get_nested("ctl", "plugins"):
            plugin_class = self.get_plugin_class(plugin_config["type"])
            name = plugin_config.get("name")
            if hasattr(plugin_class, "expose_vars"):
                env = self.ctx.tmpl["env"]["plugin"].get(name, {})
                errors = plugin_class.expose_vars(env, plugin_config.get("config", {}))
                for filepath, error in list(errors.items()):
                    self.log.debug(f"expose_vars: {filepath}: {error}")
                self.ctx.tmpl["env"]["plugin"][name] = env

    def validate_config(self):
        # just accessing data validates
        len(self.config)
        self.log_config_issues()

    def log_config_issues(self):
        if self.config.errors:
            for err in self.config.errors:
                self.log.error(f"[config error] {err.pretty}")
            raise ConfigError("config invalid")

        for warn in self.config.warnings:
            self.log.info(f"[config warning] {warn.pretty}")

    def check_permissions(self, namespace, perm):
        # self.log.debug("checking permissions namespace '{}' for '{}'".format(namespace, perm))

        if not self.permissions.check(namespace, grainy.core.int_flags(perm)):
            raise PermissionDenied(namespace, perm)

    def get_plugin_class(self, name):
        """
        get plugin class
        """
        self.check_permissions(argv_to_grainy_namespace(name), "r")
        # TODO log usage - -set audit level?
        return plugin.get_plugin_class(name)

    def get_plugin(self, name):
        """
        get configured plugin by name
        """
        self.check_permissions(argv_to_grainy_namespace(name), "r")
        # TODO log usage - -set audit level?
        return plugin.get_instance(name, self)
