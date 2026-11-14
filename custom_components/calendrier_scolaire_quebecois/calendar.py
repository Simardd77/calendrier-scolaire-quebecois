"""Plateforme calendrier pour Calendrier Scolaire Quebecois."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SchoolCalendarConfigEntry, SchoolCalendarCoordinator
from .entity import SchoolCalendarBaseEntity
from .manual_rule import (
    add_manual_rule,
    delete_manual_occurrence,
    manual_event_from_calendar,
)
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
    manual_id = event.extra.get("manual_event_id")
    return CalendarEvent(
        summary=event.summary,
        start=event.start,
        end=event.end,
        description=event.description or None,
        location=event.location or None,
        uid=manual_id or event.uid,
        recurrence_id=event.extra.get("manual_recurrence_id") or None,
        rrule=event.extra.get("manual_rrule") or None,
    )


class QuebecSchoolCalendarEntity(SchoolCalendarBaseEntity, CalendarEntity):
    """Calendrier regroupant les evenements de toutes les sources."""

    # L'entite principale d'un appareil porte le nom de l'appareil.
    _attr_name = None

    # Active l'ajout et la suppression depuis la vue des calendriers. La
    # modification passe par les options de l'integration.
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
    )

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

    async def async_create_event(self, **kwargs: Any) -> None:
        """Cree un evenement manuel depuis la vue des calendriers.

        L'evenement est enregistre dans les options de l'entree, comme avec le
        service ``add_manual_event``. L'entree se recharge ensuite et l'evenement
        apparait dans le calendrier.

        Args:
            **kwargs: ``summary``, ``dtstart``, ``dtend`` et, selon la saisie,
                ``rrule``, ``description`` et ``location``.

        Raises:
            ServiceValidationError: Si l'evenement n'est pas representable ou
                existe deja. Le message est affiche a l'utilisateur.
        """
        entry = self.coordinator.config_entry
        try:
            rule = manual_event_from_calendar(
                summary=kwargs["summary"],
                dtstart=kwargs["dtstart"],
                dtend=kwargs["dtend"],
                rrule=kwargs.get("rrule"),
                description=kwargs.get("description"),
                location=kwargs.get("location"),
                tz=dt_util.DEFAULT_TIME_ZONE,
            )
            options = add_manual_rule(entry.options, rule, entry.title)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        self.hass.config_entries.async_update_entry(entry, options=options)
        _LOGGER.info(
            "Evenement manuel '%s' cree depuis le calendrier '%s'",
            rule.summary,
            entry.title,
        )

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Supprime un evenement manuel, une occurrence ou la fin d'une serie.

        Seuls les evenements manuels se suppriment: ceux du calendrier officiel
        viennent d'une source, rechargee a chaque cycle.

        Args:
            uid: Identifiant de la regle manuelle.
            recurrence_id: Journee de l'occurrence visee (``AAAA-MM-JJ``).
            recurrence_range: ``THISANDFUTURE`` pour « celui-ci et les
                suivants », sinon None.

        Raises:
            ServiceValidationError: Si l'evenement n'est pas supprimable. Le
                message est affiche a l'utilisateur.
        """
        entry = self.coordinator.config_entry
        try:
            options = delete_manual_occurrence(
                entry.options, uid, recurrence_id, recurrence_range
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        self.hass.config_entries.async_update_entry(entry, options=options)
        _LOGGER.info(
            "Evenement manuel '%s' supprime depuis le calendrier '%s'",
            uid,
            entry.title,
        )

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
