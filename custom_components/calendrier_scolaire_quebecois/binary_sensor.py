"""Plateforme capteur binaire pour Calendrier Scolaire Quebecois."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SchoolCalendarConfigEntry, SchoolCalendarCoordinator
from .entity import SchoolCalendarBaseEntity

# Samedi et dimanche.
WEEKEND_DAYS = (5, 6)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchoolCalendarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Configure les capteurs binaires.

    Args:
        hass: Instance Home Assistant.
        entry: Entree de configuration.
        async_add_entities: Fonction d'ajout des entites.
    """
    coordinator = entry.runtime_data

    async_add_entities(
        [
            SchoolOpenBinarySensor(coordinator),
            EventTodayBinarySensor(coordinator),
            HolidayTodayBinarySensor(coordinator),
        ]
    )


class SchoolOpenBinarySensor(SchoolCalendarBaseEntity, BinarySensorEntity):
    """Indique si l'ecole accueille les eleves aujourd'hui."""

    _attr_translation_key = "school_open"

    def __init__(self, coordinator: SchoolCalendarCoordinator) -> None:
        """Initialise le capteur.

        Args:
            coordinator: Coordinateur fournissant les evenements.
        """
        super().__init__(coordinator, "school_open")

    @property
    def is_on(self) -> bool:
        """Etat d'ouverture de l'ecole.

        L'ecole est consideree fermee la fin de semaine, hors de la periode
        scolaire, pendant les conges et lors des journees pedagogiques.

        Returns:
            True si les eleves sont attendus aujourd'hui.
        """
        today = dt_util.now().date()

        if today.weekday() in WEEKEND_DAYS:
            return False

        # Les vacances d'ete ne sont pas marquees dans un calendrier scolaire:
        # elles se deduisent des bornes de l'annee. Lorsque le document ne les
        # annonce pas, is_within_term retourne None et seuls les marqueurs
        # explicites sont pris en compte.
        if self.calendar_data.is_within_term(today) is False:
            return False

        return not any(
            event.closes_school for event in self.calendar_data.events_on(today)
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Motif de la fermeture et bornes de l'annee scolaire."""
        data = self.calendar_data
        today = dt_util.now().date()

        # L'annee rapportee est celle qui situe aujourd'hui, pas l'enveloppe de
        # toutes les annees chargees: ajouter le calendrier de l'annee prochaine
        # ne doit pas deplacer la fin annoncee de l'annee en cours.
        term_start, term_end = data.current_term(today)

        attributes: dict[str, object] = {
            "term_start": term_start.isoformat() if term_start else None,
            "term_end": term_end.isoformat() if term_end else None,
        }

        if today.weekday() in WEEKEND_DAYS:
            return {**attributes, "reason": "weekend", "summary": None}

        if data.is_within_term(today) is False:
            return {**attributes, "reason": "outside_term", "summary": None}

        closing = [event for event in data.events_on(today) if event.closes_school]

        if not closing:
            return {**attributes, "reason": None, "summary": None}

        return {
            **attributes,
            "reason": closing[0].category.value,
            "summary": closing[0].summary,
        }


class EventTodayBinarySensor(SchoolCalendarBaseEntity, BinarySensorEntity):
    """Indique si un evenement est prevu aujourd'hui."""

    _attr_translation_key = "event_today"

    def __init__(self, coordinator: SchoolCalendarCoordinator) -> None:
        """Initialise le capteur.

        Args:
            coordinator: Coordinateur fournissant les evenements.
        """
        super().__init__(coordinator, "event_today")

    @property
    def is_on(self) -> bool:
        """Presence d'au moins un evenement aujourd'hui."""
        return bool(self.calendar_data.events_on(dt_util.now().date()))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Titres des evenements du jour."""
        events = self.calendar_data.events_on(dt_util.now().date())

        return {
            "count": len(events),
            "summaries": [event.summary for event in events],
        }


class HolidayTodayBinarySensor(SchoolCalendarBaseEntity, BinarySensorEntity):
    """Indique si aujourd'hui est un conge scolaire."""

    _attr_translation_key = "holiday_today"

    def __init__(self, coordinator: SchoolCalendarCoordinator) -> None:
        """Initialise le capteur.

        Args:
            coordinator: Coordinateur fournissant les evenements.
        """
        super().__init__(coordinator, "holiday_today")

    @property
    def is_on(self) -> bool:
        """Presence d'un conge ou de vacances aujourd'hui."""
        return any(
            event.is_holiday
            for event in self.calendar_data.events_on(dt_util.now().date())
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Titre du conge en cours, le cas echeant."""
        holidays = [
            event
            for event in self.calendar_data.events_on(dt_util.now().date())
            if event.is_holiday
        ]

        if not holidays:
            return {"summary": None}

        return {
            "summary": holidays[0].summary,
            "last_day": holidays[0].last_day.isoformat(),
        }
