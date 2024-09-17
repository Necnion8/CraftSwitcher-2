import types
from enum import Enum
from typing import Generic, TypeVar, get_origin, get_args, Any

from dncore.abc import ObjectSerializable, Cloneable, ObjectSerializer
from dncore.util import typename

VT = TypeVar("VT")
T = TypeVar("T")
__all__ = ["ObjectType", "SimpleType", "SerializableType", "ListType", "DictType", "ConfigType", "SerializerWrap"]


class ObjectType(Generic[VT]):
    def __init__(self, v_type: type[VT], nullable=False):
        self.type = v_type
        self.nullable = nullable

    def equals_type(self, obj: VT) -> bool:
        return isinstance(obj, self.type)

    def typename(self) -> str:
        return self.type.__name__

    def __repr__(self):
        return "<{} vType={}>".format(type(self).__name__, self.typename())

    def serialize(self, obj: VT | None):
        raise NotImplementedError

    def deserialize(self, serialized: Any | None) -> VT | None:
        raise NotImplementedError

    def clone(self, obj):
        raise NotImplementedError

    def default(self):
        from .configuration import ValueNotSet
        raise ValueNotSet("value not set")

    @staticmethod
    def from_value(v_type: type, nullable=False, *, serializers: list[ObjectSerializer]):
        """
        :rtype: ObjectType
        """
        from .configuration import ConfigValues
        if v_type in (bool, str, int, float):
            # noinspection PyTypeChecker
            return SimpleType(v_type, nullable)
        elif isinstance(v_type, types.UnionType):
            a_types = list(get_args(v_type))
            if len(a_types) != 2 or type(None) not in a_types:
                raise ValueError(f"unsupported Union: {v_type}")
            a_types.remove(type(None))
            return ObjectType.from_value(a_types[0], nullable=True, serializers=serializers)
        elif issubclass(v_type, ConfigValues):
            return ConfigType(v_type, nullable)
        elif issubclass(v_type, ObjectSerializable):
            return SerializableType(v_type, nullable)
        elif issubclass(v_type, Enum):
            # noinspection PyTypeChecker
            return EnumType(v_type, nullable)
        elif get_origin(v_type) is list:
            return ListType(get_args(v_type)[0], nullable, serializers=serializers)
        elif get_origin(v_type) is dict:
            # noinspection PyTypeChecker
            return DictType(get_args(v_type), nullable, serializers=serializers)
        else:
            for serializer in serializers:
                if serializer.check(v_type):
                    return SerializerWrap(serializer)
            raise ValueError(f"unsupported type: {typename(v_type)}")


class SimpleType(ObjectType[VT]):
    def __init__(self, v_type: type[VT], nullable: bool):
        if v_type not in (bool, str, int, float):
            raise ValueError(f"unsupported type: {v_type.__name__}")
        ObjectType.__init__(self, v_type, nullable)

    def serialize(self, obj: VT):
        return obj

    def deserialize(self, serialized) -> VT | None:
        return None if serialized is None else self.type(serialized)

    def clone(self, obj):
        return obj


class SerializableType(ObjectType[ObjectSerializable]):
    def __init__(self, v_type: type[ObjectSerializable], nullable: bool):
        ObjectType.__init__(self, v_type, nullable)

    def serialize(self, obj):
        return None if obj is None else obj.serialize()
        # return self.type.serialize(obj, obj)

    def deserialize(self, serialized):
        return self.type.deserialize(serialized)

    def clone(self, obj):
        if obj is not None:
            if isinstance(obj, Cloneable):
                return obj.clone()
            raise TypeError(f"not cloneable object: {obj!r}")


class ListType(ObjectType[list[T]]):
    def __init__(self, arg_type: type[T], nullable: bool, *, serializers: list[ObjectSerializer]):
        ObjectType.__init__(self, list, nullable)
        self.arg_type = ObjectType.from_value(arg_type, serializers=serializers)

    def __repr__(self):
        return "<{} vType={} >".format(type(self).__name__, type(self.arg_type).__name__)

    def serialize(self, obj: list[T] | None):
        if obj is None:
            return []

        new_list = []
        for item in obj:
            if not self.arg_type.equals_type(item):
                raise ValueError(f"invalid data exists in list: {item!r}")
            new_list.append(self.arg_type.serialize(item))
        return new_list

    def deserialize(self, serialized: list | None) -> list[T]:
        if isinstance(serialized, list):
            return [self.arg_type.deserialize(i) for i in serialized]
        return []

    def clone(self, obj):
        return [self.arg_type.clone(i) for i in obj]

    def default(self):
        return []


class DictType(ObjectType[dict[str, T]]):
    def __init__(self, args_type: tuple[type[T], type[T]], nullable: bool, *, serializers: list[ObjectSerializer]):
        ObjectType.__init__(self, dict, nullable)
        if not issubclass(args_type[0], str):
            raise ValueError(f"unsupported key type: {typename(args_type[0])}")
        self.arg_type = ObjectType.from_value(args_type[1], serializers=serializers)

    def __repr__(self):
        return "<{} vType={} >".format(type(self).__name__, type(self.arg_type).__name__)

    def serialize(self, obj: dict[T] | None):
        if obj is None:
            return {}

        new_list = {}
        for key, item in obj.items():
            if not self.arg_type.equals_type(item):
                raise ValueError(f"invalid data exists in dict: {item!r}")
            new_list[key] = self.arg_type.serialize(item)
        return new_list

    def deserialize(self, serialized: dict | None) -> dict[str, T]:
        if isinstance(serialized, dict):
            return {k: self.arg_type.deserialize(i) for k, i in serialized.items()}
        return {}

    def clone(self, obj):
        return {k: self.arg_type.clone(i) for k, i in obj.items()}

    def default(self):
        return {}


class ConfigType(SerializableType):
    def clone(self, obj):
        return obj.clone() if isinstance(obj, Cloneable) else obj

    def default(self):
        return self.type()  # create ConfigValues


class EnumType(ObjectType[T]):
    def serialize(self, obj: Enum | None):
        return None if obj is None else obj.name

    def deserialize(self, serialized: Any | None) -> VT | None:
        if serialized is None:
            return
        for entry in self.type:
            if entry.name == serialized:
                return entry
        else:
            return self.default()  # try default enum value

    def clone(self, obj):
        return obj

    def default(self):
        try:
            return self.type.defaults()
        except (AttributeError, TypeError) as e:
            raise AttributeError(f"{self.type} is not implemented .defaults() class method") from e


# noinspection PyMethodMayBeStatic
class SerializerWrap(ObjectType):
    def __init__(self, serializer: ObjectSerializer):
        self.serializer = serializer
        ObjectType.__init__(self, type(serializer))

    def equals_type(self, obj: VT) -> bool:
        return obj is not None and self.serializer.check(type(obj))

    def serialize(self, obj: VT | None):
        if self.serializer.override_nulls() or obj is not None:
            return self.serializer.serialize(obj)

    def deserialize(self, serialized: Any | None) -> VT | None:
        if self.serializer.override_nulls() or serialized is not None:
            return self.serializer.deserialize(serialized)

    def clone(self, obj):
        return obj.clone() if isinstance(obj, Cloneable) else obj
