"""Network check of the Cloud Run environment (ADR-0015), run as the netcheck job.

The job runs in the edge zone (the pb-edge tag). NETCHECK_BLOCKED lists the core data
addresses (Cloud SQL, redis-core) as host:port, comma separated: none may accept a
TCP connection. NETCHECK_ALLOWED lists redis-edge, behind the same peering: it must
accept one, so a blocked address that is merely wrong cannot pass as blocked. Opens
and closes sockets only, sends nothing. Exits non-zero, naming the address, when
either does not hold.
"""

import os
import socket
import sys

TIMEOUT_SECONDS = float(os.environ.get("NETCHECK_TIMEOUT_SECONDS", "5"))


def addresses(name: str) -> list[tuple[str, int]]:
    result = []
    for item in os.environ.get(name, "").split(","):
        if item.strip():
            host, _, port = item.strip().rpartition(":")
            result.append((host, int(port)))
    return result


def connects(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def main() -> int:
    blocked, allowed = addresses("NETCHECK_BLOCKED"), addresses("NETCHECK_ALLOWED")
    if not blocked or not allowed:
        print("netcheck: NETCHECK_BLOCKED and NETCHECK_ALLOWED are both required")
        return 2
    failed = False
    for host, port in blocked:
        if connects(host, port):
            print(f"✗ {host}:{port} accepted a connection; it must be blocked")
            failed = True
        else:
            print(f"✓ {host}:{port} blocked from the edge zone")
    for host, port in allowed:
        if connects(host, port):
            print(f"✓ {host}:{port} reachable from the edge zone")
        else:
            print(f"✗ {host}:{port} unreachable, so the check proves nothing")
            failed = True
    print("netcheck: FAILED" if failed else "netcheck: OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
