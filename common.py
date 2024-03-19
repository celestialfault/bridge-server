from typing import TypedDict


class Message(TypedDict):
    author: str
    message: str
    nonce: str
