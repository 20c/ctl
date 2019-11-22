import os
import pytest
import shutil

import ctl
import json

from ctl.plugins.changelog import ChangeLogPlugin, ChangelogVersionMissing

from util import instantiate_test_plugin

def instantiate(tmpdir, ctlr=None, **kwargs):
    dirpath = "{}".format(tmpdir)
    md_file = os.path.join(dirpath, "CHANGELOG.md")
    data_file = os.path.join(dirpath, "CHANGELOG.yml")
    config = {
        "config": {
            "md_file": md_file,
            "data_file": data_file,
        }
    }
    config["config"].update(kwargs)
    plugin = instantiate_test_plugin("changelog", "test_changelog", _ctl=ctlr, **config)
    return plugin


def test_init():
    ctl.plugin.get_plugin_class("changelog")


def test_generate_clean(tmpdir, ctlr, data_changelog_generate_clean):
    plugin = instantiate(tmpdir, ctlr)
    data_file = plugin.get_config("data_file")
    plugin.generate_clean(data_file)

    assert plugin.load(data_file) == data_changelog_generate_clean.expected

    with pytest.raises(ValueError):
        plugin.generate_clean(data_file)


def test_generate(tmpdir, ctlr, data_changelog_generate):
    data_file = os.path.join(data_changelog_generate.path, "CHANGELOG.yml")
    plugin = instantiate(tmpdir, ctlr, data_file=data_file)
    md_file = plugin.get_config("md_file")
    plugin.generate(md_file, data_file)

    with open(md_file,"r") as fh:
        content = fh.read()
        assert content.strip() == data_changelog_generate.md.strip()

def test_generate_datafile(tmpdir, ctlr, data_changelog_generate_datafile):
    md_file = os.path.join(data_changelog_generate_datafile.path, "CHANGELOG.md")
    plugin = instantiate(tmpdir, ctlr, md_file=md_file)
    data_file = plugin.get_config("data_file")
    plugin.generate_datafile(md_file, data_file)

    with open(data_file,"r") as fh:
        content = fh.read()
        print(content)
        assert content.strip() == data_changelog_generate_datafile.yml.strip()


def test_release(tmpdir, ctlr, data_changelog_release):

    md_file_src = os.path.join(data_changelog_release.path, "CHANGELOG.md")

    plugin = instantiate(tmpdir, ctlr)
    md_file = plugin.get_config("md_file")
    data_file = plugin.get_config("data_file")
    shutil.copyfile(md_file_src, md_file)
    plugin.generate_datafile(md_file, data_file)
    plugin.release("1.1.0", data_file)


    with open(data_file,"r") as fh:
        content = fh.read()
        assert content.strip() == data_changelog_release.yml.strip()



def test_validate(tmpdir, ctlr, data_changelog_generate):

    data_file = os.path.join(data_changelog_generate.path, "CHANGELOG.yml")
    plugin = instantiate(tmpdir, ctlr, data_file=data_file)

    plugin.validate(data_file, "1.0.0")

    with pytest.raises(ChangelogVersionMissing):
        plugin.validate(data_file, "1.1.0")



