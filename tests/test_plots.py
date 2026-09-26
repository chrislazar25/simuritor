"""README charts render from the committed sweep results."""

from pathlib import Path

from scripts import plots


def test_both_charts_render_from_the_sweep_csv(tmp_path: Path) -> None:
    plots.main(["--out", str(tmp_path)])
    for name in ("safe-contract.png", "backup-vs-promise.png"):
        assert (tmp_path / name).read_bytes().startswith(b"\x89PNG")
