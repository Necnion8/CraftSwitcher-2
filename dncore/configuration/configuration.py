import inspect
import re
import textwrap
import traceback
import types
import typing
from logging import getLogger
from typing import Any, Iterable, Callable

from dncore.abc import ObjectSerializable, ObjectSerializer, serializables
from dncore.configuration.types import ObjectType, ConfigType

log = getLogger(__name__)
__all__ = ["ConfigValueEntry", "ConfigValues", "ValueNotSet"]


class ConfigValueEntry:
    def __init__(self, v_name: str, v_type: type, v_default: Any,
                 *, comments: str = None, optional=True, serializers: list[ObjectSerializer] = None):
        if type(None) is v_type:
            raise ValueError("invalid type: NoneType")

        self.name = v_name
        self.type = ObjectType.from_value(v_type, nullable=False, serializers=serializers or [])
        self.default = v_default
        self.comments = comments
        self.optional = optional
        self.__value = None

        if self.type.nullable:
            if self.default is not None:
                self.__value = self.type.clone(self.default)
        else:
            if self.default is None:
                try:
                    self.__value = self.type.default()
                except ValueNotSet:
                    pass
            else:
                self.__value = self.type.clone(self.default)
        self.test("REI:", self.__value)

    @property
    def value(self):
        if self.__value is None and not self.type.nullable:
            self.__value = self.type.clone(self.default) if self.optional else self.type.default()
        self.test("RE:", self.__value)
        return self.__value

    @value.setter
    def value(self, value):
        if value is None or self.type.equals_type(value):
            self.__value = value
        else:
            raise TypeError(f"invalid type (required: {self.type.typename()}, obj: {value!r})")

    def serialize(self):
        try:
            return self.type.serialize(self.value)
        except ValueNotSet:
            return None  # ignored

    def deserialize(self, serialized, set_default=True):
        self.test("- setDefault", set_default)
        if serialized is not None:
            self.test("serialized is not None")
            self.__value = self.type.deserialize(serialized)

        elif not set_default and self.type.nullable:  # nullを許容する値だった
            self.test("containsKey and nullable")
            self.__value = None

        elif not self.optional:  # 値が必須だった
            self.test("set default")
            try:
                # タイプがdefault()による Optional Default を許容するなら
                self.__value = self.type.default()

            except ValueError as e:
                self.test("F")
                # 値が未指定としてエラー
                raise ValueNotSet(f"'{self.name}' value has not set", entry=self) from e

        else:
            self.test("value")
            self.__value = self.type.clone(self.default)

        self.test("RES:", self.__value)

    def test(self, *m):
        # if self.name in ["connecting_activity", "status"]:
        #     print(f"{self.name!r}:", *m)
        pass


class ConfigValues(ObjectSerializable):
    __init = False

    def __init__(self):
        serializers = [*self._serializers(), *serializables.serializers()]
        errors, self.__values = self.__find_values(serializers)
        if errors:
            field_names_length = min(max(len(n) for n in errors), 50) + 1
            values = []
            for n, e in errors.items():
                values.append(f"{n}{(field_names_length-len(n))*' '} : {str(e)}")
                if not isinstance(e, ValueNotSet):
                    values.append("\n".join(traceback.format_exception(e)))
            raise ValueError("Invalid define ConfigValues values:\n" + "\n".join(values))

        for key, entry in self.__values.items():
            setattr(self, key, entry)

        self.__init = True
        self.__getter = None  # type: Callable[[ConfigValueEntry], Any] | None
        self.__setter = None  # type: Callable[[ConfigValueEntry, Any], None] | None

    def get_values(self):
        return self.__values

    def serialize(self):
        return {k: i.serialize() for k, i in self.get_values().items()}

    @classmethod
    def _serializers(cls) -> Iterable[ObjectSerializer]:
        """
        このメソッドをオーバーライドし、カスタムクラスのシリアライザーを返す。
        """
        return []

    @classmethod
    def deserialize(cls, value):
        obj = cls()
        obj.deserialize_from(value or {})
        return obj

    def deserialize_from(self, data: dict):
        for entry in self.get_values().values():
            if isinstance(entry.type, ConfigType):
                if entry.name in data and data[entry.name] is None:
                    continue  # このConfigValuesのデフォルト値を当てるためにデシリアライズしない
                entry.value.deserialize_from(data.get(entry.name) or {})
            else:
                entry.deserialize(data.get(entry.name), entry.name in data)

    def __getattribute__(self, item):
        obj = object.__getattribute__(self, item)
        if item.startswith("_") or not isinstance(obj, ConfigValueEntry):
            return obj

        if self.__getter is None:
            return obj.value
        else:
            return self.__getter(obj)

    def __setattr__(self, key, value):
        if not self.__init or key.startswith("_"):
            object.__setattr__(self, key, value)
            return

        try:
            obj = object.__getattribute__(self, key)
        except AttributeError:
            raise AttributeError("denied set other value")
        else:
            if not isinstance(obj, ConfigValueEntry):
                raise AttributeError
            if self.__setter is None:
                obj.value = value
            else:
                self.__setter(obj, value)

    @classmethod
    def __find_values(cls, serializers: list[ObjectSerializer]):
        """
        変数のコメントとデフォルトと型ヒントを読み取る
        find_commentsを元に値の並びを維持する
        """

        def _v_check(n, v):
            return (not n.startswith("_")
                    and not inspect.isfunction(v)
                    and not inspect.ismethod(v)
                    and not inspect.isclass(v))

        def type_wrapper(v_typ, opt):
            opt = opt
            if isinstance(v_typ, types.UnionType):
                a_types = list(typing.get_args(v_typ))
                if len(a_types) != 2 or type(None) not in a_types:
                    raise ValueError(f"Not allowed Union type: {v_typ}")
                opt = True

            return v_typ, opt

        value_annotations = {k: v for k, v in cls.__annotations__.items()
                             if not k.startswith("_")}  # type: dict[str, type]
        value_defaults = {n: getattr(cls, n)
                          for n in dir(cls)
                          if _v_check(n, getattr(cls, n))}

        errors = {}  # type: dict[str, Exception]
        values = {}  # type: dict[str, ConfigValueEntry]

        # commented
        for name, comments in cls.__find_comments().items():
            if name not in value_defaults and name not in value_annotations:
                continue

            optional = name in value_defaults and value_defaults[name] is not None
            v_default = value_defaults.pop(name, None)
            v_type = value_annotations.pop(name, None) or type(v_default)

            try:
                v_type, optional = type_wrapper(v_type, optional)
                values[name] = ConfigValueEntry(name, v_type, v_default,
                                                comments=comments, optional=optional, serializers=serializers)
            except Exception as e:
                errors[name] = e

        # no commented with default
        if value_defaults:
            for name, v_default in value_defaults.items():
                v_type = value_annotations.pop(name, None) or type(v_default)

                try:
                    v_type, _ = type_wrapper(v_type, False)
                    values[name] = ConfigValueEntry(name, v_type, v_default, optional=True, serializers=serializers)
                except Exception as e:
                    errors[name] = e

        # only annotation
        if value_annotations:
            for name, v_type in value_annotations.items():
                try:
                    v_type, optional = type_wrapper(v_type, False)
                    values[name] = ConfigValueEntry(name, v_type, None, optional=optional, serializers=serializers)
                except Exception as e:
                    errors[name] = e

        return errors, values

    @classmethod
    def __find_comments(cls):
        """
        inspect.getsource()を使い、値とその前行にある#コメントを読み取る
        """
        sources = inspect.getsource(cls)

        value_comments = {}  # type: dict[str, str | None]
        lines = []
        v_reg = re.compile("^([a-zA-Z0-9_]+)[ :=]")

        for line in sources.splitlines():
            line = line.lstrip(" ")
            if line.startswith("#"):
                lines.append(line[1:])
            else:
                m = v_reg.search(line)
                if m:
                    v_name = m.group(1)
                    if lines:
                        value_comments[v_name] = textwrap.dedent("\n".join(lines))
                    else:
                        value_comments[v_name] = None
                lines.clear()

        return value_comments

    def set_setter(self, callback: Callable[[ConfigValueEntry, Any], None]):
        self.__setter = callback

    def set_getter(self, callback: Callable[[ConfigValueEntry], Any]):
        self.__getter = callback


class ValueNotSet(ValueError):
    def __init__(self, *args, entry: ConfigValueEntry = None):
        ValueError.__init__(self, *args)
        self.entry = entry
