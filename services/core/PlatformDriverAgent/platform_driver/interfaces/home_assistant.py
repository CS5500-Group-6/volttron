# -*- coding: utf-8 -*- {{{
# ===----------------------------------------------------------------------===
#
#                 Component of Eclipse VOLTTRON
#
# ===----------------------------------------------------------------------===
#
# Copyright 2023 Battelle Memorial Institute
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
# ===----------------------------------------------------------------------===
# }}}


import random
from math import pi
import json
import sys
from platform_driver.interfaces import BaseInterface, BaseRegister, BasicRevert
from volttron.platform.agent import utils
from volttron.platform.vip.agent import Agent
import logging
import requests
from requests import get

_log = logging.getLogger(__name__)
type_mapping = {"string": str,
                "int": int,
                "integer": int,
                "float": float,
                "bool": bool,
                "boolean": bool}


class HomeAssistantRegister(BaseRegister):
    def __init__(self, read_only, pointName, units, reg_type, attributes, entity_id, entity_point, default_value=None,
                 description=''):
        super(HomeAssistantRegister, self).__init__("byte", read_only, pointName, units, description='')
        self.reg_type = reg_type
        self.attributes = attributes
        self.entity_id = entity_id
        self.value = None
        self.entity_point = entity_point


def _post_method(url, headers, data, operation_description):
    err = None
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            _log.info(f"Success: {operation_description}")
        else:
            err = f"Failed to {operation_description}. Status code: {response.status_code}. " \
                  f"Response: {response.text}"

    except requests.RequestException as e:
        err = f"Error when attempting - {operation_description} : {e}"
    if err:
        _log.error(err)
        raise Exception(err)


class Interface(BasicRevert, BaseInterface):
    def __init__(self, **kwargs):
        super(Interface, self).__init__(**kwargs)
        self.point_name = None
        self.ip_address = None
        self.access_token = None
        self.port = None
        self.units = None

    # ----------------- Core Unified Service Caller -----------------
    def _call_service(self, domain, service, data):
        """
        Unified method to call Home Assistant services via HTTP POST.
        """
        url = f"http://{self.ip_address}:{self.port}/api/services/{domain}/{service}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        _post_method(url, headers, data, f"{service} on {domain} with {data}")

    # ----------------- Core Write Interface -----------------
    def _set_point(self, point_name, value):
        """
        Automatically detect entity type and call the corresponding handler.
        """
        register = self.get_register_by_name(point_name)
        entity_id = register.entity_id
        writeable = register.get('writeable', False)

        if not entity_id:
            _log.error(f"Missing entity_id for register {point_name}")
            return

        if not writeable:
            _log.error(f"The point {point_name} is not writeable.")
            return

        # Auto-detect entity type: e.g., switch.light → switch
        entity_type = entity_id.split(".", 1)[0]

        # Map entity types to handlers
        HANDLERS = {
            "switch": self._handle_switch,
            "light": self._handle_light,
            "fan": self._handle_fan,
            "cover": self._handle_cover,
            "climate": self._handle_thermostat,
            "input_boolean": self._handle_input_boolean,
        }

        handler = HANDLERS.get(entity_type)
        if not handler:
            _log.error(f"Unsupported or non-writeable type: {entity_type}")
            return

        try:
            handler(entity_id, value)
        except Exception as e:
            _log.error(f"Error setting point for {entity_id}: {e}")

    # ----------------- Device Handlers -----------------
    def _handle_switch(self, entity_id, value):
        """
        Handle switch entities (on/off).
        """
        service = "turn_on" if bool(value) else "turn_off"
        self._call_service("switch", service, {"entity_id": entity_id})

    def _handle_light(self, entity_id, value):
        """
        Handle light entities.
        value can be:
            - bool → on/off
            - dict {"brightness": int} → set brightness
        """
        if isinstance(value, bool):
            service = "turn_on" if value else "turn_off"
            self._call_service("light", service, {"entity_id": entity_id})
        elif isinstance(value, dict) and "brightness" in value:
            self._call_service("light", "turn_on", {"entity_id": entity_id, "brightness": value["brightness"]})
        else:
            raise ValueError(f"Unsupported light value: {value}")

    def _handle_fan(self, entity_id, value):
        """
        Handle fan entities.
        value can be:
            - bool → on/off
            - int/float → percentage 0-100
            - str → speed: low, medium, high
        """
        if isinstance(value, bool):
            service = "turn_on" if value else "turn_off"
            self._call_service("fan", service, {"entity_id": entity_id})
        elif isinstance(value, (int, float)):
            percentage = max(0, min(100, int(value)))
            self._call_service("fan", "set_percentage", {"entity_id": entity_id, "percentage": percentage})
        elif isinstance(value, str) and value.lower() in ["low", "medium", "high"]:
            self._call_service("fan", "set_speed", {"entity_id": entity_id, "speed": value.lower()})
        else:
            raise ValueError(f"Unsupported fan value: {value}")

    def _handle_cover(self, entity_id, value):
        """
        Handle cover entities.
        value can be:
            - bool → open/close
            - str → open/close/stop
            - int → position 0-100
        """
        mapping = {
            True: "open_cover",
            False: "close_cover",
            "open": "open_cover",
            "close": "close_cover",
            "stop": "stop_cover"
        }
        if isinstance(value, int):
            self._call_service("cover", "set_cover_position", {"entity_id": entity_id, "position": value})
        else:
            service = mapping.get(value)
            if not service:
                raise ValueError(f"Unsupported cover command: {value}")
            self._call_service("cover", service, {"entity_id": entity_id})

    def _handle_thermostat(self, entity_id, value):
        """
        Handle thermostat (climate) entities.
        value can be:
            - int/float → temperature
            - dict {"mode": str} → HVAC mode
        """
        if isinstance(value, (int, float)):
            temp = round((value - 32) * 5/9, 1) if self.units == "C" else value
            self._call_service("climate", "set_temperature", {"entity_id": entity_id, "temperature": temp})
        elif isinstance(value, dict) and "mode" in value:
            self._call_service("climate", "set_hvac_mode", {"entity_id": entity_id, "hvac_mode": value["mode"]})
        else:
            raise ValueError(f"Unsupported thermostat value: {value}")

    def _handle_input_boolean(self, entity_id, value):
        """
        Handle input_boolean entities (on/off).
        """
        service = "turn_on" if str(value).lower() == "on" else "turn_off"
        self._call_service("input_boolean", service, {"entity_id": entity_id})