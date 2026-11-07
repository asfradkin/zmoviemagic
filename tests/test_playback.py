import pytest

from services.playback_service import CooldownError, PlaybackService


def test_playback_launches_requested_id(fake_firetv):
    playback = PlaybackService(fake_firetv, cooldown_seconds=0)

    result = playback.play("luca-id")

    assert result == {
        "status": "success",
        "message": "Playing video luca-id",
    }
    assert fake_firetv.launched == ["luca-id"]


def test_playback_preserves_retry_message(fake_firetv):
    fake_firetv.retried = True
    playback = PlaybackService(fake_firetv, cooldown_seconds=0)

    assert playback.play("luca-id")["message"] == "Playing video luca-id (retried)"


def test_playback_rejects_invalid_id_before_launch(fake_firetv):
    playback = PlaybackService(fake_firetv, cooldown_seconds=0)

    with pytest.raises(ValueError, match="Invalid video ID"):
        playback.play("not valid")
    assert fake_firetv.launched == []


def test_playback_enforces_cooldown(fake_firetv):
    playback = PlaybackService(fake_firetv, cooldown_seconds=60)
    playback.play("luca-id")

    with pytest.raises(CooldownError, match="Please wait 60 seconds"):
        playback.play("moana-id")
    assert fake_firetv.launched == ["luca-id"]


def test_overlapping_play_is_rejected_and_lock_released(fake_firetv, monkeypatch):
    playback = PlaybackService(fake_firetv, cooldown_seconds=0)

    def launch(video_id):
        with pytest.raises(CooldownError, match="busy"):
            playback.play("moana-id")
        raise RuntimeError("disconnected")

    monkeypatch.setattr(fake_firetv, "launch_movie", launch)
    with pytest.raises(RuntimeError, match="disconnected"):
        playback.play("luca-id")
    monkeypatch.setattr(fake_firetv, "launch_movie", lambda video_id: {"retried": False})
    assert playback.play("luca-id")["status"] == "success"
