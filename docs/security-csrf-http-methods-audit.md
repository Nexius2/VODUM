# Audit global CSRF et methodes HTTP

Date: 2026-08-30

## Garde global existant

Le garde CSRF est enregistre par `create_app()` comme `before_request`, avant
l'enregistrement des modules de routes et blueprints. Son execution ne depend
donc pas de l'import d'une fonctionnalite particuliere et couvre les routes
administrateur, portail, setup et API.

Les methodes POST, PUT, PATCH et DELETE doivent presenter un jeton non vide qui
correspond en temps constant a `_csrf_token` dans la session signee :

- les formulaires utilisent le champ `_csrf_token` injecte dans les templates;
- les requetes JavaScript ou JSON utilisent `X-CSRF-Token`;
- un jeton absent, vide ou different produit HTTP 403 avant l'execution de la
  vue;
- les methodes de lecture ne demandent pas de jeton CSRF.

Le garde a ete extrait dans `core.csrf_security` pour permettre une regression
directe sans demarrer les taches, providers et acces DB de l'application. Deux
exemptions historiques pour `/health` et `/favicon.ico` ont ete retirees : elles
etaient inutiles pour leurs GET et auraient affaibli une future methode mutante
ajoutee par erreur sur ces chemins.

## Audit des GET

`tools/audit_get_routes.py` analyse maintenant tous les modules Python de
`app`, y compris les blueprints et API, et recherche les appels d'ecriture dans
les vues GET. L'execution stricte ne remonte aucune route a revoir.

L'unique exception declaree est
`GET /api/monitoring/poster/<server_id>`. Cette vue administrateur authentifiee
lit une image provider et peut alimenter le cache artwork local. Elle ne modifie
ni utilisateurs, ni serveurs, ni reglages, ni acces provider. Son cache et ses
en-tetes HTTP sont intentionnels et deja documentes dans le TODO.

Aucune route ne combine GET avec POST, PUT, PATCH ou DELETE dans un meme
decorateur.

## Conclusion

Aucun contournement CSRF exploitable n'a ete confirme. Le retrait des exemptions
inutiles ferme preventivement deux chemins et rend le contrat uniforme pour
toutes les methodes mutantes.

## Tests et controles

- POST, PUT, PATCH et DELETE sans jeton : HTTP 403;
- jeton incorrect : HTTP 403 pour chaque methode;
- jeton de formulaire correct : requete acceptee;
- jeton d'en-tete correct avec JSON : requete acceptee;
- deux jetons vides : HTTP 403;
- GET sans jeton : requete acceptee;
- audit GET strict sur toute l'application : zero finding, une exception revue.
