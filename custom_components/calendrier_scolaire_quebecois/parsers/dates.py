"""Extraction de dates francaises et de plages de dates.

Les calendriers scolaires quebecois expriment les dates en clair
("du 23 decembre au 6 janvier") aussi souvent qu'en format numerique
("23/12/2024"). Ce module gere les deux, ainsi que l'annee implicite deduite
de l'annee scolaire courante.

Ce module ne depend pas de Home Assistant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

#: Mois et abreviations acceptes, avec et sans accents.
MONTH_VARIANTS: dict[str, int] = {
    "janvier": 1,
    "janv": 1,
    "jan": 1,
    "fevrier": 2,
    "février": 2,
    "fevr": 2,
    "févr": 2,
    "fev": 2,
    "fév": 2,
    "mars": 3,
    "avril": 4,
    "avr": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "juil": 7,
    "aout": 8,
    "août": 8,
    "aou": 8,
    "aoû": 8,
    "septembre": 9,
    "sept": 9,
    "sep": 9,
    "octobre": 10,
    "oct": 10,
    "novembre": 11,
    "nov": 11,
    "decembre": 12,
    "décembre": 12,
    "dec": 12,
    "déc": 12,
}

# Alternation triee du plus long au plus court pour que "janvier" soit teste
# avant "jan", sinon le moteur regex s'arreterait sur l'abreviation.
_MONTH_ALT = "|".join(
    re.escape(name) for name in sorted(MONTH_VARIANTS, key=len, reverse=True)
)

# Un nom de mois ne doit pas etre suivi d'une lettre, pour eviter que "mai"
# corresponde a l'interieur de "maison".
_MONTH = rf"(?:{_MONTH_ALT})\.?(?![a-zA-ZÀ-ÖØ-öø-ÿ])"

# Separateurs de plage: "au", "a", "à", tirets et demi-cadratins.
_RANGE_SEP = r"(?:\s*(?:au|jusqu'au|jusqu au|à|a)\s*|\s*[-–—]\s*)"

# Suffixe ordinal du premier jour du mois ("1er").
_ORDINAL = r"(?:\s*er\b|\s*ers\b)?"

_ANNEE_MIN = 1990
_ANNEE_MAX = 2100

# Une plage plus longue qu'une annee scolaire indique presque toujours une
# erreur d'analyse (deux dates sans rapport sur la meme ligne).
MAX_SPAN_DAYS = 370


@dataclass(frozen=True, slots=True)
class DateSpan:
    """Une plage de dates detectee dans un texte.

    Attributes:
        start: Premiere journee couverte.
        end_exclusive: Lendemain de la derniere journee couverte.
        match_start: Index de debut de la correspondance dans le texte source.
        match_end: Index de fin de la correspondance dans le texte source.
    """

    start: date
    end_exclusive: date
    match_start: int
    match_end: int

    @property
    def last_day(self) -> date:
        """Derniere journee couverte, incluse."""
        return self.end_exclusive - timedelta(days=1)

    @property
    def is_single_day(self) -> bool:
        """Indique si la plage couvre une seule journee."""
        return self.end_exclusive - self.start == timedelta(days=1)


def school_year_start_for(today: date) -> int:
    """Determine l'annee de debut de l'annee scolaire contenant une date.

    L'annee scolaire quebecoise commence en aout et se termine en juin.

    Args:
        today: Date de reference.

    Returns:
        Annee civile du mois d'aout ouvrant l'annee scolaire.
    """
    return today.year if today.month >= 8 else today.year - 1


def resolve_year(month: int, school_year_start: int) -> int:
    """Deduit l'annee civile d'un mois sans annee explicite.

    Args:
        month: Numero du mois (1-12).
        school_year_start: Annee de debut de l'annee scolaire de reference.

    Returns:
        Annee civile correspondante.
    """
    return school_year_start if month >= 8 else school_year_start + 1


def normalize_two_digit_year(year: int) -> int:
    """Convertit une annee sur deux chiffres en annee sur quatre chiffres.

    Args:
        year: Annee telle que lue dans le texte.

    Returns:
        Annee sur quatre chiffres.
    """
    if year >= 100:
        return year
    return year + 2000 if year < 70 else year + 1900


def _month_number(raw: str) -> int | None:
    """Traduit un nom de mois en numero.

    Args:
        raw: Nom ou abreviation du mois, tel que capture.

    Returns:
        Numero du mois, ou None si inconnu.
    """
    return MONTH_VARIANTS.get(raw.strip().rstrip(".").lower())


def _build_date(day: int, month: int, year: int) -> date | None:
    """Construit une date en validant sa plausibilite.

    Args:
        day: Jour du mois.
        month: Numero du mois.
        year: Annee civile.

    Returns:
        Date valide, ou None si la combinaison est impossible.
    """
    if not _ANNEE_MIN <= year <= _ANNEE_MAX:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _build_numeric_date(first: int, second: int, year: int) -> date | None:
    """Construit une date depuis un format numerique ambigu.

    Le Quebec ecrit habituellement jour/mois/annee. En cas d'impossibilite,
    l'ordre mois/jour/annee est tente en repli.

    Args:
        first: Premier nombre lu.
        second: Deuxieme nombre lu.
        year: Annee, possiblement sur deux chiffres.

    Returns:
        Date valide, ou None.
    """
    full_year = normalize_two_digit_year(year)

    if (result := _build_date(first, second, full_year)) is not None:
        return result
    return _build_date(second, first, full_year)


def _span(start: date, last_day: date, match: re.Match[str]) -> DateSpan | None:
    """Assemble un DateSpan en validant sa duree.

    Args:
        start: Premiere journee.
        last_day: Derniere journee incluse.
        match: Correspondance regex d'origine.

    Returns:
        DateSpan valide, ou None si la plage est incoherente.
    """
    if last_day < start:
        return None
    if (last_day - start).days > MAX_SPAN_DAYS:
        return None

    return DateSpan(
        start=start,
        end_exclusive=last_day + timedelta(days=1),
        match_start=match.start(),
        match_end=match.end(),
    )


# --- Motifs, du plus specifique au plus general ------------------------------

# Un nombre precede d'un autre chiffre n'est pas un jour: cette garde evite
# qu'une annee comme "2025" fournisse le "25" d'une fausse date.
_NO_LEADING_DIGIT = r"(?<!\d)"

# "du 23 decembre 2024 au 6 janvier 2025", "23 decembre au 6 janvier"
_RE_RANGE_TWO_MONTHS = re.compile(
    rf"(?:du\s+)?{_NO_LEADING_DIGIT}(?P<d1>\d{{1,2}}){_ORDINAL}\s+(?P<m1>{_MONTH})"
    rf"(?:\s+(?P<y1>\d{{4}}))?"
    rf"{_RANGE_SEP}"
    rf"(?P<d2>\d{{1,2}}){_ORDINAL}\s+(?P<m2>{_MONTH})"
    rf"(?:\s+(?P<y2>\d{{4}}))?",
    re.IGNORECASE,
)

# "du 3 au 7 mars 2025", "3 au 7 mars", "1-5 mars"
_RE_RANGE_ONE_MONTH = re.compile(
    rf"(?:du\s+)?{_NO_LEADING_DIGIT}(?P<d1>\d{{1,2}}){_ORDINAL}"
    rf"{_RANGE_SEP}"
    rf"(?P<d2>\d{{1,2}}){_ORDINAL}\s+(?P<m>{_MONTH})"
    rf"(?:\s+(?P<y>\d{{4}}))?",
    re.IGNORECASE,
)

# "23/12/2024 au 06/01/2025". Le point n'est pas accepte comme separateur car
# il produirait de fausses dates a partir de numeros de version ("1.12.0").
_RE_RANGE_NUMERIC = re.compile(
    r"(?<!\d)(?P<d1>\d{1,2})[/-](?P<m1>\d{1,2})[/-](?P<y1>\d{2,4})"
    r"\s*(?:au|à|a|[-–—])\s*"
    r"(?P<d2>\d{1,2})[/-](?P<m2>\d{1,2})[/-](?P<y2>\d{2,4})(?!\d)",
    re.IGNORECASE,
)

# "2024-09-03"
_RE_ISO = re.compile(r"(?<!\d)(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})(?!\d)")

# "3 septembre 2024", "1er juillet", "3 sept."
_RE_LITERAL = re.compile(
    rf"{_NO_LEADING_DIGIT}(?P<d>\d{{1,2}}){_ORDINAL}\s+(?:de\s+)?(?P<m>{_MONTH})"
    rf"(?:\s+(?P<y>\d{{4}}))?",
    re.IGNORECASE,
)

# "03/09/2024", "3-9-24"
_RE_NUMERIC = re.compile(
    r"(?<!\d)(?P<d>\d{1,2})[/-](?P<m>\d{1,2})[/-](?P<y>\d{2,4})(?!\d)"
)


def _parse_range_two_months(
    match: re.Match[str], school_year_start: int
) -> DateSpan | None:
    """Analyse une plage exprimee avec deux mois nommes."""
    month1 = _month_number(match.group("m1"))
    month2 = _month_number(match.group("m2"))
    if month1 is None or month2 is None:
        return None

    year1_raw = match.group("y1")
    year2_raw = match.group("y2")

    year1 = int(year1_raw) if year1_raw else resolve_year(month1, school_year_start)

    if year2_raw:
        year2 = int(year2_raw)
    elif month2 < month1:
        # Traversee du 31 decembre: "du 23 decembre au 6 janvier".
        year2 = year1 + 1
    else:
        year2 = year1

    start = _build_date(int(match.group("d1")), month1, year1)
    last_day = _build_date(int(match.group("d2")), month2, year2)

    if start is None or last_day is None:
        return None
    return _span(start, last_day, match)


def _parse_range_one_month(
    match: re.Match[str], school_year_start: int
) -> DateSpan | None:
    """Analyse une plage a l'interieur d'un seul mois."""
    month = _month_number(match.group("m"))
    if month is None:
        return None

    year_raw = match.group("y")
    year = int(year_raw) if year_raw else resolve_year(month, school_year_start)

    start = _build_date(int(match.group("d1")), month, year)
    last_day = _build_date(int(match.group("d2")), month, year)

    if start is None or last_day is None:
        return None
    return _span(start, last_day, match)


def _parse_range_numeric(
    match: re.Match[str], _school_year_start: int
) -> DateSpan | None:
    """Analyse une plage exprimee en format numerique."""
    start = _build_numeric_date(
        int(match.group("d1")), int(match.group("m1")), int(match.group("y1"))
    )
    last_day = _build_numeric_date(
        int(match.group("d2")), int(match.group("m2")), int(match.group("y2"))
    )

    if start is None or last_day is None:
        return None
    return _span(start, last_day, match)


def _parse_iso(match: re.Match[str], _school_year_start: int) -> DateSpan | None:
    """Analyse une date au format ISO."""
    start = _build_date(
        int(match.group("d")), int(match.group("m")), int(match.group("y"))
    )
    if start is None:
        return None
    return _span(start, start, match)


def _parse_literal(match: re.Match[str], school_year_start: int) -> DateSpan | None:
    """Analyse une date unique avec mois nomme."""
    month = _month_number(match.group("m"))
    if month is None:
        return None

    year_raw = match.group("y")
    year = int(year_raw) if year_raw else resolve_year(month, school_year_start)

    start = _build_date(int(match.group("d")), month, year)
    if start is None:
        return None
    return _span(start, start, match)


def _parse_numeric(match: re.Match[str], _school_year_start: int) -> DateSpan | None:
    """Analyse une date unique en format numerique."""
    start = _build_numeric_date(
        int(match.group("d")), int(match.group("m")), int(match.group("y"))
    )
    if start is None:
        return None
    return _span(start, start, match)


# L'ordre est significatif: les plages doivent etre reconnues avant les dates
# simples, sinon "du 3 au 7 mars" produirait un evenement le 7 mars seulement.
_PATTERNS = (
    (_RE_RANGE_TWO_MONTHS, _parse_range_two_months),
    (_RE_RANGE_ONE_MONTH, _parse_range_one_month),
    (_RE_RANGE_NUMERIC, _parse_range_numeric),
    (_RE_ISO, _parse_iso),
    (_RE_LITERAL, _parse_literal),
    (_RE_NUMERIC, _parse_numeric),
)


def find_date_spans(text: str, school_year_start: int) -> list[DateSpan]:
    """Detecte toutes les dates et plages de dates d'un texte.

    Les motifs sont appliques du plus specifique au plus general. Une portion
    de texte deja consommee par un motif n'est pas reanalysee, ce qui evite
    qu'une plage soit aussi comptee comme deux dates isolees.

    Args:
        text: Texte a analyser, typiquement une ligne.
        school_year_start: Annee de debut de l'annee scolaire servant a deduire
            les annees absentes.

    Returns:
        Plages detectees, triees par position dans le texte.
    """
    if not text:
        return []

    consumed: list[tuple[int, int]] = []
    spans: list[DateSpan] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < c_end and end > c_start for c_start, c_end in consumed)

    for pattern, handler in _PATTERNS:
        for match in pattern.finditer(text):
            if overlaps(match.start(), match.end()):
                continue

            span = handler(match, school_year_start)
            if span is None:
                continue

            consumed.append((match.start(), match.end()))
            spans.append(span)

    spans.sort(key=lambda item: item.match_start)
    return spans


def strip_date_text(text: str, spans: list[DateSpan]) -> str:
    """Retire les portions de texte correspondant aux dates.

    Utilise pour deriver un titre lisible depuis une ligne brute.

    Args:
        text: Texte source.
        spans: Plages detectees dans ce texte.

    Returns:
        Texte prive des expressions de date.
    """
    if not spans:
        return text

    pieces: list[str] = []
    cursor = 0

    for span in sorted(spans, key=lambda item: item.match_start):
        if span.match_start > cursor:
            pieces.append(text[cursor : span.match_start])
        cursor = max(cursor, span.match_end)

    pieces.append(text[cursor:])
    return " ".join(pieces)
