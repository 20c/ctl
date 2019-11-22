"""
Plugin that allows you to handle repository versioning
"""
from __future__ import absolute_import
import os
import ctl
import confu.schema
import argparse
from ctl.plugins import ExecutablePlugin
from ctl.plugins.repository import RepositoryPlugin
from ctl.plugins.git import temporary_plugin as temporary_git_plugin
from ctl.plugins.changelog import (
    temporary_plugin as temporary_changelog_plugin,
    ChangelogVersionMissing,
)
from ctl.util.versioning import bump_semantic, version_string
from ctl.auth import expose
from ctl.exceptions import UsageError, OperationNotExposed, PluginOperationStopped
from ctl.docs import pymdgen_confu_types


@pymdgen_confu_types()
class VersionPluginConfig(confu.schema.Schema):
    """
    Configuration schema for `VersionPlugin`
    """

    repository = confu.schema.Str(
        help="name of repository type plugin or path " "to a repository checkout",
        default=None,
        cli=False,
    )

    branch_dev = confu.schema.Str(
        default="master",
        help="the branch to merge from when the " "--merge-release flag is present",
    )

    branch_release = confu.schema.Str(
        default="master",
        help="the breanch to merge to when " "the --merge-release flag is present",
    )

    changelog_validate = confu.schema.Bool(
        default=True,
        help="If a changelog data file (CHANGELOG.yaml) exists, validate before tagging",
    )


@ctl.plugin.register("version")
class VersionPlugin(ExecutablePlugin):
    """
    manage repository versioning
    """

    class ConfigSchema(ExecutablePlugin.ConfigSchema):
        config = VersionPluginConfig()

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
            help=VersionPluginConfig().repository.help,
            default=plugin_config.get("repository"),
        )

    @classmethod
    def add_arguments(cls, parser, plugin_config, confu_cli_args):

        shared_parser = argparse.ArgumentParser(add_help=False)

        release_parser = argparse.ArgumentParser(add_help=False)
        group = release_parser.add_mutually_exclusive_group(required=False)
        group.add_argument(
            "--release",
            action="store_true",
            help="if set will also "
            "perform `merge_release` operation and tag in the specified "
            "release branch instead of the currently active branch",
        )

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
            choices=["major", "minor", "patch", "dev"],
            help="bumps the specified version segment by 1",
        )

        op_bump_parser.add_argument(
            "--no-auto-dev",
            help="disable automatic bumping of dev "
            "version after bumping `major`, `minor` or `patch`",
            action="store_true",
        )

        confu_cli_args.add(op_bump_parser, "changelog_validate")

        cls.add_repo_argument(op_bump_parser, plugin_config)

        # operations `merge_release`
        op_mr_parser = sub.add_parser(
            "merge_release",
            help="merge dev branch into release branch " "(branches defined in config)",
            parents=[shared_parser],
        )

        cls.add_repo_argument(op_mr_parser, plugin_config)

    @property
    def init_version(self):
        """
        `True` if a `Ctl/VERSION` file should be created if it's missing
        """
        return getattr(self, "_init_version", False)

    @init_version.setter
    def init_version(self, value):
        self._init_version = value

    @property
    def no_auto_dev(self):
        """
        `True` if we do **NOT** want to automatically bump a dev version when a major
        minor or patch version is bumped
        """
        return getattr(self, "_no_auto_dev", False)

    @no_auto_dev.setter
    def no_auto_dev(self, value):
        self._no_auto_dev = value

    def execute(self, **kwargs):

        super(VersionPlugin, self).execute(**kwargs)

        branch_dev = self.get_config("branch_dev")
        branch_release = self.get_config("branch_release")
        self.no_auto_dev = kwargs.get("no_auto_dev", False)
        self.init_version = kwargs.get("init", False)

        if "version" in kwargs and isinstance(kwargs["version"], list):
            kwargs["version"] = kwargs["version"][0]

        kwargs["repo"] = self.get_config("repository")

        op = kwargs.get("op")
        fn = self.get_op(op)

        if not getattr(fn, "exposed", False):
            raise OperationNotExposed(op)

        fn(**kwargs)

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
                raise IOError(
                    "Target is neither a configured repository "
                    "plugin nor a valid file path: "
                    "{}".format(target)
                )

            plugin = ctl.plugins.git.temporary_plugin(self.ctl, target, target)

        if not self.init_version and not os.path.exists(plugin.version_file):
            raise UsageError(
                "Ctl/VERSION file does not exist. You can set the --init flag to create "
                "it automatically."
            )

        return plugin

    @expose("ctl.{plugin_name}.merge_release")
    def merge_release(self, repo, **kwargs):
        """
        Merge branch self.branch_dev into branch self.branch_release in the specified
        repo

        **Arguments**

        - repo (`str`): name of existing repository type plugin instance
        """
        from_branch = self.get_config("branch_dev")
        to_branch = self.get_config("branch_release")
        if from_branch == to_branch:
            self.log.debug("dev and release branch are identical, no need to merge")
            return

        repo_plugin = self.repository(repo)
        self.log.info(
            "Merging branch '{}' into branch '{}'".format(from_branch, to_branch)
        )
        repo_plugin.merge(from_branch, to_branch)
        repo_plugin.push()

    @expose("ctl.{plugin_name}.tag")
    def tag(self, version, repo, **kwargs):
        """
        tag a version according to version specified

        **Arguments**

        - version (`str`): tag version (eg. 1.0.0)
        - repo (`str`): name of existing repository type plugin instance

        **Keyword Arguments**

        - release (`bool`): if `True` also run `merge_release`
        """
        repo_plugin = self.repository(repo)
        repo_plugin.pull()

        if not repo_plugin.is_clean:
            raise UsageError("Currently checked out branch is not clean")

        if kwargs.get("release"):
            self.merge_release(repo=repo)
            repo_plugin.checkout(self.get_config("branch_release") or "master")

        self.log.info(
            "Preparing to tag {} as {}".format(repo_plugin.checkout_path, version)
        )
        if not os.path.exists(repo_plugin.repo_ctl_dir):
            os.makedirs(repo_plugin.repo_ctl_dir)

        with open(repo_plugin.version_file, "w") as fh:
            fh.write(version)

        repo_plugin.commit(
            files=["Ctl/VERSION"], message="Version {}".format(version), push=True
        )
        repo_plugin.tag(version, message=version, push=True)

    @expose("ctl.{plugin_name}.bump")
    def bump(self, version, repo, **kwargs):
        """
        bump a version according to semantic version

        **Arguments**

        - version (`str`): major, minor, patch or dev
        - repo (`str`): name of existing repository type plugin instance
        """

        repo_plugin = self.repository(repo)

        if version not in ["major", "minor", "patch", "dev"]:
            raise ValueError("Invalid semantic version: {}".format(version))

        is_dev = version == "dev"

        current = repo_plugin.version
        version = bump_semantic(current, version)

        self.log.info(
            "Bumping semantic version: {} to {}".format(
                version_string(current), version_string(version)
            )
        )

        if self.get_config("changelog_validate") and not is_dev:
            self.validate_changelog(repo, version)

        self.tag(version=version_string(version), repo=repo, **kwargs)

        if not is_dev and not self.no_auto_dev:
            self.log.info("Creating dev tag")
            self.bump(version="dev", repo=repo, **kwargs)

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
            self.ctl, "{}_changelog".format(self.plugin_name), data_file=changelog_path
        )

        self.log.info(
            "Found changelog data file at {} - validating ...".format(changelog_path)
        )

        try:
            changelog_plugin.validate(changelog_path, version)
        except ChangelogVersionMissing as exc:
            raise PluginOperationStopped(
                self,
                "{}\nYou can set the --no-changelog-validate flag to skip this check".format(
                    exc
                ),
            )
