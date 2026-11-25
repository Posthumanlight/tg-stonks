"""Static JSON payloads built once per process and served with a strong ETag
(`Cache-Control: no-cache`: the browser revalidates for free and gets a 304)."""

import hashlib
from dataclasses import dataclass

from fastapi import Request, Response
from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class StaticJson:
    body: bytes  # the serialized model
    etag: str  # quoted strong ETag

    @classmethod
    def of(cls, model: BaseModel) -> "StaticJson":
        body = model.model_dump_json().encode()
        return cls(body=body, etag=f'"{hashlib.sha256(body).hexdigest()}"')


def respond(request: Request, cached: StaticJson) -> Response:
    headers = {"ETag": cached.etag, "Cache-Control": "no-cache"}
    if cached.etag in _etags(request.headers.get("if-none-match")):
        return Response(status_code=304, headers=headers)
    return Response(cached.body, media_type="application/json", headers=headers)


def _etags(header: str | None) -> set[str]:
    if not header:
        return set()
    return {tag.strip().removeprefix("W/") for tag in header.split(",")}
