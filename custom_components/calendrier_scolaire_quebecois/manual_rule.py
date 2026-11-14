"""Conversion d'un evenement cree depuis la vue des calendriers en ManualEvent.

Le formulaire natif de Home Assistant decrit une repetition par une chaine
``RRULE`` (RFC 5545). Le modele ``ManualEvent`` n'en couvre qu'une partie: des
jours de semaine sur une plage de dates. Ce module traduit ce sous-ensemble et
refuse le reste avec un message clair, plutot que d'enregistrer un evenement
different de celui demande.

Ce module ne depend pas de Home Assistant afin de rester testable en isolation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

from .const import CONF_MANUAL_EVENTS
from .models import ManualEvent, build_manual_event_id

#: Codes RFC 5545 des jours, dans l'ordre de ``date.weekday()`` (lundi = 0).
_DAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

#: Parametres de RRULE que la traduction sait honorer.
_SUPPORTED_PARTS = {"FREQ", "INTERVAL", "BYDAY", "UNTIL", "COUNT", "WKST"}

#: Plafond de ``COUNT``: borne la boucle de calcul de la date de fin.
_MAX_COUNT = 1000


def _parse_rrule(rrule: str) -> dict[str, str]:
    """Decoupe une RRULE en parametres, en refusant ceux qu'on ne sait pas honorer.

    Args:
        rrule: Chaine du type ``FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20270623``.

    Returns:
        Parametres, noms en majuscules.

    Raises:
        ValueError: Si la regle contient un parametre non pris en charge.
    """
    parts: dict[str, str] = {}
    for chunk in rrule.strip().split(";"):
        if not chunk:
            continue
        name, _, value = chunk.partition("=")
        parts[name.strip().upper()] = value.strip().upper()
    unsupported = sorted(set(parts) - _SUPPORTED_PARTS)
    if unsupported:
        raise ValueError(
            "Repetition non prise en charge (" + ", ".join(unsupported) + "). "
            "Seuls des jours de semaine sur une plage de dates sont possibles."
        )
    return parts


def _parse_weekdays(parts: dict[str, str], start: date) -> tuple[int, ...]:
    """Determine les jours de semaine d'une regle quotidienne ou hebdomadaire."""
    freq = parts.get("FREQ")
    if freq not in ("DAILY", "WEEKLY"):
        raise ValueError(
            "Seules les repetitions quotidiennes et hebdomadaires sont prises en "
            "charge."
        )
    if parts.get("INTERVAL", "1") != "1":
        raise ValueError(
            "Une repetition « une semaine sur deux » (ou tous les N jours) n'est pas "
            "prise en charge."
        )
    byday = parts.get("BYDAY")
    if not byday:
        return tuple(range(7)) if freq == "DAILY" else (start.weekday(),)
    days: set[int] = set()
    for code in byday.split(","):
        if not re.fullmatch(r"(MO|TU|WE|TH|FR|SA|SU)", code.strip()):
            raise ValueError(
                "Une repetition du type « le 3e lundi du mois » n'est pas prise en "
                "charge."
            )
        days.add(_DAY_CODES.index(code.strip()))
    return tuple(sorted(days))


def _parse_until(value: str, tz: tzinfo) -> date:
    """Lit la valeur de UNTIL et retourne le dernier jour, en date locale."""
    try:
        if "T" not in value:
            return datetime.strptime(value, "%Y%m%d").date()
        if value.endswith("Z"):
            moment = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
            return moment.astimezone(tz).date()
        return datetime.strptime(value, "%Y%m%dT%H%M%S").date()
    except ValueError as err:
        raise ValueError(f"Fin de repetition illisible: {value!r}") from err


def _date_of_nth_occurrence(start: date, weekdays: tuple[int, ...], count: int) -> date:
    """Retourne la date de la n-ieme occurrence, a partir de ``start`` inclus."""
    found = 0
    day = start
    # Au plus 7 jours par occurrence demandee: la boucle est bornee.
    for _ in range(count * 7 + 7):
        if day.weekday() in weekdays:
            found += 1
            if found == count:
                return day
        day += timedelta(days=1)
    raise ValueError("Nombre de repetitions invalide")  # pragma: no cover


def manual_event_from_calendar(
    *,
    summary: str,
    dtstart: date | datetime,
    dtend: date | datetime,
    rrule: str | None,
    description: str | None,
    location: str | None,
    tz: tzinfo,
) -> ManualEvent:
    """Traduit un evenement cree dans la vue des calendriers en regle manuelle.

    Args:
        summary: Titre.
        dtstart: Debut. Une ``date`` pour une journee entiere, sinon un
            ``datetime``.
        dtend: Fin, exclusive pour une journee entiere.
        rrule: Regle de repetition RFC 5545, ou None pour un evenement ponctuel.
        description: Description saisie, que le modele ne peut pas conserver.
        location: Lieu saisi, que le modele ne peut pas conserver.
        tz: Fuseau local, pour lire les heures et la fin de repetition.

    Returns:
        Regle prete a etre enregistree. ``skip_closures`` est actif: le
        formulaire natif n'offre pas ce choix.

    Raises:
        ValueError: Si l'evenement demande n'est pas representable. Le message
            est destine a l'utilisateur.
    """
    if (description or "").strip() or (location or "").strip():
        raise ValueError(
            "La description et le lieu ne sont pas pris en charge pour les "
            "evenements manuels."
        )
    start_time = end_time = None
    if isinstance(dtstart, datetime):
        local_start = dtstart.astimezone(tz)
        local_end = dtend.astimezone(tz)
        if local_end.date() != local_start.date():
            raise ValueError(
                "Un evenement avec heures doit commencer et finir le meme jour."
            )
        start_day = local_start.date()
        start_time = local_start.time().replace(second=0, microsecond=0)
        end_time = local_end.time().replace(second=0, microsecond=0)
    else:
        start_day = dtstart
        if dtend - dtstart > timedelta(days=1):
            raise ValueError(
                "Un evenement de plusieurs jours n'est pas pris en charge. Utilisez "
                "une repetition hebdomadaire sur la plage voulue."
            )

    if rrule is None:
        weekdays: tuple[int, ...] = ()
        end_day = start_day
    else:
        parts = _parse_rrule(rrule)
        weekdays = _parse_weekdays(parts, start_day)
        has_until, has_count = "UNTIL" in parts, "COUNT" in parts
        if has_until and has_count:
            raise ValueError("UNTIL et COUNT ne peuvent pas etre combines.")
        if has_until:
            end_day = _parse_until(parts["UNTIL"], tz)
        elif has_count:
            try:
                count = int(parts["COUNT"])
            except ValueError as err:
                raise ValueError("Nombre de repetitions invalide") from err
            if not 1 <= count <= _MAX_COUNT:
                raise ValueError(
                    f"Le nombre de repetitions doit etre entre 1 et {_MAX_COUNT}."
                )
            end_day = _date_of_nth_occurrence(start_day, weekdays, count)
        else:
            raise ValueError(
                "Indiquez la fin de la repetition (une date ou un nombre de fois): "
                "une repetition sans fin n'est pas prise en charge."
            )

    return ManualEvent(
        event_id=build_manual_event_id(
            summary.strip(), start_day, weekdays, start_time
        ),
        summary=summary.strip(),
        start_date=start_day,
        end_date=end_day,
        weekdays=weekdays,
        start_time=start_time,
        end_time=end_time,
        skip_closures=True,
    )


def add_manual_rule(
    options: Mapping[str, Any], rule: ManualEvent, title: str
) -> dict[str, Any]:
    """Ajoute une regle aux options d'une entree, sans doublon.

    Args:
        options: Options courantes de l'entree.
        rule: Regle a ajouter.
        title: Titre de l'entree, pour le message d'erreur.

    Returns:
        Nouvelles options completes, a enregistrer.

    Raises:
        ValueError: Si une regle identique existe deja.
    """
    stored = [
        dict(item)
        for item in options.get(CONF_MANUAL_EVENTS) or []
        if isinstance(item, dict)
    ]
    if any(item.get("id") == rule.event_id for item in stored):
        raise ValueError(f"Un evenement manuel identique existe deja dans '{title}'.")
    stored.append(rule.as_dict())
    return {**options, CONF_MANUAL_EVENTS: stored}
