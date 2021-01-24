import os
import pwd

from util import instantiate_test_plugin

from ctl.plugins.log_user import LogUserPlugin


def test_apply():
    username = pwd.getpwuid(os.getuid()).pw_name
    plugin = instantiate_test_plugin("log_user", "test_log_user")

    assert plugin.username == username

    assert plugin.apply("this is a test") == "{username} - this is a test".format(
        username=username
    )
