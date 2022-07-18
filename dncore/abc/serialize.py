__all__ = ["ObjectSerializable", "Cloneable", "ObjectSerializer"]


class ObjectSerializable:
    def serialize(self):
        raise NotImplementedError

    @classmethod
    def deserialize(cls, value):
        raise NotImplementedError


class Cloneable:
    def clone(self):
        raise NotImplementedError


# noinspection PyMethodMayBeStatic
class ObjectSerializer:
    def serialize(self, obj):
        raise NotImplementedError

    def deserialize(self, value):
        raise NotImplementedError

    def check(self, clazz) -> bool:
        raise NotImplementedError

    def override_nulls(self):
        return False
