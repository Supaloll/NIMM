J'ai tout ce qu'il me faut. Je construis le script de diagnostic.

Ce qu'il va faire :



Charger ta clé DeepSeek directement depuis nimm\_laurent.db (pas de config manuelle)

Envoyer 10 messages au LLM d'extraction, du plus simple au plus subtil

Afficher exactement ce que le LLM produit pour chaque message, brut

Puis passer chaque réponse dans le pipeline NIMM (parser + save\_inline\_memory) en mode simulation, pour voir ce qui passe et ce qui est rejeté — sans écrire en DB

Rapport final : quel niveau décroche, et pourquoi.



**Résultat :**



Ce que le LLM fait mal — 3 bugs identifiés

Bug 1 — Le prénom hallucine : "Laurence" au lieu de "Maïssane"

Dès le message #3, DeepSeek invente "Laurence" comme sujet alors qu'il s'agit de Maïssane. Ça se répète sur les messages #5 et #6. La cause : quand le contexte ne répète pas le prénom explicitement, le LLM s'invente un sujet féminin proche du prénom "Laurent" qu'il vient de voir. Ces triplets sont acceptés par les filtres (Laurence ressemble à un prénom), mais attribués à la mauvaise personne.

Bug 2 — Les faits chiffrés sont perdus ou mal encodés

Message #2 : "6 ans" et "4 compétitions" → le LLM produit deux tags sport|judo avec des contextes différents, au lieu de créer un triplet dédié pour la durée et un pour le nombre de compétitions. La valeur numérique se retrouve dans le champ contexte (qui n'est pas indexé pour le recall) plutôt que dans le champ objet.

Bug 3 — Le sujet des faits sur Maïssane est souvent Laurent

Messages #7, #8, #10 : les faits concernent Maïssane, mais le LLM les attribue à Laurent (Laurent / enfant = fille). Il mémorise la relation père-fille au lieu du fait sur la fille. C'est logique de son point de vue (le "je" du message c'est Laurent), mais ça rend la mémoire de Maïssane vide.



La cause racine

Le prompt dit : "sujet : prénom réel — ici 'Laurent'". Cette indication oriente le LLM vers Laurent comme sujet par défaut. Quand il parle d'un proche, il tend à faire Laurent / enfant = fille plutôt que Maïssane / trait = fair-play.



Ce qu'on va corriger

Deux modifications dans hub.py, dans la fonction extract\_memories\_background() :



Le prompt — reformuler pour qu'il comprenne que le sujet peut être n'importe quelle personne mentionnée, pas seulement l'utilisateur. Et ajouter une règle explicite : les faits sur un proche s'encodent avec le prénom du proche comme sujet, pas celui de l'utilisateur.

max\_tokens de 300 → 600 — ça gagne des triplets sur les messages #3 et #6, sans coût significatif.



On ne touche pas aux filtres — ils fonctionnent correctement. Le problème est entièrement dans ce que le LLM produit.

**Après correction dans 'hub.py'**

Excellent. C'est nuit et jour par rapport à l'ancien prompt.

Avant : "Laurence" comme sujet, chiffres perdus dans le contexte, 0 fait sur Maïssane dans les messages émotionnels.

Après : 23 triplets acceptés, zéro rejet, Maïssane correctement identifiée sur tous les messages, les chiffres dans les objets.

Deux petites observations mineures avant de valider :



Message #5 : probleme\_sante = pénalisée pour passivité en judo — c'est un mauvais prédicat pour un défaut technique, mais c'est anecdotique, ça ne gêne pas.

Message #8 : la fierté de Laurent n'est pas capturée — mais c'est un état émotionnel du père, pas un fait stable sur Maïssane, c'est correct de ne pas le stocker.

\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*

Je valide cette maj avec ça, je vais relancer une session sur un autre thème, histoire de voir dans un autre contexte ce qu'il se passe.

