import pytest

import ctl
from ctl.log import Log
from ctl.plugins import PluginBase
from util import instantiate_test_plugin


class DummyAlert(PluginBase):
    def init(self):
        self.alerts = []

    def alert(self, msg):
        self.alerts = msg.split("\n")


@pytest.mark.parametrize(
    "logged,alerted,levels,output_levels",
    [
        # Test 1 - log info and error, dont specify collection levels or trigger
        # levels - meaning all messages trigger the alert and all are alerted
        (["error", "info"], ["error", "info"], [], []),
        # Test 2 - log info and error, only trigger on error, alert both
        (["error", "info"], ["error", "info"], ["error"], []),
        # Test 3 - log info and error, only trigger on error, only alert error
        (["error", "info"], ["error"], ["error"], ["error"]),
    ],
)
def test_init_and_collect(logged, alerted, levels, output_levels):
    # create temp file to log messages to
    dummy_alert = ctl.plugin._instance["dummy_alert"] = DummyAlert({}, None)
    logger_name = "a_logger"

    # logger config as passed to the plugin
    logger_config = {"logger": logger_name, "format": "%(message)s"}
    config = {"config": {"loggers": [logger_config]}}

    # instantiate plugin
    plugin = instantiate_test_plugin("log_alert", "test_log", **config)

    log = Log(logger_name)

    for fn in logged:
        getattr(log, fn)(fn.upper())

    collected = [(level, f"[{logger_name}] {level.upper()}") for level in logged]
    alerted = [f"[{logger_name}] {level.upper()}" for level in alerted]

    assert plugin.messages == collected

    plugin.alert(plugin="dummy_alert", levels=levels, output_levels=output_levels)

    print(dummy_alert.alerts)

    assert dummy_alert.alerts == alerted
