"""Flux de configuration pour Calendrier Scolaire Quebecois."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, time
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    ATTR_NAME,
    CONF_ENABLE_OCR,
    CONF_FEED_SECRET,
    CONF_MANUAL_EVENTS,
    CONF_REFRESH_INTERVAL,
    CONF_SOURCES,
    CONFIG_ENTRY_VERSION,
    ICS_URL_PREFIX,
    DEFAULT_ENABLE_OCR,
    DEFAULT_NAME,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    MAX_REFRESH_INTERVAL,
    MIN_REFRESH_INTERVAL,
    SOURCE_TYPE_DIRECT_URL,
    SOURCE_TYPES,
)
from .coordinator import async_probe_source
from .fetcher import FetchError
from .models import (
    CalendarSource,
    ManualEvent,
    build_manual_event_id,
    build_source_id,
    generate_feed_secret,
    is_calendar_like,
)
from .parsers import ParserError

_LOGGER = logging.getLogger(__name__)

# Champs du formulaire d'ajout de source, partages entre le flux de
# configuration initial et le flux d'options.
_SOURCE_FIELDS = {
    vol.Optional("source_url", default=""): cv.string,
    vol.Optional("source_type", default=SOURCE_TYPE_DIRECT_URL): vol.In(SOURCE_TYPES),
}

_SETTINGS_FIELDS = {
    vol.Optional(CONF_REFRESH_INTERVAL, default=DEFAULT_REFRESH_INTERVAL): vol.All(
        vol.Coerce(int), vol.Range(min=MIN_REFRESH_INTERVAL, max=MAX_REFRESH_INTERVAL)
    ),
    vol.Optional(CONF_ENABLE_OCR, default=DEFAULT_ENABLE_OCR): cv.boolean,
}


class CalendrierScolaireQuebecoisConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gere la creation d'une entree de configuration."""

    VERSION = CONFIG_ENTRY_VERSION

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Recueille la configuration initiale.

        Args:
            user_input: Donnees saisies, ou None au premier affichage.

        Returns:
            Formulaire a afficher ou entree creee.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input.get(ATTR_NAME, "").strip() or DEFAULT_NAME
            source_url = user_input.get("source_url", "").strip()
            source_type = user_input.get("source_type", SOURCE_TYPE_DIRECT_URL)

            sources: list[dict[str, str]] = []

            if source_url:
                if not _is_http_url(source_url):
                    errors["source_url"] = "invalid_url"
                else:
                    # Une meme URL ne doit pas etre configuree deux fois.
                    await self.async_set_unique_id(build_source_id(source_url))
                    self._abort_if_unique_id_configured()

                    error = await _async_validate_source(
                        self.hass,
                        source_url,
                        source_type,
                        enable_ocr=bool(
                            user_input.get(CONF_ENABLE_OCR, DEFAULT_ENABLE_OCR)
                        ),
                    )
                    if error:
                        errors["source_url"] = error
                    else:
                        sources.append(
                            CalendarSource(
                                source_id=build_source_id(source_url),
                                name=name,
                                url=source_url,
                                source_type=source_type,
                            ).as_dict()
                        )

            if not errors:
                return self.async_create_entry(
                    title=name,
                    data={
                        ATTR_NAME: name,
                        CONF_FEED_SECRET: generate_feed_secret(),
                    },
                    options={
                        CONF_SOURCES: sources,
                        CONF_REFRESH_INTERVAL: user_input.get(
                            CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                        ),
                        CONF_ENABLE_OCR: user_input.get(
                            CONF_ENABLE_OCR, DEFAULT_ENABLE_OCR
                        ),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(ATTR_NAME, default=DEFAULT_NAME): cv.string,
                **_SOURCE_FIELDS,
                **_SETTINGS_FIELDS,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry) -> OptionsFlow:  # noqa: ANN001
        """Retourne le flux d'options associe.

        Args:
            config_entry: Entree concernee.

        Returns:
            Flux d'options.
        """
        return CalendrierScolaireQuebecoisOptionsFlow()


class CalendrierScolaireQuebecoisOptionsFlow(OptionsFlow):
    """Permet de modifier les reglages et de gerer les sources."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Affiche le menu principal des options.

        Args:
            user_input: Non utilise.

        Returns:
            Menu des actions disponibles.
        """
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "settings",
                "add_source",
                "remove_source",
                "add_manual_event",
                "edit_manual_event",
                "remove_manual_event",
                "feed",
            ],
        )

    async def async_step_feed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Affiche l'URL du flux iCalendar et permet de renouveler le secret.

        Args:
            user_input: Donnees saisies, ou None au premier affichage.

        Returns:
            Formulaire affichant l'URL, ou fin de flux.
        """
        entry = self.config_entry

        if user_input is not None:
            if not user_input.get("rotate_secret"):
                return self._save(self._options)

            # Le renouvellement invalide immediatement les abonnements existants.
            self.hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_FEED_SECRET: generate_feed_secret()},
            )
            # Le formulaire est reaffiche avec la nouvelle URL, pour que
            # l'utilisateur puisse la recopier sans rouvrir les options.

        return self.async_show_form(
            step_id="feed",
            data_schema=vol.Schema(
                {vol.Optional("rotate_secret", default=False): cv.boolean}
            ),
            description_placeholders={"url": self._feed_url()},
        )

    def _feed_url(self) -> str:
        """Construit l'URL publique du flux iCalendar.

        Returns:
            URL complete, ou un message explicatif si aucune adresse de base
            n'est configuree dans Home Assistant.
        """
        entry = self.config_entry
        secret = entry.data.get(CONF_FEED_SECRET)

        if not secret:
            return "Secret absent: rechargez l'integration."

        path = f"{ICS_URL_PREFIX}/{entry.entry_id}/{secret}.ics"

        try:
            base = get_url(self.hass, prefer_external=True)
        except NoURLAvailableError:
            return (
                f"{path} (definissez une URL externe dans Reglages > Systeme > "
                "Reseau pour obtenir l'adresse complete)"
            )

        return f"{base}{path}"

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Modifie l'intervalle de rafraichissement et l'OCR.

        Args:
            user_input: Donnees saisies, ou None au premier affichage.

        Returns:
            Formulaire a afficher ou options enregistrees.
        """
        if user_input is not None:
            return self._save({**self._options, **user_input})

        current = self._options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_REFRESH_INTERVAL,
                    default=current.get(
                        CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_REFRESH_INTERVAL, max=MAX_REFRESH_INTERVAL),
                ),
                vol.Optional(
                    CONF_ENABLE_OCR,
                    default=current.get(CONF_ENABLE_OCR, DEFAULT_ENABLE_OCR),
                ): cv.boolean,
            }
        )

        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_add_source(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ajoute une source de calendrier.

        Args:
            user_input: Donnees saisies, ou None au premier affichage.

        Returns:
            Formulaire a afficher ou options enregistrees.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input.get("source_url", "").strip()
            sources = self._sources

            if not _is_http_url(url):
                errors["source_url"] = "invalid_url"
            elif any(item.get("url") == url for item in sources):
                errors["source_url"] = "already_exists"
            else:
                source_type = user_input.get("source_type", SOURCE_TYPE_DIRECT_URL)
                error = await _async_validate_source(
                    self.hass,
                    url,
                    source_type,
                    enable_ocr=bool(
                        self._options.get(CONF_ENABLE_OCR, DEFAULT_ENABLE_OCR)
                    ),
                )
                if error:
                    errors["source_url"] = error
                else:
                    sources.append(
                        CalendarSource(
                            source_id=build_source_id(url),
                            name=user_input.get(ATTR_NAME, "").strip() or url,
                            url=url,
                            source_type=source_type,
                        ).as_dict()
                    )
                    return self._save({**self._options, CONF_SOURCES: sources})

        schema = vol.Schema(
            {
                vol.Required(ATTR_NAME, default=""): cv.string,
                vol.Required("source_url"): cv.string,
                vol.Optional("source_type", default=SOURCE_TYPE_DIRECT_URL): vol.In(
                    SOURCE_TYPES
                ),
            }
        )

        return self.async_show_form(
            step_id="add_source", data_schema=schema, errors=errors
        )

    async def async_step_remove_source(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Retire une ou plusieurs sources de calendrier.

        Args:
            user_input: Donnees saisies, ou None au premier affichage.

        Returns:
            Formulaire a afficher, abandon si aucune source, ou options
            enregistrees.
        """
        sources = self._sources

        if not sources:
            return self.async_abort(reason="no_sources")

        if user_input is not None:
            to_remove = set(user_input.get("sources", []))
            remaining = [item for item in sources if item.get("id") not in to_remove]
            return self._save({**self._options, CONF_SOURCES: remaining})

        choices = {
            item["id"]: f"{item.get('name') or item['url']} ({item['url']})"
            for item in sources
        }

        schema = vol.Schema(
            {vol.Required("sources", default=[]): cv.multi_select(choices)}
        )

        return self.async_show_form(step_id="remove_source", data_schema=schema)

    async def async_step_add_manual_event(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ajoute un evenement saisi a la main, ponctuel ou recurrent.

        Args:
            user_input: Donnees saisies, ou None au premier affichage.

        Returns:
            Formulaire a afficher ou options enregistrees.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            rule, error = _build_manual_rule(user_input)
            events = self._manual_events
            if error:
                errors["base"] = error
            elif any(item.get("id") == rule.event_id for item in events):
                errors["base"] = "manual_event_exists"
            else:
                events.append(rule.as_dict())
                return self._save({**self._options, CONF_MANUAL_EVENTS: events})
        return self.async_show_form(
            step_id="add_manual_event",
            data_schema=self.add_suggested_values_to_schema(
                _MANUAL_EVENT_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_edit_manual_event(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choisit l'evenement manuel a modifier.

        Args:
            user_input: Donnees saisies, ou None au premier affichage.

        Returns:
            Liste de choix, abandon si aucun evenement, ou formulaire de
            modification de l'evenement choisi.
        """
        events = self._manual_events
        if not events:
            return self.async_abort(reason="no_manual_events")
        if user_input is not None:
            chosen = user_input["manual_event"]
            if any(item.get("id") == chosen for item in events):
                self._editing_manual_id = chosen
                return await self.async_step_update_manual_event()
        options = [
            selector.SelectOptionDict(
                value=item["id"], label=_describe_manual_event(item)
            )
            for item in events
            if item.get("id")
        ]
        schema = vol.Schema(
            {
                vol.Required("manual_event"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, mode=selector.SelectSelectorMode.LIST
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_manual_event", data_schema=schema)

    async def async_step_update_manual_event(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Modifie l'evenement manuel choisi, formulaire prerempli.

        L'identifiant derive du contenu de la regle (titre, premiere date, jours,
        heure de debut): il est donc recalcule, et l'ancien disparait. Une
        modification qui reproduit un autre evenement existant est refusee.

        Args:
            user_input: Donnees saisies, ou None au premier affichage.

        Returns:
            Formulaire a afficher ou options enregistrees.
        """
        events = self._manual_events
        current = next(
            (item for item in events if item.get("id") == self._editing_manual_id),
            None,
        )
        if current is None:
            return self.async_abort(reason="no_manual_events")
        errors: dict[str, str] = {}
        if user_input is not None:
            rule, error = _build_manual_rule(user_input)
            if error:
                errors["base"] = error
            elif any(
                item.get("id") == rule.event_id and item is not current
                for item in events
            ):
                errors["base"] = "manual_event_exists"
            else:
                rule = _keep_excluded_dates(rule, current)
                updated = [
                    rule.as_dict() if item is current else item for item in events
                ]
                return self._save({**self._options, CONF_MANUAL_EVENTS: updated})
        suggested = user_input if user_input is not None else _form_values(current)
        return self.async_show_form(
            step_id="update_manual_event",
            data_schema=self.add_suggested_values_to_schema(
                _MANUAL_EVENT_SCHEMA, suggested
            ),
            errors=errors,
        )

    async def async_step_remove_manual_event(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Retire un ou plusieurs evenements manuels.

        Args:
            user_input: Donnees saisies, ou None au premier affichage.

        Returns:
            Formulaire a afficher, abandon si aucun evenement, ou options
            enregistrees.
        """
        events = self._manual_events
        if not events:
            return self.async_abort(reason="no_manual_events")
        if user_input is not None:
            to_remove = set(user_input.get("manual_events", []))
            remaining = [item for item in events if item.get("id") not in to_remove]
            return self._save({**self._options, CONF_MANUAL_EVENTS: remaining})
        choices = {
            item["id"]: _describe_manual_event(item)
            for item in events
            if item.get("id")
        }
        schema = vol.Schema(
            {vol.Required("manual_events", default=[]): cv.multi_select(choices)}
        )
        return self.async_show_form(step_id="remove_manual_event", data_schema=schema)

    # --- Utilitaires ---------------------------------------------------------

    @property
    def _options(self) -> dict[str, Any]:
        """Copie modifiable des options courantes."""
        return dict(self.config_entry.options)

    @property
    def _sources(self) -> list[dict[str, str]]:
        """Copie modifiable de la liste des sources."""
        raw = self.config_entry.options.get(CONF_SOURCES) or []
        return [dict(item) for item in raw if isinstance(item, dict)]

    _editing_manual_id: str | None = None

    @property
    def _manual_events(self) -> list[dict[str, Any]]:
        """Copie modifiable de la liste des evenements manuels."""
        raw = self.config_entry.options.get(CONF_MANUAL_EVENTS) or []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def _save(self, options: dict[str, Any]) -> ConfigFlowResult:
        """Enregistre les options.

        Home Assistant remplace integralement les options par les donnees
        fournies: l'appelant doit donc transmettre le dictionnaire complet.

        Args:
            options: Options completes a enregistrer.

        Returns:
            Resultat de fin de flux.
        """
        return self.async_create_entry(title="", data=options)


_WEEKDAY_LABELS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")

_MANUAL_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required("summary"): selector.TextSelector(),
        vol.Required("start_date"): selector.DateSelector(),
        vol.Optional("end_date"): selector.DateSelector(),
        vol.Optional("weekdays", default=[]): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[str(day) for day in range(7)],
                multiple=True,
                translation_key="weekdays",
                mode=selector.SelectSelectorMode.LIST,
            )
        ),
        vol.Optional("start_time"): selector.TimeSelector(),
        vol.Optional("end_time"): selector.TimeSelector(),
        vol.Optional("skip_closures", default=True): selector.BooleanSelector(),
    }
)


def _parse_form_time(value: Any) -> time | None:
    """Lit une heure du formulaire ("HH:MM" ou "HH:MM:SS"), vide si absente."""
    if not value:
        return None
    return cv.time(value)


def _build_manual_rule(
    user_input: dict[str, Any],
) -> tuple[ManualEvent | None, str | None]:
    """Construit une regle d'evenement manuel a partir du formulaire.

    Args:
        user_input: Donnees du formulaire d'ajout.

    Returns:
        Couple (regle, None) si la saisie est valide, sinon (None, cle d'erreur).
    """
    summary = str(user_input.get("summary", "")).strip()
    if not summary:
        return None, "manual_event_summary_required"
    try:
        start_date = date.fromisoformat(user_input["start_date"])
        end_date = (
            date.fromisoformat(user_input["end_date"])
            if user_input.get("end_date")
            else start_date
        )
        start_time = _parse_form_time(user_input.get("start_time"))
        end_time = _parse_form_time(user_input.get("end_time"))
    except (ValueError, KeyError, vol.Invalid):
        return None, "manual_event_invalid"
    if end_date < start_date:
        return None, "manual_event_range"
    if (start_time is None) != (end_time is None):
        return None, "manual_event_times_together"
    if start_time and end_time and end_time <= start_time:
        return None, "manual_event_times_order"
    weekdays = tuple(sorted({int(day) for day in user_input.get("weekdays") or []}))
    try:
        rule = ManualEvent(
            event_id=build_manual_event_id(summary, start_date, weekdays, start_time),
            summary=summary,
            start_date=start_date,
            end_date=end_date,
            weekdays=weekdays,
            start_time=start_time,
            end_time=end_time,
            skip_closures=bool(user_input.get("skip_closures", True)),
        )
    except ValueError:
        return None, "manual_event_invalid"
    return rule, None


def _keep_excluded_dates(rule: ManualEvent, stored: dict[str, Any]) -> ManualEvent:
    """Reporte sur la regle modifiee les journees deja retirees une a une.

    Le formulaire ne les montre pas: sans ce report, modifier un evenement
    ferait reapparaitre les occurrences supprimees depuis la vue des calendriers.
    Celles qui tombent hors de la nouvelle plage sont abandonnees.
    """
    try:
        previous = ManualEvent.from_dict(stored).excluded_dates
    except ValueError:
        return rule
    kept = tuple(day for day in previous if rule.start_date <= day <= rule.end_date)
    return replace(rule, excluded_dates=kept) if kept else rule


def _form_values(item: dict[str, Any]) -> dict[str, Any]:
    """Convertit une regle stockee en valeurs de formulaire.

    Les jours de semaine redeviennent des chaines (le selecteur en attend) et
    les champs absents sont omis plutot que mis a vide.
    """
    values: dict[str, Any] = {
        "summary": item.get("summary", ""),
        "start_date": item.get("start_date"),
        "end_date": item.get("end_date"),
        "weekdays": [str(day) for day in item.get("weekdays") or []],
        "skip_closures": bool(item.get("skip_closures", True)),
    }
    if item.get("start_time") and item.get("end_time"):
        values["start_time"] = item["start_time"]
        values["end_time"] = item["end_time"]
    return {key: value for key, value in values.items() if value is not None}


def _describe_manual_event(item: dict[str, Any]) -> str:
    """Decrit une regle stockee pour la liste de retrait."""
    summary = item.get("summary") or item.get("id")
    days = ", ".join(
        _WEEKDAY_LABELS[day]
        for day in item.get("weekdays") or []
        if isinstance(day, int) and 0 <= day <= 6
    )
    start, end = item.get("start_date"), item.get("end_date")
    period = start if not days or start == end else f"{start} > {end}"
    hours = (
        f" {item['start_time']}-{item['end_time']}"
        if item.get("start_time") and item.get("end_time")
        else ""
    )
    return f"{summary} ({days + ', ' if days else ''}{period}{hours})"


def _is_http_url(value: str) -> bool:
    """Verifie qu'une chaine est une URL HTTP ou HTTPS.

    Args:
        value: Chaine a verifier.

    Returns:
        True si la chaine est une URL utilisable.
    """
    try:
        cv.url(value)
    except vol.Invalid:
        return False
    return True


async def _async_validate_source(
    hass: HomeAssistant,
    url: str,
    source_type: str,
    *,
    enable_ocr: bool,
) -> str | None:
    """Verifie qu'une URL fournit reellement un calendrier scolaire.

    Une adresse joignable ne suffit pas: le document est telecharge et analyse,
    et il est refuse s'il ne porte aucun marqueur de calendrier scolaire. Cela
    evite qu'un reglement ou une page quelconque cree un calendrier vide ou
    rempli de faux evenements.

    Args:
        hass: Instance Home Assistant.
        url: Adresse saisie par l'utilisateur.
        source_type: Type de source declare.
        enable_ocr: Autorise le repli OCR pendant la validation.

    Returns:
        None si la source est valide, sinon la cle d'erreur a afficher.
    """
    try:
        events = await async_probe_source(hass, url, source_type, enable_ocr=enable_ocr)
    except FetchError as err:
        _LOGGER.debug("Validation impossible, '%s' inaccessible: %s", url, err)
        return "cannot_connect"
    except ParserError as err:
        _LOGGER.debug("Validation impossible, '%s' illisible: %s", url, err)
        return "not_a_calendar"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Erreur inattendue pendant la validation de '%s'", url)
        return "unknown"

    if not is_calendar_like(events):
        _LOGGER.debug(
            "'%s' ne porte aucun marqueur de calendrier scolaire (%d evenement(s) "
            "non types)",
            url,
            len(events),
        )
        return "not_a_calendar"

    return None
