"""Les documents retenus par une source de site scolaire sont tracables.

Sans cette trace, impossible de savoir quel PDF a produit les evenements d'une
source qui pointe vers une page: le capteur d'etat ne montrait que la page.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.calendrier_scolaire_quebecois import coordinator as coord
from custom_components.calendrier_scolaire_quebecois.const import (
    CONF_SOURCES,
    DOMAIN,
)
from custom_components.calendrier_scolaire_quebecois.fetcher import FetchResult
from custom_components.calendrier_scolaire_quebecois.models import (
    EventCategory,
    SchoolEvent,
)
from custom_components.calendrier_scolaire_quebecois.parsers import ParserError

PAGE = "https://ecole.test/calendrier/"
BON = "https://ecole.test/calendrier/bon.pdf"
SANS_MARQUEUR = "https://ecole.test/calendrier/reglement.pdf"
ILLISIBLE = "https://ecole.test/calendrier/abime.pdf"

SITE = {
    "id": "web1",
    "name": "Site de l'ecole",
    "url": PAGE,
    "type": "school_website",
}
DIRECT = {
    "id": "pdf1",
    "name": "PDF direct",
    "url": BON,
    "type": "direct_url",
}


def _evenement(categorie: EventCategory) -> SchoolEvent:
    return SchoolEvent(
        summary="Evenement",
        start=date(2026, 12, 21),
        end=date(2026, 12, 22),
        category=categorie,
        source="test",
    )


def _page(liens: list[str]) -> bytes:
    corps = "".join(f'<a href="{lien}">Document</a>' for lien in liens)
    return f"<html><body>{corps}</body></html>".encode()


def _installer(monkeypatch, *, page: bytes) -> None:
    """Remplace le reseau et l'analyse des documents par des doublures."""

    async def fetch(session, url, timeout):
        contenu = page if url == PAGE else b"%PDF"
        type_ = "text/html" if url == PAGE else "application/pdf"
        return FetchResult(url=url, content=contenu, content_type=type_)

    async def extraire(hass, nom, result, **kwargs):
        if result.url == ILLISIBLE:
            raise ParserError("document illisible")
        if result.url == SANS_MARQUEUR:
            return [_evenement(EventCategory.EVENT)]
        return [_evenement(EventCategory.HOLIDAY)]

    monkeypatch.setattr(coord, "fetch", fetch)
    monkeypatch.setattr(coord, "async_extract_events", extraire)


@pytest.fixture
async def monter(hass, enable_custom_integrations):
    """Monte une entree et la decharge a la fin, pour ne laisser aucun minuteur."""
    await hass.config.async_set_time_zone("America/Toronto")
    entrees: list[MockConfigEntry] = []

    async def _monter(sources: list[dict]) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Calendrier scolaire",
            data={"name": "Calendrier scolaire"},
            options={CONF_SOURCES: sources},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entrees.append(entry)
        return entry

    yield _monter

    for entry in entrees:
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _sources_du_capteur(hass) -> dict[str, dict]:
    """Attribut ``sources`` du capteur d'etat, indexe par identifiant."""
    for etat in hass.states.async_all("sensor"):
        if "sources" in etat.attributes:
            return {s["id"]: s for s in etat.attributes["sources"]}
    raise AssertionError("capteur d'etat introuvable")


async def test_les_documents_retenus_sont_listes(hass, monter, monkeypatch, caplog):
    """Seuls les documents acceptes figurent, dans l'ordre de decouverte."""
    _installer(monkeypatch, page=_page([BON, SANS_MARQUEUR, ILLISIBLE]))
    caplog.set_level(logging.INFO)

    entry = await monter([SITE])

    documents = entry.runtime_data.data.documents["web1"]
    assert documents.urls == (BON,)
    assert documents.page_text_fallback is False
    source = _sources_du_capteur(hass)["web1"]
    assert source["documents"] == [BON]
    assert source["page_text_fallback"] is False
    assert f"Document retenu pour 'Site de l'ecole': {BON}" in caplog.text
    assert SANS_MARQUEUR not in caplog.text.split("Document retenu")[-1]


async def test_une_page_sans_document_signale_le_repli_textuel(
    hass, monter, monkeypatch, caplog
):
    """Sans lien, le texte de la page est analyse: c'est signale."""
    _installer(monkeypatch, page=_page([]))
    monkeypatch.setattr(
        coord,
        "_events_from_text",
        lambda texte, nom, annee: [_evenement(EventCategory.HOLIDAY)],
    )

    entry = await monter([SITE])

    documents = entry.runtime_data.data.documents["web1"]
    assert documents.urls == ()
    assert documents.page_text_fallback is True
    source = _sources_du_capteur(hass)["web1"]
    assert source["documents"] == []
    assert source["page_text_fallback"] is True
    assert any(
        enregistrement.levelno == logging.WARNING
        and "texte de la page" in enregistrement.getMessage()
        for enregistrement in caplog.records
    )


async def test_une_source_directe_n_a_pas_de_document(hass, monter, monkeypatch):
    """Les attributs existent toujours, vides, pour un lien direct."""
    _installer(monkeypatch, page=_page([]))

    entry = await monter([DIRECT])

    assert entry.runtime_data.data.documents == {}
    source = _sources_du_capteur(hass)["pdf1"]
    assert source["documents"] == []
    assert source["page_text_fallback"] is False


async def test_les_documents_survivent_au_recalcul_sans_telechargement(
    hass, monter, monkeypatch
):
    """Ajouter un evenement manuel ne fait pas perdre la trace."""
    _installer(monkeypatch, page=_page([BON]))

    entry = await monter([SITE])
    entry.runtime_data.async_rebuild_from_snapshot()
    await hass.async_block_till_done()

    assert entry.runtime_data.data.documents["web1"].urls == (BON,)
    assert _sources_du_capteur(hass)["web1"]["documents"] == [BON]


@pytest.mark.parametrize("liens", [[SANS_MARQUEUR], [ILLISIBLE]])
async def test_aucun_document_accepte_laisse_une_liste_vide(
    hass, monter, monkeypatch, liens
):
    """Des liens existent mais aucun n'est retenu: ce n'est pas un repli."""
    _installer(monkeypatch, page=_page(liens))

    entry = await monter([SITE, DIRECT])

    documents = entry.runtime_data.data.documents["web1"]
    assert documents.urls == ()
    assert documents.page_text_fallback is False
