import json
import os

import ctl
from util import instantiate_test_plugin


def instantiate(tmpdir, ctlr=None, **kwargs):
    config = {
        "config": {
            "source": os.path.join(os.path.dirname(__file__), "data"),
            "output": str(tmpdir.mkdir("walk_dir_out")),
            "debug": True,
            "walk_dirs": ["walk_dir"],
        }
    }
    config["config"].update(**kwargs)
    plugin = instantiate_test_plugin("walk_dir", "test_walk_dir", _ctl=ctlr, **config)
    return plugin


def test_init():
    ctl.plugin.get_plugin_class("walk_dir")


def test_walk_dir(tmpdir, ctlr):
    plugin = instantiate(tmpdir, ctlr)
    plugin.execute()
    print(json.dumps(plugin.debug_info, indent=2))

    expected_files = [
        "walk_dir/a/file_1",
        "walk_dir/a/file_2",
        "walk_dir/b/file_1",
        "walk_dir/b/file_2",
    ]

    assert len(plugin.debug_info["mkdir"]) == 2
    assert sorted(plugin.debug_info["files"]) == expected_files


def test_process(tmpdir, ctlr):
    process = [{"plugin": "echo", "action": "execute", "pattern": "file_1"}]
    echo_plugin = instantiate_test_plugin(
        "command",
        "echo",
        _ctl=ctlr,
        config={"command": ["echo 'processed' > {{ kwargs.output }}"], "shell": True},
    )
    plugin = instantiate(tmpdir, ctlr, process=process)
    plugin.execute()

    assert len(plugin.debug_info["processed"]) == 2
    for processed in plugin.debug_info["processed"]:
        with open(processed["output"]) as fh:
            assert fh.read() == "processed\n"


def test_ignore(tmpdir, ctlr):
    ignore = ["walk_dir/b"]
    plugin = instantiate(tmpdir, ctlr, ignore=ignore)
    plugin.execute()

    expected_files = ["walk_dir/a/file_1", "walk_dir/a/file_2"]

    assert len(plugin.debug_info["mkdir"]) == 1
    assert sorted(plugin.debug_info["files"]) == expected_files
