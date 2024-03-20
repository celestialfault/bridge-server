from typing import TypedDict


class Message(TypedDict):
    system: bool  # = False
    pings: bool  # = True
    author: str
    message: str
    nonce: str
