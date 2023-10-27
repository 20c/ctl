"""
Plugin that allows you to handle repository versioning
"""

import argparse
import os

import semver

import ctl
from ctl.auth import expose
from ctl.exceptions import OperationNotExposed, UsageError
from ctl.plugins.version_base import VersionBasePlugin, VersionBasePluginConfig
from ctl.util.versioning import validate_prerelease


@ctl.plugin.register("semver2")
class Semver2Plugin(VersionBasePlugin):
    """
    manage repository versioning
    """

    class ConfigSchema(VersionBasePlugin.ConfigSchema):
        config = VersionBasePluginConfig()

    @classmethod
    def add_arguments(cls, parser, plugin_config, confu_cli_args):
        parsers = super().add_arguments(parser, plugin_config, confu_cli_args)

        sub = parsers.get("sub")
        shared_parser = parsers.get("shared_parser")
        release_parser = parsers.get("release_parser")
        group = parsers.get("group")

        # operation `tag`
        op_tag_parser = parsers.get("op_tag_parser")
        op_tag_parser.add_argument(
            "--prerelease",
            type=str,
            help="tag a prerelease with the specified prerlease name",
        )

        # operation `bump`
        op_bump_parser = parsers.get("op_bump_parser")
        op_bump_parser.add_argument(
            "--prerelease",
            type=str,
            help="tag a prerelease with the specified prerlease name",
        )

        # operation `release`
        op_release_parser = sub.add_parser(
            "release",
            help="go from pre-release version to release version. This will drop the current pre-release tag.",
            parents=[shared_parser, release_parser],
        )
        confu_cli_args.add(op_release_parser, "changelog_validate")
        confu_cli_args.add(op_release_parser, "branch")
        cls.add_repo_argument(op_release_parser, plugin_config)

    def execute(self, **kwargs):
        super().execute(**kwargs)

        if "version" in kwargs and isinstance(kwargs["version"], list):
            kwargs["version"] = kwargs["version"][0]

        kwargs["repo"] = self.get_config("repository")

        op = kwargs.get("op")
        fn = self.get_op(op)

        if not getattr(fn, "exposed", False):
            raise OperationNotExposed(op)

        fn(**kwargs)

    @expose("ctl.{plugin_name}.tag")
    def tag(self, version, repo, prerelease=None, **kwargs):
        """
        tag a version according to version specified

        **Arguments**

        - version (`str`): tag version (eg. 1.0.0)
        - repo (`str`): name of existing repository type plugin instance

        **Keyword Arguments**
        - prerelease (`str`): identifier if this is a prerelease version
        - release (`bool`): if `True` also run `merge_release`
        """
        repo_plugin = self.repository(repo)
        repo_plugin.pull()

        if not repo_plugin.is_clean:
            raise UsageError("Currently checked out branch is not clean")

        version = semver.VersionInfo.parse(version)

        if prerelease:
            version = version.bump_prerelease(prerelease)

        version_tag = str(version)

        if self.get_config("changelog_validate"):
            # TODO: changelog for pre-releases?
            if not version.prerelease:
                self.validate_changelog(repo, version_tag)

        self.log.info(f"Preparing to tag {repo_plugin.checkout_path} as {version_tag}")

        if not os.path.exists(repo_plugin.repo_ctl_dir):
            os.makedirs(repo_plugin.repo_ctl_dir)

        files = []

        self.update_version_files(repo_plugin, version_tag, files)

        repo_plugin.commit(files=files, message=f"Version {version_tag}", push=True)
        repo_plugin.tag(version_tag, message=version_tag, push=True)

    @expose("ctl.{plugin_name}.bump")
    def bump(self, version, repo, **kwargs):
        """
        bump a version according to semantic version

        **Arguments**

        - version (`str`): major, minor, patch or dev
        - repo (`str`): name of existing repository type plugin instance
        """

        repo_plugin = self.repository(repo)
        repo_plugin.pull()

        if version not in ["major", "minor", "patch", "prerelease"]:
            raise ValueError(f"Invalid semantic version: {version}")

        current = semver.VersionInfo.parse(repo_plugin.version)
        prerelease = kwargs.pop("prerelease", None)

        if version == "major":
            new_version = current.bump_major()
        elif version == "minor":
            new_version = current.bump_minor()
        elif version == "patch":
            new_version = current.bump_patch()
        elif version == "prerelease":
            if not current.prerelease:
                raise ValueError(
                    "Cannot bump the prerelease if it's not a prereleased version"
                )
            else:
                new_version = current.bump_prerelease()

        if prerelease and version != "prerelease":
            new_version = new_version.bump_prerelease(prerelease)

        self.log.info(f"Bumping semantic version: {current} to {new_version}")

        self.tag(version=str(new_version), repo=repo, **kwargs)

    @expose("ctl.{plugin_name}.release")
    def release(self, repo, **kwargs):
        """
        release and tag a version

        current version needs to be a pre-release version.

        **Arguments**

        - repo (`str`): name of existing repository type plugin instance
        """
        repo_plugin = self.repository(repo)
        repo_plugin.pull()

        version = repo_plugin.version

        # Use semver to parse version
        version = semver.VersionInfo.parse(version)

        if not version.prerelease:
            raise UsageError(
                "Currently not on a pre-release version. Use `bump` or `tag` operation instead"
            )

        version = version.replace(prerelease=None)
        self.tag(version=str(version), repo=repo, **kwargs)
