from home_assistant import Interface

# Replace with your Home Assistant info
config = {
    "ip_address": "192.168.1.100",
    "port": 8123,
    "access_token": "YOUR_LONG_LIVED_ACCESS_TOKEN",
}

# Fake registry config
registry_config = [
    {
        "Volttron Point Name": "living_light",
        "Entity ID": "light.living_room",
        "Entity Point": "state",
        "Units": "",
        "Writable": "true",
        "Type": "bool",
        "Attributes": {},
        "Notes": "Test light"
    },
    {
        "Volttron Point Name": "living_fan",
        "Entity ID": "fan.living_room",
        "Entity Point": "speed",
        "Units": "",
        "Writable": "true",
        "Type": "int",
        "Attributes": {},
        "Notes": "Test fan"
    }
]

# Initialize interface
iface = Interface(units="F")  # or "C"
iface.configure(config, registry_config)

# Test turning light on
iface._set_point("living_light", True)

# Test fan at 50%
iface._set_point("living_fan", 50)
