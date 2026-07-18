# Venv Plugin

Manages a python virtualenv

## Requirements

We currently use `pipenv` to maintain the virtualenv, although support for other solutions like `poetry` are being discussed.

```
pip install pipenv
```

Additionally if you want to be able to sync your `setup.py` file from the Pipfile via the `sync_setup` setup operation you will need to install the `pipenv-setup` addon.

```
pip install pipenv-setup
```

## Example

In the following example we want to set up a virtualenv for python3.6. For the sake of simplicity it will only install the latest version of the `requests` module into it.

`Ctl/config.yaml`

```yaml
{!examples/plugins/venv/Ctl/config.yaml!}
```

By default it will be looking for a pipenv `Pipfile` in your ctl home

`Ctl/Pipfile`

!!! note "Use a symlink"
    While it is possible for ctl to work with a Pipfile that is not at your project root
    having it at root seems to be the accepted standard at this point. We suggest you
    maintain the Pipfile at `./Pipfile` and symlink it in `$CTL_HOME/Pipfile`

    Alternatively you can also just setup your `pipfile` [plugin config](/api/ctl.plugins.venv#venvpluginconfig)
    attribute accordingly.

```ini
{!examples/plugins/venv/Ctl/Pipfile!}
```

## Run the command

The command will be exposed as an operation to the ctl cli by it's name and also provide three sub operations: `build`, `sync` and `copy`

### Build / Sync

`build` is used to initially build the virtualenv
`sync` will build the virtualenv if it does not exist and otherwise update that it with the latest requirements

```sh
ctl venv36 sync output/venv36
```

### Copy

Copies an existing virtualenv to a new location

```sh
ctl venv36 copy output/venv36 output/venv36_copy
```

## Usage

!!! note "Plugin name"
    This usage documentation assumes that the plugin instance name
    is `venv`

{pymdgen-cmd:ctl --home=docs venv --help}

### Build

{pymdgen-cmd:ctl --home=docs venv build --help}

### Sync

{pymdgen-cmd:ctl --home=docs venv sync --help}

### Sync Setup

{pymdgen-cmd:ctl --home=docs venv sync_setup --help}

### Copy

{pymdgen-cmd:ctl --home=docs venv copy --help}
