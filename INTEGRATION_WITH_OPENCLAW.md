# Guide d'Intégration : AI Firewall avec OpenClaw

Bienvenue ! Ce guide explique étape par étape comment intégrer le module **AI Firewall** à votre application cliente **OpenClaw**. Ce module agit comme un proxy sécurisé entre OpenClaw et les fournisseurs d'IA (comme OpenAI ou Anthropic), en ajoutant de l'authentification, des contrôles budgétaires et un streaming transparent.

Ce guide est conçu pour être accessible à tous les niveaux : développeurs débutants, intermédiaires ou experts. Nous partons des bases et avançons pas à pas.

## Table des Matières
1. [Qu'est-ce que AI Firewall ?](#qu-est-ce-que-ai-firewall-)
2. [Prérequis](#prérequis)
3. [Installation et Configuration](#installation-et-configuration)
4. [Modification d'OpenClaw](#modification-d-openclaw)
5. [Test de l'Intégration](#test-de-lintégration)
6. [Dépannage](#dépannage)
7. [Fonctionnalités Avancées](#fonctionnalités-avancées)

## 1. Qu'est-ce que AI Firewall ?

AI Firewall est un **proxy reverse** écrit en Python avec FastAPI. Il :
- **S'interpose** entre votre client (OpenClaw) et le fournisseur d'IA.
- **Authentifie** les requêtes avec une clé API interne.
- **Contrôle le budget** : Limite les dépenses quotidiennes par utilisateur (ex. 5 $).
- **Gère le streaming** : Transmet les réponses en temps réel (Server-Sent Events) sans ajouter de latence.
- **Compte les tokens** : Calcule automatiquement les coûts après chaque requête (en arrière-plan).

**Avantages** :
- Sécurité : Protège vos clés API upstream.
- Économie : Évite les dépassements budgétaires.
- Transparence : Les appels API restent identiques, juste l'URL change.

## 2. Prérequis

Avant de commencer, assurez-vous d'avoir :
- **Docker** installé (version 20+ recommandée). [Guide d'installation](https://docs.docker.com/get-docker/).
- **Docker Compose** (inclus avec Docker Desktop).
- Un compte chez un fournisseur d'IA (ex. OpenRouter, OpenAI). Vous aurez besoin d'une clé API.
- **OpenClaw** : Votre application cliente qui appelle `/v1/chat/completions`.

Si vous n'avez pas Docker, vous pouvez installer Python 3.12+ et Redis localement, mais Docker est plus simple pour la production.

## 3. Installation et Configuration

### Étape 1 : Télécharger le Projet
Clonez ou téléchargez ce dépôt GitHub :
```bash
git clone https://github.com/votre-repo/ai-firewall.git
cd ai-firewall
```

### Étape 2 : Configurer les Variables d'Environnement
Le module utilise un fichier `.env` pour les configurations sensibles. Ne partagez jamais ce fichier !

1. Copiez le fichier exemple :
   ```bash
   cp .env.example .env
   ```

2. Ouvrez `.env` avec un éditeur de texte (ex. VS Code) et remplissez :
   - `INTERNAL_API_KEY` : Une clé secrète pour authentifier OpenClaw (ex. `ma-cle-secrete-123`).
   - `UPSTREAM_BASE_URL` : L'URL de votre fournisseur (ex. `https://openrouter.ai/api` ou `https://api.openai.com`).
   - `UPSTREAM_API_KEY` : Votre clé API du fournisseur (ex. `sk-or-v1-xxxxxx`).
   - `DAILY_BUDGET_LIMIT` : Limite budgétaire par jour (ex. `5.0` pour 5 $).
   - Laissez `REDIS_URL` par défaut si vous utilisez Docker.

   Exemple de `.env` :
   ```
   INTERNAL_API_KEY=ma-cle-secrete-123
   UPSTREAM_BASE_URL=https://openrouter.ai/api
   UPSTREAM_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxx
   DAILY_BUDGET_LIMIT=5.0
   ```

### Étape 3 : Lancer le Proxy
Avec Docker Compose (recommandé) :
```bash
docker compose up --build -d
```
- Cela construit l'image et lance deux services : `proxy` (port 8000) et `redis` (port 6379).
- Le proxy sera accessible sur `http://localhost:8000`.

Pour vérifier : Ouvrez `http://localhost:8000/health` dans un navigateur. Vous devriez voir `{"status": "ok"}`.

## 4. Modification d'OpenClaw

Maintenant, configurez OpenClaw pour utiliser le proxy au lieu de contacter directement le fournisseur.

### Changements Nécessaires
Dans le code d'OpenClaw (probablement dans un fichier comme `api_client.py` ou similaire) :
1. **Changez l'URL de base** : Remplacez l'URL du fournisseur par `http://localhost:8000` (ou l'IP de votre serveur).
2. **Ajoutez l'authentification** : Incluez le header `Authorization: Bearer <INTERNAL_API_KEY>` dans chaque requête.

### Exemple de Code (Python avec httpx ou requests)
Supposons qu'OpenClaw utilise `requests` pour appeler l'API :

**Avant (direct vers le fournisseur)** :
```python
import requests

response = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={
        "Authorization": "Bearer sk-or-v1-xxxxxx",
        "Content-Type": "application/json",
    },
    json={
        "model": "openai/gpt-4o-mini",
        "messages": [{"role": "user", "content": "Bonjour !"}],
        "stream": True,
    },
)
```

**Après (via AI Firewall)** :
```python
import requests

response = requests.post(
    "http://localhost:8000/v1/chat/completions",  # Nouveau URL !
    headers={
        "Authorization": "Bearer ma-cle-secrete-123",  # Nouvelle clé !
        "Content-Type": "application/json",
    },
    json={
        "model": "openai/gpt-4o-mini",
        "messages": [{"role": "user", "content": "Bonjour !"}],
        "stream": True,
    },
)
```

- Le reste du code (parsing de la réponse, gestion du streaming) reste identique !
- Pour le streaming, OpenClaw lira les chunks SSE comme avant.

### Si OpenClaw Utilise un SDK (ex. OpenAI SDK)
Si OpenClaw utilise le SDK officiel d'OpenAI :
```python
from openai import OpenAI

client = OpenAI(
    api_key="ma-cle-secrete-123",  # Clé interne
    base_url="http://localhost:8000",  # Proxy URL
)

response = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Bonjour !"}],
    stream=True,
)
```

- Le SDK gère automatiquement les headers.

## 5. Test de l'Intégration

### Test Simple (avec curl)
Testez le proxy directement :
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer ma-cle-secrete-123" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4o-mini",
    "stream": true,
    "messages": [{"role": "user", "content": "Hello, world!"}]
  }'
```
- Vous devriez voir les chunks SSE en streaming (ex. `data: {"choices": [...]}`).
- Si ça marche, intégrez à OpenClaw.

### Test avec OpenClaw
- Lancez OpenClaw et faites une requête.
- Vérifiez les logs du proxy : `docker compose logs proxy`.
- Surveillez le budget : `docker compose exec redis redis-cli GET budget:default:2026-02-18` (ajustez la date).

### Vérifications
- **Auth** : Sans le header `Authorization`, vous obtenez `401 Unauthorized`.
- **Budget** : Après quelques requêtes coûteuses, `402 Payment Required`.
- **Streaming** : Les réponses arrivent en temps réel.

## 6. Dépannage

### Problème : "Connection refused" ou "502 Bad Gateway"
- Vérifiez que Docker Compose est lancé : `docker compose ps`.
- Testez la santé : `curl http://localhost:8000/health`.
- Vérifiez `.env` : Clé API upstream valide ?

### Problème : "Invalid API key" (401)
- Vérifiez `INTERNAL_API_KEY` dans `.env` et dans les headers d'OpenClaw.

### Problème : "Daily budget exceeded" (402)
- Réinitialisez : `docker compose exec redis redis-cli DEL budget:default:2026-02-18`.
- Augmentez `DAILY_BUDGET_LIMIT` dans `.env`.

### Problème : Streaming lent ou bloqué
- Assurez-vous que `stream: true` dans la requête.
- Logs : `docker compose logs proxy` pour erreurs upstream.

### Logs Avancés
- Voir les logs en temps réel : `docker compose logs -f proxy`.
- Erreurs Redis : `docker compose logs redis`.

Si rien ne marche, ouvrez une issue sur GitHub avec vos logs.

## 7. Fonctionnalités Avancées

- **Multi-utilisateurs** : Étendez `verify_api_key()` pour mapper clés à users.
- **Métriques** : Ajoutez Prometheus pour monitoring.
- **Scalabilité** : Utilisez plusieurs workers Uvicorn ou Kubernetes.
- **Sécurité** : Ajoutez HTTPS avec Caddy ou Traefik.

Pour plus de détails, consultez le `README.md` du projet.

---

**Besoin d'aide ?** Posez des questions sur GitHub ou contactez l'auteur. Bonne intégration ! 🚀
