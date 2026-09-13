"""Styles (a preset of one type's params) and the description-to-settings path."""

from __future__ import annotations

from pathlib import Path

import pytest

from lyricfield import describe as D
from lyricfield import styles as St
from lyricfield.config import Config

REPO = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ styles

def test_slugify_is_url_safe():
    assert St.slugify("Calm Drift") == "calm-drift"
    assert " " not in St.slugify("A  Messy   Name!")


def test_save_and_load_round_trip(tmp_path, cfg):
    cfg.params.look.dim_hue = 0.31
    s = St.Style.from_config(cfg, "Cold", "a description")
    s.save(tmp_path)
    back = St.get_style(s.slug, tmp_path)
    assert back.name == "Cold"
    assert back.params.look.dim_hue == 0.31


def test_a_style_cannot_touch_the_track(tmp_path, cfg):
    """A style is provably song-independent: it carries params, never track data.

    That is the whole reason styles are reusable, so it is worth asserting
    rather than trusting.
    """
    cfg.track.title = "Some Song"
    cfg.track.vocals = "/tmp/vocals.wav"
    s = St.Style.from_config(cfg, "Cold")
    target = Config()
    target.track.title = "A Different Song"
    before = target.track.title, target.track.vocals
    s.apply_to(target)
    assert (target.track.title, target.track.vocals) == before


def test_applying_a_style_across_types_is_refused(cfg):
    s = St.Style.from_config(cfg, "Cold")
    s.type = "some_other_type"
    with pytest.raises(ValueError):
        s.apply_to(Config())


def test_the_shipped_style_loads_and_is_valid():
    """`calm-drift` predates several tunables, so loading it is a live test
    that old presets survive new parameters."""
    d = REPO / "styles" / "lyric_grid" / "calm-drift"
    if not (d / "style.toml").exists():
        pytest.skip("calm-drift is not present")
    s = St.Style.load(d / "style.toml")
    c = Config()
    s.apply_to(c)
    assert c.validate() == []


def test_delete_removes_it(tmp_path, cfg):
    s = St.Style.from_config(cfg, "Temp")
    s.save(tmp_path)
    assert St.get_style(s.slug, tmp_path) is not None
    St.delete_style(s.slug, tmp_path)
    with pytest.raises(FileNotFoundError):
        St.get_style(s.slug, tmp_path)


# ---------------------------------------------------------------- describe

def test_bare_json_is_read():
    assert D._extract_json('{"controls": {"motion": 0.2}}')["controls"]["motion"] == 0.2


def test_fenced_json_is_read():
    assert D._extract_json('```json\n{"why": "ok"}\n```')["why"] == "ok"


def test_prose_around_the_json_is_tolerated():
    assert D._extract_json('Sure!\n{"why": "ok"}\nHope that helps.')["why"] == "ok"


def test_a_reply_with_no_json_is_refused():
    with pytest.raises(D.DescribeError):
        D._extract_json("I could not do that.")


def test_a_json_array_is_refused():
    with pytest.raises(D.DescribeError):
        D._extract_json("[1, 2, 3]")


def test_an_empty_description_never_reaches_the_model(cfg, monkeypatch):
    monkeypatch.setattr(D, "ask", lambda *a, **k: pytest.fail("should not have asked"))
    with pytest.raises(D.DescribeError):
        D.propose(cfg, "   ")


def test_the_prompt_names_every_control_and_range(cfg):
    text = D._prompt(cfg, "colder")
    for c in cfg.video_type.controls(cfg.params):
        assert c["key"] in text
    for name in cfg.video_type.ranges():
        assert name in text


def _reply(monkeypatch, payload: str):
    monkeypatch.setattr(D, "ask", lambda *a, **k: payload)


def test_a_control_is_applied(cfg, monkeypatch):
    _reply(monkeypatch, '{"controls": {"motion": 0.1}, "why": "calmer"}')
    out = D.propose(cfg, "calmer")
    assert out.changed
    assert out.problems == []
    assert cfg.validate() == []


def test_an_unknown_control_is_ignored_not_applied(cfg, monkeypatch):
    _reply(monkeypatch, '{"controls": {"nonsense": 0.5}}')
    out = D.propose(cfg, "whatever")
    assert any("not a control" in s for s in out.ignored)


def test_a_non_numeric_value_is_ignored(cfg, monkeypatch):
    _reply(monkeypatch, '{"controls": {"motion": "fast"}}')
    out = D.propose(cfg, "fast")
    assert any("not a number" in s for s in out.ignored)


def test_an_out_of_range_parameter_is_clamped(cfg, monkeypatch):
    lo, hi, _ = cfg.video_type.ranges()["dim_hue"]
    _reply(monkeypatch, '{"params": {"dim_hue": 99}}')
    out = D.propose(cfg, "impossible")
    assert any("outside" in s for s in out.ignored)
    assert lo <= cfg.params.look.dim_hue <= hi


def test_an_unknown_parameter_is_ignored(cfg, monkeypatch):
    _reply(monkeypatch, '{"params": {"not_a_knob": 1}}')
    out = D.propose(cfg, "whatever")
    assert any("not a setting" in s for s in out.ignored)


def test_a_reply_that_changes_nothing_says_so(cfg, monkeypatch):
    _reply(monkeypatch, '{"controls": {}, "params": {}}')
    out = D.propose(cfg, "make it nice")
    assert out.ignored


def test_whatever_the_model_says_the_config_stays_valid(cfg, monkeypatch):
    """The model is untrusted input. No reply may leave an invalid config."""
    for payload in ('{"controls": {"brightness": 5, "glow": 5, "beat": 5}}',
                    '{"controls": {"brightness": -3, "motion": -3}}',
                    '{"params": {"ceil": 1.0, "glow_base": 1.0, "level_max": 1.0}}'):
        c = Config()
        _reply(monkeypatch, payload)
        D.propose(c, "extreme")
        assert c.validate() == [], f"{payload} left {c.validate()}"
