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

Pour le premier lancement, utilisez `hermes styx setup` dans un terminal de l'hôte. La commande propose l'installation de Tor s'il manque, demande un mot de passe si aucun n'est enregistré, prépare la webapp puis démarre Styx. `hermes styx start` effectue les mêmes vérifications : il peut donc servir de première commande sans étape supplémentaire.

Avant l'installation, Styx affiche la commande et demande confirmation. Les mots de passe administrateur et les accords restent gérés par le gestionnaire de paquets, pas par Styx. Un refus ou un échec arrête le setup sans publier de service onion. Le plugin n'écrase jamais un mot de passe existant.

Ensuite, `autostart` peut préparer l'interface et attendre le listener de sa passerelle pendant son démarrage, mais ne redémarre jamais cette passerelle depuis l'intérieur. Le démarrage depuis la passerelle, le dashboard/API et les terminaux non interactifs ne propose aucune installation système : effectuez le setup sur l'hôte au préalable.

## Connexion automatique de l'onglet Hermes

La webapp privée d'Hermes demande une autorisation par onglet, en plus de l'accès au proxy. Une fois la session Cerberus validée, Styx obtient un lien à usage unique avec la commande publique `hermes webapp --no-open --skip-build`, sans afficher ni journaliser sa sortie. Le navigateur passe par la page de lancement officielle d'Hermes, qui échange ce lien contre l'autorisation native conservée dans le `sessionStorage` de l'onglet.

Styx ne lit pas de fichier de secret Hermes, ne désactive aucun contrôle d'authentification et ne modifie pas la webapp. Aucun lien n'est demandé pour une connexion Cerberus non authentifiée. Si un fournisseur de connexion Hermes supplémentaire a été configuré, son écran de connexion reste applicable.

Un nouvel onglet ou un rechargement reçoit son propre passage de lancement. Le paramètre temporaire `_styx_entry` peut apparaître dans l'adresse : il évite une boucle de redirections et n'est pas l'autorisation Hermes. Il est à usage unique, lié à la session Cerberus et expire après deux minutes. L'adresse affichée par `hermes styx url` reste inchangée et sans ce paramètre.

Les lancements sont limités en concurrence et en nombre de passages en attente. Les erreurs ou délais du lanceur donnent une réponse contrôlée plutôt qu'un accès non authentifié. `hermes styx start` remplace automatiquement un ancien gate qui ne gérait pas encore ce passage, sans redémarrer la passerelle ni supprimer l'identité onion.

## Chargement et performances

### Styx Fast (optionnel)

```bash
hermes styx webapp fast     # ouvrir le client léger par défaut
hermes styx webapp hermes   # revenir à la webapp officielle
hermes styx webapp status   # afficher le mode enregistré
```

Le choix est propre au profil et s'applique à la prochaine ouverture de l'adresse principale avec un gate à jour. `hermes` reste le défaut. Après mise à jour depuis une version sans Fast, redémarrez Styx (pas la passerelle) pour charger le nouveau code. Fast est disponible pour `target: webapp`, pas pour le dashboard.

Fast sert un document HTML léger, sans framework ni police externe. Il affiche les sessions récentes, charge l'historique par pages et utilise le WebSocket canonique d'Hermes pour créer ou reprendre des sessions, envoyer des messages et recevoir ou arrêter une réponse. Le sélecteur de modèles contacte Hermes uniquement à son ouverture ; le choix s'applique au prochain message. La configuration globale du modèle ne change pas. Les pièces jointes et enregistrements demandés par l'utilisateur sont transmis à la même instance Hermes. Depuis **Settings → Open full Hermes**, vous pouvez ouvrir l'interface officielle pour les outils, les approbations et les réglages avancés.

La page Cerberus ne change pas. Fast ne réutilise que l'autorisation native encore valide de l'onglet ; sinon il passe par le lancement officiel et l'échange à usage unique. Une installation qui exige une connexion Hermes supplémentaire ouvre l'interface officielle. Fast nécessite un Hermes dont le WebSocket prend en charge `hermes-gateway-v1` et les sessions GUI. Le service Hermes, ses données et ses fichiers ne sont pas modifiés.

### Priorité d'affichage

L'ordre visé est : structure et styles essentiels, connexion sécurisée et liste des sessions, conversation active et champ de message, puis historique ancien et outils avancés à la demande. C'est une priorité de parcours, pas une statistique d'usage ni une réécriture du Desktop.

Ce découpage fonctionnel n'est **pas encore implémenté** : plusieurs fonctions sont regroupées dans les mêmes fichiers Hermes. Styx ne réécrit pas sa webapp ni ses imports pour les séparer.

Un essai contrôlé dans Tor Browser, avec une instance de Styx et une adresse onion de diagnostic temporaires reliées au même backend Hermes, a comparé le chargement sans cache avec et sans indications HTTP de préchargement. L'essai JS a provoqué des téléchargements en double. L'essai limité aux styles a fait arriver le CSS principal plus tôt, mais n'a pas réduit le temps jusqu'à l'interface utilisable : environ 65 s sans priorité contre 81 s avec, puis 24 s au rechargement avec cache. Il s'agit d'un seul comparatif, sensible aux variations Tor, pas d'une preuve de régression causale ni d'une mesure de Pi. Le rechargement chaud n'avait pas de témoin chaud dans cette série.

Faute de gain global démontré, ces indications de préchargement ont été retirées, pas activées sur le Styx habituel. La compression et le cache natif déjà présents restent conservés. La prochaine piste est le découpage réel du démarrage Hermes autour des sessions et du chat, à étudier via une évolution compatible d'Hermes, sans modifier son authentification. Cerberus reste autonome, sans requêtes supplémentaires ni accès aux messages privés avant connexion.

- **Cerberus** conserve exactement la même peinture, le même formulaire et aucune ressource externe. Le formulaire précède désormais les données de l'image dans le HTML pour pouvoir s'afficher sans attendre la peinture complète. La page utilise gzip si le navigateur l'accepte, sans mise en cache du formulaire ni de son jeton CSRF.
- **Après le mot de passe**, Styx demande directement le passage natif Hermes : un aller-retour vers la racine est supprimé. Aucune autorisation n'est créée avant la vérification du mot de passe. Les nouveaux onglets et rechargements utilisent toujours le flux officiel.
- **Scripts et styles** : seuls les fichiers JS/CSS versionnés sous `/assets/`, explicitement publics et immuables côté Hermes, peuvent être compressés en streaming. La compression reste hors de la boucle réseau. Les réponses déjà encodées, les plages de téléchargement, `no-transform` et les réponses portant des cookies ne sont pas transformées.
- **Cache** : les directives natives d'Hermes sont conservées. Styx n'ajoute ni cache partagé ni stockage de données privées, de réponses API ou de tickets. Les pages natives d'authentification et les API restent transmises sans compression supplémentaire.

L'en-tête `Server-Timing: styx-launch;dur=…` sur les redirections de lancement donne le temps serveur du passage Hermes, sans divulguer son lien ou son ticket. Il aide à distinguer un lanceur lent du transfert des fichiers par Tor.

Ces optimisations réduisent le volume à transférer, mais ne garantissent pas une ouverture instantanée : le débit Tor, la puissance de l'hôte et le navigateur restent déterminants. Pour une installation déjà lancée, rechargez le code en redémarrant **Styx seulement** (`stop`, puis `start`, avec `--client-auth` si utilisé) ; il n'est pas nécessaire de redémarrer les bots.

## Linux, macOS et Windows

Hermes gère son installation et la construction de sa webapp ; le plugin reste responsable du lancement de Tor, des verrous, de l'identification de ses processus et des permissions de ses secrets.

- **Linux** : le setup utilise le gestionnaire de la distribution (apt-get, pacman, dnf/yum, zypper ou apk) et sudo/doas si nécessaire. Il ne lance pas de mise à niveau complète du système.
- **macOS** : le setup utilise Homebrew s'il est installé ; les emplacements Homebrew usuels sont détectés.
- **Windows natif** : le setup préfère `scoop install tor` pour installer le Tor Expert Bundle. Sinon, winget propose **Tor Browser**, qui inclut Tor, en conservant les étapes interactives et les accords de l'installateur. Cette installation plus large est annoncée avant confirmation. Styx retrouve l'exécutable réel de Scoop/Tor Browser sans réutiliser un shim qui injecte une autre configuration Tor.
- Pour une installation manuelle, ajoutez le répertoire de `tor` / `tor.exe` au `PATH` ou définissez `STYX_TOR_BINARY` sur le chemin complet de l'exécutable.
- Le dossier doit conserver le nom `styx`. Le manifeste déclare `psutil`, déjà fourni par les versions actuelles d'Hermes, pour la gestion portable des processus.
- Les secrets utilisent des permissions POSIX sur Linux/macOS et des ACL protégées utilisateur/SYSTEM sous Windows. Un système de fichiers Windows sans ACL privées n'est pas accepté ; `chmod` seul n'y protège pas les clés.

Styx délègue l'installation au gestionnaire existant ; il n'installe pas Homebrew/Scoop et n'exécute pas de script distant téléchargé. Les dépendances de construction restent gérées par Hermes et une erreur d'installation doit être corrigée sur l'hôte. Le mode optionnel `target: dashboard` exige toujours le démarrage séparé du dashboard.

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

`hermes styx url`, `start` et `status` peuvent afficher l'adresse sur l'hôte. `/styx` dans le chat n'affiche que l'état.

## Mise à jour

Pour une installation gérée par Hermes :

```bash
hermes plugins update styx
hermes styx stop
hermes styx start
```

Avec l'autorisation client Tor, utilisez `hermes styx start --client-auth`. Redémarrez **Styx seulement**, pas la passerelle Hermes. Les anciennes sessions devront se reconnecter.

Pour un ancien clone manuel sans suivi Hermes, `hermes plugins adopt styx` enregistre sa provenance avant les mises à jour. Un checkout de développement lié par symlink reste géré avec Git ; ne le réinstallez pas par-dessus pour tester une réorganisation.

## Fonctionnement

```text
Tor Browser
    ↓ service onion v3, port 80
127.0.0.1:9130  Cerberus : connexion et proxy
    ↓ Host et Origin réécrits vers le loopback
127.0.0.1:9120  Hermes webapp (port par défaut)
```

Tor utilise une instance dédiée avec `SocksPort 0` : ce n'est pas un proxy Tor général. Styx gère l'authentification sans définir `webapp.public_url` avec l'adresse onion.

Les logs de Tor passent par stdout/stderr, redirigés vers `logs/tor.log` par Styx. Contrairement aux chemins `DataDirectory` et `HiddenServiceDir`, la directive Tor `Log ... file` n'enlève pas les guillemets d'un nom de fichier ; la redirection évite ce problème, y compris avec des espaces dans le chemin. Si un processus quitte avant l'enregistrement de son PID, l'erreur indique son code de sortie et son fichier de log.

Les tentatives de connexion partagent un budget global de huit échecs ou vérifications en cours par fenêtre de quinze minutes. Les vérifications scrypt s'exécutent hors de la boucle événementielle, deux au maximum à la fois. Le corps d'une connexion est limité à 16 Kio et sa lecture à dix secondes.

Les uploads et réponses du proxy sont transmis en flux. Le proxy préserve la compression, les en-têtes `Set-Cookie` distincts et la négociation des sous-protocoles WebSocket.

Les opérations de démarrage et d'arrêt utilisent un verrou natif exclusif. Avant un signal, Styx vérifie le propriétaire, la commande, le profil et l'identité de naissance du processus. Linux utilise les pidfds quand ils sont disponibles ; macOS, Windows et les anciens noyaux Linux utilisent les opérations psutil gardées par la date de création du processus. Aucun PID nu n'est signalé. Les anciens fichiers PID entiers restent acceptés après vérification d'identité. Les chemins Tor sont quotés, y compris avec des espaces.

## Développement

Gardez le nom de dossier `styx` : les imports du plugin et le lancement de Cerberus en dépendent.

| Fichier | Rôle |
|---|---|
| `plugin.yaml`, `__init__.py` | Manifeste et enregistrement Hermes. |
| `gate.py` | Petit lanceur conservant la commande `python -m styx.gate` et l'identification des processus existants. |
| `backend/cli.py`, `backend/supervisor.py` | Commandes, démarrage et arrêt. |
| `backend/bootstrap.py` | Setup interactif et installation de Tor via le gestionnaire existant. |
| `backend/gate.py`, `backend/headers.py` | Connexion et proxy HTTP/WebSocket. |
| `backend/webapp_ensure.py`, `backend/webapp_handoff.py` | Préparation de la webapp et autorisation native Hermes, par onglet et après Cerberus. |
| `backend/login_page.py`, `assets/` | Page de connexion autonome. |
| `backend/passwords.py`, `backend/sessions.py` | Empreintes scrypt et cookies de session. |
| `backend/tor_supervisor.py`, `backend/client_auth.py` | Service onion et autorisation Tor. |
| `backend/platform_support.py`, `backend/storage.py`, `backend/network.py` | Primitives portables, fichiers privés et contrôle HTTP. |
| `backend/paths.py` | Racine du plugin et chemins des données durables, toujours hors du code. |
| `dashboard/`, `desktop/` | Intégrations visuelles Hermes. |

Le point d'entrée `__init__.py` ne fait que l'enregistrement auprès d'Hermes ; l'implémentation utilise des imports relatifs dans `backend/`. Aucun paquet Python supplémentaire ni installation `pip` du dépôt n'est nécessaire. Le manifeste et les surfaces `dashboard/` et `desktop/` restent aux emplacements attendus par Hermes.

Depuis la racine du dépôt, lancez les tests dans l'environnement Hermes :

```bash
hermes --run-module unittest discover -s "$PWD/tests" -v
hermes plugins validate "$PWD"
hermes plugins doctor "$PWD" --ci
```

Les tests utilisent des données temporaires et des serveurs HTTP/WebSocket locaux, jamais l'identité onion ni la passerelle en production. Les installations sont simulées. Si Tor est déjà installé, un test supplémentaire démarre le vrai binaire avec `DisableNetwork 1`, dans un répertoire temporaire avec des espaces ; il ne contacte pas le réseau Tor.

`.github/workflows/tests.yml` prépare l'exécution native sur Linux, macOS et Windows, avec Python 3.13 et 3.14, sans passerelle Hermes ni instance Tor réelle. Les tests couvrent notamment la compilation automatique, les réponses d'erreur HTTP, les processus, les verrous et les ACL Windows. Ajouter le workflow ne signifie pas que ces six jobs ont déjà été exécutés : les résultats natifs restent à vérifier en CI.
