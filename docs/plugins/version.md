## Version Plugin

Use this plugin to tag and push a release to a repository

It will automatically tag, merge branches and maintain a `Ctl/VERSION` file in the targeted repository.

### Config Example

```yaml
{!examples/plugins/version/Ctl/config.yml!}
```

### Command Examples

Tag the repository we specified in the `repository`
config attribute above

```sh
# update Ctl/VERSION to 1.0.0
# tag 1.0.0
# push tag
ctl version tag 1.0.0
```

If you're using the version plugin for the first time on a repo and a `Ctl/VERSION` file does not exist yet you can pass the `--init` option to create it.

```sh
# create Ctl/VERSION file
# update Ctl/VERSION to 1.0.0
# tag 1.0.0
# push tag
ctl version tag 1.0.0 --init
```

You may also chose to bump a semantic version

```sh
# update Ctl/VERSION from 1.0.0 to 1.1.0
# tag 1.1.0
# push tag
ctl version bump minor
```

!!! note "semver2 plugin"
    The `semver2` plugin supports additional flags on these operations:
    `--prefix v` (tag as `v1.0.0`), `--no-git-tag` (commit version files
    but skip the git tag) and `--no-git` (skip all git operations). For
    example `ctl semver2 bump minor --no-git-tag`. The `version` plugin
    does not implement these flags and will reject them.

### Use existing repository checkout

Instead of configuring and specifying a git type plugin to use
you can also set `repository` to a directory path. It still needs
to be the location of a valid git checkout.


```yaml
ctl:
  plugins:
    - type: version
      name: version
      config:
        repository: /path/to/my/repository/checkout
```

### Specifying repository in the command line

It is also possible to specify a repository when running the
command.

```
ctl version tag 1.0.0 /path/to/my/repository
ctl version tag 1.0.0 .
ctl version tag 1.0.0 [plugin_name]
```

### Usage

!!! note "Plugin name"
    This usage documentation assumes that the plugin instance name
    is `version`

{pymdgen-cmd:ctl --home=docs version --help}

#### Tag

{pymdgen-cmd:ctl --home=docs version tag --help}

#### Bump

{pymdgen-cmd:ctl --home=docs version bump --help}

#### Merge_Release

{pymdgen-cmd:ctl --home=docs version merge_release --help}
