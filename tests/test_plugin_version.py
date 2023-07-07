import os
import shutil

import pytest
import toml
from util import instantiate_version as instantiate

import ctl
from ctl.exceptions import PermissionDenied


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

    pyproject = toml.load(pyproject_path)
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
