import kaspion.paths as paths


def test_data_dir_honors_override(monkeypatch, tmp_path):
    monkeypatch.setenv("KASPION_DATA_DIR", str(tmp_path))
    assert paths.data_dir() == tmp_path
    assert paths.db_path() == tmp_path / "finance.duckdb"
    assert paths.report_path() == tmp_path / "dashboard.html"


def test_data_dir_is_outside_the_source_tree(monkeypatch):
    monkeypatch.delenv("KASPION_DATA_DIR", raising=False)
    repo = paths.Path(paths.__file__).resolve().parents[1]
    assert repo not in paths.data_dir().resolve().parents


def test_data_dir_creates_nothing(monkeypatch, tmp_path):
    target = tmp_path / "not-yet"
    monkeypatch.setenv("KASPION_DATA_DIR", str(target))
    paths.data_dir()
    assert not target.exists()      # pure function — callers mkdir
