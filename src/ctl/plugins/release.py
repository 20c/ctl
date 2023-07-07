"""
Plugin interface for plugins that handle software releases
"""


import argparse
import os

import confu.schema

import ctl
import ctl.config
import ctl.plugins.git
import ctl.plugins.repository
from ctl.auth import expose
from ctl.docs import pymdgen_confu_types
from ctl.plugins import command


@pymdgen_confu_types()
class ReleasePluginConfig(confu.schema.Schema):
    """
    Configuration schema for `ReleasePlugin`
    """

    repository = confu.schema.Str(
        help="repository target for release - should be a path "
        "to a source checkout or the name of a "
        "repository type plugin",
        cli=False,
        default=None,
    )


class ReleasePlugin(command.CommandPlugin):

    """
    base plugin interface for releasing / packaging software
    """

    class ConfigSchema(ctl.plugins.PluginBase.ConfigSchema):
        config = ReleasePluginConfig()

    @classmethod
    def add_arguments(cls, parser, plugin_config, confu_cli_args):
        shared_parser = argparse.ArgumentParser(add_help=False)
        group = shared_parser.add_argument_group()

        group.add_argument(
            "version",
            nargs=1,
            type=str,
            help="release version - if repository is managed by git, "
            "checkout this branch/tag",
        )

        group.add_argument(
            "repository",
            nargs="?",
            type=str,
            default=plugin_config.get("repository"),
            help=ReleasePluginConfig().repository.help,
        )

        sub = parser.add_subparsers(title="Operation", dest="op")

        op_release_parser = sub.add_parser(
            "release", help="execute release", parents=[shared_parser]
        )

        op_release_parser.add_argument(
            "--dry", action="store_true", help="Do a dry run (nothing will be uploaded)"
        )

        op_validate_parser = sub.add_parser(
            "validate", help="validate release", parents=[shared_parser]
        )

        return {
            "group": group,
            "op_release_parser": op_release_parser,
            "op_validate_parser": op_validate_parser,
        }

    def execute(self, **kwargs):
        self.kwargs = kwargs
        self.prepare()
        self.shell = True

        self.set_repository(self.get_config("repository"))
        self.dry_run = kwargs.get("dry")
        self.version = kwargs.get("version")[0]
        self.orig_branch = self.repository.branch

        if self.dry_run:
            self.log.info("Doing dry run...")
        self.log.info(f"Release repository: {self.repository}")

        try:
            self.repository.checkout(self.version)
            op = self.get_op(kwargs.get("op"))
            op(**kwargs)
        finally:
            self.repository.checkout(self.orig_branch)

    def set_repository(self, repository):
        """
        Set release repository. Distributions will be built from that
        repository.

        Currently only supports `git` type repositories

        **Attributes**

        - repository (`str`): can either be the name of a `git` type plugin
        instance or the path to git repository checkout
        """

        if not repository:
            raise ValueError("No repository specified")

        try:
            self.repository = self.other_plugin(repository)
            if not isinstance(self.repository, ctl.plugins.repository.RepositoryPlugin):
                raise TypeError(
                    "The plugin with the name `{}` is not a "
                    "repository type plugin and cannot be used "
                    "as a repository".format(repository)
                )
        except KeyError:
            self.repository = os.path.abspath(repository)
            if not os.path.exists(self.repository):
                raise OSError(
                    "Target is neither a configured repository "
                    "plugin nor a valid file path: "
                    "{}".format(self.repository)
                )

            self.repository = ctl.plugins.git.temporary_plugin(
                self.ctl, f"{self.plugin_name}__tmp_repo", self.repository
            )

        self.cwd = self.repository.checkout_path

    @expose("ctl.{plugin_name}.release")
    def release(self, **kwargs):
        """
        Build, validate and release the package
        """
        self._release(**kwargs)

    @expose("ctl.{plugin_name}.validate")
    def validate(self, **kwargs):
        """
        Build and validate the package
        """
        self._validate(**kwargs)

    def _release(self, **kwargs):
        """should run release logic"""
        raise NotImplementedError()

    def _validate(self, **kwargs):
        """should run build and validation logic"""
        raise NotImplementedError()
