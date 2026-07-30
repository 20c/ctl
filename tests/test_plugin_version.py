import argparse
import logging
import os
import shutil

import pytest
import tomlkit

import ctl
from ctl.exceptions import PermissionDenied, UsageError
from util import instantiate_version as instantiate


def test_init():
    ctl.plugin.get_plugin_class("version")


def test_repository(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    assert plugin.repository("dummy_repo") == dummy_repo


def test_tag(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.tag(version="1.0.0", repo="dummy_repo")
    assert os.path.exists(dummy_repo.version_file)
    assert dummy_repo.version == "1.0.0"
    assert dummy_repo._tag == "1.0.0"

    plugin.tag(version="1.0.1", repo="dummy_repo")
    assert dummy_repo.version == "1.0.1"
    assert dummy_repo._tag == "1.0.1"

    plugin.tag(version="1.0.2", repo="dummy_repo", release=True)
    assert dummy_repo.version == "1.0.2"
    assert dummy_repo._tag == "1.0.2"
    assert dummy_repo._merged == "release"
    assert dummy_repo.branch == "release"


def test_tag_pyproject(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)

    pyproject_path = os.path.join(dummy_repo.checkout_path, "pyproject.toml")

    shutil.copyfile(
        os.path.join(os.path.dirname(__file__), "data", "version", "pyproject.toml"),
        pyproject_path,
    )

    plugin.tag(version="2.0.0", repo="dummy_repo")

    with open(pyproject_path) as f:
        pyproject = tomlkit.load(f)
    assert pyproject["tool"]["poetry"]["version"] == "2.0.0"


def test_bump(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.tag(version="1.0.0", repo="dummy_repo")

    plugin.bump(version="dev", repo="dummy_repo")
    assert dummy_repo.version == "1.0.0.1"
    assert dummy_repo._tag == "1.0.0.1"

    plugin.bump(version="patch", repo="dummy_repo")
    assert dummy_repo.version == "1.0.1"
    assert dummy_repo._tag == "1.0.1"

    plugin.bump(version="minor", repo="dummy_repo")
    assert dummy_repo.version == "1.1.0"
    assert dummy_repo._tag == "1.1.0"

    plugin.bump(version="major", repo="dummy_repo")
    assert dummy_repo.version == "2.0.0"
    assert dummy_repo._tag == "2.0.0"

    with pytest.raises(ValueError):
        plugin.bump(version="invalid", repo="dummy_repo")


def test_bump_truncated(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.tag(version="1.0", repo="dummy_repo")

    plugin.bump(version="minor", repo="dummy_repo")
    assert dummy_repo.version == "1.1.0"
    assert dummy_repo._tag == "1.1.0"

    plugin.tag(version="1.0", repo="dummy_repo")
    plugin.bump(version="patch", repo="dummy_repo")
    assert dummy_repo.version == "1.0.1"
    assert dummy_repo._tag == "1.0.1"

    plugin.tag(version="2", repo="dummy_repo")
    plugin.bump(version="patch", repo="dummy_repo")
    assert dummy_repo.version == "2.0.1"
    assert dummy_repo._tag == "2.0.1"

    plugin.tag(version="3", repo="dummy_repo")
    plugin.bump(version="major", repo="dummy_repo")
    assert dummy_repo.version == "4.0.0"
    assert dummy_repo._tag == "4.0.0"


def test_execute(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.execute(op="tag", version="1.0.0", repository="dummy_repo", init=True)
    assert dummy_repo._tag == "1.0.0"

    plugin.execute(op="bump", version="patch", repository="dummy_repo", init=True)
    assert dummy_repo._tag == "1.0.1"

    with pytest.raises(ValueError, match="operation not defined"):
        plugin.execute(op=None)

    with pytest.raises(ValueError, match="invalid operation"):
        plugin.execute(op="invalid")


def test_execute_permissions(tmpdir, ctldeny):
    plugin, dummy_repo = instantiate(tmpdir, ctldeny)
    with pytest.raises(PermissionDenied):
        plugin.execute(op="tag", version="1.0.0", repo="dummy_repo", init=True)

    with pytest.raises(PermissionDenied):
        plugin.execute(op="bump", version="patch", repo="dummy_repo", init=True)


PYPROJECT_PEP621 = """\
[project]
name = "ctl-test"
version = "0.5.0"
"""

PYPROJECT_POETRY = """\
[tool.poetry]
name = "ctl-test"
version = "0.5.0"
"""

PYPROJECT_DYNAMIC_VERSION = """\
[project]
name = "ctl-test"
dynamic = ["version"]
"""


def write_pyproject(dummy_repo, content):
    path = os.path.join(dummy_repo.checkout_path, "pyproject.toml")
    with open(path, "w") as fh:
        fh.write(content)
    return path


def assert_no_git_operations(dummy_repo):
    """
    the no-git operations must not reach the repository plugin at all -
    a commit here bypasses the caller's own commit gate, and a tag or
    push happens before the caller's release gate
    """

    assert dummy_repo._committed is False
    assert dummy_repo._pushed is False
    assert dummy_repo._pulled is False
    assert dummy_repo._tag is None
    assert dummy_repo._tags == set()


@pytest.mark.parametrize(
    "pyproject,read_version",
    [(PYPROJECT_PEP621, "0.5.0"), (PYPROJECT_POETRY, "0.5.0")],
)
def test_set_pyproject_only_repo(tmpdir, ctlr, pyproject, read_version):
    """
    a repository that keeps its version only in pyproject.toml is
    written without acquiring a Ctl/VERSION file - an unexpected
    untracked file breaks a caller that requires the diff to contain
    the version bump and nothing else
    """

    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.init_version = False

    pyproject_path = write_pyproject(dummy_repo, pyproject)

    plugin.set(version="0.6.0", repo="dummy_repo")

    with open(pyproject_path) as fh:
        written = tomlkit.load(fh)

    if "project" in written:
        assert written["project"]["version"] == "0.6.0"
    else:
        assert written["tool"]["poetry"]["version"] == "0.6.0"

    # no Ctl/VERSION, and not even a Ctl/ directory
    assert not os.path.exists(dummy_repo.version_file)
    assert not os.path.exists(dummy_repo.repo_ctl_dir)

    assert_no_git_operations(dummy_repo)


def test_set_writes_both_files_when_ctl_version_exists(tmpdir, ctlr):
    """
    a repository that does use Ctl/VERSION still gets both files
    """

    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    os.makedirs(dummy_repo.repo_ctl_dir, exist_ok=True)
    with open(dummy_repo.version_file, "w") as fh:
        fh.write("0.5.0")

    plugin.init_version = False

    pyproject_path = write_pyproject(dummy_repo, PYPROJECT_PEP621)

    files = plugin.set(version="0.6.0", repo="dummy_repo")

    assert dummy_repo.version == "0.6.0"
    with open(pyproject_path) as fh:
        assert tomlkit.load(fh)["project"]["version"] == "0.6.0"

    assert sorted(files) == sorted([dummy_repo.version_file, pyproject_path])
    assert_no_git_operations(dummy_repo)


def test_set_reports_written_files_and_versions(tmpdir, ctlr, caplog):
    """
    the caller needs to be able to see which files were touched and what
    the version went from and to, so it can check the result before
    committing it
    """

    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.init_version = False
    pyproject_path = write_pyproject(dummy_repo, PYPROJECT_PEP621)

    with caplog.at_level(logging.INFO):
        plugin.set(version="0.6.0", repo="dummy_repo")

    messages = [record.getMessage() for record in caplog.records]

    assert any(pyproject_path in message for message in messages)
    assert any("0.5.0 -> 0.6.0" in message for message in messages)


def test_set_no_version_files_raises(tmpdir, ctlr):
    """
    a repository with nothing to write must fail rather than report
    success having changed no file - the caller would only discover it
    a step later, when its diff check finds nothing
    """

    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.init_version = False
    write_pyproject(dummy_repo, PYPROJECT_DYNAMIC_VERSION)

    # a dynamic version has nothing to write, and there is no
    # Ctl/VERSION file either - the repository guard catches it first
    with pytest.raises(UsageError, match="No version found"):
        plugin.set(version="0.6.0", repo="dummy_repo")

    assert not os.path.exists(dummy_repo.version_file)
    assert_no_git_operations(dummy_repo)


def test_update_version_files_empty_raises(tmpdir, ctlr):
    """
    the write phase itself refuses to report success having written
    nothing, independently of the repository guard above
    """

    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.init_version = False
    write_pyproject(dummy_repo, PYPROJECT_DYNAMIC_VERSION)

    files = []
    with pytest.raises(UsageError, match="No version files to write"):
        plugin.update_version_files(dummy_repo, "0.6.0", files)

    assert files == []
    assert not os.path.exists(dummy_repo.version_file)


def test_bump_no_git_derives_from_pyproject(tmpdir, ctlr):
    """
    a semantic bump in a pyproject-only repository derives from the
    pyproject version, not from the 0.0.0 that
    `RepositoryPlugin.version` falls back to - 0.0.0 would compute a
    plausible wrong answer and write it without complaint
    """

    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.init_version = False

    pyproject_path = write_pyproject(dummy_repo, PYPROJECT_PEP621)

    plugin.bump(version="minor", repo="dummy_repo", no_git=True)

    with open(pyproject_path) as fh:
        # 0.5.0 -> 0.6.0, not 0.0.0 -> 0.1.0
        assert tomlkit.load(fh)["project"]["version"] == "0.6.0"

    assert not os.path.exists(dummy_repo.version_file)
    assert_no_git_operations(dummy_repo)


def test_bump_no_git_leaves_ctl_version_repo_untouched_by_git(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    os.makedirs(dummy_repo.repo_ctl_dir, exist_ok=True)
    with open(dummy_repo.version_file, "w") as fh:
        fh.write("1.0.0")

    plugin.bump(version="patch", repo="dummy_repo", no_git=True)

    assert dummy_repo.version == "1.0.1"
    assert_no_git_operations(dummy_repo)


def test_bump_without_no_git_still_commits_and_tags(tmpdir, ctlr):
    """
    the default path is unchanged - `--no-git` is opt in
    """

    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.tag(version="1.0.0", repo="dummy_repo")

    plugin.bump(version="minor", repo="dummy_repo")

    assert dummy_repo.version == "1.1.0"
    assert dummy_repo._tag == "1.1.0"
    assert dummy_repo._pulled is True


def test_current_version_resolution_order(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.init_version = False

    # nothing at all
    with pytest.raises(UsageError, match="Cannot determine the current version"):
        plugin.current_version(dummy_repo)

    # pyproject only
    write_pyproject(dummy_repo, PYPROJECT_PEP621)
    assert plugin.current_version(dummy_repo) == "0.5.0"

    # Ctl/VERSION wins when both exist
    os.makedirs(dummy_repo.repo_ctl_dir, exist_ok=True)
    with open(dummy_repo.version_file, "w") as fh:
        fh.write("1.2.3")
    assert plugin.current_version(dummy_repo) == "1.2.3"


def test_current_version_init_starts_at_zero(tmpdir, ctlr):
    """
    --init genuinely has no previous version, and 0.0.0 stays the right
    answer there - this is the one case the fallback was correct for
    """

    plugin, dummy_repo = instantiate(tmpdir, ctlr)  # sets init_version = True
    assert plugin.current_version(dummy_repo) == "0.0.0"


def test_pyproject_version_reader(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)

    # no pyproject.toml at all
    assert plugin.pyproject_version(dummy_repo) is None

    write_pyproject(dummy_repo, PYPROJECT_DYNAMIC_VERSION)
    assert plugin.pyproject_version(dummy_repo) is None

    write_pyproject(dummy_repo, PYPROJECT_POETRY)
    assert plugin.pyproject_version(dummy_repo) == "0.5.0"

    write_pyproject(dummy_repo, PYPROJECT_PEP621)
    assert plugin.pyproject_version(dummy_repo) == "0.5.0"


def test_repository_accepts_pyproject_only_repo(tmpdir, ctlr):
    """
    a pyproject-only repository is a valid target without --init, which
    would otherwise be the only way in and would create the untracked
    Ctl/VERSION file the caller cannot have
    """

    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.init_version = False

    with pytest.raises(UsageError, match="No version found"):
        plugin.repository("dummy_repo")

    write_pyproject(dummy_repo, PYPROJECT_PEP621)

    assert plugin.repository("dummy_repo") == dummy_repo
    assert not os.path.exists(dummy_repo.version_file)


def test_init_flag_reaches_init_version(tmpdir, ctlr):
    """
    `--init` arrives as an `init` kwarg and has to be carried over to
    `init_version` - it used to parse and then be ignored, so the flag
    the error message recommends did not actually work
    """

    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.init_version = False

    plugin.execute(op="set", version=["1.0.0"], repository="dummy_repo", init=True)

    assert plugin.init_version is True
    assert dummy_repo.version == "1.0.0"
    assert_no_git_operations(dummy_repo)


def test_execute_set(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.execute(op="set", version=["1.2.3"], repository="dummy_repo", init=True)

    assert dummy_repo.version == "1.2.3"
    assert_no_git_operations(dummy_repo)


def test_cli_accepts_set_and_bump_no_git(ctlr):
    parser = argparse.ArgumentParser()
    ctl.plugin_cli_arguments(
        ctlr, parser, {"type": "version", "name": "version", "config": {}}
    )

    args = parser.parse_args(["set", "1.0.0"])
    assert args.op == "set"
    assert args.version == ["1.0.0"]

    args = parser.parse_args(["set", "1.0.0", "--init"])
    assert args.init is True

    # `set` does no git work and does not validate, so it must not accept
    # flags it would then ignore
    with pytest.raises(SystemExit):
        parser.parse_args(["set", "1.0.0", "--branch", "main"])

    with pytest.raises(SystemExit):
        parser.parse_args(["set", "1.0.0", "--no-changelog-validate"])

    args = parser.parse_args(["bump", "minor", "--no-git"])
    assert args.no_git is True

    # not passing it leaves the git path in place
    args = parser.parse_args(["bump", "minor"])
    assert args.no_git is False


def test_cli_rejects_semver2_only_flags(ctlr):
    # --prefix and --no-git-tag are implemented by the semver2 plugin only,
    # and --no-git only by the version plugin's `bump` (`set` is the
    # no-git form of `tag`); each parser must reject the flags it does not
    # implement instead of parsing and silently ignoring them
    parser = argparse.ArgumentParser()
    ctl.plugin_cli_arguments(
        ctlr, parser, {"type": "version", "name": "version", "config": {}}
    )

    with pytest.raises(SystemExit):
        parser.parse_args(["tag", "--prefix", "v", "1.0.0"])

    with pytest.raises(SystemExit):
        parser.parse_args(["bump", "--no-git-tag", "minor"])

    with pytest.raises(SystemExit):
        parser.parse_args(["tag", "--no-git", "1.0.0"])
