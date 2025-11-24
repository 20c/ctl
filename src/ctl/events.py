class Events:
    """
    Events handler that works similarly to jquery events
    """

    def __init__(self):
        self.events = {}

    def trigger(self, event_name, *args, **kwargs):
        """
        Trigger an event by name, calling all callbacks
        attached to the event

        All arguments and keyword arguments are passed through
        to the callback

        Arguments:
            - event_name (str): name of the event
        """

        for callback in self.events.get(event_name, []):
            callback(self, *args, **kwargs)

    def on(self, event_name, callback):
        """
        Add callback to event specified by event_name
        """
        if event_name not in self.events:
            self.events[event_name] = [callback]
        elif callback not in self.events[event_name]:
            self.events[event_name].append(callback)

    def off(self, event_name, callback):
        """
        Remove callback from event specified by event_name
        """
        callbacks = self.events.get(event_name)
        if callbacks and callback in callbacks:
            callbacks.remove(callback)

    def one(self, event_name, callback):
        """
        Add callback to event specified by event_name and remove
        it automatically after event has been triggered
        """
        listener = self

        def wrapped(*args, **kwargs):
            callback(*args, **kwargs)
            listener.off(event_name, wrapped)

        self.on(event_name, wrapped)


common_events = Events()
