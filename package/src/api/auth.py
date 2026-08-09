import os
from dataclasses import dataclass


@dataclass
class User:
    id: str
    key: str = ""


def _local_authorizer():
    """FastAPI dependency that accepts any request locally.

    Returns a User with id from the X-User-Id header if present,
    otherwise a fixed development user. No key validation.
    """
    from fastapi import Depends, Header

    async def _auth(
        x_api_key: str = Header(default=""),
        x_user_id: str = Header(default="local-user"),
    ):
        return User(id=x_user_id, key=x_api_key)

    return _auth


def get_authorizer():
    """Return the authorizer for the current environment.

    Locally: returns a FastAPI dependency that accepts any request and
    returns a User with id from X-User-Id header or 'local-user'.
    """
    return _local_authorizer()


apikey_auth = get_authorizer()
