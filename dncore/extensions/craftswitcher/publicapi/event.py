from typing import TYPE_CHECKING

from dncore.event import Event

if TYPE_CHECKING:
    from .abc import WebSocketClient

__all__ = [
    "WebSocketClientConnectEvent",
    "WebSocketClientDisconnectEvent",
]


class WebSocketClientConnectEvent(Event):
    def __init__(self, client: "WebSocketClient"):
        self.client = client


class WebSocketClientDisconnectEvent(Event):
    def __init__(self, client: "WebSocketClient"):
        self.client = client
