# Events

CTL uses an event system to let plugins and components trigger and react to events.

## Common Events

### Currently defined events

- `exit` - triggers when CTL cli completes
- `{log_name}-log-write-before` - triggers before a log is written to, {log_name} is to be subsituted by the name of the logger
- `{log_name}-log-write-after` - triggers after a log is written to, {log_name} is to be substituted by the name of the logger

### Plugin hook

#### Config

Common events are events that are accessible by all plugins. Configure
your plugin's events objects to hook into them.

```yaml
ctl:
  plugins:
    - type: plugin
      events:
        # hook into the CTL `exit` event, which triggers when
        # the CTL cli completes.
        exit:
          # call the plugin's `do_something` method with
          # the keyword argument `test`=123
          do_something:
            test: 123
```

#### Through code

You can also hook directly in your code

```py
from ctl.events import common_events

common_events.on("exit", lambda *a, **kw: plugin.do_something(test=123))
```

### Trigger events

```py
from ctl.events import common_events

# trigger event, all arguments are passed to the callbacks attached ot the even
common_events.trigger("my_event", 123, something_else=456)
```

## Event Handlers

`common_events` is a predefined event handler that should be used for most puposes, you can however easily instantiate new event handlers if you need them.

```py
from ctl.events import Events

event_handler = Events()

event_handler.on("my_event", lambda *a, **kw: do_something(*a, **kw))
event.handler.trigger("my_event", "some arg", test="some kwarg")
```
