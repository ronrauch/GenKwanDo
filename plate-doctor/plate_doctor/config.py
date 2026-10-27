"""Plate Doctor configuration. The ONLY place the credit line lives.

Change ATTRIBUTION here and the CLI --about, the web About panel and every generated run.json follow.
(README.md and LICENSE carry the same placeholder text because they cannot import this module.)
"""
APP_NAME = "Plate Doctor"
VERSION = "0.1.0"
YEAR = 2026

# TODO: credit line, decided at ship. One-line edit.
ATTRIBUTION = "TODO: credit line, decided at ship"

# Runtime defaults. Nothing here spends money: every network path is gated in submit.py.
RECIPE_NAME = "SECRETLAB-LTX25-CleanPlate-v001"      # lab workflow id (naming convention), not a credit line
HDR_RECIPE_NAME = "SECRETLAB-LTX23-HDR-ICLoRA-local-v001"


def about_text() -> str:
    return f"{APP_NAME}\n{ATTRIBUTION}\nv{VERSION} · {YEAR}"
