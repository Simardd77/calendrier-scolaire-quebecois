"""Analyseurs de calendrier scolaire.

Ce paquet ne depend pas de Home Assistant. Chaque module est utilisable et
testable isolement, ce qui permet de valider l'extraction sans demarrer une
instance Home Assistant.
"""

from __future__ import annotations


class ParserError(Exception):
    """Erreur generique d'analyse."""


class DependencyMissingError(ParserError):
    """Une dependance optionnelle requise est absente de l'environnement."""

    def __init__(self, package: str, feature: str) -> None:
        """Initialise l'erreur.

        Args:
            package: Nom du paquet Python manquant.
            feature: Fonctionnalite indisponible sans ce paquet.
        """
        self.package = package
        self.feature = feature
        super().__init__(
            f"Le paquet '{package}' est requis pour {feature} mais n'est pas installe"
        )


__all__ = ["DependencyMissingError", "ParserError"]
