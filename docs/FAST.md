# Périmètre de Hermes Fast

Fast est une **copie compilée de la Webapp officielle**, réduite à ce que Fast proposait
déjà. Cette liste sert de référence pour les prochaines mises à jour.

## À conserver

- Sessions récentes : créer, ouvrir, renommer, supprimer et charger les suivantes.
- Historique paginé, lecture Markdown, retour en bas du fil.
- Envoi, réponse en direct et arrêt. Pas de file d’attente ni de pilotage en cours de réponse.
- Modèle et effort de raisonnement de la session, sans changer le modèle par défaut d’Hermes.
- Pièces jointes du navigateur (fichiers et images), dictée et conversation vocale.
- Apparence (système, claire ou sombre), reconnexion, déconnexion de Styx,
  lien vers le TUI et retour à la Webapp complète.
- Cerberus et autorisation native Hermes. Les comptes qui nécessitent une connexion Hermes
  supplémentaire continuent vers la version officielle.

## À retirer de Fast

- Navigation Bots, projets/worktrees, profils et connexions, messageries, tâches planifiées,
  artefacts, capacités et extensions ; leurs écrans, onglets et panneaux.
- Terminal intégré, arborescence de fichiers, aperçu de navigateur et revue Git. Le **mode
  TUI de Styx** reste séparé et accessible comme avant.
- Réglages avancés, installation, mises à jour, télémétrie d’interface et intégrations Desktop.
- Actions avancées sur les sessions, messages ou outils : duplication, archivage, épingles,
  éditeur de messages, panneaux d’outils et réponses aux approbations/secrets. Pour une demande
  interactive, Fast invite à rouvrir la session dans Hermes complet ; il n’approuve jamais à sa place.

Ces retraits concernent l’interface, pas les permissions ni les outils de l’agent sur le
serveur. Du code auxiliaire partagé peut rester nécessaire aux composants officiels.
La version `hermes` et le mode `tui` ne sont pas remplacés.
