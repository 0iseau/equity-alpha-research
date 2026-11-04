# Projet — actions américaines

Point de départ : les données brutes téléchargées et leur script de collecte.

```text
Project/
├── data/
│   └── raw/                       # Données originales et métadonnées de collecte
├── scripts/
│   └── download_public_data.py    # Collecte FRED / ALFRED
└── README.md
```

Les fichiers CRSP/Compustat ont été exportés manuellement depuis WRDS au CEDIF.
Leur provenance est décrite dans `data/raw/manifest.json` ; le script fourni ne
les télécharge pas. Les sous-dossiers `fred/` et `public/` conservent les données
publiques déjà collectées, avec leurs métadonnées existantes.

## Télécharger les données publiques

Depuis ce dossier, avec Python 3.10 ou supérieur (bibliothèque standard uniquement) :

```powershell
python scripts/download_public_data.py --help
python scripts/download_public_data.py --end 2025-12-31
```

Chaque exécution crée une nouvelle collecte horodatée dans `data/raw/public/`.
Vérifier que son `manifest.json` indique `status: complete` ; les échecs sont
signalés et ne doivent pas être ignorés. Aucun téléchargement n'a été relancé
pendant le nettoyage.

Les données brutes ne sont pas encore préparées pour une simulation historique :
une date d'observation n'établit pas à elle seule la disponibilité de l'information.
Les traitements et analyses seront reconstruits progressivement.

L'historique Git est conservé dans le dossier caché `.git`. Les anciens fichiers
de travail ont été supprimés, sans créer de commit ; les versions déjà enregistrées
restent consultables dans Git.
