import io
from pathlib import Path
from typing import Any

import ruamel.yaml
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import LiteralScalarString

from dncore.abc import ObjectSerializable
from dncore.configuration import ConfigValues, ConfigValueEntry, ValueNotSet
from dncore.configuration.file import ParseError, ConfigFileDriver
from dncore.configuration.types import ConfigType

yaml = ruamel.yaml.YAML()
yaml.indent(mapping=2, sequence=4, offset=2)
__all__ = ["YamlFileDriver"]


class YamlFileDriver(ConfigFileDriver):
    __data = None  # type: CommentedMap | None

    def load(self):
        self.__data = None
        if not self.path.is_file():
            self.__data = None
        else:
            with self.path.open("r", encoding="utf-8") as file:
                self.__data = yaml.load(file)
        return self.__data

    def save(self, obj: Any | ObjectSerializable):
        if isinstance(obj, ObjectSerializable):
            obj = obj.serialize()

        with io.StringIO() as temp:
            yaml.dump(obj, temp)
            temp.seek(0)

            parent = Path(self.path.parent)
            if not parent.exists():
                parent.mkdir(exist_ok=True)

            with self.path.open("w", encoding="utf-8") as file:
                file.write(temp.read())

    def load_to(self, config: ConfigValues) -> list[ParseError]:
        errors = list()
        self.__deserialize_config(self.load(), config, dirs=[], errors=errors)
        return errors

    def save_from(self, config: ConfigValues) -> list[ParseError]:
        errors = list()
        self.save(self.__serialize_config(self.__data, config, dirs=[], errors=errors))
        return errors

    @classmethod
    def __serialize_config(cls, data: CommentedMap | None, config: ConfigValues, *, dirs, errors):
        write_comments = False
        if not data:
            write_comments = True
            data = CommentedMap()

        if config is None:
            return None

        count = 0
        for name, entry in config.get_values().items():
            try:
                if isinstance(entry.type, ConfigType):
                    dirs.append(name)
                    try:
                        value = cls.__serialize_config(data.get(name), entry.value, dirs=dirs, errors=errors)
                    finally:
                        dirs.remove(name)
                else:
                    value = entry.serialize()

                data[name] = cls._format_value(value)
                if write_comments and entry.comments:
                    sp_line = "\n" if count else ""
                    data.yaml_set_comment_before_after_key(name, before=sp_line + entry.comments, indent=len(dirs) * 2)

            except Exception as err:
                errors.append(ParseError(".".join(dirs + [name]), entry, err))

            count += 1

        return data

    @classmethod
    def __deserialize_config(cls, data: CommentedMap | None, config: ConfigValues, set_default=True, *, dirs, errors):
        if data is None:
            data = CommentedMap()
        for name, entry in config.get_values().items():  # type: (str, ConfigValueEntry)
            try:
                if isinstance(entry.type, ConfigType):
                    dirs.append(name)
                    try:
                        if name in data and data[name] is None and entry.type.nullable:
                            entry.value = None
                            continue

                        child = entry.value  # 本当はここでNull許容した上で値をセットしたい
                        if child is None:  # 値があるか？なんてそもそもおかしい。なぜなら、既にデフォルト挙動で値がセットされるもの
                            if entry.default is None:
                                try:
                                    child = entry.value = entry.type.default()
                                except ValueNotSet:
                                    continue

                            else:
                                child = entry.value = entry.type.clone(entry.default)

                        else:
                            if name not in data or data[name] is None:
                                if entry.default is not None:
                                    entry.value = entry.type.clone(entry.default)
                                    continue

                        if not set_default and name in data and data[name] is None:
                            continue  # このConfigValuesのデフォルト値を当てるためにデシリアライズしない

                        cls.__deserialize_config(data.get(name), child, set_default or name not in data, dirs=dirs, errors=errors)

                    finally:
                        dirs.remove(name)
                else:
                    entry.deserialize(data.get(name), set_default or name not in data)
            except Exception as err:
                errors.append(ParseError(".".join(dirs + [name]), entry, err))

    @classmethod
    def _format_value(cls, obj):
        if isinstance(obj, str) and max(map(len, obj.split("\n"))) >= 2 and obj.count("\n") >= 3:
            obj = LiteralScalarString(obj)

        return obj
