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
            help="automatically create Ctl/VERSION file if it does not exist",
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

    def execute(self, **kwargs):
        """
        Carries the `--init` cli flag over to `init_version`.

        Without this the flag parses and is passed through as `init`,
        but nothing ever reads it - `repository()` would keep refusing
        a repository without a `Ctl/VERSION` file while pointing at the
        very flag that was just used.
        """

        super().execute(**kwargs)

        if kwargs.get("init"):
            self.init_version = True

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
                    f"The plugin with the name `{target}` is not a "
                    "repository type plugin and cannot be used "
                    "as a target"
                )
        except KeyError:
            if target:
                target = os.path.abspath(target)
            if not target or not os.path.exists(target):
                raise OSError(
                    "Target is neither a configured repository "
                    "plugin nor a valid file path: "
                    f"{target}"
                )

            # pointed to a path, so we need to create a temporary git plugin
            plugin = ctl.plugins.git.temporary_plugin(
                self.ctl, target, target, branch=self.kwargs.get("branch")
            )

        # a repository that keeps its version in pyproject.toml is a
        # valid target even without a Ctl/VERSION file - `--init` is no
        # escape for it, since the untracked Ctl/VERSION it creates
        # shows up in a caller's diff check

        if (
            not self.init_version
            and not os.path.exists(plugin.version_file)
            and not self.pyproject_version(plugin)
        ):
            raise UsageError(
                f"No version found for {plugin.checkout_path}: neither a "
                "Ctl/VERSION file nor a version in pyproject.toml. You can "
                "set the --init flag to create a Ctl/VERSION file "
                "automatically."
            )

        return plugin

    def pyproject_version(self, repo_plugin):
        """
        Returns the version declared in the repository's `pyproject.toml`,
        supporting both Poetry (`[tool.poetry].version`) and PEP 621
        (`[project].version`) layouts.

        **Arguments**

        - repo_plugin (`RepositoryPlugin`)

        **Returns**

        `str` the version, or `None` if there is no `pyproject.toml` or it
        declares no static version (a PEP 621 `dynamic` version has
        nothing to read here)
        """

        # `default` is munge's own contract for "no such file" - matching
        # on the wording of the OSError it would otherwise raise makes this
        # break silently the day that wording changes
        pyproject = munge.load_datafile(
            "pyproject.toml", search_path=repo_plugin.checkout_path, default=None
        )

        if pyproject is None:
            return None

        project = pyproject.get("project") or {}
        if project.get("version"):
            return f"{project['version']}"

        poetry = (pyproject.get("tool") or {}).get("poetry") or {}
        if poetry.get("version"):
            return f"{poetry['version']}"

        return None

    def current_version(self, repo_plugin):
        """
        Returns the repository's current version.

        `Ctl/VERSION` is authoritative when it exists, but a repository
        that keeps its version only in `pyproject.toml` is read from
        there rather than being handed the `0.0.0` that
        `RepositoryPlugin.version` falls back to - computing a semantic
        bump from `0.0.0` produces a plausible wrong answer that nothing
        reports.

        `RepositoryPlugin.version` itself is deliberately left alone: it
        is a generic repository interface, and `log_git` calls it to
        build a log line prefix, where raising is not an option.

        **Arguments**

        - repo_plugin (`RepositoryPlugin`)

        **Returns**

        `str` the current version

        **Raises**

        `UsageError` if no version can be determined
        """

        if os.path.exists(repo_plugin.version_file):
            return repo_plugin.version

        version = self.pyproject_version(repo_plugin)
        if version:
            return version

        if self.init_version:
            # initializing: there genuinely is no previous version, and
            # this is the one case where 0.0.0 is the right answer
            return "0.0.0"

        raise UsageError(
            f"Cannot determine the current version of {repo_plugin.checkout_path}: "
            "neither a Ctl/VERSION file nor a version in pyproject.toml. You "
            "can set the --init flag to start from 0.0.0."
        )

    def update_version_files(self, repo_plugin, version, files):
        """
        Finds the various files in a repo that will need to
        have new version values written, such as Ctl/VERSION
        and pyproject.toml

        Raises `UsageError` if there was nothing to write. Exiting
        successfully having changed no file at all is worse than
        failing - the caller is told the version was set, and only
        finds out otherwise when a later step inspects the diff.
        """

        types = ["ctl", "pyproject"]

        for typ in types:
            fn = getattr(self, f"update_{typ}_version")
            path = fn(repo_plugin, version)
            if path:
                files.append(path)

        if not files:
            raise UsageError(
                f"No version files to write in {repo_plugin.checkout_path}: "
                "there is no Ctl/VERSION file and pyproject.toml declares no "
                "static version. You can set the --init flag to create a "
                "Ctl/VERSION file."
            )

    def update_ctl_version(self, repo_plugin, version):
        """
        Writes a new version to the Ctl/VERSION file.

        Only files that already exist are written - a repository that
        does not use Ctl/VERSION must not acquire an untracked one, it
        would show up as an unexpected entry in a caller's diff. `--init`
        is the explicit opt in to creating it.

        Returns the written file path, or `None` if nothing was written.
        """

        if not os.path.exists(repo_plugin.version_file) and not self.init_version:
            return None

        os.makedirs(repo_plugin.repo_ctl_dir, exist_ok=True)

        with open(repo_plugin.version_file, "w") as fh:
            fh.write(version)
        return repo_plugin.version_file

    def update_pyproject_version(self, repo_plugin, version):
        """
        Writes a new version to the pyproject.toml file
        if it exists. Supports both Poetry format ([tool.poetry].version)
        and PEP 621 format ([project].version).
        """

        pyproject_path = os.path.join(repo_plugin.checkout_path, "pyproject.toml")
        pyproject = munge.load_datafile(
            "pyproject.toml", search_path=repo_plugin.checkout_path, default=None
        )

        if pyproject is None:
            return None

        updated = False

        # Check for Poetry format: [tool.poetry].version
        if "tool" in pyproject and "poetry" in pyproject["tool"]:
            if "version" in pyproject["tool"]["poetry"]:
                pyproject["tool"]["poetry"]["version"] = version
                updated = True

        # Check for PEP 621 format: [project].version
        if "project" in pyproject and "version" in pyproject["project"]:
            pyproject["project"]["version"] = version
            updated = True

        if not updated:
            return None

        codec = munge.get_codec("toml")

        with open(pyproject_path, "w") as fh:
            codec().dump(pyproject, fh)
        return pyproject_path

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
                f"{exc}\nYou can set the --no-changelog-validate flag to skip this check",
            )
