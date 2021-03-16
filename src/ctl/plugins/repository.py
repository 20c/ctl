"""
Plugin interface for plugins that manage software repositories
"""

import os

import confu.schema
import giturlparse

from ctl.docs import pymdgen_confu_types
from ctl.plugins import ExecutablePlugin
from ctl.util.versioning import version_tuple


@pymdgen_confu_types()
class PluginConfig(confu.schema.Schema):
    """
    Configuration schema for `RepositoryPlugin`
    """

    repo_url = confu.schema.Str(cli=False)
    checkout_path = confu.schema.Directory(
        default="",
        blank=True,
        help="checkout to this local "
        "location - if not specified "
        "will default to "
        "~/.cache/ctl/repo/{repo_url}",
    )

    branch = confu.schema.Str(help="Checkout this branch", default="master")


class RepositoryPlugin(ExecutablePlugin):
    """
    Interface for repository type plugins
    """

    class ConfigSchema(ExecutablePlugin.ConfigSchema):
        config = PluginConfig()

    def __repr__(self):
        return f"Repository `{self.plugin_name}`"

    @property
    def uuid(self):
        """ should return current commit hash/id """
        raise NotImplementedError()

    @property
    def version(self):
        """ current version as it exists in `version_file` """
        try:
            print(("Reading version from", self.version_file))
            with open(self.version_file) as fh:
                version = version_tuple(fh.read().strip())
        except FileNotFoundError:
            self.log.debug(f"No version file found at {self.version_file}")
            return (0, 0, 0)
        return version

    @property
    def version_file(self):
        """ location of version file """
        return os.path.join(self.repo_ctl_dir, "VERSION")

    @property
    def repo_ctl_dir(self):
        """ location of ctl directory inside repository """
        return os.path.join(self.checkout_path, "Ctl")

    @property
    def is_cloned(self):
        """
        should return True or False depending on whether the repository
        is already cloned at checkout_path or not
        """
        raise NotImplementedError()

    @property
    def is_clean(self):
        """
        Should perform a clean check (eg. git status --porcelain) and return True
        if clean, False if not
        """
        raise NotImplementedError()

    @property
    def branch(self):
        """
        Should return the name of the current branch
        """
        raise NotImplementedError()

    def branch_exists(self, name):
        """
        Should return True if the branch with the name exists in
        the local repository, False otherwise
        """
        raise NotImplementedError()

    def commit(self, **kwargs):
        """
        Should commit changes

        **Keyword arguments**

        - files (`list`): list of files to commit, should be
          filenames relative to the repo root
        - message (`str`): commit message
        - push (`bool`=`True`): push immediately
        """
        raise NotImplementedError()

    def clone(self, **kwargs):
        """
        Should clone the repository according to config parameters `repo_url` and `checkout_path`
        """
        raise NotImplementedError()

    def pull(self, **kwargs):
        """ Should pull the repository """
        raise NotImplementedError()

    def push(self, **kwargs):
        """ Should push changes to the remote """
        raise NotImplementedError()

    def tag(self, version, **kwargs):
        """ Should tag the current branch """
        raise NotImplementedError()

    def checkout(self, branch, **kwargs):
        """ Should checkout a branch by name """
        raise NotImplementedError()

    def merge(self, branch_a, branch_b, **kwargs):
        """ Should merge branch b into branch a """
        raise NotImplementedError()

    def init(self):
        self.repo_url = self.get_config("repo_url")
        self.checkout_path = self.get_config("checkout_path")

        branch = self.get_config("branch")

        if not self.checkout_path:

            parsed_url = giturlparse.parse(self.repo_url)

            # print("pathname", parsed_url.pathname)
            # print("href", parsed_url.href)
            # print("user", parsed_url.user)
            # print("name", parsed_url.name)
            # print("owner", parsed_url.owner)
            # print("resource", parsed_url.resource)

            self.checkout_path = os.path.join(
                self.ctl.cachedir, "repo", parsed_url.resource, parsed_url.pathname
            )

        # while checkout patch can be relative in the config, we want
        # it to be absolute from here on out
        self.checkout_path = os.path.abspath(self.checkout_path)

        self.clone()
        if branch != self.branch:
            self.checkout(branch, create=True)
