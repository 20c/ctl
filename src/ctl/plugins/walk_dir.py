"""
A plugin that lets you traverse a directory and process it's files
and sub-directories
"""


import os
import re

import confu.schema

import ctl
from ctl.docs import pymdgen_confu_types


@pymdgen_confu_types()
class MatchConfig(confu.schema.Schema):

    """
    Configuration schema that maps a plugin
    action to a regex pattern
    """

    pattern = confu.schema.Str(help="regex pattern")
    plugin = confu.schema.Str(default="self", help="plugin name")
    action = confu.schema.Str(help="plugin action (method name)")


@pymdgen_confu_types()
class WalkDirPluginConfig(confu.schema.Schema):

    """
    Configuration schema for the walkdir plugin
    """

    # TODO: source should be a Directory attribute, but as it stands sometimes
    # the directory might be missing during validation, and may be created during
    # runtime by another plugin.

    source = confu.schema.Str(help="source directory")
    output = confu.schema.Str(help="output directory")

    walk_dirs = confu.schema.List(
        item=confu.schema.Str(),
        cli=False,
        help="subdirectories to walk and process files in",
    )

    ignore = confu.schema.List(
        item=confu.schema.Str(),
        cli=False,
        help="regex patterns that if matched will cause a file or directory to be ignored",
    )

    process = confu.schema.List(
        item=MatchConfig(), cli=False, help="pattern matches to plugin actions"
    )

    debug = confu.schema.Bool(default=False, help="debug mode")
    skip_dotfiles = confu.schema.Bool(default=True, help="Skip dot files")


@ctl.plugin.register("walk_dir")
class WalkDirPlugin(ctl.plugins.ExecutablePlugin):
    """
    walk directories and process files

    # Instanced Attributes

    - debug_info (`dict`): holds various debug information
    - requires_output (`bool=False`): does the plugin require an output to be set?

    """

    class ConfigSchema(ctl.plugins.PluginBase.ConfigSchema):
        config = WalkDirPluginConfig("config")

    def prepare(self, **kwargs):
        """
        prepare plugin for execution

        !!! note "Output directory"
            output directory from `config.output` will be created
            if it does not exist

        *overrides `ExecutablePlugin.prepare`*
        """

        self.debug = self.config.get("debug")
        self.debug_info = {"files": [], "processed": [], "mkdir": []}

        self.requires_output = False
        self._source = self.get_config("source")
        self._output = self.get_config("output")
        self.walk_dirs = self.get_config("walk_dirs")
        self.skip_dotfiles = self.get_config("skip_dotfiles")

        self.log.info(f"Skip dotfiles: {self.skip_dotfiles}")

        if not os.path.exists(self._output):
            os.makedirs(self._output)

    def source(self, path=None):
        """
        Returns the source path

        Plugin's `prepare` method needs to have been called.

        **Keyword Arguments**

        - path (`str`): if specified will join this path
          to the source path and return the result

        **Returns**

        source path (`str`)
        """

        if path:
            return os.path.join(self._source, path)
        return self._source

    def output(self, path=None):
        """
        Returns the output path

        Plugin's `prepare` method needs to have been called.

        **Keyword Arguments**

        - path (`str`): if specified will join this path
          to the output path and return the result

        **Returns**

        output path (`str`)
        """

        if not self._output:
            return path
        if path:
            return os.path.join(self._output, path)
        return self._output

    def execute(self, **kwargs):
        """
        Execute the plugin

        *overrides and calls `ExecutablePlugin.execute`*
        """

        super().execute(**kwargs)

        if not self._output and self.requires_output:
            raise ValueError("No output directory specified")

        if not self._source:
            raise ValueError("No source directory specified")

        if self._output:
            self._output = self.render_tmpl(self._output)

        self._source = self.render_tmpl(self._source)

        self.source_regex = rf"^{self.source()}/"

        self.process_files()

    def process_files(self):
        """
        Walks the subdirectories of the source path
        and processes the files.

        Only subdirectories specified in the `walk_dirs`
        config attribute will be considered.
        """

        for subdir in self.walk_dirs:
            for dirpath, dirnames, filenames in os.walk(self.source(subdir)):
                path = re.sub(self.source_regex, "", dirpath)

                for filepath, filename in [
                    (os.path.join(path, _f), _f) for _f in filenames
                ]:
                    if self.skip_dotfiles and filename[0] == ".":
                        continue

                    if not self.ignored(filepath, path):
                        self.prepare_file(filepath, path)
                        self.process_file(filepath, path)

    def prepare_file(self, path, dirpath):
        """
        Prepare a file for processing

        Right now this mainly ensures that the output path
        for the processed file exists by creating it.

        **Argument(s)**

        - path (`str`): relative filepath being processed
        - dirpath (`str`): relative dirpath being processed
        """

        output_dir = os.path.dirname(self.output(path))
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)
            self.debug_append("mkdir", output_dir)

    def process_file(self, path, dirpath):
        """
        Test `MatchConfig` instances set up in the `process`
        config attribute against the provided file path and
        process file according to matches.

        **Argument(s)**

        - path (`str`): relative filepath being processed
        - dirpath (`str`): relative dirpath being processed
        """

        self.debug_append("files", path)

        for process_config in self.get_config("process"):
            plugin = self.other_plugin(process_config.get("plugin"))
            action = process_config.get("action")
            pattern = process_config.get("pattern")
            if re.search(pattern, path) is not None:
                fn = getattr(plugin, action)
                fn(source=self.source(path), output=self.output(path))
                self.debug_append(
                    "processed",
                    {
                        "plugin": process_config.get("plugin"),
                        "source": self.source(path),
                        "output": self.output(path),
                    },
                )

    def ignored(self, path, dirpath):
        """
        Check if a filepath matches any of the patterns set up
        in the `ignore` config attribute

        **Argument(s)**

        - path (`str`): relative filepath being processed
        - dirpath (`str`): relative dirpath being processed

        **Returns**

        `True` if file should be ignored, `False` if not
        """

        for pattern in self.get_config("ignore"):
            if re.search(pattern, path) is not None:
                return True

    def debug_append(self, typ, data):
        if self.debug:
            self.debug_info[typ].append(data)
