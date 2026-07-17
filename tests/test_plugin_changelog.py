import os
import shutil
import subprocess

import pytest

import ctl
from ctl.exceptions import PluginOperationStopped
from ctl.plugins.changelog import CHANGELOG_SECTIONS, ChangelogVersionMissing
from util import (
    init_scratch_git_repo,
    instantiate_test_plugin,
    run_git,
    scratch_git_commit,
    scratch_git_origin_ref,
)


def instantiate(tmpdir, ctlr=None, **kwargs):
    dirpath = f"{tmpdir}"
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

    with open(md_file) as fh:
        content = fh.read()
        assert content.strip() == data_changelog_generate.md.strip()


def test_generate_datafile(tmpdir, ctlr, data_changelog_generate_datafile):
    md_file = os.path.join(data_changelog_generate_datafile.path, "CHANGELOG.md")
    plugin = instantiate(tmpdir, ctlr, md_file=md_file)
    data_file = plugin.get_config("data_file")
    plugin.generate_datafile(md_file, data_file)

    with open(data_file) as fh:
        content = fh.read()
        assert content.strip() == data_changelog_generate_datafile.yml.strip()


def test_release(tmpdir, ctlr, data_changelog_release):
    md_file_src = os.path.join(data_changelog_release.path, "CHANGELOG.md")

    plugin = instantiate(tmpdir, ctlr)
    md_file = plugin.get_config("md_file")
    data_file = plugin.get_config("data_file")
    shutil.copyfile(md_file_src, md_file)
    plugin.generate_datafile(md_file, data_file)
    plugin.release("1.1.0", data_file)

    with open(data_file) as fh:
        content = fh.read()
        print(content)
        assert content.strip() == data_changelog_release.yml.strip()


def test_validate(tmpdir, ctlr, data_changelog_generate):
    data_file = os.path.join(data_changelog_generate.path, "CHANGELOG.yml")
    plugin = instantiate(tmpdir, ctlr, data_file=data_file)

    plugin.validate(data_file, "1.0.0")

    with pytest.raises(ChangelogVersionMissing):
        plugin.validate(data_file, "1.1.0")


# changelog fragments (changelog.d)


CHANGELOG_YML_UNRELEASED = """\
Unreleased:
  added:
  - unreleased added entry
  security: []
1.0.0:
  added:
  - initial release
"""

CHANGELOG_YML_EMPTY_UNRELEASED = """\
Unreleased:
  added: []
  fixed: []
  changed: []
  deprecated: []
  removed: []
  security: []
1.0.0:
  added:
  - initial release
"""

CHANGELOG_YML_RELEASED_ONLY = """\
1.0.0:
  added:
  - initial release
"""

CTL_CONFIG_YML = """\
ctl:
  permissions:
    - namespace: "ctl"
      permission: "crud"

  plugins:
    - name: changelog
      type: changelog

  log:
"""

EMPTY_SECTIONS = {section: [] for section in CHANGELOG_SECTIONS}


def write_file(filepath, content):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as fh:
        fh.write(content)


def setup_fragments(tmpdir, ctlr, changelog_yml, fragments=None):
    """
    sets up a project directory containing a changelog data file and
    a changelog.d fragments directory and instantiates a changelog
    plugin against it
    """

    project_dir = os.path.join(f"{tmpdir}", "project")
    data_file = os.path.join(project_dir, "CHANGELOG.yml")
    md_file = os.path.join(project_dir, "CHANGELOG.md")
    fragments_dir = os.path.join(project_dir, "changelog.d")

    write_file(data_file, changelog_yml)
    os.makedirs(fragments_dir)

    for filename, content in (fragments or {}).items():
        write_file(os.path.join(fragments_dir, filename), content)

    plugin = instantiate(tmpdir, ctlr, data_file=data_file, md_file=md_file)
    return plugin, data_file, md_file, fragments_dir


def setup_check_repo(tmpdir, ctlr):
    """
    sets up a scratch git repository containing a changelog data file
    and a changelog.d fragments directory with an initial commit and
    instantiates a changelog plugin against it
    """

    repo_dir = init_scratch_git_repo(os.path.join(f"{tmpdir}", "repo"))
    data_file = os.path.join(repo_dir, "CHANGELOG.yml")
    fragments_dir = os.path.join(repo_dir, "changelog.d")

    write_file(data_file, CHANGELOG_YML_EMPTY_UNRELEASED)
    write_file(os.path.join(fragments_dir, ".gitkeep"), "")
    base_commit = scratch_git_commit(repo_dir, "base")

    plugin = instantiate(tmpdir, ctlr, data_file=data_file)
    return plugin, repo_dir, data_file, fragments_dir, base_commit


def test_load_fragments_collection(tmpdir, ctlr):
    fragments = {
        "20-second.yaml": "added:\n- second added entry\n",
        "10-first.yaml": ("added:\n- first added entry\nfixed:\n- first fixed entry\n"),
        "30-third.yml": "security:\n- third security entry\n",
        ".40-hidden.yaml": "added:\n- hidden entry\n",
        "50-notes.txt": "added:\n- not a yaml file\n",
    }
    plugin, data_file, _, fragments_dir = setup_fragments(
        tmpdir, ctlr, CHANGELOG_YML_UNRELEASED, fragments
    )

    # a directory with a yaml extension is ignored as well
    os.makedirs(os.path.join(fragments_dir, "60-directory.yaml"))

    files, sections = plugin.load_fragments(fragments_dir)

    # only visible *.yaml / *.yml files are collected, sorted by file name
    assert files == [
        os.path.join(fragments_dir, "10-first.yaml"),
        os.path.join(fragments_dir, "20-second.yaml"),
        os.path.join(fragments_dir, "30-third.yml"),
    ]

    assert sections == {
        "added": ["first added entry", "second added entry"],
        "fixed": ["first fixed entry"],
        "changed": [],
        "deprecated": [],
        "removed": [],
        "security": ["third security entry"],
    }


def test_release_fragments_merge(tmpdir, ctlr, capsys):
    fragments = {
        "001-first.yaml": (
            "added:\n- fragment one added entry\nfixed:\n- fragment one fixed entry\n"
        ),
        "002-second.yaml": (
            "added:\n- fragment two added entry\n"
            "security:\n- fragment two security entry\n"
        ),
    }
    plugin, data_file, _, fragments_dir = setup_fragments(
        tmpdir, ctlr, CHANGELOG_YML_UNRELEASED, fragments
    )

    plugin.release("1.1.0", data_file)

    data = plugin.load(data_file)

    # unreleased entries come first, fragment entries follow in
    # fragment file name order
    assert data["1.1.0"] == {
        "added": [
            "unreleased added entry",
            "fragment one added entry",
            "fragment two added entry",
        ],
        "fixed": ["fragment one fixed entry"],
        "security": ["fragment two security entry"],
    }

    # written section keys follow CHANGELOG_SECTIONS order
    assert list(data["1.1.0"].keys()) == ["added", "fixed", "security"]

    # the Unreleased key existed, so it is reset to an empty scaffold
    assert data["Unreleased"] == EMPTY_SECTIONS

    # collected fragments are deleted
    assert os.listdir(fragments_dir) == []

    # a suggestion to move unreleased items to fragments is printed
    assert "Consider moving" in capsys.readouterr().out


def test_release_fragments_unreleased_absent(tmpdir, ctlr):
    fragments = {"001-first.yaml": "added:\n- fragment added entry\n"}
    plugin, data_file, _, _ = setup_fragments(
        tmpdir, ctlr, CHANGELOG_YML_RELEASED_ONLY, fragments
    )

    plugin.release("1.1.0", data_file)

    data = plugin.load(data_file)
    assert data["1.1.0"] == {"added": ["fragment added entry"]}

    # the Unreleased key was not present before the release and is
    # not created by it
    assert "Unreleased" not in data


def test_release_fragments_empty_error(tmpdir, ctlr):
    plugin, data_file, _, _ = setup_fragments(
        tmpdir, ctlr, CHANGELOG_YML_EMPTY_UNRELEASED
    )

    with pytest.raises(ValueError, match="changelog fragments"):
        plugin.release("1.1.0", data_file)


@pytest.mark.parametrize(
    "filename,content,expected",
    [
        # an empty file loads as None which is not a mapping
        ("002-empty.yaml", "", "needs to contain a mapping"),
        # sections are case-sensitive so `Added` is unknown
        (
            "002-unknown-section.yaml",
            "Added:\n- some entry\n",
            "valid sections are: added, fixed, changed, deprecated, removed, security",
        ),
        ("002-not-a-list.yaml", "added: some entry\n", "needs to be a list"),
        ("002-not-a-string.yaml", "added:\n- 123\n", "not a string"),
        (
            "002-unparseable.yaml",
            "added: [unclosed\n",
            "Could not parse changelog fragment",
        ),
    ],
)
def test_release_fragment_validation(tmpdir, ctlr, filename, content, expected):
    fragments = {
        "001-valid.yaml": "added:\n- valid fragment entry\n",
        filename: content,
    }
    plugin, data_file, _, fragments_dir = setup_fragments(
        tmpdir, ctlr, CHANGELOG_YML_UNRELEASED, fragments
    )

    with open(data_file) as fh:
        data_before = fh.read()

    with pytest.raises(ValueError) as excinfo:
        plugin.release("1.1.0", data_file)

    message = str(excinfo.value)

    # the error names the offending fragment file
    assert filename in message
    assert expected in message

    # all fragments are validated before anything is written or deleted
    with open(data_file) as fh:
        assert fh.read() == data_before
    assert sorted(os.listdir(fragments_dir)) == sorted(["001-valid.yaml", filename])


def test_release_fragments_dir_relative_to_data_file(tmpdir, ctlr, monkeypatch):
    fragments = {"001-first.yaml": "added:\n- project fragment entry\n"}
    plugin, data_file, _, fragments_dir = setup_fragments(
        tmpdir, ctlr, CHANGELOG_YML_RELEASED_ONLY, fragments
    )

    # set up a decoy changelog.d in a different working directory
    cwd = os.path.join(f"{tmpdir}", "elsewhere")
    decoy = os.path.join(cwd, "changelog.d", "001-decoy.yaml")
    write_file(decoy, "added:\n- decoy fragment entry\n")
    monkeypatch.chdir(cwd)

    plugin.release("1.1.0", data_file)

    data = plugin.load(data_file)

    # fragment mode activated against the data file's directory,
    # not the current working directory
    assert data["1.1.0"] == {"added": ["project fragment entry"]}
    assert os.listdir(fragments_dir) == []
    assert os.path.exists(decoy)


def test_release_fragments_generates_md(tmpdir, ctlr):
    fragments = {"001-first.yaml": "added:\n- fragment added entry\n"}
    plugin, data_file, md_file, _ = setup_fragments(
        tmpdir, ctlr, CHANGELOG_YML_UNRELEASED, fragments
    )

    plugin.release("1.1.0", data_file)

    with open(md_file) as fh:
        content = fh.read()

    assert "## 1.1.0" in content
    assert "- unreleased added entry" in content
    assert "- fragment added entry" in content


def test_check_pass_on_fragment_added(tmpdir, ctlr):
    plugin, repo_dir, data_file, fragments_dir, base_commit = setup_check_repo(
        tmpdir, ctlr
    )
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    write_file(os.path.join(fragments_dir, "001-first.yaml"), "added:\n- entry\n")
    scratch_git_commit(repo_dir, "add fragment")

    # default base resolution (origin/main) and explicit base both pass
    plugin.check(data_file)
    plugin.check(data_file, base=base_commit)


def test_check_pass_on_fragment_deleted(tmpdir, ctlr):
    plugin, repo_dir, data_file, fragments_dir, _ = setup_check_repo(tmpdir, ctlr)

    write_file(os.path.join(fragments_dir, "001-first.yaml"), "added:\n- entry\n")
    base_commit = scratch_git_commit(repo_dir, "add fragment")
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    run_git(repo_dir, "rm", "changelog.d/001-first.yaml")
    scratch_git_commit(repo_dir, "remove fragment")

    plugin.check(data_file)


def test_check_pass_on_data_file_change(tmpdir, ctlr):
    plugin, repo_dir, data_file, _, base_commit = setup_check_repo(tmpdir, ctlr)
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    write_file(data_file, CHANGELOG_YML_UNRELEASED)
    scratch_git_commit(repo_dir, "update changelog")

    plugin.check(data_file)


def test_check_data_file_in_subdir(tmpdir, ctlr):
    # data file and fragments dir in a repo subdirectory - diff paths
    # are repo-root-relative so both sides need to be relativized
    # against the git toplevel, not against dirname(data_file)
    repo_dir = init_scratch_git_repo(os.path.join(f"{tmpdir}", "repo"))
    data_file = os.path.join(repo_dir, "sub", "CHANGELOG.yml")
    fragments_dir = os.path.join(repo_dir, "sub", "changelog.d")

    write_file(data_file, CHANGELOG_YML_EMPTY_UNRELEASED)
    write_file(os.path.join(fragments_dir, ".gitkeep"), "")
    base_commit = scratch_git_commit(repo_dir, "base")
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    plugin = instantiate(tmpdir, ctlr, data_file=data_file)

    # a non-ascii fragment file name must still match (quotepath off)
    write_file(os.path.join(fragments_dir, "001-für.yaml"), "added:\n- entry\n")
    scratch_git_commit(repo_dir, "add fragment")

    plugin.check(data_file)

    # changes outside the subdir do not pass the check
    run_git(repo_dir, "rm", "sub/changelog.d/001-für.yaml")
    write_file(os.path.join(repo_dir, "CHANGELOG.yml"), CHANGELOG_YML_UNRELEASED)
    write_file(os.path.join(repo_dir, "changelog.d", "001-decoy.yaml"), "added:\n- x\n")
    base_commit = scratch_git_commit(repo_dir, "reset to decoy changes only")
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    write_file(os.path.join(repo_dir, "CHANGELOG.yml"), CHANGELOG_YML_EMPTY_UNRELEASED)
    write_file(os.path.join(repo_dir, "changelog.d", "002-decoy.yaml"), "added:\n- y\n")
    scratch_git_commit(repo_dir, "more decoy changes outside sub/")

    with pytest.raises(PluginOperationStopped, match="No changelog changes"):
        plugin.check(data_file)


def test_check_fail_no_changelog_changes(tmpdir, ctlr):
    plugin, repo_dir, data_file, _, base_commit = setup_check_repo(tmpdir, ctlr)
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    write_file(os.path.join(repo_dir, "unrelated.txt"), "unrelated change\n")
    scratch_git_commit(repo_dir, "unrelated change")

    with pytest.raises(PluginOperationStopped, match="No changelog changes"):
        plugin.check(data_file)


def test_check_fail_bad_base(tmpdir, ctlr):
    plugin, _, data_file, _, _ = setup_check_repo(tmpdir, ctlr)

    with pytest.raises(PluginOperationStopped, match="does-not-exist"):
        plugin.check(data_file, base="does-not-exist")


def test_check_default_base_fallback(tmpdir, ctlr):
    plugin, repo_dir, data_file, fragments_dir, base_commit = setup_check_repo(
        tmpdir, ctlr
    )

    # only origin/master exists - origin/HEAD and origin/main do not
    # resolve, so the default base falls back to origin/master
    scratch_git_origin_ref(repo_dir, "master", base_commit)

    write_file(os.path.join(fragments_dir, "001-first.yaml"), "added:\n- entry\n")
    scratch_git_commit(repo_dir, "add fragment")

    plugin.check(data_file)


def test_check_fail_no_default_base(tmpdir, ctlr):
    plugin, repo_dir, data_file, fragments_dir, _ = setup_check_repo(tmpdir, ctlr)

    write_file(os.path.join(fragments_dir, "001-first.yaml"), "added:\n- entry\n")
    scratch_git_commit(repo_dir, "add fragment")

    with pytest.raises(PluginOperationStopped, match="please pass --base"):
        plugin.check(data_file)


def test_check_cli_exit_codes(tmpdir):
    home = os.path.join(f"{tmpdir}", "home")
    write_file(os.path.join(home, "config.yml"), CTL_CONFIG_YML)

    repo_dir = init_scratch_git_repo(os.path.join(f"{tmpdir}", "repo"))
    data_file = os.path.join(repo_dir, "CHANGELOG.yml")
    write_file(data_file, CHANGELOG_YML_EMPTY_UNRELEASED)
    write_file(os.path.join(repo_dir, "changelog.d", ".gitkeep"), "")
    base_commit = scratch_git_commit(repo_dir, "base")
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    cmd = [
        "ctl",
        "changelog",
        "check",
        "--data-file",
        data_file,
        "--home",
        home,
    ]

    # no changelog changes on the branch - exit code 1
    write_file(os.path.join(repo_dir, "unrelated.txt"), "unrelated change\n")
    scratch_git_commit(repo_dir, "unrelated change")

    failing = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
    assert failing.returncode == 1
    # the failure must come from the check op itself, not some other
    # exit-1 path (e.g. a config error during init)
    assert "No changelog changes" in failing.stdout + failing.stderr

    # changelog fragment added - exit code 0
    write_file(
        os.path.join(repo_dir, "changelog.d", "001-first.yaml"), "added:\n- entry\n"
    )
    scratch_git_commit(repo_dir, "add fragment")

    passing = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
    assert passing.returncode == 0, passing.stderr
