#!/usr/bin/env python3
"""Check that the build backend constraint actually bound the build.

`build-system.requires` names hatchling with no version, and build requirements
resolve outside `uv.lock`, so the only thing holding the backend still is the
`[tool.uv] build-constraint-dependencies` pin in pyproject.toml. A constraint
that silently failed to apply would look exactly like no constraint at all, and
the drift that killed the second v2.0.0 tag (#44) would be back: a newer
hatchling emits a newer Metadata-Version, and the publish action's twine
rejects the wheel after trusted publishing has already authenticated.

So this does not trust the constraint — it asks the wheel who built it. Run it
after `uv build`, from the repository root.
"""

import re
import sys
import zipfile
from pathlib import Path

# tomllib is 3.11+; ctl supports 3.10, and tomlkit is already a dev dependency.
import tomlkit

REPO = Path(__file__).resolve().parent.parent

# hatchling writes its own line into .dist-info/WHEEL:
#     Generator: hatchling 1.32.0
GENERATOR = re.compile(r"^Generator:\s*hatchling\s+(?P<version>\S+)\s*$", re.M)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def constrained_hatchling() -> str:
    """The hatchling version pyproject.toml constrains the build to."""
    pyproject = tomlkit.parse((REPO / "pyproject.toml").read_text())
    constraints = (
        pyproject.get("tool", {}).get("uv", {}).get("build-constraint-dependencies", [])
    )
    pins = [
        str(c) for c in constraints if str(c).replace(" ", "").startswith("hatchling==")
    ]
    if not pins:
        fail(
            "pyproject.toml [tool.uv] build-constraint-dependencies does not pin "
            "hatchling with `==`. build-system.requires is unpinned, so without "
            "that pin the backend — and the metadata version we publish — floats."
        )
    return pins[0].replace(" ", "").split("==", 1)[1]


def built_with(wheel: Path) -> str:
    """The hatchling version that actually produced the wheel, per the wheel."""
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/WHEEL")]
        if len(names) != 1:
            fail(f"{wheel.name} does not contain exactly one .dist-info/WHEEL")
        found = GENERATOR.search(archive.read(names[0]).decode())
    if not found:
        fail(f"{wheel.name}'s WHEEL has no `Generator: hatchling <version>` line")
    return found.group("version")


def main() -> int:
    wheels = sorted((REPO / "dist").glob("*.whl"))
    if not wheels:
        fail("no wheel in dist/ — run `uv build` first")

    want = constrained_hatchling()
    for wheel in wheels:
        got = built_with(wheel)
        if got != want:
            fail(
                f"{wheel.name} was built by hatchling {got}, but pyproject.toml "
                f"constrains the build to {want}. The build constraint did not "
                "bind — the backend, and the metadata version, are floating."
            )
        print(f"{wheel.name}: built by the constrained hatchling {got}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
