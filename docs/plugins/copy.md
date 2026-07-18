# Copy Plugin

Walk directories at a source directory and copy files to an output directory

## Example config

In this first example we want to copy all files from `./source/dir_1` and
`./source/dir_2` to `./output/dir_1` and `./output/dir_2` respectively.

```yaml
{!examples/plugins/copy/basic/Ctl/config.yaml!}
```

## Run the command

The command will be exposed as an operation in the ctl cli by it's name, so we simply run it as such

```sh
ctl copy
```

```sh
[2019-10-09 08:22:34,496] [usage] ran command: `copy`
[2019-10-09 08:22:34,497] [ctl.plugins.copy] Skip dotfiles: True
[2019-10-09 08:22:34,498] [ctl.plugins.copy] output/dir_1/file.txt
[2019-10-09 08:22:34,499] [ctl.plugins.copy] output/dir_3/file.txt
```

## Example: Ignore files based on pattern

You can use the `ignore` config to ignore certain file types or paths

```yaml
{!examples/plugins/copy/ignore/Ctl/config.yaml!}
```

## Example: process files based on pattern

You can use the `process` config to process files after they have been copied.

We can defer to other plugins for such actions.

In the following example we do a simple search and replace on `*.html` files via a [command](/plugins/command) plugin.

```yaml
{!examples/plugins/copy/process/Ctl/config.yaml!}
```

## Usage

!!! note "Plugin name"
    This usage documentation assumes that the plugin instance name
    is `copy`

{pymdgen-cmd:ctl --home=docs copy --help}
