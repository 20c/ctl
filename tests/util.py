import os
import subprocess
import sys

import ctl
from ctl.plugins.repository import RepositoryPlugin

# invoking a bare `ctl` would resolve through PATH, which may hold an
# unrelated installation or no `ctl` at all (the venv's bin directory
# is not on PATH when the suite runs as `python -m pytest`) - going
# through the interpreter running the tests always exercises the code
# under test

CTL_CMD = [
    sys.executable,
    "-c",
    "import sys; from ctl.cli import main; sys.exit(main(sys.argv))",
]


def run_git(repo_dir, *args):
    """
    runs a git command in the specified scratch repository directory

    uses `git -C` so the command never leaks out of the scratch
    repository - raises `subprocess.CalledProcessError` on failure

    **Returns**

    stripped stdout (`str`)
    """

    result = subprocess.run(
        ["git", "-C", repo_dir] + list(args),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def init_scratch_git_repo(repo_dir, branch="main"):
    """
    initializes an isolated scratch git repository for testing

    - creates the repository with `branch` as the initial branch
      (avoids default-branch warnings)
    - sets local user.email / user.name so commits work regardless
      of the environment's git configuration

    **Returns**

    the repository directory (`str`)
    """

    os.makedirs(repo_dir, exist_ok=True)
    run_git(repo_dir, "init", "-b", branch)
    run_git(repo_dir, "config", "user.email", "test@example.com")
    run_git(repo_dir, "config", "user.name", "Test User")
    return repo_dir


def scratch_git_commit(repo_dir, message="commit"):
    """
    stages all changes in the scratch repository and commits them

    **Returns**

    the commit hash (`str`)
    """

    run_git(repo_dir, "add", "-A")
    run_git(repo_dir, "commit", "-m", message)
    return run_git(repo_dir, "rev-parse", "HEAD")


def scratch_git_origin_ref(repo_dir, name="main", target="HEAD"):
    """
    creates a remote-tracking ref (eg. `origin/main`) in the scratch
    repository pointing at `target` - no actual remote is needed
    """

    run_git(repo_dir, "update-ref", f"refs/remotes/origin/{name}", target)


def instantiate_version(tmpdir, ctlr=None):
    """
    shortcut to instantiate a version plugin as well as a dummy repository
    """
    dummy_repo = ctl.plugin._instance["dummy_repo"] = DummyRepositoryPlugin(
        {"config": {"checkout_path": str(tmpdir.mkdir("repo"))}}, ctlr
    )
    config = {"config": {"branch_dev": "main", "branch_release": "release"}}
    plugin = instantiate_test_plugin("version", "test_version", _ctl=ctlr, **config)
    plugin.init_version = True
    plugin.no_auto_dev = True
    return (plugin, dummy_repo)


def instantiate_semver2(tmpdir, ctlr=None):
    """
    shortcut to instantiate a version plugin as well as a dummy repository
    """
    dummy_repo = ctl.plugin._instance["dummy_repo"] = DummyRepositoryPlugin(
        {"config": {"checkout_path": str(tmpdir.mkdir("repo"))}}, ctlr
    )
    plugin = instantiate_test_plugin("semver2", "test_semver2", _ctl=ctlr)
    plugin.init_version = True

    return (plugin, dummy_repo)


def instantiate_test_plugin(typ, name, _ctl=None, **extra):
    config = {"type": typ, "name": name}
    config.update(**extra)
    ctl.plugin.instantiate([config], _ctl)
    return ctl.plugin.get_instance(name)


class DummyRepositoryPlugin(RepositoryPlugin):
    """
    In order to test the versioning plugin we need a dummy
    repository plugin - so we can test that actions are properly
    propagated to a repository managed by the version plugin.

    This plugin serves that purpose
    """

    def init(self):
        self._repo_url = self.config.get("repo_url")
        self._checkout_path = self.config.get("checkout_path")
        self._clean = True
        self._cloned = False
        self._committed = False
        self._pulled = False
        self._pushed = False
        self._merged = None
        self._tag = None
        self._branch = "main"
        self._tags = set()

    @property
    def uuid(self):
        return "deadbeef"

    @property
    def is_cloned(self):
        return self._cloned

    @property
    def is_clean(self):
        return self._clean

    @property
    def branch(self):
        return self._branch

    def commit(self, **kwargs):
        self._committed = True

    def clone(self, **kwargs):
        self._is_cloned = True

    def pull(self, **kwargs):
        self._pulled = True

    def push(self, **kwargs):
        self._committed = False
        self._pushed = True

    def tag(self, version, **kwargs):
        self._tag = version
        no_git_tag = kwargs.get("no_git_tag", False)

        if not no_git_tag:
            self._tags.add(version)

    def checkout(self, branch, **kwargs):
        print(("SETTING BRANCH", branch))
        self._branch = branch

    def merge(self, a, b, **kwargs):
        self.checkout(b)
        self._merged = b

    def has_tag(self, tag):
        return tag in self._tags
