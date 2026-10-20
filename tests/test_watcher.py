import time

from fileconverter.core.engine import ConversionEngine
from fileconverter.core.watcher import FolderWatcher


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_watcher_converts_new_files_and_ignores_temp_files(work):
    (work / "before.json").write_text('{"old": true}')  # existing: not converted
    engine = ConversionEngine(max_workers=1)
    seen = []
    watcher = FolderWatcher(
        work, "yaml", engine, poll_interval=0.05, on_new_job=seen.append
    )
    watcher.start()
    try:
        (work / "new.json").write_text('{"x": 1}')
        (work / "download.json.part").write_text("{")
        (work / ".hidden.json").write_text("{}")
        (work / "notes.unknownext").write_text("?")
        assert _wait_for(lambda: (work / "new.yaml").exists())
        time.sleep(0.3)
    finally:
        watcher.stop()
        engine.shutdown(wait=True)
    assert [p.name for p in seen] == ["new.json"]
    assert not (work / "before.yaml").exists()
    assert (work / "new.yaml").read_text().strip() == "x: 1"
