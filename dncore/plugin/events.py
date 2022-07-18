from dncore.event import Event

__all__ = ["PluginEvent", "PluginEnableEvent", "PluginDisableEvent"]


class PluginEvent(Event):
    def __init__(self, plugin):
        """
        :type plugin: dncore.plugin.PluginInfo
        """
        self._plugin = plugin

    @property
    def plugin_info(self):
        return self._plugin

    @property
    def plugin_instance(self):
        """
        :rtype: dncore.plugin.Plugin
        """
        return self._plugin.instance


class PluginEnableEvent(PluginEvent):
    pass


class PluginDisableEvent(PluginEvent):
    pass
