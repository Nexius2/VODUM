# Audit de non-enumeration du compte administrateur

Date: 2026-08-30

## Parcours verifie

`POST /login/submit` normalise l'email, applique Turnstile lorsqu'il est active,
puis consulte les verrous IP et email avant de verifier le mot de passe.

Pour un email connu, le hash administrateur persiste est verifie. Pour un email
inconnu, `_admin_password_matches` verifie un hash factice genere au demarrage.
Les deux chemins effectuent donc une operation de meme nature et un seul appel a
`check_password_hash` avant de produire un echec.

Un mauvais mot de passe produit dans les deux cas :

- la meme redirection vers `/login`;
- le meme message traduit `auth.invalid_credentials`;
- un echec dans les portees IP et email de l'anti-bruteforce;
- aucun identifiant, statut de compte ou detail de base de donnees dans la
  reponse.

Le motif interne `bad_email` ou `bad_password` est utilise uniquement dans les
journaux et les alertes de securite destinees a l'exploitant. Il n'influence pas
la reponse HTTP. Cette distinction est utile au diagnostic sans constituer un
oracle accessible au client non authentifie.

## Limites intentionnelles

Une instance qui ne possede encore aucun mot de passe administrateur redirige
vers l'installation initiale. Ce comportement indique l'etat global de
configuration de l'instance, pas l'existence d'une adresse email choisie par le
visiteur, et il est necessaire au premier demarrage.

Lorsque la 2FA est active, un mot de passe principal valide peut mener au message
de code TOTP invalide. Cela revele la validite du premier facteur a une personne
qui le connait deja, mais ne permet pas de tester l'existence arbitraire d'un
email avec un mauvais mot de passe. Modifier ce parcours risquerait de casser les
retours necessaires a la connexion 2FA sans gain contre l'enumeration de compte.

## Conclusion

Aucune vulnerabilite d'enumeration du compte administrateur n'a ete confirmee.
Aucune modification du code de production n'est necessaire.

## Tests

- email inconnu : verification unique du hash factice;
- email connu : verification unique du hash persiste;
- comparaison directe des deux chemins avec le meme mot de passe rejete;
- message d'echec public generique deja couvert par le contrat de route.
