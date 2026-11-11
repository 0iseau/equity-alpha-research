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

Script `scripts/crsp_monthly.py`, version 2, corrigée après l'audit Astra du
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

**Implémentation : `scripts/crsp_universe.py`** (2026-11-11). Sorties :
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

**Implémentation : `scripts/crsp_size.py`** (2026-11-11). Sorties :
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
bloquant `me_cap` corrigé ; exécution `5f371b20c0f4`).

### Étape 5 : rendements excédentaires

**Inspiration** : TF.

- `ret_exc = ret − rf`, où `ret` est le rendement total validé des étapes 1 et 2
  et non `MthRet`. Le taux `rf` est tiré de la Ken French Data Library
  (téléchargée à ce moment-là). JKP utilise `t30ret` de CRSP, que nous n'avons
  pas.
- Le rendement excédentaire du mois suivant `ret_exc_lead1m` n'est calculé que si
  le mois suivant existe dans le panel, ou s'il s'agit du mois de radiation.

### Étape 6 : liens CRSP-Compustat (`ccm_links.parquet`)

**Inspiration** : TF *(à reconfirmer)*, plus prudent que JKP.

- `LINKTYPE ∈ {LC, LU}` et `LINKPRIM ∈ {P, C}` (TF). JKP ajoute `LS` et n'utilise
  pas `LINKPRIM`. Le relevé JKP signale lui-même un risque de liens en double
  non déterministes. **Décision D5.**
- `LINKENDDT = 'E'` est traité comme +∞ ; la date est valide si
  `LINKDT ≤ date ≤ LINKENDDT`.

**Contrôles** : **zéro doublon** `(PERMNO, date)` ni `(gvkey, date)` après
filtrage. Dans le cas contraire, le script échoue.

### Étape 7 : données comptables annuelles (`compustat_annual.parquet`)

**Inspiration** : JKP (`standardized_accounting_data`, `add_helper_vars`) et TF.

- Filtres déjà vérifiés : `INDL`, `STD`, `C`, `D`. On garde **`curcd = 'USD'`**
  (TF). JKP convertit les devises, ce qui serait inutile ici. **Décision D6.**
- **Déduplication** : la table est d'abord ramenée au niveau `gvkey × datadate`
  en retirant `LPERMNO`, après vérification que les champs comptables sont
  identiques. On garde ensuite le dernier `datadate` par `gvkey × fyear` (TF).
  Tout conflit fait échouer le script.
- **Book equity**, identique chez JKP et TF :
  `be = coalesce(seq, ceq + pstk_x, at − lt) + coalesce(txditc, 0) − coalesce(pstk_x, 0)`,
  avec `pstk_x = coalesce(pstkrv, pstkl, pstk)`, et `be` mis à manquant s'il est
  ≤ 0. Notre extrait n'a ni `txdb` ni `itcb`, donc on utilise directement
  `txditc`.
- Les autres variables auxiliaires (ROE, croissance des actifs, accruals, etc.)
  sont définies à l'étape des signaux, en reprenant les formules JKP.

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

### Étape 9 : agrégats du fichier quotidien (`crsp_daily_agg.parquet`)

**Inspiration** : JKP (`prepare_daily`, `roll_apply_daily`, `bidask_hl`).

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

### Étape 10 : traitement des valeurs extrêmes

- **Pas de winsorisation** des rendements de portefeuille.
- JKP ne winsorise les rendements à 0,1 % et 99,9 % que pour les régressions de
  facteurs ; ce choix sera décidé à l'étape des alphas.
- Les caractéristiques seront transformées en rangs à l'étape des signaux, ce qui
  neutralise les valeurs extrêmes sans les supprimer.

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

## Ordre d'implémentation

1. Étapes 1 et 2.
2. Étapes 3 et 4.
3. Étape 5, quand le taux sans risque est téléchargé.
4. Étapes 6, 7 et 8.
5. Étape 9.

Chaque étape se termine par son rapport de contrôle et un paquet d'audit pour
ChatGPT avant de passer à la suivante.
