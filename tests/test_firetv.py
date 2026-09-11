from services.firetv_service import FireTVService


def test_firetv_preserves_disney_deep_link_command(monkeypatch):
    class FakeDevice:
        def __init__(self):
            self.commands = []

        def shell(self, command):
            self.commands.append(command)

    device = FakeDevice()
    service = FireTVService(host="192.0.2.1")
    monkeypatch.setattr(service, "get_device", lambda force_reconnect=False: (device, None))

    assert service.launch_movie("luca-id") == {"retried": False}
    assert device.commands == [
        "input keyevent 224 && input keyevent 3 && "
        "am start -a android.intent.action.VIEW "
        '-d "https://www.disneyplus.com/play/luca-id?startTime=0" '
        "com.disney.disneyplus"
    ]
