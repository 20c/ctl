# TODO py3 implements PermissionError, probably extend that?
class PermissionDenied(Exception):
    def __init__(self, grainy_namespace, level):
        super(PermissionDenied, self).__init__(
            "You do not have '{}' permission to this namespace: {}".format(
                level, grainy_namespace
            )
        )


class OperationNotExposed(Exception):
    def __init__(self, op):
        super(OperationNotExposed, self).__init__("{} is not exposed".format(op))


class UsageError(ValueError):
    """
	ctl operation usage error
	"""
    pass


class ConfigError(ValueError):
    pass


class PluginOperationStopped(ValueError):
    """
    Can be raised during plugin operation for a clean exit that logs
    an error message
    """
    def __init__(self, plugin, details):
        """
        **Arguments**

        - plugin: plugin instance
        - details(`str`): error message
        """
        super(PluginOperationStopped, self).__init__(details)
        self.details = details
        self.plugin = plugin

    def __str__(self):
        return u"Plugin operation stopped: {}".format(self.details)
