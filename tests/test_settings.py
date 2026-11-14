import json

from mytts.settings import DEFAULT_HOTKEY, Settings


def test_missing_file_gives_defaults(tmp_path):
    s = Settings.load(tmp_path / "nope.json")
    assert s == Settings()
    assert s.hotkey == DEFAULT_HOTKEY and s.restore_clipboard


def test_round_trip(tmp_path):
    path = tmp_path / "sub" / "settings.json"
    s = Settings(voice="bf_emma", speed=1.25, theme="sepia", font_size=16.0, hotkey="Win+Shift+R",
                 always_on_top=True, restore_clipboard=False, geometry="AdnQywAD", tray_hint_shown=True)
    s.save(path)
    assert Settings.load(path) == s
    assert not path.with_name("settings.json.tmp").exists()


def test_damaged_file_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert Settings.load(path) == Settings()
    path.write_text("[1, 2]", encoding="utf-8")
    assert Settings.load(path) == Settings()


def test_wrong_types_fall_back_per_field(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "voice": 5,  # wrong type
        "speed": 2,  # int is fine for a float field
        "font_size": True,  # a bool is not a number here
        "always_on_top": "yes",  # wrong type
        "theme": "sepia",
        "unknown": 1,
    }), encoding="utf-8")
    s = Settings.load(path)
    assert s.voice == Settings().voice
    assert s.speed == 2.0 and isinstance(s.speed, float)
    assert s.font_size == Settings().font_size
    assert s.always_on_top is False
    assert s.theme == "sepia"
