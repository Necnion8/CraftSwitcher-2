import datetime
import inspect
import re
from logging import getLogger
from typing import Any, Literal

import discord

from dncore.abc import ObjectSerializer, ObjectSerializable, Cloneable, IGNORE_FRAME

__all__ = ["serializers", "DatetimeSerializer", "DatetimeDateSerializer", "DatetimeTimeSerializer", "EmbedType",
           "GuildId", "ChannelId", "MessageId", "RoleId", "Color", "Embed", "Emoji", "Reaction", "ActivitySetting"]

EmbedType = Literal['rich', 'image', 'video', 'gifv', 'article', 'link']


class DatetimeSerializer(ObjectSerializer):
    def check(self, clazz):
        return issubclass(clazz, datetime.datetime)

    def serialize(self, obj: datetime.datetime):
        return obj.replace(tzinfo=datetime.timezone.utc).isoformat()

    @classmethod
    def deserialize(cls, value):
        if isinstance(value, float):
            return datetime.datetime.utcfromtimestamp(value)  # bug fix

        return datetime.datetime.fromisoformat(value)


class DatetimeDateSerializer(ObjectSerializer):
    def check(self, clazz):
        return issubclass(clazz, datetime.date)

    def serialize(self, obj: datetime.date):
        return obj.isoformat()

    @classmethod
    def deserialize(cls, value):
        return datetime.date.fromisoformat(value)


class DatetimeTimeSerializer(ObjectSerializer):
    def check(self, clazz):
        return issubclass(clazz, datetime.time)

    def serialize(self, obj: datetime.time):
        return obj.replace(tzinfo=datetime.timezone.utc).isoformat()

    @classmethod
    def deserialize(cls, value):
        return datetime.time.fromisoformat(value)


class GuildId(ObjectSerializable, Cloneable):
    def __init__(self, guild_id: int = None):
        self.id = guild_id

    def serialize(self):
        return self.id

    @classmethod
    def deserialize(cls, value):
        return cls(value) if isinstance(value, int) else None

    def clone(self):
        return GuildId(guild_id=self.id)

    async def fetch(self):
        if self.id is None:
            raise ValueError("id is not set")
        from dncore.util.instance import get_core
        client = get_core().connected_client
        if client is None:
            raise RuntimeError("Client is not unavailable")
        return await client.fetch_guild(self.id)

    async def get(self):
        if self.id is None:
            return None
        try:
            return await self.fetch()
        except discord.HTTPException:
            pass


class ChannelId(ObjectSerializable, Cloneable):
    def __init__(self, channel_id: int = None):
        self.id = channel_id

    def serialize(self):
        return self.id

    @classmethod
    def deserialize(cls, value):
        return cls(value) if isinstance(value, int) else None

    def clone(self):
        return ChannelId(channel_id=self.id)

    async def fetch(self):
        if self.id is None:
            raise ValueError("id is not set")
        from dncore.util.instance import get_core
        client = get_core().connected_client
        if client is None:
            raise RuntimeError("Client is not unavailable")
        return await client.fetch_channel(self.id)

    async def get(self):
        if self.id is None:
            return None
        try:
            return await self.fetch()
        except discord.HTTPException:
            pass


class MessageId(ObjectSerializable, Cloneable):
    def __init__(self, message_id: int = None, channel_id: int = None):
        self.id = message_id
        self.channel_id = channel_id

    def serialize(self):
        return dict(mid=self.id, cid=self.channel_id)

    @classmethod
    def deserialize(cls, value):
        return cls(value.get("mid"), value.get("cid")) if isinstance(value, dict) else None

    def clone(self):
        return MessageId(self.id, self.channel_id)

    async def fetch(self):
        if self.id is None or self.channel_id is None:
            raise ValueError("id is not set")
        from dncore.util.instance import get_core
        client = get_core().connected_client
        if client is None:
            raise RuntimeError("Client is not unavailable")
        return await client.fetch_message(self.channel_id, self.id)

    async def get(self):
        if self.id is None or self.channel_id is None:
            return None
        try:
            return await self.fetch()
        except discord.HTTPException:
            pass


class RoleId(ObjectSerializable, Cloneable):
    def __init__(self, role_id: int = None, guild_id: int = None):
        self.id = role_id
        self.guild_id = guild_id

    def serialize(self):
        return dict(rid=self.id, gid=self.guild_id)

    @classmethod
    def deserialize(cls, value):
        return cls(value.get("rid"), value.get("gid")) if isinstance(value, dict) else None

    def clone(self):
        return RoleId(self.id, self.guild_id)

    async def fetch(self):
        if self.id is None or self.guild_id is None:
            raise ValueError("id is not set")
        from dncore.util.instance import get_core
        client = get_core().connected_client
        if client is None:
            raise RuntimeError("Client is not unavailable")
        guild = await client.fetch_guild(self.guild_id)
        role = guild.get_role(self.id)
        if role is None:
            await guild.fetch_roles()
            role = guild.get_role(self.id)
        return role

    async def get(self):
        if self.id is None or self.guild_id is None:
            return None
        try:
            return await self.fetch()
        except discord.HTTPException:
            pass


class Color(ObjectSerializable, Cloneable):
    def __init__(self, value: int = None, nullable=False):
        self.nullable = nullable
        self.default = None if nullable else value
        self.value = value

    def serialize(self):
        value = self.default if self.value is None else self.value
        if value is not None:
            return hex(value)

    @classmethod
    def deserialize(cls, value):
        if isinstance(value, int):
            return cls(value)
        elif isinstance(value, str):
            return cls(int(value, 16))

    def clone(self):
        return Color(self.value, nullable=self.nullable)

    @property
    def color(self):
        value = self.default if self.value is None else self.value
        if value is not None:
            return discord.Colour(value)


class Embed(ObjectSerializable, Cloneable, discord.Embed):
    def __init__(self, description: str = None, title: str = None, *,
                 colour: int | discord.Colour = None, type: EmbedType = 'rich',
                 url: Any = None, timestamp: datetime.datetime = None):

        discord.Embed.__init__(self, colour=colour, title=title, type=type, url=url,
                               description=description, timestamp=timestamp)

    def serialize(self, *, simple=True):
        serialized = self.to_dict()  # type: dict[str, Any]
        if serialized.get("type") == "rich":
            serialized.pop("type")
        if simple and len(serialized) == 1 and "description" in serialized:
            return self.description
        if "color" in serialized:
            serialized["color"] = Color(serialized["color"]).serialize()
        return serialized

    @classmethod
    def deserialize(cls, value):
        if isinstance(value, str):
            return cls(description=value)
        if isinstance(value, dict) and "color" in value:
            value = dict(value)
            value["color"] = Color.deserialize(value["color"]).value
        return cls.from_dict(value)

    def clone(self):
        return self.copy()

    @classmethod
    def info(cls, content: str | discord.Embed | None, title: str = None):
        if not isinstance(content, discord.Embed):
            embed = cls(description=content)
        else:
            embed = cls.from_dict(content.to_dict())

        if title:
            embed.title = title

        if embed.colour is None:
            from dncore.util.instance import get_core
            embed.colour = get_core().config.discord.embeds.color_info.color

        return embed

    @classmethod
    def warn(cls, content: str | discord.Embed | None, title: str = None):
        if not isinstance(content, discord.Embed):
            embed = cls(description=content)
        else:
            embed = cls.from_dict(content.to_dict())

        if title:
            embed.title = title

        if embed.colour is None:
            from dncore.util.instance import get_core
            embed.colour = get_core().config.discord.embeds.color_warn.color

        return embed

    @classmethod
    def error(cls, content: str | discord.Embed | None, title: str = None):
        if not isinstance(content, discord.Embed):
            embed = cls(description=content)
        else:
            embed = cls.from_dict(content.to_dict())

        if title:
            embed.title = title

        if embed.colour is None:
            from dncore.util.instance import get_core
            embed.colour = get_core().config.discord.embeds.color_error.color

        return embed

    @staticmethod
    def _format(m: str, values: dict[str, Any], log_name: str, *, is_url=False):
        if not m:
            return m

        rex = re.compile("^https?://.+")
        try:
            tmp = str(m).format_map(values)
            return tmp if not is_url or rex.match(tmp) else None
        except (KeyError, ValueError, AttributeError) as e:
            m2 = m.replace("\n", "\\n")
            log = getLogger(log_name)
            log.warning(f"テキストをフォーマットできませんでした: {m2!r}")
            log.warning(f"  理由: {type(e).__name__}: {e}")
            log.warning(f"  変数: {', '.join(values)}")
            if is_url and not rex.match(m):
                return None
            return m

    def format(self, args: dict[str, Any] | None):
        if not args and args is not None:
            return self.copy()

        f = inspect.currentframe()
        try:
            while f.f_back is not None:
                f = f.f_back
                n = f.f_globals["__name__"]
                if not n.startswith("dncore.abc") and not n.startswith("dncore.util"):
                    if f.f_locals.get("__ignore_frame") is not IGNORE_FRAME:
                        break

            if args is None:
                args = {k: str(v) for k, v in f.f_locals.items() if not k.startswith("_")}

            log = f.f_globals["__name__"]

        finally:
            del f

        embed = self.copy()

        if embed.title:
            embed.title = self._format(embed.title, args, log)

        if embed.url:
            embed.url = self._format(embed.url, args, log, is_url=True)

        if embed.description:
            embed.description = self._format(embed.description, args, log)

        if embed.footer:
            embed.set_footer(
                text=self._format(embed.footer.text, args, log),
                icon_url=self._format(embed.footer.icon_url, args, log, is_url=True)
            )

        if embed.author:
            embed.set_author(
                name=self._format(embed.author.name, args, log),
                url=self._format(embed.author.url, args, log, is_url=True),
                icon_url=self._format(embed.author.icon_url, args, log, is_url=True)
            )

        if embed.fields:
            fields = list(embed.fields)
            embed.clear_fields()
            for field in fields:
                embed.add_field(
                    name=self._format(field.name, args, log),
                    value=self._format(field.value, args, log),
                    inline=field.inline
                )

        if embed.image:
            fmt = self._format(embed.image.url, args, log, is_url=True)
            embed.set_image(url=fmt)

        if embed.thumbnail:
            embed.set_thumbnail(url=self._format(embed.thumbnail.url, args, log, is_url=True))

        return embed


class Emoji(ObjectSerializable, Cloneable, discord.PartialEmoji):
    def serialize(self, *, simple=True):
        serialized = self.to_dict()
        return serialized["name"] if simple and "name" in serialized and len(serialized) == 1 else serialized

    @classmethod
    def deserialize(cls, value):
        if value is None:
            return
        if isinstance(value, str):
            return cls(name=value)
        return cls.from_dict(value)

    def clone(self):
        return type(self).from_dict(self.to_dict())


class Reaction(ObjectSerializable, Cloneable):
    def __init__(self, reaction: Embed | Emoji | None):
        self.reaction = reaction

    def serialize(self):
        if isinstance(self.reaction, Embed):
            serialized = self.reaction.serialize()
            return serialized if isinstance(serialized, str) else {"reaction": "embed", **serialized}
        elif isinstance(self.reaction, Emoji):
            serialized = self.reaction.serialize(simple=False)
            return {"reaction": "emoji", **serialized}

    @classmethod
    def deserialize(cls, value):
        if isinstance(value, str):
            return cls(reaction=Embed.deserialize(value))
        elif isinstance(value, dict):
            reaction_type = value.pop("reaction", None)
            if reaction_type == "embed":
                return cls(reaction=Embed.deserialize(value))
            elif reaction_type == "emoji":
                return cls(reaction=Emoji.deserialize(value))
        return cls(reaction=None)

    def clone(self):
        return type(self)(reaction=self.reaction.clone() if self.reaction else None)


class ActivitySetting(ObjectSerializable, Cloneable):
    def __init__(self, status: str | discord.Status = "online", activity: str = None):
        self._status = str(status)
        self.activity = activity

    def clone(self):
        return ActivitySetting(self._status, self.activity)

    def __repr__(self):
        return f"<ActivityStatus status={self._status!r}, activity={self.activity!r}>"

    @property
    def status(self):
        try:
            return discord.Status(self._status)
        except ValueError:
            return discord.Status.online

    @status.setter
    def status(self, value: discord.Status):
        self._status = str(value)

    def serialize(self):
        return dict(status=self._status, activity=self.activity)

    @classmethod
    def deserialize(cls, value):
        if isinstance(value, dict):
            return cls(status=value.get("status"), activity=value.get("activity"))
        return None

    def create(self, priority: int):
        from dncore.discord.status import Activity
        return Activity(discord.Game(name=self.activity) if self.activity else None, priority, status=self.status)


def serializers():
    return DatetimeSerializer(), DatetimeTimeSerializer(), DatetimeDateSerializer(),
