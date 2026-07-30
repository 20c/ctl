"""
Plugin that allows you to handle repository versioning
"""

import confu.schema

import ctl
from ctl.auth import expose
from ctl.docs import pymdgen_confu_types
from ctl.exceptions import OperationNotExposed, UsageError
from ctl.plugins.version_base import VersionBasePlugin, VersionBasePluginConfig
from ctl.util.versioning import bump_semantic, version_string


@pymdgen_confu_types()
class VersionPluginConfig(VersionBasePluginConfig):
    """
    Configuration schema for `VersionPlugin`
    """

    branch_dev = confu.schema.Str(
        default="main",
        help="the branch to merge from when the --merge-release flag is present",
    )

    branch_release = confu.schema.Str(
        default="main",
        help="the breanch to merge to when the --merge-release flag is present",
    )


@ctl.plugin.register("version")
class VersionPlugin(VersionBasePlugin):
    """
    manage repository versioning
    """

    class ConfigSchema(VersionBasePlugin.ConfigSchema):
        config = VersionPluginConfig()

    @classmethod
    def add_arguments(cls, parser, plugin_config, confu_cli_args):
        parsers = super().add_arguments(parser, plugin_config, confu_cli_args)
        sub = parsers.get("sub")
        shared_parser = parsers.get("shared_parser")
        group = parsers.get("group")

        group.add_argument(
            "--release",
            action="store_true",
            help="if set will also "
            "perform `merge_release` operation and tag in the specified "
            "release branch instead of the currently active branch",
        )

        op_bump_parser = parsers.get("op_bump_parser")

        # NOTE: `--no-git` goes directly on the operation parser, never on
        # `shared_parser`: argparse copies parent actions when a subparser
        # is created, and the base class has already created the tag/bump
        # parsers by the time this method runs. Same trap as documented in
        # the semver2 plugin.
        op_bump_parser.add_argument(
            "--no-git",
            dest="no_git",
            action="store_true",
            help="skip all git operations (pull, commit, tag and push) - only "
            "version files are updated",
            default=False,
        )

        # operation `set`
        #
        # deliberately a verb of its own rather than a flag on `tag`: it
        # never tags, and this is the normal case for any repository whose
        # release is driven externally, so it should be the short form
        op_set_parser = sub.add_parser(
            "set",
            help="write a version to the repository's version files without "
            "any git operations",
            parents=[shared_parser],
        )
        op_set_parser.add_argument(
            "version", nargs=1, type=str, help="version string to write"
        )
        op_set_parser.add_argument(
            "--init",
            action="store_true",
            help="automatically create Ctl/VERSION file if it does not exist",
        )
        # `changelog_validate` and `branch` are deliberately not offered
        # here: `set` performs no git operations, so there is no branch to
        # act on, and validation belongs to `bump`, which owns the version
        # it derived. Accepting a flag that is then never read is the same
        # defect as the `--init` that used to parse and be ignored.
        cls.add_repo_argument(op_set_parser, plugin_config)

        # operations `merge_release`
        op_mr_parser = sub.add_parser(
            "merge_release",
            help="merge dev branch into release branch (branches defined in config)",
            parents=[shared_parser],
        )
        cls.add_repo_argument(op_mr_parser, plugin_config)

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
        self.log.info(f"Merging branch '{from_branch}' into branch '{to_branch}'")
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
            repo_plugin.checkout(self.get_config("branch_release") or "main")

        self.log.info(f"Preparing to tag {repo_plugin.checkout_path} as {version}")

        files = []

        self.update_version_files(repo_plugin, version, files)

        repo_plugin.commit(files=files, message=f"Version {version}", push=True)
        repo_plugin.tag(version, message=version, push=True)

    @expose("ctl.{plugin_name}.set")
    def set(self, version, repo, **kwargs):
        """
        write a version to the repository's version files

        Performs no git operations at all - no pull, no clean tree
        check, no commit, no tag, no push. Only files that already
        exist are written, unless `--init` was passed.

        This is the operation to use when the release itself is driven
        outside of ctl, where a commit or tag from here would bypass the
        caller's own gates.

        **Arguments**

        - version (`str`): version to write (eg. 1.0.0)
        - repo (`str`): name of existing repository type plugin instance
        """

        repo_plugin = self.repository(repo)

        current = self.current_version(repo_plugin)

        files = []
        self.update_version_files(repo_plugin, version, files)

        # report what was written so the caller can check it before
        # committing - the caller verifies the result itself, this is
        # for a human reading the output
        for filepath in files:
            self.log.info(f"Wrote {filepath}")

        self.log.info(f"Version {version_string(current)} -> {version_string(version)}")

        return files

    @expose("ctl.{plugin_name}.bump")
    def bump(self, version, repo, **kwargs):
        """
        bump a version according to semantic version

        **Arguments**

        - version (`str`): major, minor, patch or dev
        - repo (`str`): name of existing repository type plugin instance

        **Keyword Arguments**

        - no_git (`bool`): if `True` only write the version files, no
          pull, commit, tag or push
        """

        no_git = kwargs.get("no_git", False)

        repo_plugin = self.repository(repo)

        if not no_git:
            repo_plugin.pull()

        if version not in ["major", "minor", "patch", "dev"]:
            raise ValueError(f"Invalid semantic version: {version}")

        is_dev = version == "dev"

        current = self.current_version(repo_plugin)
        version = bump_semantic(current, version)

        self.log.info(
            f"Bumping semantic version: {version_string(current)} to {version_string(version)}"
        )

        if self.get_config("changelog_validate") and not is_dev:
            self.validate_changelog(repo, version)

        if no_git:
            self.set(version=version_string(version), repo=repo, **kwargs)
            return

        self.tag(version=version_string(version), repo=repo, **kwargs)
