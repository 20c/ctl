import copy

import confu.exceptions
import confu.generator
import confu.schema
import grainy.core


class Permission(confu.schema.Str):
    """
    for permission values
    """

    def validate(self, value, path, **kwargs):
        value = super().validate(value, path, **kwargs)
        if not grainy.core.int_flags(value):
            raise confu.exceptions.ValidationError(
                self, path, value, "valid permission flags required"
            )

        return value


class PermissionSchema(confu.schema.Schema):
    """
    Configuration schem for permissions
    """

    namespace = confu.schema.Str("namespace", help="Permissioning namespace")

    permission = Permission("permission", help="Permissioning level")


class PluginProxySchema(confu.schema.ProxySchema):
    """
    Will properly route plugin validation to the correct
    plugin schema
    """

    def schema(self, config):
        import ctl

        return ctl.plugin.get_plugin_class(config["type"]).ConfigSchema()

    def validate(self, config, path=None, errors=None, warnings=None):
        path[-1] = config["name"]
        return self.schema(config).validate(
            config, path=path, errors=errors, warnings=warnings
        )


class CTLSchema(confu.schema.Schema):
    """
    Configuration schema for ctl config
    """

    plugin_path = confu.schema.List(
        "plugin_path",
        confu.schema.Directory("plugin_path.item"),
        help="list of directories to search for plugins",
    )

    permissions = confu.schema.List(
        "permissions", PermissionSchema(), help="list of permissions"
    )

    plugins = confu.schema.List(
        "plugins", PluginProxySchema(), help="list of plugin config objects"
    )


class SMTPConfigSchema(confu.schema.Schema):
    host = confu.schema.Str("host", default="localhost")


class ArgparseSchema(confu.schema.Schema):
    """
    Defines an argparse argument
    """

    name = confu.schema.Str("name", help="argument name")
    help = confu.schema.Str("help", default="", blank=True, help="help text")
    choices = confu.schema.List("choices", confu.schema.Str(), help="value choices")
    nargs = confu.schema.Str("nargs", default="?")
    type = confu.schema.Str("type", default="str")

    def add_to_parser(self, parser, config):
        """
        Adds an argument to a parser instance

        Arguments:
            - parser: argparse parser
            - config: dict holding config variables for one argument
        """
        _config = copy.deepcopy(config)
        typ = __builtins__.get(_config.pop("type"))
        name = _config.pop("name")
        choices = _config.pop("choices") or None
        parser.add_argument(name, type=typ, choices=choices, **_config)

    def add_many_to_parser(self, parser, configs):
        """
        Adds many arguments to a parser instance

        Arguments:
            - parser: argparse parser
            - configs: list holding dicts with each dict holding
                config variables for one argument
        """
        for config in configs:
            self.add_to_parser(parser, config)


class BaseSchema(confu.schema.Schema):
    """
    Configuration schema for root config
    """

    class config(confu.schema.Schema):
        """
        Sub schema for ctl config
        """

        ctl = CTLSchema("ctl")
