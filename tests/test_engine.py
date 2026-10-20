from pathlib import Path

from fileconverter.core import history
from fileconverter.core.base import BaseConverter, ConversionJob, ConversionOptions
from fileconverter.core.engine import (
    ConversionEngine,
    build_output_path,
    jobs_from_results_json,
)
from fileconverter.core.registry import _CONVERTERS, register


def test_same_stem_files_into_one_output_dir_do_not_collide(work):
    (work / "a").mkdir()
    (work / "b").mkdir()
    first, second = work / "a" / "photo.png", work / "b" / "photo.png"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    out = work / "out"
    reserved: set[Path] = set()
    p1 = build_output_path(first, "jpg", out, reserved=reserved)
    p2 = build_output_path(second, "jpg", out, reserved=reserved)
    assert p1 == out / "photo.jpg"
    assert p2 == out / "photo (1).jpg"


def test_never_overwrites_the_source(work):
    src = work / "data.csv"
    src.write_text("a\n1\n")
    path = build_output_path(src, "csv", overwrite_policy="overwrite")
    assert path == work / "data (1).csv"


def test_skip_and_overwrite_policies(work):
    src = work / "a.png"
    src.write_bytes(b"x")
    (work / "a.jpg").write_bytes(b"x")
    assert build_output_path(src, "jpg", overwrite_policy="skip") is None
    assert build_output_path(src, "jpg", overwrite_policy="overwrite") == work / "a.jpg"
    assert build_output_path(src, "jpg", overwrite_policy="rename") == work / "a (1).jpg"


def test_tar_names(work):
    src = work / "backup.tar.gz"
    src.write_bytes(b"x")
    assert build_output_path(src, "zip") == work / "backup.zip"
    zip_src = work / "photos.zip"
    zip_src.write_bytes(b"x")
    assert build_output_path(zip_src, "gz") == work / "photos.tar.gz"
    (work / "photos.tar.gz").write_bytes(b"x")
    assert build_output_path(zip_src, "gz") == work / "photos (1).tar.gz"
    assert build_output_path(zip_src, "folder") == work / "photos"


def test_retry_keeps_original_options(work):
    entries = [
        {
            "source": str(work / "a.png"),
            "output": None,
            "target_format": "jpg",
            "success": False,
            "options": {"quality": 55},
        },
        {"source": str(work / "b.png"), "target_format": "jpg", "success": True},
    ]
    jobs = jobs_from_results_json(entries)
    assert len(jobs) == 1
    assert jobs[0].options.get("quality") == 55


class _FlakyConverter(BaseConverter):
    """Writes half a file, then fails — like a crashing encoder."""

    name = "Flaky"
    input_formats = frozenset({"flaky"})
    output_formats = frozenset({"out"})

    def __init__(self):
        self.calls = 0

    def convert(self, job, progress_cb=None):
        self.calls += 1

        def _do():
            job.output_path.write_bytes(b"partial")
            raise RuntimeError("encoder crashed")

        return self._run_timed(job, _do)


def _with_converter(converter, fn):
    register(converter)
    try:
        return fn()
    finally:
        _CONVERTERS.remove(converter)


def test_failed_job_removes_partial_output_and_retries(work):
    src = work / "input.flaky"
    src.write_text("x")
    out = work / "input.out"
    converter = _FlakyConverter()
    engine = ConversionEngine(max_workers=1)

    def run():
        job = ConversionJob(src, out, "out")
        return engine.run_batch([job], max_retries=2, retry_delay=0)

    [result] = _with_converter(converter, run)
    assert not result.success
    assert "encoder crashed" in result.error
    assert converter.calls == 3
    assert not out.exists()  # no truncated file left behind
    entries = history.recent()
    assert len(entries) == 3 and not entries[0].success


def test_existing_output_is_not_deleted_on_failure(work):
    src = work / "input.flaky"
    src.write_text("x")
    out = work / "input.out"
    out.write_text("precious")
    engine = ConversionEngine(max_workers=1)
    [result] = _with_converter(
        _FlakyConverter(), lambda: engine.run_batch([ConversionJob(src, out, "out")])
    )
    assert not result.success
    assert out.exists()


def test_engine_passes_detected_format_to_converter(work):
    seen = {}

    class _Recorder(BaseConverter):
        name = "Recorder"
        input_formats = frozenset({"png"})
        output_formats = frozenset({"rec"})

        def convert(self, job, progress_cb=None):
            seen["src"] = job.src_format
            return self._run_timed(job, lambda: job.output_path.write_text("ok"))

    src = work / "no_extension"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    engine = ConversionEngine(max_workers=1)
    [result] = _with_converter(
        _Recorder(),
        lambda: engine.run_batch([ConversionJob(src, work / "x.rec", "rec")]),
    )
    assert result.success, result.error
    assert seen["src"] == "png"


def test_cancelled_jobs_are_not_retried(work):
    src = work / "input.flaky"
    src.write_text("x")
    converter = _FlakyConverter()
    engine = ConversionEngine(max_workers=1)
    job = ConversionJob(src, work / "input.out", "out", options=ConversionOptions())

    # Cancel before it starts: the job should finish as "Cancelled" and a
    # retry round must not start it again.
    engine._executor.submit(lambda: __import__("time").sleep(0.2))  # occupy the worker
    register(converter)
    try:
        futures = []
        original_submit = engine.submit

        def submit_and_cancel(j, *a, **kw):
            f = original_submit(j, *a, **kw)
            engine.cancel(j.job_id)
            futures.append(f)
            return f

        engine.submit = submit_and_cancel  # type: ignore[method-assign]
        [result] = engine.run_batch([job], max_retries=3, retry_delay=0)
    finally:
        _CONVERTERS.remove(converter)
    assert result.message == "Cancelled"
    assert converter.calls == 0
    assert len(futures) == 1
