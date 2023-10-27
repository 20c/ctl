"""
Plugin that allows you to manage a git repository
"""


import argparse
import os
import re
import subprocess

import ctl
from ctl.auth import expose
from ctl.exceptions import OperationNotExposed
from ctl.plugins.repository import RepositoryPlugin
from ctl.util.git import GitManager, RepositoryConfig, TemporaryGitContext


def temporary_plugin(ctl, name, path, **config):
    """
    Instantiate a temporary git plugin pointing
    at an existing checkout path.

    **Arguments**

    - ctl: ctl instance
    - name: plugin name
    - path: file path to a cloned git repository

    **Keyword Arguments**

    Any keyword arguments will be passed on to
    plugin config

    **Returns**

    `GitPlugin` instance
    """

    config.update({"checkout_path": path})
    return GitPlugin({"type": "git", "name": name, "config": config}, ctl)


@ctl.plugin.register("git")
class GitPlugin(RepositoryPlugin):

    """
    manage a git repository

    For information on the configuration schema please check
    the `RepositoryPlugin` documenation
    """

    @property
    def uuid(self):
        """return recent commit hash of the repo"""
        command = self.command("rev-parse", "--short", "HEAD")
        return self.run_git_command(command)[0].strip()

    @property
    def is_cloned(self):
        """
        returns whether or not the checkout_path location is a valid
        git repo or not
        """
        return os.path.exists(os.path.join(self.checkout_path, ".git"))

    @property
    def is_clean(self):
        """
        Return whether the current repo checkout is clean
        """
        check_clean = self.command("status", "--porcelain")
        result = self.run_git_command(check_clean)
        return len(result) == 0

    @property
    def branch(self):
        """
        Return current branch name
        """
        get_branch = self.command("rev-parse", "--abbrev-ref", "HEAD")
        result = self.run_git_command(get_branch)
        return result[0].strip()

    def branch_exists(self, name):
        """
        Return if a branch exists in the local repo or not

        **Arguments**

        - name (`str`): branch name

        **Returns**

        `True` if branch exists, `False` if not
        """
        get_branch = self.command("rev-parse", "--verify", name)
        try:
            self.run_git_command(get_branch)
        except Exception as exc:
            if f"{exc}".find("fatal: Needed a single revision") > -1:
                return False
            raise
        return True

    @classmethod
    def add_arguments(cls, parser, plugin_config, confu_cli_args):
        shared_parser = argparse.ArgumentParser(add_help=False)
        group = shared_parser.add_mutually_exclusive_group(required=False)
        group.add_argument("--repo-url", type=str)
        group.add_argument("--checkout-path", type=str)
        group.add_argument("--gitlab-url", type=str)

        # subparser that routes operation
        sub = parser.add_subparsers(title="Operation", dest="op")

        # operation `clone`
        sub.add_parser("clone", help="clone repo", parents=[shared_parser])

        # operation `pull`
        sub.add_parser("pull", help="pull remote", parents=[shared_parser])

        # operation `mergerelease`
        op_mergerelease_parser = sub.add_parser(
            "merge_release",
            help="Will find chnage-request associated with the source/target branch and rename the change-request to v{{VERSION}} where VERSION comes from the Ctl/VERSION as it exists in the source branch. Once the change-request is renamed it will then be squashed and merged.",
            parents=[shared_parser],
        )

        op_mergerelease_parser.add_argument(
            "source_branch", type=str, help="source branch"
        )
        op_mergerelease_parser.add_argument(
            "target_branch", type=str, help="target branch"
        )

        # operation `checkout`
        op_checkout_parser = sub.add_parser(
            "checkout", help="checkout tag or branch", parents=[shared_parser]
        )
        op_checkout_parser.add_argument("tag", nargs=1, help="tag or branch")

        # operation `list_change_requests`
        sub.add_parser(
            "list_change_requests",
            help="list open change requests",
            parents=[shared_parser],
        )

        # operation `change_request_rename`
        op_rename_change_request = sub.add_parser(
            "rename_change_request",
            help="rename change request",
            parents=[shared_parser],
        )
        op_rename_change_request.add_argument(
            "source_branch", type=str, help="source branch"
        )
        op_rename_change_request.add_argument(
            "target_branch", type=str, help="target branch"
        )
        op_rename_change_request.add_argument("title", type=str, help="new title")

    @property
    def git_manager(self):
        return GitManager(
            url=self.repo_url or None,
            directory=self.checkout_path,
            default_branch=self.get_config("branch"),
            repository_config=RepositoryConfig(
                gitlab_url=self.kwargs.get("gitlab_url", os.environ.get("GITLAB_URL"))
                or "",
            ),
            log=self.log,
        )

    def execute(self, **kwargs):
        """
        Execute plugin operation

        **Keyword Arguments**

        - op (`str`): operation to execute - needs to be exposed
        - checkout_path (`str`): override repo_url config param
        - repo_url (`str`): override repo_url config param

        *overrides and calls `RepositoryPlugin.execute`*
        """

        super().execute(**kwargs)

        print("kwargs")

        op = kwargs.get("op")

        if not op:
            # TODO UsageError
            raise ValueError("operation not defined")

        fn = getattr(self, op)

        if not getattr(fn, "exposed", False):
            raise OperationNotExposed(op)

        del kwargs["op"]

        fn(**kwargs)

    def command(self, *command):
        """
        Prepare git command to use with `run_git_command`

        Will automaticdally prepare `--git-dir` and `--work-tree` options

        **Arguments**

        Any arguments passed will be joined together as a command

        **Returns**

        prepared command (`list`)
        """
        return [
            "git",
            "--git-dir",
            os.path.join(self.checkout_path, ".git"),
            "--work-tree",
            self.checkout_path,
        ] + list(command)

    def run_git_command(self, command):
        """
        Execute git command

        Use `command` to prepare command

        **Arguments**

        - command (`list`): command list that will be passed to subprocess

        **Returns**

        - captured output (`list`)
        """
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        stdout = []
        stderr = []
        with proc.stdout:
            for line in iter(proc.stdout.readline, b""):
                stdout.append(line.decode("utf-8").strip())

        with proc.stderr:
            for line in iter(proc.stderr.readline, b""):
                stderr.append(line.decode("utf-8").strip())

        for msg in stdout:
            self.log.info(msg)

        for err in stderr:
            self.log.error(err)

        if stderr:
            if re.search("(error|fatal):", "\n".join(stderr)):
                raise RuntimeError("\n".join(stderr))

        return stdout

    def commit(self, **kwargs):
        """
        Commit changes

        **Keyword Arguments**

        - files (`list`): list of files to commit, should be
          filenames relative to the repo root
        - message (`str`): commit message
        - push (`bool`=`True`): push immediately
        """

        files = kwargs.get("files")
        message = kwargs.get("message")

        # TODO: do we still need this in some situations ?
        # files = [os.path.join(self.checkout_path, f) for f in files]

        self.log.debug(f"COMMIT {files} : {message}")

        command_add = self.command("add", *files)
        self.run_git_command(command_add)

        command_commit = self.command("commit", *files) + ["-m", message]
        self.run_git_command(command_commit)

        self.log.debug("COMMIT COMPLETE")
        if kwargs.get("push"):
            self.push()

    @expose("ctl.{plugin_name}.clone")
    def clone(self, **kwargs):
        """
        Clone the repo specified in `repo_url` to `checkout_path`

        Will only clone if there is no valid git repo at ceckout_path
        already
        """

        if self.is_cloned:
            return

        self.log.debug(f"Cloning {self.repo_url}")
        command = ["git", "clone", self.repo_url, self.checkout_path]

        self.run_git_command(command)

        self.log.debug("Cloned {s.repo_url} in {s.checkout_path}".format(s=self))

    @expose("ctl.{plugin_name}.pull")
    def pull(self, **kwargs):
        """
        Pull the repo
        """

        branch = self.get_config("branch")
        remote = self.get_config("remote")

        self.log.debug(f"PULL {self.checkout_path} {remote}/{branch}")
        self.checkout(branch)
        command_pull = self.command("pull", remote, branch)
        self.run_git_command(command_pull)
        self.log.debug(f"PULL {self.checkout_path} {remote}/{branch} complete")

    def push(self, **kwargs):
        """
        Push commits
        """

        branch = self.get_config("branch")
        remote = self.get_config("remote")

        self.log.debug(f"PUSH {self.checkout_path} {remote} {branch}")
        command_push = self.command("push", remote, branch)
        if kwargs.get("tags"):
            command_push += ["--tags"]
        self.run_git_command(command_push)
        self.log.debug(f"PUSH {self.checkout_path} {remote} {branch} complete")

    def tag(self, version, message, **kwargs):
        """
        Tag the currently active branch

        **Arguments**

        - vrsion (`str`): tag version string / tag name
        - message (`str`): commit message
        """
        command_tag = self.command("tag", "-a", version, "-m", message)
        self.run_git_command(command_tag)
        if kwargs.get("push"):
            self.push(tags=True)

    @expose("ctl.{plugin_name}.checkout")
    def checkout(self, branch, **kwargs):
        """
        Checkout a branch or tag

        **Arguments**

        - branch (`str`): branch name
        """
        if not self.branch_exists(branch) and kwargs.get("create"):
            self.run_git_command(self.command("branch", branch))
        command_checkout = self.command("checkout", branch)
        self.run_git_command(command_checkout)

    @expose("ctl.{plugin_name}.list_change_requests")
    def list_change_requests(self, **kwargs):
        for cr in self.git_manager.list_change_requests():
            self.log.info(
                f"#{cr.id} - {cr.title} - ({cr.source_branch} -> {cr.target_branch})"
            )

    @expose("ctl.{plugin_name}.change_request_rename")
    def rename_change_request(
        self, source_branch: str, target_branch: str, title: str, **kwargs
    ):
        """
        Rename a merge/pull request title

        **Arguments**

        - source_branch (`str`): branch name
        - target_branch (`str`): branch name
        - title (`str`): new title
        """
        self.log.info(
            f"Renaming change request from {source_branch} to {target_branch} with title {title}"
        )
        self.git_manager.rename_change_request(target_branch, source_branch, title)
        self.log.info(
            f"Renamed change request from {source_branch} to {target_branch} with title {title}"
        )

    @expose("ctl.{plugin_name}.merge_release")
    def merge_release(self, source_branch: str, target_branch: str, **kwargs):
        # Step 1 Open ephemeral context

        with TemporaryGitContext(git_manager=self.git_manager) as ctx:
            ctx.git_manager.switch_branch(source_branch)

            # Step 2 load contents of Ctl/VERSION file

            try:
                with open(os.path.join(ctx.git_manager.directory, "Ctl/VERSION")) as fh:
                    version = fh.read().strip()
            except FileNotFoundError:
                raise RuntimeError("No Ctl/VERSION file found in source branch")

        # Step 3 find change request associated with target_branch and source_branch

        change_request = self.git_manager.get_open_change_request(
            target_branch, source_branch
        )

        if not change_request:
            raise RuntimeError(
                f"No change request found for {target_branch} and {source_branch}"
            )

        # Step 4 rename change request
        self.log.info(
            f"Renaming change request from {source_branch} to {target_branch} with title v{version}"
        )
        self.git_manager.rename_change_request(
            target_branch, source_branch, f"v{version}"
        )

        # Step 5 squash and merge change request
        self.log.info(
            f"Squashing and merging change request from {source_branch} to {target_branch}"
        )
        self.git_manager.merge_change_request(target_branch, source_branch, squash=True)

    def merge(self, branch_a, branch_b, **kwargs):
        """
        Merge branch A into branch B

        **Arguments**

        - branch_a (`str`): name of branch to merge
        - branch_b (`str`): name of branch to merge into

        **Keyword Arguments**

        - push (`bool`): if true will push branch B after merge
        """

        old_branch = self.branch
        self.checkout(branch_b)
        self.run_git_command(self.command("merge", branch_a))
        if kwargs.get("push"):
            self.push()
        self.checkout(old_branch)
