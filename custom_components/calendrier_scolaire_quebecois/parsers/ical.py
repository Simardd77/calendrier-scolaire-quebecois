"""Analyse de fichiers iCalendar.

Ce module ne depend pas de Home Assistant: le fuseau horaire a appliquer aux
horodatages naifs est fourni par l'appelant.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, tzinfo

from ..models import EventCategory, SchoolEvent, clean_summary, deduplicate_events
from . import DependencyMissingError
from .events import classify

_LOGGER = logging.getLogger(__name__)

ICAL_MAGIC = b"BEGIN:VCALENDAR"


def looks_like_ical(data: bytes) -> bool:
    """Verifie la signature textuelle d'un fichier iCalendar.

    Args:
        data: Premiers octets du document.

    Returns:
        True si le contenu commence par un en-tete VCALENDAR.
    """
    return data[:1024].lstrip().upper().startswith(ICAL_MAGIC)


def _coerce_end(
    start: date | datetime, end: date | datetime | None, default_tz: tzinfo
) -> date | datetime:
    """Determine une borne de fin valide et strictement posterieure au debut.

    Args:
        start: Debut de l'evenement, deja normalise.
        end: Fin telle que lue, possiblement absente.
        default_tz: Fuseau applique aux horodatages naifs.

    Returns:
        Borne de fin coherente avec le type du debut.
    """
    start_is_dt = isinstance(start, datetime)

    if end is None:
        return start + timedelta(hours=1) if start_is_dt else start + timedelta(days=1)

    if start_is_dt:
        if not isinstance(end, datetime):
            # Fin exprimee en date alors que le debut est horodate: on cadre sur
            # la fin de journee correspondante.
            end = datetime.combine(end, datetime.min.time())
        end = _ensure_aware(end, default_tz)
        if end <= start:
            return start + timedelta(hours=1)
        return end

    if isinstance(end, datetime):
        end = end.date()

    # Pour une valeur DATE, iCalendar definit DTEND comme exclusif: la valeur
    # lue est donc utilisable telle quelle.
    if end <= start:
        return start + timedelta(days=1)
    return end


def _ensure_aware(value: datetime, default_tz: tzinfo) -> datetime:
    """Attache un fuseau horaire a un horodatage naif.

    Args:
        value: Horodatage lu dans le fichier.
        default_tz: Fuseau a appliquer si aucun n'est present.

    Returns:
        Horodatage avec fuseau horaire.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=default_tz)
    return value


def _normalize_start(value: date | datetime, default_tz: tzinfo) -> date | datetime:
    """Normalise le debut d'un evenement iCalendar.

    Args:
        value: Valeur DTSTART lue.
        default_tz: Fuseau applique aux horodatages naifs.

    Returns:
        Date pour un evenement de journee entiere, datetime localise sinon.
    """
    if isinstance(value, datetime):
        return _ensure_aware(value, default_tz)
    return value


def parse_ical(data: bytes, source_name: str, default_tz: tzinfo) -> list[SchoolEvent]:
    """Analyse un flux iCalendar et retourne les evenements.

    Les regles de recurrence (RRULE) ne sont pas developpees: seule la premiere
    occurrence est retenue.

    Args:
        data: Contenu binaire du fichier .ics.
        source_name: Nom de la source, conserve sur chaque evenement.
        default_tz: Fuseau applique aux horodatages sans fuseau.

    Returns:
        Evenements dedoublonnes et tries chronologiquement.

    Raises:
        DependencyMissingError: Si icalendar n'est pas installe.
    """
    try:
        import icalendar
    except ImportError as err:
        raise DependencyMissingError(
            "icalendar", "l'analyse des fichiers iCalendar"
        ) from err

    calendar = icalendar.Calendar.from_ical(data)
    events: list[SchoolEvent] = []
    recurring = 0

    for component in calendar.walk("VEVENT"):
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue

        if component.get("RRULE") is not None:
            recurring += 1

        dtend = component.get("DTEND")
        duration = component.get("DURATION")

        start = _normalize_start(dtstart.dt, default_tz)

        if dtend is not None:
            end_value: date | datetime | None = dtend.dt
        elif duration is not None:
            end_value = start + duration.dt
        else:
            end_value = None

        summary = clean_summary(str(component.get("SUMMARY", "")))
        if not summary:
            summary = "Événement scolaire"

        try:
            events.append(
                SchoolEvent(
                    summary=summary,
                    start=start,
                    end=_coerce_end(start, end_value, default_tz),
                    category=classify(summary) or EventCategory.EVENT,
                    source=source_name,
                    description=clean_summary(str(component.get("DESCRIPTION", ""))),
                    location=clean_summary(str(component.get("LOCATION", ""))),
                )
            )
        except ValueError as err:
            _LOGGER.debug("Evenement iCalendar ignore (%s): %s", summary, err)

    if recurring:
        _LOGGER.warning(
            "%d evenement(s) recurrent(s) dans '%s': seule la premiere "
            "occurrence est prise en compte",
            recurring,
            source_name,
        )

    return deduplicate_events(events)
