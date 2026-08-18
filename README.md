# ebay-analytics (4DPrint) — Phase 1

Système de collecte hebdomadaire des statistiques eBay (trafic, contenu des
annonces, commandes) pour 4DPrint, avec journal des modifications comme
livrable central. Cette phase 1 couvre : schéma + migrations, OAuth eBay avec
refresh persisté en base, job de collecte hebdomadaire, `/health` et alerting
abstrait. La revue/édition des annonces, le moteur de proposition et
l'application des corrections (`ReviseItem`) sont hors périmètre — le schéma
les anticipe (`change_proposals`, `change_log`).

## Prérequis

- Docker + Docker Compose
- Une application créée sur [developer.ebay.com](https://developer.ebay.com) (voir plus bas)

## Démarrage local

```bash
cp .env.example .env
# renseigner EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_RU_NAME, EBAY_OAUTH_REDIRECT_URI
docker compose up
```

Le service `app` attend que Postgres soit prêt, applique les migrations
Alembic (`alembic upgrade head`) puis démarre FastAPI sur `http://localhost:8000`.

Vérifier :

```bash
curl http://localhost:8000/health
```

## Créer l'application eBay Developer

1. Créer un compte sur [developer.ebay.com](https://developer.ebay.com/) et une application (Production **et** Sandbox recommandé pour tester avant).
2. Dans **Application Keys**, récupérer `App ID (Client ID)` et `Cert ID (Client Secret)`.
3. Dans **User Tokens > Get a Token from eBay via Your Application**, configurer :
   - **Your auth accepted URL** / **Your auth declined URL** : pages de votre choix.
   - **Your auth privacy policy URL** : obligatoire, doit être une page publique HTTPS.
   - Le **RuName** généré est à mettre dans `EBAY_RU_NAME`. Ce n'est **pas** une URL — c'est un identifiant eBay qui redirige en interne vers l'URL de callback réelle que vous déclarez dans les paramètres du RuName (`EBAY_OAUTH_REDIRECT_URI`, doit être HTTPS et exposée sur le domaine Coolify, ex. `https://ebay-analytics.4dprint.example/oauth/callback`).
4. Scopes à accepter lors du consentement (déjà codés dans `app/ebay/oauth.py`) :
   - `sell.analytics.readonly`
   - `sell.fulfillment`
   - `sell.finances`
   - `api_scope` (scope de base, utilisé pour la Trading API via token OAuth)

## Parcours OAuth

1. Ouvrir `GET /oauth/login` dans un navigateur (redirige vers le consentement eBay).
2. Après acceptation, eBay redirige vers `EBAY_OAUTH_REDIRECT_URI` avec un paramètre `code`, géré par `GET /oauth/callback`.
3. Le refresh token est alors persisté dans la table `oauth_tokens` (une seule ligne, id=1). **Le refresh token n'est jamais stocké en variable d'environnement** : une variable Coolify ne se met pas à jour automatiquement, donc le seul état durable est la base.
4. Les appels API suivants rafraîchissent automatiquement l'access token 5 minutes avant expiration (`app/ebay/oauth.get_valid_access_token`), avec réécriture en base à chaque refresh.

## Job de collecte hebdomadaire

```bash
docker exec <nom_du_conteneur_app> python -m app.jobs.weekly
```

- Idempotent : rejouable sur la même semaine (clé `collection_runs(run_type, period_start)`, période = semaine ISO Europe/Paris) sans créer de doublons — les collecteurs font des upserts (`ON CONFLICT DO UPDATE` / `DO NOTHING`) sur les contraintes d'unicité des tables de snapshot.
- Collecte : contenu des annonces (Trading API `GetSellerList` + `GetItem`), trafic 7j/28j (Sell Analytics `getTrafficReport`), commandes (Sell Fulfillment `getOrders`) + commissions (Sell Finances `getTransactions`).
- En cas d'échec (OAuth ou API), le run est marqué `failed` et une alerte est émise via l'interface `Alerter` (phase 1 : log structuré uniquement — brancher un canal réel plus tard sans changer les appelants).

### Déploiement Coolify — Scheduled Task

Le conteneur `app` tourne en continu (service FastAPI). La collecte hebdomadaire
est déclenchée par une **Scheduled Task Coolify** qui exécute une commande
*dans* ce conteneur déjà démarré — ce n'est **pas** un service séparé qui se
lance et se termine seul :

```bash
docker exec <container_app> python -m app.jobs.weekly
```

Fréquence recommandée : une fois par semaine (ex. lundi 06:00 Europe/Paris).

## Variables d'environnement

| Variable | Description |
|---|---|
| `DATABASE_URL` | URL SQLAlchemy Postgres (`postgresql+psycopg://...`) — ressource Coolify séparée en prod |
| `EBAY_ENV` | `production` ou `sandbox` |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | Clés de l'application eBay Developer |
| `EBAY_RU_NAME` | RuName déclaré côté eBay Developer |
| `EBAY_OAUTH_REDIRECT_URI` | URL HTTPS publique du callback (documentaire ; la vraie redirection eBay suit la config du RuName) |
| `EBAY_TRADING_SITE_ID` | Site ID Trading API (71 = France) |
| `EBAY_TRADING_COMPATIBILITY_LEVEL` | Compatibility level Trading API |
| `EBAY_MARKETPLACE_ID` | `EBAY_FR` |
| `ALERTING_BACKEND` | `log` en phase 1 |
| `APP_TIMEZONE` | `Europe/Paris` |
| `LOG_LEVEL` | `INFO` par défaut |

Aucun secret ne doit être commité dans le repo ni écrit dans les logs — en
Coolify, ces variables sont définies comme variables d'environnement du
service (sauf le refresh token, qui vit exclusivement en base).

## Déploiement Coolify

1. Créer une ressource Postgres séparée sur Coolify, récupérer son `DATABASE_URL` interne.
2. Créer une application Coolify de type **Dockerfile** (pas Nixpacks) pointant sur ce repo.
3. Configurer les variables d'environnement (section ci-dessus) dans l'app Coolify.
4. Exposer le domaine HTTPS de l'app et déclarer `https://<domaine>/oauth/callback` comme URL de redirection du RuName côté eBay Developer.
5. Au premier déploiement, effectuer le parcours OAuth (`/oauth/login`) une fois depuis un navigateur pour peupler `oauth_tokens`.
6. Créer une Scheduled Task Coolify sur l'app : commande `python -m app.jobs.weekly`, fréquence hebdomadaire.
7. Configurer un check de santé Coolify sur `GET /health` (déjà utilisé par le `HEALTHCHECK` du Dockerfile).

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Couvre : parsing des réponses eBay (Trading API XML, Analytics JSON), logique
de refresh de token OAuth, règles de cooldown (14 jours) et de débit (3
modifications/semaine max).

## Écarts identifiés entre le brief et la doc officielle eBay

- `getOrders` (Sell Fulfillment) ne fournit **pas** les commissions eBay
  (final value fee) — uniquement `pricingSummary` (prix, frais de port). Les
  commissions viennent de la **Sell Finances API** (`getTransactions`, scope
  `sell.finances`), ajoutée en phase 1 suite à validation.
- Le format `date_range` de `getTrafficReport` accepte bien la forme ISO 8601
  avec offset explicite utilisée ici ; la forme courte `YYYYMMDD..YYYYMMDD`
  est implicitement en fuseau America/Los_Angeles (non utilisée).
