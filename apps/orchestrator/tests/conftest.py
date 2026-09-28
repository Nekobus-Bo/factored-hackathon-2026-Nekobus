"""Test environment: the app requires SESSION_SECRET at startup."""

import os

os.environ.setdefault("SESSION_SECRET", "test-only-session-secret")
