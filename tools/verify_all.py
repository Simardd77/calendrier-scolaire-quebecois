"""Verification complete de l'integration, sans Home Assistant installe.

Couvre la structure du depot, la coherence des metadonnees, et les regressions
des modules d'analyse purs. La validation sur PDF reel est dans validate_grid.py.
"""

from __future__ import annotations

import json
import py_compile
import re
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

# Ce script vit dans <depot>/tools/. La racine du depot est deduite de sa
# propre position: aucun chemin absolu, et le renommage du dossier reste sans
# effet.
ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "calendrier_scolaire_quebecois"

if not COMPONENT.is_dir():
    sys.exit(f"Composant introuvable sous {ROOT}")

problems: list[str] = []
notes: list[str] = []


def fail(message: str) -> None:
    problems.append(message)


def check(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        fail(f"{label}\n      attendu : {expected!r}\n      obtenu  : {actual!r}")


print(f"Python local : {sys.version.split()[0]}")
print(f"Projet       : {ROOT.name}")
print()

# --- 1. Compilation ---------------------------------------------------------
py_files = sorted(COMPONENT.rglob("*.py"))
print(f"1. Compilation de {len(py_files)} fichier(s) Python")

_cache = Path(tempfile.mkdtemp(prefix="csq_pyc_"))
for index, path in enumerate(py_files):
    try:
        py_compile.compile(str(path), doraise=True, cfile=str(_cache / f"{index}.pyc"))
    except py_compile.PyCompileError as err:
        fail(f"Compilation echouee : {path.relative_to(ROOT)}\n      {err.msg.strip()}")
shutil.rmtree(_cache, ignore_errors=True)

# --- 2. JSON ----------------------------------------------------------------
json_files = {
    "hacs": ROOT / "hacs.json",
    "manifest": COMPONENT / "manifest.json",
    "strings": COMPONENT / "strings.json",
    "fr": COMPONENT / "translations" / "fr.json",
    "en": COMPONENT / "translations" / "en.json",
}
print(f"2. Validation de {len(json_files)} fichier(s) JSON")

loaded: dict[str, dict] = {}
for name, path in json_files.items():
    if not path.is_file():
        fail(f"Fichier JSON absent : {path.relative_to(ROOT)}")
        continue
    try:
        loaded[name] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        fail(f"JSON invalide : {path.relative_to(ROOT)} ({err})")

# --- 3. YAML ----------------------------------------------------------------
print("3. Validation de services.yaml")
services_yaml: dict | None = None
try:
    import yaml

    services_yaml = yaml.safe_load(
        (COMPONENT / "services.yaml").read_text(encoding="utf-8")
    )
except ImportError:
    notes.append("pyyaml absent : services.yaml non valide syntaxiquement")
except Exception as err:  # noqa: BLE001
    fail(f"services.yaml invalide : {err}")

# --- 4. Parite des traductions ----------------------------------------------
print("4. Parite des cles de traduction")


def key_paths(node: object, prefix: str = "") -> set[str]:
    if not isinstance(node, dict):
        return {prefix}
    paths: set[str] = set()
    for key, value in node.items():
        paths |= key_paths(value, f"{prefix}.{key}" if prefix else key)
    return paths


if "strings" in loaded and "fr" in loaded:
    if key_paths(loaded["strings"]) != key_paths(loaded["fr"]):
        fail("strings.json et translations/fr.json n'ont pas les memes cles")

if "strings" in loaded and "en" in loaded:
    missing = key_paths(loaded["strings"]) - key_paths(loaded["en"])
    extra = key_paths(loaded["en"]) - key_paths(loaded["strings"])
    if missing:
        fail(f"Cles absentes de en.json : {sorted(missing)}")
    if extra:
        fail(f"Cles en trop dans en.json : {sorted(extra)}")

# --- 5. Cles de traduction des entites --------------------------------------
print("5. Cles de traduction des entites")
strings = loaded.get("strings", {})
entity_section = strings.get("entity", {})

for platform in ("sensor", "binary_sensor"):
    source = (COMPONENT / f"{platform}.py").read_text(encoding="utf-8")
    declared = set(re.findall(r'_attr_translation_key = "([^"]+)"', source))
    available = set(entity_section.get(platform, {}))
    for key in sorted(declared - available):
        fail(f"Cle '{key}' de {platform}.py absente de strings.json")

# --- 6. Services ------------------------------------------------------------
print("6. Coherence des services")
const_source = (COMPONENT / "const.py").read_text(encoding="utf-8")
service_names = set(re.findall(r'^SERVICE_\w+: Final = "([^"]+)"', const_source, re.M))

if services_yaml is not None:
    for name in sorted(service_names):
        if name not in services_yaml:
            fail(f"Service '{name}' absent de services.yaml")

for name in sorted(service_names):
    if name not in strings.get("services", {}):
        fail(f"Service '{name}' absent de strings.json")

if "train_parser" in service_names:
    fail("Le service train_parser devait etre supprime")

# --- 7. Modules supprimes ---------------------------------------------------
print("7. Absence de references aux modules supprimes")
forbidden = {
    "learning": r"\blearning\b",
    "engines": r"from \.engines|from \.\.engines",
    "entities": r"from \.entities|from \.\.entities",
    "helpers locaux": r"from \.helpers|from \.\.helpers",
    "core.manager": r"core\.manager|SchoolCalendarManager",
}
for path in py_files:
    text = path.read_text(encoding="utf-8")
    for label, pattern in forbidden.items():
        if re.search(pattern, text):
            fail(f"Reference residuelle a '{label}' dans {path.relative_to(ROOT)}")

for stale in ("core", "engines", "entities", "helpers"):
    directory = COMPONENT / stale
    if directory.exists():
        fail(f"Le repertoire '{stale}' existe encore")

# --- 8. Appels bloquants ----------------------------------------------------
print("8. Absence d'appels bloquants dans le code asynchrone")
for path in py_files:
    if path.parent.name == "parsers":
        continue  # Modules synchrones appeles via un executor, par conception.
    text = path.read_text(encoding="utf-8")
    if re.search(r"^\s*(with )?open\(", text, re.M):
        fail(f"Appel open() direct dans {path.relative_to(ROOT)}")
    if "aiohttp.ClientSession()" in text:
        fail(f"Session aiohttp creee manuellement dans {path.relative_to(ROOT)}")

# --- 9. Coroutines non attendues -------------------------------------------
print("9. Detection de coroutines non attendues")
coordinator_source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
for name in ("events_between", "events_on", "next_event"):
    if re.search(rf"async def {name}\b", coordinator_source):
        fail(f"CalendarData.{name} ne doit pas etre asynchrone")

allowed = {"events_between", "events_on", "next_event", "is_within_term"}
for platform in ("sensor.py", "binary_sensor.py", "calendar.py"):
    text = (COMPONENT / platform).read_text(encoding="utf-8")
    for call in re.findall(r"self\.calendar_data\.(\w+)\(", text):
        if call not in allowed:
            fail(f"Appel inattendu calendar_data.{call}() dans {platform}")

# --- 10. Manifest -----------------------------------------------------------
print("10. Verification du manifest")
manifest = loaded.get("manifest", {})
for key in ("domain", "name", "config_flow", "iot_class", "requirements", "version"):
    if key not in manifest:
        fail(f"Cle '{key}' absente de manifest.json")

check("domaine du manifest", manifest.get("domain"), "calendrier_scolaire_quebecois")

required = " ".join(manifest.get("requirements", []))
for package in ("pdfplumber", "icalendar"):
    if package not in required:
        fail(f"'{package}' devrait figurer dans les requirements")
for package in ("pytesseract", "pdf2image", "pillow"):
    if package in required:
        fail(f"'{package}' ne doit pas figurer dans les requirements")

if "homeassistant" in loaded.get("hacs", {}):
    floor = loaded["hacs"]["homeassistant"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if floor not in readme:
        fail(f"Le plancher {floor} de hacs.json n'apparait pas dans le README")

# --- 11. Fichiers attendus --------------------------------------------------
print("11. Presence des fichiers attendus")
expected = [
    "__init__.py",
    "binary_sensor.py",
    "calendar.py",
    "config_flow.py",
    "const.py",
    "coordinator.py",
    "entity.py",
    "fetcher.py",
    "manifest.json",
    "models.py",
    "sensor.py",
    "services.yaml",
    "strings.json",
    "parsers/__init__.py",
    "parsers/dates.py",
    "parsers/events.py",
    "parsers/grid.py",
    "parsers/ical.py",
    "parsers/ocr.py",
    "parsers/pdf.py",
    "translations/en.json",
    "translations/fr.json",
]
for relative in expected:
    if not (COMPONENT / relative).is_file():
        fail(f"Fichier attendu absent : {relative}")

# --- 12. Regressions des analyseurs purs ------------------------------------
print("12. Regressions des analyseurs")

_workdir = Path(tempfile.mkdtemp(prefix="csq_pure_"))
_pkg = _workdir / "pkg"
_pkg.mkdir()
(_pkg / "__init__.py").write_text("", encoding="utf-8")
shutil.copy(COMPONENT / "models.py", _pkg / "models.py")
shutil.copytree(COMPONENT / "parsers", _pkg / "parsers")
sys.path.insert(0, str(_workdir))

from pkg.models import (  # noqa: E402
    SCHOOL_CLOSED_CATEGORIES,
    EventCategory,
    SchoolEvent,
    clean_summary,
    deduplicate_events,
    merge_extraction_results,
    resolve_term_membership,
)
from pkg.parsers.dates import find_date_spans, school_year_start_for  # noqa: E402
from pkg.parsers.events import (  # noqa: E402
    classify,
    detect_school_year,
    extract_events_from_text,
)
from pkg.parsers.grid import (  # noqa: E402
    ShapePrototype,
    _is_bridgeable,
    _merge_consecutive,
)

SY = 2024


def spans(text: str) -> list[tuple[date, date]]:
    return [(s.start, s.last_day) for s in find_date_spans(text, SY)]


check("annee scolaire aout", school_year_start_for(date(2024, 8, 29)), 2024)
check("annee scolaire janvier", school_year_start_for(date(2025, 1, 15)), 2024)
check("detect_school_year", detect_school_year("Calendrier 2024-2025"), 2024)

check(
    "plage deux mois",
    spans("Vacances des fetes du 23 decembre au 6 janvier"),
    [(date(2024, 12, 23), date(2025, 1, 6))],
)
check(
    "plage meme mois",
    spans("Semaine de relache du 3 au 7 mars"),
    [(date(2025, 3, 3), date(2025, 3, 7))],
)
check(
    "premier du mois",
    spans("1er juillet - Fete du Canada"),
    [(date(2025, 7, 1), date(2025, 7, 1))],
)
check(
    "date numerique",
    spans("Examen 15/01/2025"),
    [(date(2025, 1, 15), date(2025, 1, 15))],
)
check("numero de version rejete", spans("Version 1.12.0"), [])
check("numero de page rejete", spans("Page 2 de 15"), [])
check("mot contenant un mois rejete", spans("La maison des jeunes"), [])
check("date impossible rejetee", spans("31 fevrier 2025"), [])
check("telephone rejete", spans("Info 514-555-1234"), [])

check("classe pedagogique", classify("Journee pedagogique"), EventCategory.PEDAGOGICAL_DAY)
check("classe conge", classify("Conge ferie"), EventCategory.HOLIDAY)
check(
    "pedagogique prime sur conge",
    classify("Conge - journee pedagogique"),
    EventCategory.PEDAGOGICAL_DAY,
)
# Une journee pedagogique n'est pas toujours nommee comme telle.
check(
    "journee pedagogique decrite sans le mot",
    classify("Conge pour les eleves - travail pour les enseignants"),
    EventCategory.PEDAGOGICAL_DAY,
)
# Un conge commun a tous reste un conge, meme si le personnel est mentionne.
check(
    "conge commun reste un conge",
    classify("Conge pour le personnel et les eleves"),
    EventCategory.HOLIDAY,
)
check(
    "conge mentionnant les deux corps reste un conge",
    classify("Conges pour les eleves, les enseignantes et les enseignants"),
    EventCategory.HOLIDAY,
)
check("classe inconnue", classify("Bla bla truc"), None)
check(
    "classe rentree",
    classify("Rentree scolaire des eleves"),
    EventCategory.TERM_START,
)
check(
    "classe fin des classes",
    classify("Fin des classes pour les eleves"),
    EventCategory.TERM_END,
)
# Les bornes de l'annee sont evaluees du point de vue des eleves: une rentree du
# personnel ne borne pas l'annee scolaire.
check(
    "rentree du personnel non typee",
    classify("Rentree des enseignants"),
    EventCategory.EVENT,
)
check(
    "rentree mentionnant les deux publics",
    classify("Rentree des enseignants et des eleves"),
    EventCategory.TERM_START,
)
check(
    "rentree sans public precise",
    classify("Rentree scolaire"),
    EventCategory.TERM_START,
)
# La regle ne s'applique qu'aux bornes: un conge du personnel reste un conge.
check(
    "conge du personnel reste un conge",
    classify("Conge pour le personnel"),
    EventCategory.HOLIDAY,
)
# La rentree et la fin des classes sont des journees de classe: elles ne
# ferment pas l'ecole.
check(
    "la rentree ne ferme pas l'ecole",
    EventCategory.TERM_START in SCHOOL_CLOSED_CATEGORIES,
    False,
)
check(
    "la fin des classes ne ferme pas l'ecole",
    EventCategory.TERM_END in SCHOOL_CLOSED_CATEGORIES,
    False,
)
# Une journee pedagogique le jour de la rentree reste une fermeture.
check(
    "pedagogique prime sur la rentree",
    classify("Rentree des enseignants - journee pedagogique"),
    EventCategory.PEDAGOGICAL_DAY,
)

# Les parentheses doivent etre conservees pour ne pas produire de libelle
# desequilibre a partir de la legende d'un calendrier.
check(
    "clean_summary conserve les parentheses",
    clean_summary("Journees pedagogiques (conge pour les eleves)"),
    "Journees pedagogiques (conge pour les eleves)",
)
check("clean_summary retire la ponctuation de bordure", clean_summary(" - Conge : "), "Conge")

events = extract_events_from_text(
    "29 aout 2024 - Rentree scolaire des eleves\n"
    "Journee pedagogique le 4 octobre\n"
    "Vacances des fetes du 23 decembre 2024 au 6 janvier 2025\n",
    "Test",
    SY,
)
check("extraction de base", len(events), 3)
check(
    "titres nettoyes",
    [e.summary for e in events],
    ["Rentree scolaire des eleves", "Journee pedagogique", "Vacances des fetes"],
)

fetes = next(e for e in events if e.summary == "Vacances des fetes")
check("fin exclusive", fetes.end, date(2025, 1, 7))
check("derniere journee incluse", fetes.last_day, date(2025, 1, 6))
check("couvre le 25 decembre", fetes.occurs_on(date(2024, 12, 25)), True)
check("ne couvre pas le 7 janvier", fetes.occurs_on(date(2025, 1, 7)), False)
check("ferme l'ecole", fetes.closes_school, True)

check(
    "deduplication par titre et dates",
    len(
        deduplicate_events(
            [
                SchoolEvent("Conge", date(2025, 3, 3), date(2025, 3, 4), source="a"),
                SchoolEvent("congé", date(2025, 3, 3), date(2025, 3, 4), source="b"),
                SchoolEvent("Conge", date(2025, 4, 3), date(2025, 4, 4), source="a"),
            ]
        )
    ),
    2,
)

try:
    SchoolEvent("X", date(2025, 1, 2), date(2025, 1, 2))
    fail("SchoolEvent aurait du refuser end == start")
except ValueError:
    pass

try:
    SchoolEvent("X", date(2025, 1, 2), datetime(2025, 1, 3))
    fail("SchoolEvent aurait du refuser un melange date/datetime")
except ValueError:
    pass

# --- 12b. Priorite de la grille sur le texte --------------------------------
print("12b. Priorite de la grille sur le texte")

_note = SchoolEvent(
    "phrase tronquee issue d'une note",
    date(2027, 4, 1),
    date(2027, 4, 2),
    category=EventCategory.EVENT,
)
_typed = SchoolEvent(
    "Rentree des eleves",
    date(2026, 8, 27),
    date(2026, 8, 28),
    category=EventCategory.TERM_START,
)
_from_grid = SchoolEvent(
    "Conge",
    date(2026, 12, 23),
    date(2026, 12, 24),
    category=EventCategory.HOLIDAY,
)

check(
    "sans grille, tout le texte est conserve",
    len(merge_extraction_results([_note, _typed], [])),
    2,
)
check(
    "avec grille, les mentions non classees sont ecartees",
    [event.summary for event in merge_extraction_results([_note, _typed], [_from_grid])],
    ["Rentree des eleves", "Conge"],
)

# --- 13. Bornes de l'annee scolaire -----------------------------------------
print("13. Bornes de l'annee scolaire")

# Cas du calendrier 2026-2027 : rentree le 1er septembre, fin le 23 juin.
STARTS = [date(2026, 9, 1)]
ENDS = [date(2027, 6, 23)]

check(
    "avant la rentree, hors periode",
    resolve_term_membership(date(2026, 8, 18), STARTS, ENDS),
    False,
)
check(
    "le jour de la rentree, en periode",
    resolve_term_membership(date(2026, 9, 1), STARTS, ENDS),
    True,
)
check(
    "en cours d'annee, en periode",
    resolve_term_membership(date(2026, 12, 1), STARTS, ENDS),
    True,
)
check(
    "le dernier jour de classe, en periode",
    resolve_term_membership(date(2027, 6, 23), STARTS, ENDS),
    True,
)
check(
    "apres la fin des classes, hors periode",
    resolve_term_membership(date(2027, 7, 5), STARTS, ENDS),
    False,
)
check(
    "sans borne connue, indetermine",
    resolve_term_membership(date(2026, 8, 18), [], []),
    None,
)
# Sans fin annoncee, la periode est bornee a la fin juin suivante: un
# calendrier qui ne marque que sa rentree ne doit pas laisser l'ecole ouverte
# l'ete d'apres.
check(
    "rentree connue sans fin, en periode avant juin",
    resolve_term_membership(date(2027, 5, 3), STARTS, []),
    True,
)
check(
    "rentree connue sans fin, hors periode en juillet",
    resolve_term_membership(date(2027, 7, 5), STARTS, []),
    False,
)
check(
    "fin connue sans rentree, en periode avant la fin",
    resolve_term_membership(date(2027, 1, 5), [], ENDS),
    True,
)
check(
    "fin connue sans rentree, hors periode apres",
    resolve_term_membership(date(2027, 7, 5), [], ENDS),
    False,
)

# --- 14. Logique de grille --------------------------------------------------
print("14. Logique d'analyse en grille")

# Enjambement des fins de semaine: un vendredi et le lundi suivant forment une
# seule plage, mais un ecart contenant un jour ouvrable la coupe.
check("vendredi vers lundi", _is_bridgeable(date(2027, 3, 26), date(2027, 3, 29)), True)
check("jours consecutifs", _is_bridgeable(date(2027, 3, 1), date(2027, 3, 2)), True)
check("ecart avec jour ouvrable", _is_bridgeable(date(2027, 3, 1), date(2027, 3, 4)), False)

check(
    "fusion du conge des fetes",
    _merge_consecutive(
        [date(2026, 12, 23), date(2026, 12, 24), date(2026, 12, 25)]
        + [date(2026, 12, 28), date(2026, 12, 29), date(2026, 12, 30), date(2026, 12, 31)]
        + [date(2027, 1, 1), date(2027, 1, 4), date(2027, 1, 5)]
    ),
    [(date(2026, 12, 23), date(2027, 1, 5))],
)
check(
    "plages disjointes conservees",
    _merge_consecutive([date(2027, 3, 1), date(2027, 3, 2), date(2027, 5, 24)]),
    [(date(2027, 3, 1), date(2027, 3, 2)), (date(2027, 5, 24), date(2027, 5, 24))],
)

# Un aplat sans contour ne peut pas correspondre a une forme contournee: c'est
# ce qui empeche l'ombrage des fins de semaine de produire des evenements.
circle = ShapePrototype("curve", 15.0, 13.0, True, False, "none", "g0.000")
weekend = ShapePrototype("rect", 19.9, 14.8, False, True, "g0.867", "none")
square = ShapePrototype("rect", 15.2, 13.7, True, False, "none", "g0.000")

check("ombrage incompatible avec contour", circle.distance_to(weekend), None)
check("types differents incompatibles", square.distance_to(circle), None)
check(
    "meme famille compatible",
    round(ShapePrototype("curve", 15.2, 14.2, True, False, "none", "g0.000").distance_to(circle), 2),
    1.22,
)

# Deux remplissages de couleurs differentes designent deux significations.
fill_a = ShapePrototype("rect", 18.0, 14.0, False, True, "c1.000,0.800,0.000", "none")
fill_b = ShapePrototype("rect", 18.0, 14.0, False, True, "c0.000,0.600,1.000", "none")
check("couleurs de remplissage distinctes", fill_a.distance_to(fill_b), None)
check("meme couleur de remplissage", fill_a.distance_to(fill_a), 0.0)

# Deux triangles d'orientations opposees ont la meme boite englobante. Seul le
# centroide des sommets les distingue: un triangle pointant vers le haut
# concentre ses sommets d'un cote, l'autre du cote oppose.
triangle_up = ShapePrototype(
    "curve", 21.5, 15.5, True, False, "none", "g0.000", 0.50, 0.75
)
triangle_down = ShapePrototype(
    "curve", 21.5, 15.5, True, False, "none", "g0.000", 0.50, 0.25
)
no_vertices = ShapePrototype("curve", 21.5, 15.5, True, False, "none", "g0.000")

check(
    "orientations opposees incompatibles",
    triangle_up.distance_to(triangle_down),
    None,
)
check("meme orientation compatible", triangle_up.distance_to(triangle_up), 0.0)
check(
    "sans sommets, seules les dimensions comptent",
    no_vertices.distance_to(triangle_down),
    0.0,
)

shutil.rmtree(_workdir, ignore_errors=True)

# --- Resultat ---------------------------------------------------------------
print()
for note in notes:
    print(f"NOTE : {note}")

if problems:
    print(f"\nPROBLEMES ({len(problems)}) :\n")
    for problem in problems:
        print(f"  - {problem}")
    sys.exit(1)

print("\nToutes les verifications passent.")
