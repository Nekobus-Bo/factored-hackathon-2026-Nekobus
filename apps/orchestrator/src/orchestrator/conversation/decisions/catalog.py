"""Which decision points the encoder serves, and what to ask it for.

`POST /v1/analyze` answers 422 to a decision point id it does not know, and the
same call carries the PII spans the masking unions in: naming one wrong id would
lose both. So the orchestrator asks only for ids that `GET /v1/decision-points`
lists (in legacy seed mode, before an artifact exists, that is `turn_intent`
alone), and a DP request can never be what breaks masking.

The listing is cached and refreshed on a timer. A failed refresh keeps the last
good listing and is not retried for a while, so a down encoder costs one extra
request per interval, not one per turn.
"""

import logging
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from contracts import DecisionPointsResponse

from orchestrator.conversation.decisions.config import DecisionPointConfig
from orchestrator.conversation.decisions.records import UnavailableReason
from orchestrator.encoder_client import EncoderUnavailableError

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 300.0
RETRY_SECONDS = 15.0


@dataclass(frozen=True)
class RequestPlan:
    """What one analyze call asks for, and which active DPs it will not ask for."""

    # The ids to name; None names nothing (the service picks its default set).
    ids: list[str] | None = None
    # Active DPs left out, with why. They are recorded as unavailable.
    blocked: dict[str, UnavailableReason] = field(default_factory=dict)

    @property
    def mismatched(self) -> list[str]:
        return [dp for dp, why in self.blocked.items() if why == "config_mismatch"]


def plan_request(
    active: Sequence[DecisionPointConfig], served: DecisionPointsResponse | None
) -> RequestPlan:
    """Ask for the active DPs the encoder serves with the labels the effects need."""
    if not active:
        return RequestPlan()
    if served is None:
        # The listing is unknown. Naming nothing cannot 422; a DP the default set
        # leaves out is recorded as not returned.
        return RequestPlan()
    offered = {info.id: set(info.labels) for info in served.decision_points}
    ids: list[str] = []
    blocked: dict[str, UnavailableReason] = {}
    for dp in active:
        labels = offered.get(dp.id)
        if labels is None:
            blocked[dp.id] = "not_served"
        elif not dp.required_labels() <= labels:
            blocked[dp.id] = "config_mismatch"
        else:
            ids.append(dp.id)
    return RequestPlan(ids=ids, blocked=blocked)


class ServedCatalog:
    """The cached `GET /v1/decision-points` listing."""

    def __init__(
        self,
        refresh_seconds: float = REFRESH_SECONDS,
        retry_seconds: float = RETRY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.refresh_seconds = refresh_seconds
        self.retry_seconds = retry_seconds
        self._clock = clock
        self._listing: DecisionPointsResponse | None = None
        self._fetched_at = -math.inf
        self._failed_at: float | None = None

    async def get(self, source: Any) -> DecisionPointsResponse | None:
        """The listing, fetched when due; the last good one if the fetch fails.

        `source` is anything with `async decision_points()` (the encoder client).
        None means nothing is known yet.
        """
        now = self._clock()
        if self._listing is not None and now - self._fetched_at < self.refresh_seconds:
            return self._listing
        if self._failed_at is not None and now - self._failed_at < self.retry_seconds:
            return self._listing
        fetch = getattr(source, "decision_points", None)
        if fetch is None:
            return self._listing
        try:
            listing: DecisionPointsResponse = await fetch()
        except Exception as exc:
            # Only the type: the message of an unexpected error could quote a body.
            logger.warning(
                "Decision point listing unavailable (%s)",
                str(exc)
                if isinstance(exc, EncoderUnavailableError)
                else type(exc).__name__,
            )
            self._failed_at = now
            return self._listing
        self._listing = listing
        self._fetched_at = now
        self._failed_at = None
        return listing

    def invalidate(self) -> None:
        """Fetch again on the next turn (the encoder said an id was unknown)."""
        self._fetched_at = -math.inf
        self._failed_at = None
