"""Diagnostic d'extraction sur un calendrier quelconque.

Contrairement a validate_grid.py, ce script n'impose aucune attente: il rapporte
ce que l'integration extrait et, surtout, ce qu'elle n'a pas su interpreter.

Usage:
    python3 analyze_pdf.py chemin/vers/calendrier.pdf
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = ROOT / "custom_components" / "calendrier_scolaire_quebecois"

if not SOURCE.is_dir():
    sys.exit(f"Composant introuvable sous {ROOT}")

if len(sys.argv) < 2:
    sys.exit("Usage: python3 analyze_pdf.py chemin/vers/calendrier.pdf")

PDF = Path(sys.argv[1])
if not PDF.is_file():
    sys.exit(f"PDF introuvable : {PDF}")

_workdir = Path(tempfile.mkdtemp(prefix="csq_analyze_"))
_pkg = _workdir / "pkg"
_pkg.mkdir()
(_pkg / "__init__.py").write_text("", encoding="utf-8")
shutil.copy(SOURCE / "models.py", _pkg / "models.py")
shutil.copytree(SOURCE / "parsers", _pkg / "parsers")
sys.path.insert(0, str(_workdir))

from pkg.models import (  # noqa: E402
    EventCategory,
    merge_extraction_results,
    resolve_term_membership,
)
from pkg.parsers.dates import school_year_start_for  # noqa: E402
from pkg.parsers.events import (  # noqa: E402
    detect_school_year,
    extract_events_from_text,
)
from pkg.parsers.grid import (  # noqa: E402
    ShapePrototype,
    _build_legend,
    _center,
    _day_words,
    _enclosed_day,
    _find_month_regions,
    _is_candidate_marker,
    _label_right_of,
    _match_legend,
    extract_events_from_grid,
)
from pkg.parsers.pdf import read_pdf  # noqa: E402

from datetime import date  # noqa: E402


def rule(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


document = read_pdf(PDF.read_bytes())
declared_year = detect_school_year(document.text)
school_year = declared_year or school_year_start_for(date.today())

rule("1. DOCUMENT")
print(f"  fichier              : {PDF.name}")
print(f"  pages                : {len(document.pages)}")
print(f"  couche texte         : {'oui' if document.has_text else 'non'}")
print(f"  annee scolaire lue   : {declared_year or 'non annoncee'}")
print(f"  annee scolaire reten.: {school_year}")

rule("2. ANALYSE TEXTUELLE")
textual = extract_events_from_text(document.text, PDF.stem, school_year)
print(f"  {len(textual)} evenement(s)")
for event in textual[:20]:
    print(f"    {event.first_day} -> {event.last_day}  [{event.category.value}]  {event.summary}")
if len(textual) > 20:
    print(f"    ... et {len(textual) - 20} autre(s)")

grid_events = []

for index, page in enumerate(document.pages, start=1):
    regions = _find_month_regions(page.words, school_year)
    if not regions:
        continue

    rule(f"3. GRILLES DETECTEES (page {index})")
    print(f"  {len(regions)} region(s) mensuelle(s)")
    for region in sorted(regions, key=lambda r: (r.year, r.month)):
        print(
            f"    {region.year}-{region.month:02d}  x={region.x_center:6.1f} "
            f"y={region.top:6.1f} -> {region.bottom:6.1f}"
        )

    candidates = [s for s in page.shapes if _is_candidate_marker(s)]
    legend = _build_legend(candidates, page.words, regions)

    rule(f"4. LEGENDE RELEVEE (page {index})")
    print(f"  {len(legend)} entree(s) sur {len(candidates)} forme(s) candidate(s)")
    for entry in legend:
        proto = entry.prototype
        print(
            f"    {proto.object_type:<6} {proto.width:5.1f}x{proto.height:<5.1f} "
            f"strk={str(proto.stroked)[0]} fill={str(proto.filled)[0]} "
            f"trait={proto.stroke_color:<16} fond={proto.fill_color:<16} "
            f"[{entry.category.value}]"
        )
        print(f"           -> {entry.label}")

    rule(f"4b. TOUTES LES FORMES HORS GRILLES (page {index})")
    print("  Diagnostic de la legende: pourquoi une forme n'y figure pas.")
    outside = []
    for shape in page.shapes:
        x, y = _center(shape)
        if any(r.contains(x, y) for r in regions):
            continue
        outside.append(shape)

    print(f"  {len(outside)} forme(s) hors des grilles")
    for shape in sorted(outside, key=lambda s: s["top"]):
        width = shape["x1"] - shape["x0"]
        height = shape["bottom"] - shape["top"]
        pts = shape.get("points") or []
        candidate = _is_candidate_marker(shape)
        label = _label_right_of(shape, page.words) if candidate else ""

        centroid = ""
        if pts:
            mean_y = sum(p[1] for p in pts) / len(pts)
            span = max((p[1] for p in pts)) - min((p[1] for p in pts))
            if span:
                centroid = f" centroide_y={(mean_y - min(p[1] for p in pts)) / span:.2f}"

        print(
            f"    {str(shape.get('object_type')):<6} "
            f"y={shape['top']:7.1f} {width:5.1f}x{height:<5.1f} "
            f"pts={len(pts):<3} strk={str(shape.get('stroke'))[0]} "
            f"fill={str(shape.get('fill'))[0]} "
            f"cand={'oui' if candidate else 'NON'}{centroid}"
        )
        print(f"           libelle: {label or '(AUCUN)'}")

    rule(f"5. EVENEMENTS DE LA GRILLE (page {index})")
    page_events = extract_events_from_grid(
        page.words, page.shapes, PDF.stem, school_year
    )
    grid_events.extend(page_events)
    print(f"  {len(page_events)} evenement(s)")
    for event in page_events:
        span = (
            f"{event.first_day}"
            if event.first_day == event.last_day
            else f"{event.first_day} -> {event.last_day}"
        )
        print(f"    {span:<26} [{event.category.value:<16}] {event.summary}")

    rule(f"5b. MARQUEURS DE GRILLE ET APPARIEMENT (page {index})")
    print("  Dimensions reelles, sommets disponibles, et entree de legende")
    print("  retenue avec sa distance. Une distance elevee signale un")
    print("  appariement fragile.")
    days_for_debug = _day_words(page.words)
    for shape in sorted(candidates, key=lambda s: (s["top"], s["x0"])):
        x, y = _center(shape)
        region = next((r for r in regions if r.contains(x, y)), None)
        if region is None:
            continue

        proto = ShapePrototype.from_shape(shape)
        entry = _match_legend(proto, legend)
        day = _enclosed_day(shape, days_for_debug)
        vertices = shape.get("points") or shape.get("pts") or []

        centroid = "-"
        if vertices:
            ys = [point[1] for point in vertices]
            span = max(ys) - min(ys)
            if span:
                centroid = f"{(sum(ys) / len(ys) - min(ys)) / span:.2f}"

        distances = sorted(
            (proto.distance_to(other.prototype), other.label)
            for other in legend
            if proto.distance_to(other.prototype) is not None
        )
        detail = ", ".join(f"{d:.2f}={label[:22]}" for d, label in distances[:3])

        stamp = (
            f"{region.year}-{region.month:02d}-{day:02d}"
            if day is not None
            else f"{region.year}-{region.month:02d}-??"
        )
        print(
            f"    {stamp}  {proto.object_type:<6} "
            f"{proto.width:5.1f}x{proto.height:<5.1f} som={len(vertices):<3} "
            f"centro={centroid:<5} -> {(entry.label[:34] if entry else 'AUCUN')}"
        )
        print(f"        candidats: {detail}")

    rule(f"6. FORMES NON INTERPRETEES DANS LES GRILLES (page {index})")
    print("  Ces formes sont dans une grille mais ne correspondent a aucune")
    print("  entree de legende. C'est ici que se voient les heuristiques a")
    print("  ajuster.")
    days = _day_words(page.words)
    unmatched: Counter[str] = Counter()
    unmatched_days: dict[str, list[str]] = {}

    for shape in candidates:
        x, y = _center(shape)
        region = next((r for r in regions if r.contains(x, y)), None)
        if region is None:
            continue
        proto = ShapePrototype.from_shape(shape)
        if _match_legend(proto, legend) is not None:
            continue

        key = (
            f"{proto.object_type:<6} {proto.width:5.1f}x{proto.height:<5.1f} "
            f"strk={str(proto.stroked)[0]} fill={str(proto.filled)[0]} "
            f"trait={proto.stroke_color:<14} fond={proto.fill_color}"
        )
        unmatched[key] += 1
        day = _enclosed_day(shape, days)
        if day is not None:
            unmatched_days.setdefault(key, []).append(
                f"{region.year}-{region.month:02d}-{day:02d}"
            )

    if not unmatched:
        print("\n  Aucune. Toutes les formes des grilles ont ete interpretees.")
    for key, count in unmatched.most_common():
        print(f"\n  {count:>4}x  {key}")
        sample = unmatched_days.get(key, [])[:8]
        if sample:
            print(f"        jours : {', '.join(sample)}")

rule("7. RESULTAT FUSIONNE")
# Meme regle que l'integration: la grille fait autorite lorsqu'elle produit des
# resultats, et les mentions textuelles non classees sont ecartees.
merged = merge_extraction_results(textual, grid_events)
print(f"  texte    : {len(textual)}")
print(f"  grille   : {len(grid_events)}")
print(f"  fusionne : {len(merged)}")
print()
for event in merged:
    span = (
        f"{event.first_day}"
        if event.first_day == event.last_day
        else f"{event.first_day} -> {event.last_day}"
    )
    print(f"    {span:<26} [{event.category.value:<16}] {event.summary}")
print()

by_category: Counter[str] = Counter(event.category.value for event in merged)
for category, count in by_category.most_common():
    print(f"    {category:<18} {count}")

rule("8. BORNES DE L'ANNEE SCOLAIRE")
starts = sorted(e.first_day for e in merged if e.category is EventCategory.TERM_START)
ends = sorted(e.last_day for e in merged if e.category is EventCategory.TERM_END)

print(f"  rentree         : {[d.isoformat() for d in starts] or 'AUCUNE'}")
print(f"  fin des classes : {[d.isoformat() for d in ends] or 'AUCUNE (bornee a la fin juin suivante)'}")

verdict = resolve_term_membership(date.today(), starts, ends)
print(f"\n  aujourd'hui ({date.today().isoformat()}) en periode scolaire : {verdict}")

if verdict is None:
    print("\n  ATTENTION : sans borne, le capteur 'Ecole ouverte' ne peut pas")
    print("  distinguer les vacances d'ete. Il repondra 'ouverte' tous les jours")
    print("  de semaine non marques.")

closed_today = [e for e in merged if e.closes_school and e.occurs_on(date.today())]
print(f"  evenement fermant l'ecole aujourd'hui : {len(closed_today)}")

shutil.rmtree(_workdir, ignore_errors=True)
