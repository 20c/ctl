import confu.schema


class pymdgen_confu_types:
    """
    Decorates a confu schema class to show pretty
    class attribute types when generating docs with
    pymdgen

    TODO: should this maybe live in confu?
    """

    def __init__(self):
        pass

    def __call__(self, cls):
        for name in dir(cls):
            attr = getattr(cls, name)
            if isinstance(attr, confu.schema.Attribute):
                attr.pymdgen_type_info = self.confu_type_info(attr)
        return cls

    def confu_type_info(self, attr):
        attr_name = attr.__class__.__name__
        if getattr(attr, "item", None):
            return f"{attr_name}<{self.confu_type_info(attr.item)}>"
        return attr_name
