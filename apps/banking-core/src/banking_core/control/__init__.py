"""Control package for banking-core.

Implements the deterministic decision boundary:
- Verification FSM (ADR-0003 Appendix A)
- Session state pinning and Redis store (ADR-0004)
- Policy engine with validated config (ADR-0002)
- Authorizer with non-configurable code floor
"""

from banking_core.control.authorize import Authorizer, authorize
from banking_core.control.config import (
    ControlConfigRepository,
    DatabaseControlConfigRepository,
    InMemoryControlConfigRepository,
    get_control_config_repository,
)
from banking_core.control.fsm import (
    FSMError,
    InvalidFSMTransitionError,
    VerificationFSM,
)
from banking_core.control.loader import load_policy_config, save_policy_config
from banking_core.control.policy import Decision, PolicyConfig, PolicyEngine
from banking_core.control.session import (
    RedisSessionStore,
    SessionState,
    validate_no_holder_tampering,
)

__all__ = [
    "Authorizer",
    "ControlConfigRepository",
    "DatabaseControlConfigRepository",
    "Decision",
    "FSMError",
    "InMemoryControlConfigRepository",
    "InvalidFSMTransitionError",
    "PolicyConfig",
    "PolicyEngine",
    "RedisSessionStore",
    "SessionState",
    "VerificationFSM",
    "authorize",
    "get_control_config_repository",
    "load_policy_config",
    "save_policy_config",
    "validate_no_holder_tampering",
]
