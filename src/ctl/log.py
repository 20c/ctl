import logging
import logging.config

from ctl.events import common_events


def default_pylogger_config(name="ctl"):
    """
    The defauly python logging setup to use when no `log` config
    is provided via the ctl config file
    """
    return {
        "version": 1,
        "formatters": {"default": {"format": "[%(asctime)s] %(message)s"}},
        "handlers": {
            "console": {
                "level": "INFO",
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            }
        },
        "loggers": {
            name: {"level": "INFO", "handlers": ["console"]},
            "usage": {"level": "INFO", "handlers": ["console"]},
        },
    }


def set_pylogger_config(config=None):
    """
    setup python logging from config dict
    """
    if not config:
        config = default_pylogger_config()
    logging.config.dictConfig(config)


ATTACHED = {}


class Log:
    def __init__(self, name="ctl"):
        self._log = logging.getLogger(name)
        self.name = name

    def log(self, level, msg, typ=None):
        common_events.trigger(f"{self.name}-log-write-before")
        plugins = []

        plugins = ATTACHED.get(typ or self.name, [])

        for plugin in plugins:
            msg = plugin.apply(msg, level)

        msg = f"[{self.name}] {msg}"
        fn = getattr(self._log, level)
        fn(msg)

        for plugin in plugins:
            plugin.finalize(msg, level)

        common_events.trigger(f"{self.name}-log-write-after")

    def debug(self, msg, typ=None):
        self.log("debug", msg, typ=typ)

    def info(self, msg, typ=None):
        self.log("info", msg, typ=typ)

    def warning(self, msg, typ=None):
        self.log("warning", msg, typ=typ)

    def error(self, msg, typ=None):
        self.log("error", msg, typ=typ)
