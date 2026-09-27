"""CLI entrypoint to verify the audit log hash chain."""

import sys

from banking_core.audit.service import verify_chain
from banking_core.db.session import get_session_maker


def main() -> None:
    """Execute hash chain verification and exit with appropriate status code."""
    session_maker = get_session_maker()
    with session_maker() as session:
        is_valid, count, head_hash, broken_id, error_msg = verify_chain(session)

    if is_valid:
        print(
            f"OK: verified {count} entries in audit log hash chain "
            f"(head_hash={head_hash})"
        )
        sys.exit(0)
    else:
        print(f"FAILED: broken link at entry id={broken_id}: {error_msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
