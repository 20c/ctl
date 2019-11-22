"""
Plugin that allows you manage CHANGELOG.(md|yaml|json) files
"""

import os.path
import re
import argparse
from collections import OrderedDict

import munge
import confu.schema

import ctl
from ctl.auth import expose
from ctl.plugins import ExecutablePlugin
from ctl.docs import pymdgen_confu_types

CHANGELOG_SECTIONS = ("added", "fixed", "changed", "deprecated", "removed", "security")


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

        super(ChangelogVersionMissing, self).__init__(
            "Version {} does not exist in changelog located at {}".format(
                version, data_file
            )
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

        op_generate_parser = sub.add_parser(
            "generate", help="generate CHANGELOG.md", parents=[generate_parser]
        )

        # operation `generate_datafile`

        op_generate_datafile_parser = sub.add_parser(
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

    def load(self, changelog_filepath):
        data = munge.load_datafile(changelog_filepath)
        return data

    def execute(self, **kwargs):
        super(ChangeLogPlugin, self).execute(**kwargs)

        if "data_file" in kwargs:
            kwargs["data_file"] = os.path.abspath(kwargs["data_file"])

        if "md_file" in kwargs:
            kwargs["md_file"] = os.path.abspath(kwargs["md_file"])

        fn = self.get_op(kwargs.get("op"))
        fn(**kwargs)

    @expose("ctl.{plugin_name}.release")
    def release(self, version, data_file, **kwargs):
        """
        Adds the specified release to the changelog.

        This will validate and move all items under "unreleased"
        to a new section for the specified release version

        **Arguments**

        - version (`str`): version mame (eg. tag name)
        - data_file (`str`): file path to a CHANGELOG.(yaml|json) file
        """
        changelog = self.load(data_file)
        if version in changelog:
            raise ValueError(
                "Release {} already exists in {}".format(version, data_file)
            )

        release_section = {}

        for change_type, changes in changelog.get("unreleased", {}).items():
            if changes:
                release_section[change_type] = [change for change in changes]

        if not release_section:
            raise ValueError("No items exist in unreleased to be moved")

        changelog[version] = release_section
        changelog["unreleased"] = dict(
            [(section, []) for section in CHANGELOG_SECTIONS]
        )

        ext = os.path.splitext(data_file)[1][1:]
        codec = munge.get_codec(ext)

        with open(data_file, "w+") as fh:
            codec().dump(changelog, fh)

        self.log.info("Updated {}".format(data_file))

        self.generate(self.get_config("md_file"), data_file)

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
        self.log.info("Generating {}".format(md_file))

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
            raise ValueError("File already exists: {}".format(data_file))

        changelog = {
            "unreleased": dict([(section, []) for section in CHANGELOG_SECTIONS])
        }

        codec = os.path.splitext(data_file)[1][1:]
        codec = munge.get_codec(codec)
        self.log.info("Generating {}".format(data_file))
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
        self.log.info("Generating {}".format(data_file))

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
            {"version": version, "changes": changes}
            for version, changes in data.items()
        ]

        releases = sorted(releases, key=lambda i: i.get("version"), reverse=True)

        for release in releases:
            out.extend(["","", "## {version}".format(**release)])
            sections = {}
            for change_type, items in release.get("changes", {}).items():
                if len(items):
                    sections[change_type] = ["- {}".format(item) for item in items]

            for change_type in CHANGELOG_SECTIONS:
                if change_type in sections:
                    out.append("### {}".format(change_type))
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

        with open(changelog_filepath, "r") as fh:
            changelog_md = fh.readlines()

        version_regex = "##\D+([\d\.]+|unreleased).?"
        change_title_regex = "### (.+)"
        change_regex = "- (.+)"

        changelog = {}
        version_container = None
        change_list = None

        for line in changelog_md:
            line = line.lower()
            match_version = re.match(version_regex, line)
            match_title = re.match(change_title_regex, line)
            match_change = re.match(change_regex, line)

            if match_version:
                version_container = changelog[match_version.group(1)] = {}
                continue
            elif match_title:
                change_list = version_container[match_title.group(1)] = []
                continue
            elif match_change:
                change_list.append(match_change.group(1))
                continue

        return changelog

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
