import os
import pwd

import ctl
from ctl.plugins import PluginBase
from util import instantiate_test_plugin


class GitDummy(PluginBase):
    def init(self):
        self.uuid = "deadbeef"
        self.version = 123


def test_apply():
    username = pwd.getpwuid(os.getuid()).pw_name

    config = {"config": {"git": "git_dummy"}}

    ctl.plugin._instance["git_dummy"] = GitDummy({}, None)

    plugin = instantiate_test_plugin("log_git", "test_log_git", **config)

    assert plugin.apply("test", "error") == f"deadbeef:123 {username} - test"
