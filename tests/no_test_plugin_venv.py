import os
import re
import shutil
import subprocess
import sys

import pytest
from util import instantiate_test_plugin

import ctl
from ctl.exceptions import UsageError


def instantiate(tmpdir, ctlr=None, **kwargs):
    vi = sys.version_info
    config = {
        "config": {
            "pipfile": os.path.join(
                os.path.dirname(__file__), "data", "venv", "Pipfile"
            ),
            "python_version": f"{vi[0]}.{vi[1]}",
        }
    }
    print(config)
    config["config"].update(**kwargs)
    plugin = instantiate_test_plugin("venv", "test_venv", _ctl=ctlr, **config)
    return plugin


def test_init():
    ctl.plugin.get_plugin_class("venv")


def test_build_and_exists(tmpdir, ctlr):
    path = os.path.join(str(tmpdir.mkdir("test_venv")), "venv")
    plugin = instantiate(tmpdir, ctlr)
    plugin.execute(op="build", output=path)
    assert plugin.venv_exists()
    assert plugin.venv_exists(path)
    assert not plugin.venv_exists("does.not.exist")
    plugin.venv_validate()
    plugin.venv_validate(path)
    with pytest.raises(UsageError):
        plugin.venv_validate("does.not.exist")


def test_sync(tmpdir, ctlr):
    path = os.path.join(str(tmpdir.mkdir("test_venv")), "venv")
    plugin = instantiate(tmpdir, ctlr)
    plugin.execute(op="sync", output=path)

    output = subprocess.check_output(
        [f"source {path}/bin/activate; pip freeze;"], shell=True
    )

    print(f"{output}")

    assert f"{output}".find("confu==") > -1


def test_copy(tmpdir, ctlr):
    path_dir = str(tmpdir.mkdir("test_venv"))
    path = os.path.join(path_dir, "venv")
    path_copy = os.path.join(path_dir, "venv_copy")

    plugin = instantiate(tmpdir, ctlr)
    plugin.execute(op="build", output=path)
    plugin.execute(op="copy", source=path, output=path_copy)

    assert plugin.venv_exists(path_copy)
    plugin.venv_validate(path_copy)


@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
# FIXME: why does this fail on travis with
# pip_shims.shims.install_req_from_line being None
@pytest.mark.skipif(
    os.environ.get("TRAVIS") == "true",
    reason="fails on travis, postpone rabbit-holing for now",
)
def test_sync_setup(tmpdir, ctlr):
    path = os.path.join(str(tmpdir.mkdir("test_venv")), "venv")

    plugin = instantiate(tmpdir, ctlr)

    # sync venv first so Pipfile.lock exists
    plugin.execute(op="sync", output=path)

    # copy setup.py to tmpdir
    file_source = os.path.join(os.path.dirname(__file__), "data", "venv", "setup.py")
    setup_file = file_copy = os.path.join(path, "setup.py")
    shutil.copyfile(file_source, file_copy)

    # copy Pipfile to tmpdir (needs to be in same location as setup.py)
    file_source = os.path.join(os.path.dirname(__file__), "data", "venv", "Pipfile")
    file_copy = os.path.join(path, "Pipfile")
    shutil.copyfile(file_source, file_copy)

    # copy Pipfile.lock to tmpdir (needs to be in same location as setup.py)
    file_source = os.path.join(
        os.path.dirname(__file__), "data", "venv", "Pipfile.lock"
    )
    file_copy = os.path.join(path, "Pipfile.lock")
    shutil.copyfile(file_source, file_copy)

    # sync_setup
    plugin.execute(op="sync_setup", setup_file=setup_file)

    with open(setup_file) as fh:
        setup_file_data = fh.read()
        assert re.search(r"install_requires=\[.*confu>=", setup_file_data)
