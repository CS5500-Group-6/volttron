import os
import sys
import types
from unittest.mock import Mock

import pytest

# Ensure repository root is on sys.path so tests can import package modules when running
# tests from the `tests/` directory directly.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Ensure PlatformDriverAgent's top-level package location is on sys.path so imports like
# `from platform_driver.interfaces import ...` resolve when importing the driver module.
PDA_DIR = os.path.abspath(os.path.join(ROOT, "services", "core", "PlatformDriverAgent"))
if PDA_DIR not in sys.path:
    sys.path.insert(0, PDA_DIR)

from services.core.PlatformDriverAgent.platform_driver.interfaces.home_assistant import (
    Interface,
    HomeAssistantRegister,
)


def _register_get(self, key, default=None):
    # Provide dict-like .get for HomeAssistantRegister instances used by _set_point
    return getattr(self, key, default)


def test_home_assistant_fan_and_cover_write(monkeypatch):
    """
    Verifies that:
    1) Setting 'kitchen_fan' to 'medium' results in a POST to /api/services/fan/set_speed
       with JSON {"entity_id": "fan.kitchen_fan", "speed": "medium"}
    2) Setting 'window_blind' to 50 results in a POST to /api/services/cover/set_cover_position
       with JSON {"entity_id": "cover.window_blind", "position": 50}
    """

    # Create a minimal concrete subclass to satisfy abstract methods and avoid running
    # the full BaseInterface initialization.
    class DummyInterface(Interface):
        def _scrape_all(self):
            return {}

        def configure(self, *args, **kwargs):
            return None

        def get_point(self, *args, **kwargs):
            return None

    iface = object.__new__(DummyInterface)
    # Attributes used by _call_service/_handle_* methods
    iface.ip_address = "127.0.0.1"
    iface.port = 8123
    iface.access_token = "FAKE_TOKEN"
    iface.units = "F"

    # Create registers for fan and cover
    fan_reg = HomeAssistantRegister(
        read_only=False,
        pointName="kitchen_fan",
        units=None,
        reg_type="fan",
        attributes=None,
        entity_id="fan.kitchen_fan",
        entity_point=None,
    )
    cover_reg = HomeAssistantRegister(
        read_only=False,
        pointName="window_blind",
        units=None,
        reg_type="cover",
        attributes=None,
        entity_id="cover.window_blind",
        entity_point=None,
    )

    # Ensure .get works (Interface._set_point calls register.get('writeable', False))
    fan_reg.get = types.MethodType(_register_get, fan_reg)
    cover_reg.get = types.MethodType(_register_get, cover_reg)

    # Mark registers as writeable
    fan_reg.writeable = True
    cover_reg.writeable = True

    # Provide a simple get_register_by_name implementation
    def get_register_by_name(name):
        if name == "kitchen_fan":
            return fan_reg
        if name == "window_blind":
            return cover_reg
        raise KeyError(name)

    iface.get_register_by_name = get_register_by_name

    # Capture posted calls
    calls = []

    def fake_post(url, headers=None, json=None):
        calls.append({"url": url, "headers": headers, "json": json})
        resp = Mock()
        resp.status_code = 200
        resp.text = "OK"
        return resp

    # Patch requests.post used by _post_method
    monkeypatch.setattr("requests.post", fake_post)

    # Perform writes
    iface._set_point("kitchen_fan", "medium")  # should call fan.set_speed
    iface._set_point("window_blind", 50)       # should call cover.set_cover_position

    # Two calls expected
    assert len(calls) == 2, f"expected 2 POSTs, got {len(calls)}: {calls}"

    # Validate fan call
    fan_call = calls[0]
    assert "/api/services/fan/set_speed" in fan_call["url"]
    assert fan_call["headers"]["Authorization"] == "Bearer FAKE_TOKEN"
    assert fan_call["json"] == {"entity_id": "fan.kitchen_fan", "speed": "medium"}

    # Validate cover call
    cover_call = calls[1]
    assert "/api/services/cover/set_cover_position" in cover_call["url"]
    assert cover_call["headers"]["Authorization"] == "Bearer FAKE_TOKEN"
    assert cover_call["json"] == {"entity_id": "cover.window_blind", "position": 50}
