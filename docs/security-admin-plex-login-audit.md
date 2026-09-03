# Audit de la connexion administrateur Plex

Date: 2026-08-29

## Perimetre

Flux examine: `POST /auth/plex/login`, callback Plex, verification du PIN et de
l'identite, preuve TOTP VODUM optionnelle, puis creation de la session admin.
Les flux de liaison, remplacement et decouverte ont ete examines pour confirmer
qu'un etat d'un autre usage ne peut pas etre reutilise pour se connecter.

## Protections confirmees

- Le demarrage est un POST couvert par le CSRF global et l'anti-bruteforce.
- Le PIN Plex fort et l'etat aleatoire sont crees cote serveur; l'etat est lie a
  la session, compare en temps constant, limite a dix minutes et consomme avant
  toute validation, y compris lors d'un echec.
- Le but du flux (`login`) est controle: un etat de liaison, remplacement ou
  decouverte ne peut pas devenir une connexion.
- Le callback recupere le jeton directement aupres de Plex avec des origines et
  timeouts bornes. Le jeton de connexion n'est ni journalise, ni place dans la
  session, ni persiste.
- L'identifiant stable retourne par Plex doit correspondre exactement a
  l'identite administrateur Plex encore active au moment du callback.
- Si le TOTP VODUM supplementaire est configure, aucune session admin n'est
  ouverte avant sa validation. La preuve intermediaire expire apres cinq minutes,
  est consommee avant controle et revalide l'identite active et la configuration.
- La creation du principal vide l'ancienne session, ce qui protege contre la
  fixation, puis marque la connexion de l'identite seulement apres succes.
- Les echecs utilisent des pages sans jeton ni detail de reponse Plex et alimentent
  les limites IP ainsi que des identifiants d'etat/identite haches.

## Findings

Aucune vulnerabilite exploitable supplementaire n'a ete confirmee dans ce flux.
Les comportements atypiques (callback GET et interrogation du PIN) font partie du
protocole Plex et restent proteges par l'etat de session a usage unique.

## Tests ajoutes

- consommation unique d'un flux valide;
- consommation immediate d'un etat incorrect avant rejet;
- rejet d'un flux expire et d'un flux reserve a un autre usage;
- expiration et consommation de la preuve TOTP Plex intermediaire sans ouverture
  de session administrateur.

Les audits generaux du TOTP, des cookies, de la duree de session et de la
deconnexion restent suivis separement dans le TODO.
