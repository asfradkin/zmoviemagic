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
