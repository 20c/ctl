import json
import logging
import os
import shutil
import subprocess

import munge
import pytest
import yaml

import ctl
from ctl.exceptions import PluginOperationStopped
from ctl.plugins.changelog import (
    CHANGELOG_SECTIONS,
    CI_BASE_REF_ENV,
    ChangelogVersionMissing,
)
from util import (
    CTL_CMD,
    init_scratch_git_repo,
    instantiate_test_plugin,
    run_git,
    scratch_git_commit,
    scratch_git_origin_ref,
)

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


# the check op reads the CI base-ref variables, and these tests run in
# CI - a `pull_request` job sets GITHUB_BASE_REF to a branch that does
# not exist in the scratch repositories, which would fail every default
# base-ref test. The tests that exercise the CI path set the variable
# themselves.
@pytest.fixture(autouse=True)
def isolate_ambient_ci_base_ref(monkeypatch):
    for var in CI_BASE_REF_ENV:
        monkeypatch.delenv(var, raising=False)


def clean_ci_base_ref_env():
    """
    a copy of the environment with the CI base-ref variables removed,
    for subprocess based tests

    the autouse fixture above already scrubs os.environ for the
    duration of a test, so a subprocess inherits a clean environment
    either way - passing this explicitly keeps the subprocess tests
    correct on their own terms rather than by way of a fixture they
    do not name
    """

    return {
        key: value for key, value in os.environ.items() if key not in CI_BASE_REF_ENV
    }


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


def test_release_fragments_preserves_nonstandard_unreleased_sections(tmpdir, ctlr):
    """
    a non-standard section under `Unreleased` (hand written, or produced
    by generate_datafile which lowercases arbitrary `### Section`
    headings into keys) must survive a fragment mode release - the
    legacy path carries every key over and dropping them here would be
    silent data loss
    """

    changelog_yml = """\
Unreleased:
  added:
  - unreleased added entry
  notes:
  - a non standard section entry
1.0.0:
  added:
  - initial release
"""

    fragments = {"001-first.yaml": "added:\n- fragment added entry\n"}
    plugin, data_file, _, _ = setup_fragments(tmpdir, ctlr, changelog_yml, fragments)

    plugin.release("1.1.0", data_file)

    data = plugin.load(data_file)

    assert data["1.1.0"]["added"] == ["unreleased added entry", "fragment added entry"]
    assert data["1.1.0"]["notes"] == ["a non standard section entry"]

    # and the scaffold reset did not leave the entry behind either
    assert "notes" not in data["Unreleased"]


CHANGELOG_YML_LOWERCASE_UNRELEASED = """\
unreleased:
  added:
  - unreleased added entry
  security: []
1.0.0:
  added:
  - initial release
"""


@pytest.mark.parametrize(
    "key,changelog_yml",
    [
        ("unreleased", CHANGELOG_YML_LOWERCASE_UNRELEASED),
        ("Unreleased", CHANGELOG_YML_UNRELEASED),
        (
            "UNRELEASED",
            CHANGELOG_YML_LOWERCASE_UNRELEASED.replace("unreleased:", "UNRELEASED:", 1),
        ),
    ],
)
def test_release_fragments_unreleased_key_casing(tmpdir, ctlr, key, changelog_yml):
    """
    the residual section is matched case insensitively - a changelog
    using `unreleased:` collects its residual entries just like one
    using `Unreleased:`, and keeps its own casing across the roll

    matching only the canonical casing rolled a release that silently
    omitted every residual entry, since fragment mode has no loud
    "nothing to move" failure to fall back on
    """

    fragments = {"001-first.yaml": "added:\n- fragment added entry\n"}
    plugin, data_file, _, fragments_dir = setup_fragments(
        tmpdir, ctlr, changelog_yml, fragments
    )

    plugin.release("1.1.0", data_file)

    data = plugin.load(data_file)

    # residual entries first, fragments after
    assert data["1.1.0"]["added"] == [
        "unreleased added entry",
        "fragment added entry",
    ]

    # the repository's own casing survives the roll, and no second
    # residual section is introduced alongside it
    assert key in data
    assert [k for k in data if f"{k}".casefold() == "unreleased"] == [key]
    assert data[key] == EMPTY_SECTIONS

    assert os.listdir(fragments_dir) == []


def test_release_legacy_lowercase_unreleased_key(tmpdir, ctlr):
    """
    legacy mode (no changelog.d directory) collects the residual
    entries under a lowercase key as well - it used to raise
    `No items exist in unreleased to be moved` instead
    """

    project_dir = os.path.join(f"{tmpdir}", "project")
    data_file = os.path.join(project_dir, "CHANGELOG.yml")
    md_file = os.path.join(project_dir, "CHANGELOG.md")

    write_file(data_file, CHANGELOG_YML_LOWERCASE_UNRELEASED)

    plugin = instantiate(tmpdir, ctlr, data_file=data_file, md_file=md_file)

    # no changelog.d directory - legacy mode
    assert not os.path.isdir(plugin.fragments_dir_path(data_file))

    plugin.release("1.1.0", data_file)

    data = plugin.load(data_file)

    assert data["1.1.0"] == {"added": ["unreleased added entry"]}
    assert data["unreleased"] == EMPTY_SECTIONS
    assert "Unreleased" not in data


def test_release_ambiguous_unreleased_keys(tmpdir, ctlr):
    """
    two residual sections differing only in casing must raise rather
    than have one of them guessed at - merging them silently is the
    same data loss this resolution fixes

    nothing may be written before the refusal: neither the changelog
    nor the fragment files
    """

    changelog_yml = """\
Unreleased:
  added:
  - capital unreleased entry
unreleased:
  added:
  - lowercase unreleased entry
1.0.0:
  added:
  - initial release
"""

    fragments = {"001-first.yaml": "added:\n- fragment added entry\n"}
    plugin, data_file, _, fragments_dir = setup_fragments(
        tmpdir, ctlr, changelog_yml, fragments
    )

    fragment_path = os.path.join(fragments_dir, "001-first.yaml")

    with open(data_file) as fh:
        changelog_before = fh.read()
    with open(fragment_path) as fh:
        fragment_before = fh.read()

    with pytest.raises(ValueError, match="more than one unreleased section"):
        plugin.release("1.1.0", data_file)

    with open(data_file) as fh:
        assert fh.read() == changelog_before
    with open(fragment_path) as fh:
        assert fh.read() == fragment_before

    assert os.listdir(fragments_dir) == ["001-first.yaml"]


def test_release_preserves_nonstandard_sections_under_lowercase_key(tmpdir, ctlr):
    """
    the non-standard section carry over is not narrowed by the case
    insensitive lookup - it is the provision the casing mismatch was
    bypassing in the first place
    """

    changelog_yml = """\
unreleased:
  added:
  - unreleased added entry
  notes:
  - a non standard section entry
1.0.0:
  added:
  - initial release
"""

    fragments = {"001-first.yaml": "added:\n- fragment added entry\n"}
    plugin, data_file, _, _ = setup_fragments(tmpdir, ctlr, changelog_yml, fragments)

    plugin.release("1.1.0", data_file)

    data = plugin.load(data_file)

    assert data["1.1.0"]["added"] == ["unreleased added entry", "fragment added entry"]
    assert data["1.1.0"]["notes"] == ["a non standard section entry"]
    assert "notes" not in data["unreleased"]


def test_resolve_unreleased_key(tmpdir, ctlr):
    plugin = instantiate(tmpdir, ctlr)

    assert plugin.resolve_unreleased_key({"Unreleased": {}}) == "Unreleased"
    assert plugin.resolve_unreleased_key({"unreleased": {}}) == "unreleased"
    assert plugin.resolve_unreleased_key({"UnReLeAsEd": {}}) == "UnReLeAsEd"
    assert plugin.resolve_unreleased_key({"1.0.0": {}}) is None
    assert plugin.resolve_unreleased_key({}) is None

    # a non string key (an unquoted `1.0:` parses as a float) must not
    # blow the comparison up
    assert plugin.resolve_unreleased_key({1.0: {}, "unreleased": {}}) == "unreleased"

    with pytest.raises(ValueError, match="more than one unreleased section"):
        plugin.resolve_unreleased_key({"unreleased": {}, "Unreleased": {}})


def test_release_fragment_duplicate_section_key(tmpdir, ctlr):
    """
    a duplicated section key inside one fragment must be an error -
    the fragment is deleted once collected, so letting the last key
    win would drop the shadowed entries unrecoverably
    """

    fragments = {
        "001-dupe.yaml": "added:\n- first entry\nfixed:\n- a fix\nadded:\n- second entry\n"
    }
    plugin, data_file, _, fragments_dir = setup_fragments(
        tmpdir, ctlr, CHANGELOG_YML_EMPTY_UNRELEASED, fragments
    )

    with pytest.raises(ValueError) as excinfo:
        plugin.release("1.1.0", data_file)

    message = str(excinfo.value)
    assert "001-dupe.yaml" in message
    assert "duplicate key" in message

    # nothing was written and the fragment is still on disk
    assert "1.1.0" not in plugin.load(data_file)
    assert os.listdir(fragments_dir) == ["001-dupe.yaml"]


def test_release_version_collision_non_string_key(tmpdir, ctlr):
    """
    an unquoted `1.0:` in the data file parses as a float - the
    collision guard needs to compare as strings, otherwise the release
    is written a second time under a differently typed key and the
    fragments are consumed
    """

    changelog_yml = """\
Unreleased:
  added: []
1.0:
  added:
  - initial release
"""

    fragments = {"001-first.yaml": "added:\n- fragment added entry\n"}
    plugin, data_file, _, fragments_dir = setup_fragments(
        tmpdir, ctlr, changelog_yml, fragments
    )

    with pytest.raises(ValueError, match="already exists"):
        plugin.release("1.0", data_file)

    # the fragment was not consumed by the rejected release
    assert os.listdir(fragments_dir) == ["001-first.yaml"]


def test_release_fragment_removal_failure_names_leftovers(tmpdir, ctlr, monkeypatch):
    """
    if a fragment cannot be removed after the release was written, the
    error has to name the fragments still on disk - they would
    otherwise be silently collected into the next release as well
    """

    fragments = {
        "001-a.yaml": "added:\n- entry a\n",
        "002-b.yaml": "added:\n- entry b\n",
    }
    plugin, data_file, md_file, fragments_dir = setup_fragments(
        tmpdir, ctlr, CHANGELOG_YML_EMPTY_UNRELEASED, fragments
    )

    real_remove = os.remove

    def fail_on_second(path, *args, **kwargs):
        if os.path.basename(path) == "002-b.yaml":
            raise OSError("permission denied")
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(os, "remove", fail_on_second)

    with pytest.raises(OSError) as excinfo:
        plugin.release("1.1.0", data_file)

    assert "002-b.yaml" in str(excinfo.value)

    # the md file was regenerated before the removal step, so a failing
    # removal does not also cost the markdown regeneration
    assert os.path.isfile(md_file)
    with open(md_file) as fh:
        assert "entry b" in fh.read()


def test_release_fragments_empty_error(tmpdir, ctlr):
    plugin, data_file, _, _ = setup_fragments(
        tmpdir, ctlr, CHANGELOG_YML_EMPTY_UNRELEASED
    )

    with pytest.raises(ValueError, match="changelog fragments"):
        plugin.release("1.1.0", data_file)


def test_release_existing_version_reports_leftover_fragments(tmpdir, ctlr):
    """
    releasing a version that already exists while fragments are still
    present is the non-atomic-release recovery case - the error has to
    say so, it is the only thing telling an operator their fragments
    would otherwise be counted twice
    """

    fragments = {"001-first.yaml": "added:\n- fragment added entry\n"}
    plugin, data_file, _, fragments_dir = setup_fragments(
        tmpdir, ctlr, CHANGELOG_YML_EMPTY_UNRELEASED, fragments
    )

    plugin.release("1.1.0", data_file)

    # a partially failed run leaves fragments behind for a version that
    # is already written
    write_file(
        os.path.join(fragments_dir, "002-leftover.yaml"), "added:\n- leftover entry\n"
    )

    with pytest.raises(ValueError, match="removed by hand") as excinfo:
        plugin.release("1.1.0", data_file)

    assert fragments_dir in str(excinfo.value)

    # nothing was consumed by the rejected release
    assert os.listdir(fragments_dir) == ["002-leftover.yaml"]


@pytest.mark.parametrize("absolute", [False, True])
def test_release_custom_fragments_dir(tmpdir, ctlr, absolute):
    """
    the fragments_dir config attribute has to be honored, and an
    absolute value has to be used as given rather than resolved against
    the data file's directory
    """

    project_dir = os.path.join(f"{tmpdir}", "project")
    data_file = os.path.join(project_dir, "CHANGELOG.yml")
    md_file = os.path.join(project_dir, "CHANGELOG.md")

    if absolute:
        fragments_dir = os.path.join(f"{tmpdir}", "elsewhere", "notes.d")
        configured = fragments_dir
    else:
        fragments_dir = os.path.join(project_dir, "notes.d")
        configured = "notes.d"

    write_file(data_file, CHANGELOG_YML_EMPTY_UNRELEASED)
    write_file(
        os.path.join(fragments_dir, "001-first.yaml"), "added:\n- fragment entry\n"
    )

    # the default location must be ignored entirely
    write_file(
        os.path.join(project_dir, "changelog.d", "999-decoy.yaml"),
        "added:\n- decoy entry\n",
    )

    plugin = instantiate(
        tmpdir,
        ctlr,
        data_file=data_file,
        md_file=md_file,
        fragments_dir=configured,
    )

    assert plugin.fragments_dir_path(data_file) == fragments_dir

    plugin.release("1.1.0", data_file)

    assert plugin.load(data_file)["1.1.0"] == {"added": ["fragment entry"]}
    assert os.listdir(fragments_dir) == []
    # the decoy in the default directory was never touched
    assert os.listdir(os.path.join(project_dir, "changelog.d")) == ["999-decoy.yaml"]


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


def test_check_relative_data_file(tmpdir, ctlr, monkeypatch):
    # `check` is exposed and can be called directly with a relative
    # data_file - `execute()` only abspaths it on the cli path, so
    # without hardening dirname() is "" and subprocess raises OSError
    # on cwd="", surfacing as a misleading "no git repository" error
    plugin, repo_dir, data_file, fragments_dir, base_commit = setup_check_repo(
        tmpdir, ctlr
    )
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    write_file(os.path.join(fragments_dir, "001-first.yaml"), "added:\n- entry\n")
    scratch_git_commit(repo_dir, "add fragment")

    monkeypatch.chdir(repo_dir)
    plugin.check(os.path.basename(data_file))


def test_check_pass_on_fragment_deleted(tmpdir, ctlr):
    plugin, repo_dir, data_file, fragments_dir, _ = setup_check_repo(tmpdir, ctlr)

    write_file(os.path.join(fragments_dir, "001-first.yaml"), "added:\n- entry\n")
    base_commit = scratch_git_commit(repo_dir, "add fragment")
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    run_git(repo_dir, "rm", "changelog.d/001-first.yaml")
    scratch_git_commit(repo_dir, "remove fragment")

    plugin.check(data_file)


@pytest.mark.parametrize(
    "path",
    [
        # `list_fragments` does not recurse, so a nested file would pass
        # the gate and then never be collected by `release`
        "changelog.d/2026/nested.yaml",
        # not a fragment file - editing the directory's readme is not a
        # changelog entry
        "changelog.d/README.md",
        "changelog.d/.hidden.yaml",
    ],
)
def test_check_fail_on_non_collected_fragment_path(tmpdir, ctlr, path):
    plugin, repo_dir, data_file, _, base_commit = setup_check_repo(tmpdir, ctlr)
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    write_file(os.path.join(repo_dir, path), "added:\n- entry\n")
    scratch_git_commit(repo_dir, "add non-fragment path")

    # the gate only accepts what `release` would actually collect
    with pytest.raises(PluginOperationStopped):
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

    # the message has to identify the base-ref guard specifically -
    # matching the ref name alone also matches the diff-failure and the
    # no-changes messages, so it cannot tell the three paths apart
    with pytest.raises(PluginOperationStopped, match="Could not resolve base ref"):
        plugin.check(data_file, base="does-not-exist")


def test_check_fail_outside_git_repository(tmpdir, ctlr):
    project_dir = os.path.join(f"{tmpdir}", "not-a-repo")
    data_file = os.path.join(project_dir, "CHANGELOG.yml")

    write_file(data_file, CHANGELOG_YML_EMPTY_UNRELEASED)
    os.makedirs(os.path.join(project_dir, "changelog.d"))

    plugin = instantiate(tmpdir, ctlr, data_file=data_file)

    with pytest.raises(PluginOperationStopped, match="Could not locate a git"):
        plugin.check(data_file)


def test_check_fail_no_merge_base(tmpdir, ctlr):
    """
    the diff guard is what turns a missing merge base (the shallow
    clone case the docs call out) into a loud failure instead of an
    unreadable one
    """

    plugin, repo_dir, data_file, fragments_dir, _ = setup_check_repo(tmpdir, ctlr)

    write_file(os.path.join(fragments_dir, "001-first.yaml"), "added:\n- entry\n")
    scratch_git_commit(repo_dir, "add fragment")

    # an orphan commit shares no history with HEAD, so there is no
    # merge base for the three-dot diff to resolve
    tree = run_git(repo_dir, "hash-object", "-w", "-t", "tree", os.devnull)
    orphan = run_git(repo_dir, "commit-tree", "-m", "orphan", tree)
    scratch_git_origin_ref(repo_dir, "main", orphan)

    with pytest.raises(PluginOperationStopped, match="Could not diff against base ref"):
        plugin.check(data_file)


def test_check_three_dot_diff_ignores_base_branch_changes(tmpdir, ctlr):
    """
    the diff has to be three-dot (against the merge base) - a two-dot
    diff reports changelog changes that landed on the base branch after
    the branch point, so a branch that touched nothing would pass
    """

    plugin, repo_dir, data_file, _, branch_point = setup_check_repo(tmpdir, ctlr)

    # the branch itself only touches code
    write_file(os.path.join(repo_dir, "src.py"), "print('hi')\n")
    scratch_git_commit(repo_dir, "code only")
    branch_head = run_git(repo_dir, "rev-parse", "HEAD")

    # meanwhile the base branch gains a changelog change of its own
    run_git(repo_dir, "checkout", "-b", "base-branch", branch_point)
    write_file(data_file, CHANGELOG_YML_UNRELEASED)
    base_commit = scratch_git_commit(repo_dir, "changelog change on base branch")
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    run_git(repo_dir, "checkout", branch_head)

    with pytest.raises(PluginOperationStopped, match="No changelog changes"):
        plugin.check(data_file)


def test_check_default_base_prefers_origin_head(tmpdir, ctlr):
    """
    origin/HEAD is the documented first candidate - it has to win over
    origin/main when both resolve
    """

    plugin, repo_dir, data_file, fragments_dir, branch_point = setup_check_repo(
        tmpdir, ctlr
    )

    write_file(os.path.join(fragments_dir, "001-first.yaml"), "added:\n- entry\n")
    fragment_commit = scratch_git_commit(repo_dir, "add fragment")

    # origin/HEAD sits at the fragment commit, so diffing against it
    # yields no changelog change - origin/main sits at the branch point
    # and would pass. Only the candidate order decides the outcome.
    scratch_git_origin_ref(repo_dir, "HEAD", fragment_commit)
    scratch_git_origin_ref(repo_dir, "main", branch_point)

    with pytest.raises(PluginOperationStopped, match="No changelog changes"):
        plugin.check(data_file)


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

    cmd = CTL_CMD + [
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

    # a leaked CI base-ref variable would pick a base ref that does not
    # exist in this scratch repository
    env = clean_ci_base_ref_env()

    failing = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, env=env)
    assert failing.returncode == 1
    # the failure must come from the check op itself, not some other
    # exit-1 path (e.g. a config error during init)
    assert "No changelog changes" in failing.stdout + failing.stderr

    # changelog fragment added - exit code 0
    write_file(
        os.path.join(repo_dir, "changelog.d", "001-first.yaml"), "added:\n- entry\n"
    )
    scratch_git_commit(repo_dir, "add fragment")

    passing = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, env=env)
    assert passing.returncode == 0, passing.stderr
    # exit 0 alone is not proof the op ran - assert it actually
    # reported the detection and did not log a swallowed error
    passing_output = passing.stdout + passing.stderr
    assert "Changelog change detected against" in passing_output
    assert "command error" not in passing_output

    # --base has to reach the op - if the argparse plumbing broke, the
    # op would silently fall back to default base resolution, which
    # passes here too, so point --base at a ref that must fail
    bad_base = subprocess.run(
        cmd + ["--base", "origin/does-not-exist"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        env=env,
    )
    assert bad_base.returncode == 1
    assert "origin/does-not-exist" in bad_base.stdout + bad_base.stderr


def test_check_ci_base_ref_unresolvable(tmpdir, ctlr, monkeypatch):
    """
    when CI names the target branch but the ref is not present, the
    check has to fail closed - falling back to the origin/HEAD guess
    would diff against the wrong branch and pass the gate on a
    changelog entry that arrived with that branch
    """

    plugin, repo_dir, data_file, fragments_dir, base_commit = setup_check_repo(
        tmpdir, ctlr
    )
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    write_file(os.path.join(repo_dir, "src.py"), "print('hi')\n")
    scratch_git_commit(repo_dir, "code only")

    monkeypatch.setenv("GITHUB_BASE_REF", "release-2.x")

    with pytest.raises(PluginOperationStopped, match="release-2.x"):
        plugin.check(data_file)


def test_cli_exit_code_on_unhandled_error(tmpdir):
    """
    an operation that fails with something other than a
    PluginOperationStopped must still exit non-zero - exiting 0 makes
    every validation error and every outright bug look like success to
    a calling script or CI gate
    """

    home = os.path.join(f"{tmpdir}", "home")
    write_file(os.path.join(home, "config.yml"), CTL_CONFIG_YML)

    data_file = os.path.join(f"{tmpdir}", "CHANGELOG.yml")
    write_file(data_file, CHANGELOG_YML_EMPTY_UNRELEASED)

    # generate_clean refuses to overwrite an existing data file and
    # raises a plain ValueError to do it
    result = subprocess.run(
        CTL_CMD
        + [
            "changelog",
            "generate_clean",
            "--data-file",
            data_file,
            "--home",
            home,
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "already exists" in result.stdout + result.stderr


def test_check_base_ref_from_ci_environment(tmpdir, ctlr, monkeypatch):
    """
    the origin/HEAD guess is only right for a branch that targets the
    default branch - when CI names the real target branch the check has
    to diff against that, otherwise the gate passes on a changelog
    entry that came in with the target branch rather than this change
    """

    repo_dir = init_scratch_git_repo(os.path.join(f"{tmpdir}", "repo"))
    data_file = os.path.join(repo_dir, "CHANGELOG.yml")
    fragments_dir = os.path.join(repo_dir, "changelog.d")

    write_file(data_file, CHANGELOG_YML_EMPTY_UNRELEASED)
    write_file(os.path.join(fragments_dir, ".gitkeep"), "")
    main_commit = scratch_git_commit(repo_dir, "base")
    scratch_git_origin_ref(repo_dir, "main", main_commit)

    # `develop` branches off main and carries somebody else's fragment
    run_git(repo_dir, "checkout", "-b", "develop")
    write_file(os.path.join(fragments_dir, "000-other.yaml"), "added:\n- other entry\n")
    develop_commit = scratch_git_commit(repo_dir, "other fragment")
    scratch_git_origin_ref(repo_dir, "develop", develop_commit)

    # this branch targets develop and adds no changelog entry at all
    run_git(repo_dir, "checkout", "-b", "feature")
    write_file(os.path.join(repo_dir, "src.py"), "print('hi')\n")
    scratch_git_commit(repo_dir, "code only")

    plugin = instantiate(tmpdir, ctlr, data_file=data_file)

    monkeypatch.setenv("GITHUB_BASE_REF", "develop")

    with pytest.raises(PluginOperationStopped):
        plugin.check(data_file)

    # without the CI hint the origin/HEAD -> origin/main guess picks up
    # develop's fragment and the gate passes on somebody else's entry
    monkeypatch.delenv("GITHUB_BASE_REF")
    plugin.check(data_file)


def test_check_ignores_ambient_git_env(tmpdir, ctlr, monkeypatch):
    """
    GIT_DIR / GIT_WORK_TREE override cwd based repository discovery -
    a tool invoked from a git hook or `git rebase --exec` inherits them
    and would otherwise probe an unrelated repository
    """

    # the data file lives in a subdirectory, so the git commands run
    # with that subdirectory as cwd - a relative GIT_DIR then resolves
    # against the wrong directory
    repo_dir = init_scratch_git_repo(os.path.join(f"{tmpdir}", "repo"))
    data_file = os.path.join(repo_dir, "sub", "CHANGELOG.yml")
    fragments_dir = os.path.join(repo_dir, "sub", "changelog.d")

    write_file(data_file, CHANGELOG_YML_EMPTY_UNRELEASED)
    write_file(os.path.join(fragments_dir, ".gitkeep"), "")
    base_commit = scratch_git_commit(repo_dir, "base")
    scratch_git_origin_ref(repo_dir, "main", base_commit)

    write_file(os.path.join(fragments_dir, "001-first.yaml"), "added:\n- entry\n")
    scratch_git_commit(repo_dir, "add fragment")

    plugin = instantiate(tmpdir, ctlr, data_file=data_file)

    # what git exports to a hook - a bare `.git` that only resolves
    # relative to the repository git itself was invoked from
    monkeypatch.setenv("GIT_DIR", ".git")

    plugin.check(data_file)


# release write fidelity (#32)
#
# `release` used to load the changelog, mutate the parsed structure and dump
# the whole thing back out. Every comment in the file was deleted by that
# round trip, and list indentation, string wrapping and non-ascii escaping
# changed across sections the release never touched. Only the lines the
# release actually changes are rewritten now, so what these tests pin is the
# bytes of everything else.


CHANGELOG_YML_COMMENTED = """\
# project change log
#
# New entries go in changelog.d/ fragments - do not append here.
1.1.0:
  added:
  - a long entry that is wrapped by hand across two lines rather than
    left to the writer to fold wherever it likes
  fixed:
  - 'an entry that is quoted because it starts with a `#` marker: `#31`'

# the first release, kept for the record
1.0.0:
  added:
  - initial release
"""


def read(path):
    with open(path, newline="") as fh:
        return fh.read()


def block_of(text, key):
    """
    returns the lines of one top level block, key line included
    """

    lines = text.splitlines()
    start = lines.index(f"{key}:")
    end = start + 1

    while end < len(lines) and (
        not lines[end] or lines[end].startswith((" ", "-", "#"))
    ):
        end += 1

    return lines[start:end]


def test_release_leaves_untouched_blocks_byte_identical(tmpdir, ctlr):
    """
    the release moves the residual entries into a new block and touches
    nothing else - every release already in the file comes out as the exact
    bytes it went in as, comments, hand wrapping and quoting included

    this is the regression test for #32: the previous writer reserialized
    the whole document, so both existing blocks came out reformatted and
    all three comments were deleted
    """

    changelog = f"{CHANGELOG_YML_COMMENTED}"
    unreleased = "Unreleased:\n  added:\n  - a new entry\n"

    plugin, data_file, _, _ = setup_fragments(tmpdir, ctlr, f"{unreleased}{changelog}")

    before = read(data_file)
    plugin.release("1.2.0", data_file)
    after = read(data_file)

    for key in ("1.1.0", "1.0.0"):
        assert block_of(after, key) == block_of(before, key)

    # every comment survives, including the one between two version blocks
    for comment in (
        "# project change log",
        "# New entries go in changelog.d/ fragments - do not append here.",
        "# the first release, kept for the record",
    ):
        assert comment in after

    # and the release itself happened
    assert yaml.safe_load(after)["1.2.0"] == {"added": ["a new entry"]}
    assert yaml.safe_load(after)["Unreleased"] == {
        section: [] for section in CHANGELOG_SECTIONS
    }


def test_release_new_block_matches_the_codec_writer(tmpdir, ctlr):
    """
    the block a release writes is rendered by the same codec that wrote the
    whole file before, so a changelog carrying no comments does not churn:
    what lands is what the previous writer would have written
    """

    plugin, data_file, _, _ = setup_fragments(tmpdir, ctlr, CHANGELOG_YML_UNRELEASED)

    plugin.release("1.1.0", data_file)
    after = read(data_file)

    expected = munge.get_codec("yaml")().dumps(
        {"1.1.0": {"added": ["unreleased added entry"]}}
    )

    assert "\n".join(block_of(after, "1.1.0")) + "\n" == expected


def test_release_twice_leaves_the_first_release_alone(tmpdir, ctlr):
    """
    rolling again must not re-touch what the previous roll wrote - a writer
    that reformats on every pass produces a whole-file diff for each release
    """

    plugin, data_file, _, fragments_dir = setup_fragments(
        tmpdir,
        ctlr,
        f"Unreleased:\n  added:\n  - first entry\n{CHANGELOG_YML_COMMENTED}",
    )

    plugin.release("1.2.0", data_file)
    after_first = read(data_file)

    write_file(
        os.path.join(fragments_dir, "001-second.yaml"), "fixed:\n- second entry\n"
    )
    plugin.release("1.3.0", data_file)
    after_second = read(data_file)

    assert block_of(after_second, "1.2.0") == block_of(after_first, "1.2.0")
    assert block_of(after_second, "1.1.0") == block_of(after_first, "1.1.0")
    assert block_of(after_second, "1.0.0") == block_of(after_first, "1.0.0")


def test_release_warns_about_comments_it_cannot_move(tmpdir, ctlr, caplog):
    """
    a comment inside the residual section annotates entries that are moving
    into the release, and only the entries move. That loss is the one this
    writer cannot avoid, so it is named - file and line - rather than done
    silently
    """

    changelog = (
        "Unreleased:\n"
        "  added:\n"
        "  # this note is about the entry below it\n"
        "  - an entry\n"
        "1.0.0:\n"
        "  added:\n"
        "  - initial release\n"
    )

    plugin, data_file, _, _ = setup_fragments(tmpdir, ctlr, changelog)

    with caplog.at_level(logging.WARNING):
        plugin.release("1.1.0", data_file)

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    ]

    assert any(
        f"{data_file}:3" in message
        and "this note is about the entry below it" in message
        for message in warnings
    ), warnings


def test_release_does_not_warn_about_a_hash_in_an_entry(tmpdir, ctlr, caplog):
    """
    a `#` inside an entry is data, not a comment - deciding by pattern
    rather than by what the parser reports would warn about a changelog
    entry that references an issue number
    """

    changelog = (
        "Unreleased:\n"
        "  fixed:\n"
        "  - 'fixed the thing, see `#31`'\n"
        "1.0.0:\n"
        "  added:\n"
        "  - initial release\n"
    )

    plugin, data_file, _, _ = setup_fragments(tmpdir, ctlr, changelog)

    with caplog.at_level(logging.WARNING):
        plugin.release("1.1.0", data_file)

    assert not [
        record for record in caplog.records if record.levelno >= logging.WARNING
    ]


def test_release_preserves_missing_trailing_newline(tmpdir, ctlr):
    """
    a file that does not end with a newline must not acquire one, and the
    appended block must not be glued onto its last line
    """

    changelog = "Unreleased:\n  added:\n  - a new entry\n1.0.0:\n  added:\n  - initial"

    plugin, data_file, _, _ = setup_fragments(tmpdir, ctlr, changelog)

    plugin.release("1.1.0", data_file)
    after = read(data_file)

    assert not after.endswith("\n")
    assert yaml.safe_load(after)["1.1.0"] == {"added": ["a new entry"]}
    assert yaml.safe_load(after)["1.0.0"] == {"added": ["initial"]}


def test_release_preserves_crlf_line_endings(tmpdir, ctlr):
    """
    a CRLF changelog stays CRLF - rewriting it as LF throughout is the
    whole-file diff this writer exists to avoid
    """

    changelog = CHANGELOG_YML_UNRELEASED.replace("\n", "\r\n")

    plugin, data_file, _, _ = setup_fragments(tmpdir, ctlr, changelog)

    plugin.release("1.1.0", data_file)
    after = read(data_file)

    assert "\r\n" in after
    assert "\n" not in after.replace("\r\n", "")
    assert yaml.safe_load(after)["1.1.0"] == {"added": ["unreleased added entry"]}


def test_release_with_unreleased_as_the_last_block(tmpdir, ctlr):
    """
    the residual section does not have to be the first block - when it is
    the last one there is no following key to bound it, and the new release
    is inserted above it by sort order
    """

    changelog = (
        "1.0.0:\n"
        "  added:\n"
        "  - initial release\n"
        "Unreleased:\n"
        "  added:\n"
        "  - a new entry\n"
    )

    plugin, data_file, _, _ = setup_fragments(tmpdir, ctlr, changelog)

    plugin.release("1.1.0", data_file)
    after = read(data_file)

    assert yaml.safe_load(after)["1.1.0"] == {"added": ["a new entry"]}
    assert yaml.safe_load(after)["Unreleased"] == {
        section: [] for section in CHANGELOG_SECTIONS
    }
    # existing block untouched, and the file still parses as one mapping
    assert block_of(after, "1.0.0") == ["1.0.0:", "  added:", "  - initial release"]


def test_release_with_empty_unreleased_and_fragments(tmpdir, ctlr):
    """
    in fragment mode the residual section is routinely empty - the release
    is collected from the fragments and the empty block is still reset in
    place
    """

    plugin, data_file, _, _ = setup_fragments(
        tmpdir,
        ctlr,
        CHANGELOG_YML_EMPTY_UNRELEASED,
        {"001-entry.yaml": "fixed:\n- a fragment entry\n"},
    )

    plugin.release("1.1.0", data_file)
    after = read(data_file)

    assert yaml.safe_load(after)["1.1.0"] == {"fixed": ["a fragment entry"]}
    assert yaml.safe_load(after)["Unreleased"] == {
        section: [] for section in CHANGELOG_SECTIONS
    }


def test_release_does_not_reorder_an_unsorted_changelog(tmpdir, ctlr):
    """
    the file is no longer globally re-sorted on every release. A changelog
    whose blocks are out of order keeps the order its author gave it, and
    only the new block is placed by sort order - re-sorting the whole file
    is a diff nobody asked for, and the markdown is sorted when it is
    generated either way
    """

    changelog = (
        "Unreleased:\n"
        "  added:\n"
        "  - a new entry\n"
        "1.0.0:\n"
        "  added:\n"
        "  - initial release\n"
        "1.0.5:\n"
        "  added:\n"
        "  - out of order on purpose\n"
    )

    plugin, data_file, md_file, _ = setup_fragments(tmpdir, ctlr, changelog)

    plugin.release("1.1.0", data_file)
    after = read(data_file)

    assert [key for key in yaml.safe_load(after)] == [
        "Unreleased",
        "1.1.0",
        "1.0.0",
        "1.0.5",
    ]

    # the markdown is generated in sorted order regardless
    with open(md_file) as fh:
        md = fh.read()

    assert md.index("## 1.1.0") < md.index("## 1.0.5") < md.index("## 1.0.0")


def test_release_json_data_file_still_uses_the_codec(tmpdir, ctlr):
    """
    only the yaml write path splices - a json changelog has no comments to
    preserve and keeps the whole-file codec write
    """

    project_dir = os.path.join(f"{tmpdir}", "json_project")
    data_file = os.path.join(project_dir, "CHANGELOG.json")
    md_file = os.path.join(project_dir, "CHANGELOG.md")

    write_file(
        data_file,
        '{"Unreleased": {"added": ["a new entry"]}, "1.0.0": {"added": ["initial"]}}',
    )

    plugin = instantiate(tmpdir, ctlr, data_file=data_file, md_file=md_file)
    plugin.release("1.1.0", data_file)

    with open(data_file) as fh:
        written = json.load(fh)

    assert written["1.1.0"] == {"added": ["a new entry"]}
    assert written["Unreleased"] == {section: [] for section in CHANGELOG_SECTIONS}
