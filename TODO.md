import_tautulli  semble se lancer regulierement meme sans import programmé


- prevoir du multi admin
  * dans settings, prevoir un onglets accounts
  * dans cet onglet, on peut add, remove edit admin account.
  * admin account on l'acces complet sur admin UI
Complexité : LS
Faisabilité : haute, mais à faire après découpage du code


- ajouter une interface utilisateurs pour qu'ils puissent voir l'etat de leur compte et certaines stats des serveurs et leur stats
  * appelons l'ui actuel admin UI
  * appelons l'ui utilisateur user UI
  * prevoir l'affichage du nom de domaine. a renseigné dans les settings admin ui et dans la page user ui / general
  * user peut voir son compte et l'integralité de ces données accessible via vodum_user exept notes.
  * notes become admin_notes and we should add user_notes
  * user ne peut modifier que son firstname, lastname, secondary_email, discord uer id and name, notiffication system order si l'option est cocher dans settings admin_ui
  * user can see what server and library he has access to
  * user monitoring: une page dedié au monitoring ou il peut voir (uniquement des data le concernant):
    1) total watch time / sessions for the last 24h, 7 days, 30cdays
	2) un donuts pour affiché les media type
	3) un graphe pour afficher les sessions (per days,7d,30d, 1y, all time)
	4) top players pour voir sur quoi il regarde
	5) son historique
  * integration de wwiw dans l'ui user???
  * ajouter un champs mdp avec posibilité pour le user de le modifier. attention, il doit au moins y avoir un system de notification de configurer pour ca pour le recovery.
  * ajouter un login via plex .... comment ca marche avec du multi serveur??? normalement, c'est un compte user donc pas de soucis, mais a verifier.
Complexité : XL
Faisabilité : oui, mais à faire après decoupage et multi admin
	


- dans monitoring overview, afficher dans une bulle le nombre de sessions et de transcode par serveur.




- dans le profil utilisateur, posibilité d'avoir un lien qui pointe vers le user sur plex.
  * attention, il peut y avoir plusieurs serveur pour un meme user. il faut donc un system pour choisir le serveur dans ce cas la. ou ouvrir les x pages plex.
  

  

  



