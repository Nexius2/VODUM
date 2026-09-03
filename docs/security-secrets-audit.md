# Audit des secrets et identifiants sensibles

Date: 2026-08-31

## Conclusion

Les tokens Plex/Jellyfin, cles Tautulli, mots de passe et jetons OAuth SMTP,
tokens Discord, secret TOTP administrateur, secret Turnstile, jetons Plex de
decouverte et mots de passe temporaires de migration utilisent le chiffrement
Fernet avec le prefixe versionne `enc:v1:`. Les mots de passe admin/portail et
les jetons de session sont des hash non reversibles et ne doivent pas passer par
ce chiffrement.

Le formulaire et les donnees de page remplacent les secrets enregistres par des
valeurs vides et des indicateurs `configured`. Les reponses portail excluent les
hash et jetons de session. La telemetrie est limitee a une allowlist de valeurs
agregees et rejette les champs identifiants ou imbriques.

## Cle de chiffrement

- `VODUM_ENCRYPTION_KEY` reste prioritaire lorsqu'elle est explicitement fournie.
- Sinon `vodum.encryption_key` est cree atomiquement avec le mode `0600` sur une
  installation neuve.
- Si la base principale ou son WAL contient deja `enc:v1:` et que la cle manque,
  VODUM echoue avec une instruction de restauration et ne genere aucune cle de
  remplacement.
- Une cle invalide ou une cle valide mais differente provoque une erreur de
  dechiffrement; les valeurs existantes ne sont pas ecrasees.
- La restauration verifie la cle avant installation et refuse une cle differente
  lorsque `VODUM_ENCRYPTION_KEY` impose une autre valeur.

La cle Flask `vodum.secret_key` protege les cookies de session mais ne dechiffre
pas les credentials persistants. Sa perte invalide les sessions ouvertes; elle
ne rend pas les secrets provider illisibles.

## Migration et exposition

La migration de bootstrap chiffre les anciennes valeurs en clair pour SMTP,
OAuth SMTP, Discord, TOTP administrateur, Turnstile, tokens serveur et cles
Tautulli. Les champs de migration introduits plus tard sont chiffres des leur
creation.

Le filtre de journal neutralise emails, IPv4, Authorization/Bearer, tokens,
mots de passe, secrets et cles API. Le mode debug peut volontairement augmenter
le detail technique et ne doit pas etre active en production publique.

## Permissions

Les fichiers de cles sont demandes en mode `0600`. Sur les plateformes ne
supportant pas les permissions POSIX, le controle repose aussi sur les droits du
volume persistant. Les ZIP complets restent sensibles puisqu'ils embarquent la
base et le materiel de dechiffrement; leur audit est traite dans le lot backup.
