"""
Plugin that allows you manage CHANGELOG.(md|yaml|json) files
"""

import argparse
import os
import os.path
import re
import subprocess

import confu.schema
import munge
import yaml
from natsort import natsorted

import ctl
from ctl.auth import expose
from ctl.docs import pymdgen_confu_types
from ctl.exceptions import PluginOperationStopped
from ctl.plugins import ExecutablePlugin

CHANGELOG_SECTIONS = ("added", "fixed", "changed", "deprecated", "removed", "security")

# the canonical residual section key, used when writing a changelog from
# scratch - an existing changelog's own casing is preserved instead, see
# `ChangelogPlugin.resolve_unreleased_key`
UNRELEASED_KEY = "Unreleased"

# environment variables through which CI systems expose the branch a
# change is merging into - used by the `check` operation to pick a base
# ref when none was passed

CI_BASE_REF_ENV = (
    # github actions, `pull_request` events
    "GITHUB_BASE_REF",
    # gitlab ci, merge request pipelines
    "CI_MERGE_REQUEST_TARGET_BRANCH_NAME",
)


def comment_lines(text):
    """
    Returns the 0-based line numbers of every yaml comment in `text`.

    A `#` only opens a comment where it is not part of a scalar, and the
    parser is the only thing that knows the difference - `- fixed '#31'`
    carries a `#` that is data, and a `#` on the line above it is not. The
    scanner reports the character range of every token it produces and
    skips comments entirely, so a `#` that falls outside all of those
    ranges is a comment. Matching `^\\s*#` instead would also claim the
    lines of a block scalar.

    **Arguments**

    - text (`str`): yaml document text

    **Returns**

    `set` of 0-based line numbers
    """

    spans = [
        (token.start_mark.index, token.end_mark.index)
        for token in yaml.scan(text, Loader=yaml.SafeLoader)
    ]

    lines = set()
    line = 0

    for index, char in enumerate(text):
        if char == "\n":
            line += 1
            continue
        if char != "#":
            continue
        if any(start <= index < end for start, end in spans):
            continue
        lines.add(line)

    return lines


class StrictFragmentLoader(yaml.SafeLoader):
    """
    A yaml safe loader that rejects duplicate mapping keys instead of
    silently letting the last one win.

    A changelog fragment is deleted once it has been collected into a
    release, so a duplicated section key would drop the shadowed
    entries unrecoverably.
    """

    def construct_mapping(self, node, deep=False):
        seen = set()

        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key `{key}`",
                    key_node.start_mark,
                )
            seen.add(key)

        return super().construct_mapping(node, deep=deep)


def temporary_plugin(ctl, name, **config):
    """
    instantiate an impromptu changelog plugin instance

    **Arguments**

    - ctl: ctl instance
    - name: instance name

    **Keyword Arguments**

    Any keyword arguments will be passed on to plugin
    config

    **Returns**

    `ChangeLogPlugin` instance
    """

    return ChangeLogPlugin({"type": "changelog", "name": name, "config": config}, ctl)


class ChangelogVersionMissing(KeyError):
    """
    Raised when a changlog data file is validated
    to contain a specific version but that version
    is missing
    """

    def __init__(self, data_file, version):
        """
        **Arguments**

        - data_file (`str`): file path to a CHANGELOG.(yaml|json) file
        - version (`str`)
        """

        super().__init__(
            f"Version {version} does not exist in changelog located at {data_file}"
        )


@pymdgen_confu_types()
class ChangeLogPluginConfig(confu.schema.Schema):
    """
    Config schema for the ChangeLogPlugin plugin
    """

    data_file = confu.schema.Str(
        default="CHANGELOG.yaml", help="path to a changelog data file"
    )
    md_file = confu.schema.Str(
        default="CHANGELOG.md", help="path to a changelog markdown file"
    )
    fragments_dir = confu.schema.Str(
        default="changelog.d",
        help="path to a changelog fragments directory - a relative "
        "path will be resolved against the directory containing "
        "the changelog data file",
    )


@ctl.plugin.register("changelog")
class ChangeLogPlugin(ExecutablePlugin):
    """
    manage changelog files
    """

    class ConfigSchema(ExecutablePlugin.ConfigSchema):
        config = ChangeLogPluginConfig()

    @classmethod
    def add_arguments(cls, parser, plugin_config, confu_cli_args):
        generate_parser = argparse.ArgumentParser(add_help=False)
        group = generate_parser.add_argument_group()
        group.add_argument(
            "--print",
            action="store_true",
            help="if set no file will be generated and output will be printed "
            " to console instead.",
        )
        confu_cli_args.add(group, "data_file", "md_file")

        # subparser that routes operation

        sub = parser.add_subparsers(title="Operation", dest="op")

        # operation `generate`

        sub.add_parser(
            "generate", help="generate CHANGELOG.md", parents=[generate_parser]
        )

        # operation `generate_datafile`

        sub.add_parser(
            "generate_datafile",
            help="generate CHANGELOG.yaml from CHANGELOG.md",
            parents=[generate_parser],
        )

        # operation `generate_clean`

        op_generate_empty = sub.add_parser(
            "generate_clean", help="generate fresh CHANGELOG.(yaml|json) file"
        )
        confu_cli_args.add(op_generate_empty, "data_file")

        # operation `release`

        op_release = sub.add_parser(
            "release",
            help="Create new section for release and move all items "
            "under unreleased to it - requires a CHANGELOG.(yaml|json) file. "
            "Will regenerate the CHANGELOG.md file after",
        )
        op_release.add_argument("version", help="release version", type=str)

        confu_cli_args.add(op_release, "data_file")

        # operation `check`

        op_check = sub.add_parser(
            "check",
            help="Check that the current branch touches the changelog - "
            "passes if the diff against the base ref contains changes to "
            "the changelog data file or the changelog fragments directory",
        )
        op_check.add_argument(
            "--base",
            help="git ref to diff against - if not specified the branch "
            "reported by the CI environment is used, falling back to the "
            "first of origin/HEAD, origin/main, origin/master that "
            "resolves",
            type=str,
        )

        confu_cli_args.add(op_check, "data_file")

    def load(self, changelog_filepath):
        data = munge.load_datafile(changelog_filepath)
        return data

    def execute(self, **kwargs):
        super().execute(**kwargs)

        if "data_file" in kwargs:
            kwargs["data_file"] = os.path.abspath(kwargs["data_file"])

        if "md_file" in kwargs:
            kwargs["md_file"] = os.path.abspath(kwargs["md_file"])

        fn = self.get_op(kwargs.get("op"))
        fn(**kwargs)

    def sort_changelog(self, changelog):
        """
        Takes a changelog `dict` and sorts keys by version using
        natural sort

        Returns the sorted `dict`
        """

        changelog_list = []
        for key in natsorted(list(changelog.keys()), reverse=True):
            changelog_list.append((key, changelog.get(key)))

        return dict(changelog_list)

    def resolve_unreleased_key(self, changelog):
        """
        Returns the key under which the residual (unreleased) entries are
        stored in the changelog, matched case insensitively.

        A changelog written by `generate_clean` uses `Unreleased`, but a
        hand maintained one may use any casing - matching only the
        canonical form silently drops every residual entry in fragment
        mode, which is exactly the data loss the non-standard section
        carry over below exists to prevent.

        Keys are compared as strings for the same reason
        `release` compares them that way: an unquoted `1.0:` in a yaml
        changelog parses as a float.

        **Arguments**

        - changelog (`dict`): loaded changelog data

        **Returns**

        `str` the matching key, or `None` if the changelog has none
        """

        matches = [key for key in changelog if f"{key}".casefold() == "unreleased"]

        if len(matches) > 1:
            # guessing which one was meant would merge two sections the
            # author kept apart - the same silent data loss in a
            # different shape
            raise ValueError(
                "Changelog contains more than one unreleased section: "
                f"{', '.join(sorted(f'{key}' for key in matches))} - "
                "rename all but one of them before releasing"
            )

        return matches[0] if matches else None

    def fragments_dir_path(self, data_file):
        """
        Returns the resolved file path to the changelog fragments
        directory.

        A relative `fragments_dir` config value is resolved against
        the directory containing the changelog data file, an absolute
        value is used as is.

        **Arguments**

        - data_file (`str`): file path to a CHANGELOG.(yaml|json) file

        **Returns**

        `str`: file path to the changelog fragments directory
        """

        fragments_dir = self.get_config("fragments_dir")

        if not os.path.isabs(fragments_dir):
            fragments_dir = os.path.join(os.path.dirname(data_file), fragments_dir)

        return fragments_dir

    def load_fragment(self, filepath):
        """
        Loads and validates a single changelog fragment file

        A fragment file needs to contain a mapping of valid changelog
        sections to lists of change strings

        **Arguments**

        - filepath (`str`): file path to a changelog fragment file

        **Returns**

        fragment `dict`
        """

        try:
            with open(filepath, encoding="utf-8") as fh:
                data = yaml.load(fh, Loader=StrictFragmentLoader)
        except Exception as exc:
            raise ValueError(
                f"Could not parse changelog fragment {filepath}: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"Changelog fragment {filepath} needs to contain a mapping "
                "of changelog sections to lists of changes"
            )

        for change_type, changes in list(data.items()):
            if change_type not in CHANGELOG_SECTIONS:
                raise ValueError(
                    f"Changelog fragment {filepath} contains unknown section "
                    f"`{change_type}` - valid sections are: "
                    f"{', '.join(CHANGELOG_SECTIONS)}"
                )
            if not isinstance(changes, list):
                raise ValueError(
                    f"Changelog fragment {filepath}: section `{change_type}` "
                    "needs to be a list of changes"
                )
            for change in changes:
                if not isinstance(change, str):
                    raise ValueError(
                        f"Changelog fragment {filepath}: section `{change_type}` "
                        f"contains an entry that is not a string: {change!r}"
                    )

        return data

    def is_fragment_filename(self, filename):
        """
        Returns whether the specified file name is a changelog fragment
        file name.

        Fragment files are `*.yaml` / `*.yml` files - hidden files and
        files with other extensions (`README.md`, `.gitkeep`) are not
        fragments.

        **Arguments**

        - filename (`str`): file name (not a path)

        **Returns**

        `bool`
        """

        if filename.startswith("."):
            return False

        return os.path.splitext(filename)[1] in (".yaml", ".yml")

    def list_fragments(self, fragments_dir):
        """
        Returns the file paths of all changelog fragment files found
        in the specified directory, sorted by file name.

        Fragment files are `*.yaml` / `*.yml` files - hidden files and
        files with other extensions are ignored.

        **Arguments**

        - fragments_dir (`str`): file path to a changelog fragments
        directory

        **Returns**

        fragment file paths `list`
        """

        files = []

        for filename in sorted(os.listdir(fragments_dir)):
            if not self.is_fragment_filename(filename):
                continue
            filepath = os.path.join(fragments_dir, filename)
            if not os.path.isfile(filepath):
                continue
            files.append(filepath)

        return files

    def load_fragments(self, fragments_dir):
        """
        Loads and validates all changelog fragment files found in the
        specified directory.

        Fragment files are `*.yaml` / `*.yml` files and are processed
        sorted by file name - hidden files and files with other
        extensions are ignored.

        **Arguments**

        - fragments_dir (`str`): file path to a changelog fragments
        directory

        **Returns**

        `tuple` of (fragment file paths `list`, merged sections `dict`)
        """

        files = self.list_fragments(fragments_dir)

        sections = {section: [] for section in CHANGELOG_SECTIONS}

        for filepath in files:
            for change_type, changes in list(self.load_fragment(filepath).items()):
                sections[change_type].extend(changes)

        return files, sections

    def collect_release_section(
        self, changelog, fragments_dir, fragment_mode, unreleased_key
    ):
        """
        Collects the changes that are to be moved into a new release
        section.

        In fragment mode the residual entries under `Unreleased` are
        merged first, followed by the changelog fragment entries in
        file name order. In legacy mode only the `Unreleased` entries
        are used and no fragments are collected.

        All fragments are loaded and validated here, before the caller
        writes anything.

        **Arguments**

        - changelog (`dict`): loaded changelog data
        - fragments_dir (`str`): file path to the changelog fragments
        directory
        - fragment_mode (`bool`): whether to collect changelog fragments
        - unreleased_key (`str`): the key the residual entries are stored
        under, or `None` if the changelog has none. The caller resolves it
        with `resolve_unreleased_key` before anything is written, and that
        resolution is the authoritative one - resolving again here could
        only ever disagree with the key the caller then resets.

        **Returns**

        `tuple` of (release section `dict`, fragment file paths `list`)
        """

        unreleased = (changelog.get(unreleased_key) if unreleased_key else None) or {}
        release_section = {}

        if not fragment_mode:
            for change_type, changes in list(unreleased.items()):
                if changes:
                    release_section[change_type] = [change for change in changes]

            return release_section, []

        fragment_files, fragment_sections = self.load_fragments(fragments_dir)

        if any(changes for changes in unreleased.values()):
            print(
                "Consider moving the items under `Unreleased` to "
                f"changelog fragments in {fragments_dir}"
            )

        for change_type in CHANGELOG_SECTIONS:
            changes = [change for change in unreleased.get(change_type) or []]
            changes.extend(fragment_sections.get(change_type) or [])
            if changes:
                release_section[change_type] = changes

        # carry over any non-standard sections that exist under
        # `Unreleased` - the legacy path preserves everything it finds
        # there and dropping them in fragment mode would be silent
        # data loss

        for change_type, changes in list(unreleased.items()):
            if change_type in CHANGELOG_SECTIONS:
                continue
            if changes:
                release_section[change_type] = [change for change in changes]

        return release_section, fragment_files

    def block_spans(self, text):
        """
        Returns the line span each top level key of a yaml mapping document
        occupies.

        The boundaries come from the parser's own marks rather than from
        matching indentation: a changelog entry may be indented any way
        that parses, and a `-` at column 0 inside a section list is the
        common case.

        Blank lines and comment lines that sit between two blocks are
        counted as part of neither. A comment above a key belongs to that
        key, and a writer that swallowed it into the block above would move
        somebody's annotation onto another release.

        **Arguments**

        - text (`str`): yaml document text

        **Returns**

        `list` of `(key, lead, start, end)` tuples, where `lead` is the
        first line of the block's leading comment run, `start` the line the
        key is on and `end` the first line after the block. All 0-based,
        `end` exclusive.
        """

        node = yaml.compose(text, Loader=yaml.SafeLoader)

        if node is None:
            return []

        if not isinstance(node, yaml.MappingNode):
            raise ValueError(
                "Changelog data file does not contain a mapping of versions to changes"
            )

        lines = text.splitlines(keepends=True)
        comments = comment_lines(text)

        def is_comment(number):
            return number in comments and lines[number].lstrip().startswith("#")

        def is_gap(number):
            return is_comment(number) or not lines[number].strip()

        spans = []

        for position, (key_node, _) in enumerate(node.value):
            start = key_node.start_mark.line

            if position + 1 < len(node.value):
                end = node.value[position + 1][0].start_mark.line
            else:
                end = len(lines)

            while end > start + 1 and is_gap(end - 1):
                end -= 1

            lead = start
            while lead > 0 and is_gap(lead - 1):
                lead -= 1

            spans.append((f"{key_node.value}", lead, start, end))

        return spans

    def render_block(self, key, value):
        """
        Renders a single top level changelog block.

        The same codec that writes the whole file elsewhere, so a block
        written here is byte for byte the block the file-wide writer would
        have produced.
        """

        return munge.get_codec("yaml")().dumps({key: value})

    def write_release_yaml(
        self, data_file, version, release_section, unreleased_key, existing_keys
    ):
        """
        Writes a release into a yaml changelog by rewriting only the lines
        the release actually changes: the residual section is reset in
        place and the new release block is inserted at its sorted position.

        Everything else in the file - comments, indentation, line wrapping,
        quoting, the order of blocks already there - is left as the bytes
        it already was. Reserializing the parsed document instead is what
        deletes every comment in the file and reformats sections the
        release never touched.

        Two consequences worth knowing about:

        - the file is no longer globally re-sorted on every release. A
          changelog whose blocks are out of order stays that way, and only
          the new block is placed by sort order
        - a comment inside the residual section is attached to entries that
          are moving into the release, and cannot come along. That is
          warned about rather than done silently

        **Arguments**

        - data_file (`str`): file path to a CHANGELOG.(yaml|yml) file
        - version (`str`): version name (eg. tag name)
        - release_section (`dict`): the changes to write under `version`
        - unreleased_key (`str`): the key holding the residual entries, or
          `None` if the changelog has none
        - existing_keys (`list`): the changelog's keys, for sorting
        """

        # newline="" so the file's own line endings survive the read - with
        # translation on, a CRLF changelog would be rewritten as LF
        # throughout, which is the whole-file diff this is here to avoid
        with open(data_file, newline="") as fh:
            text = fh.read()

        newline = "\r\n" if "\r\n" in text else "\n"
        ends_with_newline = text.endswith(("\n", "\r"))
        lines = text.splitlines(keepends=True)

        spans = self.block_spans(text)

        # a file that does not end with a newline is terminated for the
        # duration of the edit, so an appended block cannot end up glued to
        # its last line, and un-terminated again on the way out
        if lines and not ends_with_newline:
            lines[-1] = f"{lines[-1]}{newline}"

        def render(key, value):
            block = self.render_block(key, value)
            return [f"{line}{newline}" for line in block.splitlines()]

        # sorted position of the new block, expressed against the keys as
        # they are, so an out of order file is not silently reordered
        ranking = {
            f"{key}": rank
            for rank, key in enumerate(
                natsorted(
                    [f"{key}" for key in existing_keys] + [f"{version}"], reverse=True
                )
            )
        }

        insert_at = len(lines)

        for key, lead, _, _ in spans:
            if ranking.get(key, -1) > ranking[f"{version}"]:
                insert_at = lead
                break

        edits = [(insert_at, insert_at, render(version, release_section))]

        if unreleased_key is not None:
            _, _, start, end = next(
                span for span in spans if span[0] == f"{unreleased_key}"
            )

            moved = sorted(
                number for number in comment_lines(text) if start <= number < end
            )

            for number in moved:
                self.log.warning(
                    f"{data_file}:{number + 1}: comment dropped by the release - "
                    f"{lines[number].strip()} - it annotates entries that are "
                    f"moving into {version}, and only the entries move"
                )

            reset = {section: [] for section in CHANGELOG_SECTIONS}
            edits.append((start, end, render(unreleased_key, reset)))

        # bottom up, so an earlier edit cannot shift a later edit's lines
        for start, end, block in sorted(edits, key=lambda edit: edit[0], reverse=True):
            lines[start:end] = block

        output = "".join(lines)

        if not ends_with_newline:
            output = output[: -len(newline)]

        with open(data_file, "w", newline="") as fh:
            fh.write(output)

    @expose("ctl.{plugin_name}.release")
    def release(self, version, data_file, **kwargs):
        """
        Adds the specified release to the changelog.

        This will validate and move all items under "unreleased"
        to a new section for the specified release version

        If a changelog fragments directory exists, all changelog
        fragment files in it will be collected into the release
        section as well and deleted afterwards

        **Arguments**

        - version (`str`): version mame (eg. tag name)
        - data_file (`str`): file path to a CHANGELOG.(yaml|json) file
        """
        changelog = self.load(data_file)

        # resolved up front, before anything is written: an ambiguous
        # changelog has to fail with the data file and the fragments
        # still untouched. Resolving after `changelog[version]` was
        # assigned would also let a release literally named `unreleased`
        # be mistaken for the residual section.

        unreleased_key = self.resolve_unreleased_key(changelog)

        fragments_dir = self.fragments_dir_path(data_file)
        fragment_mode = os.path.isdir(fragments_dir)

        # data file keys are compared as strings - an unquoted `1.0:`
        # in a yaml changelog parses as a float and would slip past a
        # plain `version in changelog` check, writing a second key for
        # a release that already exists

        existing_versions = {f"{key}" for key in changelog}

        if f"{version}" in existing_versions:
            if fragment_mode and self.list_fragments(fragments_dir):
                raise ValueError(
                    f"Release {version} already exists in {data_file}. If a "
                    "previous run wrote it and then failed before removing "
                    f"the changelog fragments in {fragments_dir}, those are "
                    "leftovers and need to be removed by hand - otherwise "
                    "the fragments are pending entries for the next release "
                    "and the version argument is wrong"
                )
            raise ValueError(f"Release {version} already exists in {data_file}")

        release_section, fragment_files = self.collect_release_section(
            changelog, fragments_dir, fragment_mode, unreleased_key
        )

        if not release_section:
            if fragment_mode:
                raise ValueError(
                    "No items exist in unreleased or in changelog fragments "
                    f"at {fragments_dir} to be moved"
                )
            raise ValueError("No items exist in unreleased to be moved")

        ext = os.path.splitext(data_file)[1][1:]

        if ext in ("yaml", "yml"):
            # only the lines the release changes are rewritten - see
            # `write_release_yaml`. Reserializing the parsed document, as
            # the codec path below does, is what deletes every comment in
            # the file and reformats sections nothing touched
            self.write_release_yaml(
                data_file,
                version,
                release_section,
                unreleased_key,
                list(changelog.keys()),
            )
        else:
            changelog[version] = release_section

            if unreleased_key:
                # the key the repository actually uses is reset, not a
                # normalized one - rewriting `unreleased:` to `Unreleased:`
                # behind the author's back is its own surprise diff
                #
                # legacy mode without a residual key never gets here: the
                # release section would be empty and the raise above has
                # already fired
                changelog[unreleased_key] = {
                    section: [] for section in CHANGELOG_SECTIONS
                }

            changelog = self.sort_changelog(changelog)

            codec = munge.get_codec(ext)

            with open(data_file, "w+") as fh:
                codec().dump(changelog, fh)

        self.log.info(f"Updated {data_file}")

        # the markdown is regenerated from the data file, which is
        # already written at this point - doing it before the fragments
        # are removed means a failing removal cannot also cost the
        # md regeneration

        self.generate(self.get_config("md_file"), data_file)

        self.remove_fragments(version, data_file, fragment_files)

    def remove_fragments(self, version, data_file, fragment_files):
        """
        Removes the changelog fragment files that were collected into a
        release.

        Raises `OSError` naming every fragment still on disk if one of them
        cannot be removed - a leftover fragment is collected into the next
        release as well, so the ones that were not reached have to be named
        rather than left to be discovered.

        **Arguments**

        - version (`str`): the release the fragments were collected into
        - data_file (`str`): file path to a CHANGELOG.(yaml|json) file
        - fragment_files (`list`): fragment file paths to remove
        """

        removed = []

        for filepath in fragment_files:
            try:
                os.remove(filepath)
            except OSError as exc:
                leftover = [path for path in fragment_files if path not in removed]
                raise OSError(
                    f"Release {version} was written to {data_file} but the "
                    f"changelog fragment {filepath} could not be removed: "
                    f"{exc} - the following fragments are still on disk and "
                    "need to be removed by hand, they would otherwise be "
                    f"collected into the next release as well: "
                    f"{', '.join(leftover)}"
                ) from exc

            removed.append(filepath)
            self.log.info(f"Removed changelog fragment {filepath}")

    def run_git(self, repo_dir, *args):
        """
        Runs a git command in the specified directory

        **Arguments**

        - repo_dir (`str`): directory to run the git command in
        - any other arguments will be passed to git as command
        arguments

        **Returns**

        `tuple` of (success `bool`, stdout `str`, stderr `str`)
        """

        # GIT_DIR / GIT_WORK_TREE and friends override cwd based
        # repository discovery, so a tool invoked from a git hook or
        # `git rebase --exec` would silently probe a different
        # repository than the one holding the changelog

        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }

        try:
            # errors="replace" so undecodable output bytes (e.g. a
            # non-utf8 filename under a C locale) cannot raise a bare
            # UnicodeDecodeError, which the cli would swallow into a
            # silent exit 0
            result = subprocess.run(
                ["git"] + list(args),
                cwd=repo_dir,
                capture_output=True,
                text=True,
                errors="replace",
                env=env,
            )
        except OSError as exc:
            return False, "", f"{exc}"

        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()

    @expose("ctl.{plugin_name}.check")
    def check(self, data_file, **kwargs):
        """
        Checks that the current branch contains changelog changes.

        Diffs the current HEAD against a base ref and passes if the
        diff touches the changelog data file or any path inside the
        changelog fragments directory.

        Raises a `PluginOperationStopped` error if no changelog
        changes are detected or the base ref cannot be resolved.

        **Arguments**

        - data_file (`str`): file path to a CHANGELOG.(yaml|json) file

        **Keyword Arguments**

        - base (`str`): git ref to diff against, if not specified the
        branch reported by the CI environment is used, falling back to
        the first of origin/HEAD, origin/main, origin/master that
        resolves
        """

        # `execute()` abspaths `data_file` for the cli path, but `check`
        # is exposed and can be called directly with a relative path -
        # `os.path.dirname("CHANGELOG.yaml")` would be `""` and
        # subprocess raises OSError on `cwd=""`

        data_file = os.path.abspath(data_file)

        fragments_dir = self.fragments_dir_path(data_file)
        base = kwargs.get("base")
        repo_dir = os.path.dirname(data_file)

        success, toplevel, error = self.run_git(
            repo_dir, "rev-parse", "--show-toplevel"
        )

        if not success:
            raise PluginOperationStopped(
                self,
                f"Could not locate a git repository containing {data_file} "
                f"(changelog fragments directory: {fragments_dir}): {error}",
            )

        if base:
            success, _, error = self.run_git(repo_dir, "rev-parse", "--verify", base)
            if not success:
                raise PluginOperationStopped(
                    self,
                    f"Could not resolve base ref `{base}` to check for "
                    f"changelog changes ({data_file}, fragments directory "
                    f"{fragments_dir}): {error}",
                )
        else:
            # CI systems expose the branch the change is actually
            # merging into - the origin/HEAD guess below is only the
            # right answer for a branch that targets the default
            # branch, and guessing wrong makes the gate pass on
            # somebody else's changelog entry

            for variable in CI_BASE_REF_ENV:
                value = os.environ.get(variable)
                if not value:
                    continue

                candidate = f"origin/{value}"
                success, _, error = self.run_git(
                    repo_dir, "rev-parse", "--verify", candidate
                )

                # CI named the target branch, so it is known - falling
                # back to the origin/HEAD guess here would diff against
                # the wrong branch and pass the gate on a changelog
                # entry that came in with that branch

                if not success:
                    raise PluginOperationStopped(
                        self,
                        f"${variable} names `{value}` as the branch this "
                        f"change merges into, but `{candidate}` does not "
                        f"resolve: {error} - fetch the base ref, or pass "
                        "--base explicitly",
                    )

                base = candidate
                self.log.info(f"Using base ref `{base}` from ${variable}")
                break

        if not base:
            for candidate in ("origin/HEAD", "origin/main", "origin/master"):
                success, _, _ = self.run_git(
                    repo_dir, "rev-parse", "--verify", candidate
                )
                if success:
                    base = candidate
                    break

            if not base:
                raise PluginOperationStopped(
                    self,
                    "Could not resolve a default base ref (tried origin/HEAD, "
                    "origin/main, origin/master) to check for changelog "
                    f"changes ({data_file}, fragments directory "
                    f"{fragments_dir}) - please pass --base",
                )

            self.log.warning(
                f"No base ref specified - guessed `{base}`. This is only "
                "correct for a branch that targets the default branch - "
                "pass --base to diff against the branch this change "
                "actually merges into"
            )

        # core.quotepath=off so non-ascii paths come out raw instead of
        # quoted+octal-escaped (which would never match the comparison
        # below); --no-relative pins root-relative output even when the
        # user has diff.relative set
        success, diff, error = self.run_git(
            repo_dir,
            "-c",
            "core.quotepath=off",
            "diff",
            "--no-relative",
            "--name-only",
            f"{base}...HEAD",
        )

        if not success:
            raise PluginOperationStopped(
                self,
                f"Could not diff against base ref `{base}` to check for "
                f"changelog changes ({data_file}, fragments directory "
                f"{fragments_dir}): {error} - if the cause is a missing "
                "merge base, the checkout is likely shallow and needs the "
                "base ref's history fetched first",
            )

        # both sides of the path comparison need to be realpath'd
        # as symlinked directories would mismatch otherwise

        toplevel = os.path.realpath(toplevel)
        rel_data_file = os.path.relpath(os.path.realpath(data_file), toplevel)
        rel_fragments_dir = os.path.relpath(
            os.path.realpath(fragments_dir), toplevel
        ).rstrip("/")

        # only paths that `release` would actually collect count - a
        # fragment in a subdirectory is not collected, and a
        # `changelog.d/README.md` edit is not a changelog entry, so
        # neither may satisfy the gate

        for path in diff.splitlines():
            path = path.strip()

            if not path:
                continue

            if path == rel_data_file:
                self.log.info(f"Changelog change detected against {base}: {path}")
                return

            if os.path.dirname(path) == rel_fragments_dir and self.is_fragment_filename(
                os.path.basename(path)
            ):
                self.log.info(f"Changelog change detected against {base}: {path}")
                return

        raise PluginOperationStopped(
            self,
            f"No changelog changes detected against base ref `{base}` - "
            f"expected changes to {rel_data_file} or changelog fragments "
            f"in {rel_fragments_dir}/",
        )

    @expose("ctl.{plugin_name}.generate")
    def generate(self, md_file, data_file, **kwargs):
        """
        Generates a changelog markdown filefrom
        a CHANGELOG.(yaml|json) file that follows the 20c changelog
        format

        **Arguments**

        - md_file (`str`): file path to a CHANGELOG.md file
        this is where the output will be written to
        - data_file (`str`): file path to a CHANGELOG.(yaml|json) file

        **Keyword Arguments**

        - print (`bool=False`): if True print the generated changelog
        to stdout instead of writing to a file
        """

        changelog = self.datafile_to_md(data_file)
        self.log.info(f"Generating {md_file}")

        if kwargs.get("print"):
            print(changelog)
            return

        with open(md_file, "w+") as fh:
            fh.write(changelog)

    @expose("ctl.{plugin_name}.generate_clean")
    def generate_clean(self, data_file, **kwargs):
        """
        Will generate a clean CHANGELOG.(yaml|json) file with
        just an `unreleased` section in it.

        Will fail if a file already exists

        **Arguments**

        - data_file (`str`): file path to a CHANGELOG.(yaml|json) file
        this is where the output will be written to
        """

        if os.path.exists(data_file):
            raise ValueError(f"File already exists: {data_file}")

        changelog = {UNRELEASED_KEY: {section: [] for section in CHANGELOG_SECTIONS}}

        codec = os.path.splitext(data_file)[1][1:]
        codec = munge.get_codec(codec)
        self.log.info(f"Generating {data_file}")
        with open(data_file, "w+") as fh:
            codec().dump(changelog, fh)

    @expose("ctl.{plugin_name}.generate_datafile")
    def generate_datafile(self, md_file, data_file, **kwargs):
        """
        Generates a changelog data file (yaml, json etc.) from
        a CHANGELOG.md file that follows the 20c changelog
        format.

        **Arguments**

        - md_file (`str`): file path to a CHANGELOG.md file
        - data_file (`str`): file path to a CHANGELOG.(yaml|json) file
        this is where the output will be written to

        **Keyword Arguments**

        - print (`bool=False`): if True print the generated changelog
        to stdout instead of writing to a file
        """

        changelog = self.md_to_dict(md_file)
        codec = os.path.splitext(data_file)[1][1:]
        codec = munge.get_codec(codec)
        self.log.info(f"Generating {data_file}")

        if kwargs.get("print"):
            print(codec().dumps(changelog))
            return

        with open(data_file, "w+") as fh:
            codec().dump(changelog, fh)

    def datafile_to_md(self, changelog_filepath):
        """
        Will attempt to generate md formatted changelog
        string from changelog data file

        We are using munge so any codec that munge supports
        can be used (default=yaml)

        **Arguments**

        - changelog_filepath (`str`): filepath to your CHANGELOG.yaml file

        **Returns**

        `str`: md formatted changelog
        """

        data = self.load(changelog_filepath)

        out = ["# Changelog"]

        releases = [
            {"version": version.capitalize(), "changes": changes}
            for version, changes in list(data.items())
        ]

        releases = natsorted(releases, key=lambda i: i.get("version"), reverse=True)

        for release in releases:
            out.extend(["", "", "## {version}".format(**release)])
            sections = {}
            for change_type, items in list(release.get("changes", {}).items()):
                if len(items):
                    sections[change_type] = [f"- {item}" for item in items]

            for change_type in CHANGELOG_SECTIONS:
                if change_type in sections:
                    out.append(f"### {change_type.capitalize()}")
                    out.extend(sections[change_type])

        return "\n".join(out)

    def md_to_dict(self, changelog_filepath):
        """
        will attempt to generate a dict from an
        existing CHANGELOG.md file

        **Arguments**

        - changelog_filepath (`str`): filepath to the CHANGELOG.md
        file

        **Returns**

        changelog `dict`
        """

        with open(changelog_filepath) as fh:
            changelog_md = fh.readlines()

        version_regex = r"##\D+([\d\.]+|unreleased).?"
        change_title_regex = "### (.+)"
        change_regex = "- (.+)"

        changelog = {}
        version_container = None
        change_list = None

        for line in changelog_md:
            match_version = re.match(version_regex, line, re.IGNORECASE)
            match_title = re.match(change_title_regex, line, re.IGNORECASE)
            match_change = re.match(change_regex, line, re.IGNORECASE)

            if match_version:
                version_container = changelog[match_version.group(1)] = {}
                continue
            elif match_title:
                change_list = version_container[match_title.group(1).lower()] = []
                continue
            elif match_change:
                change_list.append(match_change.group(1))
                continue

        return self.sort_changelog(changelog)

    def version_exists(self, data_file, version):
        """
        Checks if the specified release exists in the changelog

        **Arguments**

        - data_file (`str`): file path to a CHANGELOG.(yaml|json) file
        - version (`str`)

        **Returns**

        `True` if release exists, `False` if not
        """

        data = self.load(data_file)
        return data and version in data

    def validate(self, data_file, version):
        """
        Checks if the specified release version exists in the changelog
        and will raise a `ChangelogVersionMissing` Exception when it
        does not

        **Arguments**

        - data_file (`str`): file path to a CHANGELOG.(yaml|json) file
        - version (`str`)
        """

        if not self.version_exists(data_file, version):
            raise ChangelogVersionMissing(data_file, version)
