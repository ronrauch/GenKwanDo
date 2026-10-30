"""The repo must be shippable as open source: no personal paths, no private names, no leaked ids."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
TEXT = {".py", ".md", ".json", ".html", ".txt", ".toml", ".cfg", ".gitignore"}


def repo_text_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.parts) & SKIP_DIRS) and (p.suffix in TEXT or p.name in {"LICENSE", ".gitignore"}):
            if "tests" in p.parts and p.name == "test_scrub.py":
                continue  # this file names the strings it forbids
            yield p


@pytest.mark.parametrize("needle", ["/Users/", "ronrauch", "Ron Rauch", "MIKE", "JIM2", "Beatles", "Lucy", "Built by The Secret Lab"])
def test_no_forbidden_string_anywhere(needle):
    hits = [str(p.relative_to(ROOT)) for p in repo_text_files() if needle in p.read_text(errors="ignore")]
    assert hits == [], f"{needle!r} found in {hits}"


def test_no_content_hash_filenames_from_a_private_graph():
    for p in repo_text_files():
        assert not re.search(r"\b[0-9a-f]{64}\.(png|mp3|wav|mp4)\b", p.read_text(errors="ignore")), p


def test_graph_template_is_scrubbed():
    t = (ROOT / "cutting_room_lite" / "graphs" / "h3_ref2va_window.template.json").read_text()
    assert "COVER.png" in t and "WINDOW_AUDIO.wav" in t and "cutting-room-lite/window" in t


def test_the_attribution_lives_in_one_constant_and_the_readme_has_a_todo():
    src = (ROOT / "cutting_room_lite" / "__init__.py").read_text()
    assert src.count("ATTRIBUTION =") == 1 and "TODO: credit line" in src
    readme = (ROOT / "README.md").read_text()
    assert "TODO: credit line" in readme and "EXAMPLE OUTPUT" in readme


def test_license_is_mit():
    assert "MIT License" in (ROOT / "LICENSE").read_text()
