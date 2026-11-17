<h1 align="center">Styx</h1>
<p align="center">Retrouvez votre interface Hermes dans Tor Browser.<br>Une adresse onion, un mot de passe. Aucun port ouvert sur le réseau local.</p>

<p align="center"><img src="docs/login.png" width="100%" alt="Page de connexion Styx : un champ de mot de passe sur une peinture mythologique, avec Cerbère au bord du Styx." /></p>

## Installation

Sur la machine qui héberge Hermes : **Linux** (noyau 5.3+), **Hermes ≥ 0.22.0**, Git et `tor` (`sudo apt install tor` ou `sudo pacman -S tor`). Pour vous connecter, utilisez [Tor Browser](https://www.torproject.org/).

```bash
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/plugins"
git clone https://github.com/CloudDown/styx.git "${HERMES_HOME:-$HOME/.hermes}/plugins/styx"
hermes plugins enable styx
```

## 1. Choisir un mot de passe

```bash
hermes styx passwd
```

Cerberus garde l'accès à l'interface. Choisissez une phrase de passe longue et unique.

## 2. Ouvrir le passage

```bash
hermes styx start
hermes styx url
```

Styx active la webapp et démarre ou redémarre la passerelle Hermes si nécessaire. Copiez l'adresse affichée **dans Tor Browser**, puis entrez votre mot de passe. Gardez la machine allumée ; Tor peut ajouter de la latence.

L'adresse reste la même après un arrêt et un redémarrage. Gardez-la privée, même si le mot de passe reste nécessaire pour entrer.

## 3. Fermer

```bash
hermes styx stop
```

Seuls Tor et Cerberus s'arrêtent. Hermes et ses bots continuent de fonctionner.

## Au quotidien

| Action | Commande |
|---|---|
| Vérifier l'état sur l'hôte | `hermes styx status` |
| Diagnostiquer un problème | `hermes styx doctor` |
| Changer le mot de passe | `hermes styx passwd` |
| Vérifier depuis le chat, sans afficher l'adresse | `/styx` |

L'onglet **Styx** du dashboard permet aussi de démarrer, arrêter et copier l'adresse. L'indicateur Desktop est facultatif, dans **Capabilities → Plugins**.

Pour exiger en plus une clé Tor par appareil, consultez le [guide](docs/GUIDE.md#clé-tor-par-appareil).

## Accès et confidentialité

Une session donne les droits de l'utilisateur système qui exécute Hermes, **y compris le shell, les fichiers et les clés**. Ne partagez l'accès qu'avec une personne à qui vous confieriez ce compte.

Hermes et Cerberus écoutent uniquement en local. Tor publie le point d'entrée ; aucun port n'est exposé sur le LAN. La page de connexion ne charge aucune ressource externe. Les tentatives de connexion sont limitées globalement.

Changer le mot de passe révoque les sessions : nouvelle connexion à la prochaine requête HTTP, fermeture des WebSockets sous une seconde. Ne définissez pas `webapp.public_url` avec l'adresse onion : Styx gère l'authentification.

Configuration, mises à jour et tests : [guide](docs/GUIDE.md) · [Licence MIT](LICENSE).
