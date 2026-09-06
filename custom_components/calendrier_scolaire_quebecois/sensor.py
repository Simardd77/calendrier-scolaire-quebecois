"""Plateforme capteur pour Calendrier Scolaire Quebecois."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SchoolCalendarConfigEntry, SchoolCalendarCoordinator
from .entity import SchoolCalendarBaseEntity

# Horizon du capteur d'evenements a venir.
UPCOMING_DAYS = 7

STATUS_READY = "ready"
STATUS_NO_SOURCES = "no_sources"
STATUS_NO_EVENTS = "no_events"
STATUS_ERROR = "error"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchoolCalendarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Configure les capteurs.

    Args:
        hass: Instance Home Assistant.
        entry: Entree de configuration.
        async_add_entities: Fonction d'ajout des entites.
    """
    coordinator = entry.runtime_data

    async_add_entities(
        [
            TotalEventsSensor(coordinator),
            NextEventSensor(coordinator),
            UpcomingEventsSensor(coordinator),
            StatusSensor(coordinator),
        ]
    )


class TotalEventsSensor(SchoolCalendarBaseEntity, SensorEntity):
    """Nombre total d'evenements connus."""

    _attr_translation_key = "total_events"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SchoolCalendarCoordinator) -> None:
        """Initialise le capteur.

        Args:
            coordinator: Coordinateur fournissant les evenements.
        """
        super().__init__(coordinator, "total_events")

    @property
    def native_value(self) -> int:
        """Nombre d'evenements charges."""
        return len(self.calendar_data.events)


class NextEventSensor(SchoolCalendarBaseEntity, SensorEntity):
    """Titre du prochain evenement."""

    _attr_translation_key = "next_event"

    def __init__(self, coordinator: SchoolCalendarCoordinator) -> None:
        """Initialise le capteur.

        Args:
            coordinator: Coordinateur fournissant les evenements.
        """
        super().__init__(coordinator, "next_event")

    @property
    def native_value(self) -> str | None:
        """Titre de l'evenement en cours ou a venir."""
        event = self.calendar_data.next_event(dt_util.now())
        if event is None:
            return None

        # L'etat d'une entite Home Assistant est limite a 255 caracteres.
        return event.summary[:255]

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Details du prochain evenement."""
        event = self.calendar_data.next_event(dt_util.now())

        if event is None:
            return {}

        return {
            "start": event.start.isoformat(),
            "end": event.end.isoformat(),
            "first_day": event.first_day.isoformat(),
            "last_day": event.last_day.isoformat(),
            "all_day": event.all_day,
            "category": event.category.value,
            "closes_school": event.closes_school,
            "source": event.source,
        }


class UpcomingEventsSensor(SchoolCalendarBaseEntity, SensorEntity):
    """Nombre d'evenements dans les sept prochains jours."""

    _attr_translation_key = "upcoming_events"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SchoolCalendarCoordinator) -> None:
        """Initialise le capteur.

        Args:
            coordinator: Coordinateur fournissant les evenements.
        """
        super().__init__(coordinator, "upcoming_events")

    @property
    def native_value(self) -> int:
        """Nombre d'evenements chevauchant la periode a venir."""
        now = dt_util.now()
        return len(
            self.calendar_data.events_between(now, now + timedelta(days=UPCOMING_DAYS))
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Liste resumee des evenements a venir."""
        now = dt_util.now()
        events = self.calendar_data.events_between(
            now, now + timedelta(days=UPCOMING_DAYS)
        )

        return {
            "horizon_days": UPCOMING_DAYS,
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


class StatusSensor(SchoolCalendarBaseEntity, SensorEntity):
    """Etat de l'integration."""

    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_READY, STATUS_NO_SOURCES, STATUS_NO_EVENTS, STATUS_ERROR]

    def __init__(self, coordinator: SchoolCalendarCoordinator) -> None:
        """Initialise le capteur.

        Args:
            coordinator: Coordinateur fournissant les donnees.
        """
        super().__init__(coordinator, "status")

    @property
    def available(self) -> bool:
        """Ce capteur doit rester lisible pour diagnostiquer une panne.

        Returns:
            Toujours True.
        """
        return True

    @property
    def native_value(self) -> str:
        """Etat courant de l'integration."""
        data = self.calendar_data

        if not self.coordinator.last_update_success:
            return STATUS_ERROR
        if data.sources_total == 0:
            return STATUS_NO_SOURCES
        if not data.events:
            return STATUS_NO_EVENTS
        return STATUS_READY

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Detail des sources et des erreurs rencontrees."""
        data = self.calendar_data

        return {
            "sources_total": data.sources_total,
            "sources_ok": data.sources_ok,
            "events_count": len(data.events),
            "errors": data.source_errors,
            "ocr_enabled": self.coordinator.enable_ocr,
            # L'identifiant est expose ici parce que c'est le seul endroit ou
            # l'utilisateur peut le lire: le service remove_source l'attend.
            "sources": [
                {
                    "id": source.source_id,
                    "name": source.name,
                    "url": source.url,
                    "type": source.source_type,
                }
                for source in self.coordinator.sources
            ],
        }
