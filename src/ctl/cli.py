from __future__ import absolute_import, division, print_function

import argparse
import munge
import sys
import traceback

import grainy.core

import ctl
import ctl.plugins.all
from ctl import Context, Ctl, plugin
from ctl.exceptions import PermissionDenied, ConfigError, PluginOperationStopped
from ctl.events import common_events


# <release env> moving after deploy
def add_options(parser, options):
    for opt in options:
        name = opt.pop("name")

        # clicks is_flag
        if "is_flag" in opt:
            del opt["is_flag"]
            opt["action"] = "store_true"

        parser.add_argument(name, **opt)


def ctl_options(parser):
    pass


def mk_parser():
    # add_help=False, fall through does full help, initial doesn't need
    parser = argparse.ArgumentParser(description="control", add_help=False)
    add_options(parser, Context.option_list())
    parser.add_argument(
        "--version",
        action="version",
        version="{}s version {}".format("%(prog)", ctl.__version__),
    )
    ctl_options(parser)
    return parser


def mk_operation_parser(ctlr, sub_parser, name, plugin_config):
    """
    adds to argparser for configured plugin instances
    """

    plugin_class = ctl.plugin.get_plugin_class(plugin_config["type"])

    # only list if it has execute method
    if not hasattr(plugin_class, "execute"):
        return False

    descr = plugin_config.get("description", None)
    if not descr and plugin_class.__doc__:
        descr = plugin_class.__doc__.lstrip().splitlines()[0]

    # add subcommand from plugin
    op_parser = sub_parser.add_parser(name, help=descr)
    ctl.plugin_cli_arguments(ctlr, op_parser, plugin_config)


def mk_parser_all(ctlr):
    """
    makes a parser with all plugins loaded and help for all applied
    """
    parser = mk_parser()
    sub_parser = parser.add_subparsers(title="[ALL] Configured Operations")

    for plugin_config in ctlr.ctx.config.get_nested("ctl", "plugins"):
        mk_operation_parser(ctlr, sub_parser, plugin_config.get("name"), plugin_config)

    return parser


def exit_full_help(ctlr, exit=1):
    parser = mk_parser_all(ctlr)
    parser.print_help()

    print("\nPlugins")
    for name, cls in plugin.registry.items():
        if cls.__doc__:
            descr = cls.__doc__.lstrip().splitlines()[0]
        else:
            descr = ""
        print("  {}\t{}".format(name, descr))

    if exit:
        sys.exit(exit)


def main(argv=sys.argv, run=True):
    parser = mk_parser()
    # make it not exit on anything and just get the first arg
    parser.add_argument("ctl_operation", nargs="?")

    try:
        args, unknown = parser.parse_known_args(args=argv[1:])

    except Exception as e:
        ctlr.log.error("unknown arg error: {}".format(e))
        raise

    # update cli context with options/arguments before
    # using it to instantiate Ctl instance
    ctx = Context()
    ctx.tmpl["env"].update(input={"ctl": args.__dict__})
    ctx.update_options(args.__dict__)

    ctlr = Ctl(ctx, full_init=False)

    argd = vars(args)
    operation = argd["ctl_operation"]

    if not operation:
        exit_full_help(ctlr)

    # rebuild argparse with plugin's correct options
    # reparse to get plugin args
    # differs from mk_parser_all in that it doesn't need to load all every configured plugin
    parser = mk_parser()
    sub_parser = parser.add_subparsers(
        title="Configured Operations", dest="ctl_operation"
    )

    try:
        mk_operation_parser(
            ctlr, sub_parser, operation, ctlr.get_plugin_config(operation)
        )

    except ValueError as exc:
        if "{}".format(exc).find("unknown plugin") > -1:
            ctlr.log.error("unknown operation: {}".format(operation))
            exit_full_help(ctlr)
        else:
            raise

    # TODO add help plugin to inspect plugins

    try:
        args, unknown = parser.parse_known_args(args=argv[1:])
        # ctlr.log.debug("unknown args {}".format(unknown))

    except Exception as e:
        ctlr.log.error("argparser {}".format(e))
        if ctx.debug:
            raise
        return 1

    ctx.tmpl["env"]["input"].update(plugin=args.__dict__)
    ctx.tmpl["env"]["config"] = ctx.config

    # read config with plugin input vars now exposed
    ctlr.ctx.read_config()
    # re-expose plugin vars
    ctlr.expose_plugin_vars()
    # final read of config with everything in place
    ctlr.ctx.read_config()

    try:
        ctlr.init()
    except ConfigError as exc:
        sys.exit(1)

    try:
        plugin_obj = ctlr.get_plugin(operation)

    except Exception as e:
        ctlr.log.error("operation `{}` raised exception: {}".format(operation, e))
        if ctx.debug:
            raise
        return 1

    # this shouldn't be here, it lets a plugin modify ctl options
    # ctx.update_options(vars(args))
    try:
        ctlr.usage_log.info("ran command: `{}`".format(" ".join(argv[1:])), typ="usage")
        plugin_obj.execute(**vars(args))
    except PluginOperationStopped as exc:
        exc.plugin.log.error(u"{}".format(exc))
        sys.exit(1)
    except Exception as e:
        ctlr.log.error("command error {}".format(e))
        ctlr.log.error(traceback.format_exc())
        if ctx.debug:
            raise
    finally:
        common_events.trigger("exit")
