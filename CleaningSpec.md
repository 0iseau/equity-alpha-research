# Spécification du nettoyage et de la préparation des données

Version 0.1 du 2026-11-11, à valider par Danny puis à faire auditer par ChatGPT.

## Sources de référence

- **JKP** : Jensen, Kelly et Pedersen (2023), *Is There a Replication Crisis in
  Finance?*, JF. Code Python `github.com/bkelly-lab/jkp-data`, fichiers
  `src/jkp/data/main.py`, `config.py` et `aux_functions.py`. Le pipeline lit le
  format **CIZ**, comme nos fichiers.
- **TF** : Tidy Finance with Python, chapitres `wrds-crsp-and-compustat`,
  `value-and-bivariate-sorts` et `replicating-fama-and-french-factors` (source :
  `github.com/tidy-finance/website/chapters`). Ces chapitres lisent aussi le
  format **CIZ**.
- **Cours** : slides de Goyal, cours 1 (Strategies) et 3 (Trading costs).

Règle générale : **JKP pour la rigueur** des définitions, **TF pour la simplicité**
de mise en œuvre et **le cours prime** en cas de conflit. Chaque écart est
justifié ci-dessous.

Certains éléments n'ont été vus qu'à travers un résumé du code, sans lecture du
texte exact. Ils sont marqués *(à reconfirmer)*.

## Profil de nos fichiers bruts (vérifié le 2026-11-11)

| Constat | Conséquence |
|---|---|
| `crsp_ciz_security_history.csv` ne contient **pas `conditionaltype`**. JKP et TF utilisent ce champ pour isoler la cotation régulière. | Il faut un substitut (voir l'étape 3). |
| Les intervalles de `secinfostartdt` à `secinfoenddt` ne se chevauchent pas et n'ont pas de trou (191 048 lignes, 40 518 PERMNO). | La jointure par intervalle de dates est sûre. |
| Pour **23 114 radiations sur 29 528**, l'intervalle d'information se termine avant la fin du mois de radiation. Le mois de radiation tombe alors sur une ligne où `primaryexch = 'X'`. | La jointure TF telle quelle **supprimerait le mois de radiation**, ce qui recrée un biais du survivant (voir l'étape 3). |
| Le fichier contient aussi des fonds (`FUND`, `ETF`, `CEF`), des ADR (`AD`), des REIT et des titres non incorporés aux US (47 421 lignes avec `usincflg = N`). | Ils sont filtrés à l'étape 3. |
| Le fichier Compustat est déjà filtré : `INDL`, `STD`, `C` et `D` partout. On y trouve 5 388 lignes en CAD et 15 sans devise. | Seules les lignes en USD sont gardées (étape 7). |
| Le fichier Compustat contient **2 933 doublons gvkey-datadate**. C'est un extrait CCM avec `LPERMNO`, donc probablement une ligne par PERMNO lié. | La table doit être dédupliquée (étape 7). |
| Dans la table des liens, `LINKENDDT = 'E'` signifie un lien encore ouvert. | Ce code est traité comme une date infinie. |
| Le CRSP mensuel contient une ligne par événement de distribution. Prix, rendement, capitalisation et volume y sont toujours identiques pour un même mois. | Le panel est dédupliqué et les distributions vont dans une table séparée (étape 1). |

## Conventions transverses

- **Sorties** : fichiers Parquet dans `data/processed/`, écrits de façon atomique.
  Chaque table a un rapport de contrôle JSON enregistré à côté, avec les chiffres
  clés et la liste des cas rejetés.
- **Unités natives conservées** et documentées dans un dictionnaire de données.
  Seule exception : la capitalisation `me` est exprimée en **millions de USD**
  (`MthCap / 1000`), comme chez JKP et TF.
- **Clé temporelle** : `eom`, la fin de mois calendaire. `MthCalDt` est gardé tel
  quel.
- **Les données nettoyées gardent tout l'historique.** L'échantillon d'analyse
  (1963-2025) est choisi plus tard.
- **Les manquants restent manquants.** Aucun remplissage ni imputation, sauf les
  rendements de radiation explicitement décrits à l'étape 2.
- **Échec en cas d'anomalie.** Un schéma, une clé ou une plage de valeurs
  inattendus arrêtent le script. Les valeurs atypiques sont signalées, sans être
  supprimées.

## Étapes

### Étapes 1 et 2 : panel CRSP mensuel et radiations — **implémentées**

Script `scripts/data_cleaning/1_crsp_monthly.py`, version 2, corrigée après l'audit Astra du
2026-11-11. Sorties :
- `crsp_monthly.parquet` ;
- `crsp_distributions.parquet` ;
- `crsp_d9_reconciliation.csv` ;
- `crsp_monthly_report.json`, écrit en dernier, avec l'identifiant de
  l'exécution et les SHA-256 des entrées et des sorties.

**Code repris** :
- JKP `gen_crsp_sf` : choix des colonnes, indicateur `bidask` (BA → 1, TR → 0),
  `shrout` en millions.
- JKP `prepare_crsp_sf`, branche mensuelle :
  - jointure des radiations sur `(permno, mois)` ;
  - imputation de −30 % pour les radiations liées à la performance sans
    rendement (codes CIZ c2 et c3) ;
  - composition `(1+ret)(1+delret)−1` sauf si `MthDelFlg ∈ {A, P, V}` ;
  - calcul de `me_company`.
- TF : `me = 0` devient manquant, et `me_lag1` vient d'une jointure décalée d'un
  mois (manquant s'il y a un trou).

**Rendement total `ret` et sa colonne `ret_status`** :
- `crsp` : `MthRet` tel quel (mois N, A, P et V) ;
- `crsp_plus_delret` / `crsp_plus_delret_imputed` : mois M ou G composé avec
  `delret`, observé ou imputé à −30 % ;
- `daily_plus_delret` / `daily_plus_delret_imputed` : mois ajouté par D9 ;
- `missing_*` : une partie du rendement est inconnue, donc `ret` est manquant,
  avec la raison :
  - `missing_crsp` : `MthRet` manquant ;
  - `missing_pre_delisting` : la partie avant radiation est inconnue ;
  - `missing_delret` : le rendement de radiation est inconnu ;
  - `missing_delist_record` : pas de fiche de radiation (avant 1950).
- `ret_crsp` garde toujours `MthRet` brut, et `delret_raw` le `delret` brut.

**Disponibilité des montants de radiation.** Le rendement de radiation est
attribué au mois de radiation : c'est le rendement de détention de la position,
selon la convention de CRSP et de JKP. Il peut reposer sur un montant connu plus
tard (`delamtdt`, `delnextdt` conservés), par exemple 537 des 547 cas G. Le titre
sort de l'univers à sa radiation, donc ce rendement **n'alimente aucun signal**.
Au backtest, le produit est supposé réinvesti à la fin du mois de radiation.

**Écarts justifiés par nos données** :
- **`me = MthCap / 1000`** au lieu de `prc × shrout` (JKP). Dans 180 lignes, le
  dernier prix est antérieur au nombre d'actions courant, et seul `MthCap` utilise
  les actions à la date du prix. Le contrôle confirme que **tous** les écarts
  viennent de ce cas ou d'un arrondi.
- **Volume en actions.** JKP multiplie le volume mensuel par 100, mais dans notre
  export `MthVol` est exactement la somme des `DlyVol`. L'ajustement du volume
  NASDAQ et le volume en dollars passent à l'étape 3, car ils ont besoin de la
  bourse.
- **Pas de `div_tot`**, car `MthCumFacShr` est absent de l'export. Les dividendes
  restent dans la table des distributions.
- **274 mois de radiation ajoutés (D9).** Ces actions sont radiées le mois qui
  suit leur dernière ligne CRSP, sans ligne pour ce mois, et la jointure JKP perd
  leur rendement de radiation.
  - On ajoute une ligne avec `date = delistingdt` et `delist_row_added = True`.
  - Son rendement est `(1 + r_avant)(1 + delret) − 1`, où `r_avant` compose les
    rendements quotidiens `DlyDelFlg = N` entre la dernière date mensuelle et la
    date de radiation. La ligne quotidienne `Y`, qui porte le rendement de
    radiation, est exclue de ce produit.
  - CRSP fait le pont sur les jours sans prix : sur nos données, ce produit
    retrouve `MthRet` dans 99 % des 1 062 mois comparables qui ont de tels jours.
  - **Rupture** : un jour avec un prix mais sans rendement signifie que CRSP n'a
    pas relié ce prix au précédent. La chaîne est coupée, la partie avant
    radiation est inconnue, et `ret` reste manquant (`pre_delist_break`).
  - Sans rendement quotidien utilisable, `ret` reste manquant aussi.
  - Les lignes quotidiennes répétées à l'identique sont dédoublonnées. Deux
    lignes différentes pour un même jour arrêtent le script.
  - Si plusieurs parties manquent à la fois, `ret_status` donne la priorité à la
    partie avant radiation. Le rapport compte ces chevauchements.
- **Pas de `ret = 0` (D10).** JKP remplace un rendement manquant par 0 quand
  `delret` existe, et un `delret` manquant par 0 pour les radiations qui ne sont
  pas liées à la performance. Ici, si une partie du rendement de détention est
  inconnue, `ret` reste manquant et `ret_status` dit pourquoi : une valeur
  manquante n'est pas zéro.
- Les mois N, A, P et V gardent `ret` **exactement** égal à `MthRet`, ce que
  vérifie un contrôle.
- Le CUSIP d'en-tête est renommé `hdr_cusip`. Le CUSIP historique viendra de
  l'historique des titres, à l'étape 3.
- `me_company` est daté à la fin du mois. `me_company_complete` indique si toutes
  les classes d'actions de la société ont une capitalisation ce mois-là (1 393
  société-mois partiels).

**Résultats des contrôles** (rapport JSON de la version 3, après la contre-revue
Astra) :
- 5 276 434 lignes brutes donnent 5 210 620 mois-action, plus 274 mois de
  radiation ajoutés, pour 40 437 titres de 1930-01 à 2025-12 ;
- les champs propres à l'action ne sont jamais en conflit ; les clés, dates et
  indicateurs ne sont jamais nuls ; les nombres sont finis ; les prix et le
  nombre d'actions sont positifs ;
- 1 089 403 événements de distribution, sans conflit ;
- les 29 509 radiations des titres présents sont toutes reliées à un mois, et
  aucune ne tombe sur un mois N ;
- **contrôle inverse** : 236 mois ont un indicateur de radiation sans fiche,
  tous en 1949 ou avant, car le fichier des radiations commence le 1950-05-06.
  Les A et P sont complets ; les 102 cas M et G ont un rendement manquant
  (98 `missing_delist_record` et 4 `missing_pre_delisting`, qui n'ont pas non
  plus de fiche) ;
- D9 : 244 rendements reconstruits (197 avec `delret` observé, 47 imputés) et
  30 manquants, dont 29 ruptures de cotation : les 18 cas de la contre-revue et
  11 autres du même type ;
- cas de référence de l'audit retrouvés : PERMNO 65788 à −22,73 % et 12964 à
  −79,82 % ;
- 2 900 imputations à −30 % ;
- 83 884 rendements finaux manquants, dont 83 409 au statut `missing_crsp` ;
- le rendement pondéré de tous les titres suit `vwretd` avec une corrélation de
  0,99978 sur 1 151 mois ;
- 732 rendements dépassent +300 % : ils sont signalés, pas supprimés.

**Reporté aux étapes suivantes** (réserves de la contre-revue, sans effet sur le
panel) :
- **Financement des produits de radiation tardifs**, réserve sur le constat 4 :
  au backtest, le produit d'une radiation G dont le montant est connu après le
  mois (`delamtdt > eom`) n'est réinvesti qu'à partir de `delamtdt`. Entre les
  deux, il est traité comme une créance.
- **Lecture sûre**, réserve sur le constat 10 : chaque script qui lit ces
  sorties vérifie d'abord leurs SHA-256 contre `crsp_monthly_report.json`.

**Statut : étapes 1 et 2 closes le 2026-11-11.** Contre-revue Astra traitée ;
aucun constat bloquant ouvert.

### Étape 3 : univers éligible (`eligible` dans le panel)

**Inspiration** : filtres TF et JKP, avec une adaptation sur le moment où
l'éligibilité est jugée.

Filtres TF repris :
- `sharetype = 'NS'` ;
- `securitytype = 'EQTY'` ;
- `securitysubtype = 'COM'` ;
- `issuertype ∈ {ACOR, CORP}` ;
- `primaryexch ∈ {N, A, Q}` ;
- `tradingstatusflg = 'A'` ;
- `usincflg = 'Y'`. JKP n'applique pas ce dernier filtre. **Décision D1.**

Le champ `conditionaltype ∈ {RW, NW}` est **absent** de notre export. On le
remplace par `tradingstatusflg = 'A'` et `primaryexch ∈ {N, A, Q}`, et cette
limite est documentée. **Décision D2.** Alternative : réexporter l'historique des
titres depuis WRDS.

**Adaptation clé.** L'éligibilité est jugée **à la date de formation**, fin du
mois t, à partir de l'information valide à `MthCalDt` du mois t. Le rendement
du mois t+1 est ensuite **toujours conservé**, quel que soit le statut du titre
en t+1. Cela évite à la fois le look-ahead et la perte du mois de radiation : JKP
et TF filtrent au même mois, ce qui perdrait 23 114 mois de radiation chez nous.

Le code SIC historique `siccd` est pris dans l'historique des titres (TF).

**Implémentation : `scripts/data_cleaning/3_crsp_universe.py`** (2026-11-11). Sorties :
`crsp_universe.parquet`, c'est-à-dire tout le panel avec les indicateurs, et
`crsp_universe_report.json`.

- **Lecture sûre** : `crsp_monthly.parquet` n'est lu que si son SHA-256
  correspond au rapport de l'étape 1 (`utils.read_verified`).
- **Jointure** (JKP `gen_crsp_sf`) : on prend l'intervalle de l'historique des
  titres valide à `date` (`secinfostartdt ≤ date ≤ secinfoenddt`). Les
  intervalles ne se chevauchent jamais, ce qui est vérifié.
- **Indicateurs** :
  - `common` (JKP) : `EQTY`, `COM`, `NS` et `issuertype ∈ {ACOR, CORP}` ;
  - `exch_main` : `primaryexch ∈ {N, A, Q}` et `tradingstatusflg = 'A'` (D2) ;
  - `us_inc` : `usincflg = 'Y'` (D1) ;
  - `eligible` : `common`, `exch_main` et `us_inc`, avec `me` connu et
    **aucune radiation dans le mois** (`MthDelFlg = 'N'`), car une action radiée
    pendant le mois t ne peut pas être achetée à la fin de t ;
  - `crsp_nyse` : éligible et `primaryexch = 'N'`, pour les bornes NYSE de
    l'étape 4.
- **`ret_lead1`** : rendement total de la ligne du mois t+1 (`ret` et
  `ret_status` des étapes 1 et 2), si cette ligne existe. Le statut du titre en
  t+1 n'est pas utilisé.
- **Volume** (JKP) : ajustement du volume NASDAQ de Gao-Ritter
  (`adj_trd_vol_NASDAQ`, copié tel quel) et `dolvol = |prc| × vol_adj` en USD,
  sans le ×100 de JKP.
- **Industries** (JKP `crsp_industry`, `_parse_siccodes_file`) : `sic = 0`
  devient manquant, et `ff49` vient de `resources/Siccodes49.txt`, copié de JKP.
- **CUSIP historique** : `cusip` vient de l'historique des titres, à la date de
  la ligne. `hdr_cusip` reste le CUSIP d'en-tête.

**Résultats des contrôles** :
- **22 341 lignes sans information de titre**, toutes des mois de radiation
  (indicateurs A, P, M, G et V) : l'historique des titres s'arrête à la date de
  radiation, avant la fin du mois. Le script échoue si un mois N n'a pas
  d'information ;
- **3 805 426 mois-action éligibles**. Depuis 1963 : entre 1 963 et 7 462 titres
  par mois (4 563 en moyenne, environ 80 % du nombre de titres de l'indice CRSP),
  et au moins 1 139 titres NYSE par mois ;
- effet des filtres depuis 1963, sur 4 844 588 lignes : `common` en garde
  3 782 727, puis `exch_main` 3 717 129, puis `us_inc` 3 466 247, et enfin
  `me` connu et aucune radiation dans le mois 3 449 977 ;
- **25 481 lignes t+1 conservées** alors que le titre n'est plus éligible en
  t+1, dont 24 235 ont un rendement numérique. Parmi les positions éligibles
  en t, **22 948** ont un mois de radiation en t+1, dont 22 673 avec un
  rendement numérique : ce sont les rendements qu'un filtre appliqué au même
  mois aurait perdus. Le comptage utilise l'indicateur de radiation de t+1 ;
  la v1 du rapport ne comptait que M, G et D9, soit 3 322 ;
- t+1 manquant pour un titre éligible : 3 659 « pas de ligne suivante », tous en
  2025-12 sauf 2 cas en 1930-32. S'y ajoutent 1 036 `missing_crsp` et
  275 rendements de radiation inconnus. Leur poids sera rapporté au backtest ;
- le rendement pondéré de t+1 des titres éligibles en t suit `vwretd` avec une
  corrélation de 0,99869 sur 756 mois depuis 1963 (+0,03 % par mois en moyenne :
  l'indice contient aussi des fonds, des ADR et des REIT) ;
- `ff49` est manquant sur 2,5 % des lignes éligibles : code SIC manquant ou hors
  liste FF49, comme chez JKP.

**Corrections après l'audit Astra de l'étape 3** (2026-11-11) :
- **Volume NASDAQ des mois de radiation**, constat 1. L'ajustement de
  Gao-Ritter prend la bourse à la date si le titre y est actif. Sinon, il prend
  celle du **dernier intervalle actif**, là où le volume a été échangé :
  9 043 lignes corrigées. Cas de contrôle : PERMNO 10003 en 1995-12 donne
  `vol_adj` = 73 190,5. Les changements de régime à l'intérieur d'un mois ne
  sont pas ventilés jour par jour, une limite documentée. Ces lignes sont
  toutes inéligibles en t, donc aucun rendement n'est touché.
- **Compteurs**, constat 2 : corrigés, voir ci-dessus.
- **`eligible` est un filtre d'univers**, constat 3 ; il ne garantit pas
  l'exécution au prix de clôture. Deux colonnes aideront le backtest à séparer
  la formation de l'ordre de son exécution :
  - `prc_age_days` : âge du dernier prix. Parmi les lignes éligibles, 3 737 ont
    un prix antérieur à la date, dont 1 158 de plus de 7 jours ;
  - `zero_volume` : aucun volume dans le mois (5 624 lignes éligibles).

  Les rendements des positions déjà détenues ne sont pas touchés.
- **Poids des rendements t+1 inconnus**, constat 4 : publié dans le rapport,
  soit 0,0097 % de la capitalisation éligible par mois en moyenne.
- **`read_verified`**, constat 5 : le hachage et la lecture portent maintenant
  sur les mêmes octets.
- Précision sur D2 : JKP exige `conditionaltype = RW`, alors que TF accepte RW
  et NW avec un statut actif. Notre substitut est plus proche de TF. L'écart ne
  peut pas être chiffré sans réexporter `conditionaltype`.
- Corrections v3 des étapes 1 et 2 : N1 à N4 confirmés résolus par Astra.

**Statut : étape 3 close le 2026-11-11.**

### Étape 4 : bornes NYSE et groupes de taille

**Inspiration** : JKP (`nyse_size_cutoffs`, `classify_stocks_size_groups`).

- Bornes calculées chaque mois sur les titres éligibles avec `primaryexch = 'N'` :
  centiles 1, 20, 50 et 80 de `me`.
- Groupes : **mega** au-dessus de p80, **large** entre p50 et p80, **small**
  entre p20 et p50, **micro** entre p1 et p20, **nano** sous p1.
- **Toutes les tailles sont gardées** dans les données. Le groupe de taille est
  un simple indicateur, et aucune action n'est retirée au nettoyage.
  **Décision D7.**
- L'exclusion éventuelle d'un groupe est décidée plus tard, à l'étape du
  backtest, par une **règle fixée dès maintenant** :
  - pour chaque groupe de taille, on mesure l'alpha brut, le turnover, les coûts
    estimés (spread et impact de prix pour 100 M$) et le **coût de rentabilité
    nulle**, égal à l'alpha brut divisé par le turnover ;
  - un groupe est retiré du portefeuille final si ses coûts estimés dépassent ce
    coût de rentabilité nulle, ou si 100 M$ y représenteraient une part trop
    grande du volume échangé ;
  - la règle porte sur les coûts et la capacité, **jamais sur l'alpha seul**.
    Sources : Novy-Marx et Velikov (2016) et le cours 3.
  - Les résultats sont présentés dans trois versions : toutes les actions, sans
    les titres sous le 20e centile NYSE, et avec notre règle.
  - Le seuil de participation au volume reste à fixer avant le backtest.
- Les bornes NYSE serviront aussi aux tris en déciles (cours).

**Implémentation : `scripts/data_cleaning/4_crsp_size.py`** (2026-11-11). Sorties :
- `nyse_cutoffs.parquet` : une ligne par mois avec `n`, `nyse_p1`, `nyse_p20`,
  `nyse_p50` et `nyse_p80` ;
- `crsp_panel.parquet` : le panel de l'étape 3, plus `size_grp` et `me_cap` ;
- `crsp_size_report.json`.

- **Code repris** :
  - JKP `nyse_size_cutoffs` : agrégats SQL copiés (`QUANTILE_DISC` à 1 %, 20 %,
    50 % et 80 %). Le filtre NYSE de JKP (`obs_main`, `exch_main`,
    `primary_sec`, `common`) est remplacé par notre éligibilité de l'étape 3 ;
  - JKP `classify_stocks_size_groups` : groupes nano, micro, small, large et
    mega ;
  - JKP `me_cap = min(me, nyse_p80)`, pour les poids plafonnés. `me_cap` est
    manquant si `me` ou p80 manque (correction de l'audit : `min_horizontal`
    ignore les manquants). Contrôle sur tout le panel.
- **Échantillon NYSE** : nos titres éligibles cotés au NYSE (`crsp_nyse`), à la
  capitalisation du **titre**, comme JKP. TF exige aussi l'incorporation aux US.
- **Écart avec JKP** : JKP classe un mois sans borne en « mega » pour reproduire
  SAS. Ici, un titre éligible sans groupe arrête le script.
- La lecture de `crsp_universe.parquet` est vérifiée par SHA-256.

**Résultats des contrôles** :
- 1 152 mois de bornes, toujours ordonnées. Depuis 1963 : de 1 139 à 1 874
  titres NYSE par mois, et chaque titre éligible a un groupe ;
- part des titres NYSE par groupe : 1,0 / 19,0 / 30,0 / 30,0 / 20,0 %, comme
  prévu ;
- tous les titres éligibles depuis 1963, en nombre puis en capitalisation :

  | Groupe | Part des titres | Part de la capitalisation |
  |---|---|---|
  | nano | 18,8 % | 0,3 % |
  | micro | 40,7 % | 2,7 % |
  | small | 20,5 % | 6,6 % |
  | large | 12,9 % | 16,0 % |
  | mega | 7,2 % | 74,5 % |

- **contrôle indépendant** avec les bornes NYSE de Ken French
  (`ME_Breakpoints`), sur 756 mois depuis 1963 : corrélation des logarithmes de
  0,998 (p20), 0,9996 (p50) et 0,9998 (p80) ;
  - les années 1960 et 1970 concordent à moins de 1 % ;
  - l'écart médian du p50 (nous / French − 1) grandit ensuite. Le test d'Astra,
    qui additionne les classes d'actions par PERMCO, donne :

    | Période | Par titre | Par société |
    |---|---|---|
    | 1963–1979 | +0,0 % | 0,0 % |
    | 1980–1989 | −1,3 % | −1,3 % |
    | 1990–2019 | −3,4 % | −0,6 % |
    | 2020–2025 | −13,4 % | −11,2 % |

  - Ken French compte des **sociétés** (classes additionnées), alors que JKP et
    nous comptons des titres. Cela explique l'essentiel de l'écart de 1990 à
    2019, mais pas celui des années 1980 ;
  - l'écart des années 2020 vient peut-être des SPAC : 51 titres NYSE ont le mot
    « ACQUISITION » dans leur nom en 2022-04, dont 41 en SIC 6799. C'est une
    **hypothèse**, car le fichier French ne donne pas ses titres. Même sans eux,
    il reste 118 sociétés de plus que chez French ;
  - choix retenu : rester sur la convention JKP, au niveau du titre. Aucun
    rendement n'est touché, mais les groupes changent : avec les bornes French,
    29 969 observations éligibles de 1963 à 2019 changeraient de groupe. Les
    tris avec les bornes Ken French sont un **test de robustesse possible** au
    backtest.
  - Le contrôle vérifie aussi que chaque mois depuis 1963 est présent une seule
    fois dans le fichier French et que les bornes comparées sont positives.
- Le téléchargeur Ken French s'arrête sans rien écrire si un fichier en ligne
  diffère du fichier local (nouveau millésime). Le manifeste est écrit en
  dernier, par un fichier temporaire.

**Statut : étape 4 close le 2026-11-11** (audit Astra « À CORRIGER », constat
bloquant `me_cap` corrigé ; exécution `51233f73d9fe` après les deux réserves
mineures de l'audit de l'étape 5).

### Étape 5 : rendements excédentaires

**Inspiration** : TF.

- `ret_exc = ret − rf`, où `ret` est le rendement total validé des étapes 1 et 2
  et non `MthRet`. Le taux `rf` est tiré de la Ken French Data Library
  (téléchargée à ce moment-là). JKP utilise `t30ret` de CRSP, que nous n'avons
  pas.
- Le rendement excédentaire du mois suivant `ret_exc_lead1m` n'est calculé que si
  le mois suivant existe dans le panel, ou s'il s'agit du mois de radiation.

**Implémentation : `scripts/data_cleaning/5_crsp_excess.py`** (2026-11-11, run `227ee7867201`).
Sorties :
- `ff_factors_monthly.parquet` : par mois `yyyymm`, les facteurs FF3
  (`mkt_excess`, `smb`, `hml`), FF5 (`mkt_excess_ff5`, `smb_ff5`, `hml_ff5`,
  `rmw`, `cma`), le momentum `mom` et `risk_free`, en décimales ;
- `crsp_panel_exc.parquet` : le panel de l'étape 4, plus `risk_free`, `ret_exc`
  et `ret_exc_lead1` ;
- `crsp_excess_report.json`.

- **Code repris** :
  - TF, lecture des fichiers Ken French : codes −99,99 et −999 → manquant,
    division par 100, `Mkt-RF` → `mkt_excess`, `RF` → `risk_free` ;
  - TF, jointure à gauche sur le mois puis `ret_excess = ret − risk_free` ;
  - JKP `ret_exc_lead1m` : ici `ret_exc_lead1 = ret_lead1 − rf(t+1)`, où
    `ret_lead1` vient de l'étape 3 (ligne du mois t+1, mois de radiation inclus).
- **Écarts** :
  - JKP utilise `t30ret` de CRSP, absent de notre extrait : on utilise le RF de
    Ken French ;
  - TF supprime les rendements excédentaires manquants ; ici aucune ligne n'est
    retirée, et un rendement manquant reste manquant.
- **Facteurs** : le RF de FF5 est identique à celui de FF3. Le Mkt-RF de FF5
  diffère légèrement (au plus 0,08 %, 30 mois au-delà de l'arrondi de 0,01 %).
  La cause n'est pas établie : les notices French donnent les mêmes critères
  pour le marché. Le SMB diffère presque chaque mois (construction différente),
  le HML jamais. Comme TF, on garde les facteurs propres à chaque modèle : les
  régressions FF5 utiliseront les colonnes `_ff5`, au plus tôt depuis 1963-07.
- **Millésime** : les fichiers Ken French sont révisés à chaque publication. On
  garde le millésime téléchargé (CRSP 202609), protégé par le téléchargeur.
  Les facteurs vont jusqu'à 2026-09, au-delà de notre panel (2025-12) : les
  régressions s'arrêteront à 2025-12.

**Résultats des contrôles** :
- fichiers Ken French : empreinte SHA-256 égale au manifeste (sur les octets
  lus), en-tête exact, mois réels, uniques et consécutifs, valeurs finies ;
- chaque facteur est présent sur tout son calendrier d'utilisation : 1963-01 à
  2025-12 pour FF3, momentum et RF, 1963-07 à 2025-12 pour FF5 ;
- RF mensuel entre −0,06 % et 1,35 %, jamais manquant, présent et égal dans FF3
  et FF5 sur chaque mois commun ;
- `ret_exc` est manquant exactement quand `ret` l'est (83 884 lignes), de même
  pour `ret_exc_lead1` et `ret_lead1` (122 584 lignes), et chaque rendement a
  son RF ;
- **contrôle de datation titre par titre** : sur les 5 210 894 lignes,
  `ret_exc_lead1` du mois t égale `ret_exc` de la ligne du mois t+1 du même
  titre, manquants compris. Ce contrôle échoue si on soustrait le RF du mauvais
  mois (testé : 3,9 millions de lignes en erreur) ;
- **contrôle de marché** : le rendement excédentaire VW en t+1 des titres
  éligibles, pondéré par `me` de t, contre le Mkt-RF de Fama-French du mois
  t+1, sur 755 mois depuis 1963 : corrélation **0,99999**, écart absolu moyen
  de 0,009 % par mois. Décalé d'un mois, la corrélation tombe à 0,04. Il situe
  le mois du marché, mais ne distingue pas le RF utilisé.

**Statut : étape 5 close le 2026-11-11** (audit Astra « VALIDÉ AVEC RÉSERVES »,
réserves traitées ; exécutions `51233f73d9fe` pour l'étape 4 et `372513cad024`
pour l'étape 5, après l'ajout du contrôle « aucun mois vide » demandé à l'audit
de l'étape 6).

### Étape 6 : liens CRSP-Compustat (`ccm_links.parquet`)

**Inspiration** : TF *(à reconfirmer)*, plus prudent que JKP.

- `LINKTYPE ∈ {LC, LU}` et `LINKPRIM ∈ {P, C}` (TF). JKP ajoute `LS` et n'utilise
  pas `LINKPRIM`. Le relevé JKP signale lui-même un risque de liens en double
  non déterministes. **Décision D5.**
- `LINKENDDT = 'E'` est traité comme +∞ ; la date est valide si
  `LINKDT ≤ date ≤ LINKENDDT`.

**Contrôles** : **zéro doublon** `(PERMNO, date)` ni `(gvkey, date)` après
filtrage. Dans le cas contraire, le script échoue.

**Implémentation : `scripts/data_cleaning/6_ccm_links.py`** (2026-11-11, run `700c7a6b03bf`).
Sorties :
- `ccm_link_table.parquet` : les 32 306 liens gardés (`permno`, `gvkey`,
  `linkdt`, `linkenddt` nul si le lien est encore actif, type, drapeau, `liid`) ;
- `ccm_links.parquet` : une ligne par mois-action lié (`permno`, `yyyymm`,
  `eom`, `date`, `gvkey`), soit 4 125 224 lignes. Le `gvkey` sera joint au panel
  à l'étape 8 ;
- `ccm_links_report.json`.

- **Code repris** :
  - TF `ccm_linking_table` : `linktype ∈ {LU, LC}` et `linkprim ∈ {P, C}` ;
  - TF `ccm_links` : jointure sur `permno`, puis date dans
    `[linkdt, linkenddt]` ;
  - JKP `gen_crsp_sf` : le test porte sur la date de la ligne CRSP, et une fin
    ouverte vaut +∞. Cette date est notre colonne `date` : `MthCalDt` sur une
    ligne CRSP (dernier jour de cotation du mois dans le calendrier CRSP), et
    `delistingdt` sur une ligne de radiation ajoutée (D9). Avec la fin de mois
    civile, 267 liens éligibles seraient perdus et 9 changeraient de société.
- **Lecture stricte** : en-tête exact, types et drapeaux connus, dates
  converties strictement, clé `(gvkey, LIID, LINKDT)` unique, `LPERMNO` manquant
  seulement pour les types sans titre CRSP (NR, NU). La taille du fichier est
  comparée au manifeste brut, et son SHA-256 est noté dans le rapport.

**Résultats des contrôles** :
- liens gardés : **aucun chevauchement** par `permno` ni par `gvkey` ;
- zéro doublon `(permno, mois)` et zéro doublon `(gvkey, date)`. Un seul mois
  porte deux titres pour une même société (179077, 2017-10) : l'ancien titre est
  radié le 5 et son successeur est coté en fin de mois. Jamais deux titres
  éligibles pour une société dans le même mois ;
- **couverture des mois-actions éligibles depuis 1963** : 93,3 % en nombre et
  **98,1 % en capitalisation** ;

  | Décennie | En nombre | En capitalisation |
  |---|---|---|
  | 1960 | 71,0 % | 92,6 % |
  | 1970 | 84,4 % | 97,2 % |
  | 1980 | 91,1 % | 98,5 % |
  | 1990 | 97,5 % | 99,5 % |
  | 2000 | 98,6 % | 99,3 % |
  | 2010 | 98,6 % | 97,9 % |
  | 2020 | 96,0 % | 97,3 % |

- par groupe de taille, en nombre : nano 88,5 %, micro 92,5 %, small 95,0 %,
  large 97,2 %, mega 98,5 % ;
- **liens écartés (D5), parmi les éligibles depuis 1963** :
  - drapeaux J et N (classes d'actions secondaires, par exemple une seconde
    classe cotée de la même société) : 330 titres, 30 763 mois-actions,
    **1,75 % de la capitalisation**. Ces titres restent dans le panel, mais sans
    données comptables ;
  - type LS : 18 titres, 1 589 mois-actions, 0,05 % de la capitalisation ;
- **contrôle par une seconde route** : pour chaque ligne du panel, on prend le
  dernier lien gardé commencé à la date de la ligne ou avant, s'il n'est pas
  fini. Le résultat doit être exactement la table publiée (4 125 224 lignes,
  0 manquante, 0 en trop). Ce contrôle échoue si un mois de liens disparaît
  (testé). Chaque mois depuis 1963 doit aussi avoir plus de 80 % de sa
  capitalisation liée (minimum observé : 88,1 % en 1963-02) ;
- le `PERMCO` du lien égale celui de la ligne du panel sur toutes les lignes
  liées ;
- **rapprochement avec l'export WRDS** : WRDS a fusionné le fichier comptable
  annuel avec cette même table. Ses 343 569 lignes `(gvkey, permno, datadate)`
  tombent toutes dans un lien brut, et 99,1 % dans un lien gardé. Ce test
  valide notre lecture des dates de lien, pas l'existence de comptes pour
  chaque mois lié.

**Limites** :
- la table de liens est celle d'aujourd'hui (CRSP corrige parfois des liens
  anciens). C'est la pratique standard ; les intervalles de validité sont
  respectés ;
- 234 `gvkey` liés sont absents de l'extrait comptable annuel (2 044
  mois-actions éligibles). La disponibilité réelle des comptes sera mesurée à
  leur jointure (étapes 7 et 8) ;
- D5 : parmi les 330 titres J/N, 29 493 des 30 763 mois-actions rejoindraient
  une société qui a déjà un titre éligible lié ce mois-là. Leur poids atteint
  3,3 % de la capitalisation en 2025-11. À rappeler au moment des signaux
  comptables.

**À l'étape 8** : la table est jointe au panel par une **jointure gauche** sur
`(permno, eom)`, pour garder les rendements et les titres sans comptes.

**Statut : étape 6 close le 2026-11-11** (audit Astra « VALIDÉ AVEC RÉSERVES »,
réserves traitées ; exécutions `372513cad024` pour l'étape 5 et `2a792dacd465`
pour l'étape 6).

### Étape 7 : données comptables annuelles (`compustat_annual.parquet`)

**Inspiration** : JKP (`standardized_accounting_data`, `add_helper_vars`) et TF.

- Filtres déjà vérifiés : `INDL`, `STD`, `C`, `D`. On garde **`curcd = 'USD'`**
  (TF). JKP convertit les devises, ce qui serait inutile ici. **Décision D6.**
- **Déduplication** : la table est d'abord ramenée au niveau `gvkey × datadate`
  en retirant `LPERMNO`, après vérification que les champs comptables sont
  identiques. `gvkey × fyear` doit ensuite être unique. Tout conflit fait
  échouer le script.
- **Book equity** (JKP) :
  `be_x = coalesce(seq, ceq + coalesce(pstk_x, 0), at − lt) + coalesce(txditc, 0) − coalesce(pstk_x, 0)`,
  avec `pstk_x = coalesce(pstkrv, pstkl, pstk)`, et `be_x` mis à manquant s'il
  est ≤ 0. Notre extrait n'a ni `txdb` ni `itcb`, donc on utilise directement
  `txditc`.
- Les autres variables auxiliaires (ROE, croissance des actifs, accruals, etc.)
  sont définies à l'étape des signaux, en reprenant les formules JKP.

**Implémentation : `scripts/data_cleaning/7_compustat_annual.py`** (2026-11-11, run
`b3acac9ae9d4`). Sorties :
- `compustat_annual.parquet` : une ligne par `gvkey × datadate`, soit 335 244
  exercices pour 27 438 sociétés, de 1950-06 à 2026-09. Colonnes : `gvkey`,
  `datadate`, `fyear`, `fyr`, `sich`, les 21 postes comptables bruts (millions
  de USD), puis `pstk_x`, `txditc_x`, `seq_x` et `be_x` ;
- `compustat_annual_report.json`.

- **Code repris** :
  - JKP `load_raw_fund_table_and_filter` et TF : les filtres `INDL`, `STD`, `C`
    et `D` sont vérifiés sur chaque ligne ; `curcd = 'USD'` (TF) ;
  - JKP `add_helper_vars` : `at`, `sale` et `che` négatifs mis à manquant, puis
    `pstk_x = coalesce(pstkrv, pstkl, pstk)`,
    `seq_x = coalesce(seq, ceq + coalesce(pstk_x, 0), at − lt)`,
    `be_x = seq_x + coalesce(txditc_x, 0) − coalesce(pstk_x, 0)`, manquant si
    ≤ 0. On suit JKP mot pour mot (TF écrit `ceq + pstk` sans le `coalesce`).
- **Écarts avec la spec initiale et les références** :
  - **pas de sélection du dernier `datadate` par exercice** : après le filtre
    USD, `gvkey × fyear` est déjà unique (contrôle bloquant). Le seul doublon vu
    au profilage venait des 15 lignes sans exercice ni devise. TF, lui, garde le
    dernier rapport par **année civile** de `datadate` : il retirerait 632
    exercices de transition (changement de date de clôture) que nous gardons ;
  - les champs d'en-tête `costat`, `fic` et `ipodate` sont **retirés** : ils
    décrivent la société telle qu'elle est aujourd'hui, et ne doivent pas servir
    à une date passée. `ajex` et `prcc_f` ne sont pas utilisés ;
  - `sich` (code SIC historique, connu depuis 1982) est gardé.
- **Lecture stricte** : en-tête exact, taille comparée au manifeste brut et
  SHA-256 noté, dates et nombres convertis strictement, nombres finis.

**Résultats des contrôles** :
- 343 569 lignes brutes → 340 636 après retrait des copies par `LPERMNO`
  (2 933), **sans aucun conflit** sur les autres champs ;
- devises : 335 244 lignes USD gardées, 5 377 CAD et 15 sans devise retirées.
  197 sociétés ont des exercices en USD et en CAD, 13 en USD avec une devise
  manquante, et 463 n'ont aucun exercice en USD. Seules 30 clôtures CAD de 5
  sociétés tombent au milieu d'une série USD ;
- clés : `datadate` toujours en fin de mois, `fyr` égal au mois de `datadate`,
  `fyear` conforme à la règle Compustat (clôture de janvier à mai = exercice
  précédent), `gvkey × fyear` unique ;
- négatifs mis à manquant : 143 `sale`, 42 `che`, 0 `at` ;
- `seq_x` : 302 524 fois `seq`, 1 585 fois `ceq + pstk_x`, 6 612 fois
  `at − lt`, 24 523 fois manquant ;
- `be_x` : 297 865 valeurs positives (88,9 %), 12 856 mises à manquant car ≤ 0,
  24 523 manquantes faute de données ;
- identités comptables : `seq = ceq + pstk` à 1 % près sur 99,999 % des lignes ;
  `at = lt + seq` à 10 % près sur 98,1 % (l'écart est surtout l'intérêt
  minoritaire) ;
- 304 717 intervalles de 12 mois entre deux rapports, 1 063 plus courts et
  2 026 plus longs (changements d'exercice et trous) ;
- **contrôles du book equity** : un petit tableau calculé à la main (les trois
  sources de `seq_x`, ajustements manquants, valeurs négatives, frontière zéro)
  est testé à chaque exécution. `be_x` est aussi recalculé par une seconde
  écriture de la formule sur toutes les lignes, valeurs manquantes comprises ;
- contrôle ponctuel contre les rapports annuels publics : Apple 2020 (capitaux
  propres 65 339, ventes 274 515, résultat net 57 411) et IBM 2019 (20 841,
  77 147, 9 431) concordent ;
- sociétés liées à l'étape 6 : 27 391 sur 28 147 ont au moins un exercice en
  USD, **à une date quelconque**, soit 98,75 % des mois-actions liés. Ce chiffre
  ne dit pas si un compte est disponible à la date de formation.

**Limites connues** :
- **Notre extrait est une fusion CCM** : il ne contient que les exercices dont
  la date de clôture tombe dans un lien CRSP. Les exercices clos avant la
  cotation manquent, même quand ils étaient publics (exemple vérifié par
  Astra : le prospectus de Google d'août 2004 contenait les bilans 2002 et
  2003, absents de l'extrait). Dans le cas usuel, une société nouvellement
  cotée attend son premier exercice complet plus 6 mois ; l'attente peut
  dépasser 18 mois. Mesure d'Astra : 250 708 mois-actions éligibles liés
  depuis 1963 précèdent le premier compte utilisable, soit **7,8 % en nombre
  et 1,2 % en capitalisation**. Ces titres gardent leurs rendements et leurs
  signaux de prix. Cela limite aussi le biais de remplissage rétroactif de
  Compustat.
- Les comptes Compustat sont dans leur état actuel (retraitements inclus) : les
  valeurs publiées à l'époque ne sont pas disponibles. Exemple : les ventes
  2009 d'Apple valent 42 905 dans la table, après un dépôt rectificatif de
  janvier 2010, contre 36 537 à la première annonce. C'est la pratique standard
  (JKP, TF) ; le délai de 6 mois couvre une partie des révisions, pas toutes.
- Sans `txdb` ni `itcb`, `txditc_x` manque sur 56 279 exercices, et compte
  alors pour zéro dans `be_x` (convention JKP).

**À transmettre aux étapes suivantes** (audit Astra) :
- étape 8 : rapporter la couverture des comptes **à la date de formation**,
  selon l'ancienneté du lien et selon les postes nécessaires à chaque signal
  (un bilan pour la value, deux exercices pour certaines mesures de qualité) ;
- étape 8 : trois mois-actions où un ancien exercice USD atteint 18 mois juste
  quand un exercice CAD plus récent atteint 6 mois (`gvkey` 002770, 005682,
  010120). À trancher avec la borne des 18 mois ;
- signaux : deux lignes successives ne sont pas toujours espacées de 12 mois
  (1 063 intervalles plus courts, 2 026 plus longs). Les signaux de croissance
  compareront des dates à 12 mois d'écart, comme JKP, et non des lignes
  voisines ;
- `sich` est daté avec son exercice s'il sert à un signal.

**Statut : étape 7 close le 2026-11-11** (audit Astra « VALIDÉ AVEC RÉSERVES »,
réserves traitées ; exécution `b3acac9ae9d4`).

### Étape 8 : disponibilité des données comptables

**Inspiration** : JKP (`create_acc_chars`, `lag_to_public`, `max_data_lag`).

- JKP considère une donnée publique 4 mois après `datadate` et la garde au plus
  18 mois. Le cours demande **6 mois**, et ce délai est retenu. Fenêtre : de la
  fin du mois `datadate + 6` jusqu'au premier des deux événements suivants, la
  publication de l'exercice suivant ou `datadate + 18` mois. **Décision D4.**
- **Mise à jour mensuelle**, comme JKP, plutôt qu'une seule fois en juin comme
  Fama-French dans TF. C'est cohérent avec un rebalancement mensuel et avec la
  consigne du cours : « using most up-to-date data is preferable ».
- Les ratios de valeur utilisent la capitalisation **du mois t** (JKP ; Asness et
  Frazzini, 2013). La comptabilité est jointe sur `(gvkey, mois de disponibilité)`
  via les liens de l'étape 6.

**Contrôle anti-look-ahead automatique** : pour toute ligne, la date de
disponibilité doit être inférieure ou égale à la date de formation. Toute
violation fait échouer le script.

**Implémentation : `scripts/data_cleaning/8_accounting_availability.py`** (2026-11-11, run
`e983304b3cfc`). Sorties :
- `acc_public.parquet` : pour chaque société et chaque mois, le rapport
  utilisable (`gvkey`, `public_date`, `datadate`), soit 4 048 344 lignes ;
- `crsp_panel_acc.parquet` : le panel de l'étape 5, plus `gvkey`,
  `acc_datadate` (date de clôture du rapport utilisable) et `acc_age_months`.
  Aucune ligne n'est retirée (jointures gauches) ;
- `accounting_availability_report.json`.

Les valeurs comptables restent dans `compustat_annual.parquet`. Elles seront
jointes sur `(gvkey, acc_datadate)` à l'étape des signaux.

- **Code repris** de JKP (`add_earnings_persistence_and_expand`, `expand`) :
  - début : fin du mois `datadate + 6 mois` ;
  - fin : le plus tôt entre le mois précédant le début du rapport suivant et la
    fin du mois `datadate + 18 mois` (bornes incluses) ;
  - une ligne par mois entre le début et la fin, puis jointure sur
    `(gvkey, eom)`.
- **Écarts avec JKP** :
  - délai de 6 mois (cours, D4) au lieu de 4 ;
  - le « rapport suivant » est le rapport suivant de la société **dans
    n'importe quelle devise**, lu dans le fichier brut. Un rapport plus récent
    remplace l'ancien même si ses valeurs sont inutilisables (non USD) : il n'y
    a alors aucun compte disponible. Cela règle les trois cas limites signalés
    à l'audit de l'étape 7 ;
  - JKP garde la première ligne en cas de doublon `(gvkey, public_date)` ; ici
    un doublon arrête le script.
- **Exemple** : un exercice clos le 31 décembre 2019 est utilisable de la
  formation de fin juin 2020 (rendements de juillet 2020) à celle de fin mai
  2021, puis l'exercice 2020 le remplace.

**Résultats des contrôles** :
- **test d'anticipation** : sur les 3 710 004 lignes avec comptes, le rapport
  est toujours public à la date de formation. L'âge du rapport va de 6 à 18
  mois (18 mois : 1 318 lignes éligibles, quand le rapport suivant tarde) ;
- **seconde route** : pour chaque ligne liée (4 125 224), on cherche le dernier
  rapport public de la société, toutes devises confondues. Il doit être le
  rapport retenu s'il est en USD et a au plus 18 mois ; sinon rien n'est
  attendu. Zéro écart ;
- **test de troncature** : on cache tous les rapports qui ne sont pas encore
  publics à une date T, on reconstruit, et le passé doit rester identique. Zéro
  écart à 1975-06, 1999-12 et 2015-03 ;
- **tests négatifs** : un délai de 5 mois au lieu de 6 est détecté (323 608
  lignes), de même que l'utilisation du rapport suivant à la place du rapport
  courant (296 024 lignes) ;
- cohérence des exécutions : les liens ont été construits sur ce panel, et les
  comptes sur ces liens (identifiants d'exécution vérifiés) ;
- 58 116 lignes liées n'ont rien d'utilisable car le dernier rapport public
  n'est pas en USD.

**Couverture à la date de formation** (mois-actions éligibles depuis 1963) :

| Mesure | En nombre | En capitalisation |
|---|---|---|
| Lien Compustat | 93,3 % | 98,1 % |
| Rapport utilisable | 85,5 % | 96,8 % |
| Actif total connu | 84,2 % | 96,8 % |
| Book equity connu | 81,3 % | 94,3 % |
| Deux exercices (courant et 12 mois avant) | 77,6 % | 95,3 % |

- book equity par décennie, en capitalisation : 88,3 % (1960), 94,3 % (1970),
  95,2 % (1980), 96,3 % (1990), 96,8 % (2000), 94,6 % (2010), 92,4 % (2020).
  Minimum mensuel : 77,6 % ;
- book equity par taille, en nombre : nano 74,3 %, micro 77,2 %, small 85,2 %,
  large 91,1 %, mega 95,2 % ;
- selon l'ancienneté du lien (titres liés), part ayant un rapport utilisable :
  1,8 % les 6 premiers mois, 53,2 % de 6 à 17 mois, 98,1 % de 18 à 35 mois,
  99,3 % ensuite. C'est l'effet de l'absence des comptes d'avant cotation.

**Corrections après l'audit Astra** (run `e983304b3cfc`, aucune valeur changée) :
- **cas de référence écrits à la main**, indépendants des constantes du script
  et testés à chaque exécution : clôture de décembre → première formation fin
  juin, remplacement par le rapport suivant, borne de 18 mois, rapport suivant
  tardif, rapport suivant en CAD. Un délai global de 5 mois ou un âge maximal de
  24 mois font échouer ce test ;
- l'âge du rapport est vérifié sur chaque ligne, et le `gvkey` de chaque ligne
  est comparé à la table de liens d'entrée, manquants compris ;
- le fichier brut relu pour le calendrier doit avoir l'empreinte enregistrée à
  l'étape 7 ;
- le compteur des lignes sans compte utilisable est détaillé : 57 957 dont le
  dernier rapport public est en CAD, 159 dont la devise est inconnue. Parmi
  elles, seules 28 auraient encore un ancien rapport USD utilisable sans la
  règle de remplacement, dont 3 éligibles depuis 1963.

**Limites** :
- les signaux comptables manquent pour les sociétés récemment cotées (voir
  l'étape 7). Le traitement des signaux manquants sera fixé à l'étape des
  signaux ;
- parmi les rapports retenus sur des lignes éligibles, 43 496 n'ont aucun poste
  renseigné : chaque signal doit vérifier ses propres entrées ;
- **retraitements et dépôts tardifs (constat bloquant de l'audit Astra,
  décision D12)** : la date de disponibilité est déduite de la date de clôture.
  Notre export n'a ni date de dépôt ni historique des versions. Les valeurs sont
  celles d'aujourd'hui, donc un montant retraité après la formation peut entrer
  dans un signal. Exemple vérifié par Astra, Super Micro Computer (`gvkey`
  176567) : pour l'exercice clos en juin 2024, la table donne 5 417,2 M$ de
  capitaux propres, alors que le chiffre public en décembre 2024 était
  5 469,5 M$ (écart de 1 %) ; pour l'exercice 2017, les ventes de la table
  (2 484,9) viennent d'un retraitement de 2019, contre 2 529,9 annoncés à
  l'époque. Au moins 10 mois-actions éligibles sont touchés ; le total ne peut
  pas être mesuré avec nos données.
  - Cette limite est celle de Compustat standard, utilisé avec un délai fixe
    par JKP, Tidy Finance, Fama-French et la convention du cours. La corriger
    demande une base « point-in-time », que nous n'avons pas.
  - Elle ne touche que les signaux comptables (value, qualité). Les signaux de
    prix (momentum, volatilité) ne sont pas concernés.

**Statut : étape 8 close le 2026-11-11** (audit Astra « À CORRIGER » : constats
de contrôle corrigés, run `e983304b3cfc` ; constat bloquant traité par la
décision D12, validée par Danny, voir « Règle D12 » en fin de document).

### Étape 9 : agrégats du fichier quotidien (`crsp_daily_agg.parquet`)

**Inspiration** : JKP (`prepare_daily`, `roll_apply_daily`, `bidask_hl`).

**Périmètre réduit, validé par Danny le 2026-11-11 (décision D11)**, pour tenir
l'échéance du 13 novembre. On ne calcule que ce qui sert à un signal retenu ou
au modèle de coûts :
- **gardé** : volatilité sur 21 et 252 jours, bêta de marché sur 252 jours,
  volume en dollars sur 126 jours, spread coté (`DlyBid`, `DlyAsk`) ;
- **écarté** : rendement maximal sur 21 jours, illiquidité d'Amihud, part de
  jours sans transaction, estimateur de Corwin-Schultz. Un spread coté manquant
  est remplacé par la moyenne de la catégorie de taille, comme le prévoit le
  cours, et seulement dans le modèle de coûts.

La liste complète ci-dessous reste la référence si le temps le permet.

- Les lignes avec `DlyDelFlg = 'Y'` sont exclues (JKP). Le fichier de 22 Go est
  lu par blocs, une seule fois.
- Mesures par titre et par mois de fin de fenêtre, avec le **nombre minimal
  d'observations de JKP** :
  - volatilité sur 21 jours (au moins 15) et sur 252 jours (au moins 120) ;
  - rendement maximal sur 21 jours ;
  - bêta de marché sur 252 jours (au moins 120) ;
  - volume en dollars et part de jours sans transaction sur 126 jours (au moins
    60) ;
  - illiquidité d'Amihud sur 126 jours.
- **Spreads** :
  - spread coté à partir de `DlyBid` et `DlyAsk` quand ils existent ;
  - sinon l'estimateur haut-bas de Corwin-Schultz, comme JKP (`bidaskhl_21d`, au
    moins 10 jours). Les jours où le prix est une moyenne bid/ask
    (`DlyPrcFlg = 'BA'`) sont exclus de ce calcul.
  - Le cours remplace les spreads manquants par la moyenne de la catégorie de
    taille ; cette imputation ne sert **qu'au modèle de coûts**, pas aux signaux.

**Implémentation : `scripts/data_cleaning/9_crsp_daily_agg.py`** (2026-11-11, run
`f7a7e36567cf`, périmètre réduit D11 plus l'estimateur haut-bas). Sorties :
- `crsp_daily_min.parquet` : les colonnes quotidiennes utilisées (table
  intermédiaire, 102 millions de lignes) ;
- `crsp_daily_agg.parquet` : une ligne par mois-action (4 891 218), clé
  `(permno, yyyymm)`, avec `rvol_21d`, `rvol_252d`, `beta_252d`, `dolvol_21d`,
  `dolvol_126d`, `spread_quoted_21d`, `bidaskhl_21d` et les nombres
  d'observations ;
- `crsp_daily_agg_report.json`.

- **Code repris de JKP** :
  - les fenêtres « 21, 126 et 252 jours » sont **1, 6 et 12 mois civils** se
    terminant à la fin du mois (`gen_aux_windows`) ;
  - nombre minimal d'observations : 15, 60 et 120 ;
  - `rvol` = écart-type de `ret_exc` ; `beta` = cov(`ret_exc`, marché) /
    var(marché) ; `dolvol` = moyenne du volume quotidien en dollars ;
  - garde-fous : pas de valeur si les rendements bruts sont quasi constants
    (écart-type ≤ 1e-6) ou nuls 90 % du temps ou plus ;
  - lignes `DlyDelFlg = 'Y'` exclues ; rendement après un trou de plus de 14
    jours non utilisé ; jours sans rendement de marché exclus ;
  - ajustement Gao-Ritter du volume NASDAQ (fonction de l'étape 3).
- **Écarts** :
  - marché et taux sans risque quotidiens de Ken French (JKP construit son
    propre marché et utilise `t30ret / 21`) ;
  - les fenêtres sont calculées à partir de sommes mensuelles (nombre, somme,
    somme des carrés, produits croisés), en une seule passe ;
  - spread coté `(ask − bid) / milieu`, moyenne mensuelle sur au moins 10 jours
    de cotation valide (`ask > bid > 0`, spread ≤ 50 % du milieu). Il s'ajoute à
    l'estimateur haut-bas de JKP ;
  - une valeur n'existe que pour un mois où le titre a des lignes quotidiennes.
- **Disponibilité** : les données du mois t servent à la formation de fin t.

**Résultats des contrôles** :
- fichier quotidien : taille conforme au manifeste, empreinte identique à celle
  de l'étape 1, en-tête exact. 102 059 931 lignes pour 40 058 titres ; 31 620
  doublons exacts retirés, aucun doublon contradictoire ; 29 362 lignes de
  radiation exclues ; aucun trou de plus de 14 jours ; 100 lignes sans place de
  cotation connue (volume en dollars manquant) ;
- **seconde route** : sur 101 titres, chaque statistique est recalculée
  directement sur les lignes quotidiennes de chaque fenêtre. Écart relatif
  maximal de 1e-13, aucune différence de valeurs manquantes ;
- **contrôle indépendant du fichier quotidien** : les rendements quotidiens
  composés sur le mois égalent le rendement mensuel CRSP à 0,0001 près sur
  99,99998 % des 4 672 805 mois comparés (corrélation 1,0000) ;
- bêta moyen du marché pondéré par la capitalisation : 1,01 (de 0,79 à 1,14) ;
- **couverture des éligibles depuis 1963**, en capitalisation : volatilité sur
  12 mois et bêta 99,3 %, volume en dollars sur 6 mois 99,6 %, spread coté
  94,0 % ;
- médianes : volatilité quotidienne 2,6 % (1 mois) et 2,9 % (12 mois), bêta
  0,73, spread coté 1,9 %. Spread médian par taille : mega 0,06 %, large
  0,13 %, small 0,58 %, micro 2,8 %, nano 8,5 %.

**Estimateur haut-bas (`bidaskhl_21d`), ajouté le 2026-11-11 avec l'accord de
Danny.** Le spread coté n'existe presque pas avant les années 1990 (couverture
en capitalisation : 0,3 % en 1960, 7,5 % en 1970, 12,6 % en 1980, 85,9 % en
1990). L'imputation par la catégorie de taille ne peut pas suffire sur ces
années. On reprend donc l'estimateur de Corwin et Schultz (2012) tel que JKP
le code (`bidask_hl`, `impute_high_low`, `adjust_overnight_returns`,
`compute_bidask_spread`, copiés) : spread tiré des cours haut et bas du jour et
de la veille, valeurs négatives mises à zéro, moyenne mensuelle sur plus de 10
jours.
- couverture en capitalisation : 99,9 % (1960), 92,7 % (1970), 96,5 % (1980),
  puis plus de 99,8 %. L'un ou l'autre des deux spreads : au moins 99,9 % à
  chaque décennie, 99,2 % des mois-actions éligibles en nombre ;
- sur les 2 183 967 mois-actions qui ont les deux mesures, la corrélation de
  rang mensuelle moyenne est de 0,71 et les médianes sont proches (1,30 % coté,
  1,25 % haut-bas) ;
- **mais l'estimateur haut-bas écrase les écarts entre tailles** : médiane de
  0,50 % pour les mega (0,06 % coté) et de 2,8 % pour les nano (8,5 % coté). Il
  surestime le coût des grandes capitalisations et sous-estime celui des
  petites. La façon de combiner les deux mesures (par exemple le spread coté
  quand il existe, sinon le haut-bas) est une **décision du modèle de coûts**, à
  fixer avant le backtest.

**Statut : implémentée, en attente de l'audit Astra.**

### Étape 10 : traitement des valeurs extrêmes

- **Pas de winsorisation** des rendements de portefeuille.
- JKP ne winsorise les rendements à 0,1 % et 99,9 % que pour les régressions de
  facteurs ; ce choix sera décidé à l'étape des alphas.
- Les caractéristiques seront transformées en rangs à l'étape des signaux, ce qui
  neutralise les valeurs extrêmes sans les supprimer.

**Statut : étape 10 close le 2026-11-11.** Aucun code : rien n'est supprimé ni
écrêté dans les données nettoyées. Les deux choix ci-dessus seront appliqués
aux étapes des signaux et des alphas.

### Dictionnaire de données (`resources/data_dictionary.csv`)

Prévu par `ProjectWorkflow.md`. Une ligne par colonne des sept tables
nettoyées (144 colonnes) : signification, unité, source, disponibilité et
rôle(s).

- **Disponibilité** : `key` (clé), `t` (connu à la fin du mois t), `interval`
  (intervalle de validité), `acc_6m` (rapport annuel utilisable 6 mois après la
  clôture), `t+1` (connu après le mois de détention), `after_t` (peut être daté
  après t), `today` (valeur d'aujourd'hui).
- **Rôles** : `identifier`, `universe`, `predictor`, `outcome`, `benchmark`,
  `execution_cost`, `weight`, `audit`. Une colonne peut en avoir plusieurs.
- **`scripts/data_cleaning/check_data_dictionary.py`** arrête tout si une colonne d'une table
  manque au dictionnaire, si le dictionnaire cite une colonne inexistante, ou
  si un rôle est incompatible avec la disponibilité :
  - un rôle de décision (`universe`, `predictor`, `execution_cost`, `weight`)
    exige une disponibilité `key`, `t`, `interval` ou `acc_6m` ;
  - `t+1` et le rôle `outcome` vont toujours ensemble, sans autre rôle.
- Colonnes à ne jamais utiliser comme entrée : `hdr_cusip` (`today`),
  `delamtdt` et `delnextdt` (`after_t`), et les trois colonnes `t+1`
  (`ret_lead1`, `ret_lead1_status`, `ret_exc_lead1`).
- Tables couvertes : `crsp_panel_acc`, `crsp_daily_agg`, `compustat_annual`,
  `ff_factors_monthly`, `acc_public`, `ccm_links`, `nyse_cutoffs`.

## Ce que nous ne reprenons pas de JKP

- La couche internationale (rendements de titres Compustat, conversion des
  devises, classification par pays).
- Le Compustat trimestriel et la combinaison annuel/trimestriel : nous n'avons que
  l'annuel.
- La classification GICS : nous ne l'avons pas, donc on utilise le SIC et les 49
  industries de Fama-French.
- La série `t30ret` de CRSP, remplacée par le taux sans risque de Ken French.

## Décisions à valider

| ID | Décision proposée | Alternative |
|---|---|---|
| D1 | `usincflg = 'Y'` (TF) | Pas de filtre (JKP) |
| D2 | Pas de `conditionaltype` : substitut `tradingstatusflg = 'A'` et `primaryexch ∈ {N, A, Q}`, limite documentée | Réexporter depuis WRDS |
| D3 | −30 % pour une radiation liée à la performance sans rendement (JKP, Shumway). Avis d'audit : accepter, avec un test de sensibilité au backtest à −55 % pour le Nasdaq (Shumway et Warther, 1999 ; 2 094 cas concernés) | Aucune imputation (TF) |
| D4 | Disponibilité à 6 mois, durée de validité maximale de 18 mois, mise à jour mensuelle | 4 mois (JKP) ou juin uniquement (FF/TF) |
| D5 | Liens LC/LU et P/C (TF) | LC/LU/LS sans LINKPRIM (JKP) |
| D6 | Compustat en USD uniquement | Conversion des devises (JKP) |
| D7 | **Validée** : toutes les tailles sont gardées, et un groupe n'est exclu ensuite que selon une règle fondée sur les coûts et la capacité, fixée à l'avance | Exclure d'office sous le 20e centile NYSE (Fama-French) ou seulement les nano (JKP) |
| D8 | Industries : 49 industries FF pour les données, regroupement plus grossier pour la neutralisation, à fixer à l'étape des signaux | Divisions SIC (TF) |
| D9 | Ajouter une ligne le mois de radiation quand CRSP n'en a pas (274 cas). Son rendement = rendements quotidiens jusqu'à la radiation, composés avec `delret`. Avis d'audit : conserver | Perdre ces rendements de radiation (JKP) |
| D10 | Pas de remplissage par 0 : si une partie du rendement de détention est inconnue, `ret` est manquant et `ret_status` dit pourquoi | `ret = 0` et `delret = 0` (JKP) |
| D11 | **Validée** : étape 9 réduite à la volatilité (21 et 252 jours), au bêta (252 jours), au volume en dollars et au spread coté | Liste complète de JKP |
| D12 | **Validée par Danny le 2026-11-11** : garder les signaux comptables malgré la limite des retraitements Compustat (valeurs actuelles, délai fixe de 6 mois), sans affirmer que le biais est faible. Règle détaillée sous le tableau | Obtenir une base point-in-time ou les dates de dépôt (réexport WRDS), ou renoncer aux signaux comptables |

### Règle D12 : signaux comptables et retraitements

Le biais ne peut pas être mesuré avec nos données. On ne dit donc jamais qu'il
est négligeable. On montre que la conclusion n'en dépend pas, ou on dit qu'elle
en dépend.

- Le backtest présente **deux versions** de la stratégie, fixées à l'avance :
  - **version A** : signaux de prix seuls (momentum, volatilité), non exposés
    au biais ;
  - **version B** : signaux de prix et signaux comptables (value, qualité),
    exposés au biais.
- Les deux versions passent les mêmes tests (alphas et tests t sur les modèles
  de facteurs, coûts inclus).
- Lecture des résultats :
  - si la version A a un alpha significatif, la conclusion tient sans signal
    comptable. L'écart entre B et A est la contribution des signaux comptables,
    présentée comme un **maximum**, car une partie peut venir du biais ;
  - si l'alpha n'apparaît qu'avec la version B, le rapport dit que le résultat
    repose sur des signaux exposés à un biais non mesurable.
- Compléments : un test avec un délai de 12 mois au lieu de 6 pour les signaux
  comptables (dépôts tardifs), et une référence académique vérifiée sur l'écart
  entre données retraitées et données d'époque, à chercher à la rédaction.
- La limite est déclarée dans le rapport, avec l'exemple de Super Micro
  Computer.

## Ordre d'implémentation

1. Étapes 1 et 2.
2. Étapes 3 et 4.
3. Étape 5, quand le taux sans risque est téléchargé.
4. Étapes 6, 7 et 8.
5. Étape 9.

Chaque étape se termine par son rapport de contrôle et un paquet d'audit pour
ChatGPT avant de passer à la suivante.
