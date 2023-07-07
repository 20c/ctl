"""
Plugin that appends git reposity commit hash and tag version to log messages
"""
import os

import confu.schema

import ctl
from ctl import plugin
from ctl.docs import pymdgen_confu_types
from ctl.plugins.log_user import LogUserPlugin


@pymdgen_confu_types()
class LogGitConfig(LogUserPlugin.ConfigSchema.config.__class__):
    """
    Confguration schema for `LogGitPlugin`
    """

    git = confu.schema.Str(
        help="name of a `git` type plugin to use to obtain uuid and version"
    )


@ctl.plugin.register("log_git")
class LogGitPlugin(LogUserPlugin):

    """
    Augment log message with git information

    **Instanced Arguments**

    - git (`GitPlugin`)
    """

    class ConfigSchema(LogUserPlugin.ConfigSchema):
        config = LogGitConfig()

    def init(self):
        self.git = plugin._instance.get(self.config.get("git"))

        for logger in self.config.get("loggers", []):
            filepath = logger.get("file")
            if filepath and filepath[0] != "/":
                logger["file"] = os.path.join(self.git.checkout_path, filepath)

        super().init()

    def apply(self, message, level):
        """
        Add git information to log message

        **Arguments**

        - message (`str`): log message
        - level (`str`): log severity level
        """
        message = super().apply(message)
        return "{uuid}:{version} {message}".format(
            uuid=self.git.uuid, version=self.git.version, message=message
        )
