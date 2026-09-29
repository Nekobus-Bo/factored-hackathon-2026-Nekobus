"""The harness must import without loading PyTorch: the decision-points task never
needs it, and a machine that cannot install it must still calibrate."""

from __future__ import annotations

import subprocess
import sys
import textwrap

# Run in a fresh interpreter, where nothing has imported a heavy library yet. Where
# PyTorch is installed (CI), the assertion fails if an import stops being lazy;
# where it is not, the harness importing at all proves the same.
_PROBE = textwrap.dedent(
    """
    import sys

    import calibrate
    import calibrate.runner
    from encoder.registry import build  # noqa: F401

    heavy = {"torch", "sentence_transformers", "gliner", "gliner2", "transformers"}
    loaded = sorted(name for name in sys.modules if name.split(".")[0] in heavy)
    assert not loaded, loaded
    print("ok")
    """
)


def test_harness_imports_without_loading_pytorch() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
