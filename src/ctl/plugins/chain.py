"""
A plugin that allows you to execute other plugins in a chain
"""


import collections

import confu.schema

import ctl
import ctl.config
from ctl.docs import pymdgen_confu_types


@pymdgen_confu_types()
class ChainActionConfig(confu.schema.Schema):
    """
    Confu schema describes a plugin action
    """

    name = confu.schema.Str(
        default="execute", help="call this action on the plugin instance (method name)"
    )
    arguments = confu.schema.Schema(item=confu.schema.Str(), help="arguments to pass")


@pymdgen_confu_types()
class ChainConfig(confu.schema.Schema):
    """
    Confu schema describes a stage in the chain
    """

    stage = confu.schema.Str(help="user friendly name of the stage in the chain")
    plugin = confu.schema.Str(help="plugin instance name")
    action = ChainActionConfig(help="plugin action")


@pymdgen_confu_types()
class ChainPluginConfig(confu.schema.Schema):
    """
    Confu schema for the chain plugin
    """

    arguments = confu.schema.List(
        item=ctl.config.ArgparseSchema(), cli=False, help="cli parameters for the chain"
    )
    chain = confu.schema.List(item=ChainConfig(), cli=False, help="stages in the chain")
    vars = confu.schema.Dict(
        item=confu.schema.Str(blank=True), cli=False, help="extra variables"
    )


@ctl.plugin.register("chain")
class ChainPlugin(ctl.plugins.ExecutablePlugin):

    """
    chain execute other plugins

    # Instanced Attributes

    - start (`int`): start at this stage
    - end (`int`): end at this stage
    """

    class ConfigSchema(ctl.plugins.PluginBase.ConfigSchema):
        config = ChainPluginConfig("config")

    @classmethod
    def expose_vars(cls, env, plugin_config):
        """
        Expose contents of `vars` config attribute to the
        submitted environment

        **Argument(s)**

        - env (`dict`)
        - plugin_config (`dict`)
        """

        env.update(plugin_config.get("vars"))
        return {}

    @classmethod
    def add_arguments(cls, parser, plugin_config, confu_cli_args):
        """
        Set CLI Arguments

        *overrides `PluginBase.add_arguments`*
        """

        parser.add_argument("--end", type=str, help="stop at this stage")
        parser.add_argument("--start", type=str, help="start at this stage")
        ctl.config.ArgparseSchema().add_many_to_parser(
            parser, plugin_config.get("arguments")
        )

    def execute(self, **kwargs):
        """
        Execute the plugin

        **Keyword Arguments**

        - start (`int`): starting stage
        - end (`int`): ending stage

        *overrides and calls `ExecutablePlugin.execute`*
        """

        super().execute(**kwargs)
        self.chain = chain = self.get_config("chain")
        self.end = kwargs.get("end")
        self.start = kwargs.get("start")
        self.execute_chain(chain)

    def execute_chain(self, chain):
        """
        Execute a plugin chain from ChainConfig dict

        **Arguments**

        - chain (`list<dict>`): list of chain configs (see `ChainConfig`)
        """

        self.validate_stage(self.end)
        self.validate_stage(self.start)

        total = len(chain)
        num = 1
        started = True

        if self.start:
            started = False

        for stage in chain:
            if self.start == stage["stage"]:
                started = True
            if not started:
                self.log.info("skip {}".format(stage["stage"]))
                continue
            self.execute_stage(stage, num, total)
            num += 1
            if self.end == stage["stage"]:
                self.log.info(f"end {self.end}")
                return

        self.log.info(f"completed chain `{self.plugin_name}`")

    def execute_stage(self, stage, num=1, total=1):
        """
        Execute a stage

        **Arguments**

        - stage (`dict`): chain config (see `ChainConfig`)
        - num (`int`): stage number in the chain
        - total (`int`): total stages in the chain
        """

        self.log.info(
            "exec {stage} [{num}/{total}]".format(s=self, num=num, total=total, **stage)
        )
        plugin = self.other_plugin(stage["plugin"])
        fn = getattr(plugin, stage["action"]["name"], None)
        if not isinstance(fn, collections.abc.Callable):
            raise AttributeError(
                "Action `{action.name}` does not exist in plugin `{plugin}".format(
                    **stage
                )
            )

        kwargs = {}
        for name, value in list(stage["action"].get("arguments", {}).items()):
            kwargs[name] = self.render_tmpl(value)

        fn(**kwargs)

    def validate_stage(self, name):
        """
        Validate stage by name, will raise a `ValueError` on failure to validate

        **Arguments**

        - name (`str`)
        """

        if not name:
            return

        for stage in self.chain:
            if stage.get("stage") == name:
                return
        raise ValueError(f"Invalid stage speciefied - does not exist: {name}")
