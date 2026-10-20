import zipfile

from fileconverter.core.formats import FOLDER_FORMAT, detect_format, normalize_ext, sniff_format


def _ftyp(brand: bytes) -> bytes:
    return b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x00\x00" + b"\x00" * 64


def test_normalize_ext():
    assert normalize_ext(".PNG") == "png"
    assert normalize_ext("photo.JPG") == "jpg"
    assert normalize_ext("png") == "png"


def test_heic_is_not_mistaken_for_mp4(work):
    path = work / "photo.heic"
    path.write_bytes(_ftyp(b"heic"))
    assert sniff_format(path) == "heic"
    assert detect_format(path) == "heic"


def test_iphone_heic_saved_as_jpg_is_detected(work):
    path = work / "photo.jpg"
    path.write_bytes(_ftyp(b"mif1"))
    assert detect_format(path) == "heif"


def test_real_mp4_brands_still_mp4(work):
    path = work / "clip.mp4"
    path.write_bytes(_ftyp(b"isom"))
    assert detect_format(path) == "mp4"
    mov = work / "clip.mov"
    mov.write_bytes(_ftyp(b"qt  "))
    assert detect_format(mov) == "mov"


def _odf(path, mimetype):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", mimetype)
        zf.writestr("content.xml", "<x/>")


def test_ods_is_not_detected_as_odt(work):
    ods = work / "sheet.ods"
    _odf(ods, "application/vnd.oasis.opendocument.spreadsheet")
    assert sniff_format(ods) == "ods"
    assert detect_format(ods) == "ods"

    odt = work / "text.odt"
    _odf(odt, "application/vnd.oasis.opendocument.text")
    assert detect_format(odt) == "odt"


def test_directories_are_folders(work):
    folder = work / "photos.2024"
    folder.mkdir()
    assert detect_format(folder) == FOLDER_FORMAT


def test_wrong_extension_uses_content(work):
    path = work / "image.txt"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    assert detect_format(path) == "png"


def test_tif_and_tiff_are_related(work):
    path = work / "scan.tif"
    path.write_bytes(b"II*\x00" + b"\x00" * 32)
    assert detect_format(path) == "tif"
