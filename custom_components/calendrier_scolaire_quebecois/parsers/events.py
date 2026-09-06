"""Extraction et classification des evenements depuis du texte brut.

Ce module ne depend pas de Home Assistant.
"""

from __future__ import annotations

import re

from ..models import (
    EventCategory,
    SchoolEvent,
    clean_summary,
    deduplicate_events,
    normalize_text,
)
from .dates import find_date_spans, strip_date_text

# Nombre maximal d'evenements retenus pour une seule source, afin qu'un
# document inattendu ne puisse pas saturer la memoire.
MAX_EVENTS_PER_SOURCE = 2000

# Longueur maximale du reste de ligne accepte comme titre lorsqu'aucun mot-cle
# n'a permis de classer l'evenement.
MAX_UNCATEGORIZED_LENGTH = 120

# Mots-cles par categorie, normalises (sans accents, en minuscules).
# L'ordre du tuple est significatif: une journee pedagogique doit etre reconnue
# comme telle et non comme un simple conge.
_KEYWORDS: tuple[tuple[EventCategory, tuple[str, ...]], ...] = (
    (
        EventCategory.PEDAGOGICAL_DAY,
        (
            "pedagogique",
            "pedago",
            "journee de planification",
            # Formulation courante qui decrit une journee pedagogique sans la
            # nommer: les eleves sont en conge, le personnel travaille.
            "travail pour les enseignants",
            "travail des enseignants",
            "travail pour le personnel",
        ),
    ),
    (
        EventCategory.HOLIDAY,
        (
            "vacances",
            "conge",
            "relache",
            "ferie",
            "fermeture",
            "ecole fermee",
            "temps des fetes",
            "jour de l'an",
            "noel",
            "paques",
            "action de grace",
            "fete nationale",
            "fete du travail",
            "fete du canada",
            "tempete",
            "jour de neige",
        ),
    ),
    (
        EventCategory.TERM_START,
        (
            "rentree",
            "accueil des eleves",
            "entree progressive",
            "debut des classes",
            "premiere journee de classe",
            "premiere journee",
        ),
    ),
    (
        EventCategory.TERM_END,
        (
            "fin des classes",
            "fin de l'annee scolaire",
            "derniere journee de classe",
            "derniere journee",
        ),
    ),
    (
        EventCategory.EXAM,
        (
            "examen",
            "epreuve",
            "evaluation",
            "sommative",
            "passation",
        ),
    ),
    (
        EventCategory.MEETING,
        (
            "rencontre de parents",
            "rencontre parents",
            "rencontre avec les parents",
            "remise des bulletins",
            "remise du bulletin",
            "bulletin",
            "assemblee",
            "conseil d'etablissement",
            "portes ouvertes",
            "porte ouverte",
            "reunion",
            "communication aux parents",
        ),
    ),
    (
        EventCategory.EVENT,
        (
            "accueil",
            "sortie",
            "excursion",
            "photo scolaire",
            "photo",
            "spectacle",
            "activite",
            "carnaval",
            "halloween",
            "graduation",
            "gala",
            "olympiades",
            "exposition",
            "semaine de",
            "classe",
            "ecole",
            "cours",
            "journee",
        ),
    ),
)

# Libelle de repli lorsque la ligne ne contient qu'une date.
_CATEGORY_LABELS: dict[EventCategory, str] = {
    EventCategory.HOLIDAY: "Congé",
    EventCategory.PEDAGOGICAL_DAY: "Journée pédagogique",
    EventCategory.TERM_START: "Rentrée scolaire",
    EventCategory.TERM_END: "Fin des classes",
    EventCategory.EXAM: "Examen",
    EventCategory.MEETING: "Rencontre",
    EventCategory.EVENT: "Événement scolaire",
}

# Marqueurs de public. Un calendrier distingue souvent la rentree du personnel
# de celle des eleves: seule la seconde borne l'annee scolaire du point de vue
# d'une famille.
_STAFF_MARKERS = (
    "enseignant",
    "personnel",
    "direction",
    "equipe-ecole",
    "equipe ecole",
    "professeur",
    "suppleant",
)
_STUDENT_MARKERS = ("eleve", "etudiant")

# Categories dont le sens depend du public vise.
_AUDIENCE_SENSITIVE = frozenset({EventCategory.TERM_START, EventCategory.TERM_END})

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{3,}")
_SCHOOL_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})\s*[-–—/]\s*(20\d{2})(?!\d)")

# Mots de liaison restant en bordure du titre apres retrait de la date.
# "Journee pedagogique le 4 octobre" laisse "Journee pedagogique le".
_CONNECTOR_WORDS = frozenset(
    {
        "a",
        "au",
        "aux",
        "de",
        "des",
        "du",
        "en",
        "et",
        "la",
        "le",
        "les",
        "pour",
        "sur",
    }
)


def _strip_connectors(text: str) -> str:
    """Retire les mots de liaison isoles en debut et en fin de titre.

    Args:
        text: Titre nettoye mais pouvant conserver une preposition orpheline.

    Returns:
        Titre sans mot de liaison en bordure.
    """
    tokens = text.split()

    while tokens and normalize_text(tokens[0]) in _CONNECTOR_WORDS:
        tokens.pop(0)
    while tokens and normalize_text(tokens[-1]) in _CONNECTOR_WORDS:
        tokens.pop()

    return " ".join(tokens)


def _targets_staff_only(normalized: str) -> bool:
    """Verifie qu'un libelle concerne le personnel a l'exclusion des eleves.

    Args:
        normalized: Libelle normalise.

    Returns:
        True si le personnel est mentionne sans les eleves.
    """
    return any(marker in normalized for marker in _STAFF_MARKERS) and not any(
        marker in normalized for marker in _STUDENT_MARKERS
    )


def classify(text: str) -> EventCategory | None:
    """Determine la categorie d'un evenement a partir de son libelle.

    Les bornes de l'annee scolaire sont evaluees du point de vue des eleves. Une
    rentree qui ne concerne que le personnel enseignant ne borne donc pas
    l'annee: elle est ramenee a un evenement ordinaire.

    Args:
        text: Libelle brut de l'evenement.

    Returns:
        Categorie detectee, ou None si aucun mot-cle ne correspond.
    """
    normalized = normalize_text(text)

    for category, keywords in _KEYWORDS:
        if not any(keyword in normalized for keyword in keywords):
            continue

        if category in _AUDIENCE_SENSITIVE and _targets_staff_only(normalized):
            return EventCategory.EVENT

        return category

    return None


def detect_school_year(text: str) -> int | None:
    """Detecte l'annee scolaire annoncee dans un document.

    Un calendrier mentionne presque toujours son annee scolaire sous la forme
    "2024-2025". Cette information est plus fiable que la date du jour pour
    deduire les annees absentes des dates.

    Args:
        text: Texte complet du document.

    Returns:
        Annee de debut de l'annee scolaire, ou None si non detectee.
    """
    for match in _SCHOOL_YEAR_RE.finditer(text):
        first = int(match.group(1))
        second = int(match.group(2))
        if second == first + 1:
            return first

    return None


def _is_plausible_title(text: str) -> bool:
    """Verifie qu'un reste de ligne peut servir de titre d'evenement.

    Filtre les en-tetes, numeros de page et fragments de tableau, qui sont
    frequents dans le texte extrait d'un PDF.

    Args:
        text: Reste de ligne apres retrait des dates.

    Returns:
        True si le texte ressemble a un libelle d'evenement.
    """
    if not text or len(text) > MAX_UNCATEGORIZED_LENGTH:
        return False

    return len(_WORD_RE.findall(text)) >= 2


def extract_events_from_text(
    text: str,
    source_name: str,
    school_year_start: int,
    *,
    strict: bool = False,
) -> list[SchoolEvent]:
    """Extrait les evenements d'un texte ligne par ligne.

    Une ligne produit un evenement lorsqu'elle contient au moins une date et
    qu'elle est soit reconnue par un mot-cle, soit accompagnee d'un libelle
    plausible.

    Args:
        text: Texte a analyser.
        source_name: Nom de la source, conserve sur chaque evenement.
        school_year_start: Annee de debut de l'annee scolaire de reference.
        strict: Si True, seules les lignes reconnues par un mot-cle sont
            retenues. Reduit le bruit au prix de quelques oublis.

    Returns:
        Evenements dedoublonnes et tries chronologiquement.
    """
    if not text:
        return []

    events: list[SchoolEvent] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if len(line) < 3:
            continue

        spans = find_date_spans(line, school_year_start)
        if not spans:
            continue

        remainder = _strip_connectors(clean_summary(strip_date_text(line, spans)))
        category = classify(line)

        if category is None:
            if strict or not _is_plausible_title(remainder):
                continue
            category = EventCategory.EVENT

        summary = remainder or _CATEGORY_LABELS[category]

        for span in spans:
            events.append(
                SchoolEvent(
                    summary=summary,
                    start=span.start,
                    end=span.end_exclusive,
                    category=category,
                    source=source_name,
                )
            )

            if len(events) >= MAX_EVENTS_PER_SOURCE:
                return deduplicate_events(events)

    return deduplicate_events(events)
