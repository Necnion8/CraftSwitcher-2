
__all__ = [
    "PluginException",
    "PluginRequirementsError",
    "PluginOperationError",
    "PluginDependencyError",
    "InvalidPluginInfo",
]


class PluginException(Exception):
    pass


class PluginRequirementsError(PluginException):
    pass


class PluginOperationError(PluginException):
    pass


class PluginDependencyError(PluginException):
    def __init__(self, *args, depends: list[str] = None):
        super().__init__(*args)
        self.depends = depends


class InvalidPluginInfo(Exception):
    pass
