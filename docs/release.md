# Releasing ctl

A release is a `v*` tag on the GitHub mirror (`github.com/20c/ctl`).
`.github/workflows/release.yml` runs on that tag:

```
checks  →  build  →  publish-pypi  →  github-release
```

- **checks** — `tests.yml` on the tagged commit (lint + the Python matrix).
  A tag on a red commit fails here before anything is built. Coverage upload
  is skipped on tags so a Codecov outage cannot block a publish.
- **build** — verifies the tag matches `project.version` in `pyproject.toml`
  (until the version is derived from the tag, #39), then `uv build` into the
  `dist` artifact. Holds no token.
- **publish-pypi** — `environment: pypi`; downloads `dist`, publishes with
  PyPI trusted publishing (OIDC) and PEP 740 attestations. No checkout, no
  repository code, no `contents` scope. **Pauses for the environment's
  required reviewer before any step runs.**
- **github-release** — after PyPI accepts: creates the GitHub Release with the
  same sdist and wheel attached.

The tag is cut by lmer's release flow (version + changelog roll on the GitLab
side, a merged release MR, then the signed tag pushed to GitHub and then
GitLab). This page covers what the workflow needs from the host and what to do
when a run does not finish.

## Preconditions — host-side, the operator's

These cannot live in the repository. Each one is a control, not hygiene.

1. **PyPI trusted publisher for `ctl` must pin `environment: pypi`.**
   Register it as owner `20c`, repository `ctl`, workflow `release.yml`,
   environment **`pypi`** — the environment field is not optional here.
   This is the load-bearing half of the publish boundary: the tag's own tree
   supplies `release.yml`, so a workflow that omitted the `environment:`
   block would otherwise publish with no approval prompt. With the publisher
   pinned to the environment, PyPI rejects any OIDC token that does not
   carry the `pypi` environment claim, and the only way to get that claim is
   to declare the environment — which triggers its required reviewer.
   **Without this pin, the human gate does not exist.**
2. **GitHub environment `pypi`** with a required reviewer and a deployment
   tag-pattern policy of `v*`. Every release pauses here until approved;
   the approval prompt shows a ref, not a diff.
3. **Tag ruleset on `v*`** (restrict create/update/delete) with the release
   bot as the only bypass. This is what decides *who can start* a release.
4. **GitLab protected tags `v*`** on the canonical repository — leg 2 pushes
   the tag there last, after GitHub is green.
5. **Release credentials** provisioned to release sessions only: the
   fine-grained PAT for the mirror (`contents:write` + `workflows:write`) and
   the SSH signing key. The tag is signed; nothing in CI verifies the
   signature — items 1–3 are the enforced controls.

## When a run does not finish — the partial-release runbook

Read this before the run, not during it. The workflow deliberately does not
set `skip-existing`, so PyPI refusing a duplicate upload is a hard failure.
That makes one recovery path right and two wrong.

### `publish-pypi` succeeded, `github-release` failed

The package is on PyPI; there is no GitHub Release yet.

1. Open the failed run in GitHub Actions.
2. Choose **Re-run failed jobs** — *not* "Re-run all jobs".
   Only `github-release` re-runs; it downloads the `dist` artifact from the
   original run (artifacts live 90 days) and `action-gh-release` is
   idempotent on an existing Release, so this is safe to repeat.
3. If the artifact has expired or the re-run is impossible, create the
   Release by hand: GitHub → Releases → Draft a new release → choose the
   existing tag → attach the sdist and wheel **downloaded from PyPI**
   (`pip download ctl==X.Y.Z --no-deps --no-binary :all:` for the sdist,
   `--only-binary :all:` for the wheel) so the Release carries the exact
   published bytes.

**Do not** "Re-run all jobs": `publish-pypi` re-runs, PyPI rejects the
duplicate, and `github-release` never reaches its turn.
**Do not** delete and re-push the tag: same rejection, plus the tag would
no longer match the signed tag the release run recorded.

### `publish-pypi` failed partway — one file on PyPI, one missing

Twine uploads the sdist and wheel one at a time; a network failure between
them leaves the version on PyPI with one file. Re-running `publish-pypi`
hits the duplicate refusal on the file that did land.

1. Download the `dist` artifact from the failed run (Actions → the run →
   Artifacts → `dist`).
2. Upload the missing file only, as a PyPI project owner with a scoped
   token: `twine upload dist/<missing-file>`. The version is already on
   PyPI; this completes it rather than republishing it.
3. Then **Re-run failed jobs** is still wrong (it would retry the publish).
   Create the GitHub Release by hand as in step 3 above, attaching both
   files from the artifact.

**Know what a hand-completed version looks like afterwards:** the file the
workflow uploaded carries a PEP 740 attestation; the file you upload from a
laptop does not and cannot — attestations are minted from the workflow's
OIDC identity, and `twine` on a personal token has no such identity. The
version ends up **one file attested, one unattested**, permanently (PyPI
does not accept an attestation after the fact, and the file cannot be
replaced). Every other ctl release is fully attested, so whoever notices the
asymmetry later will read it as a defect; if that matters, it is the
argument for the alternative below, which ends with every file attested.

If completing the version by hand is not acceptable, the alternative is a
new patch version: roll the changelog again and cut `vX.Y.(Z+1)`. The
partial version stays on PyPI (PyPI does not allow re-using a version);
yank it from the project page with a note pointing at the replacement.

### `checks` or `build` failed

Nothing has been published, so **re-running is free and safe** — it is the
first thing to try, and unlike the sections above there is no duplicate
upload to trip over. Use **Re-run failed jobs** for a flaky test or a
transient runner problem; the tag and the environment approval are
unaffected because `publish-pypi` never ran.

If the failure is real (the code is broken at the tag), fix on `main`
through the normal flow and cut the next version; a `v*` tag is never
re-pointed.

### Recording

Whatever path was taken, record it in the release run (the lmer run
directory for that release) so the next person can see what state the
version was left in.
