# TODO py3 implements PermissionError, probably extend that?
class PermissionDenied(Exception):
    def __init__(self, grainy_namespace, level):
        super().__init__(
            f"You do not have '{level}' permission to this namespace: {grainy_namespace}"
        )


class OperationNotExposed(Exception):
    def __init__(self, op):
        super().__init__(f"{op} is not exposed")


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
        super().__init__(details)
        self.details = details
        self.plugin = plugin

    def __str__(self):
        return f"Plugin operation stopped: {self.details}"
