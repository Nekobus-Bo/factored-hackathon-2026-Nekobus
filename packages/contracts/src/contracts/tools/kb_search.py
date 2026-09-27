"""Contract for kb.search tool."""

from pydantic import Field, StrictInt

from contracts.tools.base import BaseToolInput, BaseToolModel, BaseToolOutput


class KbSearchInput(BaseToolInput):
    """Input payload for searching public knowledge base.

    Contains public FAQ / policy queries only; no customer PII.
    Permitted in every verification state.
    """

    query: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Search query string",
    )
    locale: str = Field(
        default="es",
        min_length=2,
        max_length=10,
        pattern=r"^[a-z]{2}(-[A-Z]{2})?$",
        description="Locale for search results (e.g. es, pt, en)",
    )
    limit: StrictInt = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of snippets to retrieve (1-20)",
    )


class KbSearchResultItem(BaseToolModel):
    """Knowledge base article snippet."""

    article_id: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Article identifier",
    )
    title: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Article title",
    )
    snippet: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Relevant text excerpt",
    )
    category: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Knowledge base topic category",
    )
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Relevance confidence score",
    )


class KbSearchOutput(BaseToolOutput):
    """Knowledge base search response."""

    results: list[KbSearchResultItem] = Field(
        default_factory=list,
        description="Ranked list of matching knowledge snippets",
    )
