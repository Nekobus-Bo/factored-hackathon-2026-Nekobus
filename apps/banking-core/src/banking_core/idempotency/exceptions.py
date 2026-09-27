"""Idempotency exceptions for banking-core."""


class IdempotencyError(Exception):
    """Base exception for idempotency store errors."""

    pass


class InvalidIdempotencyKeyError(IdempotencyError, ValueError):
    """Raised when an idempotency key does not match the required regex pattern."""

    def __init__(self, key: str, message: str | None = None) -> None:
        self.key = key
        super().__init__(
            message
            or f"Invalid idempotency key '{key}'. Must match ^[A-Za-z0-9._:-]{{8,128}}$"
        )


class IdempotencyConflictError(IdempotencyError):
    """Raised when an idempotency key is reused with different request arguments."""

    def __init__(
        self,
        key: str,
        tool: str,
        stored_request_hash: str,
        current_request_hash: str,
        reason_code: str = "INVALID_ARGUMENTS",
    ) -> None:
        self.key = key
        self.tool = tool
        self.stored_request_hash = stored_request_hash
        self.current_request_hash = current_request_hash
        self.reason_code = reason_code
        super().__init__(
            f"Idempotency conflict: key '{key}' was previously used for tool '{tool}' "
            f"with request_hash '{stored_request_hash}', got '{current_request_hash}'."
        )
