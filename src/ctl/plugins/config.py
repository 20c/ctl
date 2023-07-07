import confu
import munge

import ctl


class ConfigPluginConfig(confu.schema.Schema):
    """
    configuration schema for command plugin
    """

    format = confu.schema.Str("format", default="yaml", help="output format")


def option_name(path, delimiter="--"):
    """returns a cli option name from attribute path"""
    return "--{}".format(delimiter.join(path).replace("_", "-"))


def destination_name(path, delimiter="__"):
    """returns a cli option destination name from attribute path"""
    return f"{delimiter.join(path)}"


def list_options(schema):
    rv = []

    def optionize(attribute, path):
        if not attribute.cli:
            return

        kwargs = {
            "type": lambda x: attribute.validate(x, path),
            "help": attribute.help,
            "dest": destination_name(path),
            "default": attribute.default,
        }

        name = option_name(path, delimiter=".")

        finalize = getattr(attribute, "finalize_argparse", None)
        if finalize:
            name = finalize(kwargs, name)
        kwargs["name"] = name
        rv.append(kwargs)

    schema.walk(optionize)
    print(rv)
    return rv


@ctl.plugin.register("config")
class ConfigPlugin(ctl.plugins.PluginBase):
    """
    ctl config tool
    """

    ConfigSchema = ConfigPluginConfig

    def init(self):
        self.ConfigSchema = self.ConfigSchema()

    @classmethod
    def option_list(cls):
        return list_options(cls.ConfigSchema())

    def execute(self, command=None, **kwargs):
        fmt = kwargs.get("format")
        ctx = self.ctl.ctx
        print(f"current config from {ctx.home}")
        fmt = "yml"
        codec = munge.get_codec(fmt)()
        print(codec.dumps(ctx.config.data))
