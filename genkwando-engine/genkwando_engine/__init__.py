"""Cutting Room Lite: album cover + song slice -> music video, with MiniMax H3 on ComfyUI."""

VERSION = "0.1.0"
YEAR = 2026

# The ONE place the credit line lives. The README, the UI footer and `--about` all read it from here
# (README carries a TODO placeholder instead). Decided at ship; changing it is a one-line edit.
ATTRIBUTION = "TODO: credit line, decided at ship"


def about() -> str:
    """The attribution block printed by `--about` and shown in the UI footer."""
    return f"Cutting Room Lite\n{ATTRIBUTION}\nv{VERSION} · {YEAR}\nMIT licence"
