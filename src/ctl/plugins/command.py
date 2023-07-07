"""
A plugin that allows you to run one or several shell commands
"""


import os
import subprocess
import sys

import confu.schema

import ctl
import ctl.config
from ctl.auth import expose
from ctl.docs import pymdgen_confu_types


class CwdContext:
    """
    A context manager that allows you to temporarily
    execute commands in a different working directory
    """

    def __init__(self, plugin, cwd):
        """
        **Arguments**

        - plugin (`PluginBase`): plugin instance
        - cwd (`str`): set current working directory to this path
        """
        self.cwd = os.path.expanduser(cwd)
        self.plugin = plugin

    def __enter__(self):
        """
        **Returns**

        new working directory (`str`)
        """
        if not os.path.isdir(self.cwd):
            raise ValueError("{} is not a directory".formath(self.cwd))

        self.old_cwd = self.plugin.cwd
        self.plugin.cwd = self.cwd
        return self.cwd

    def __exit__(self, *args):
        self.plugin.cwd = self.old_cwd


@pymdgen_confu_types()
class CommandPluginConfig(confu.schema.Schema):
    """
    configuration schema for command plugin
    """

    command = confu.schema.List(
        item=confu.schema.Str("command.item"), help="shell commands to run", cli=False
    )
    arguments = confu.schema.List(
        item=ctl.config.ArgparseSchema(), cli=False, help="arbirtrary cli arguments"
    )
    env = confu.schema.Dict(
        item=confu.schema.Str(), default={}, cli=False, help="environment variables"
    )
    shell = confu.schema.Bool(
        default=False, cli=False, help="run subprocess in shell mode"
    )
    working_dir = confu.schema.Directory(
        default=None,
        blank=True,
        help="set a working directory before " "running the commands",
    )


@ctl.plugin.register("command")
class CommandPlugin(ctl.plugins.ExecutablePlugin):
    """
    runs a command

    # Instanced Attributes

    - env (`dict`): shell environment variables that will be set
      during command execution
    - stdout: stdout target
    - stdin: stdin target
    """

    class ConfigSchema(ctl.plugins.PluginBase.ConfigSchema):
        config = CommandPluginConfig("config")

    description = "run a command"

    @classmethod
    def add_arguments(cls, parser, plugin_config, confu_cli_args):
        ctl.config.ArgparseSchema().add_many_to_parser(
            parser, plugin_config.get("arguments")
        )

    def prepare(self, **kwargs):
        """
        prepares the command environment

        cwd, shell env, stdout / stdin are all set up
        through this

        this is called automatically during the `ExecutablePlugin.execute`
        call

        *overrides `ExecutablePlugin.prepare`*
        """

        self.env = os.environ.copy()
        self.stdout = sys.stdout
        self.stderr = sys.stderr

        self.env.update(**(self.get_config("env") or {}))
        self.cwd = self.get_config("working_dir")
        self.shell = self.get_config("shell")

    # namespace will be built using the name of the
    # plugin instance
    #
    # required permissions will be obtained from `permissions` key
    # in the plugin's config, and default to `r` if not specified
    @expose("ctl.{plugin_name}")
    def execute(self, **kwargs):
        """
        execute the command(s) specified in the plugin
        config `command` list

        *overrides and calls `ExecutablePlugin.execute`*
        """

        super().execute(**kwargs)
        command = self.get_config("command")
        self._run_commands(command, **kwargs)

    def _run_commands(self, command, **kwargs):
        """
        execute a list of commands

        this is called automatically during `execute`

        **Argument(s)**

        - command (`list`): list of shell commands

        **Returns**

        - False if command failed with error
        """

        for cmd in command:
            cmd = self.render_tmpl(cmd, kwargs)
            self.log.debug(f"running command: {cmd}")
            rc = self._exec(cmd)
            self.log.debug(f"done with {cmd}, returned {rc}")
            if rc:
                self.log.error(f"command {cmd} failed with {rc}")
                return False

        # TODO: should return True here?

    def _exec(self, command):
        """
        execute a single command

        this is called automatically during `_run_commands`

        **Argument(s)**

        - command (`str`)

        **Returns**

        - int: process return code
        """

        popen_kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": self.shell,
            "env": self.env,
            "cwd": self.cwd,
        }

        proc = subprocess.Popen(command, **popen_kwargs)
        stdout = []
        stderr = []

        with proc.stdout:
            for line in iter(proc.stdout.readline, b""):
                line = line.decode("utf-8")
                stdout.append(line)

        with proc.stderr:
            for line in iter(proc.stderr.readline, b""):
                line = line.decode("utf-8")
                stderr.append(line)

        for line in stdout:
            self.stdout.write(f"{line}")

        for line in stderr:
            self.stderr.write(f"{line}")

        return proc.returncode

    def cwd_ctx(self, cwd):
        """
        Returns a context manager that allows you to execute
        commands in a new working directory

        **Arguments**

        - cwd `str`: path to directory

        **Returns**

        `CwdContext` context
        """

        return CwdContext(plugin=self, cwd=cwd)
