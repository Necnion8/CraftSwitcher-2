import datetime
import re

__all__ = ["Version", "IGNORE_FRAME", "FakeStringFormat"]
IGNORE_FRAME = object()


class Version(object):
    REGEX = re.compile(r"(?P<v1>\d+)\.(?P<v2>\d+)\.(?P<v3>\d+)(?P<b>b?)(/(?P<dt>\d{6}))?")

    def __init__(self, version: tuple[int, int, int], release: datetime.date = None, *, beta=False):
        self.version = version
        self.release_date = release
        self.beta = beta

    def __repr__(self):
        return "<Version version={1!r} release={0.release_date} beta={0.beta}>"\
            .format(self, ".".join(map(str, self.version)))

    def __str__(self):
        s = "{0}{1}".format(".".join(map(str, self.version)), "b" if self.beta else "")
        if self.release_date:
            s += "/" + self.release_date.strftime("%y%m%d")
        return s

    @property
    def numbers(self):
        return Version(version=self.version, beta=self.beta)

    @classmethod
    def parse(cls, text: str):
        match = cls.REGEX.match(text.lower())
        if not match:
            raise ValueError("Invalid version format: %s" % text)

        version = (int(match.group("v1")), int(match.group("v2")), int(match.group("v3")))
        beta = bool(match.group("b"))
        if match.group("dt"):
            date = datetime.datetime.strptime(match.group("dt"), "%y%m%d").date()
        else:
            date = None
        return cls(version, date, beta=beta)

    def __eq__(self, other):
        if not isinstance(other, Version):
            raise ValueError
        return self.version == other.version  # and self.beta == other.beta

    def __lt__(self, other):
        if not isinstance(other, Version):
            raise ValueError(f"unsupported: {other!r}")

        if self.version != other.version:
            return self.version < other.version

        if self.release_date != other.release_date:
            _dt = 0 if self.release_date is None else self.release_date.toordinal()
            _dt_other = 0 if other.release_date is None else other.release_date.toordinal()
            return _dt < _dt_other

        return self.beta > other.beta
        # return self.version < other.version

    def __ne__(self, other):
        return not self.__eq__(other)

    def __le__(self, other):
        return self.__lt__(other) or self.__eq__(other)

    def __gt__(self, other):
        return not self.__le__(other)

    def __ge__(self, other):
        return not self.__lt__(other)


class FakeStringFormat(object):
    def __str__(self):
        return ""

    def __getattr__(self, item):
        return FakeStringFormat()
