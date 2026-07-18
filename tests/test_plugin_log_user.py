import os
import pwd

from util import instantiate_test_plugin


def test_apply():
    username = pwd.getpwuid(os.getuid()).pw_name
    plugin = instantiate_test_plugin("log_user", "test_log_user")

    assert plugin.username == username

    assert plugin.apply("this is a test") == f"{username} - this is a test"
