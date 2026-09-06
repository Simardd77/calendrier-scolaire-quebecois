# Calendrier Scolaire Québécois pour Home Assistant

<p align="center">
  <img src="https://raw.githubusercontent.com/Simardd77/calendrier-scolaire-quebecois/HEAD/custom_components/calendrier_scolaire_quebecois/brand/icon.png" alt="Logo" />
</p>

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Dernière version stable](https://img.shields.io/github/v/release/Simardd77/calendrier-scolaire-quebecois.svg?style=for-the-badge&label=stable)](https://github.com/Simardd77/calendrier-scolaire-quebecois/releases/latest)
[![Dernière beta](https://img.shields.io/github/v/release/Simardd77/calendrier-scolaire-quebecois.svg?include_prereleases&filter=*-beta*&label=beta&color=orange&style=for-the-badge)](https://github.com/Simardd77/calendrier-scolaire-quebecois/releases)
[![Licence MIT](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge)](https://github.com/Simardd77/calendrier-scolaire-quebecois/blob/HEAD/LICENSE)

Intégration Home Assistant qui transforme un calendrier scolaire québécois
(PDF, page web ou fichier iCalendar) en une véritable entité calendrier,
accompagnée de capteurs prêts pour l'automatisation.

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Prérequis](#prérequis)
- [Compatibilité](#compatibilité)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entités](#entités)
- [Voir le calendrier sur un iPhone ou dans Google Agenda](#voir-le-calendrier-sur-un-iphone-ou-dans-google-agenda)
- [Services](#services)
- [Exemples d'automatisation](#exemples-dautomatisation)
- [Comment l'extraction fonctionne](#comment-lextraction-fonctionne)
- [OCR pour les PDF numérisés](#ocr-pour-les-pdf-numérisés)
- [Dépannage](#dépannage)
- [Limites connues](#limites-connues)
- [Développement](#développement)
- [Licence](#licence)
- [Support](#support)

## Fonctionnalités

- Entité calendrier native, visible dans le tableau de bord Calendrier et
  utilisable dans les automatisations
- Lecture des PDF texte, y compris le contenu des tableaux
- **Lecture des calendriers en grille**, le format des centres de services
  scolaires québécois, où le sens de chaque journée est encodé par une forme ou
  une couleur autour du chiffre
- Lecture des fichiers iCalendar
- Exploration d'une page d'établissement pour y trouver les documents de
  calendrier — **expérimental**, voir [Limites connues](#limites-connues)
- Année implicite déduite de l'année scolaire annoncée dans le document
- Classification automatique : congé, journée pédagogique, rentrée, fin des
  classes, examen, rencontre, événement
- Capteur « École ouverte » qui tient compte des fins de semaine, des congés,
  des journées pédagogiques **et des vacances d'été**, déduites du début et de
  la fin de l'année scolaire
- Fins de semaine retirées des congés : un congé annoncé « du 23 décembre au
  5 janvier » ne prétend pas que les samedis en font partie
- Refus d'une source qui n'est pas un calendrier scolaire, plutôt que de
  remplir le calendrier de fausses dates
- OCR facultatif pour les PDF numérisés
- **Publication du calendrier en flux iCalendar**, pour s'y abonner depuis
  l'application Calendrier d'un iPhone, Google Agenda ou Outlook

## Prérequis

- Home Assistant **2026.1.0** ou plus récent
- [HACS](https://hacs.xyz) pour l'installation recommandée

Les dépendances Python (`pdfplumber`, `icalendar`) sont installées
automatiquement par Home Assistant.

## Compatibilité

Il s'agit d'une **intégration**, pas d'un add-on : elle s'exécute dans le
processus Python de Home Assistant et fonctionne sur toutes les méthodes
d'installation.

| Fonctionnalité | HA OS | HA Container | HA Core |
|---|---|---|---|
| Entité calendrier, capteurs, services | oui | oui | oui |
| PDF avec couche texte | oui | oui | oui |
| Calendriers en grille (format des centres de services) | oui | oui | oui |
| Fichiers iCalendar | oui | oui | oui |
| Exploration d'un site d'établissement | expérimental | expérimental | expérimental |
| Publication du flux iCalendar | oui | oui | oui |
| OCR des PDF numérisés | non | non | oui, si binaires installés |

L'OCR est la seule fonctionnalité indisponible sur Home Assistant OS et
Container, et elle ne concerne qu'un cas précis : un PDF qui est une image, sans
aucune couche texte. Tout le reste, y compris l'analyse des calendriers en
grille, fonctionne partout.

L'analyse en grille ne lit pas des pixels : elle exploite les objets vectoriels
du PDF, leurs coordonnées et leurs couleurs, extraits directement de la
structure du fichier. Elle n'a donc jamais besoin d'OCR.

## Installation

### Via HACS

[![Ouvrir dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Simardd77&category=integration&repository=calendrier-scolaire-quebecois)

Redémarrez Home Assistant après l'installation.

### Installation manuelle

1. Copiez `custom_components/calendrier_scolaire_quebecois` dans le dossier
   `custom_components` de votre configuration Home Assistant
2. Redémarrez Home Assistant

## Configuration

L'intégration se configure entièrement par l'interface. La configuration par
`configuration.yaml` n'est pas prise en charge.

1. Paramètres → Appareils et services → Ajouter une intégration
2. Cherchez « Calendrier Scolaire Québécois »
3. Renseignez :
   - **Nom du calendrier** : nom de l'appareil et de l'entité calendrier
   - **URL de la source** : facultative, à remplir plus tard si besoin
   - **Type de source** : document direct, site d'établissement, ou iCalendar
   - **Intervalle de rafraîchissement** : en **secondes**, `21600` par défaut,
     soit 6 heures. Valeurs acceptées : de 300 secondes à 7 jours
   - **Activer l'OCR** : désactivé par défaut, voir la section OCR

### Gérer les sources après l'installation

**Configurer** sur la carte de l'intégration ouvre un menu à quatre entrées :

| Entrée | Rôle |
|---|---|
| **Modifier les réglages** | Intervalle de rafraîchissement et OCR |
| **Ajouter une source** | Même formulaire que l'installation, équivalent du service `add_source` |
| **Retirer des sources** | Sélection dans la liste des sources configurées, sans avoir à connaître leur identifiant |
| **Publier vers un agenda externe** | Adresse du flux iCalendar et renouvellement du secret |

Passer par **Retirer des sources** est la voie la plus simple pour en supprimer
une. Le service `remove_source` sert surtout depuis une automatisation.

### Ajouter une source, ou ajouter un service ?

Deux opérations voisines dans l'interface n'agissent pas au même niveau.

**Ajouter une source** ajoute un calendrier de plus dans le calendrier existant.
Les événements de toutes les sources sont fusionnés et dédoublonnés dans la même
entité `calendar`, et aucune entité n'est créée. L'intervalle de
rafraîchissement, le réglage OCR et l'adresse du flux iCalendar restent
partagés. (Exemple, calendrier de l'année suivante)

**Ajouter un service** crée une seconde entrée de configuration : un nouvel
appareil, un jeu complet de huit entités préfixées par le nouveau nom, des
réglages indépendants et une seconde adresse de flux. Les deux calendriers
restent étanches. (Exemple, calendrier d'un 2e enfant)

Le critère de décision tient en une question : voulez-vous un capteur
`École ouverte` de plus ?

Une source de plus convient quand plusieurs calendriers décrivent la même réalité
scolaire.

| Situation | Ce que la fusion apporte |
|---|---|
| Le calendrier du centre de services et celui propre à l'école | Les journées pédagogiques locales complètent le calendrier officiel, sans qu'un second capteur soit à surveiller |
| L'année en cours et la suivante, publiée au printemps | La bascule de juin à août se fait sans intervention |
| Le PDF officiel et un `.ics` d'activités parascolaires | Les sorties et les rencontres rejoignent les congés dans le même agenda |

Un service de plus s'impose dès que les établissements sont distincts, deux
enfants inscrits dans deux centres de services par exemple. Les réunir comme
deux sources d'un même calendrier rendrait `École ouverte` faux pour les deux :
une journée pédagogique chez l'un fermerait l'école de l'autre. Le capteur ne
distingue pas la provenance des fermetures ; seul l'attribut `source` de chaque
événement le fait.

- **Une même URL n'est acceptée qu'une fois par calendrier**, sous peine du
  message « Cette source est déjà configurée ». Elle ne peut pas non plus servir
  à créer deux entrées.

### Une source doit être un vrai calendrier

L'URL saisie n'est pas seulement testée pour sa joignabilité : le document est
téléchargé et analysé avant d'être accepté. S'il ne contient aucun congé,
journée pédagogique, semaine de relâche ni rentrée, il est refusé avec le
message « Ce document ne semble pas être un calendrier scolaire ».

La raison est qu'un document quelconque contient presque toujours des dates. Un
règlement, un procès-verbal ou un rapport annuel produiraient des dizaines de
faux événements. Seul un calendrier scolaire emploie le vocabulaire du domaine,
ce qui permet de faire la différence.

Si votre document est bien un calendrier mais qu'il est refusé, deux causes
probables : c'est un PDF numérisé sans couche texte, et il faut activer l'OCR ;
ou l'URL pointe sur une page d'accueil, et il faut choisir le type **site
d'établissement** pour que les documents y soient cherchés.

Cette vérification s'applique aux trois points d'entrée : le formulaire initial,
l'ajout depuis les options, et le service `add_source`. Elle porte uniquement
sur l'ajout : une source déjà configurée n'est jamais revérifiée, et continue
donc d'être téléchargée à chaque cycle même si son contenu a cessé d'être un
calendrier. C'est l'attribut `errors` du capteur d'état qui le signale.

### Types de source

| Type | Usage |
|---|---|
| `direct_url` | L'URL pointe directement sur un PDF ou un `.ics` |
| `school_website` | L'URL est une page web ; les liens vers les PDF et `.ics` y sont cherchés automatiquement. **Expérimental** |
| `ical` | L'URL pointe sur un flux iCalendar |

Le type réel du document est de toute façon déterminé à partir de son contenu,
pas de son extension : une URL sans extension fonctionne.

> **`school_website` est en cours de mise au point.** Le résultat dépend
> beaucoup de la façon dont l'établissement construit sa page, et les essais en
> cours montrent que la découverte échoue ou reste incomplète sur une partie des
> sites. Pour une configuration dont vous dépendez, préférez `direct_url` sur
> l'adresse du PDF : c'est le chemin éprouvé. Si la recherche ne trouve rien
> l'adresse du document est visible dans les journaux en mode `debug`
> et [une issue](https://github.com/Simardd77/calendrier-scolaire-quebecois/issues)
> avec l'URL de la page aide à corriger le tir.

## Entités

Chaque entrée crée un appareil regroupant les entités suivantes.
`<nom_calendrier>` est le **Nom du calendrier** saisi à la configuration, mis en
minuscules et sans accents : « Centre de Service Scolaire des Patriotes » donne
`centre_de_service_scolaire_des_patriotes`.

### Calendrier

- `calendar.<nom_calendrier>` — tous les événements, toutes sources confondues

Cette entité est créée dès l'installation, même sans source configurée et même
si le premier téléchargement échoue. Elle reste disponible lors d'une coupure
réseau, les événements déjà connus étant conservés.

### Capteurs

| Entité | Description |
|---|---|
| `sensor.<nom_calendrier>_total_d_evenements` | Nombre d'événements chargés |
| `sensor.<nom_calendrier>_prochain_evenement` | Titre de l'événement en cours ou à venir |
| `sensor.<nom_calendrier>_evenements_des_7_prochains_jours` | Nombre d'événements sur 7 jours |
| `sensor.<nom_calendrier>_etat` | `ready`, `no_sources`, `no_events` ou `error` |

Le capteur d'état expose dans ses attributs la liste des sources, leurs
identifiants et les erreurs rencontrées. C'est là qu'on lit le `source_id`
attendu par le service `remove_source`, dans la clé `id` de chaque source.

Les identifiants d'entités ci-dessus sont ceux de la traduction française, dont
ils sont dérivés. Vérifiez-les dans **Outils de développement → États** si votre
interface est dans une autre langue.

#### Attributs du prochain événement

Les plus utiles en automatisation :

```yaml
start: "2026-08-25"        # première journée couverte
end: "2026-08-29"          # journée de fin exclusive, comme dans iCalendar
first_day: "2026-08-25"    # journées inclusives, plus pratiques en template
last_day: "2026-08-28"     # ici, end moins un jour
all_day: true
category: pedagogical_day
closes_school: true
source: "CSS des Patriotes"
```

Distinction à faire: `end` est **exclusif**, comme dans le format
iCalendar, alors que `last_day` est la dernière journée réellement couverte. En
template, préférez `first_day` et `last_day`, qui évitent les erreurs de un
jour.

`closes_school` évite d'avoir à connaître la liste des catégories : il est vrai
pour un congé comme pour une journée pédagogique.

Valeurs possibles de `category` :

| Valeur | Signification | Ferme l'école |
|---|---|---|
| `holiday` | Congé, vacances, semaine de relâche, jour férié | oui |
| `pedagogical_day` | Journée pédagogique | oui |
| `term_start` | Rentrée scolaire | non |
| `term_end` | Fin des classes | non |
| `exam` | Examen, épreuve, évaluation | non |
| `meeting` | Rencontre de parents, bulletin, assemblée | non |
| `event` | Autre événement scolaire | non |

### Capteurs binaires

| Entité | Description |
|---|---|
| `binary_sensor.<nom_calendrier>_ecole_ouverte` | Faux la fin de semaine, hors de l'année scolaire, pendant les congés et les journées pédagogiques |
| `binary_sensor.<nom_calendrier>_evenement_aujourd_hui` | Vrai si un événement couvre aujourd'hui |
| `binary_sensor.<nom_calendrier>_conge_aujourd_hui` | Vrai pendant un congé ou des vacances |

### Attributs des autres entités

Les attributs du prochain événement sont documentés plus haut. Voici ceux des
autres capteurs et capteurs binaires. Tous se consultent dans **Outils de
développement → États**, en sélectionnant l'entité.

| Entité | Attribut | Contenu |
|---|---|---|
| `Événements des 7 prochains jours` | `horizon_days` | Toujours `7` |
| | `events` | Liste de `summary`, `first_day`, `last_day`, `category` |
| `État` | `sources_total` | Nombre de sources configurées |
| | `sources_ok` | Sources traitées sans erreur |
| | `events_count` | Nombre d'événements chargés |
| | `errors` | Message d'erreur par nom de source |
| | `ocr_enabled` | Reflet du réglage OCR |
| | `sources` | Liste de `id`, `name`, `url`, `type` — la clé `id` est le `source_id` attendu par `remove_source` |
| `École ouverte` | `term_start`, `term_end` | Début et fin de l'année scolaire en cours, déduits du document, `null` s'il ne les annonce pas. Plusieurs années chargées ne donnent pas leur enveloppe |
| | `reason` | `weekend`, `outside_term`, `holiday`, `pedagogical_day`, ou `null` si l'école est ouverte |
| | `summary` | Titre du congé en cours, `null` sinon |
| `Événement aujourd'hui` | `count` | Nombre d'événements du jour |
| | `summaries` | Leurs titres |
| `Congé aujourd'hui` | `summary` | Titre du congé en cours, `null` sinon |
| | `last_day` | Dernière journée du congé, pratique pour un décompte. **Présent seulement pendant un congé** |

### Fins de semaine retirées des congés

Un calendrier annonce un congé par ses dates, « du 23 décembre au 5 janvier »,
sans mentionner les fins de semaine qu'il traverse : l'absence de classe y est
déjà acquise. Publier la plage telle quelle laisserait croire qu'un samedi est
un congé scolaire.

Les fermetures sont donc découpées en segments ne couvrant que des jours de
semaine. Le congé des fêtes 2026-2027 devient :

| Segment | Du | Au |
|---|---|---|
| 1 | mercredi 23 décembre 2026 | vendredi 25 décembre 2026 |
| 2 | lundi 28 décembre 2026 | vendredi 1er janvier 2027 |
| 3 | lundi 4 janvier 2027 | mardi 5 janvier 2027 |

Ce découpage ne s'applique qu'aux **fermetures** — congés et journées
pédagogiques. Une activité annoncée un samedi, un carnaval par exemple, est un
événement réel et reste intacte, de même que les événements horodatés comme une
rencontre de parents.

Conséquence à connaître : une fermeture tombant entièrement en fin de semaine
disparaît, puisqu'elle ne décrit aucune journée de classe. C'est le cas d'une
fête nationale un samedi.

### Vacances d'été et période scolaire

Un calendrier scolaire ne marque pas les vacances d'été : juillet et août ne
portent aucune indication, l'absence de classe étant sous-entendue par le
document. Un capteur qui ne lirait que les marqueurs répondrait donc « école
ouverte » tout l'été.

L'intégration déduit la période scolaire des journées de **rentrée** et de **fin
des classes** annoncées par le calendrier pdf, et considère l'école fermée en dehors.

## Voir le calendrier sur un iPhone ou dans Google Agenda

Home Assistant n'expose pas ses entités calendrier sous une forme qu'une
application d'agenda sait lire. L'intégration publie donc elle-même un **flux
iCalendar** auquel n'importe quel client peut s'abonner.

Rien n'est à activer : un secret est attribué à votre calendrier dès sa
création, ce qui rend le flux disponible immédiatement. Il ne reste qu'à en
relever l'adresse.

### Récupérer l'adresse du fluxenda externe**

L'écran affiche l'adresse complète, de la forme :

```
http://homeassistant.local/api/calendrier_scolaire_quebecois/ics/<id>/<secret>.ics
https://homeassistant/api/calendrier_scolaire_quebecois/ics/<id>/<secret>.ics
```

Copiez-la. Elle reste valable indéfiniment : une mise à jour de l'intégration,
un redémarrage de Home Assistant ou un changement de réglages ne la modifient
pas.

### S'abonner depuis un iPhone ou un iPad

1. Réglages → **Apps** → Calendrier → Comptes
   *(sur iOS 17 et antérieur : Réglages → Calendrier → Comptes)*
2. Ajouter un compte → **Autre**
3. **Ajouter un calendrier avec abonnement**
4. Coller l'adresse

Pour que l'abonnement se retrouve sur tous vos appareils Apple au lieu de rester
sur ce seul téléphone, ajoutez-le plutôt depuis l'application Calendrier sur
macOS, en choisissant l'emplacement **iCloud**.

### S'abonner depuis Google Agenda ou Outlook

Dans Google Agenda : **Autres agendas** → **+** → **À partir de l'URL**. Dans
Outlook : **Ajouter un calendrier** → **S'abonner à partir du web**.

### Trois points à anticiper

**L'adresse doit être joignable depuis l'appareil.** Avec une adresse locale,
la synchronisation ne fonctionnera qu'à la maison. Pour qu'elle suive partout,
Home Assistant doit avoir une URL externe configurée dans Paramètres → Système →
Réseau : Nabu Casa Cloud, ou un reverse proxy en HTTPS.

**Cette adresse tient lieu de mot de passe.** Le point d'accès n'est pas
authentifié, et il ne peut pas l'être : une application d'agenda ne sait pas
présenter un jeton Home Assistant. Quiconque possède l'adresse peut consulter le
calendrier. L'accès est en lecture seule, et il s'agit d'un calendrier scolaire,
donc l'enjeu reste modeste — mais traitez-la comme un secret. Si vous l'avez
partagée par erreur, cochez **Renouveler le secret** sur ce même écran : les
abonnements existants cessent aussitôt de fonctionner, et il faut recréer
l'abonnement avec la nouvelle adresse.

### Ce que contient le flux

Les congés sont publiés comme événements de **journée entière**, ce qui les
affiche en bandeau en haut de la journée plutôt que sur une plage horaire. Ils
sont marqués `TRANSP:TRANSPARENT`, donc ils ne vous font pas apparaître comme
occupé. Chaque événement porte sa catégorie dans `CATEGORIES`, ce qui permet un
filtrage côté client.

### Qu'est-ce qui ferait changer l'adresse

| Action | Effet |
|---|---|
| Mettre à jour l'intégration | aucun, l'adresse est conservée |
| Redémarrer Home Assistant | aucun |
| Renouveler le secret | l'adresse change, l'abonnement doit être recréé |
| Supprimer puis réajouter l'intégration | l'adresse change entièrement |
| Changer l'URL externe de Home Assistant | seule la première partie change, mais l'abonnement casse |

Dans les trois derniers cas, il faut supprimer l'abonnement sur l'appareil et le
recréer : iOS comme Google Agenda ne suivent pas un changement d'adresse.

## Services

### `add_source`

```yaml
action: calendrier_scolaire_quebecois.add_source
data:
  name: Calendrier 2026-2027
  source_url: https://exemple.qc.ca/calendrier.pdf
  source_type: direct_url
```

### `remove_source`

```yaml
action: calendrier_scolaire_quebecois.remove_source
data:
  source_id: 6b1f2c8a9d04
```

L'URL complète est également acceptée à la place de l'identifiant.

### `refresh_calendar`

```yaml
action: calendrier_scolaire_quebecois.refresh_calendar
```

### `parse_pdf`

Analyse un PDF local et **retourne** les événements détectés sans les ajouter au
calendrier. Pratique pour valider un document avant de l'ajouter comme source.

```yaml
action: calendrier_scolaire_quebecois.parse_pdf
data:
  file_path: /config/calendriers/calendrier-2026-2027.pdf
response_variable: resultat
```

Le répertoire doit figurer dans `allowlist_external_dirs` :

```yaml
homeassistant:
  allowlist_external_dirs:
    - /config/calendriers
```

Lorsque plusieurs calendriers sont configurés, ajoutez `config_entry_id` pour
désigner celui visé. Les services `add_source`, `remove_source` et `parse_pdf`
retournent sinon une erreur explicite.

## Exemples d'automatisation

Réveil seulement les jours d'école :

```yaml
automation:
  - alias: Réveil les jours d'école
    triggers:
      - trigger: time
        at: "06:45:00"
    conditions:
      - condition: state
        entity_id: binary_sensor.calendrier_scolaire_ecole_ouverte
        state: "on"
    actions:
      - action: light.turn_on
        target:
          entity_id: light.chambre
```

Avis la veille d'une journée pédagogique :

```yaml
automation:
  - alias: Avis journée pédagogique
    triggers:
      - trigger: calendar
        entity_id: calendar.calendrier_scolaire
        event: start
        offset: "-12:00:00"
    conditions:
      - condition: template
        value_template: >
          {{ 'pédagogique' in trigger.calendar_event.summary | lower }}
    actions:
      - action: notify.persistent_notification
        data:
          message: >
            Demain : {{ trigger.calendar_event.summary }}
```

## Comment l'extraction fonctionne

Deux stratégies sont appliquées à chaque PDF, puis leurs résultats sont
fusionnés et dédoublonnés. Un document n'a donc pas besoin de correspondre à un
seul format.

Lorsque l'analyse en grille produit des événements, elle fait autorité : les
mentions textuelles non classées sont écartées. Les calendriers en grille sont
accompagnés de notes en prose dont les dates, noyées dans des phrases, donnent
des titres tronqués. Les mentions **typées** du texte sont conservées, par
exemple une date de rentrée annoncée hors de la grille.

### Analyse textuelle

Le texte est analysé ligne par ligne. Une ligne devient un événement quand elle
contient une date **et** qu'elle est reconnue par un mot-clé (« vacances »,
« pédagogique », « examen », « rencontre de parents », etc.) ou qu'elle est
suivie d'un libellé plausible.

### Analyse géométrique des calendriers en grille

Les centres de services scolaires publient douze grilles mensuelles où la
couche texte ne contient que des chiffres nus. L'information « le 23 décembre
est un congé » n'existe nulle part dans le texte : elle est portée par un
cercle, un carré, un losange ou un fond de couleur autour du chiffre. Aucun
analyseur textuel ne peut réussir sur ces documents.

L'intégration exploite donc la géométrie du PDF, en s'appuyant sur un principe
simple : **le document porte sa propre légende**. Les formes situées hors des
grilles sont relevées avec le texte qui les accompagne, ce qui produit une table
de correspondance propre au document. Chaque forme des grilles est ensuite
rattachée à la forme de légende la plus proche.

Cette analyse lit les objets vectoriels du PDF, pas des pixels : elle ne requiert
aucun OCR et fonctionne donc sur Home Assistant OS comme ailleurs.

Aucune dimension n'est codée en dur, ce qui permet de traiter les variations
d'un établissement à l'autre. La signature d'une forme comprend son type, ses
dimensions, la présence d'un contour, la présence d'un remplissage, les couleurs
des deux, et le centroïde de ses sommets : un établissement qui surligne ses
congés avec un fond de couleur plutôt qu'un contour est donc pris en charge de la
même manière.

Le centroïde est ce qui distingue deux formes de même encombrement. Un triangle
pointant vers le haut et un triangle pointant vers le bas partagent exactement la
même boîte englobante, mais leurs sommets se concentrent de part et d'autre, avec
des centroïdes séparés de 0,5. Sans lui, un calendrier utilisant les deux
orientations verrait ses libellés interchangés — et le cas est réel : dans le
calendrier du CSSDM, le triangle dessiné dans la légende ne fait pas la même
taille que celui utilisé dans les grilles, si bien que les dimensions seules
menaient au mauvais rapprochement.

Les grilles elles-mêmes sont validées : un nom de mois cité dans une note de bas
de page ressemble à un en-tête, mais ne surplombe aucune grille. Un candidat
n'est retenu que s'il couvre une vingtaine de numéros de jour, puis la
disposition est recalculée sur les seules grilles réelles. Sans ce filtre, les
faux en-têtes rétrécissent la largeur de colonne déduite et la dernière colonne
de chaque grille passe inaperçue.

C'est aussi ce qui évite les faux positifs. La teinte grise des colonnes de fin
de semaine est un aplat sans contour, incompatible avec une entrée de légende
dessinée au trait, donc jamais interprétée comme un événement. Par sécurité,
une signature qui marquerait plus de 60 journées est écartée comme ombrage
structurel.

Les journées consécutives de même signification sont regroupées, en enjambant
les fins de semaine. Le congé des fêtes, du 23 décembre 2026 au 5 janvier 2027,
forme ainsi une seule plage plutôt que dix journées séparées, et le congé de
Pâques, le vendredi 26 mars et le lundi 29 mars 2027, forme un bloc de quatre
jours.

Ce regroupement reste interne à l'analyse. Les fermetures obtenues sont ensuite
redécoupées pour écarter les fins de semaine, comme décrit dans
[Fins de semaine retirées des congés](#fins-de-semaine-retirées-des-congés) : la
plage du congé des fêtes ressort en trois segments, et le bloc de Pâques en deux
journées isolées.

Validé sur deux calendriers 2026-2027 de formats différents, en utilisant à
chaque fois les compteurs imprimés dans le document comme contrôle indépendant.

**Centre de services scolaire des Patriotes** — grille de sept jours, marqueurs
au trait : 22 événements extraits. Le regroupement des journées consécutives
explique l'écart avec les compteurs de la légende : ces 22 événements couvrent
44 journées de semaine marquées, dont 42 fermetures — soit exactement les
22 congés, 16 journées pédagogiques et 4 journées pour force majeure annoncés
par le document — plus la rentrée et la fin des classes. Les journées de la
relâche, du congé des fêtes, de Pâques et de la Saint-Jean sont exactes.

**Centre de services scolaire de Montréal** — grille de cinq jours, deux
orientations de triangle, cercle barré, rectangle rouge, et notes en prose :
19 événements, soit les 18 de la grille plus la rentrée du 27 août, typée depuis
une note en prose et non depuis la grille. Les journées pédagogiques marquées
correspondent exactement aux 8 fixées par le centre de services que le document
annonce, dont les deux institutionnelles nommées.

Les dates sans année sont rattachées à l'année scolaire annoncée dans le
document (« 2026-2027 »). À défaut, l'année scolaire courante est utilisée :
août à décembre pour la première année civile, janvier à juillet pour la
seconde.

Formats reconnus :

| Exemple | Résultat |
|---|---|
| `3 septembre 2026` | 3 septembre 2026 |
| `4 octobre` | année déduite |
| `1er juillet` | 1 juillet |
| `12 sept.` | abréviations acceptées |
| `du 23 décembre au 5 janvier` | plage traversant le 31 décembre |
| `du 3 au 7 mars` | plage dans un même mois |
| `1-5 mars 2027` | plage avec tiret |
| `15/01/2027`, `2026-09-03` | formats numériques |

## OCR pour les PDF numérisés

**Vous n'en avez probablement pas besoin.** L'OCR ne sert qu'à un cas précis :
un PDF qui est une image, sans aucune couche texte, typiquement un calendrier
photographié ou passé au numériseur. Les calendriers publiés par les centres de
services scolaires, y compris ceux en grille, contiennent du texte et des objets
vectoriels : ils sont traités sans OCR.

Un indice fiable : si vous pouvez sélectionner du texte dans le PDF avec votre
lecteur habituel, l'OCR est inutile.

L'OCR est donc **désactivé par défaut**, d'autant qu'il exige des binaires
système absents de Home Assistant OS et Home Assistant Container : `tesseract`
(avec le paquet de langue française) et `poppler`. Sur ces installations,
l'activer ne produira rien.

Sur une installation Core dans un environnement que vous maîtrisez :

```bash
# Debian / Ubuntu
sudo apt-get install tesseract-ocr tesseract-ocr-fra poppler-utils
pip install pytesseract pdf2image pillow
```

Activez ensuite l'OCR dans **Configurer → Modifier les réglages**.

Si un PDF ne produit aucun événement et que l'OCR est désactivé, le journal
signale explicitement que le document est probablement numérisé.

## Dépannage

Activez les journaux détaillés :

```yaml
logger:
  logs:
    custom_components.calendrier_scolaire_quebecois: debug
```

| Symptôme | Piste |
|---|---|
| Le calendrier est vide | Vérifiez l'attribut `errors` du capteur d'état, puis validez le document avec `parse_pdf` |
| `no_sources` | Aucune source n'est configurée : ajoutez-en une dans les options |
| `error` | Toutes les sources ont échoué ; l'attribut `errors` donne le message par source |
| Du texte est extrait mais aucun événement | Un avertissement le signale explicitement dans le journal. Le document n'utilise ni mots-clés reconnus ni grille avec légende |
| Aucun texte extrait | Le PDF est une image : voir la section OCR |
| Dates décalées | Le document utilise peut-être `mm/jj/aaaa` ; l'ordre `jj/mm/aaaa` est essayé en premier |
| « Ce document ne semble pas être un calendrier scolaire » | Le document ne contient aucun marqueur reconnu. S'il est numérisé, activez l'OCR ; si l'URL est une page d'accueil, choisissez le type site d'établissement |
| « L'URL fournie est inaccessible » | Le serveur ne répond pas dans le délai imparti, ou refuse la requête |

### Le flux iCalendar ne fonctionne pas

Ouvrez l'adresse du flux dans un navigateur : le code renvoyé indique la cause.

| Réponse | Cause |
|---|---|
| Le fichier se télécharge | Le flux fonctionne ; le problème est côté client, voir la cadence de rafraîchissement |
| `401 Unauthorized` | Le secret de l'adresse ne correspond plus : il a été renouvelé, recopiez l'adresse depuis les options |
| `403 Forbidden` | Aucun secret dans l'adresse, ou adresse tronquée à la copie |
| `404 Not Found` | L'identifiant d'entrée n'existe plus : l'intégration a été supprimée puis réajoutée |
| `503 Service Unavailable` | L'intégration est en cours de chargement, réessayez dans quelques secondes |
| Rien, délai dépassé | L'adresse n'est pas joignable depuis l'extérieur : vérifiez l'URL externe dans Paramètres → Système → Réseau |

## Limites connues

- L'exploration d'une page d'établissement, le type de source `school_website`,
  est **expérimentale**. La détection repose sur les liens `href` dont le chemin
  se termine par `.pdf`, `.ics`, `.ical` ou `.ifb` : un document servi par un
  script, derrière une redirection, sur une visionneuse, ou par une URL sans
  extension passe inaperçu. Les pages construites en JavaScript ne sont pas
  interprétées, seul le HTML renvoyé par le serveur est lu. Le type `direct_url`
  reste la voie fiable.
- Les règles de récurrence iCalendar (`RRULE`) ne sont pas développées : seule
  la première occurrence est retenue, et un avertissement est journalisé.
- L'analyse en grille exige que le document imprime sa légende. Sans légende
  exploitable, aucune signification ne peut être attribuée aux formes et
  l'analyse retourne une liste vide.
- Deux formes de même type, mêmes dimensions, mêmes couleurs **et** même
  centroïde resteraient indiscernables. En pratique les dimensions suffisent
  alors à les départager, mais la marge peut être mince.
- Un calendrier en grille dont les formes ne sont pas des objets vectoriels,
  parce qu'il s'agit d'une image, nécessiterait de la reconnaissance de formes
  que l'OCR ne fournit pas.
- Le calendrier est en lecture seule : la création d'événements depuis Home
  Assistant n'est pas prise en charge, puisque chaque rafraîchissement
  reconstruit les événements à partir des sources.
- Le flux iCalendar publié n'est pas authentifié par un jeton, l'autorisation
  reposant sur un secret contenu dans l'adresse. C'est une contrainte des
  applications d'agenda, qui ne savent pas s'authentifier auprès de Home
  Assistant.
- Une fermeture tombant entièrement en fin de semaine n'apparaît pas, le
  découpage des fins de semaine ne lui laissant aucune journée de classe.

## Développement

### Architecture

```
Source configurée (PDF, iCalendar, page d'établissement)
        │
        ▼
fetcher.py          téléchargement plafonné en taille, décodage, liens
        │
        ▼
parsers/            pdf · ical · ocr → dates → events → grid
        │           aucune dépendance à Home Assistant
        ▼
models.py           SchoolEvent, catégories, déduplication,
        │           retrait des fins de semaine, is_calendar_like
        ▼
coordinator.py      cycle de rafraîchissement, CalendarData
        │
        ├──► calendar.py · sensor.py · binary_sensor.py   entités
        └──► http.py + ics.py                             flux iCalendar
```

| Module | Rôle | Dépend de HA |
|---|---|---|
| `models.py` | Modèle d'événement et règles métier | non |
| `parsers/` | Extraction depuis PDF, iCalendar, HTML | non |
| `ics.py` | Sérialisation RFC 5545 du flux publié | non |
| `fetcher.py` | Téléchargement et découverte de documents | non |
| `coordinator.py` | Orchestration des cycles de mise à jour | oui |
| `config_flow.py` | Configuration et options | oui |
| `http.py` | Point d'accès servant le flux | oui |
| `entity.py` | Classe de base des entités : appareil, disponibilité, accès au coordinateur | oui |
| `calendar.py`, `sensor.py`, `binary_sensor.py` | Entités | oui |

### Tests

```bash
pip install -r requirements.txt
pytest tests/
```

Pour exercer la logique pure sans rien installer, `tools/verify_all.py`
contourne le paquet : il copie `models.py` et `parsers/` dans un paquet
temporaire au `__init__.py` vide, puis l'importe depuis `sys.path`. Les
dépendances lourdes restent hors du chemin, `pdf.py` n'important `pdfplumber`
qu'au moment de l'appel.

### Ajouter un mot-clé ou une catégorie

Les mots-clés de classification sont regroupés dans `parsers/events.py`, et les
catégories dans `models.py`. Un mot-clé manquant s'ajoute au tuple de sa
catégorie, avec un test dans `tests/test_events.py`.

Le dossier `tools/` contient les outils de mise au point. Rien n'y est livré à
l'utilisateur : HACS n'installe que `custom_components/`.

| Script | Rôle |
|---|---|
| `verify_all.py` | Vérifie la structure, les métadonnées, les traductions et les régressions des analyseurs. Ne requiert pas Home Assistant, ni même `pdfplumber` |
| `validate_grid.py` | Test de non-régression de l'analyse géométrique. Ses attentes sont **codées en dur pour le calendrier 2026-2027 du CSS des Patriotes** : le lancer sur un autre document signale des échecs qui ne sont pas des défauts de l'analyseur |
| `analyze_pdf.py` | Diagnostic sur un calendrier **quelconque**. N'impose aucune attente : rapporte ce qui est extrait et ce qui n'a pas pu être interprété. C'est le script à utiliser pour un nouveau document |
| `inspect_pdf.py` | Vide la géométrie complète d'un PDF : formes, couleurs, jour encadré |
| `inspect2.py` | Vide les seuls marqueurs et la légende, pour concevoir de nouvelles heuristiques |

```bash
python3 tools/verify_all.py                               # aucune dépendance
python3 tools/analyze_pdf.py chemin/vers/calendrier.pdf   # nouveau document
python3 tools/validate_grid.py                            # non-régression, CSS des Patriotes
```

Tous les scripts sauf `verify_all.py` requièrent `pdfplumber` :
`pip install pdfplumber` suffit, Home Assistant n'est pas nécessaire.

Deux calendriers 2026-2027 sont fournis dans ce dossier, ceux du CSS des
Patriotes et du CSS de Montréal, pour faire tourner les outils sans rien
télécharger. Ils appartiennent à leur centre de services scolaire respectif.
N'importe quel autre calendrier PDF fonctionne : passez son chemin en argument.

## Support

Ouvrir une [Issues](https://github.com/Simardd77/calendrier-scolaire-quebecois/issues) pour:
- Un établissement qui s'intègre pas ou contient des erreurs une fois le calendrier créé
- Mots-clés manquants
- Catégories manquantes

Sinon, voir si le sujet n'a pas déjà été couvert.
- [Discussions](https://github.com/Simardd77/calendrier-scolaire-quebecois/discussions)

## Licence

MIT — voir [LICENSE](https://github.com/Simardd77/calendrier-scolaire-quebecois/blob/HEAD/LICENSE).