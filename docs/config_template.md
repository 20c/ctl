# Config Template Rendering

If tmpl and jinja2 are installed, config will be rendered before it is loaded.

```
pip install tmpl jinja2
```

## Example

```yaml
{!examples/config_template/Ctl/config.yaml!}
```

## Exposed variables

| variable | description |
|---|---|
| ctx.home | path to ctl home directoy |
| ctx.tmpdir | path to ctl tmp directory|
| ctx.cachedir | path to ctl cache directory |
| ctx.user_home | path to user home directory |
| input.plugin | input parameters for the plugin that's being executed |
| plugin.[plugin_name] | variables exposed by a plugins `expose_vars` function |
