# Changelog

- Enrichissement des diagnostics Discord : les erreurs distinguent désormais
  les problèmes permanents de configuration, destinataire ou permissions des
  incidents temporaires de réseau, disponibilité et rate limit. Les réponses
  brutes de l'API ne sont plus enregistrées dans l'historique, et les campagnes
  évitent les retries inutiles lorsqu'aucune erreur n'est récupérable.
- Les messages Discord longs ne sont plus tronqués silencieusement : ils sont
  découpés sans perte en plusieurs messages de taille sûre, avec retry par
  partie. Les éditeurs affichent une estimation du nombre de messages et
  précisent que le sujet et les pièces jointes concernent uniquement l'email.
- Les templates et campagnes peuvent désormais hériter de la configuration
  globale ou imposer l'email, Discord, ou les deux canaux. Ce ciblage est
  appliqué par les workers et un canal requis mais indisponible produit un
  diagnostic définitif au lieu d'être silencieusement ignoré. Les anciennes
  campagnes conservent leur canal d'origine pendant la migration, tandis que
  le mode campagne de test reste explicitement envoyé à l'email de contact.
