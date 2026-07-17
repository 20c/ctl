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

#### Release behavior with fragments

When `ctl changelog release <version>` runs with a fragments directory
present:

- all fragments are validated before anything is written - validation errors
  name the offending file
- per section, residual `Unreleased:` entries are merged first, then the
  fragment entries in file name order
- the fragment files are deleted after the release has been written to the
  data file
- the CHANGELOG.md file is regenerated

A populated `Unreleased:` section is still allowed - a friendly suggestion to
move its items to fragments is printed.

!!! note "Release is not atomic"
    If a release fails between writing the data file and deleting the
    fragments, a re-run will error with "already exists" and the leftover
    fragments need to be removed by hand.

### Check for changelog changes (CI)

The `check` operation checks that the current branch touched the changelog -
any path under the fragments directory (including deletions) or the data file
itself - using `git diff --name-only <base>...HEAD` (three-dot, i.e. changes
since the merge-base with the base ref).

If `--base` is not passed the base ref defaults to the first of `origin/HEAD`,
`origin/main`, `origin/master` that resolves. The exit code is 1 when no
changelog change is found or the base ref cannot be resolved.

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
