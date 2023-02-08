"""
Plugin that allows you to manipulate logging functionality
"""


import logging

import confu.generator
import confu.schema

import ctl
from ctl.docs import pymdgen_confu_types
from ctl.log import ATTACHED


@pymdgen_confu_types()
class LogPluginLoggerConfig(confu.schema.Schema):
    """
    Configuration schema for `LogPluginLogger`
    """

    logger = confu.schema.Str(help="logger name")
    file = confu.schema.Str(default="", help="configure handler to log to this file")
    format = confu.schema.Str(
        default="[%(asctime)s] %(message)s", help="configure formatting for logger"
    )


@pymdgen_confu_types()
class LogPluginConfig(ctl.plugins.PluginBase.ConfigSchema):
    """
    Configuration schema for `LogPlugin`
    """

    loggers = confu.schema.List(
        "loggers", LogPluginLoggerConfig(), help="attach plugin to these loggers"
    )


@ctl.plugin.register("log")
class LogPlugin(ctl.plugins.PluginBase):

    """
    manipulate message logging

    **Instanced Attributes**

    - loggers(`list`): list of loggers this plugin is attached to
    """

    class ConfigSchema(ctl.plugins.PluginBase.ConfigSchema):
        config = LogPluginConfig()

    def init(self):
        loggers = self.config.get("loggers", [])

        for logger_config in loggers:
            logger_name = logger_config.get("logger")
            self.attach_to_logger(logger_name)
            self.configure_logger(logger_name, logger_config)

        self.loggers = loggers

    def configure_logger(self, logger_name, logger_config):
        """
        Configure python logger from plugin config

        If your logger config attribute specifies things like formatting
        and handlers the targeted logger will be configured accordingly

        This is called automatically during `init`

        **Arguments**

        - logger_name (`str`)
        - logger_confug (`dict`): see [LogPluginLoggerConfig](#logpluginloggerconfig)
        """

        filename = logger_config.get("file")
        logger = logging.getLogger(logger_name)
        if filename:
            formatter = logger_config.get(
                "format", LogPluginLoggerConfig.format.default
            )
            fh = logging.FileHandler(filename=filename, mode="a+")
            fh.setFormatter(logging.Formatter(formatter))
            logger.addHandler(fh)

    def attach_to_logger(self, logger_name):
        """
        Attach plugin to python logger

        **Arguments**

        - logger_name (`str`)
        """
        # attach log plugin to loggers
        if logger_name not in ATTACHED:
            ATTACHED[logger_name] = [self]
        else:
            ATTACHED[logger_name].append(self)

    def apply(self, message, level):
        """
        Apply changes to an incoming message

        **Arguments**

        - message (`str`)
        - level (`str`): logging severity level

        **Returns**

        modified message (`str`)
        """
        return message

    def finalize(self, message, level):
        """
        Finalize before message is logged

        **Arguments**

        - message (`str`)
        - level (`str`): logging severity level
        """

        pass
