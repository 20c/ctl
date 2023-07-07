import collections
import re
from functools import wraps

from grainy.core import int_flags

from ctl.exceptions import PermissionDenied


class expose:

    """
    Decorator to expose a ctl plugin's method - permissions will be checked before
    method is executed
    """

    def __init__(self, namespace, level=None, explicit=False):
        """
        **Keyword Arguments**

        - namespace (`str`): permissioning namespace, has the following formatting
          variables available:
              - `plugin`: the plugin instance
              - `plugin_name`: name of the plugin instance as defined in config
              - any arguments passed to the method by argument name
        - level (`function`|`str`|`None`): permission level to check.
              - If a function is passed it is expected to return a permission level
                string. The function will be passed the plugin instance as an argument.
              - If a string is passed it is expected to be a permission level string
              - If None is passed, permission level will be obtained from the plugin's
                config and default to `r`
        - explicit (`bool`=`False`): If true will enable explicit namespace checking
        """

        self.namespace = namespace
        self.level = level
        self.explicit = explicit

    def __call__(self, fn):
        level = self.level
        namespace_ = self.namespace
        explicit = self.explicit

        @wraps(fn)
        def wrapped(self, *args, **kwargs):
            # format the namespace using the plugin instance
            # and any arguments passed to the decorated method
            namespace_args = {
                "plugin": self,
                "plugin_name": self.pluginmgr_config.get("name"),
            }
            namespace_args.update(**kwargs)
            namespace = namespace_.format(**namespace_args)

            # obtain required permission level
            if level is None:
                # level is not specified at all in the decorator,
                # in which case we obtain from plugin config and default to 'r'
                permissions = self.config.get("permissions", {}).get(fn.__name__, "r")
            elif isinstance(level, collections.abc.Callable):
                # level is specified and a function, call it and set from there
                permissions = level(self)
            else:
                # level is specified and will be taken from decroator directly
                permissions = level

            # check permissions
            allowed = self.ctl.permissions.check(
                namespace, int_flags(permissions), explicit=explicit
            )

            # raise on permission check failure
            if not allowed:
                raise PermissionDenied(namespace, permissions)

            # execute method
            return fn(self, *args, **kwargs)

        doc = []
        doc_indent = 0

        if fn.__doc__:
            doc.append(fn.__doc__)
            m = re.search(r"(\s+)", fn.__doc__)
            if m:
                doc_indent = m.group(1)

        doc.extend(
            [
                f'{doc_indent}!!! note "Exposed to CLI"',
                f"{doc_indent}    namespace: `{namespace_}`",
            ]
        )

        wrapped.__doc__ = "\n".join(doc)
        wrapped.exposed = True
        return wrapped
