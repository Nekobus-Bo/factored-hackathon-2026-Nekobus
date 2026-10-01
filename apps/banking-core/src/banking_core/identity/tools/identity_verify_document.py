"""Implementation of identity.verify_document tool in banking-core.

Simulated provider for document biometric verification (ADR-0007).
Takes opaque asset references, never raw biometric files or customer IDs.
Never sufficient alone to authorize actions: it reports a decision and never
moves the verification state.

The simulated provider answers deterministically from the opaque
``document_front_ref``, so a test scenario picks the outcome by naming the asset:

- ``sim-approve-*``: APPROVED, high score (LIVENESS_PASSED, DOCUMENT_AUTHENTIC)
- ``sim-reject-*``: REJECTED, low score (DOCUMENT_NOT_AUTHENTIC)
- anything else: MANUAL_REVIEW_REQUIRED. There is no provider result for an
  unknown asset, so a human decides; an unrecognized ref is never approved.

``document_back_ref`` and ``document_type`` are not evaluated.
"""

from contracts.tools.identity_verify_document import (
    DocumentDecision,
    IdentityVerifyDocumentInput,
    IdentityVerifyDocumentOutput,
)

from banking_core.control.session import SessionState

SIMULATED_APPROVE_PREFIX = "sim-approve-"
SIMULATED_REJECT_PREFIX = "sim-reject-"


def execute_identity_verify_document(
    args: IdentityVerifyDocumentInput,
    session: SessionState,
) -> IdentityVerifyDocumentOutput:
    """Execute simulated identity document verification.

    Reads the session for symmetry with the other tools but never changes it.
    """
    ref = args.document_front_ref
    if ref.startswith(SIMULATED_APPROVE_PREFIX):
        return IdentityVerifyDocumentOutput(
            decision=DocumentDecision.APPROVED,
            score=0.98,
            reasons=["LIVENESS_PASSED", "DOCUMENT_AUTHENTIC"],
        )
    if ref.startswith(SIMULATED_REJECT_PREFIX):
        return IdentityVerifyDocumentOutput(
            decision=DocumentDecision.REJECTED,
            score=0.05,
            reasons=["DOCUMENT_NOT_AUTHENTIC"],
        )
    return IdentityVerifyDocumentOutput(
        decision=DocumentDecision.MANUAL_REVIEW_REQUIRED,
        score=0.0,
        reasons=["NO_PROVIDER_RESULT"],
    )
