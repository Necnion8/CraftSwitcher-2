import discord

from dncore.event import Event

__all__ = ["EVENTS", "DiscordGenericEvent", "ConnectEvent", "DisconnectEvent", "ReadyEvent", "ResumedEvent",
           "MessageEvent", "MessageDeleteEvent", "MessageEditEvent",
           "ReactionAddEvent", "ReactionRemoveEvent", "ReactionClearEvent",
           "MemberJoinEvent", "MemberRemoveEvent", "MemberUpdateEvent",
           "VoiceStateUpdateEvent",
           ]


class DiscordGenericEvent(Event):
    def __init__(self, event_name: str, /, *args, **kwargs):
        self.event = event_name
        self.args = args
        self.kwargs = kwargs


class ConnectEvent(Event):
    pass


class DisconnectEvent(Event):
    pass


class ReadyEvent(Event):
    pass


class ResumedEvent(Event):
    pass


class _MessageEvent(object):
    def __init__(self, message: discord.Message):
        self.message = message
        self.author = message.author  # type: discord.User | discord.ClientUser | discord.Member
        self.content = message.content  # type: str
        self.channel = message.channel  # type: discord.TextChannel | discord.DMChannel | discord.GroupChannel
        self.guild = message.guild  # type: discord.Guild | None


class MessageEvent(Event, _MessageEvent):
    pass


class MessageDeleteEvent(Event, _MessageEvent):
    pass


class MessageEditEvent(Event):
    def __init__(self, before: discord.Message, after: discord.Message):
        self.before = before
        self.after = after


class _ReactionEvent(object):
    def __init__(self, reaction: discord.Reaction, user: discord.Member | discord.User):
        self.reaction = reaction
        self.user = user


class ReactionAddEvent(Event, _ReactionEvent):
    pass


class ReactionRemoveEvent(Event, _ReactionEvent):
    pass


class ReactionClearEvent(Event):
    def __init__(self, message: discord.Message, reactions: discord.Reaction):
        self.message = message
        self.reactions = reactions


class _MemberEvent(object):
    def __init__(self, member: discord.Member):
        self.member = member


class MemberJoinEvent(Event, _MemberEvent):
    pass


class MemberRemoveEvent(Event, _MemberEvent):
    pass


class MemberUpdateEvent(Event):
    def __init__(self, before: discord.Member, after: discord.Member):
        self.before = before
        self.after = after


class VoiceStateUpdateEvent(Event):
    def __init__(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        self.member = member
        self.before = before
        self.after = after


EVENTS = {
    "connect": ConnectEvent,
    "disconnect": DisconnectEvent,
    "ready": ReadyEvent,
    "resumed": ResumedEvent,
    "message": MessageEvent,
    "message_delete": MessageDeleteEvent,
    "message_edit": MessageEditEvent,
    "reaction_add": ReactionAddEvent,
    "reaction_remove": ReactionRemoveEvent,
    "reaction_clear": ReactionClearEvent,
    "member_join": MemberJoinEvent,
    "member_remove": MemberRemoveEvent,
    "member_update": MemberUpdateEvent,
    "voice_state_update": VoiceStateUpdateEvent,
}
