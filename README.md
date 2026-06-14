# NERV EPUB Manager

Script Python pour **copier**, **aplatir** et **compresser agressivement** vos fichiers EPUB.

## Fonctionnalités

- **Copie + aplatissement** — Tous les EPUBs sont copiés directement à la racine du dossier destination, renommés automatiquement en `Auteur - Titre.epub` (lu depuis les métadonnées internes)
- **Compression agressive** — Réduit les images à ~10 % de leur taille originale (90 % de gain) via recherche dichotomique de la qualité JPEG optimale
- **Conversion PNG → JPEG** — Optionnelle, avec gestion de la transparence (fond blanc)
- **Top 10** — Statistiques finales avec les 10 meilleurs gains de compression
- **Suppression automatique de la corbeille** — Supprime `.caltrash` (corbeille Calibre) au lancement
- **Mode dry-run** — Simulation complète sans modification de fichiers
- **Thèmes UI** — Thème `plain` (classique, sobre) par défaut ; thème `nerv` (Evangelion) activable
  - Le thème `nerv` affiche un **tableau de bord plein écran type htop** : matrice de circuit avec compteurs animés, barres SYNC MAGI, doubles minuteurs, flux de logs et alertes rouges. Les logs sont intégrés à la fenêtre (aucune sortie parasite).
- **Compatibilité Windows / WSL** — Traduit automatiquement les chemins Windows (`D:\...`) en chemins Linux (`/mnt/d/...`) lorsque le script tourne sous WSL
- **Logs console uniquement** — Aucun fichier de log généré

## Sécurité des données

Les originaux ne sont **jamais modifiés**. Le pipeline est : copie → compression de la copie.

```
D:\CalibreLibrary (originaux intacts)   D:\CalibreLibraryCmp (copies compressées)
├── Auteur A/                            ├── Auteur A - Titre 1.epub
│   ├── Titre 1/                         ├── Auteur A - Titre 2.epub
│   │   └── Titre 1.epub  ──────────→   └── Auteur B - Titre 3.epub
│   └── Titre 2/
│       └── Titre 2.epub  ──────────→
└── Auteur B/
    └── Titre 3/
        └── Titre 3.epub  ──────────→
```

## Installation

```bash
pip install -r requirements.txt
```

**Prérequis** : Python 3.11+

## Configuration

Éditez `config.json` :

```json
{
    "source_dir": "D:\\CalibreLibrary",
    "destination_dir": "D:\\CalibreLibraryCmp",
    "theme": "plain",
    "compression": {
        "target_size_ratio": 0.10,
        "jpeg_quality_min": 10,
        "jpeg_quality_max": 85,
        "max_width": 1200,
        "max_height": 1600,
        "convert_png_to_jpeg": true
    }
}
```

| Paramètre | Description | Défaut |
|---|---|---|
| `source_dir` | Dossier source — chemins Windows (`D:\...`) ou Linux acceptés | — |
| `destination_dir` | Dossier destination (créé si inexistant) | — |
| `theme` | `plain` (classique) ou `nerv` (Evangelion) | `plain` |
| `target_size_ratio` | Ratio cible (0.10 = 10 % de la taille originale) | `0.10` |
| `jpeg_quality_min` | Qualité JPEG minimale (borne basse de la dichotomie) | `10` |
| `jpeg_quality_max` | Qualité JPEG maximale (borne haute) | `85` |
| `max_width` | Largeur maximale des images (px) | `1200` |
| `max_height` | Hauteur maximale des images (px) | `1600` |
| `convert_png_to_jpeg` | Convertir les PNG en JPEG (sauf transparence si désactivé) | `true` |

## Utilisation

```bash
# Pipeline complet : copie → compression
python epub_manager.py

# Simulation (aucun fichier modifié)
python epub_manager.py --dry-run

# Copie uniquement (sans compression)
python epub_manager.py --copy-only

# Compression uniquement (fichiers déjà dans la destination)
python epub_manager.py --compress-only

# Activer le thème Evangelion
python epub_manager.py --theme nerv

# Config personnalisée + logs détaillés
python epub_manager.py --config autre_config.json --verbose
```

### Options CLI

| Option | Court | Description |
|---|---|---|
| `--config FILE` | `-c` | Fichier de configuration (défaut : `config.json`) |
| `--theme` | `-t` | Thème de l'interface (`nerv` ou `plain`) — prioritaire sur la config |
| `--dry-run` | `-n` | Mode simulation |
| `--copy-only` | | Copie sans compression |
| `--compress-only` | | Compression sans copie |
| `--verbose` | `-v` | Logs DEBUG dans le terminal |

## Compatibilité WSL

Les chemins Windows dans `config.json` (`D:\CalibreLibrary`) sont automatiquement convertis en chemins WSL (`/mnt/d/CalibreLibrary`) lorsque le script est exécuté sous Linux. Aucune modification de configuration nécessaire.

## Licence

Projet personnel — libre d'utilisation.
