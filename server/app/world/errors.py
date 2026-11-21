class GenerationFailed(Exception):
    """A generation attempt broke an invariant (retried) or all attempts failed."""


class UnknownObject(LookupError):
    """A path or index that does not exist in the generated world."""
