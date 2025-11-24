import os

import pytest

import ctl
from util import instantiate_test_plugin


def instantiate(tmpdir, ctlr=None, **kwargs):
    path_dir = str(tmpdir.mkdir("chain_out"))

    path_1 = os.path.join(path_dir, "test")

    echo_1_plugin = instantiate_test_plugin(
        "command",
        "echo_1",
        _ctl=ctlr,
        config={"command": [f"echo 'echo 1 ran' > {path_1}"], "shell": True},
    )
    assert echo_1_plugin

    path_2 = os.path.join(path_dir, "test2")

    echo_2_plugin = instantiate_test_plugin(
        "command",
        "echo_2",
        _ctl=ctlr,
        config={
            "command": ["echo '{{ kwargs.content }}' " + f" > {path_2}"],
            "shell": True,
        },
    )
    assert echo_2_plugin

    config = {
        "config": {
            "chain": [
                {"stage": "first", "plugin": "echo_1"},
                {
                    "stage": "second",
                    "plugin": "echo_2",
                    "action": {
                        "name": "execute",
                        "arguments": {"content": "echo 2 ran"},
                    },
                },
            ]
        }
    }
    config["config"].update(**kwargs)
    plugin = instantiate_test_plugin("chain", "test_chain", _ctl=ctlr, **config)
    return plugin, path_1, path_2


def test_init():
    ctl.plugin.get_plugin_class("chain")


def test_run_full(tmpdir, ctlr):
    plugin, outfile_1, outfile_2 = instantiate(tmpdir, ctlr)
    plugin.execute()
    with open(outfile_1) as fh:
        assert (fh.read()) == "echo 1 ran\n"

    with open(outfile_2) as fh:
        assert (fh.read()) == "echo 2 ran\n"


def test_run_end(tmpdir, ctlr):
    plugin, outfile_1, outfile_2 = instantiate(tmpdir, ctlr)
    plugin.execute(end="first")
    with pytest.raises(IOError):
        open(outfile_2)

    with open(outfile_1) as fh:
        assert (fh.read()) == "echo 1 ran\n"


def test_run_start(tmpdir, ctlr):
    plugin, outfile_1, outfile_2 = instantiate(tmpdir, ctlr)
    plugin.execute(start="second")
    with pytest.raises(IOError):
        open(outfile_1)

    with open(outfile_2) as fh:
        assert str(fh.read()) == "echo 2 ran\n"
