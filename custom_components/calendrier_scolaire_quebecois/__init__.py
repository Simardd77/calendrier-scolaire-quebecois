"""Integration Calendrier Scolaire Quebecois pour Home Assistant."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_END_DATE,
    ATTR_END_TIME,
    ATTR_EVENT_ID,
    ATTR_FILE_PATH,
    ATTR_NAME,
    ATTR_SKIP_CLOSURES,
    ATTR_SOURCE_ID,
    ATTR_SOURCE_TYPE,
    ATTR_SOURCE_URL,
    ATTR_START_DATE,
    ATTR_START_TIME,
    ATTR_SUMMARY,
    ATTR_WEEKDAYS,
    CONF_ENABLE_OCR,
    CONF_MANUAL_EVENTS,
    CONF_SOURCES,
    DEFAULT_ENABLE_OCR,
    DOMAIN,
    PLATFORMS,
    SERVICE_ADD_MANUAL_EVENT,
    SERVICE_ADD_SOURCE,
    SERVICE_PARSE_PDF,
    SERVICE_REFRESH_CALENDAR,
    SERVICE_REMOVE_MANUAL_EVENT,
    SERVICE_REMOVE_SOURCE,
    SOURCE_TYPE_DIRECT_URL,
    SOURCE_TYPES,
)
from .coordinator import (
    SchoolCalendarConfigEntry,
    SchoolCalendarCoordinator,
    async_probe_source,
)
from .fetcher import FetchError
from .http import SchoolCalendarIcsView
from .models import (
    CalendarSource,
    ManualEvent,
    build_manual_event_id,
    build_source_id,
    is_calendar_like,
)
from .parsers import ParserError

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_ADD_SOURCE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_NAME): cv.string,
        vol.Required(ATTR_SOURCE_URL): cv.url,
        vol.Optional(ATTR_SOURCE_TYPE, default=SOURCE_TYPE_DIRECT_URL): vol.In(
            SOURCE_TYPES
        ),
    }
)

SERVICE_REMOVE_SOURCE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SOURCE_ID): cv.string,
    }
)

SERVICE_REFRESH_CALENDAR_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

SERVICE_PARSE_PDF_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_FILE_PATH): cv.string,
    }
)

# Un jour de semaine est accepte comme nom (francais ou anglais, sans accent ni
# casse) ou comme entier 0-6 (lundi=0). Le selecteur de l'interface envoie des
# entiers; un appel ecrit a la main tolere les deux formes.
_WEEKDAY_NAMES: dict[str, int] = {
    "lundi": 0,
    "monday": 0,
    "mardi": 1,
    "tuesday": 1,
    "mercredi": 2,
    "wednesday": 2,
    "jeudi": 3,
    "thursday": 3,
    "vendredi": 4,
    "friday": 4,
    "samedi": 5,
    "saturday": 5,
    "dimanche": 6,
    "sunday": 6,
}


def _coerce_weekday(value: object) -> int:
    """Convertit un jour de semaine (nom ou entier) en indice 0-6."""
    if isinstance(value, bool):  # bool est un int en Python: a exclure d'abord.
        raise vol.Invalid("Jour de semaine invalide")
    if isinstance(value, int):
        if 0 <= value <= 6:
            return value
        raise vol.Invalid(f"Jour de semaine hors bornes: {value}")
    if isinstance(value, str):
        texte = value.strip().lower()
        if texte.isdigit():
            return _coerce_weekday(int(texte))
        if texte in _WEEKDAY_NAMES:
            return _WEEKDAY_NAMES[texte]
    raise vol.Invalid(f"Jour de semaine non reconnu: {value!r}")


SERVICE_ADD_MANUAL_EVENT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_SUMMARY): cv.string,
        vol.Required(ATTR_START_DATE): cv.date,
        vol.Required(ATTR_END_DATE): cv.date,
        vol.Optional(ATTR_WEEKDAYS, default=list): vol.All(
            cv.ensure_list, [_coerce_weekday]
        ),
        vol.Optional(ATTR_START_TIME): cv.time,
        vol.Optional(ATTR_END_TIME): cv.time,
        vol.Optional(ATTR_SKIP_CLOSURES, default=True): cv.boolean,
    }
)

SERVICE_REMOVE_MANUAL_EVENT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_EVENT_ID): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Enregistre les services du domaine.

    Les services sont enregistres une seule fois, independamment du nombre
    d'entrees de configuration. Chaque appel resout dynamiquement l'entree
    ciblee, ce qui evite qu'une seconde entree ecrase les gestionnaires de la
    premiere.

    Args:
        hass: Instance Home Assistant.
        config: Configuration YAML globale.

    Returns:
        True, l'enregistrement ne peut pas echouer.
    """
    _async_register_services(hass)

    # La vue est globale et resout l'entree ciblee a chaque requete: un seul
    # enregistrement suffit, quel que soit le nombre d'entrees.
    hass.http.register_view(SchoolCalendarIcsView(hass))

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: SchoolCalendarConfigEntry
) -> bool:
    """Configure une entree de configuration.

    Args:
        hass: Instance Home Assistant.
        entry: Entree a configurer.

    Returns:
        True si la configuration a reussi.
    """
    coordinator = SchoolCalendarCoordinator(hass, entry)
    entry.runtime_data = coordinator

    # async_refresh est utilise volontairement a la place de
    # async_config_entry_first_refresh: une source injoignable ne doit pas
    # empecher la creation des entites. Le calendrier existe donc toujours, et
    # l'etat du telechargement est visible via le capteur d'etat.
    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        _LOGGER.warning(
            "Premiere recuperation en echec pour '%s'. Les entites sont creees "
            "et une nouvelle tentative aura lieu automatiquement",
            entry.title,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SchoolCalendarConfigEntry
) -> bool:
    """Decharge une entree de configuration.

    Args:
        hass: Instance Home Assistant.
        entry: Entree a decharger.

    Returns:
        True si toutes les plateformes ont ete dechargees.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: SchoolCalendarConfigEntry
) -> None:
    """Recharge l'entree lorsque ses options changent.

    Le rechargement est delegue a Home Assistant plutot que reimplemente par un
    enchainement decharger/configurer, qui laissait un coordinateur orphelin.

    Args:
        hass: Instance Home Assistant.
        entry: Entree modifiee.
    """
    await hass.config_entries.async_reload(entry.entry_id)


# --- Services ----------------------------------------------------------------


def _loaded_entries(hass: HomeAssistant) -> list[SchoolCalendarConfigEntry]:
    """Retourne les entrees du domaine actuellement chargees.

    Args:
        hass: Instance Home Assistant.

    Returns:
        Entrees chargees.
    """
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def _resolve_entries(
    hass: HomeAssistant, call: ServiceCall
) -> list[SchoolCalendarConfigEntry]:
    """Determine les entrees visees par un appel de service.

    Args:
        hass: Instance Home Assistant.
        call: Appel de service.

    Returns:
        Entrees ciblees.

    Raises:
        ServiceValidationError: Si aucune entree ne correspond.
    """
    entries = _loaded_entries(hass)

    if not entries:
        raise ServiceValidationError(
            "Aucun calendrier scolaire n'est charge actuellement"
        )

    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)

    if entry_id is None:
        return entries

    matching = [entry for entry in entries if entry.entry_id == entry_id]

    if not matching:
        raise ServiceValidationError(
            f"Aucun calendrier scolaire charge avec l'identifiant '{entry_id}'"
        )

    return matching


def _resolve_single_entry(
    hass: HomeAssistant, call: ServiceCall
) -> SchoolCalendarConfigEntry:
    """Determine l'entree unique visee par un appel de service.

    Args:
        hass: Instance Home Assistant.
        call: Appel de service.

    Returns:
        Entree ciblee.

    Raises:
        ServiceValidationError: Si la cible est ambigue.
    """
    entries = _resolve_entries(hass, call)

    if len(entries) > 1:
        raise ServiceValidationError(
            "Plusieurs calendriers scolaires sont configures. Precisez "
            f"'{ATTR_CONFIG_ENTRY_ID}' pour designer celui a modifier"
        )

    return entries[0]


def _stored_sources(entry: SchoolCalendarConfigEntry) -> list[dict[str, str]]:
    """Lit la liste des sources stockees dans une entree.

    Args:
        entry: Entree de configuration.

    Returns:
        Copie de la liste des sources.
    """
    raw = entry.options.get(CONF_SOURCES) or []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _stored_manual_events(entry: SchoolCalendarConfigEntry) -> list[dict]:
    """Lit la liste des evenements manuels stockes dans une entree.

    Args:
        entry: Entree de configuration.

    Returns:
        Copie de la liste des regles manuelles.
    """
    raw = entry.options.get(CONF_MANUAL_EVENTS) or []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _async_register_services(hass: HomeAssistant) -> None:
    """Declare les services du domaine s'ils ne le sont pas deja.

    Args:
        hass: Instance Home Assistant.
    """
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH_CALENDAR):
        return

    async def handle_add_source(call: ServiceCall) -> None:
        """Ajoute une source de calendrier a une entree."""
        entry = _resolve_single_entry(hass, call)
        url = call.data[ATTR_SOURCE_URL]
        sources = _stored_sources(entry)

        if any(item.get("url") == url for item in sources):
            raise ServiceValidationError(
                f"La source '{url}' est deja configuree pour '{entry.title}'"
            )

        # Le service est un point d'entree a part entiere: il doit refuser une
        # adresse qui n'est pas un calendrier, comme le fait le formulaire.
        try:
            probed = await async_probe_source(
                hass,
                url,
                call.data[ATTR_SOURCE_TYPE],
                enable_ocr=bool(entry.options.get(CONF_ENABLE_OCR, DEFAULT_ENABLE_OCR)),
            )
        except (FetchError, ParserError) as err:
            raise ServiceValidationError(
                f"La source '{url}' n'a pas pu etre validee: {err}"
            ) from err

        if not is_calendar_like(probed):
            raise ServiceValidationError(
                f"'{url}' ne semble pas etre un calendrier scolaire: aucun conge, "
                "journee pedagogique, relache ni rentree n'y a ete trouve. Si "
                "c'est un PDF numerise, activez l'OCR avant de reessayer."
            )

        sources.append(
            CalendarSource(
                source_id=build_source_id(url),
                name=call.data[ATTR_NAME],
                url=url,
                source_type=call.data[ATTR_SOURCE_TYPE],
            ).as_dict()
        )

        # La mise a jour declenche le rechargement de l'entree, qui relance une
        # recuperation complete.
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SOURCES: sources}
        )
        _LOGGER.info("Source '%s' ajoutee a '%s'", url, entry.title)

    async def handle_remove_source(call: ServiceCall) -> None:
        """Retire une source de calendrier d'une entree."""
        entry = _resolve_single_entry(hass, call)
        identifier = call.data[ATTR_SOURCE_ID]
        sources = _stored_sources(entry)

        remaining = [
            item
            for item in sources
            if item.get("id") != identifier and item.get("url") != identifier
        ]

        if len(remaining) == len(sources):
            raise ServiceValidationError(
                f"Aucune source '{identifier}' dans '{entry.title}'"
            )

        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SOURCES: remaining}
        )
        _LOGGER.info("Source '%s' retiree de '%s'", identifier, entry.title)

    async def handle_refresh_calendar(call: ServiceCall) -> None:
        """Force une recuperation immediate des sources."""
        for entry in _resolve_entries(hass, call):
            await entry.runtime_data.async_request_refresh()

    async def handle_parse_pdf(call: ServiceCall) -> ServiceResponse:
        """Analyse un PDF local et retourne les evenements extraits."""
        entry = _resolve_single_entry(hass, call)
        events = await entry.runtime_data.async_parse_pdf_file(
            call.data[ATTR_FILE_PATH]
        )

        _LOGGER.info(
            "%d evenement(s) extrait(s) de '%s'",
            len(events),
            call.data[ATTR_FILE_PATH],
        )

        return {
            "count": len(events),
            "events": [
                {
                    "summary": event.summary,
                    "first_day": event.first_day.isoformat(),
                    "last_day": event.last_day.isoformat(),
                    "category": event.category.value,
                }
                for event in events
            ],
        }

    async def handle_add_manual_event(call: ServiceCall) -> ServiceResponse:
        """Ajoute un evenement manuel a une entree et retourne son identifiant."""
        entry = _resolve_single_entry(hass, call)

        weekdays = tuple(sorted(set(call.data[ATTR_WEEKDAYS])))
        start_time = call.data.get(ATTR_START_TIME)
        end_time = call.data.get(ATTR_END_TIME)

        try:
            rule = ManualEvent(
                event_id=build_manual_event_id(
                    call.data[ATTR_SUMMARY],
                    call.data[ATTR_START_DATE],
                    weekdays,
                    start_time,
                ),
                summary=call.data[ATTR_SUMMARY],
                start_date=call.data[ATTR_START_DATE],
                end_date=call.data[ATTR_END_DATE],
                weekdays=weekdays,
                start_time=start_time,
                end_time=end_time,
                skip_closures=call.data[ATTR_SKIP_CLOSURES],
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

        events = _stored_manual_events(entry)
        if any(item.get("id") == rule.event_id for item in events):
            raise ServiceValidationError(
                f"Un evenement manuel identique existe deja dans '{entry.title}'"
            )

        events.append(rule.as_dict())
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_MANUAL_EVENTS: events}
        )
        _LOGGER.info("Evenement manuel '%s' ajoute a '%s'", rule.summary, entry.title)

        return {ATTR_EVENT_ID: rule.event_id}

    async def handle_remove_manual_event(call: ServiceCall) -> None:
        """Retire un evenement manuel d'une entree par son identifiant."""
        entry = _resolve_single_entry(hass, call)
        event_id = call.data[ATTR_EVENT_ID]
        events = _stored_manual_events(entry)

        remaining = [item for item in events if item.get("id") != event_id]
        if len(remaining) == len(events):
            raise ServiceValidationError(
                f"Aucun evenement manuel '{event_id}' dans '{entry.title}'"
            )

        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_MANUAL_EVENTS: remaining}
        )
        _LOGGER.info("Evenement manuel '%s' retire de '%s'", event_id, entry.title)

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_SOURCE, handle_add_source, schema=SERVICE_ADD_SOURCE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_SOURCE,
        handle_remove_source,
        schema=SERVICE_REMOVE_SOURCE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_CALENDAR,
        handle_refresh_calendar,
        schema=SERVICE_REFRESH_CALENDAR_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PARSE_PDF,
        handle_parse_pdf,
        schema=SERVICE_PARSE_PDF_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_MANUAL_EVENT,
        handle_add_manual_event,
        schema=SERVICE_ADD_MANUAL_EVENT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_MANUAL_EVENT,
        handle_remove_manual_event,
        schema=SERVICE_REMOVE_MANUAL_EVENT_SCHEMA,
    )

    _LOGGER.debug("Services du domaine %s enregistres", DOMAIN)
