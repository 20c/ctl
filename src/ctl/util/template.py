import re

try:
    import jinja2

    class VariableString(dict):
        """
        Will render the variable string back to the template
        so other renderers can render it later if needed
        """

        def __init__(self, name, *args, **kwargs):
            self.name = name
            super().__init__(*args, **kwargs)

        def __getattr__(self, k):
            try:
                return super().__getattr__(k)
            except AttributeError:
                return VariableString(f"{self.name}.{k}")

        def __str__(self):
            return "{{ " + self.name + " }}"

    class IgnoreUndefined(jinja2.Undefined):

        """
        Will ignore certain undefined variables and keep
        their variable names in place so they can be rendered
        later
        """

        names = ["input", "kwargs", "plugin"]

        def __getattr__(self, k):
            if self._undefined_name in self.names:
                return VariableString(f"{self._undefined_name}.{k}")
            return super().__getattr__(k)

        def _fail_with_undefined_error(self, *args, **kwargs):
            if self._undefined_name in self.names:
                return VariableString(self._undefined_name)
            print(("_undefined", self._undefined_name, self.names))
            return super()._fail_with_undefined_error(*args, **kwargs)

        __add__ = (
            __radd__
        ) = (
            __mul__
        ) = (
            __rmul__
        ) = (
            __div__
        ) = (
            __rdiv__
        ) = (
            __truediv__
        ) = (
            __rtruediv__
        ) = (
            __floordiv__
        ) = (
            __rfloordiv__
        ) = (
            __mod__
        ) = (
            __rmod__
        ) = (
            __pos__
        ) = (
            __neg__
        ) = (
            __call__
        ) = (
            __getitem__
        ) = (
            __lt__
        ) = (
            __le__
        ) = (
            __gt__
        ) = (
            __ge__
        ) = (
            __int__
        ) = (
            __float__
        ) = (
            __complex__
        ) = __pow__ = __rpow__ = __sub__ = __rsub__ = _fail_with_undefined_error

except ImportError:

    class IgnoreUndefined:
        pass


def filter_escape_regex(value, **kwargs):
    """
    template filter that escapes a regex value
    """
    return re.escape(value)
