"""The publish action pin has to be resolvable, because the gate resolves it.

`ci/publisher_metadata_gate.py` checks our distributions with the publish
action's own twine, built from `requirements/runtime.txt` at the commit
`release.yml` pins. That makes "the gate agrees with the publisher" true by
construction rather than by maintenance — there is one source for the
publisher's tooling and no copy of it to keep honest.

What construction cannot cover is the pin itself being unresolvable, so that is
what is left to test: the ref must be an immutable commit, it must serve the
requirements, and — because the action runs a container image tagged with that
ref rather than the checked-out tree — an image must exist for it. A commit can
be real, serve a real `runtime.txt`, and still have no image behind it, in
which case the publish step dies after the tag is cut.

The fetches need the network and skip without it; a 4xx is not "no network", it
is upstream saying the pin is wrong, and that fails.
"""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "release.yml"

PUBLISHER_ACTION = "pypa/gh-action-pypi-publish"
REQUIREMENTS = (
    f"https://raw.githubusercontent.com/{PUBLISHER_ACTION}/{{sha}}"
    "/requirements/runtime.txt"
)
GHCR_TOKEN = (
    f"https://ghcr.io/token?scope=repository:{PUBLISHER_ACTION}:pull&service=ghcr.io"
)
GHCR_MANIFEST = f"https://ghcr.io/v2/{PUBLISHER_ACTION}/manifests/{{sha}}"

ACTION_PIN = re.compile(rf"{re.escape(PUBLISHER_ACTION)}@(?P<ref>\S+)")
SHA = re.compile(r"\A[0-9a-f]{40}\Z")


def pinned_action_ref() -> str:
    refs = set(ACTION_PIN.findall(RELEASE_WORKFLOW.read_text()))
    assert len(refs) == 1, (
        f"{PUBLISHER_ACTION} should be pinned exactly once in "
        f"{RELEASE_WORKFLOW.name}, found {sorted(refs)}"
    )
    return refs.pop()


def fetch(url: str, headers: dict = None) -> bytes:
    """Fetch `url`, distinguishing "upstream says no" from "no upstream".

    A 4xx is an answer: what we asked for is not there, which here always means
    the pin is wrong. Skipping on it would hide the one thing these tests exist
    to catch. Anything else — no network, DNS, a 5xx, an API that changed shape
    — is not evidence about the pin, so it skips rather than failing someone's
    pipeline over GitHub having a bad day.
    """
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers or {}), timeout=30
        ) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            pytest.fail(
                f"{url} returned {exc.code}. The ref pinned in "
                f"{RELEASE_WORKFLOW.name} does not serve this — check it is a "
                "real commit of the publish action."
            )
        pytest.skip(f"{url} returned {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"cannot reach {url}: {exc}")


def test_publish_action_is_pinned_to_a_commit():
    """A tag or branch can move to different requirements after the gate ran."""
    ref = pinned_action_ref()
    assert SHA.match(ref), (
        f"{PUBLISHER_ACTION} is pinned to {ref!r}, not a 40-character commit "
        "SHA. The gate resolves this ref; a mutable one makes what it checked "
        "and what publishes two different things."
    )


def test_the_pinned_commit_serves_its_requirements():
    """The gate builds the publisher's environment from this file."""
    body = fetch(REQUIREMENTS.format(sha=pinned_action_ref()))
    assert b"twine==" in body, (
        "the publish action's requirements at the pinned commit name no twine; "
        "ci/publisher_metadata_gate.py would build an environment that cannot "
        "check anything."
    )


def test_the_pinned_commit_has_a_published_image():
    """The action runs a container tagged with the ref, not the checked-out tree.

    `action.yml` is `using: composite`; it generates a Docker action pointing at
    ghcr.io/<repo>:<github.action_ref>, and that image's dependencies were
    installed when it was built, pinned by the same commit's
    `requirements/runtime.txt` — which is why the gate checking against that
    file describes what actually runs. But the image is selected by tag, so a
    commit with no published image passes every other check here and then fails
    the publish step, after the tag is cut.
    """
    ref = pinned_action_ref()
    try:
        token = json.loads(fetch(GHCR_TOKEN))["token"]
    except (KeyError, ValueError) as exc:
        pytest.skip(f"ghcr token endpoint returned something unexpected: {exc}")

    # Reached only if the manifest exists; fetch() fails the test on a 404.
    fetch(
        GHCR_MANIFEST.format(sha=ref),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.oci.image.index.v1+json,"
            "application/vnd.docker.distribution.manifest.list.v2+json,"
            "application/vnd.docker.distribution.manifest.v2+json",
        },
    )
