# Audit XSS des rendus administrateur et portail

Date: 2026-08-30

## Perimetre

La revue couvre les templates Jinja, le HTML produit par Python et le JavaScript
applicatif dans `static/js`. Les bibliotheques vendor minifiees ont ete separees
du code VODUM : leurs usages internes de `innerHTML` ne recoivent pas directement
les objets provider ou les reponses API de VODUM.

Les sources externes suivies jusqu'au rendu comprennent les noms Plex et
Jellyfin, utilisateurs et serveurs, bibliotheques, titres et metadonnees media,
sessions de monitoring, logs, erreurs API, donnees Discord, communications et
historique importe depuis Tautulli.

## Jinja et Python

L'auto-echappement Flask/Jinja reste actif pour les templates HTML. Aucun
`render_template_string` ni construction de template depuis une valeur externe
n'est utilise. Le dernier filtre `|safe`, applique uniquement a des entites de
fleches constantes dans la liste des bibliotheques, a ete remplace par des
caracteres Unicode ordinaires.

Le seul retour `Markup` applicatif est `browser_datetime`. La structure de la
balise `span` est constante et les trois valeurs variables sont passees par
`markupsafe.escape` : date ISO dans l'attribut, mode d'affichage et texte
visible. Une charge contenant guillemets, attributs d'evenement et balise `img`
ne peut pas sortir de l'attribut ni creer un element executable.

Les contenus de communication sont affiches comme texte dans les editeurs et
vues d'administration; aucun corps email ou Discord n'est marque comme HTML sur
la base de son contenu.

## JavaScript applicatif

Les sinks `innerHTML` ont ete classes en quatre groupes :

- vidage d'un conteneur avec une chaine vide;
- copie de fragments DOM ou HTML rendu par le serveur, deja auto-echappe;
- composants construits uniquement avec constantes, nombres normalises et
  traductions embarquees;
- listes issues d'API ou providers, dont chaque valeur textuelle passe par
  `htmlEscape`/`escapeHtml` avant interpolation.

Les modales de monitoring utilisent `textContent` pour les titres et valeurs
simples. Les tableaux dynamiques echappent notamment noms d'utilisateur,
emails, serveurs, bibliotheques, medias, clients, raisons de policy, messages de
log et messages d'erreur. Les identifiants utilises dans des URL sont encodes
avec `encodeURIComponent` ou convertis en nombres.

Aucun usage applicatif de `outerHTML`, `insertAdjacentHTML`, `document.write`,
`render_template_string` ou `DOMParser` avec donnees externes n'a ete trouve.
Les attributs `hx-swap` declaratifs de HTMX recoivent des fragments produits par
des vues Jinja et ne desactivent pas l'auto-echappement serveur.

## Finding corrige

### INFO - Contournement Jinja inutile pour les fleches de tri

- Fichier : `templates/servers/libraries.html`.
- Comportement : deux entites HTML constantes utilisaient `|safe`.
- Exploitabilite : aucune; aucune valeur externe n'atteignait le filtre.
- Correction : remplacement par les caracteres Unicode fleche haut/bas.
- Impact/regression : aucun changement fonctionnel attendu.
- Statut : corrige par reduction de surface et clarification du contrat.

## Conclusion

Aucune XSS stockee ou reflechie exploitable n'a ete confirmee dans les chemins
revus. L'audit des en-tetes et l'introduction progressive d'une CSP restent des
lots distincts du TODO afin de ne pas confondre echappement des donnees et
defense navigateur en profondeur.

## Tests

- absence de `|safe` dans tous les templates applicatifs;
- payload hostile dans le texte et les attributs de `browser_datetime`;
- verification que la sortie reste un `Markup` structurel dont toutes les
  valeurs variables sont encodees;
- inventaire manuel des sinks DOM applicatifs et de leurs fonctions d'echappement.
