"""Serialisation d'un calendrier au format iCalendar (RFC 5545).

Ce module ne depend pas de Home Assistant afin de rester testable en isolation.

Deux details du format decident du rendu dans une application comme Calendrier
d'Apple, et sont la source des erreurs les plus courantes:

- une journee entiere doit s'ecrire ``DTSTART;VALUE=DATE:20241223``. Sans le
  parametre ``VALUE=DATE``, le type par defaut de ``DTSTART`` est un horodatage,
  et l'evenement s'affiche sur une plage horaire au lieu du bandeau de la
  journee;
- les caracteres ``\\``, ``;``, ``,`` et les retours a la ligne doivent etre
  echappes dans les valeurs textuelles, et toute ligne depassant 75 octets doit
  etre pliee. Une virgule non echappee dans un titre coupe la propriete en deux
  et corrompt l'evenement;
- un evenement horodate ecrit en UTC (suffixe ``Z``) fait afficher « GMT » dans
  Calendrier d'Apple. Quand le fuseau local est connu, l'heure est donc publiee
  en heure locale « flottante », sans suffixe ni fuseau: l'application l'affiche
  telle quelle, sans ligne de fuseau horaire.
"""

from __future__ import annotations

from datetime import date, datetime, timezone, tzinfo

from .models import SchoolEvent

#: Longueur maximale d'une ligne, en octets, avant pliage (RFC 5545, 3.1).
MAX_LINE_OCTETS = 75

PRODID = "-//Calendrier Scolaire Quebecois//Flux iCalendar//FR"

#: Duree suggeree aux clients entre deux rafraichissements.
DEFAULT_REFRESH_HINT = "PT12H"

#: Suffixe garantissant l'unicite des identifiants d'evenement entre calendriers.
UID_SUFFIX = "calendrier-scolaire-quebecois"


def escape_text(value: str) -> str:
    """Echappe une valeur textuelle iCalendar.

    Le deux-points n'est volontairement pas echappe: il est autorise dans une
    valeur et l'echapper produirait un libelle errone.

    Args:
        value: Texte brut.

    Returns:
        Texte echappe.
    """
    # La barre oblique inverse doit etre traitee en premier, sinon les
    # echappements ajoutes ensuite seraient eux-memes echappes.
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace(";", "\\;").replace(",", "\\,")
    escaped = escaped.replace("\r\n", "\\n").replace("\n", "\\n")
    return escaped.replace("\r", "\\n")


def fold_line(line: str) -> list[str]:
    """Plie une ligne trop longue en respectant les frontieres de caracteres.

    La limite de 75 porte sur les octets, pas sur les caracteres: un texte
    accentue compte double sur ses accents. Le decoupage se fait donc sur les
    caracteres pour ne jamais scinder une sequence UTF-8.

    Args:
        line: Ligne complete, deja echappee.

    Returns:
        Liste de lignes. Les lignes de continuation commencent par une espace.
    """
    if len(line.encode("utf-8")) <= MAX_LINE_OCTETS:
        return [line]

    chunks: list[str] = []
    current = ""
    current_octets = 0
    # La premiere ligne dispose des 75 octets; les suivantes en cedent un a
    # l'espace de continuation.
    limit = MAX_LINE_OCTETS

    for char in line:
        size = len(char.encode("utf-8"))
        if current_octets + size > limit:
            chunks.append(current)
            current = char
            current_octets = size
            limit = MAX_LINE_OCTETS - 1
        else:
            current += char
            current_octets += size

    chunks.append(current)
    return [chunks[0], *(f" {chunk}" for chunk in chunks[1:])]


def _format_date(value: date) -> str:
    """Formate une date au format iCalendar."""
    return value.strftime("%Y%m%d")


def _format_datetime(value: datetime) -> str:
    """Formate un horodatage en UTC au format iCalendar."""
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _format_local_datetime(value: datetime, tz: tzinfo) -> str:
    """Formate un horodatage en heure locale flottante (sans suffixe Z)."""
    return value.astimezone(tz).strftime("%Y%m%dT%H%M%S")


def _event_lines(
    event: SchoolEvent, dtstamp: str, tz: tzinfo | None = None
) -> list[str]:
    """Construit les proprietes d'un evenement.

    Args:
        event: Evenement a serialiser.
        dtstamp: Horodatage de generation du flux.
        tz: Fuseau local. Si fourni, les heures sont publiees en heure locale
            flottante; sinon en UTC.

    Returns:
        Lignes de la composante VEVENT, avant pliage.
    """
    lines = [
        "BEGIN:VEVENT",
        f"UID:{event.uid}@{UID_SUFFIX}",
        f"DTSTAMP:{dtstamp}",
    ]

    if event.all_day:
        # end est deja exclusif dans notre modele, ce qu'attend DTEND.
        lines.append(f"DTSTART;VALUE=DATE:{_format_date(event.start)}")
        lines.append(f"DTEND;VALUE=DATE:{_format_date(event.end)}")
        # Un conge scolaire est une information, il ne doit pas marquer
        # l'utilisateur comme occupe.
        lines.append("TRANSP:TRANSPARENT")
    else:
        if tz is None:
            lines.append(f"DTSTART:{_format_datetime(event.start)}")
            lines.append(f"DTEND:{_format_datetime(event.end)}")
        else:
            lines.append(f"DTSTART:{_format_local_datetime(event.start, tz)}")
            lines.append(f"DTEND:{_format_local_datetime(event.end, tz)}")

    lines.append(f"SUMMARY:{escape_text(event.summary)}")
    lines.append(f"CATEGORIES:{escape_text(event.category.value)}")

    if event.description:
        lines.append(f"DESCRIPTION:{escape_text(event.description)}")
    if event.location:
        lines.append(f"LOCATION:{escape_text(event.location)}")

    lines.append("END:VEVENT")
    return lines


def build_ics(
    calendar_name: str,
    events: list[SchoolEvent],
    *,
    now: datetime | None = None,
    refresh_hint: str = DEFAULT_REFRESH_HINT,
    tz: tzinfo | None = None,
) -> str:
    """Serialise un calendrier complet.

    Args:
        calendar_name: Nom affiche par l'application cliente.
        events: Evenements a publier.
        now: Horodatage de generation. Par defaut, l'instant courant en UTC.
            Parametrable pour rendre la sortie reproductible en test.
        refresh_hint: Duree ISO 8601 suggeree entre deux rafraichissements.
        tz: Fuseau local. Si fourni, les evenements horodates sont publies
            en heure locale flottante, sans « GMT » dans le client. Sans
            fuseau, ils sont publies en UTC.

    Returns:
        Flux iCalendar complet, lignes terminees par CRLF.
    """
    dtstamp = _format_datetime(now or datetime.now(timezone.utc))
    escaped_name = escape_text(calendar_name)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"NAME:{escaped_name}",
        f"X-WR-CALNAME:{escaped_name}",
        f"REFRESH-INTERVAL;VALUE=DURATION:{refresh_hint}",
        f"X-PUBLISHED-TTL:{refresh_hint}",
    ]

    for event in events:
        lines.extend(_event_lines(event, dtstamp, tz))

    lines.append("END:VCALENDAR")

    folded: list[str] = []
    for line in lines:
        folded.extend(fold_line(line))

    # RFC 5545 impose CRLF, y compris sur la derniere ligne.
    return "\r\n".join(folded) + "\r\n"
