from pathlib import Path

from app.modules.audio_pipeline.application.pipeline_service import build_normalize_cmd


def test_normalize_cmd_loudnorm_off_is_format_only():
    cmd = build_normalize_cmd(
        Path("/x/raw.webm"), Path("/x/out.wav"), sample_rate=16000, mono=True, loudnorm=False
    )
    assert "loudnorm" not in " ".join(cmd)
    assert "-ac" in cmd and "16000" in cmd
    assert cmd[-1] == str(Path("/x/out.wav"))


def test_normalize_cmd_loudnorm_on_adds_filter():
    cmd = build_normalize_cmd(
        Path("/x/raw.webm"),
        Path("/x/out.wav"),
        sample_rate=16000,
        mono=True,
        loudnorm=True,
        loudnorm_i=-16.0,
        loudnorm_tp=-1.5,
        loudnorm_lra=11.0,
    )
    joined = " ".join(cmd)
    assert "-af" in cmd
    assert "loudnorm=I=-16.0:TP=-1.5:LRA=11.0" in joined


def test_normalize_cmd_stereo():
    cmd = build_normalize_cmd(
        Path("/x/raw.webm"), Path("/x/out.wav"), sample_rate=22050, mono=False, loudnorm=False
    )
    i = cmd.index("-ac")
    assert cmd[i + 1] == "2"
    assert "22050" in cmd
