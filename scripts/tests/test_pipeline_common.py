from pathlib import Path

from _pipeline_common import build_ffmpeg_cmd


def test_build_ffmpeg_cmd_loudnorm_off_is_format_only():
    cmd = build_ffmpeg_cmd(
        Path("/x/in.webm"), Path("/x/out.wav"), 16000, "ffmpeg", loudnorm=False
    )
    assert "loudnorm" not in " ".join(cmd)
    assert "-ac" in cmd and "1" in cmd and "16000" in cmd
    assert cmd[-1] == str(Path("/x/out.wav"))


def test_build_ffmpeg_cmd_loudnorm_on_adds_filter():
    cmd = build_ffmpeg_cmd(
        Path("/x/in.webm"),
        Path("/x/out.wav"),
        16000,
        "ffmpeg",
        loudnorm=True,
        loudnorm_i=-16.0,
        loudnorm_tp=-1.5,
        loudnorm_lra=11.0,
    )
    joined = " ".join(cmd)
    assert "-af" in cmd
    assert "loudnorm=I=-16.0:TP=-1.5:LRA=11.0" in joined


def test_build_ffmpeg_cmd_sample_rate():
    cmd = build_ffmpeg_cmd(
        Path("/x/in.webm"), Path("/x/out.wav"), 22050, "ffmpeg", loudnorm=False
    )
    i = cmd.index("-ar")
    assert cmd[i + 1] == "22050"
