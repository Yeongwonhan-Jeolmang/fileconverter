from fileconverter.core.registry import find_converter, supported_targets


def test_contacts_and_calendars_only_offer_csv():
    assert supported_targets("vcf") == ["csv"]
    assert supported_targets("ics") == ["csv"]
    assert find_converter("vcf", "ics") is None


def test_csv_to_csv_goes_to_spreadsheet_converter():
    converter = find_converter("csv", "csv")
    assert converter is not None and converter.name == "Spreadsheet Converter"


def test_xls_is_read_only():
    assert "xls" not in supported_targets("csv")
    assert "csv" in supported_targets("xls")


def test_dxf_targets_and_svg_targets():
    assert supported_targets("dxf") == ["pdf", "png", "svg"]
    assert supported_targets("svg") == ["pdf", "png"]


def test_no_nonsense_document_pairs():
    assert find_converter("pdf", "pdf") is None
    assert "pptx" not in supported_targets("docx")
    assert "md" not in supported_targets("pdf")
    assert "pptx" in supported_targets("md")


def test_folder_and_archive_extraction_pairs():
    assert "zip" in supported_targets("folder")
    assert "folder" in supported_targets("zip")
