"""
Support for RESTful API sensors.
For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.rest/
Modified to parse a JSON reply and store data as attributes
"""
import datetime
import json
import logging
from functools import reduce

import requests
from homeassistant.components.binary_sensor import DEVICE_CLASS_PROBLEM
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_NAME, STATE_UNKNOWN, CONF_RESOURCE, CONF_METHOD,
    CONF_VERIFY_SSL, CONF_PAYLOAD, STATE_OFF, STATE_ON)
from homeassistant.helpers.entity import Entity

from . import CONF_STREET, CONF_STREET_NO, CONF_PARCEL_NO, CONF_REFRESH_RATE, SCHEMA, DOMAIN, VERSION

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(SCHEMA)
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up ESPHome binary sensors based on a config entry."""
    config = config_entry.data
    name = config.get(CONF_NAME)
    url = config.get(CONF_RESOURCE, "https://api.bezstavy.cz/cezd/api/inspectaddress/%s")
    method = config.get(CONF_METHOD, "GET")
    payload = config.get(CONF_PAYLOAD, '{"ulice":"","mesto":"Statenice","psc":""}')
    verify_ssl = config.get(CONF_VERIFY_SSL, True)
    auth = None
    rest = []
    for r in config[CONF_STREET]:
        client = JSONRestClient(method, url % r, auth, None, payload, verify_ssl)
        rest.append(client)
        await hass.async_add_executor_job(client.update)

    sensor = JSONRestSensor(hass, rest, name, config.get(CONF_STREET), config.get(CONF_STREET_NO),
                            config.get(CONF_PARCEL_NO), config.get(CONF_REFRESH_RATE))
    config_entry.unique_id = sensor.unique_id
    async_add_entities([sensor])


class JSONRestSensor(Entity):
    """Implementation of a REST sensor."""

    def __init__(self, hass, rest, name, streets, street_numbers, parcel_numbers, refresh_rate):
        """Initialize the REST sensor."""
        self._streets = streets if streets else []
        self._hass = hass
        self.rest = rest
        self._name = name
        self._attributes = {}
        self._state = STATE_UNKNOWN
        self._refresh_rate = datetime.timedelta(seconds=refresh_rate)
        self._last_update = datetime.datetime.now() - self._refresh_rate

    @property
    def unique_id(self):
        """Return Unique ID string."""
        return reduce((lambda x, y: "%s,%s" % (x, y)), self._streets)

    @property
    def device_info(self):
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._name), (DOMAIN, self.unique_id)},
            # If desired, the name for the device could be different to the entity
            "name": self.name,
            "sw_version": VERSION,
            "model": "REST call",
            "manufacturer": "??EZ distribuce",
        }

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    def update(self):
        """Get the latest data from REST API and update the state."""
        if self._last_update + self._refresh_rate > datetime.datetime.now():
            return
        outages = []
        outages_in_town = []
        for r in self.rest:
            self._hass.async_add_executor_job(r.update)
            value = r.data
            if value:
                if "outages" in value and value["outages"]:
                    outages += value["outages"]
                if "outages_in_town" in value and value["outages_in_town"]:
                    outages_in_town += value["outages_in_town"]
            _LOGGER.debug("Raw REST data: %s" % value)

        self._attributes['outages'] = outages
        self._attributes['outages_in_town'] = outages_in_town
        self._attributes['times'] = list(map(lambda x: {"from": x["opened_at"], "to": x["fix_expected_at"]}, outages))

        self._state = STATE_ON if outages else STATE_OFF

        self._last_update = datetime.datetime.now()

    @property
    def state_attributes(self):
        """Return the attributes of the entity.
           Provide the parsed JSON data (if any).
        """

        return self._attributes

    @property
    def device_class(self):
        return DEVICE_CLASS_PROBLEM


class JSONRestClient(object):
    """Class for handling the data retrieval."""

    def __init__(self, method, resource, auth, headers, data, verify_ssl):
        """Initialize the data object."""
        self._request = requests.Request(
            method, resource, headers=headers, auth=auth, data=data).prepare()
        self._verify_ssl = verify_ssl
        self.data = None

    def update(self):
        """Get the latest data from REST service with provided method."""
        try:
            with requests.Session() as sess:
                response = sess.send(
                    self._request, timeout=10, verify=self._verify_ssl)

            self.data = json.loads(response.text)
        except requests.exceptions.RequestException:
            _LOGGER.error("Error fetching data: %s", self._request)
            self.data = None
