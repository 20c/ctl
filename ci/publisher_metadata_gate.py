#!/usr/bin/env python3
"""Check ./dist with the publish action's own twine, at the pinned action ref.

#44 died because the pre-tag gate and the publisher disagreed about which
`Metadata-Version` values are acceptable: the backend emitted 2.5, the pinned
publish action's twine understood 2.4, and nothing compared them until trusted
publishing had already authenticated — on a tag, which cannot be re-run.

The obvious fix is to run `twine check` in CI. The trap is that "a twine" is not
"the publisher's twine": if ours accepts more metadata versions than the
action's, the gate goes green and the tag still dies. Mirroring the action's
versions into our own dependencies would work, but only for as long as someone
keeps the mirror honest.

So nothing is mirrored. This builds a throwaway environment from the action's
own `requirements/runtime.txt`, fetched at the exact commit `release.yml` pins
the action to, and checks the distributions with that. There is one source for
the publisher's tooling — the action pin — and the gate cannot drift from the
publisher because it is not a copy of it.

Run it after `uv build`, from the repository root. Needs `uv` and network.
"""

import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PUBLISHER_ACTION = "pypa/gh-action-pypi-publish"
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "release.yml"
RUNTIME_REQUIREMENTS = (
    f"https://raw.githubusercontent.com/{PUBLISHER_ACTION}/{{sha}}"
    "/requirements/runtime.txt"
)

ACTION_PIN = re.compile(rf"{re.escape(PUBLISHER_ACTION)}@(?P<ref>\S+)")
SHA = re.compile(r"\A[0-9a-f]{40}\Z")


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def publisher_sha() -> str:
    """The publish action's pinned commit, read from the release workflow."""
    if not RELEASE_WORKFLOW.is_file():
        fail(f"{RELEASE_WORKFLOW} does not exist")
    refs = set(ACTION_PIN.findall(RELEASE_WORKFLOW.read_text()))
    if not refs:
        fail(f"no `uses: {PUBLISHER_ACTION}@...` found in {RELEASE_WORKFLOW}")
    if len(refs) > 1:
        fail(f"{PUBLISHER_ACTION} is pinned to more than one ref: {sorted(refs)}")
    ref = refs.pop()
    if not SHA.match(ref):
        fail(
            f"{PUBLISHER_ACTION} is pinned to {ref!r}, not a 40-character commit "
            "SHA. What a mutable ref installs can change after this gate ran."
        )
    return ref


def fetch_requirements(sha: str, into: Path) -> Path:
    url = RUNTIME_REQUIREMENTS.format(sha=sha)
    print(f"fetching the publisher's requirements: {url}")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        # 4xx is an answer: that commit does not serve this file, so the SHA in
        # release.yml is wrong — and it would be wrong for the publish step too.
        fail(
            f"{url} returned {exc.code}. Check the SHA pinned in "
            f"{RELEASE_WORKFLOW.name} is a real commit of the publish action."
        )
    except (urllib.error.URLError, OSError) as exc:
        fail(
            f"could not reach {url}: {exc}. This gate checks with the publisher's "
            "own tooling, so it cannot pass without fetching it."
        )
    path = into / "runtime.txt"
    path.write_bytes(body)
    return path


def publisher_environment(requirements: Path, into: Path) -> Path:
    """A venv holding exactly what the action installs, and nothing of ours."""
    env = dict(os.environ)
    # Inherited from `uv run`; it would point uv back at the project venv.
    env.pop("VIRTUAL_ENV", None)
    venv = into / "publisher"
    # Built on the interpreter this job already runs, so a Python too old for
    # the publisher's requirements fails here rather than somewhere subtler.
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(venv)], check=True, env=env
    )
    subprocess.run(
        ["uv", "pip", "install", "--python", str(venv), "-r", str(requirements)],
        check=True,
        env=env,
    )
    return venv


def main() -> int:
    distributions = sorted(str(p) for p in (REPO / "dist").glob("ctl-*"))
    if not distributions:
        fail("nothing in dist/ — run `uv build` first")

    sha = publisher_sha()
    print(f"{PUBLISHER_ACTION} is pinned at {sha}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        venv = publisher_environment(fetch_requirements(sha, tmp), tmp)
        versions = subprocess.run(
            [
                str(venv / "bin" / "python"),
                "-c",
                "import importlib.metadata as m;"
                "print('twine', m.version('twine'),"
                "'/ packaging', m.version('packaging'))",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        print(f"checking with the publisher's {versions}")
        checked = subprocess.run([str(venv / "bin" / "twine"), "check", *distributions])

    if checked.returncode != 0:
        fail(
            "the publish action's own twine rejects these distributions. It "
            "would reject them on the tag too, after trusted publishing has "
            "authenticated. Reconcile the build backend constraint and the "
            "publish action pin before tagging."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
