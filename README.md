# 🏠 Logements Abidjan — annonces Facebook (via Google) + dashboard

Site statique qui agrège automatiquement les **annonces de location publiées sur les
pages et groupes Facebook publics** de Côte d'Ivoire (appartements 2-3 pièces,
70 000–150 000 F/mois, Cocody, Yopougon, Marcory, Koumassi, Treichville…).
Gratuit, sans serveur, **sans scraping de Facebook**.

## L'astuce (légale et durable)
Facebook interdit le scraping et bannit les comptes concernés. Mais Google **indexe**
les publications des pages/groupes Facebook publics. On interroge donc l'**API Google
Custom Search** (gratuite, 100 requêtes/jour) avec des requêtes ciblées, et on récupère
les annonces depuis les résultats. Aucun risque de bannissement.
> Limites honnêtes : seuls les contenus **publics** sont indexés (pas les groupes privés,
> ni les groupes **WhatsApp** qui sont chiffrés). L'indexation a un léger délai (souvent
> quelques heures). Ouvrir une annonce peut demander une connexion Facebook.

## Comment ça marche
- `collect.py` interroge Google → filtre (prix, pièces, zones) → écrit `data/listings.json`.
- `index.html` affiche les annonces (filtres zone / pièces / prix / meublé).
- GitHub Actions relance la collecte **4×/jour** (07h, 12h, 17h, 20h Abidjan).

## Étape A — Obtenir la clé Google (gratuit, 5 min)
1. **Clé API** : va sur https://console.cloud.google.com/ → crée un projet →
   menu *APIs & Services → Library* → cherche **Custom Search API** → *Enable* →
   *Credentials → Create credentials → API key* → copie la clé.
2. **Moteur de recherche (CX)** : va sur https://programmablesearchengine.google.com/ →
   *Add* → dans « Sites à rechercher » mets `facebook.com` → crée. Ouvre-le →
   *Setup* → copie l'**ID du moteur de recherche** (Search engine ID / cx).
   (Active aussi « Search the entire web » si proposé, en gardant facebook.com prioritaire.)

## Étape B — Déployer (gratuit, 5 min)
1. Crée un compte sur https://github.com (mot de passe fort + 2FA).
2. Nouveau dépôt **Public**, ex. `logements-abidjan`.
3. *Add file → Upload files* → glisse tout ce dossier (dont `.github`) → *Commit*.
4. *Settings → Secrets and variables → Actions → New repository secret* : crée
   **GOOGLE_API_KEY** (la clé) et **GOOGLE_CX** (l'ID du moteur).
5. *Settings → Actions → General → Workflow permissions* → **Read and write** → *Save*.
6. *Actions* → « Collecte annonces Abidjan » → **Run workflow** (premier remplissage).
7. *Settings → Pages* → *Deploy from a branch* → `main` / `/(root)` → *Save*.

Site en ligne : `https://TON-PSEUDO.github.io/logements-abidjan/`, mis à jour 4×/jour.

## Régler les critères
`config.json` : `loyer_min`, `loyer_max`, `pieces_cibles`, `zones_cibles`,
`fb_requetes` (les requêtes Google).

**Fraîcheur (gestion du temps)** :
- `fb_fenetre_jours` : fenêtre max en jours (défaut **7**). Le collecteur utilise
  `sort=date:r:…` côté Google pour ne ramener que les pages vues dans cette fenêtre,
  et lit la **date de publication** de chaque annonce (métadonnées ou date du résumé).
- `fb_fraicheur` : `d7` (7 j), `d1` (24 h), `d2`, etc. — second garde-fou.
- `exiger_date` : si `true`, **exclut** les annonces dont la date n'est pas exploitable
  (mode strict). Si `false` (défaut), elles sont gardées et marquées « date à confirmer ».

Sur le site, le sélecteur **« Moins de 24h / 7 derniers jours / Toutes dates »** filtre
l'affichage, et chaque carte montre **« il y a X j »** (vert si < 24 h).

> Note honnête : la date vient de ce que Google expose pour la page (date d'indexation /
> métadonnées), excellent indicateur de fraîcheur mais pas toujours la minute exacte de
> publication. La fenêtre 7 jours est fiable ; le « moins de 24h » dépend des données disponibles.

## Sources optionnelles
```
python collect.py --with-jiji            # ajoute Jiji
python collect.py --with-coinafrique     # ajoute CoinAfrique (pip install playwright; playwright install chromium)
python collect.py --no-facebook --with-jiji   # Jiji seul
```

## Tester (sans réseau)
```
python collect.py --test
```
