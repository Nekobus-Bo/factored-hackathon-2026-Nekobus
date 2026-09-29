"""banking-core admin config API, used by the runner to set up scenarios.

Served by apps/banking-core/src/banking_core/api/routes_admin.py, and mounted only
when ADMIN_API_ENABLED=true there:
  GET  /v1/admin/policy-config        -> {"amount_mode": str, "thresholds_minor": {...},
                                          "version": int}
  PUT  /v1/admin/policy-config        <- {"amount_mode": str, "thresholds_minor": {...}}
  POST /v1/admin/demo/reset-fixtures  -> 200 (demo cards back to seed state, and the
                                         fixture customers' cross-session attempt limits
                                         forgotten); 403 when APP_ENV=production
                                         without DEMO_RESET_ENABLED
  Auth: "Authorization: Bearer <EVAL_ADMIN_TOKEN>" (banking-core's ADMIN_API_TOKEN).
  Every write is audited there.
When it is not mounted or unreachable, availability is False and setup-dependent
scenarios are not run.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from evalrunner.systems.evidence import PolicySnapshot


class AdminError(RuntimeError):
    """The admin API answered, but refused or failed."""


class AdminApi(Protocol):
    def available(self) -> bool: ...

    def policy(self) -> PolicySnapshot: ...

    def put_policy(self, policy: PolicySnapshot) -> None: ...

    def reset_fixtures(self) -> None: ...


class HttpAdminApi:
    def __init__(self, base_url: str, token: str | None, http: httpx.Client) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = http

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self.http.request(
            method, f"{self.base_url}{path}", headers=self.headers, **kwargs
        )

    def available(self) -> bool:
        try:
            response = self._call("GET", "/v1/admin/policy-config")
        except httpx.RequestError:
            return False
        if response.status_code in (401, 403):
            raise AdminError("admin API rejected the token (EVAL_ADMIN_TOKEN)")
        return response.status_code == 200

    def policy(self) -> PolicySnapshot:
        response = self._call("GET", "/v1/admin/policy-config")
        if response.status_code != 200:
            raise AdminError(f"policy read failed: HTTP {response.status_code}")
        body = response.json()
        return PolicySnapshot(
            amount_mode=str(body["amount_mode"]),
            thresholds_minor=dict(body.get("thresholds_minor") or {}),
        )

    def put_policy(self, policy: PolicySnapshot) -> None:
        response = self._call(
            "PUT",
            "/v1/admin/policy-config",
            json={
                "amount_mode": policy.amount_mode,
                "thresholds_minor": policy.thresholds_minor,
            },
        )
        if response.status_code not in (200, 204):
            raise AdminError(f"policy update failed: HTTP {response.status_code}")

    def reset_fixtures(self) -> None:
        response = self._call("POST", "/v1/admin/demo/reset-fixtures")
        if response.status_code not in (200, 204):
            raise AdminError(f"fixture reset failed: HTTP {response.status_code}")
