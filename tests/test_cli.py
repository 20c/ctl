import os
import subprocess

from util import CTL_CMD


def test_cli(config_dir):
    output = subprocess.check_output(
        CTL_CMD + ["ls", "--home", os.path.join(config_dir, "standard")]
    )

    output = f"{output}"
    assert output.find("[usage] ran command: `ls --home") > -1
