"""Synthetic UI fixtures based on the supplied picker; all device work is fake."""
from threading import Event
from xml.etree import ElementTree as ET

import pytest

from services.disney_profile import is_focused_profile
from services.firetv_service import CommandBudget, FireTVService
from services.playback_service import APIError, PlaybackService
from tests.test_catalog_v2 import load_catalog, row
from tests.test_dispatcher import terminal
from tests.test_firetv_bounded import FakeConnection, FakeDevice


@pytest.fixture
def picker():
    # Semantic shape of the actual dump; other household information is omitted.
    return '''<hierarchy rotation="0">
      <node package="com.disney.disneyplus" resource-id="com.disney.disneyplus:id/profilesContent">
        <node package="com.disney.disneyplus" text="Who's watching?"/>
        <node package="com.disney.disneyplus" enabled="true" clickable="true"
              focusable="true" focused="true">
          <node package="com.disney.disneyplus" content-desc="Access zach's profile" enabled="true"/>
        </node>
        <node package="com.disney.disneyplus" content-desc="Add Profile" focused="false"/>
      </node>
    </hierarchy>'''


def test_recognizes_exact_focused_profile_without_coordinates(picker):
    assert is_focused_profile(picker, "zach")
    assert not is_focused_profile(picker, "Zach")
    assert not is_focused_profile(picker, "another profile")


@pytest.mark.parametrize("before,after", [
    ("Who's watching?", "Enter PIN"),
    ("profilesContent", "playerContent"),
    ("com.disney.disneyplus", "another.package"),
    ('focused="true"', 'focused="false"'),
    ('enabled="true"', 'enabled="false"'),
    ('clickable="true"', 'clickable="false"'),
    ('focusable="true"', 'focusable="false"'),
    ("Access zach's profile", "Edit zach's profile"),
])
def test_other_screens_or_non_actionable_target_never_match(picker, before, after):
    assert not is_focused_profile(picker.replace(before, after), "zach")


def test_duplicate_target_or_focus_is_ambiguous(picker):
    root = ET.fromstring(picker)
    container = root[0]
    ET.SubElement(container, "node", package="com.disney.disneyplus",
                  **{"content-desc": "Access zach's profile", "enabled": "true"})
    assert not is_focused_profile(ET.tostring(root, encoding="unicode"), "zach")
    root = ET.fromstring(picker)
    ET.SubElement(root, "node", package="com.disney.disneyplus", focused="true")
    assert not is_focused_profile(ET.tostring(root, encoding="unicode"), "zach")


@pytest.mark.parametrize("xml", ["", "<broken", "x" * 65537,
    '<!DOCTYPE hierarchy [<!ENTITY x "zach">]><hierarchy/>', '<not-a-hierarchy/>'])
def test_invalid_or_unexpected_xml_is_not_actionable(xml):
    assert not is_focused_profile(xml, "zach")


def test_disabled_profile_does_no_additional_device_work(monkeypatch):
    service = FireTVService("192.0.2.1")
    monkeypatch.setattr(service, "_profile_shell", lambda *a: pytest.fail("Profile work while disabled"))
    service._select_profile_after_launch()


@pytest.fixture
def profile_service(monkeypatch):
    service = FireTVService("192.0.2.1", profile_name="zach")
    monkeypatch.setattr("services.firetv_service.time.sleep", lambda seconds: None)
    return service


def test_fresh_match_sends_exactly_one_select_and_no_launch(profile_service, monkeypatch, picker):
    calls = []

    def shell(command, budget):
        calls.append(command)
        budget.remaining()
        return picker if command.startswith("uiautomator dump ") else ""

    monkeypatch.setattr(profile_service, "_profile_shell", shell)
    profile_service._select_profile_after_launch()
    assert len(calls) == 2
    assert calls[0].startswith("uiautomator dump /sdcard/zmm-profile-")
    assert ">/dev/null && cat " in calls[0] and "; rm -f " in calls[0]
    assert calls[1] == "input keyevent 23"
    assert not any("am start" in command for command in calls)


def test_late_picker_is_detected_but_each_dump_uses_a_new_file(profile_service, monkeypatch, picker):
    calls = []

    def shell(command, budget):
        calls.append(command)
        if len(calls) == 1:
            return "<hierarchy/>"
        return picker

    monkeypatch.setattr(profile_service, "_profile_shell", shell)
    profile_service._select_profile_after_launch()
    assert len(calls) == 3
    assert calls[0] != calls[1]
    assert calls[-1] == "input keyevent 23"


def test_unrecognized_ui_has_three_probes_and_zero_input(profile_service, monkeypatch):
    calls = []
    monkeypatch.setattr(profile_service, "_profile_shell", lambda command, budget: calls.append(command) or "<hierarchy/>")
    profile_service._select_profile_after_launch()
    assert len(calls) == 3
    assert len(set(calls)) == 3
    assert not any("input keyevent" in command for command in calls)


@pytest.mark.parametrize("fail_at", [1, 2])
def test_uncertain_probe_or_select_is_never_repeated(profile_service, monkeypatch, picker, fail_at, caplog):
    calls = []

    def shell(command, budget):
        calls.append(command)
        if len(calls) == fail_at:
            raise TimeoutError("private UI and profile information")
        return picker

    monkeypatch.setattr(profile_service, "_profile_shell", shell)
    with caplog.at_level("INFO"):
        profile_service._select_profile_after_launch()
    assert len(calls) == fail_at
    assert "private UI" not in caplog.text
    assert "unconfirmed" in caplog.text


def test_profile_budget_never_exceeds_remaining_launch_deadline(profile_service, monkeypatch, picker):
    now = [0.0]
    launch_budget = CommandBudget(15, 5, lambda: now[0])
    now[0] = 14
    calls = []

    def shell(command, budget):
        assert budget.deadline == 15
        calls.append(command)
        now[0] = 16
        budget.remaining()
        return picker

    monkeypatch.setattr(profile_service, "_profile_shell", shell)
    profile_service._select_profile_after_launch(launch_budget)
    assert len(calls) == 1


def test_profile_failure_does_not_reclassify_or_retry_delivered_launch(profile_service, monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(profile_service, "_get_budget_device", lambda *a, **k: FakeDevice(connection))
    monkeypatch.setattr(profile_service, "_profile_shell", lambda *a: (_ for _ in ()).throw(OSError("private")))
    assert profile_service.launch_movie_bounded("luca-id") == {"connection": "connected"}
    assert len(connection.commands) == 1


def test_legacy_keeps_response_and_launch_when_profile_check_fails(profile_service, monkeypatch):
    launches = []
    monkeypatch.setattr(profile_service, "get_device", lambda **kwargs: (object(), None))
    monkeypatch.setattr(profile_service, "_shell", lambda device, command: launches.append(command))
    monkeypatch.setattr(profile_service, "_profile_shell", lambda *a: (_ for _ in ()).throw(TimeoutError("private")))
    assert profile_service.launch_movie("legacy-valid-not-in-catalog") == {"retried": False}
    assert len(launches) == 1


@pytest.mark.parametrize("name", [None, "x" * 65, "name\ncommand"])
def test_profile_configuration_is_validated(name):
    with pytest.raises(ValueError, match="DISNEY_PROFILE_NAME"):
        FireTVService("192.0.2.1", profile_name=name)


def test_profile_name_is_data_and_never_shell_text(profile_service, monkeypatch, picker):
    profile_service.profile_name = "name; input keyevent 3"
    commands = []
    monkeypatch.setattr(profile_service, "_profile_shell", lambda command, budget: commands.append(command) or picker)
    profile_service._select_profile_after_launch()
    assert len(commands) == 3
    assert all(profile_service.profile_name not in command for command in commands)


def test_profile_inspection_keeps_legacy_and_new_admission_serialized(tmp_path, monkeypatch):
    service = FireTVService("192.0.2.1", profile_name="zach")
    entered, release = Event(), Event()
    monkeypatch.setattr("services.firetv_service.time.sleep", lambda seconds: None)
    monkeypatch.setattr(service, "_get_budget_device", lambda *a, **k: FakeDevice(FakeConnection()))

    def inspect(command, budget):
        entered.set()
        assert release.wait(3)
        return "<hierarchy/>"

    monkeypatch.setattr(service, "_profile_shell", inspect)
    catalog = load_catalog(tmp_path, [row()])
    playback = PlaybackService(service, cooldown_seconds=0, movie_service=catalog)
    try:
        accepted = playback.submit_play("luca", "lan-household", "profile-job-001")
        assert entered.wait(2)
        with pytest.raises(APIError) as busy:
            playback.submit_play("luca", "lan-household", "profile-job-002")
        assert busy.value.code == "busy"
        with pytest.raises(RuntimeError):
            playback.play("legacy-valid")
        release.set()
        assert terminal(playback, accepted["request_id"])["command_state"] == "command_sent"
    finally:
        release.set()
        playback.shutdown()
