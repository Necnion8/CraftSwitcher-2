from pathlib import Path
from typing import NamedTuple, TYPE_CHECKING

from .event import SwitcherExtensionAddEvent, SwitcherExtensionRemoveEvent
from .utils import call_event

if TYPE_CHECKING:
    from dncore.plugin import PluginInfo

__all__ = [
    "MessageResponse",
    "EditableFile",
    "SwitcherExtension",
    "ExtensionInfo",
    "SwitcherExtensionManager",
]


class MessageResponse(object):
    def __init__(self, content: str, caption: str = None, errors=False):
        self.content = content
        self.caption = caption
        self.errors = errors


class EditableFile(object):
    def __init__(self, path: Path, key: str, label: str = None):
        self.path = path
        self.key = key
        self.label = label


class SwitcherExtension(object):
    def __init__(self):
        self.editable_files = []  # type: list[EditableFile]

    async def on_file_load(self, editable_file: EditableFile) -> MessageResponse | None:
        """
        Switcherがファイルを読み込む時
        """
        pass

    async def on_file_pre_update(self, editable_file: EditableFile) -> MessageResponse | None:
        """
        Switcherによってファイルが更新される時
        """
        pass

    async def on_file_update(self, editable_file: EditableFile) -> MessageResponse | None:
        """
        Switcherによってファイルが更新された時
        """
        pass


class ExtensionInfo(NamedTuple):
    name: str
    version: str
    description: str | None
    authors: list[str]
    plugin: "PluginInfo | None"

    @classmethod
    def create(cls, plugin: "PluginInfo", description: str = None):
        return cls(
            name=plugin.name,
            version=str(plugin.version),
            description=description or plugin.description,
            authors=plugin.authors,
            plugin=plugin,
        )


class SwitcherExtensionManager(object):
    def __init__(self):
        self.extensions = {}  # type: dict[SwitcherExtension, ExtensionInfo]

    def get(self, name: str):
        for extension, info in self.extensions.items():
            if info.name.lower() == name.lower():
                return extension

    def get_info(self, name: str):
        for extension, info in self.extensions.items():
            if info.name.lower() == name.lower():
                return extension, info
        return None, None

    def add(self, extension: SwitcherExtension, info: ExtensionInfo):
        if extension in self.extensions:
            raise ValueError("Already added extension")
        for _info in self.extensions.values():
            if _info.name.lower() == info.name.lower():
                raise ValueError("Already added extension name")
        self.extensions[extension] = info
        call_event(SwitcherExtensionAddEvent(info))

    def remove(self, extension: SwitcherExtension):
        info = self.extensions.pop(extension, None)
        if info:
            call_event(SwitcherExtensionRemoveEvent(info))
