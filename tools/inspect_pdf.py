"""Inspection de la geometrie d'un calendrier scolaire en grille.

Vide les formes (rectangles, courbes, lignes), leurs couleurs et le numero de
jour qu'elles encadrent. Sert a concevoir les heuristiques de parsers/grid.py.

Usage:
    python3 inspect_pdf.py [chemin.pdf]
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_PDF = Path(__file__).resolve().parent / "cssp-2026-2027.pdf"

MONTHS = (
    "JANVIER",
    "FEVRIER",
    "FÉVRIER",
    "MARS",
    "AVRIL",
    "MAI",
    "JUIN",
    "JUILLET",
    "AOUT",
    "AOÛT",
    "SEPTEMBRE",
    "OCTOBRE",
    "NOVEMBRE",
    "DECEMBRE",
    "DÉCEMBRE",
)


def fmt_color(value: object) -> str:
    """Formate une couleur pdfplumber de maniere compacte."""
    if value is None:
        return "None"
    if isinstance(value, (int, float)):
        return f"{float(value):.3f}"
    if isinstance(value, (list, tuple)):
        return "(" + ",".join(f"{float(c):.3f}" for c in value) + ")"
    return str(value)


def center(obj: dict) -> tuple[float, float]:
    """Retourne le centre d'un objet pdfplumber."""
    return ((obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2)


def encloses(shape: dict, word: dict, tolerance: float = 1.5) -> bool:
    """Verifie si une forme encadre le centre d'un mot."""
    cx, cy = center(word)
    return (
        shape["x0"] - tolerance <= cx <= shape["x1"] + tolerance
        and shape["top"] - tolerance <= cy <= shape["bottom"] + tolerance
    )


def main() -> int:
    """Point d'entree."""
    try:
        import pdfplumber
    except ImportError:
        print("pdfplumber n'est pas installe.")
        print("  python3 -m pip install --user pdfplumber")
        return 1

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF

    if not path.is_file():
        print(f"Fichier introuvable : {path}")
        return 1

    with pdfplumber.open(path) as pdf:
        print(f"Fichier : {path.name}")
        print(f"Pages   : {len(pdf.pages)}")

        page = pdf.pages[0]
        print(f"Taille  : {page.width:.1f} x {page.height:.1f}")
        print()

        words = page.extract_words()
        numeric = [w for w in words if w["text"].strip().isdigit()]

        print("=" * 78)
        print("1. VUE D'ENSEMBLE")
        print("=" * 78)
        print(f"  mots           : {len(words)}")
        print(f"  mots numeriques: {len(numeric)}")
        print(f"  rects          : {len(page.rects)}")
        print(f"  curves         : {len(page.curves)}")
        print(f"  lines          : {len(page.lines)}")
        print()

        print("=" * 78)
        print("2. EN-TETES DE MOIS ET POSITIONS")
        print("=" * 78)
        for word in words:
            text = word["text"].strip().upper()
            if text in MONTHS:
                print(
                    f"  {text:<12} x0={word['x0']:7.1f} x1={word['x1']:7.1f} "
                    f"top={word['top']:7.1f}"
                )
        print()

        print("=" * 78)
        print("3. RECTANGLES")
        print("=" * 78)
        print(
            f"  {'#':>3} {'x0':>7} {'top':>7} {'larg':>6} {'haut':>6} "
            f"{'strk':>4} {'fill':>4} {'lw':>5}  {'jour':>5}  "
            f"stroking / non_stroking"
        )
        for index, rect in enumerate(page.rects):
            inside = [w["text"] for w in numeric if encloses(rect, w)]
            print(
                f"  {index:>3} {rect['x0']:>7.1f} {rect['top']:>7.1f} "
                f"{rect['width']:>6.1f} {rect['height']:>6.1f} "
                f"{str(rect['stroke'])[0]:>4} {str(rect['fill'])[0]:>4} "
                f"{rect.get('linewidth', 0):>5.2f}  "
                f"{(inside[0] if inside else '-'):>5}  "
                f"{fmt_color(rect.get('stroking_color'))} / "
                f"{fmt_color(rect.get('non_stroking_color'))}"
            )
        print()

        print("=" * 78)
        print("4. COURBES")
        print("=" * 78)
        print(
            f"  {'#':>3} {'x0':>7} {'top':>7} {'larg':>6} {'haut':>6} "
            f"{'pts':>4} {'strk':>4} {'fill':>4}  {'jour':>5}  "
            f"stroking / non_stroking"
        )
        for index, curve in enumerate(page.curves):
            inside = [w["text"] for w in numeric if encloses(curve, w)]
            print(
                f"  {index:>3} {curve['x0']:>7.1f} {curve['top']:>7.1f} "
                f"{curve['width']:>6.1f} {curve['height']:>6.1f} "
                f"{len(curve.get('points', [])):>4} "
                f"{str(curve['stroke'])[0]:>4} {str(curve['fill'])[0]:>4}  "
                f"{(inside[0] if inside else '-'):>5}  "
                f"{fmt_color(curve.get('stroking_color'))} / "
                f"{fmt_color(curve.get('non_stroking_color'))}"
            )
        print()

        print("=" * 78)
        print("5. REGROUPEMENT DES FORMES PAR GABARIT")
        print("=" * 78)
        print("  Revele les familles de formes: contours de jour, legende, cadres.")
        shapes = [("rect", r) for r in page.rects] + [
            ("curve", c) for c in page.curves
        ]
        families: Counter[tuple] = Counter()
        for kind, shape in shapes:
            families[
                (
                    kind,
                    round(shape["width"]),
                    round(shape["height"]),
                    len(shape.get("points", [])) if kind == "curve" else 0,
                    bool(shape["fill"]),
                    bool(shape["stroke"]),
                    fmt_color(shape.get("non_stroking_color")),
                )
            ] += 1

        for family, count in families.most_common():
            kind, width, height, points, fill, stroke, color = family
            print(
                f"  {count:>4}x {kind:<6} {width:>4}x{height:<4} pts={points:<3} "
                f"fill={str(fill):<5} stroke={str(stroke):<5} couleur={color}"
            )
        print()

        print("=" * 78)
        print("6. JOURS ENCADRES, PAR COLONNE ET LIGNE DE GRILLE")
        print("=" * 78)
        marked: dict[str, list[str]] = defaultdict(list)
        for kind, shape in shapes:
            inside = [w for w in numeric if encloses(shape, w)]
            if not inside:
                continue
            for word in inside:
                marked[
                    f"x={shape['x0']:.0f} y={shape['top']:.0f} {kind}"
                ].append(word["text"])

        print(f"  {len(marked)} forme(s) encadrent au moins un numero de jour")
        for key in sorted(marked, key=lambda k: (float(k.split("y=")[1].split()[0]))):
            print(f"    {key:<32} -> {marked[key]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
