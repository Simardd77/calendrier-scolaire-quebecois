"""Les calendriers PDF fournis dans tools/ passent la validation de source.

Garde-fou contre un seuil de is_calendar_like trop strict: ce sont de vrais
calendriers de centres de services, ils doivent toujours etre acceptes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.calendrier_scolaire_quebecois.coordinator import (
    _events_from_pdf,
)
from custom_components.calendrier_scolaire_quebecois.models import (
    CALENDAR_MIN_TYPED_SHARE,
    CALENDAR_SIGNATURE_CATEGORIES,
    is_calendar_like,
)

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CALENDRIERS = ["cssp-2026-2027.pdf", "cssdm-2026-2027.pdf"]


@pytest.mark.parametrize("nom", CALENDRIERS)
def test_un_vrai_calendrier_est_accepte_avec_de_la_marge(nom):
    """Chaque calendrier est accepte, et sa part typee est loin du seuil."""
    chemin = TOOLS / nom
    if not chemin.is_file():
        pytest.skip(f"{nom} absent de tools/")

    evenements = _events_from_pdf(chemin.read_bytes(), nom, 2026, False)

    assert is_calendar_like(evenements) is True
    typed = sum(1 for e in evenements if e.category in CALENDAR_SIGNATURE_CATEGORIES)
    assert typed / len(evenements) >= 2 * CALENDAR_MIN_TYPED_SHARE
