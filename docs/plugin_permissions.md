# It's grainy

We are using [grainy](https://github.com/20c/grainy) to handle our permissioning.

### It's c.r.u.d

When refering to permissions we are using the tried and tested crud system

1. *c* - create
1. *r* - read
1. *u* - update
1. *d* - delete

### It's also namespaced

This allows for very granular namespaced based permissions

#### Namespace examples

| user permissions | plugin op namespace | can run |
|---|---|---|
| `ctl` | `ctl.{plugin_name}.do_something` | yes |
| `ctl.my_plugin` | `ctl.my_plugin.do_something` | yes |
| `ctl.my_plugin` | `ctl.other_plugin.do_something` | no |
| `ctl.my_plugin.do_this` | `ctl.other_plugin.do_something` | no |

## Control permission requirements

By default permission requirement for any plugin operation is `r` (unless
specifically overwritten in the `expose` decorator that's exposing the operation)

You can specify different permission requirements in the config

### Example Config: version plugin

```
    - name: version
      type: version
      config:
        # require `c` level permissions for all the tagging operations
        # in this instance of the version plugin
        permissions:
          tag: c
          bump: c
```

### Example Config: command plugin

```
    - name: ls
      type: command
      config:
        # here we require `c` level permission in order to execute the command
        # in this particular command type plugin instance
        permissions:
          execute: c
        command:
          - ls -all
```

## Development

### Expose plugin operations

You can use the `expose` dectorator from `ctl.auth` to expose methods on a plugin as an operation to be available on the ctl cli.

Any exposed function will have `exposed` property set to `True`

```py
from ctl.auth import expose

class VersionPlugion(ExecutablePlugin):
    ...

    @expose("ctl.{plugin_name}.tag")
    def tag(self, version, repo, **kwargs):
        ...

    ...
```

### Static namespace

```
class ExamplePlugin(PluginBase):
  @expose("ctl.example.do_something")
  def do_something(self, something):
    ...
```

### Dynamic namespace via formatting

```
class ExamplePlugin(PluginBase):
  @expose("ctl.{plugin_name}.do_something")
  def do_something(self, something):
    ...
```

### overwrite default permission level requirement

Sometimes you may want to hardcode a permission requirement, or perhaps obtain
it dynamically, this can be done with the level argument

```
@expose("namespace", "r")
```

```
@expose("namespace", lambda plugin: "r")
```
