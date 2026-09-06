"""Plateforme calendrier pour Calendrier Scolaire Quebecois."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SchoolCalendarConfigEntry, SchoolCalendarCoordinator
from .entity import SchoolCalendarBaseEntity
from .models import SchoolEvent

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchoolCalendarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Configure l'entite calendrier.

    Une entite unique est creee inconditionnellement pour chaque entree de
    configuration. Elle existe donc des l'installation, meme sans source
    configuree ou avant le premier telechargement reussi.

    Args:
        hass: Instance Home Assistant.
        entry: Entree de configuration.
        async_add_entities: Fonction d'ajout des entites.
    """
    async_add_entities([QuebecSchoolCalendarEntity(entry.runtime_data)])


def _to_calendar_event(event: SchoolEvent) -> CalendarEvent:
    """Traduit un evenement interne en evenement Home Assistant.

    Args:
        event: Evenement interne.

    Returns:
        Evenement au format attendu par le composant calendrier.
    """
    return CalendarEvent(
        summary=event.summary,
        start=event.start,
        end=event.end,
        description=event.description or None,
        location=event.location or None,
        uid=event.uid,
    )


class QuebecSchoolCalendarEntity(SchoolCalendarBaseEntity, CalendarEntity):
    """Calendrier regroupant les evenements de toutes les sources."""

    # L'entite principale d'un appareil porte le nom de l'appareil.
    _attr_name = None

    def __init__(self, coordinator: SchoolCalendarCoordinator) -> None:
        """Initialise l'entite calendrier.

        Args:
            coordinator: Coordinateur fournissant les evenements.
        """
        super().__init__(coordinator, "calendar")

    @property
    def available(self) -> bool:
        """Le calendrier reste disponible malgre un cycle en echec.

        Les evenements deja connus restent pertinents: un calendrier scolaire
        change rarement, et une coupure reseau momentanee ne doit pas rendre le
        calendrier inutilisable pour les automatisations.

        Returns:
            Toujours True.
        """
        return True

    @property
    def event(self) -> CalendarEvent | None:
        """Evenement en cours, ou prochain evenement a venir.

        Returns:
            Evenement le plus pertinent, ou None si le calendrier est vide.
        """
        upcoming = self.calendar_data.next_event(dt_util.now())
        return _to_calendar_event(upcoming) if upcoming else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Retourne les evenements chevauchant une periode.

        Args:
            hass: Instance Home Assistant.
            start_date: Debut de la periode demandee.
            end_date: Fin de la periode demandee, exclusive.

        Returns:
            Evenements chevauchant la periode, tries chronologiquement.
        """
        return [
            _to_calendar_event(event)
            for event in self.calendar_data.events_between(start_date, end_date)
        ]

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Attributs complementaires du calendrier.

        Returns:
            Compteurs utiles au diagnostic.
        """
        data = self.calendar_data
        return {
            "events_count": len(data.events),
            "sources_ok": data.sources_ok,
            "sources_total": data.sources_total,
        }
