import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_TIMEOUT
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from . import DOMAIN, CONF_METERS, CONF_INVOICES, AuthenticationFailedException, PartialOfflineException, \
    CONF_CONTRACTS, DEFAULT_SCAN_INTERVAL, DEFAULT_INVERT_INVOICES, CONF_INVERT_INVOICES, AUTHENTICATION_SUBCONFIG, \
    OPTIONS_SUBCONFIG, DEFAULT_FILTER_SUBCONFIG, INTERVALS_SUBCONFIG, DEFAULT_TIMEOUT
from .mosoblgaz import MosoblgazException

_LOGGER = logging.getLogger(__name__)

CONF_ENABLE_CONTRACT = "enable_contract"
CONF_ADD_ALL_CONTRACTS = "add_all_contracts"


class MosoblgazFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mosoblgaz config entries."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        """Instantiate config flow."""
        self._contracts = None
        self._last_contract_id = None
        self._current_config = None

        from collections import OrderedDict

        self.schema_user = vol.Schema(OrderedDict(AUTHENTICATION_SUBCONFIG))

    async def _check_entry_exists(self, username: str):
        current_entries = self._async_current_entries()

        for config_entry in current_entries:
            if config_entry.data.get(CONF_USERNAME) == username:
                return True

        return False

    # Initial step for user interaction
    async def async_step_user(self, user_input=None):
        """Handle a flow start."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=self.schema_user)

        username = user_input[CONF_USERNAME]

        if await self._check_entry_exists(username):
            return self.async_abort("already_exists")

        from .mosoblgaz import MosoblgazAPI

        try:
            api = MosoblgazAPI(username=username, password=user_input[CONF_PASSWORD])
            await api.authenticate()
            contracts = await api.fetch_contracts(with_data=False)

            if not contracts:
                return self.async_abort("contracts_missing")

        except AuthenticationFailedException:
            # @TODO: display captcha
            return self.async_show_form(step_id="user", data_schema=self.schema_user,
                                        errors={"base": "invalid_credentials"})

        except PartialOfflineException:
            return self.async_abort("partial_offline")

        except MosoblgazException:
            return self.async_abort("api_error")

        if not user_input.get(CONF_ADD_ALL_CONTRACTS):
            self._current_config = {**user_input, CONF_CONTRACTS: {}}
            self._contracts = contracts
            return await self.async_step_contract()

        return self.async_create_entry(title="User: " + username, data=user_input)

    async def async_step_contract(self, user_input=None):
        if self._last_contract_id is None:
            contract_id = list(self._contracts.keys())[0]
            del self._contracts[contract_id]
            self._last_contract_id = contract_id

        else:
            contract_id = self._last_contract_id

        if user_input is None:
            return self.async_show_form(step_id="contract",
                                        data_schema=self.schema_contract,
                                        description_placeholders={"code": contract_id})

        if user_input.get(CONF_ENABLE_CONTRACT):
            contract_config = {
                CONF_METERS: user_input.get(CONF_METERS),
                CONF_INVOICES: user_input.get(CONF_INVOICES),
            }

        else:
            contract_config = False

        self._current_config[CONF_CONTRACTS][contract_id] = contract_config

        if self._contracts:
            return await self.async_step_contract()

        if all(filter(lambda x: not x, self._current_config[CONF_CONTRACTS].values())):
            return self.async_abort('nothing_enabled')

        return self.async_create_entry(title='User: ' + u)

    async def async_step_import(self, user_input=None):
        if user_input is None:
            return self.async_abort("unknown_error")

        username = user_input[CONF_USERNAME]

        if await self._check_entry_exists(username):
            return self.async_abort("already_exists")

        return self.async_create_entry(title="User: " + username, data={CONF_USERNAME: username})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Mosoblgaz options callback."""
        return MosoblgazOptionsFlowHandler(config_entry)


class MosoblgazOptionsFlowHandler(config_entries.OptionsFlow):
    """Mosoblgaz options flow handler"""
    def __init__(self, config_entry: ConfigEntry):
        """Initialize Mosoblgaz options flow handler"""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """
        Options flow entry point.
        :param user_input: User input mapping
        :return: Flow response
        """
        if self.config_entry.source == SOURCE_IMPORT:
            return await self.async_step_import(user_input=user_input)

        return await self.async_step_user(user_input=user_input)

    async def async_step_import(self, user_input=None):
        """
        Callback for entries imported from YAML.
        :param user_input: User input mapping
        :return: Flow response
        """
        return self.async_show_form(
            step_id="import",
            data_schema=vol.Schema({
                vol.Optional("not_in_use", default=False): cv.boolean,
            })
        )

    async def async_step_user(self, user_input=None):
        """
        Callback for entries created via "Integrations" UI.
        :param user_input: User input mapping
        :return: Flow response
        """
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options or {}

        if self.config_entry.version == 1:
            _LOGGER.debug('Version 1 config entry detected, merging initial data')
            options = {**self.config_entry.data, **options}

        default_invert_invoices = options.get(CONF_INVERT_INVOICES, DEFAULT_INVERT_INVOICES)
        default_timeout = options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT.total_seconds())
        default_scan_interval = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds())

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_INVERT_INVOICES, default=default_invert_invoices): cv.boolean,
                    vol.Optional(CONF_TIMEOUT, default=default_timeout): cv.positive_int,
                    vol.Optional(CONF_SCAN_INTERVAL, default=default_scan_interval): cv.positive_int,
                }
            )
        )