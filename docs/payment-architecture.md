# Architecture du paiement User Portal

Date de conception: 2026-08-31

## Portee de la V1

La premiere version accepte uniquement un paiement ponctuel pour renouveler le
forfait actuellement affecte a l'utilisateur. Elle n'implemente ni abonnement
recurrent, ni changement de forfait, ni prorata, ni retrait automatique de jours
apres remboursement.

VODUM ne fournit aucun compte marchand. Chaque administrateur configure ses
propres providers et secrets.

## Inventaire a reutiliser

- `subscription_templates` reste la source de verite pour le forfait, sa duree,
  son prix et ses regles.
- `vodum_users.subscription_template_id` identifie le forfait courant.
- `app/api/subscriptions.py:update_user_expiration` contient les effets secondaires
  de reactivation, mais ne constitue pas une transaction atomique avec un paiement.
- Le trigger `vodum_users_sync_renewal_after_expiration_update` renseigne la date
  du dernier changement d'expiration.
- `app/secret_store.py` fournit le chiffrement persistant; les credentials provider
  seront stockes sous forme d'un document JSON chiffre unique.
- `DBManager.transaction()` fournit `BEGIN IMMEDIATE`, necessaire a l'idempotence.
- Le portail applique deja authentification serveur, permissions par role,
  limitation de requetes, audit et `Cache-Control: no-store`.
- `portal_show_payment`, `portal_payment_url` et `portal_payment_label` sont un
  ancien placeholder. Ils devront etre migres puis retires apres remplacement
  complet par la disponibilite calculee du nouveau moteur.

## Modules a creer

- `app/core/db_bootstrap_payments.py`: schema et index.
- `app/core/payment_providers.py`: contrat provider et objets de retour neutres.
- `app/core/payments.py`: montants, transitions, calcul de prolongation et unite
  transactionnelle de confirmation.
- `app/core/payment_settings.py`: normalisation admin, chiffrement et readiness.
- `app/core/payment_repository.py`: lectures/ecritures bornees des commandes,
  transactions et evenements.
- `app/routes/payment_admin.py`: configuration, diagnostic, tests et historique.
- `app/routes/portal_payments.py`: creation d'une commande pour le compte connecte,
  etat et historique propre.
- `app/routes/payment_webhooks.py`: endpoints publics verifies par provider.
- `app/payment_providers/paypal.py`, puis `stripe.py` et `mollie.py`.

## Tables

### `payment_provider_configs`

Une ligne par provider. Les champs publics restent en JSON; tous les secrets du
provider sont regroupes dans `secret_config_enc`, chiffre avant stockage. Les
statuts de test ne doivent contenir qu'un code diagnostique non sensible.

### `payment_orders`

Une commande possede un identifiant public opaque. Elle fige le forfait, la duree,
le montant en unite monetaire mineure et la devise au moment de sa creation.
Modifier ensuite un subscription template ne modifie jamais la commande.

### `payment_transactions`

Une transaction represente le resultat provider. L'unicite de
`(provider, provider_transaction_id)` interdit qu'une capture prolonge deux fois
un abonnement. Les remboursements sont tracables sans politique automatique.

### `payment_webhook_events`

Chaque evenement provider est deduplique. Seuls son identifiant, son empreinte et
son resultat de traitement sont conserves; le payload et les signatures ne sont
pas journalises comme secrets.

## Flux de renouvellement

1. Le portail envoie uniquement `plan_id` et `provider`.
2. Le backend verifie le compte connecte, l'activation, le provider, le forfait
   courant, sa visibilite, sa duree et son prix.
3. Le backend convertit le prix avec `Decimal` en montant entier mineur, fige un
   snapshot et cree la commande VODUM.
4. Le provider cree sa commande depuis ce snapshot et renvoie uniquement les
   informations publiques utiles au frontend.
5. Le retour navigateur affiche un etat d'attente; il ne prolonge rien.
6. Le webhook est authentifie et normalise par l'adaptateur provider.
7. Dans une transaction SQLite `BEGIN IMMEDIATE`, VODUM deduplique l'evenement et
   la transaction, reverifie ordre/provider/montant/devise/statut, verrouille
   logiquement la commande, prolonge l'expiration puis marque commande et
   transaction traitees.
8. Les effets secondaires non critiques et logs sont executes apres commit.

Calcul de la nouvelle expiration:

- si l'expiration courante est aujourd'hui ou dans le futur: expiration courante
  + duree achetee;
- sinon: date de confirmation du paiement + duree achetee.

## Contrat provider

Un provider doit exposer les operations suivantes sans connaitre le schema VODUM:

- verifier sa configuration;
- creer une session/commande de paiement depuis une commande figee;
- verifier et normaliser un webhook depuis les octets et en-tetes originaux;
- rechercher l'etat serveur d'une transaction lorsque le provider le permet.

Le resultat normalise contient provider, identifiants d'evenement/commande/
transaction, statut, montant, devise et date provider. Il ne declenche jamais lui-
meme une modification d'abonnement.

## CSRF et exposition publique

Le garde actuel refuse toute mutation sans jeton de session. Les routes webhook
seront les seules exceptions, identifiees par endpoint interne et non par prefixe
libre. Avant toute exemption, chaque adaptateur devra fournir:

- verification cryptographique officielle sur le corps brut;
- taille maximale specifique;
- provider et environnement attendus;
- deduplication de l'identifiant evenement;
- comparaison constante lorsque des secrets locaux sont compares;
- reponse generique sans fuite de diagnostic.

Les routes de creation/consultation du portail restent sous CSRF, session serveur,
permission et controle de propriete.

## Decisions de securite et d'exploitation

- Montants stockes en entiers mineurs, jamais en `float` dans le moteur paiement.
- Devise normalisee en code ISO majuscule et figee par commande.
- Aucun secret renvoye apres sauvegarde, meme chiffre.
- Aucun payload bancaire, secret, signature ou URL sensible dans les logs.
- Readiness fail-closed: option generale, provider active, environnement et
  credentials complets.
- Sandbox clairement visible et separe de Live.
- Aucun `paid` issu du navigateur; uniquement d'un evenement provider verifie ou
  d'une reconciliation serveur authentifiee.
- Les transitions terminales ne peuvent pas revenir a `pending`.

## Modifications de fichiers existants prevues

- `app/db_bootstrap.py`: enregistrer le bootstrap paiement.
- `app/core/csrf_security.py`: exception webhook strictement bornee, seulement
  lorsque le premier provider signe est implemente.
- `app/core/portal_permissions.py`: permissions paiement propres au compte.
- `app/core/portal_page_data.py`: disponibilite et historique, suppression du faux
  lien de paiement.
- `app/core/portal_settings.py` et `app/core/portal_readiness.py`: configuration et
  readiness paiement distinctes de la readiness generale du portail.
- `app/routes/portal_admin.py` et `templates/settings/portal.html`: configuration
  integree a User portal.
- `app/routes/portal.py` et `templates/portal/subscription.html`: vrai parcours de
  renouvellement.
- `app/core/portal_privacy.py`: export/effacement avec politique comptable explicite;
  les paiements ne doivent pas etre effaces aveuglement avec le compte portail.
- `translations/ui/*.json`: tous les labels et diagnostics.

## Strategie de tests

- Bootstrap idempotent, contraintes et index uniques.
- Montants et devises, snapshots immuables et calcul actif/expire.
- Matrice de transitions de statuts.
- Propriete stricte des commandes du portail.
- Readiness et conservation/chiffrement des secrets.
- Webhooks signes, invalides, dupliques, desordonnes et rejoues.
- Montant/devise/forfait discordants.
- Transaction atomique: aucune expiration prolongee sans paiement traite, et
  aucun paiement traite sans expiration prolongee.
- Retours navigateur incapables de confirmer un paiement.
- Export, retention, logs et redaction de secrets.
