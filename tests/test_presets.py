import json

import pytest

from fileconverter.core import presets
from fileconverter.core.exceptions import PresetError


def test_overriding_a_builtin_preset_can_be_undone():
    presets.save_preset("podcast-mp3", "mp3", {"bitrate": "96k"})
    assert presets.get_preset("podcast-mp3").options == {"bitrate": "96k"}
    assert not presets.is_builtin("podcast-mp3")

    presets.delete_preset("podcast-mp3")  # used to raise "built-in, can't delete"
    assert presets.get_preset("podcast-mp3").options == presets.BUILTIN_PRESETS[
        "podcast-mp3"
    ]["options"]


def test_builtin_preset_cannot_be_deleted():
    with pytest.raises(PresetError):
        presets.delete_preset("lossless-png")


def test_malformed_presets_file_is_ignored():
    presets.PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    presets.PRESETS_FILE.write_text(
        json.dumps({"broken": {"options": {}}, "ok": {"target_format": "png"}})
    )
    names = {p.name for p in presets.list_presets()}
    assert "ok" in names and "broken" not in names


def test_save_normalizes_target_format():
    presets.save_preset("mine", ".PNG", {})
    assert presets.get_preset("mine").target_format == "png"
