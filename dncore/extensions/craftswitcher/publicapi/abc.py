from fastapi import WebSocket

__all__ = [
    "WebSocketClient",
]


class WebSocketClient(object):
    _id = 0

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.id = WebSocketClient._id
        WebSocketClient._id += 1
