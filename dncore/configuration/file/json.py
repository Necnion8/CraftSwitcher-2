import json
from pathlib import Path
from typing import Any

from dncore.abc import ObjectSerializable
from dncore.configuration.file import FileDriver


class JsonFileDriver(FileDriver):
    def load(self):
        if not self.path.is_file():
            return {}
        with self.path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def save(self, obj: Any | ObjectSerializable):
        if isinstance(obj, ObjectSerializable):
            obj = obj.serialize()

        raw = json.dumps(obj, ensure_ascii=False, indent=4)
        # if len(raw) > 1024 ** 2:
        #     raw = json.dumps(data, ensure_ascii=False)

        parent = Path(self.path.parent)
        if not parent.exists():
            parent.mkdir(exist_ok=True)

        with self.path.open("w", encoding="utf-8") as file:
            file.write(raw)
