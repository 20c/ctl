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

