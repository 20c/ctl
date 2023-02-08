"""
Plugin that allows you send notification for log events
"""

import ctl
from ctl.plugins.log import LogPlugin


@ctl.plugin.register("log_alert")
class LogAlertPlugin(LogPlugin):

    """
    send notifications on log events

    # Instanced Attributes

    - messages (`list`): list of messages that triggered a notification
    """

    def init(self):
        super().init()
        self.messages = []

    def alert(self, **kwargs):
        """
        Send alert through another plugin

        **Keyword arguments**

        - levels (`list`): list of logging levels that will cause
          triggering of this alert. As soon as there is at least
          one message with the appropriate level the alert will
          be sent
        - plugin (`str`): name of plugin instance to use to facilitate
          the alert. Plugin needs to have an `alert` method
        - output_levels (`list`): allows you to specify which levels to
          collect into the output message. If not specified will default
          to the `levels` list.
        """

        levels = kwargs.get("levels", [])
        plugin_name = kwargs.get("plugin")
        output_levels = kwargs.get("output_levels", levels)

        plugin = self.other_plugin(plugin_name)
        if not plugin:
            raise Exception(f"Plugin instance not found: {plugin_name}")

        if not hasattr(plugin, "alert"):
            raise Exception(f"{plugin_name} Plugin has no `alert` method")

        # collect messages into here
        collected = []
        # will be true if the alert was triggered
        triggered = False

        # cycle through all messages to see if there is any message
        # with an appropriate level to trigger this alert
        for level, message in self.messages:
            if not levels or level.lower() in levels:
                triggered = True
                break

        if not triggered:
            self.log.debug("No messages to send")
            return

        # cycle through all messages and collect messages according
        # to levels specified in `output_levels`
        for level, message in self.messages:
            if not output_levels or level.lower() in output_levels:
                collected.append(message)

        # send alert
        plugin.alert("\n".join(collected))

        # reset messages (configurable?)
        self.messages = []

    def finalize(self, message, level):
        self.messages.append((level, message))
