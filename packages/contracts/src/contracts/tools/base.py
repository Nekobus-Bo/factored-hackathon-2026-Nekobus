"""Base classes for tool input and output contracts."""

from pydantic import BaseModel, ConfigDict


class BaseToolModel(BaseModel):
    """Base model enforcing immutability and disallowing extraneous unmodeled fields."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class BaseToolInput(BaseToolModel):
    """Base model for all tool input schemas.

    Strictly forbids extra fields to protect against IDOR and prompt injection leakage.
    Allows date fields to parse ISO strings, while numeric/boolean fields use StrictInt/StrictBool.
    """

    pass


class BaseToolOutput(BaseToolModel):
    """Base model for all tool output schemas."""

    pass
