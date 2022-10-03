"""
Plugin that allows you to render templates

## Requirements

`pip install tmpl jinja`
"""


import collections
import os

import confu.schema
import munge

import ctl

try:
    import tmpl
except ImportError:
    tmpl = None

from ctl.docs import pymdgen_confu_types
from ctl.plugins.copy import CopyPlugin, CopyPluginConfig


@pymdgen_confu_types()
class TemplatePluginConfig(CopyPluginConfig):
    """
    Configuration schema for `TemplatePlugin`
    """

    engine = confu.schema.Str(
        default="jinja2", choices=["jinja2"], help="template engine"
    )
    vars = confu.schema.List(
        item=confu.schema.Str(),
        cli=False,
        help="list of files containing template " "variables to import",
    )


def update(a, b):
    for key, value in list(b.items()):
        if isinstance(value, collections.abc.Mapping):
            a[key] = update(a.get(key, {}), value)
        else:
            a[key] = value
    return a


@ctl.plugin.register("template")
class TemplatePlugin(CopyPlugin):

    """
    render all template files from a source director into an output
    directory
    """

    class ConfigSchema(CopyPlugin.ConfigSchema):
        config = TemplatePluginConfig("config")

    @classmethod
    def expose_vars(cls, env, plugin_config):
        """
        Loop through the files specified in the `vars` plugin config property
        and expose them to the config template environment

        Note that this is different than the `load_vars` method which will
        expose the same vars to the template environment for rendering
        the templates

        **Arguments**

        - env (`dict`): template environment
        - plugin_config (`dict`)

        **Returns**

        `dict<filepath, error>`: dict of ioerrors mapped to filepath
        """

        errors = {}

        for filepath in plugin_config.get("vars", []):
            ext = os.path.splitext(filepath)[1][1:]
            codec = munge.get_codec(ext)
            try:
                with open(filepath) as fh:
                    data = codec().load(fh)
                update(env, data)
            except OSError as exc:
                errors[filepath] = exc
        return errors

    @property
    def tmpl_env(self):
        """
        template environment
        """
        return self._tmpl_env

    @property
    def engine(self):
        """
        template engine instance
        """
        if not hasattr(self, "_engine"):
            self._engine = tmpl.get_engine(self.config.get("engine"))(
                tmpl_dir=self.source()
            )
        return self._engine

    def prepare(self, **kwargs):
        super().prepare(**kwargs)
        self.debug_info["rendered"] = []
        self._tmpl_env = {}
        self.load_vars()

    def execute(self, **kwargs):
        super().execute(**kwargs)

    def load_vars(self):
        """
        Loop through the files specified in the `vars` plugin config property
        and expose them to the template environment
        """

        update(self._tmpl_env, self.ctl.ctx.tmpl["env"])
        for filepath in self.get_config("vars"):
            ext = os.path.splitext(filepath)[1][1:]
            codec = munge.get_codec(ext)
            with open(self.render_tmpl(filepath)) as fh:
                data = codec().load(fh)
            update(self._tmpl_env, data)

    def copy_file(self, path, dirpath):
        # Since we are extending the copy plugin we hijack
        # the `copy_file` method to invoke the template
        # rendering from source to output using a relative
        # file path

        self.template_file(path)

    def template_file(self, path):
        """
        Render the template from source to output using
        a relative file path

        **Arguments**

        - path(`str`): relative (to source or output) template file path
        """

        out_dir = os.path.dirname(self.output(path))
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        self.log.info(self.output(path))
        self.engine.render(path, out_dir=self.output(), env=self.tmpl_env)
        self.debug_append("rendered", self.output(path))

        os.chmod(self.output(path), os.stat(self.source(path)).st_mode)
