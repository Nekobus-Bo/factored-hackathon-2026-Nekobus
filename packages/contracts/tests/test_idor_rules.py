"""Tests enforcing ADR-0004 IDOR prevention rules across all tool input models."""

import pytest
from pydantic import ValidationError

from contracts.tools import TOOL_CATALOG
from contracts.tools.base import BaseToolInput

FORBIDDEN_KEYWORDS = [
    "customer_id",
    "account_id",
    "owner",
    "holder",
    "customer",
]


def test_no_input_model_has_forbidden_idor_fields():
    """HARD RULE (ADR-0004 IDOR):

    Asserts no input model has a field named like customer_id/account_id/owner/holder.
    The holder is pinned in the session server-side; the model must never choose or pass
    customer/account ownership parameters.
    """
    assert len(TOOL_CATALOG) == 10, "Expected 10 registered tools in catalog"

    violations: list[str] = []

    for tool_name, definition in TOOL_CATALOG.items():
        input_cls = definition.input_model
        assert issubclass(input_cls, BaseToolInput), f"{tool_name} input must inherit BaseToolInput"

        for field_name in input_cls.model_fields.keys():
            normalized = field_name.lower()
            for kw in FORBIDDEN_KEYWORDS:
                if kw in normalized:
                    violations.append(
                        f"Tool '{tool_name}' input model '{input_cls.__name__}' "
                        f"contains forbidden IDOR field '{field_name}' matching keyword '{kw}'"
                    )

    assert not violations, "\n".join(violations)


def test_all_input_models_forbid_extra_fields():
    """Assert all tool input models forbid extra fields to prevent injection."""
    for tool_name, definition in TOOL_CATALOG.items():
        input_cls = definition.input_model
        assert input_cls.model_config.get("extra") == "forbid", (
            f"Tool '{tool_name}' input model '{input_cls.__name__}' must have extra='forbid'"
        )


@pytest.mark.parametrize(
    "tool_name",
    list(TOOL_CATALOG.keys()),
)
def test_all_input_models_reject_injected_customer_id(tool_name: str):
    """Attempting to inject customer_id, account_id, or owner into any tool input must fail."""
    input_cls = TOOL_CATALOG[tool_name].input_model

    for injected_field in ["customer_id", "account_id", "owner", "holder", "customerId"]:
        with pytest.raises(ValidationError):
            input_cls(**{injected_field: "injected-id-12345"})
