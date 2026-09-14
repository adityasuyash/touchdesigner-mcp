"""What a run remembers when it repairs itself.

A take is marked "verified" from `run.problems` being empty. The repair path
used to empty it wholesale, which meant the second take could be marked
trustworthy because the retry had erased the evidence that it was not.
"""

from __future__ import annotations

from lyricfield.run import _forget_problems


def test_a_retry_forgets_only_the_stages_it_is_redoing():
    problems = [
        "ingest: transcription probably dropped a line",
        "provision: glyph placement may not line up with the frame",
        "preview: the render is 3.0s long but 8.0s was asked for",
        "verify: the picture does not follow the words",
        "save: could not record the take",
    ]
    _forget_problems(problems, ("preview", "verify", "save"))
    assert problems == [
        "ingest: transcription probably dropped a line",
        "provision: glyph placement may not line up with the frame",
    ], "the repair forgot a problem that belonged to an earlier stage"


def test_a_retry_with_nothing_of_its_own_to_forget_changes_nothing():
    problems = ["ingest: no drum hits were detected at all"]
    _forget_problems(problems, ("preview", "verify", "save"))
    assert problems == ["ingest: no drum hits were detected at all"]


def test_a_stage_name_that_merely_starts_the_same_is_not_forgotten():
    """`startswith` on the bare key would match "previewer:" too; the colon and
    space are part of the prefix for that reason."""
    problems = ["previewing: something", "preview: something else"]
    _forget_problems(problems, ("preview",))
    assert problems == ["previewing: something"]


# ------------------------------------------- the check the takes never had

def test_verify_asks_whether_the_take_moved():
    """`measure_motion` was written because "a render can come back as the same
    frame repeated and every other check will pass it", and then it was called
    from exactly one place: the style-preview capture. The guarantee covered the
    thumbnails and not the file the person receives.

    It matters most for a beatsync take, where `measure_output` has no cue times
    to correlate against and the only remaining content checks are blackness and
    frame fill -- all of which a frozen render passes.
    """
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "lyricfield" / "run.py").read_text()
    body = re.search(r"def _verify\(ctx: Ctx, say\) -> dict:(.+?)\nSTAGES",
                     src, re.S)
    assert body, "could not find _verify"
    assert "measure_motion" in body.group(1), (
        "nothing in _verify asks whether the finished file moved")
