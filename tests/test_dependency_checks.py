import builtins

from fileconverter.core.registry import all_converters, find_converter


def _break_cairosvg(monkeypatch):
    """Simulate Windows with cairosvg installed but no native Cairo DLL:
    importing it raises OSError, not ImportError."""

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "cairosvg" or name.startswith("cairosvg."):
            raise OSError('no library called "cairo-2" was found')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_missing_native_cairo_is_reported_not_raised(monkeypatch):
    _break_cairosvg(monkeypatch)
    vector = next(c for c in all_converters() if c.name == "Vector Graphics Converter")
    available, reason = vector.check_available()
    assert not available
    assert "Cairo" in reason


def test_every_converter_check_is_crash_proof(monkeypatch):
    _break_cairosvg(monkeypatch)
    for converter in all_converters():
        available, reason = converter.safe_check_available()
        assert isinstance(available, bool) and isinstance(reason, str)


def test_broken_check_does_not_break_converter_lookup(monkeypatch):
    class Boom(Exception):
        pass

    vector = find_converter("svg", "png")

    def explode():
        raise Boom("unexpected")

    monkeypatch.setattr(vector, "check_available", explode)
    assert vector.safe_check_available()[0] is False


def test_svg_conversion_fails_cleanly_without_cairo(monkeypatch, work):
    from fileconverter.core.base import ConversionJob
    from fileconverter.core.engine import ConversionEngine

    _break_cairosvg(monkeypatch)
    src = work / "pic.svg"
    src.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>')
    engine = ConversionEngine(max_workers=1)
    [result] = engine.run_batch([ConversionJob(src, work / "pic.png", "png")])
    assert not result.success
    assert "Cairo" in result.error
