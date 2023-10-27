"""
Plugin that allows you to handle repository versioning
"""

import argparse
import os

import confu.schema
import munge

import ctl
import ctl.plugins.git
from ctl.docs import pymdgen_confu_types
from ctl.exceptions import PluginOperationStopped, UsageError
from ctl.plugins import ExecutablePlugin
from ctl.plugins.changelog import ChangelogVersionMissing
from ctl.plugins.changelog import temporary_plugin as temporary_changelog_plugin
from ctl.plugins.repository import RepositoryPlugin
from ctl.util.versioning import version_string


@pymdgen_confu_types()
class VersionBasePluginConfig(confu.schema.Schema):
    """
    Configuration schema for `VersionBasePlugin`
    """

    repository = confu.schema.Str(
        help="name of repository type plugin or path to a repository checkout",
        default=None,
        cli=False,
    )

    branch = confu.schema.Str(
        default="main",
        help="Checkout this branch (this is only relevant when tagging a path instead of a configured repository)",
    )

    changelog_validate = confu.schema.Bool(
        default=True,
        help="If a changelog data file (CHANGELOG.yaml) exists, validate before tagging",
    )


class VersionBasePlugin(ExecutablePlugin):
    """
    manage repository versioning
    """

    class ConfigSchema(ExecutablePlugin.ConfigSchema):
        config = VersionBasePluginConfig()

    @classmethod
    def add_repo_argument(cls, parser, plugin_config):
        """
        The `repository` cli parameter needs to be available
        on all operations. However since it is an optional
        positional parameter that cames at the end using shared
        parsers to implement it appears to be tricky.

        So instead for now we do the next best thing and call this
        class method on all parsers that need to support the repo
        parameter

        **Arguments**

        - parser (`argparse.ArgParser`)
        - plugin_config (`dict`)
        """
        parser.add_argument(
            "repository",
            nargs="?",
            type=str,
            help=VersionBasePluginConfig().repository.help,
            default=plugin_config.get("repository"),
        )

    @classmethod
    def add_arguments(cls, parser, plugin_config, confu_cli_args):
        shared_parser = argparse.ArgumentParser(add_help=False)
        release_parser = argparse.ArgumentParser(add_help=False)
        group = release_parser.add_mutually_exclusive_group(required=False)

        group.add_argument(
            "--init",
            action="store_true",
            help="automatically create " "Ctl/VERSION file if it does not exist",
        )

        # subparser that routes operation
        sub = parser.add_subparsers(title="Operation", dest="op")

        # operation `tag`
        op_tag_parser = sub.add_parser(
            "tag",
            help="tag with a specified version",
            parents=[shared_parser, release_parser],
        )
        op_tag_parser.add_argument(
            "version", nargs=1, type=str, help="version string to tag with"
        )

        confu_cli_args.add(op_tag_parser, "changelog_validate")
        confu_cli_args.add(op_tag_parser, "branch")
        cls.add_repo_argument(op_tag_parser, plugin_config)

        # operation `bump`
        op_bump_parser = sub.add_parser(
            "bump",
            help="bump semantic version",
            parents=[shared_parser, release_parser],
        )
        op_bump_parser.add_argument(
            "version",
            nargs=1,
            type=str,
            choices=["major", "minor", "patch", "prerelease"],
            help="bumps the specified version segment by 1",
        )

        confu_cli_args.add(op_bump_parser, "changelog_validate")
        confu_cli_args.add(op_bump_parser, "branch")
        cls.add_repo_argument(op_bump_parser, plugin_config)

        return {
            "group": group,
            "sub": sub,
            "shared_parser": shared_parser,
            "release_parser": release_parser,
            "op_tag_parser": op_tag_parser,
            "op_bump_parser": op_bump_parser,
        }

    @property
    def init_version(self):
        """
        `True` if a `Ctl/VERSION` file should be created if it's missing
        """
        return getattr(self, "_init_version", False)

    @init_version.setter
    def init_version(self, value):
        self._init_version = value

    def repository(self, target):
        """
        Return plugin instance for repository

        **Arguments**

        - target (`str`): name of a configured repository type plugin
          or filepath to a repository checkout

        **Returns**

        git plugin instance (`GitPlugin`)
        """

        try:
            plugin = self.other_plugin(target)
            if not isinstance(plugin, RepositoryPlugin):
                raise TypeError(
                    "The plugin with the name `{}` is not a "
                    "repository type plugin and cannot be used "
                    "as a target".format(target)
                )
        except KeyError:
            if target:
                target = os.path.abspath(target)
            if not target or not os.path.exists(target):
                raise OSError(
                    "Target is neither a configured repository "
                    "plugin nor a valid file path: "
                    "{}".format(target)
                )

            # pointed to a path, so we need to create a temporary git plugin
            plugin = ctl.plugins.git.temporary_plugin(
                self.ctl, target, target, branch=self.kwargs.get("branch")
            )

        if not self.init_version and not os.path.exists(plugin.version_file):
            raise UsageError(
                "Ctl/VERSION file does not exist. You can set the --init flag to create "
                "it automatically."
            )

        return plugin

    def update_version_files(self, repo_plugin, version, files):
        """
        Finds the various files in a repo that will need to
        have new version values written, such as Ctl/VERSION
        and pyproject.toml
        """

        types = ["ctl", "pyproject"]

        for typ in types:
            fn = getattr(self, f"update_{typ}_version")
            path = fn(repo_plugin, version)
            if path:
                files.append(path)

    def update_ctl_version(self, repo_plugin, version):
        """
        Writes a new version to the Ctl/VERSION files
        """

        with open(repo_plugin.version_file, "w") as fh:
            fh.write(version)
        return repo_plugin.version_file

    def update_pyproject_version(self, repo_plugin, version):
        """
        Writes a new version to the pyproject.toml file
        if it exists
        """

        try:
            pyproject_path = os.path.join(repo_plugin.checkout_path, "pyproject.toml")
            pyproject = munge.load_datafile(
                "pyproject.toml", search_path=(repo_plugin.checkout_path)
            )
            pyproject["tool"]["poetry"]["version"] = version

            codec = munge.get_codec("toml")

            with open(pyproject_path, "w") as fh:
                codec().dump(pyproject, fh)
            return pyproject_path

        except OSError as exc:
            if "not found" in str(exc):
                return

    def validate_changelog(self, repo, version, data_file="CHANGELOG.yaml"):
        """
        Checks for the existance of a changelog data file
        like CHANGELOG.yaml or CHANGELOG.json and
        if found will validate that the specified
        version exists.

        Will raise a KeyError on validation failure

        **Arrguments**

        - version (`str`): tag version (eg. 1.0.0)
        - repo (`str`): name of existing repository type plugin instance
        """

        version = version_string(version)
        repo_plugin = self.repository(repo)

        changelog_path = os.path.join(repo_plugin.checkout_path, data_file)

        if not os.path.exists(changelog_path):
            return

        changelog_plugin = temporary_changelog_plugin(
            self.ctl, f"{self.plugin_name}_changelog", data_file=changelog_path
        )

        self.log.info(f"Found changelog data file at {changelog_path} - validating ...")

        try:
            changelog_plugin.validate(changelog_path, version)
        except ChangelogVersionMissing as exc:
            raise PluginOperationStopped(
                self,
                "{}\nYou can set the --no-changelog-validate flag to skip this check".format(
                    exc
                ),
            )
