# ci/

Files here exist so a release cannot be killed by a version drift that no
merge request pipeline could see. Two tags died that way (#43, #44).

## `publisher_metadata_gate.py`

Checks the built distributions with the **publish action's own twine**, not
with ours. It reads the action SHA out of `.github/workflows/release.yml`,
fetches `requirements/runtime.txt` from `pypa/gh-action-pypi-publish` at that
commit, installs it into a throwaway environment, and runs `twine check` from
there.

The point is what it avoids. `twine check` decides whether a release
publishes, and the `Metadata-Version` values it accepts come from its
`packaging` rather than from twine itself — so a gate running any other pair
is predicting the publisher. Mirroring the action's versions into our own
dependencies would work too, but only while someone keeps the mirror honest.
Resolving them from the action pin at check time means there is one source and
nothing to keep in step: the gate cannot disagree with the publisher, because
it is not a copy of it.

Consequences worth knowing: it needs the network, and it hard-fails rather
than skips when the pinned commit does not serve that file, because that means
the pin is wrong and the publish step would fail on it too.

## `check_build_constraint.py`

Asserts the built wheel was produced by the hatchling version
`pyproject.toml` constrains the build to, by reading the `Generator:` line
the backend writes into `.dist-info/WHEEL`. A build constraint that silently
failed to apply looks exactly like no constraint at all.
