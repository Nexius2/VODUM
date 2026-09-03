# Audit de securite backup et restauration

Date: 2026-08-31

## Flux controle

Les sauvegardes completes sont creees dans un fichier temporaire puis publiees
par remplacement atomique. Elles contiennent la base SQLite, les pieces jointes,
un manifeste et la cle de chiffrement correspondante. Elles doivent donc etre
traitees comme des secrets et stockees hors d'un espace public.

La restauration n'accepte qu'un fichier selectionne dans `BACKUP_DIR` apres
resolution canonique, ou un upload renomme dans le repertoire d'import. Les
formats autorises sont ZIP, SQLite et DB. La base candidate est ouverte en
lecture seule, soumise a `PRAGMA integrity_check` et doit contenir les tables
VODUM essentielles avant tout remplacement.

## Archives ZIP

Toutes les entrees sont validees avant extraction. Sont refuses:

- chemins absolus POSIX ou Windows, `..` et traversées avec backslashes;
- doublons de noms, membres chiffres, symlinks et fichiers speciaux;
- archives depassant `VODUM_MAX_ZIP_MEMBERS`;
- somme des tailles extraites depassant `VODUM_MAX_ZIP_EXTRACTED_MB`.

Aucun `extractall` n'est utilise. Les seuls fichiers racine exploites sont
`database.db`/`database.sqlite` et `vodum.encryption_key`; les pieces jointes
sont ecrites sous un repertoire de travail dedie.

## Cle, swap et rollback

La cle incluse est validee avant le swap et comparee a
`VODUM_ENCRYPTION_KEY` lorsqu'elle est imposee par l'environnement. Une archive
sans cle conserve la cle active et ne la remplace jamais silencieusement.
Avant le swap, chaque credential chiffre de cette base est dechiffre avec la cle
active; une base legacy provenant d'une autre installation est donc refusee au
lieu de rendre silencieusement les credentials inutilisables.

La base et la cle courantes sont copiees avant remplacement. Les pieces jointes
sont maintenant elles aussi conservees jusqu'a la fin de la validation
post-restauration. Une erreur restaure ensemble base, cle et ancien dossier de
pieces jointes.

## Telechargement et exposition

Les routes sont classees admin par defaut. Le nom de fichier est reduit a un nom
simple et resolu sous `BACKUP_DIR`. Les reponses de telechargement utilisent
`Cache-Control: private, no-store, max-age=0` et `Pragma: no-cache`. L'API de
liste ne retourne plus les chemins filesystem internes.

La limite HTTP globale reste volontairement assez haute pour les imports
Tautulli; la separation des limites par type d'upload est traitee dans le lot
suivant.
