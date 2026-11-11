# Equity Alpha Research

Stratégie long only sur actions américaines (Applied Investments, HEC Lausanne).

```text
Project/
├── ProjectWorkflow.md   # Étapes du projet
├── CleaningSpec.md      # Spécification du nettoyage des données
├── scripts/
│   ├── data_download/   # Collecte des données publiques (FRED, Ken French)
│   └── data_cleaning/   # Nettoyage, une étape par script
├── resources/           # Tables de référence et dictionnaire de données
├── audit/               # Paquets d'audit, un par étape
└── data/                # Données locales, non publiées
```

Les données CRSP/Compustat (WRDS) restent locales et ne sont pas publiées.
Les données FRED/ALFRED se collectent avec :

```powershell
python scripts/data_download/download_public_data.py --end 2025-12-31
```
