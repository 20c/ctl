import logging

from util import instantiate_test_plugin

from ctl.log import ATTACHED
from ctl.plugins.log import LogPlugin


def test_init():
    plugin = instantiate_test_plugin("log", "test_log")
    assert plugin.loggers == []


def test_logger(tmpdir):
    # create temp file to log messages to
    logfile = tmpdir.join("test.log")

    # logger config as passed to the plugin
    logger_config = {
        "logger": "a_logger",
        "file": str(logfile),
        "format": "%(message)s",
    }
    config = {"config": {"loggers": [logger_config]}}

    # instantiate plugin
    plugin = instantiate_test_plugin("log", "test_log", **config)

    # check that it was attached to the logger specified in config
    assert ATTACHED["a_logger"] == [plugin]

    # log a message to test that the logger was configured through
    # plugin
    logging.getLogger("a_logger").error("test")

    assert logfile.read() == "test\n"
