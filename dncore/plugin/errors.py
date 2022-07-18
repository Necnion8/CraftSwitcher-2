
__all__ = ["PluginException", "PluginRequirementsError", "PluginOperationError", "InvalidPluginInfo"]


class PluginException(Exception):
    pass


class PluginRequirementsError(PluginException):
    pass


class PluginOperationError(PluginException):
    pass


class InvalidPluginInfo(Exception):
    pass
