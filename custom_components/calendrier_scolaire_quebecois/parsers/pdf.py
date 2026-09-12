"""Lecture d'un document PDF: couche texte et geometrie.

Les fonctions de ce module sont synchrones et bloquantes: elles doivent etre
appelees depuis un executor, jamais directement dans la boucle asyncio.

Ce module ne depend pas de Home Assistant.
"""

from __future__ import annotations

import io
import logging
import unicodedata
from dataclasses import dataclass, field

from . import DependencyMissingError

_LOGGER = logging.getLogger(__name__)

# En-tete d'un fichier PDF valide.
PDF_MAGIC = b"%PDF-"

# Nombre maximal de pages dont la geometrie est relevee. Un calendrier scolaire
# tient sur une page; cette borne evite qu'un document inattendu sature la
# memoire.
MAX_GEOMETRY_PAGES = 10

# Cles conservees pour chaque objet, afin de ne pas retenir en memoire les
# structures completes de pdfplumber.
_WORD_KEYS = ("text", "x0", "x1", "top", "bottom")
_SHAPE_KEYS = (
    "object_type",
    "x0",
    "x1",
    "top",
    "bottom",
    "stroke",
    "fill",
    "linewidth",
    "stroking_color",
    "non_stroking_color",
    # Sommets du trace. Ils distinguent deux formes de meme encombrement, par
    # exemple deux triangles d'orientations opposees. Selon la version de
    # pdfplumber la cle s'appelle "pts" ou "points": les deux sont demandees.
    "points",
    "pts",
)


def looks_like_pdf(data: bytes) -> bool:
    """Verifie la signature binaire d'un PDF.

    Plus fiable que l'extension de l'URL, souvent absente ou trompeuse.

    Args:
        data: Premiers octets du document.

    Returns:
        True si le contenu commence par la signature PDF.
    """
    return data[:1024].lstrip().startswith(PDF_MAGIC)


@dataclass(slots=True)
class PageGeometry:
    """Geometrie exploitable d'une page.

    Attributes:
        words: Mots avec leurs boites englobantes.
        shapes: Rectangles et courbes avec leurs couleurs.
    """

    words: list[dict] = field(default_factory=list)
    shapes: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class PdfContent:
    """Contenu extrait d'un PDF.

    Attributes:
        text: Couche texte, tableaux inclus, une information par ligne.
        pages: Geometrie des premieres pages.
    """

    text: str = ""
    pages: list[PageGeometry] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        """Indique si une couche texte exploitable a ete trouvee."""
        return bool(self.text.strip())


def _subset(source: dict, keys: tuple[str, ...]) -> dict:
    """Extrait un sous-ensemble de cles d'un dictionnaire.

    Args:
        source: Dictionnaire d'origine.
        keys: Cles a conserver.

    Returns:
        Nouveau dictionnaire limite aux cles demandees et presentes.
    """
    return {key: source[key] for key in keys if key in source}


def read_pdf(data: bytes) -> PdfContent:
    """Lit un PDF et en retourne le texte ainsi que la geometrie.

    Le document n'est ouvert qu'une fois: les deux strategies d'analyse,
    textuelle et geometrique, se partagent la meme lecture.

    Args:
        data: Contenu binaire du PDF.

    Returns:
        Texte et geometrie du document.

    Raises:
        DependencyMissingError: Si pdfplumber n'est pas installe.
    """
    try:
        import pdfplumber
    except ImportError as err:
        raise DependencyMissingError("pdfplumber", "l'analyse des PDF") from err

    lines: list[str] = []
    pages: list[PageGeometry] = []

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 - une page illisible n'arrete pas tout
                _LOGGER.debug("Texte illisible sur la page %d", page_number)
                text = ""

            column_lines = _extract_column_lines(page)
            if text:
                text_lines = text.splitlines()
                if column_lines:
                    text_lines = _without_column_table(text_lines)
                lines.extend(text_lines)

            lines.extend(_extract_table_lines(page, page_number))
            lines.extend(column_lines)

            if page_number <= MAX_GEOMETRY_PAGES:
                pages.append(_extract_geometry(page, page_number))

    return PdfContent(text="\n".join(lines), pages=pages)


def _extract_geometry(page: object, page_number: int) -> PageGeometry:
    """Releve les mots et les formes d'une page.

    Args:
        page: Page pdfplumber.
        page_number: Numero de page, pour la journalisation.

    Returns:
        Geometrie de la page, vide en cas d'echec.
    """
    geometry = PageGeometry()

    try:
        geometry.words = [
            _subset(word, _WORD_KEYS)
            for word in page.extract_words()  # type: ignore[attr-defined]
        ]
    except Exception:  # noqa: BLE001 - geometrie facultative
        _LOGGER.debug("Mots illisibles sur la page %d", page_number)
        return geometry

    try:
        for shape in list(page.rects) + list(page.curves):  # type: ignore[attr-defined]
            geometry.shapes.append(_subset(shape, _SHAPE_KEYS))
        for image in page.images:  # type: ignore[attr-defined]
            if image.get("width", 0) <= 40 and image.get("height", 0) <= 40:
                geometry.shapes.append(
                    {
                        "object_type": "image",
                        "x0": image["x0"],
                        "x1": image["x1"],
                        "top": image["top"],
                        "bottom": image["bottom"],
                        "stroke": False,
                        "fill": True,
                        "non_stroking_color": "image",
                        "stroking_color": "none",
                    }
                )
    except Exception:  # noqa: BLE001 - geometrie facultative
        _LOGGER.debug("Formes illisibles sur la page %d", page_number)

    return geometry


def _extract_table_lines(page: object, page_number: int) -> list[str]:
    """Extrait les lignes et cellules des tableaux d'une page.

    Args:
        page: Page pdfplumber.
        page_number: Numero de page, pour la journalisation.

    Returns:
        Lignes de texte issues des tableaux.
    """
    lines: list[str] = []

    try:
        tables = page.extract_tables()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - extraction de tableau facultative
        _LOGGER.debug("Tableaux illisibles sur la page %d", page_number)
        return lines

    for table in tables:
        for row in table:
            cells = [str(cell).strip() for cell in row if cell]
            if not cells:
                continue

            # La ligne complete conserve le contexte horizontal, les cellules
            # isolees evitent qu'une semaine entiere soit fusionnee en un seul
            # evenement.
            lines.append(" | ".join(cells))
            lines.extend(cell for cell in cells if len(cell) >= 3)

    return lines


def _normalize_word(text: str) -> str:
    """Normalise un mot pour reconnaitre les titres de colonnes."""
    return "".join(
        character
        for character in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(character) != "Mn"
    )


def _extract_column_lines(page: object) -> list[str]:
    """Extrait séparément les colonnes d'un tableau de calendrier.

    Certains PDF placent les dates importantes, les rencontres et la légende
    sur la même ligne visuelle. L'extraction textuelle ordinaire les concatène,
    ce qui attribue la catégorie de la légende à la date voisine.
    """
    try:
        words = page.extract_words()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - extraction facultative
        return []

    legend_words = [
        word
        for word in words
        if _normalize_word(word.get("text", "")).strip() == "legende"
    ]
    if not legend_words:
        return []

    header_top = min(word["top"] for word in legend_words)
    headers = {
        title: [
            word
            for word in words
            if _normalize_word(word.get("text", "")).strip() in title.split()
            and abs(word["top"] - header_top) <= 3
        ]
        for title in ("dates importantes", "rencontres de parents", "legende")
    }
    if any(not words_for_title for words_for_title in headers.values()):
        return []

    title_centers = []
    for title, title_words in headers.items():
        if max(abs(word["top"] - header_top) for word in title_words) > 3:
            return []
        title_centers.append(
            sum((word["x0"] + word["x1"]) / 2 for word in title_words)
            / len(title_words)
        )

    boundaries = [
        (first + second) / 2
        for first, second in zip(sorted(title_centers), sorted(title_centers)[1:])
    ]
    table_words = [word for word in words if word["top"] > header_top + 8]
    rows: dict[float, list[dict]] = {}
    for word in table_words:
        row_top = min(
            (top for top in rows if abs(top - word["top"]) <= 1.5),
            default=round(word["top"], 1),
        )
        rows.setdefault(row_top, []).append(word)

    extracted: list[str] = []
    for row_words in rows.values():
        for column in (0, 1, 2):
            selected = [
                word
                for word in row_words
                if (column == 0 and word["x0"] < boundaries[0])
                or (
                    column == 1
                    and boundaries[0] <= word["x0"] < boundaries[1]
                )
                or (column == 2 and word["x0"] >= boundaries[1])
            ]
            if selected:
                extracted.append(" ".join(word["text"] for word in selected))

    return extracted


def _without_column_table(lines: list[str]) -> list[str]:
    """Retire la version concaténée d'un tableau déjà extrait."""
    for index, line in enumerate(lines):
        normalized = _normalize_word(line)
        if "dates importantes" in normalized and "legende" in normalized:
            return lines[:index]
    return lines
