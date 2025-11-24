import os

import ctl
from util import instantiate_test_plugin


def instantiate(tmpdir, ctlr=None, **kwargs):
    config = {
        "config": {
            "source": os.path.join(os.path.dirname(__file__), "data"),
            "output": str(tmpdir.mkdir("copy_out")),
            "debug": True,
            "walk_dirs": ["copy"],
        }
    }
    config["config"].update(**kwargs)
    plugin = instantiate_test_plugin("copy", "test_copy", _ctl=ctlr, **config)
    return plugin


def test_init():
    ctl.plugin.get_plugin_class("copy")


def test_process(tmpdir, ctlr):
    plugin = instantiate(tmpdir, ctlr)
    plugin.execute()

    assert len(plugin.debug_info["copied"]) == 4
    for processed in plugin.debug_info["copied"]:
        with open(processed) as fh:
            assert fh.read() == "some content\n"


def test_ignore(tmpdir, ctlr):
    ignore = ["copy/b"]
    plugin = instantiate(tmpdir, ctlr, ignore=ignore)
    plugin.execute()

    expected_files = ["copy/a/file_1", "copy/a/file_2"]

    assert len(plugin.debug_info["mkdir"]) == 1
    assert sorted(plugin.debug_info["files"]) == expected_files
