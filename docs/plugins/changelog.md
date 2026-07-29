## Changelog Plugin

Use this plugin to manage CHANGELOG.yaml and CHANGELOG.md files

### CHANGELOG.md

```md
{!examples/plugins/changelog/CHANGELOG.md!}
```

### CHANGELOG.yaml

```yaml
{!examples/plugins/changelog/CHANGELOG.yaml!}
```

### Config Example

```yaml
{!examples/plugins/changelog/Ctl/config.yaml!}
```

### Generate .yaml from .md

```sh
ctl changelog generate_datafile
```

### Generate .md from .yaml

```sh
ctl changelog generate
```

### Generate a fresh .yaml file

```sh
ctl changelog generate_clean
```

### Note new release

This will make a new section in the CHANGELOG.yaml file for the specified release version
and move all the items that exist in `unreleased` to it

This can only be done if a CHANGELOG.yaml file exists, CHANGELOG.md is not a valid target for this
operation

```sh
ctl changelog release 1.0.0
```

### Changelog fragments (changelog.d)

Instead of collecting unreleased changes in the `Unreleased` section of the
CHANGELOG.yaml file, each change can be noted in its own small YAML file in a
`changelog.d/` directory next to the changelog data file.

On `ctl changelog release <version>` all fragment files are collected into the
new release section and deleted afterwards.

Since two branches never touch the same fragment file this eliminates the
merge conflicts that come from every branch editing the same `Unreleased`
section.

Fragment mode activates automatically when the fragments directory exists -
repositories without a `changelog.d/` directory are completely unaffected.

The directory location can be changed through the `fragments_dir` config
attribute (default `changelog.d`) - a relative value is resolved against the
directory containing the changelog data file.

#### Fragment file format

A fragment file is a YAML mapping of section name to a list of entry strings.

```yaml
{!examples/plugins/changelog/changelog.d/20240101-example-feature.yaml!}
```

Valid sections are the lowercase `added`, `fixed`, `changed`, `deprecated`,
`removed` and `security` - section names are case-sensitive, so `Added:` is an
error.

Fragment file names follow the convention `YYYYMMDD-<topic>.yaml` - file names
only need to be unique, fragments are collected sorted by file name.

Files that are not `*.yaml` / `*.yml` (README.md, .gitkeep) as well as hidden
files are ignored. An empty `.yaml` file is a validation error since it parses
to None - use a non-yaml name for placeholder files.

Subdirectories are not scanned - only fragment files directly in the fragments
directory are collected.

A section key may not appear twice in the same fragment file. Since a fragment
is deleted once it has been collected into a release, letting the last key win
would silently drop the shadowed entries, so a duplicate key is a validation
error instead.

#### Release behavior with fragments

When `ctl changelog release <version>` runs with a fragments directory
present:

- all fragments are validated before anything is written - validation errors
  name the offending file
- per section, residual `Unreleased:` entries are merged first, then the
  fragment entries in file name order
- non-standard section keys under `Unreleased:` are carried over to the
  release section as well, they are never dropped
- the CHANGELOG.md file is regenerated
- the fragment files are deleted last, after the release has been written to
  the data file and the markdown has been regenerated

A populated `Unreleased:` section is still allowed - a friendly suggestion to
move its items to fragments is printed.

!!! note "Release is not atomic"
    If a release fails between writing the data file and deleting the
    fragments, a re-run will error with "already exists" and the leftover
    fragments need to be removed by hand. The removal error names the
    fragments that are still on disk - they would otherwise be collected into
    the next release a second time.

### Check for changelog changes (CI)

The `check` operation checks that the current branch touched the changelog -
the data file itself, or a fragment file added, changed or deleted directly in
the fragments directory - using `git diff --name-only <base>...HEAD` (three-dot,
i.e. changes since the merge-base with the base ref).

Only paths that `release` would actually collect satisfy the gate, so a nested
`changelog.d/<subdir>/entry.yaml` or a `changelog.d/README.md` edit does not
pass it.

If `--base` is not passed the base ref is taken from the CI environment
(`GITHUB_BASE_REF`, `CI_MERGE_REQUEST_TARGET_BRANCH_NAME`), falling back to the
first of `origin/HEAD`, `origin/main`, `origin/master` that resolves. The exit
code is 1 when no changelog change is found or the base ref cannot be resolved.

When one of those CI variables is set the target branch is known, so an
`origin/<branch>` that does not resolve is an error rather than a reason to
guess - fetch the base ref in the checkout step, or pass `--base`.

!!! warning "The fallback guess is not the branch's base"
    The `origin/HEAD` fallback is only the right answer for a branch that
    targets the default branch. A branch that targets, say, `develop` is
    diffed against the default branch instead, so a changelog entry that
    arrived with `develop` satisfies the gate even though the branch itself
    added none. The fallback logs a warning naming the ref it guessed - pass
    `--base` explicitly wherever branches target anything but the default
    branch.

```sh
# diff against origin/HEAD -> origin/main -> origin/master
ctl changelog check

# diff against an explicit base ref
ctl changelog check --base upstream/main
```

Example usage in a GitHub Actions workflow:

```yaml
- uses: actions/checkout@v4
  with:
    # the three-dot diff needs the merge-base to be present
    fetch-depth: 0
- run: ctl changelog check --base origin/${{ github.base_ref }}
```

!!! note "CI caveats"
    - The three-dot diff needs the merge-base to be present, so shallow
      checkouts (fetch-depth 1) must fetch the base ref / history first.
    - `origin/HEAD` is typically unset in fetch-based CI checkouts - the
      default base then falls through to `origin/main` / `origin/master`.
    - The default-base logic assumes the remote is named `origin` - pass
      `--base` otherwise.
    - `check` reads committed history only - a fragment that has been written
      but not committed does not satisfy the gate.

### Usage

!!! note "Plugin name"
    This usage documentation assumes that the plugin instance name
    is `changelog`

{pymdgen-cmd:ctl --home=docs changelog --help}

#### generate

{pymdgen-cmd:ctl --home=docs changelog generate --help}

#### generate_datafile

{pymdgen-cmd:ctl --home=docs changelog generate_datafile --help}

#### generate_clean

{pymdgen-cmd:ctl --home=docs changelog generate_clean --help}

#### release

{pymdgen-cmd:ctl --home=docs changelog release --help}

#### check

{pymdgen-cmd:ctl --home=docs changelog check --help}
