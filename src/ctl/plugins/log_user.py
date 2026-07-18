"""
Plugin that allows you to append user information to log messages
"""

import os
import pwd

import ctl
from ctl.plugins.log import LogPlugin


@ctl.plugin.register("log_user")
class LogUserPlugin(LogPlugin):
    """
    append user information to log messages

    # Instanced Attributes

    - username (`str`): username
    """

    def init(self):
        super().init()
        self.username = pwd.getpwuid(os.getuid()).pw_name

    def apply(self, message):
        """
        Augment log message with user information

        **Arguments**

        - message (`str`): log message

        **Returns**

        Augmented log message (`str`)
        """

        prefix = f"{self.username}"
        return f"{prefix} - {message}"
