# Audit TOTP administrateur

Date: 2026-08-29

## Perimetre

Generation, affichage et confirmation du secret dans le wizard et les Settings,
stockage chiffre, verification lors des connexions locale et Plex, activation,
desactivation et changement des parametres de securite.

## Finding corrige

### MEDIUM - Secret d'enrolement choisi par le navigateur

- Fichiers: `app/routes/settings.py`, `app/routes/setup_wizard.py` et leurs
  templates.
- Comportement initial: le serveur generait un secret aleatoire pour l'affichage,
  mais la confirmation faisait confiance au champ cache `pending_totp_secret`.
- Protection existante: Settings exigeait le mot de passe administrateur actuel,
  le wizard etait limite a l'installation, et un code TOTP valide etait exige.
- Exploit: un formulaire modifie pouvait remplacer le secret par une valeur faible
  connue et fournir le code correspondant. Une attaque distante exigeait toutefois
  une session/CSRF valide ou l'execution de script dans le navigateur admin.
- Impact: affaiblissement silencieux du second facteur et possibilite de predire
  ses futurs codes si le mot de passe etait ensuite compromis.
- Correction: secret genere par le serveur, lie a la session et au contexte
  `settings` ou `setup`, expiration dix minutes, consommation avant verification,
  suppression des champs caches comme entree du formulaire.
- Risque de regression: faible; un formulaire ouvert plus de dix minutes doit
  simplement etre recharge pour obtenir un nouveau QR code.
- Statut: corrige.

## Protections confirmees

- Secret initial de 160 bits produit par `os.urandom`, encode en Base32.
- Algorithme TOTP standard SHA-1, six chiffres, periode de trente secondes et
  tolerance d'un pas avant/apres pour les decalages d'horloge.
- Comparaison constante des codes et rejet des formats non numeriques ou invalides.
- Secret persistant chiffre avec le magasin de secrets VODUM.
- Activation conditionnee par un code valide du secret en attente.
- Modification Settings conditionnee par le mot de passe administrateur actuel.
- Verification TOTP placee apres le mot de passe local et apres l'identite Plex.
- Echecs raccordes a l'anti-bruteforce; aucune valeur du secret ou du code n'est
  journalisee.
- Desactivation efface le secret stocke et les options dependantes.

L'audit du cookie de confiance TOTP local reste une ligne separee du TODO.
