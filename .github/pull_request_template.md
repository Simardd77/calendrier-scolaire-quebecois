<!--
Les commentaires de ce gabarit n'apparaissent pas dans la PR publiée. Supprimez
les sections qui ne s'appliquent pas, mais gardez l'ordre des autres.

BRANCHE CIBLE
  Visez `develop`. Une PR vers `main` ne peut venir que de `develop` : la CI la
  refuse autrement.

TITRE DE LA PR
  Même forme que les commits : préfixe anglais, description en français.
    feat: création d'événements depuis la vue des calendriers
  Le titre n'est pas repris dans le changelog (voir plus bas).

MESSAGES DE COMMIT
  Le changelog d'une release est généré à partir des messages de commit. Les
  fusions « Merge pull request #N » et « chore: bump version to X » en sont
  exclues. C'est donc CHAQUE commit de la PR qui apparaît dans le changelog, tel
  quel.

  Le préfixe, en anglais, classe le commit dans une section :

    feat:                                              🚀 Nouveautés
    fix:                                               🐛 Corrections
    docs:                                              📝 Documentation
    ci:                                                📦 Intégration continue
    chore: refactor: style: perf: test:                🧹 Maintenance
    (tout autre préfixe)                               📌 Autres

  La description, après le « : », s'écrit en français. Elle est publiée telle
  quelle.
    feat: ajout du support du calendrier de l'Altitude      oui
    feat: support Altitude calendar symbols                 non, en anglais

  N'écrivez pas d'emoji dans le message : les emoji ci-dessus sont ajoutés par
  la CI aux titres de section. La CI lit le début de la ligne pour classer le
  commit, et un emoji en tête l'enverrait dans « 📌 Autres ».

VERSION
  Ne modifiez pas `version` dans `manifest.json` : elle est incrémentée sur
  `develop` juste après la sortie d'une version stable, pas dans une PR de
  fonctionnalité.
-->

## Titre court de la PR

Ce que la PR apporte et pourquoi, en un ou deux paragraphes. Citez la PR ou
l'issue liée s'il y en a une.

## Ce que ça fait

- **Point 1 :** …
- **Point 2 :** …

## Conception

Les choix qui ne se lisent pas dans le diff : structure retenue, pièges
identifiés, ce qui a été écarté et pourquoi.

## Points à connaître

Ce que la personne qui relit ou qui met à jour doit savoir : changement de
comportement, automatisation ou abonnement qui peut être touché, limite connue,
ce qui n'a pas pu être vérifié (par exemple dans une vraie instance de Home
Assistant).

## Hors de cette PR

Ce qui est volontairement laissé de côté, et où il sera traité.

## Vérifications

<!-- Cochez ce qui a été exécuté en local, et indiquez le résultat. -->

- [ ] Les messages de commit suivent la convention (préfixe anglais, description française, sans emoji)
- [ ] `pytest tests/` : … tests passent
- [ ] `black --check custom_components/ tests/ tools/`
- [ ] `flake8 custom_components/ tests/ tools/ --count --select=E9,F63,F7,F82 --show-source --statistics`
- [ ] `python3 tools/verify_all.py` (structure, métadonnées, traductions)
- [ ] `python3 tools/validate_grid.py`, si l'analyse géométrique des PDF est touchée
- [ ] `strings.json`, `translations/fr.json` et `translations/en.json` à jour, si du texte d'interface change
- [ ] README à jour, si un comportement visible change

Les contrôles de la CI (flake8, black, tests, HACS, Hassfest) confirmeront sur le runner.
