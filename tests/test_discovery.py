"""Tests unitaires de la découverte de documents de calendrier.

La decouverte se limite a la recherche de documents de calendrier dans une page
scolaire: fetcher.find_calendar_links.
"""

from custom_components.calendrier_scolaire_quebecois.const import (
    MAX_DISCOVERED_SOURCES,
)
from custom_components.calendrier_scolaire_quebecois.fetcher import (
    find_calendar_links,
)

# URL de base volontairement neutre: un segment comme "vie-scolaire" contient
# l'indice "scolaire" et rendrait tous les liens prioritaires.
BASE_URL = "https://ecole.example.com/infos/"


def test_discovery_trouve_les_documents_de_calendrier():
    """Les liens vers des PDF et des iCalendar sont retenus."""
    html = """
    <a href="calendrier-scolaire-2024-2025.pdf">Calendrier</a>
    <a href="/documents/horaire.ics">Horaire</a>
    <a href="https://ecole.example.com/reglement.pdf">Règlement</a>
    """

    links = find_calendar_links(html, BASE_URL)

    assert BASE_URL + "calendrier-scolaire-2024-2025.pdf" in links
    assert "https://ecole.example.com/documents/horaire.ics" in links
    assert "https://ecole.example.com/reglement.pdf" in links


def test_discovery_resout_les_liens_relatifs():
    """Un lien relatif est resolu contre l'URL de la page."""
    links = find_calendar_links('<a href="../calendrier.pdf">C</a>', BASE_URL)

    assert links == ["https://ecole.example.com/calendrier.pdf"]


def test_discovery_priorise_les_urls_evoquant_un_calendrier():
    """Un lien dont l'adresse evoque un calendrier passe en premier."""
    html = """
    <a href="reglement.pdf">Règlement</a>
    <a href="calendrier.pdf">Calendrier</a>
    """

    links = find_calendar_links(html, BASE_URL)

    assert links[0] == BASE_URL + "calendrier.pdf"
    assert links[1] == BASE_URL + "reglement.pdf"


def test_discovery_ignore_les_liens_non_documentaires():
    """Les pages HTML et les liens techniques ne sont pas des sources."""
    html = """
    <a href="index.html">Accueil</a>
    <a href="#section">Ancre</a>
    <a href="javascript:void(0)">Script</a>
    <a href="mailto:info@example.com">Courriel</a>
    <a href="photo.png">Photo</a>
    """

    assert find_calendar_links(html, BASE_URL) == []


def test_discovery_dedoublonne_les_liens():
    """Un meme document liste deux fois ne compte qu'une fois."""
    html = """
    <a href="calendrier.pdf">Voir</a>
    <a href="calendrier.pdf">Télécharger</a>
    """

    assert find_calendar_links(html, BASE_URL) == [BASE_URL + "calendrier.pdf"]


def test_discovery_respecte_la_limite_de_sources():
    """Une page saturee de liens ne peut pas faire exploser le nombre de sources."""
    html = "".join(
        f'<a href="calendrier-{index}.pdf">C{index}</a>'
        for index in range(MAX_DISCOVERED_SOURCES + 10)
    )

    links = find_calendar_links(html, BASE_URL)

    assert len(links) == MAX_DISCOVERED_SOURCES


def test_discovery_sans_lien():
    """Une page sans document de calendrier ne produit aucune source."""
    assert find_calendar_links("<p>Aucun document ici</p>", BASE_URL) == []
    assert find_calendar_links("", BASE_URL) == []
