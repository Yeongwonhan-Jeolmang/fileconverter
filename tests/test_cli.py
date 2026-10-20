import json

import pytest
from click.testing import CliRunner

from fileconverter import __version__
from fileconverter.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_version_works_without_installed_metadata(runner):
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_short_help_flag(runner):
    assert runner.invoke(cli, ["-h"]).exit_code == 0


def test_same_named_inputs_get_distinct_outputs(runner, work):
    (work / "a").mkdir()
    (work / "b").mkdir()
    (work / "a" / "data.json").write_text('{"x": 1}')
    (work / "b" / "data.json").write_text('{"x": 2}')
    out = work / "out"
    result = runner.invoke(
        cli, ["convert", str(work / "a" / "data.json"), str(work / "b" / "data.json"),
              "-t", "yaml", "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in out.iterdir()) == ["data (1).yaml", "data.yaml"]


def test_json_output_records_options_for_retry(runner, work):
    src = work / "data.json"
    src.write_text('{"x": 1}')
    result = runner.invoke(
        cli, ["convert", str(src), "-t", "xml", "-O", "xml_root=doc", "--json-output"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload[0]["options"]["xml_root"] == "doc"


def test_preset_errors_are_clean(runner):
    result = runner.invoke(cli, ["presets", "delete", "lossless-png"])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "built-in" in result.output


def test_target_format_is_normalized(runner, work):
    src = work / "data.json"
    src.write_text('{"x": 1}')
    result = runner.invoke(cli, ["convert", str(src), "-t", ".YAML"])
    assert result.exit_code == 0, result.output
    assert (work / "data.yaml").exists()


def test_converting_a_folder_to_zip_compresses_it(runner, work):
    folder = work / "stuff"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    result = runner.invoke(cli, ["convert", str(folder), "-t", "zip"])
    assert result.exit_code == 0, result.output
    assert (work / "stuff.zip").exists()
