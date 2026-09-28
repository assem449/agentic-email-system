"""Encrypt-at-rest helpers for participant OAuth tokens.

Tokens are the only thing this study deployment persists that grants
access to a real account, so they're the one thing worth a real crypto
primitive rather than "it's in a gitignored file." Everything else
(email content) is never written to disk at all — see NOTES.md.
"""

from cryptography.fernet import Fernet
from app.config import TOKEN_ENCRYPTION_KEY

_fernet = Fernet(TOKEN_ENCRYPTION_KEY.encode())


def encrypt(plaintext: str) -> bytes:
    return _fernet.encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    return _fernet.decrypt(ciphertext).decode("utf-8")
