"""Fixtures partagées par la suite de tests.

Note: ce fichier ne definit volontairement pas de fixture ``hass``. Le greffon
pytest-homeassistant-custom-component en fournit une vraie, et la redefinir ici
(comme le faisait un MagicMock) la masquerait pour tous les tests.
"""

from datetime import date, timedelta
from typing import Callable

import pytest

from custom_components.calendrier_scolaire_quebecois.const import (
    CONF_ENABLE_OCR,
    CONF_REFRESH_INTERVAL,
    CONF_SOURCES,
    DEFAULT_REFRESH_INTERVAL,
)
from custom_components.calendrier_scolaire_quebecois.models import (
    EventCategory,
    SchoolEvent,
)


@pytest.fixture
def make_event() -> Callable[..., SchoolEvent]:
    """Fabrique d'evenements de journee entiere.

    La fin d'un evenement de journee entiere est exclusive: ``days=1`` produit
    un evenement d'une seule journee.
    """

    def _make(
        summary: str,
        start: date,
        *,
        days: int = 1,
        category: EventCategory = EventCategory.EVENT,
        source: str = "École Test",
    ) -> SchoolEvent:
        return SchoolEvent(
            summary=summary,
            start=start,
            end=start + timedelta(days=days),
            category=category,
            source=source,
        )

    return _make


@pytest.fixture
def config_entry_data() -> dict:
    """Donnees d'une entree de configuration conforme au schema courant."""
    return {
        CONF_SOURCES: [
            {
                "id": "abc123456789",
                "name": "Calendrier de test",
                "url": "https://ecole.example.com/calendrier.pdf",
                "type": "direct_url",
            }
        ],
        CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
        CONF_ENABLE_OCR: False,
    }
