import os
import subprocess

import pytest

import ctl
from test_plugin_git import instantiate as instantiate_git
from util import instantiate_test_plugin


def package_repo(package_path, repo_path):
    subprocess.call([f"cp {package_path}/* {repo_path} -r"], shell=True)
    subprocess.call(
        ["git add *; git commit -am initial; git push;"], cwd=repo_path, shell=True
    )


def instantiate(tmpdir, ctlr=None, **kwargs):
    base_dir = os.path.join(os.path.dirname(__file__), "data", "pypi")
    config = {"config": {"config_file": os.path.join(base_dir, "pypirc")}}
    config["config"].update(**kwargs)
    plugin = instantiate_test_plugin("pypi", "test_pypi", _ctl=ctlr, **config)

    package_path = os.path.join(base_dir, "package")

    git_plugin, repo_path = instantiate_git(tmpdir, ctlr)
    package_repo(package_path, git_plugin.checkout_path)

    return plugin, git_plugin


def test_init():
    """
    Test plugin initialization
    """

    ctl.plugin.get_plugin_class("pypi")


def test_set_repository_git_path(tmpdir, ctlr):
    """
    Test setting build repository: existing git repo via filepath
    """

    plugin, git_plugin = instantiate(tmpdir, ctlr)

    plugin.set_repository(git_plugin.checkout_path)

    assert plugin.dist_path == os.path.join(git_plugin.checkout_path, "dist", "*")


def test_set_repository_git_plugin(tmpdir, ctlr):
    """
    Test setting build repository: existing git plugin
    """

    plugin, git_plugin = instantiate(tmpdir, ctlr)

    plugin.set_repository(git_plugin.plugin_name)

    assert plugin.dist_path == os.path.join(git_plugin.checkout_path, "dist", "*")


def test_set_repository_error(tmpdir, ctlr):
    """
    Test setting invalid build repository
    """

    plugin, git_plugin = instantiate(tmpdir, ctlr)

    # non existing path / plugin name

    with pytest.raises(IOError):
        plugin.set_repository("invalid repository")

    # invalid plugin type

    with pytest.raises(TypeError):
        plugin.set_repository("test_pypi")

    # no repository

    with pytest.raises(ValueError):
        plugin.set_repository(None)


def test_build_dist(tmpdir, ctlr):
    """
    Test building the dist files
    """

    plugin, git_plugin = instantiate(tmpdir, ctlr)
    plugin.prepare()
    plugin.set_repository(git_plugin.plugin_name)
    plugin._build_dist()

    assert os.path.exists(
        os.path.join(git_plugin.checkout_path, "dist", "ctl_pypi_test-0.1.2.1.tar.gz")
    )


def test_validate_dist(tmpdir, ctlr):
    """
    Test validating using twine check
    """

    plugin, git_plugin = instantiate(tmpdir, ctlr)
    plugin.prepare()
    plugin.set_repository(git_plugin.plugin_name)
    plugin._build_dist()
    plugin._validate_dist()
