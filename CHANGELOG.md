# Changelog


## Unreleased


## 2.0.0
### Added
- GitManager.fetch() cooldown to avoid redundant remote fetches, controlled by GIT_FETCH_COOLDOWN env var (default 30s)
- py.typed marker file for type checking support
- python 3.13 and 3.14 support
- changelog.d fragment support - unreleased changes can be written as fragment files in changelog.d/ and are collected into the release section by `ctl changelog release`, eliminating CHANGELOG merge conflicts
- `ctl changelog check` operation - checks that the current branch touches the changelog (fragments or data file) for use as a CI gate
- `ctl version set <version>` writes a version to the repository's version files with no git operations at all - no pull, commit, tag or push. This is the operation to use when the release is driven outside of ctl, where a commit or tag from ctl would bypass the caller's own gates
- `ctl version bump --no-git` performs a semantic bump the same way, writing the version files without any git operations
- ctl releases are published to PyPI by a GitHub Actions workflow triggered by a `v*` tag, using trusted publishing (OIDC), so the release path holds no PyPI API token
- each release also gets a GitHub Release with the sdist and wheel attached
- GitLab CI pipeline runs ruff and the test suite on every branch push and merge request, gating the tree before it is tagged
### Fixed
- ephemeral git context push rejection when concurrent processes push to the same branch - pull before push to integrate remote changes
- replaced deprecated pkg_resources with importlib.metadata
- git manager tests no longer leak ambient GITHUB_TOKEN/GITLAB_TOKEN from the environment; env-over-config token precedence is now covered by an explicit test
- ephemeral git context finalize no longer fails on the first push of a new branch (pull-before-push is skipped when the branch has no remote ref yet)
- GitManager.sync() bypasses the fetch cooldown so it always integrates the current remote state before merging and pushing
- `ctl semver2 tag/bump --no-git` was not recognized by the CLI (the flag only reached the `release` operation due to argparse parent timing)
- docs deploy no longer fails on the pymdgen markdown extension (added to the docs extra)
- `--prefix` and `--no-git-tag` no longer parse on the `version` plugin, which never implemented them (they are semver2-only and were silently ignored)
- remote branch lookups now match branch names containing slashes (e.g. `feature/x`)
- git plugin clone() no longer silently skips a not-yet-cloned checkout_path nested inside an enclosing repository (a missing or empty checkout_path is not considered cloned; skipping due to a content-bearing subdirectory now warns loudly)
- Log gained a `warning` level; the git plugin retargeting warning previously crashed with AttributeError
- `ctl changelog release` no longer prints a stray `LOADING <path>` debug line
- a failing operation now exits non-zero - previously any error other than a `PluginOperationStopped` (a validation error, a permission denial, an unexpected exception) was logged and then exited 0, which silently green-lit calling scripts and CI gates
- the residual `unreleased` changelog section is now matched case insensitively. A changelog using `unreleased:` rather than `Unreleased:` had its residual entries silently dropped from the release in fragment mode, and was refused with "No items exist in unreleased to be moved" in legacy mode. The changelog's own casing is preserved when the section is reset, and a changelog carrying both spellings is now refused rather than having one of them guessed at
- version operations read the current version from `pyproject.toml` when the repository has no `Ctl/VERSION` file, instead of computing a semantic bump from `0.0.0`. A repository that keeps its version only in `pyproject.toml` is now a valid target without `--init`, which would otherwise create an untracked `Ctl/VERSION` file
- `ctl semver2 bump` and `ctl semver2 release` read the current version the same way. Without this they derived from `0.0.0` on a repository whose version lives only in `pyproject.toml`, so a repository at `1.4.2` had `0.1.0` written, committed and tagged, and the regression was reported as success
- version files that do not already exist are no longer created unless `--init` is passed, and an operation that would write no version file at all now fails instead of reporting success having changed nothing
- the `--init` flag now takes effect - it parsed and was then ignored, so the flag the "Ctl/VERSION file does not exist" error recommends did not actually work
- `ctl changelog release` no longer deletes the comments in a CHANGELOG.yaml or reformats the whole file. It used to load the changelog, mutate the parsed structure and dump all of it back out, which drops every comment (YAML round-trips do not carry them) and rewrote list indentation, string wrapping and non-ASCII escaping across sections the release never touched. Only the lines the release actually changes are rewritten now: the residual section is reset in place and the new release block is inserted at its sorted position
- a comment inside the residual `Unreleased` section annotates entries that move into the release and cannot come along - it is now reported by file and line as it is dropped instead of disappearing silently
- the local gate and CI now run the same uv.lock-resolved ruff - pre-commit uses a local `uv run ruff` hook instead of a separately pinned mirror, so the two can no longer drift (#43)
- publishing a release to PyPI no longer fails on the metadata version of the built distributions
### Changed
- migrated from Poetry to modern pyproject.toml with hatchling build backend
- migrated from black/isort/flake8/pyupgrade to ruff for linting and formatting
- updated CI workflows to use uv instead of poetry/tox
- migrated the docs deploy workflow (gh-pages) from poetry to uv
- updated pre-commit hooks to use ruff and mypy
- upgraded all dependencies to latest versions
- git plugin warns loudly when git operations retarget an enclosing repository because checkout_path is not itself a repository root
- a release no longer re-sorts the whole changelog data file. A changelog whose blocks are out of order keeps the order its author gave it, and only the newly written block is placed by sort order - re-sorting rewrote blocks the release had nothing to do with. The generated CHANGELOG.md is sorted either way, and a CHANGELOG.json data file is still written whole
- BREAKING: when no GitLab instance is named by the operator, the instance url is now derived from the repository's own clone origin, so an ambient token can only ever reach the host the repository was cloned from. Derivation handles https, ssh and scp style (`git@host:path`) origins, and fails closed - no origin, disagreeing remotes, an origin that names no host, or a github host produces no service at all rather than a guess, with a warning naming what was inspected. The instance url and where it came from are logged at INFO so it is visible on a normal run which host received the token
- BREAKING: because a GitLab service is now created in cases where none was created before, a caller that has both `GITHUB_TOKEN` and `GITLAB_TOKEN` set, no `GITLAB_URL`, and no `default_service`, and that operates a repository whose origin is not a github host, will now get `ValueError("Multiple services available, please specify one as default via default_service")` from `GitManager.service` where it previously got the github service. Set `default_service`
- BREAKING: `GITLAB_URL` (and `--gitlab-url`) must be a full url with a scheme, e.g. `https://gitlab.example.com`. A value without one previously produced a service pointed at the malformed url `"://"`; it now raises a `ValueError` naming the value and the expected form
- ctl's build backend is pinned, so the metadata version of published ctl distributions changes only deliberately
### Deprecated
- `GitManager(repository_config_filename=...)` is accepted but ignored, and logs a notice when passed. Set `GITLAB_URL` / `GITLAB_TOKEN` / `GITHUB_TOKEN` in the environment, or pass `repository_config`, instead
### Removed
- python 3.8 and 3.9 support (EOL)
- poetry.lock (replaced with uv.lock)
- tox (local multi-version testing is `uv run --python 3.X pytest`)
- BREAKING: the repository config file (`repository_config_filename`) is no longer read. ctl does not take its own configuration out of the content of the repository it operates on - a repository must not be able to name the host a credential is sent to, nor supply the credential itself. `gitlab_url`, `gitlab_token` and `github_token` now come only from the environment (`GITLAB_URL`, `GITLAB_TOKEN`, `GITHUB_TOKEN`), from the command line (`--gitlab-url`) or from a caller supplied `repository_config`. Anyone who relied on an operated repository declaring a *different* GitLab instance than the one it was cloned from loses that, deliberately. This release must be a major version bump
### Security
- #30: ctl no longer sends the operator's GitLab credential to a host named by the repository it operates on. A config file committed to an operated repository could set `gitlab_url` and omit `gitlab_token`, and ctl would then authenticate to that host with the operator's real `GITLAB_TOKEN` - a confused deputy that exfiltrated a broadly scoped credential to whoever could land a commit on the default branch
- #35: ctl no longer accepts a `github_token` from repository content. It was previously used verbatim, with no environment precedence at all, so an operated repository could choose the GitHub identity ctl acted as
- urls are stripped of any embedded credentials before they are logged or put in an error message, and `RepositoryConfig`'s token fields no longer render in its repr


## 1.2.0
### Added
- configless execution
- new git plugin with support for gitlab, github
- new git with support for ephemeral repos
- archive branch
- py3.12
### Fixed
- fetch remote before branch remake
- throw if remotes don't match url (#69)
### Changed
- git service init changes


## 1.1.0
### Added
- `pypi release` support for poetry based projects (#27)
- `version tag/bump` support for poetry based projects (#27)
- `semver2` plugin (#20)`
- `remote` config attribute for repository plugins
- python 3.10 support (#43)
- python 3.11 support (#43)
### Fixed
- version plugins no longer mangle pyproject.toml formatting (#35)
- git plugin will now always set remote and branch for pull and push
- semver2 plugin always trying to tag a prerelease during bump action (#39)
- changelog version sorting issues during generate and release (#38)
- template plugin will now copy file permissions (#37)
- reposiotry plugins: when specifying a branch that does not exist locally or remotely the branch will be created (#47)
### Changed
- default cache dir location (#29)
### Removed
- version plugin: automatic creation of dev tags (#46)
- python 3.6 support (#43)
- python 3.7 support


## 1.0.0
### Added
- python 3.7 support (#15)
- python 3.8 support (#19)
- python 3.9 support (#19)
### Fixed
- version plugin: bump needs to do a pull before changelog validation (#14)
- venv plugin: copy: remove *.pyc files after copying a venv (#17)
- venv plugin: sync_setup --freeze option added
- venv plugin: sync_setup now also generates dev packages into extra_requires
- issue in setup.py with download_url and url (#18)
### Removed
- venv plugin is no longer working (due to poetry not allowing bash scripts and it no longer being used)
- python2.7 support (#21)
- python3.4 support (#21)
- python3.5 support (#21)


## 0.3.1
### Changed
- switch to confu package, away from cfu (same version and codebase, different package name)
- update test requirements for pyaml according to python version


## 0.3.0
### Added
- `venv` plugin: `sync_setup` operation added
- `confuargparserouter`: better way to route confu generated cli parameters to sub parsers
- `changelog` plugin`
- `version` plugin: changelog validation
### Fixed
- fix #13: plugin.expose_vars: don't raise on io error
- fix #5: fix config error handling for errors that happen outside of plugin config
- fix #6: fix semantic version bumping when the current version is truncated


## 0.2.0
### Changed
- pypi plugin: config `repository` changed to `pypi_repository` (#2)
- pypi plugin: config `target` changed to `repository` (#2)
