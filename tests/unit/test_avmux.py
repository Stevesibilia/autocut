"""The shared container work: the concat list, the audio filter, the joined command."""

from __future__ import annotations

from pathlib import Path

from autocut.core.avmux import audio_filter, concat_command, write_concat_list


def test_the_list_escapes_a_quote_in_a_path(tmp_path: Path) -> None:
    """The concat demuxer doubles single quotes, and a holiday folder may hold one."""
    list_file = write_concat_list([tmp_path / "it's here" / "001.mp4"], tmp_path / "parts.txt")

    assert "it''s here" in list_file.read_text(encoding="utf-8")


def test_a_track_is_padded_and_faded_against_the_edit() -> None:
    """The fade sits at the end of the edit, which is where the file stops."""
    assert audio_filter(73.6, 1.5) == "apad,afade=t=out:st=72.100:d=1.500"


def test_no_fade_is_asked_for_and_none_is_added() -> None:
    assert audio_filter(73.6, 0.0) == "apad"


def test_a_fade_longer_than_the_edit_starts_at_the_beginning() -> None:
    """A three second fade over a two second edit is a fade from the first frame."""
    assert audio_filter(2.0, 3.0) == "apad,afade=t=out:st=0.000:d=2.000"


def test_the_track_is_re_encoded_and_the_video_copied(tmp_path: Path) -> None:
    command = concat_command(
        tmp_path / "parts.txt",
        tmp_path / "t.mp3",
        tmp_path / "out.mp4",
        duration_s=73.6,
        fade_out_s=1.5,
        audio_bitrate="192k",
    )

    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-b:a") + 1] == "192k"
    assert command[command.index("-af") + 1] == "apad,afade=t=out:st=72.100:d=1.500"
    assert command[command.index("-t") + 1] == "73.600"


def test_clip_audio_is_copied_when_there_is_no_track(tmp_path: Path) -> None:
    """Clips that kept their ambience keep it, and nothing is re-encoded at all."""
    command = concat_command(
        tmp_path / "parts.txt", None, tmp_path / "out.mp4", keep_clip_audio=True
    )

    assert command[command.index("-c:a") + 1] == "copy"
    assert "-an" not in command
    assert command[command.index("-map") + 1] == "0:v:0"


def test_a_track_wins_over_the_clips_own_audio(tmp_path: Path) -> None:
    """Mixing the two is a decision nobody has asked for; the track is the sound."""
    command = concat_command(
        tmp_path / "parts.txt",
        tmp_path / "t.mp3",
        tmp_path / "out.mp4",
        duration_s=10.0,
        keep_clip_audio=True,
    )

    assert command[command.index("-c:a") + 1] == "aac"
    assert "0:a:0" not in command
    assert "1:a:0" in command


def test_silent_clips_and_no_track_make_a_silent_file(tmp_path: Path) -> None:
    command = concat_command(tmp_path / "parts.txt", None, tmp_path / "out.mp4")

    assert "-an" in command
    assert "-c:a" not in command
