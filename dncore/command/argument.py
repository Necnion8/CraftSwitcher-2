__all__ = ["Argument"]

import re

from dncore.util import SafeList


class Argument(SafeList[str]):
    def is_true(self, index=0, *,
                default=...,
                trues=("yes", "y", "true", "on", "enable"), falses=("no", "n", "false", "off", "disable")):
        try:
            val = self[index].lower()
        except IndexError:
            if default is ...:
                raise
            return default

        if val in trues:
            return True
        elif val in falses:
            return False
        else:
            return None

    def get_channel(self, index=0, *, default=...):
        try:
            num = self[index].lower()
        except IndexError:
            if default is ...:
                raise
            return default

        m = re.match(r"^(\d{18,})$", num) or re.match(r"^<#(\d{18,})>$", num)
        if m is None:
            if default is ...:
                raise ValueError("not channel mention")
            return default
        return int(m.group(1))

    def get_user(self, index=0, *, default=...):
        try:
            num = self[index].lower()
        except IndexError:
            if default is ...:
                raise
            return default

        m = re.match(r"^(\d{18,})$", num) or re.match(r"^<@(\d{18,})>$", num)
        if m is None:
            if default is ...:
                raise ValueError("not channel mention")
            return default
        return int(m.group(1))

    def get_role(self, index=0, *, default=...):
        try:
            num = self[index].lower()
        except IndexError:
            if default is ...:
                raise
            return default

        m = re.match(r"^(\d{18,})$", num) or re.match(r"^<@&(\d{18,})>$", num)
        if m is None:
            if default is ...:
                raise ValueError("not channel mention")
            return default
        return int(m.group(1))

