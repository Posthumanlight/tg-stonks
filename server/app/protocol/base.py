from pydantic import BaseModel, ConfigDict


class ProtocolModel(BaseModel):
    """Base for every protocol message: immutable, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")
