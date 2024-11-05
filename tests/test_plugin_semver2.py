import os
import shutil

import pytest
import tomlkit
from util import instantiate_semver2 as instantiate

import ctl
from ctl.exceptions import PermissionDenied


def test_init():
    ctl.plugin.get_plugin_class("semver2")


def test_repository(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    assert plugin.repository("dummy_repo") == dummy_repo


def test_tag(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.tag(version="1.0.0", repo="dummy_repo")
    assert os.path.exists(dummy_repo.version_file)
    assert dummy_repo.version == "1.0.0"

    plugin.tag(version="1.0.1", repo="dummy_repo")
    assert dummy_repo.version == "1.0.1"

    plugin.tag(version="1.0.2", repo="dummy_repo")
    assert dummy_repo.version == "1.0.2"
    assert dummy_repo.has_tag("1.0.2")

    plugin.tag(version="1.0.3", repo="dummy_repo", nogit=True)
    assert dummy_repo.version == "1.0.3"
    assert not dummy_repo.has_tag("1.0.3")


def test_tag_prerelease(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.tag(version="1.0.0", repo="dummy_repo", prerelease="beta")
    assert os.path.exists(dummy_repo.version_file)
    assert dummy_repo.version == "1.0.0-beta.1"
    assert dummy_repo.has_tag("1.0.0-beta.1")

    plugin.tag(version="1.0.0", repo="dummy_repo", prerelease="rc", nogit=True)
    assert dummy_repo.version == "1.0.0-rc.1"
    assert not dummy_repo.has_tag("1.0.0-rc.1")

def test_tag_pyproject(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)

    pyproject_path = os.path.join(dummy_repo.checkout_path, "pyproject.toml")

    shutil.copyfile(
        os.path.join(os.path.dirname(__file__), "data", "version", "pyproject.toml"),
        pyproject_path,
    )

    plugin.tag(version="2.0.0", repo="dummy_repo", prerelease="rc")

    with open(pyproject_path, "r") as f:
        pyproject = tomlkit.load(f)
    assert pyproject["tool"]["poetry"]["version"] == "2.0.0-rc.1"


def test_bump(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.tag(version="1.0.0", repo="dummy_repo")

    plugin.bump(version="patch", repo="dummy_repo")
    assert dummy_repo.version == "1.0.1"

    plugin.bump(version="minor", repo="dummy_repo")
    assert dummy_repo.version == "1.1.0"

    plugin.bump(version="major", repo="dummy_repo")
    assert dummy_repo.version == "2.0.0"
    assert dummy_repo.has_tag("2.0.0")

    with pytest.raises(ValueError):
        plugin.bump(version="invalid", repo="dummy_repo")
    
    plugin.bump(version="patch", repo="dummy_repo", nogit=True)
    assert dummy_repo.version == "2.0.1"
    assert not dummy_repo.has_tag("2.0.1")


def test_bump_w_prerelease_flag(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.tag(version="1.0.0", repo="dummy_repo")

    plugin.bump(version="patch", repo="dummy_repo", prerelease="rc")
    assert dummy_repo.version == "1.0.1-rc.1"
    assert dummy_repo.has_tag("1.0.1-rc.1")

    plugin.bump(version="patch", repo="dummy_repo", prerelease="beta", nogit=True)
    assert dummy_repo.version == "1.0.2-beta.1"
    assert not dummy_repo.has_tag("1.0.2-beta.1")


def test_bump_prerelease_version(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.tag(version="1.0.0", repo="dummy_repo", prerelease="rc")
    assert dummy_repo.version == "1.0.0-rc.1"

    plugin.bump(version="prerelease", repo="dummy_repo")
    assert dummy_repo.version == "1.0.0-rc.2"
    plugin.bump(version="prerelease", repo="dummy_repo")
    assert dummy_repo.version == "1.0.0-rc.3"
    assert dummy_repo.has_tag("1.0.0-rc.3")

    plugin.bump(version="prerelease", repo="dummy_repo", nogit=True)
    assert dummy_repo.version == "1.0.0-rc.4"
    assert not dummy_repo.has_tag("1.0.0-rc.4")


def test_release(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.tag(version="1.0.0", repo="dummy_repo", prerelease="rc")
    assert dummy_repo.version == "1.0.0-rc.1"
    plugin.release(repo="dummy_repo")
    assert dummy_repo.version == "1.0.0"
    assert dummy_repo.has_tag("1.0.0")

    plugin.tag(version="1.1.0", repo="dummy_repo", prerelease="rc")
    assert dummy_repo.version == "1.1.0-rc.1"
    plugin.release(repo="dummy_repo", nogit=True)
    assert dummy_repo.version == "1.1.0"
    assert not dummy_repo.has_tag("1.1.0")


def test_execute(tmpdir, ctlr):
    plugin, dummy_repo = instantiate(tmpdir, ctlr)
    plugin.execute(op="tag", version="1.0.0", repository="dummy_repo", init=True)
    assert dummy_repo.version == "1.0.0"

    plugin.execute(op="bump", version="patch", repository="dummy_repo", init=True)
    assert dummy_repo.version == "1.0.1"

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
