"""Config, the sectioned-TOML machinery, and validation."""

from __future__ import annotations

import pytest

from lyricfield import sections as S
from lyricfield.config import Config
from lyricfield.types.lyric_grid.params import Params


def test_defaults_are_valid(cfg):
    assert cfg.validate() == []


def test_toml_round_trip(tmp_path, cfg):
    cfg.track.title = "A Song"
    cfg.params.look.dim_hue = 0.42
    p = tmp_path / "config.toml"
    cfg.save(p)
    back = Config.load(p)
    assert back.track.title == "A Song"
    assert back.params.look.dim_hue == 0.42
    assert back.type == cfg.type


def test_missing_file_loads_defaults(tmp_path):
    assert Config.load(tmp_path / "nope.toml").validate() == []


def test_a_config_written_before_a_tunable_existed_still_loads(tmp_path):
    """`build_sections` tolerates missing keys on purpose: tunables get added,
    and an old config must not become unloadable because of it."""
    p = tmp_path / "old.toml"
    p.write_text('[video]\ntype = "lyric_grid"\n\n[look]\ndim_hue = 0.3\n')
    c = Config.load(p)
    assert c.params.look.dim_hue == 0.3
    assert c.params.grid.letter_frac == Params().grid.letter_frac


def test_unknown_keys_are_ignored(tmp_path):
    p = tmp_path / "future.toml"
    p.write_text('[video]\ntype = "lyric_grid"\n\n[look]\ndim_hue = 0.3\nnot_a_real_knob = 9\n')
    assert Config.load(p).params.look.dim_hue == 0.3


def test_the_shipped_example_config_loads():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    example = repo / "data" / "config.example.toml"
    if not example.exists():
        pytest.skip("no example config in the repo")
    Config.load(example)          # must not raise


# ---------------------------------------------------------------- sections

def test_section_names_match_the_dataclass():
    assert set(S.section_names(Params)) == set(Params().__dataclass_fields__)


def test_flatten_covers_every_tunable():
    flat = S.flatten(Params())
    for name in ("dim_hue", "hold", "ripple_lift", "cols"):
        assert name in flat


def test_toml_value_refuses_what_it_cannot_write():
    with pytest.raises(TypeError):
        S.toml_value(object())


# -------------------------------------------------------------- validation

def test_level_min_above_level_max_is_caught():
    p = Params()
    p.look.level_min, p.look.level_max = 0.5, 0.2
    assert p.validate() != []


def test_level_max_above_ceil_is_caught():
    p = Params()
    p.look.level_max = p.look.ceil + 0.1
    assert p.validate() != []


def test_the_brightness_stacking_regression_is_caught():
    """Spark and glow add at the output; 0.75/0.40 once measured 0.99 there.
    Only a cued word may reach 1.0."""
    p = Params()
    p.look.ceil, p.look.glow_base = 0.9, 0.9
    assert any("glow" in s or "ceil" in s for s in p.validate())


def test_dead_space_at_the_bottom_of_frame_is_caught():
    """`band` well inside `vrows` left 480px of black for three versions."""
    p = Params()
    p.grid.band = p.grid.vrows // 2
    assert p.validate() != []


def test_negative_blur_is_caught():
    p = Params()
    p.look.glow_radius, p.look.glow_radius_lfo = 5.0, 50.0
    assert p.validate() != []


def test_regions_cover_the_frame():
    p = Params()
    r = p.regions()
    assert set(r) == {"band", "lower"}
    (_, y0, w, h0) = r["band"]
    (_, y1, w2, h1) = r["lower"]
    assert w == w2 == p.grid.width
    assert y1 == y0 + h0, "the band and the area below it must be contiguous"
    assert y1 + h1 <= p.grid.height


# ------------------------------------------------------------ track facts

def test_a_fresh_config_does_not_complain_about_unmeasured_facts(cfg):
    """Zeros before ingest are normal, not errors."""
    assert cfg.track_problems() == []


def test_a_zero_beat_period_is_caught():
    """It is a divisor evaluated every frame inside a CookLevel.ALWAYS TOP."""
    c = Config()
    c.track.duration, c.track.beat_period = 100.0, 0.0
    assert any("beat_period" in s for s in c.validate())


def test_an_unmeasured_duration_is_caught_once_the_song_is_ingested():
    c = Config()
    c.track.duration, c.track.beat_period = 0.0, 0.5
    c.track.instrumental = "/tmp/does-not-matter.wav"
    assert any("duration" in s for s in c.validate())


def test_a_marker_past_the_end_of_the_track_is_caught():
    c = Config()
    c.track.duration, c.track.kick_in = 90.0, 400.0
    assert any("kick_in" in s for s in c.validate())


def test_a_missing_stem_is_caught(tmp_path):
    c = Config()
    c.track.duration = 90.0
    c.track.vocals = str(tmp_path / "gone.wav")
    assert any("vocals" in s for s in c.validate())


def test_a_present_stem_is_accepted(tmp_path):
    real = tmp_path / "vocals.wav"
    real.write_bytes(b"x")
    c = Config()
    c.track.duration, c.track.vocals = 90.0, str(real)
    assert c.validate() == []


def test_a_backwards_hold_window_is_caught():
    c = Config()
    c.track.duration = 90.0
    c.track.hold_windows = [[10.0, 5.0]]
    assert any("hold window" in s for s in c.validate())


# --------------------------------------------------- gates that fit the track

def test_the_reference_level_is_the_benchmarks():
    from lyricfield.types.lyric_grid.params import REFERENCE_LEVEL
    assert 0.3 < REFERENCE_LEVEL < 0.4


def test_the_scale_factor_says_how_far_this_master_is_from_the_reference():
    from lyricfield.types.lyric_grid.params import Analysis, REFERENCE_LEVEL
    a = Analysis()
    assert a.scaled(REFERENCE_LEVEL)["factor"] == pytest.approx(1.0, rel=1e-3)
    assert a.scaled(REFERENCE_LEVEL / 2)["factor"] < 1.0
    assert a.scaled(REFERENCE_LEVEL * 2)["factor"] > 1.0


def test_the_scale_is_clamped_at_both_ends():
    """A nearly silent track must not end up with gates at zero, where every
    frame is a kick; a very loud one must not end up gated past anything."""
    from lyricfield.types.lyric_grid.params import Analysis
    a = Analysis()
    assert a.scaled(1000.0)["factor"] <= 3.0
    assert a.scaled(1e-6)["factor"] >= 0.25


def test_an_unmeasured_level_leaves_the_factor_at_one():
    from lyricfield.types.lyric_grid.params import Analysis
    assert Analysis().scaled(0.0)["factor"] == pytest.approx(1.0)


def test_only_the_band_the_network_actually_selects_is_configured():
    """The kick, snare, rythm and high gates were scaled, pushed and reported
    as applied while moving nothing: the drum response had moved to the onset
    table pushed in from the repo, and the network selects only the low band
    (`v8_low`). Four knobs that were offered, pushed and ignored.
    """
    from lyricfield.types.lyric_grid.params import Analysis
    g = Analysis().scaled(0.3)
    assert set(g) == {"low_thresh", "low_smooth", "factor"}, (
        "a gate is being pushed that no operator downstream reads")



def test_a_band_flush_to_the_bottom_reports_no_region_below_it():
    """`band == vrows - band_top` is legal and leaves nothing underneath. The
    clamped one-pixel crop it used to emit starts at the frame's bottom edge,
    which ffmpeg rejects -- so the letters-below-the-band check silently became
    a no-op, and that check exists because letters escaping the band shipped
    three times."""
    p = Params()
    p.grid.band = p.grid.vrows - p.grid.band_top
    assert p.validate() == []
    assert "lower" not in p.regions()


def test_every_region_is_a_legal_crop():
    p = Params()
    for name, (x, y, w, h) in p.regions().items():
        assert w >= 1 and h >= 1, name
        assert 0 <= x and x + w <= p.grid.width, name
        assert 0 <= y and y + h <= p.grid.height, name


def test_a_plate_survives_the_round_trip(tmp_path):
    """Footage the lyrics are lettered over: user-supplied, per song."""
    from lyricfield.config import Config

    c = Config()
    c.track.plate = "/clips/coast.mp4"
    c.save(tmp_path / "config.toml")
    assert Config.load(tmp_path / "config.toml").track.plate == "/clips/coast.mp4"


def test_a_missing_plate_is_reported_before_anything_is_measured(tmp_path):
    """Unlike the stems, a plate is a path a person types, so it can be wrong
    the moment a song is created. Waiting for ingest to run before checking it
    means finding out at render time, which costs a build."""
    from lyricfield.config import Config

    c = Config()
    c.track.plate = str(tmp_path / "nope.mp4")
    assert any("plate file is recorded but missing" in m for m in c.validate())

    (tmp_path / "nope.mp4").write_bytes(b"")
    assert not any("plate" in m for m in c.validate())


def test_no_type_may_declare_a_tunable_called_plate():
    """`Config.as_params` merges the whole of Track into the flat dict every
    field script reads, so the name is reserved repo-wide the moment
    `Track.plate` exists."""
    from lyricfield import types as T

    for vt in T.list_types():
        p = vt.default_params()
        for section in p.__dataclass_fields__:
            assert "plate" not in getattr(p, section).__dataclass_fields__, (
                f"{vt.slug}.{section} declares `plate`, which collides with the "
                "song's own")
