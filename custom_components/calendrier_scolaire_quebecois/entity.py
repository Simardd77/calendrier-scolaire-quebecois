"""Entite de base partagee par les plateformes."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CalendarData, SchoolCalendarCoordinator


class SchoolCalendarBaseEntity(CoordinatorEntity[SchoolCalendarCoordinator]):
    """Base commune: regroupe les entites sous un meme appareil."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SchoolCalendarCoordinator, key: str) -> None:
        """Initialise l'entite.

        Args:
            coordinator: Coordinateur fournissant les donnees.
            key: Suffixe distinguant l'entite au sein de l'entree.
        """
        super().__init__(coordinator)

        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Calendrier Scolaire Québécois",
            model="Calendrier scolaire",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def calendar_data(self) -> CalendarData:
        """Donnees du coordinateur, jamais nulles.

        Un premier cycle en echec laisse ``coordinator.data`` a None. Retourner
        une structure vide evite de disperser des verifications dans chaque
        propriete d'entite.

        Returns:
            Donnees courantes, ou une structure vide.
        """
        return self.coordinator.data or CalendarData()
