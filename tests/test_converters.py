"""Converter round-trips. Each test skips if its optional dependency
isn't installed, so the suite runs on a partial install."""

import json
import shutil
import tarfile
import zipfile

import pytest

from fileconverter.core.base import ConversionJob
from fileconverter.core.engine import ConversionEngine


def convert(src, target, out=None, **options):
    out = out or src.with_name(f"{src.stem}_out.{target}")
    engine = ConversionEngine(max_workers=1)
    [result] = engine.run_batch([ConversionJob(src, out, target, options=options)])
    engine.shutdown(wait=True)
    assert result.success, result.error
    return result.output_path


# -- images ---------------------------------------------------------------
def test_transparent_png_to_jpg_has_white_background(work):
    Image = pytest.importorskip("PIL.Image")
    src = work / "alpha.png"
    img = Image.new("RGBA", (40, 40), (255, 0, 0, 0))
    img.paste((0, 0, 255, 255), (10, 10, 30, 30))
    img.save(src)
    out = convert(src, "jpg")
    with Image.open(out) as result:
        # White (allowing for JPEG noise), not black.
        assert min(result.getpixel((2, 2))) >= 245


def test_animated_gif_to_pdf_keeps_every_frame(work):
    Image = pytest.importorskip("PIL.Image")
    pypdf = pytest.importorskip("pypdf")
    src = work / "anim.gif"
    frames = [Image.new("RGB", (20, 20), c) for c in ("red", "green", "blue")]
    frames[0].save(src, save_all=True, append_images=frames[1:])
    out = convert(src, "pdf")
    assert len(pypdf.PdfReader(str(out)).pages) == 3


def test_resize_accepts_wxh_string(work):
    Image = pytest.importorskip("PIL.Image")
    src = work / "big.png"
    Image.new("RGB", (400, 200), "red").save(src)
    out = convert(src, "png", out=work / "small.png", resize="100x100")
    with Image.open(out) as result:
        assert result.size == (100, 50)


# -- data -----------------------------------------------------------------
def test_xml_attributes_round_trip(work):
    src = work / "data.xml"
    src.write_text('<root><item id="1">one</item><item id="2">two</item></root>')
    as_json = convert(src, "json")
    data = json.loads(as_json.read_text())
    assert data["root"]["item"][0] == {"@id": "1", "#text": "one"}
    back = convert(as_json, "xml", out=work / "back.xml")
    assert '<item id="2">two</item>' in back.read_text()


def test_json_with_single_list_key_to_xml(work):
    src = work / "users.json"
    src.write_text(json.dumps({"users": [{"name": "a"}, {"name": "b"}]}))
    xml = convert(src, "xml").read_text()
    assert "[{" not in xml  # used to dump the Python repr of the list
    assert xml.count("<users>") == 2


def test_toml_dates_to_json(work):
    pytest.importorskip("tomli_w")
    src = work / "c.toml"
    src.write_text("when = 2024-05-01\n")
    assert json.loads(convert(src, "json").read_text()) == {"when": "2024-05-01"}


def test_odd_json_keys_make_valid_xml(work):
    src = work / "odd.json"
    src.write_text(json.dumps({"first name": "a", "2024": 1}))
    xml = convert(src, "xml").read_text()
    assert "<first_name>a</first_name>" in xml


# -- spreadsheets / contacts / calendars ------------------------------------
def test_excel_bom_csv_header(work):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("openpyxl")
    src = work / "bom.csv"
    src.write_text("Name,Age\nAnn,30\n", encoding="utf-8-sig")
    out = convert(src, "xlsx")
    assert pd.read_excel(out).columns.tolist() == ["Name", "Age"]


def test_ics_csv_round_trip_with_timezones(work):
    pytest.importorskip("vobject")
    src = work / "cal.ics"
    src.write_text(
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\nUID:1\n"
        "DTSTAMP:20240101T000000Z\nSUMMARY:Meet\nDTSTART:20240501T140000Z\n"
        "DTEND:20240501T150000Z\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    as_csv = convert(src, "csv")
    back = convert(as_csv, "ics", out=work / "back.ics").read_text()
    assert "DTSTART:20240501T140000Z" in back


# -- archives ---------------------------------------------------------------
def test_zip_slip_is_refused(work):
    src = work / "evil.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("../../escape.txt", "x")
    engine = ConversionEngine(max_workers=1)
    [result] = engine.run_batch([ConversionJob(src, work / "evil.tar", "tar")])
    assert not result.success
    assert "zip slip" in result.error


def test_folder_compress_and_extract(work):
    folder = work / "project"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.txt").write_text("a")
    (folder / "sub" / "b.txt").write_text("b")
    archive = convert(folder, "gz", out=work / "project.tar.gz")
    with tarfile.open(archive) as tf:
        assert sorted(tf.getnames()) == ["a.txt", "sub/b.txt"]
    extracted = convert(archive, "folder", out=work / "restored")
    assert (extracted / "sub" / "b.txt").read_text() == "b"


# -- documents --------------------------------------------------------------
def test_docx_to_html_escapes_text(work):
    docx = pytest.importorskip("docx")
    src = work / "d.docx"
    document = docx.Document()
    document.add_heading("A <title>", 1)
    document.add_paragraph("x < y & z")
    document.save(src)
    html = convert(src, "html").read_text()
    assert "<h1>A &lt;title&gt;</h1>" in html
    assert "x &lt; y &amp; z" in html


def test_long_text_lines_wrap_in_pdf(work):
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    src = work / "long.txt"
    src.write_text("word " * 400)
    out = convert(src, "pdf")
    text = pypdf.PdfReader(str(out)).pages[0].extract_text()
    assert len(text.splitlines()) > 5


# -- audio / video (need the ffmpeg binary) ----------------------------------
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _tone(path, seconds=1):
    import subprocess

    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         f"sine=duration={seconds}", str(path)],
        check=True,
    )


@needs_ffmpeg
@pytest.mark.parametrize("target", ["mp3", "aac", "wma", "m4a", "flac"])
def test_audio_targets(work, target):
    src = work / "tone.wav"
    _tone(src)
    assert convert(src, target).stat().st_size > 0


@needs_ffmpeg
def test_cancelling_kills_ffmpeg(work):
    import threading
    import time

    src = work / "long.wav"
    _tone(src, seconds=600)
    out = work / "long.flac"
    engine = ConversionEngine(max_workers=1)
    job = ConversionJob(src, out, "flac", options={"sample_rate": 8000})
    future = engine.submit(job)
    time.sleep(0.5)
    started = time.monotonic()
    engine.cancel(job.job_id)
    result = future.result(timeout=20)
    assert time.monotonic() - started < 10
    assert result.message == "Cancelled"
    assert not out.exists()
    assert threading.active_count() >= 1
