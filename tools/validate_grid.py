"""Validation de l'analyse geometrique sur le calendrier reel du CSS des Patriotes.

Les attentes sont derivees de la legende imprimee dans le document (22 conges,
16 journees pedagogiques, 4 journees pour force majeure) et des jours feries
quebecois de l'annee scolaire 2026-2027.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

# Chemins deduits de la position du script, sans reference absolue.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = ROOT / "custom_components" / "calendrier_scolaire_quebecois"

if not SOURCE.is_dir():
    sys.exit(f"Composant introuvable sous {ROOT}")

PDF = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "cssp-2026-2027.pdf"
if not PDF.is_file():
    sys.exit(f"PDF introuvable : {PDF}. Passe le chemin en argument.")

_workdir = Path(tempfile.mkdtemp(prefix="csq_grid_"))
_pkg = _workdir / "pkg"
_pkg.mkdir()
(_pkg / "__init__.py").write_text("", encoding="utf-8")
shutil.copy(SOURCE / "models.py", _pkg / "models.py")
shutil.copytree(SOURCE / "parsers", _pkg / "parsers")
sys.path.insert(0, str(_workdir))

import pdfplumber  # noqa: E402

from pkg.models import (  # noqa: E402
    EventCategory,
    deduplicate_events,
    normalize_text,
)
from pkg.parsers.events import detect_school_year  # noqa: E402
from pkg.parsers.grid import (  # noqa: E402
    _build_legend,
    _find_month_regions,
    _is_candidate_marker,
    extract_events_from_grid,
)
from pkg.parsers.pdf import read_pdf  # noqa: E402

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        failures.append(f"{label}\n      attendu : {expected!r}\n      obtenu  : {actual!r}")


document = read_pdf(PDF.read_bytes())
school_year = detect_school_year(document.text) or 2026
page = document.pages[0]

print("=" * 78)
print("1. ANNEE SCOLAIRE ET REGIONS")
print("=" * 78)
check("annee scolaire", school_year, 2026)
regions = _find_month_regions(page.words, school_year)
print(f"  annee scolaire detectee : {school_year}")
print(f"  regions mensuelles      : {len(regions)}")
check("nombre de regions", len(regions), 12)

for region in sorted(regions, key=lambda r: (r.year, r.month)):
    print(f"    {region.year}-{region.month:02d}  x={region.x_center:6.1f}")

expected_months = [
    (2026, 7), (2026, 8), (2026, 9), (2026, 10), (2026, 11), (2026, 12),
    (2027, 1), (2027, 2), (2027, 3), (2027, 4), (2027, 5), (2027, 6),
]
check(
    "mois et annees",
    sorted((r.year, r.month) for r in regions),
    expected_months,
)

print()
print("=" * 78)
print("2. LEGENDE RELEVEE DANS LE DOCUMENT")
print("=" * 78)
candidates = [s for s in page.shapes if _is_candidate_marker(s)]
legend = _build_legend(candidates, page.words, regions)
print(f"  {len(legend)} entree(s)")
for entry in legend:
    proto = entry.prototype
    print(
        f"    {proto.object_type:<6} {proto.width:5.1f}x{proto.height:<5.1f} "
        f"strk={str(proto.stroked):<5} fill={str(proto.filled):<5} "
        f"[{entry.category.value:<16}] {entry.label}"
    )
check("nombre d'entrees de legende", len(legend), 5)

categories = sorted(entry.category.value for entry in legend)
check(
    "categories de la legende",
    categories,
    ["holiday", "pedagogical_day", "pedagogical_day", "term_end", "term_start"],
)

print()
print("=" * 78)
print("3. EVENEMENTS EXTRAITS DE LA GRILLE")
print("=" * 78)
events = extract_events_from_grid(
    page.words, page.shapes, "CSS des Patriotes", school_year
)
print(f"  {len(events)} evenement(s)")
for event in events:
    span = (
        f"{event.first_day}"
        if event.first_day == event.last_day
        else f"{event.first_day} -> {event.last_day}"
    )
    print(f"    {span:<26} [{event.category.value:<16}] {event.summary}")

print()
print("=" * 78)
print("4. VERIFICATION DU NOMBRE DE JOURNEES PAR CATEGORIE")
print("=" * 78)
# La legende du document annonce 22 conges et 16 journees pedagogiques. Les
# fins de semaine enjambees lors du regroupement ne doivent pas etre comptees.
def marked_days(predicate) -> int:
    days: set[date] = set()
    for event in events:
        if not predicate(event):
            continue
        current = event.first_day
        while current <= event.last_day:
            if current.weekday() < 5:
                days.add(current)
            current += __import__("datetime").timedelta(days=1)
    return len(days)


conges = marked_days(lambda e: e.category is EventCategory.HOLIDAY)
pedago = marked_days(
    lambda e: e.category is EventCategory.PEDAGOGICAL_DAY
    and "force majeure" not in normalize_text(e.summary)
)
force = marked_days(lambda e: "force majeure" in normalize_text(e.summary))

print(f"  conges (jours de semaine)              : {conges}  (legende : 22)")
print(f"  journees pedagogiques                  : {pedago}  (legende : 16)")
print(f"  journees pedagogiques force majeure    : {force}   (legende : 4)")

check("nombre de conges", conges, 22)
check("nombre de journees pedagogiques", pedago, 16)
check("nombre de journees force majeure", force, 4)

print()
print("=" * 78)
print("5. DATES CLES ATTENDUES")
print("=" * 78)


def covers(first: date, last: date, category: EventCategory) -> bool:
    return any(
        e.first_day == first and e.last_day == last and e.category is category
        for e in events
    )


expectations = [
    ("Conge du 1er juillet", date(2026, 7, 1), date(2026, 7, 1), EventCategory.HOLIDAY),
    ("Fete du Travail", date(2026, 9, 7), date(2026, 9, 7), EventCategory.HOLIDAY),
    ("Action de grace", date(2026, 10, 12), date(2026, 10, 12), EventCategory.HOLIDAY),
    (
        "Conge des fetes 23 dec -> 5 janv",
        date(2026, 12, 23),
        date(2027, 1, 5),
        EventCategory.HOLIDAY,
    ),
    (
        "Semaine de relache 1er -> 5 mars",
        date(2027, 3, 1),
        date(2027, 3, 5),
        EventCategory.HOLIDAY,
    ),
    (
        "Conge de Paques 26 -> 29 mars",
        date(2027, 3, 26),
        date(2027, 3, 29),
        EventCategory.HOLIDAY,
    ),
    (
        "Journee des patriotes",
        date(2027, 5, 24),
        date(2027, 5, 24),
        EventCategory.HOLIDAY,
    ),
    ("Saint-Jean", date(2027, 6, 24), date(2027, 6, 24), EventCategory.HOLIDAY),
    (
        "Pedagogiques 25 -> 31 aout",
        date(2026, 8, 25),
        date(2026, 8, 31),
        EventCategory.PEDAGOGICAL_DAY,
    ),
    (
        "Pedagogiques 19 -> 20 novembre",
        date(2026, 11, 19),
        date(2026, 11, 20),
        EventCategory.PEDAGOGICAL_DAY,
    ),
    (
        "Pedagogiques 11 -> 12 fevrier",
        date(2027, 2, 11),
        date(2027, 2, 12),
        EventCategory.PEDAGOGICAL_DAY,
    ),
    (
        "Pedagogiques 25 -> 29 juin",
        date(2027, 6, 25),
        date(2027, 6, 29),
        EventCategory.PEDAGOGICAL_DAY,
    ),
]

for label, first, last, category in expectations:
    ok = covers(first, last, category)
    print(f"  {'OK ' if ok else 'ECHEC'}  {label}")
    if not ok:
        failures.append(f"Plage attendue absente : {label} ({first} -> {last})")

# Les libelles portent des accents: la comparaison doit passer par
# normalize_text, sinon "rentree" ne correspond pas a "rentrée".
rentree = [e for e in events if "rentree" in normalize_text(e.summary)]
fin = [e for e in events if "fin des classes" in normalize_text(e.summary)]

print(f"  {'OK ' if rentree else 'ECHEC'}  Rentree scolaire")
for event in rentree:
    print(f"        {event.first_day} : {event.summary}")
print(f"  {'OK ' if fin else 'ECHEC'}  Fin des classes")
for event in fin:
    print(f"        {event.first_day} : {event.summary}")

check("rentree scolaire le 1er septembre", [e.first_day for e in rentree], [date(2026, 9, 1)])
check("fin des classes le 23 juin", [e.first_day for e in fin], [date(2027, 6, 23)])

print()
print("=" * 78)
print("6. ABSENCE DE POLLUTION PAR LES FINS DE SEMAINE")
print("=" * 78)
# 120 cellules grises marquent les fins de semaine. Elles ne doivent produire
# aucun evenement: leur signature (aplat sans contour) est incompatible avec
# celles de la legende.
print(f"  evenements totaux : {len(events)}")
print("  un ombrage de fin de semaine capte produirait plus de 100 journees")
check("total plausible", len(events) < 40, True)

print()
print("=" * 78)
print("7. FUSION AVEC L'ANALYSE TEXTUELLE")
print("=" * 78)
from pkg.parsers.events import extract_events_from_text  # noqa: E402

textual = extract_events_from_text(document.text, "CSS des Patriotes", school_year)
merged = deduplicate_events(textual + events)
print(f"  texte    : {len(textual)} evenement(s)")
print(f"  grille   : {len(events)} evenement(s)")
print(f"  fusionne : {len(merged)} evenement(s)")
check("la fusion ne perd rien", len(merged) >= len(events), True)

print()
print("=" * 78)
print("8. BORNES DE L'ANNEE SCOLAIRE DEDUITES DU DOCUMENT")
print("=" * 78)
from pkg.models import resolve_term_membership  # noqa: E402

starts = sorted(
    e.first_day for e in events if e.category is EventCategory.TERM_START
)
ends = sorted(e.last_day for e in events if e.category is EventCategory.TERM_END)

print(f"  rentree        : {starts}")
print(f"  fin des classes: {ends}")

check("une seule rentree", starts, [date(2026, 9, 1)])
check("une seule fin des classes", ends, [date(2027, 6, 23)])

# Le document ne marque pas les vacances d'ete: elles se deduisent des bornes.
periods = [
    ("2026-08-18 (avant la rentree)", date(2026, 8, 18), False),
    ("2026-07-15 (plein ete)", date(2026, 7, 15), False),
    ("2026-09-01 (jour de la rentree)", date(2026, 9, 1), True),
    ("2026-12-01 (en cours d'annee)", date(2026, 12, 1), True),
    ("2027-06-23 (dernier jour)", date(2027, 6, 23), True),
    ("2027-07-05 (apres la fin)", date(2027, 7, 5), False),
]

for label, day, expected in periods:
    actual = resolve_term_membership(day, starts, ends)
    status = "OK " if actual is expected else "ECHEC"
    print(f"  {status}  {label:<34} -> en periode scolaire : {actual}")
    if actual is not expected:
        failures.append(f"Periode scolaire incorrecte pour {label}")

shutil.rmtree(_workdir, ignore_errors=True)

print()
if failures:
    print(f"ECHECS ({len(failures)}) :\n")
    for failure in failures:
        print(f"  - {failure}")
    sys.exit(1)

print("Toutes les verifications passent.")
