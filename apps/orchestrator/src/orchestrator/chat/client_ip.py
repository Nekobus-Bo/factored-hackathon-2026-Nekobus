"""Which address a request is limited by.

By default the address is the transport peer, request.client.host: nothing a
client sends can change it. X-Forwarded-For is honored only when
TRUSTED_PROXY_HOPS says how many reverse proxies stand in front of the
orchestrator; then that many entries are stripped from the right, where the
trusted proxies wrote them, and the entry before them is the client. Anything
further left was supplied by the client and is ignored, so a forged header
cannot pick the bucket.

A header that does not reach that far (fewer entries than trusted hops) or whose
entry is not an address falls back to the peer: the stricter, shared bucket.
IPv6 clients are grouped by /64, the smallest block a single subscriber holds,
so rotating inside one block does not evade the limit.
"""

import ipaddress
from collections.abc import Sequence

from fastapi import Request

UNKNOWN_CLIENT = "unknown"
_IPV6_GROUP_PREFIX = 64


def _normalize(host: str) -> str:
    """Canonical text of an address, or the raw text when it is not one."""
    try:
        address = ipaddress.ip_address(host.strip())
    except ValueError:
        return host.strip() or UNKNOWN_CLIENT
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        network = ipaddress.ip_network(f"{address}/{_IPV6_GROUP_PREFIX}", strict=False)
        return str(network)
    return str(address)


def _is_address(text: str) -> bool:
    try:
        ipaddress.ip_address(text.strip())
    except ValueError:
        return False
    return True


def resolve_client_ip(
    peer: str | None,
    forwarded_for: Sequence[str],
    trusted_proxy_hops: int,
) -> str:
    """The address to limit by: peer, or the client a trusted proxy chain saw."""
    if trusted_proxy_hops <= 0 or not peer:
        return _normalize(peer) if peer else UNKNOWN_CLIENT
    entries = [
        entry.strip()
        for header in forwarded_for
        for entry in header.split(",")
        if entry.strip()
    ]
    chain = [*entries, peer]
    index = len(chain) - 1 - trusted_proxy_hops
    if index < 0 or not _is_address(chain[index]):
        return _normalize(peer)
    return _normalize(chain[index])


def client_ip(request: Request, trusted_proxy_hops: int) -> str:
    """resolve_client_ip for a request."""
    peer = request.client.host if request.client else None
    return resolve_client_ip(
        peer, request.headers.getlist("x-forwarded-for"), trusted_proxy_hops
    )
