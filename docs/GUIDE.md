# Guide Styx

## Configuration

Les paramètres se trouvent dans `plugins.entries.styx.settings`, via le formulaire Desktop Plugins ou `hermes config`.

| Paramètre | Défaut | Rôle |
|---|---|---|
| `autostart` | `false` | Démarrer Tor et Cerberus au chargement du plugin. |
| `target` | `webapp` | Publier la webapp complète ou le `dashboard`. |
| `gate_port` | `9130` | Port local de Cerberus, vers lequel Tor redirige les connexions. |

La surface choisie doit écouter sur une adresse loopback. Styx refuse une adresse LAN ou publique sans modifier cette configuration. Utilisez `127.0.0.1` en cas de doute.

Le démarrage automatique ne redémarre jamais la passerelle Hermes depuis laquelle il s'exécute. Avec `target: dashboard`, démarrez le dashboard séparément avec `hermes dashboard --no-open`.

## Démarrage autonome de la webapp

À chaque `hermes styx start` avec la cible par défaut `webapp`, Styx appelle la commande publique `hermes webapp --build-only`. **Hermes** gère le cache de compilation, ses outils Node et les bundles livrés par un installateur ; Styx ne réimplémente pas ces opérations. Une interface absente ou périmée est reconstruite, sans ouvrir de navigateur ni afficher de lien de connexion temporaire.

Le démarrage vérifie ensuite la réponse HTTP réellement servie. Un port ouvert avec la page « The Webapp is not built » n'est plus considéré sain, y compris dans `doctor` et l'état du plugin. La compilation sur une passerelle déjà active ne la redémarre pas. Un échec ou un délai de compilation supérieur à quinze minutes donne une erreur et le chemin `logs/webapp-build.log`.

Pour le premier lancement, installez Tor, choisissez un mot de passe et lancez `start` une fois. Ensuite, `autostart` peut préparer l'interface et attendre le listener de sa passerelle pendant son démarrage, mais ne redémarre jamais cette passerelle depuis l'intérieur.

## Linux, macOS et Windows

Hermes gère son installation et la construction de sa webapp ; le plugin reste responsable du lancement de Tor, des verrous, de l'identification de ses processus et des permissions de ses secrets.

- **Linux** : installez `tor` avec votre gestionnaire de paquets.
- **macOS** : `brew install tor` ; les emplacements Homebrew usuels sont détectés.
- **Windows natif** : installez le **Tor Expert Bundle**, puis ajoutez le répertoire de `tor.exe` au `PATH`. Vous pouvez aussi définir `STYX_TOR_BINARY` sur le chemin complet de l'exécutable, sur les trois OS.
- Le dossier doit conserver le nom `styx`. Le manifeste déclare `psutil`, déjà fourni par les versions actuelles d'Hermes, pour la gestion portable des processus.
- Les secrets utilisent des permissions POSIX sur Linux/macOS et des ACL protégées utilisateur/SYSTEM sous Windows. Un système de fichiers Windows sans ACL privées n'est pas accepté ; `chmod` seul n'y protège pas les clés.

Styx ne télécharge pas Tor et n'installe pas de paquet système silencieusement. Les dépendances de construction restent gérées par Hermes et une erreur d'installation doit être corrigée sur l'hôte. Le mode optionnel `target: dashboard` exige toujours le démarrage séparé du dashboard.

## Clé Tor par appareil

Pour ajouter une autorisation Tor en plus du mot de passe :

```bash
hermes styx client-auth --name laptop
```

Importez la ligne privée affichée dans Tor Browser, via l'autorisation client onion, ou dans le `ClientOnionAuthDir` de votre client Tor. Ne la partagez pas et ne la copiez pas dans un chat.

```bash
hermes styx stop
hermes styx start --client-auth
```

Conservez `--client-auth` lors des démarrages manuels destinés à utiliser ce mode. Les fichiers d'autorisation restent dans le profil Tor ; Tor applique l'autorisation tant qu'ils sont présents.

## Données et adresse onion

Les données durables sont dans `$HERMES_HOME/plugin-data/styx/` (par défaut `~/.hermes/plugin-data/styx/`), jamais dans le répertoire du code :

- `hidden_service/` : identité onion et autorisations client ;
- `passwd` et `session.key` : empreinte du mot de passe et clé de session ;
- `tor/`, `state.json`, fichiers PID et `logs/` : état d'exécution.

L'arrêt conserve l'identité onion. Ne supprimez pas `hidden_service/` pour mettre à jour ou dépanner Styx : perdre ses clés change l'adresse. Protégez ce répertoire et ses sauvegardes comme des identifiants.

`hermes styx url`, `start`, `status` et `qr` peuvent afficher l'adresse sur l'hôte. `/styx` dans le chat n'affiche que l'état. Le QR ASCII nécessite le paquet facultatif `qrcode` dans l'environnement Hermes.

## Mise à jour

Depuis le répertoire où vous avez cloné Styx :

```bash
git pull --ff-only
hermes styx stop
hermes styx start
```

Avec l'autorisation client Tor, utilisez `hermes styx start --client-auth`. Redémarrez **Styx seulement**, pas la passerelle Hermes. Les anciennes sessions devront se reconnecter.

## Fonctionnement

```text
Tor Browser
    ↓ service onion v3, port 80
127.0.0.1:9130  Cerberus : connexion et proxy
    ↓ Host et Origin réécrits vers le loopback
127.0.0.1:9120  Hermes webapp (port par défaut)
```

Tor utilise une instance dédiée avec `SocksPort 0` : ce n'est pas un proxy Tor général. Styx gère l'authentification sans définir `webapp.public_url` avec l'adresse onion.

Les tentatives de connexion partagent un budget global de huit échecs ou vérifications en cours par fenêtre de quinze minutes. Les vérifications scrypt s'exécutent hors de la boucle événementielle, deux au maximum à la fois. Le corps d'une connexion est limité à 16 Kio et sa lecture à dix secondes.

Les uploads et réponses du proxy sont transmis en flux. Le proxy préserve la compression, les en-têtes `Set-Cookie` distincts et la négociation des sous-protocoles WebSocket.

Les opérations de démarrage et d'arrêt utilisent un verrou natif exclusif. Avant un signal, Styx vérifie le propriétaire, la commande, le profil et l'identité de naissance du processus. Linux utilise les pidfds quand ils sont disponibles ; macOS, Windows et les anciens noyaux Linux utilisent les opérations psutil gardées par la date de création du processus. Aucun PID nu n'est signalé. Les anciens fichiers PID entiers restent acceptés après vérification d'identité. Les chemins Tor sont quotés, y compris avec des espaces.

## Développement

Gardez le nom de dossier `styx` : les imports du plugin et le lancement de Cerberus en dépendent.

| Fichier | Rôle |
|---|---|
| `plugin.yaml`, `__init__.py` | Manifeste et enregistrement Hermes. |
| `cli.py`, `supervisor.py` | Commandes, démarrage et arrêt. |
| `gate.py`, `headers.py` | Connexion et proxy HTTP/WebSocket. |
| `login_page.py`, `assets/` | Page de connexion autonome. |
| `tor_supervisor.py`, `client_auth.py` | Service onion et autorisation Tor. |
| `platform_support.py`, `storage.py`, `network.py` | Primitives portables, fichiers privés et contrôle HTTP. |
| `dashboard/`, `desktop/` | Intégrations visuelles Hermes. |

Depuis la racine du dépôt, lancez les tests dans l'environnement Hermes :

```bash
hermes --run-module unittest discover -s "$PWD/tests" -v
hermes plugins validate "$PWD"
```

Les tests utilisent des données temporaires et des serveurs HTTP/WebSocket locaux, jamais l'identité onion ni la passerelle en production.

`.github/workflows/tests.yml` prépare l'exécution native sur Linux, macOS et Windows, avec Python 3.13 et 3.14, sans passerelle Hermes ni instance Tor réelle. Les tests couvrent notamment la compilation automatique, les réponses d'erreur HTTP, les processus, les verrous et les ACL Windows. Ajouter le workflow ne signifie pas que ces six jobs ont déjà été exécutés : les résultats natifs restent à vérifier en CI.
