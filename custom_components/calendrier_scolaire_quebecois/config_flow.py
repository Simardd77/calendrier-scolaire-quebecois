"""Flux de configuration pour Calendrier Scolaire Quebecois."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    ATTR_NAME,
    CONF_ENABLE_OCR,
    CONF_FEED_SECRET,
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
            menu_options=["settings", "add_source", "remove_source", "feed"],
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
