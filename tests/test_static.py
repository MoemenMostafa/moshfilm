from pathlib import Path

STATIC = Path(__file__).parent.parent / "src" / "moshfilm" / "static"


def test_built_ui_present():
    assert (STATIC / "index.html").is_file()
    assert (STATIC / "render.html").is_file()
