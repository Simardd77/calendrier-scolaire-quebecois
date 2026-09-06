"""Point d'acces HTTP publiant le calendrier au format iCalendar.

Home Assistant n'expose pas ses entites calendrier sous forme de flux
iCalendar. Ce point d'acces comble ce manque pour que l'application Calendrier
d'un telephone puisse s'abonner au calendrier scolaire.

Securite: l'acces ne peut pas etre authentifie par un jeton Home Assistant, une
application de calendrier ne sachant pas en presenter un. L'autorisation repose
donc sur un secret contenu dans l'URL, ce qui fait de cette URL un identifiant a
part entiere. L'acces est en lecture seule et le secret est renouvelable depuis
les options de l'integration.
"""

from __future__ import annotations

import hmac
import logging
from http import HTTPStatus

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import CONF_FEED_SECRET, CONTENT_TYPE_ICS, DOMAIN, ICS_URL_PREFIX
from .ics import build_ics

_LOGGER = logging.getLogger(__name__)


class SchoolCalendarIcsView(HomeAssistantView):
    """Sert le calendrier scolaire d'une entree sous forme de flux iCalendar."""

    url = f"{ICS_URL_PREFIX}/{{entry_id}}/{{secret}}"
    name = f"api:{DOMAIN}:ics"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise la vue.

        Args:
            hass: Instance Home Assistant, conservee car la vue est enregistree
                globalement et resout l'entree ciblee a chaque requete.
        """
        self.hass = hass

    async def get(
        self, request: web.Request, entry_id: str, secret: str
    ) -> web.Response:
        """Retourne le flux iCalendar d'une entree de configuration.

        Args:
            request: Requete entrante.
            entry_id: Identifiant de l'entree de configuration.
            secret: Secret extrait de l'URL.

        Returns:
            Le flux iCalendar, ou une reponse d'erreur.
        """
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            return web.Response(text="404: Not Found", status=HTTPStatus.NOT_FOUND)

        expected = entry.data.get(CONF_FEED_SECRET)

        # Certains clients ajoutent l'extension d'eux-memes, et elle rend l'URL
        # plus explicite lorsqu'elle est collee a la main.
        supplied = secret[:-4] if secret.endswith(".ics") else secret

        if not expected or not supplied:
            _LOGGER.debug("Flux demande sans secret pour l'entree '%s'", entry.title)
            return web.Response(text="403: Forbidden", status=HTTPStatus.FORBIDDEN)

        if not hmac.compare_digest(supplied, str(expected)):
            _LOGGER.warning(
                "Flux demande avec un secret invalide pour '%s'", entry.title
            )
            return web.Response(
                text="401: Unauthorized", status=HTTPStatus.UNAUTHORIZED
            )

        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is None:
            return web.Response(
                text="503: Service Unavailable",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )

        data = coordinator.data
        events = list(data.events) if data is not None else []

        # Un calendrier vide reste un flux valide: l'abonnement se cree et se
        # remplira au prochain cycle, plutot que d'echouer chez le client.
        body = build_ics(entry.title, events)

        _LOGGER.debug(
            "Flux iCalendar servi pour '%s' (%d evenement(s))",
            entry.title,
            len(events),
        )

        return web.Response(text=body, content_type=CONTENT_TYPE_ICS)
