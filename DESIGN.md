# NIMM — Logique de conception

_Ce document décrit l'esprit de NIMM : pourquoi il est construit comme ça,
quels principes guident les choix. Pour les détails techniques, voir ARCHITECTURE.md._

---

## Ce qu'est NIMM

NIMM est un assistant personnel conversationnel. Pas un chatbot générique —
un assistant qui connaît son utilisateur, retient ce qui compte, et s'améliore
avec le temps. Il tourne localement, appartient à celui qui l'installe,
et peut être adapté à n'importe quelle personnalité via le système de masques.

La philosophie de base : **l'esprit plutôt que la lettre.**
NIMM ne cherche pas à appliquer des règles à la lettre — il cherche à comprendre.

---

## Principe architectural : Hub-and-Spoke

Tout passe par `hub.py`. Aucun module ne parle directement à un autre.

Pourquoi ? Parce qu'un assistant personnel touche à tout — mémoire, agenda,
bibliothèque, recherche web, synthèse vocale, image. Sans point central,
chaque module finit par connaître les autres, et le code devient un plat de
spaghettis impossible à maintenir ou faire évoluer.

Le hub orchestre. Les modules exécutent. La base de données n'est accessible
que via `database.py` — jamais directement depuis le hub ou les modules.

---

## La mémoire — ce qu'on retient et pourquoi

### Le problème central

Un LLM n'a pas de mémoire entre les conversations. NIMM résout ça en extrayant
les faits importants et en les stockant sous forme de triplets :
`sujet / prédicat / objet` — par exemple `Laurent / métier / chauffeur poids lourd`.

Mais tous les faits ne se valent pas. "Laurent aime la brandade de morue" mérite
d'être retenu. "Laurent a mangé un sandwich à Benfeld" ne mérite pas de survivre
au-delà de 24h. La difficulté est de faire cette distinction automatiquement.

### La règle d'or : autonomie du triplet

Un triplet ne doit être stocké que s'il se comprend sans relire la conversation.
`neurologue / Strasbourg` ne veut rien dire seul. `suivi_neurologique / hypertension intracrânienne`
dit quelque chose. Si l'objet a besoin du contexte pour exister → on n'extrait pas.
Ce que le triplet ne peut pas porter, le carnet de bord le capture en texte libre.

### Permanence et durée de vie

Tous les souvenirs ne sont pas permanents. NIMM distingue :

- **Permanent** : ne disparaît jamais. Famille, santé, croyances — les faits qui
  définissent une personne. Aussi tout souvenir suffisamment répété (poids ≥ 2.5
  ou 3 répétitions confirmées).
- **Persistant** : reste actif tant que le sujet est abordé régulièrement.
  Decay lent — si le sujet disparaît des conversations, le fait s'efface progressivement.
- **Épisodique** : dure quelques jours au plus. Événements ponctuels, contexte
  immédiat. Profondeur 4 → 7 jours. Profondeur 3 → 30 jours. Passé ce délai
  sans réévocation → supprimé silencieusement.

Le worker mémoire tourne toutes les 30 secondes en arrière-plan.
Il extrait, renforce, et purge. L'utilisateur ne le voit pas — c'est voulu.

### Pull plutôt que push

Ancienne approche : injecter tous les souvenirs permanents dans chaque message.
Problème : le LLM recevait les mêmes 80 triplets à chaque tour, même quand
le sujet de conversation n'avait rien à voir avec eux. Bruit, tokens gaspillés,
attention diluée.

Nouvelle approche : le LLM reçoit un **index thématique compact**
(Famille · Santé · Travail · Loisirs · Projets…) et appelle `search_memory(sujet)`
quand un thème devient pertinent dans la conversation. Il va chercher ce dont
il a besoin, quand il en a besoin. L'index se met à jour automatiquement
à chaque nouveau souvenir stocké.

### Le carnet de bord

Sur les longues conversations, la fenêtre de contexte finit par perdre les
premiers échanges. Le carnet de bord compense : toutes les 7 répliques,
le LLM génère une note courte qui résume ce qui s'est passé. Ces notes sont
réinjectées dans le contexte quand la conversation devient longue.
Ce n'est pas un résumé global — c'est une mémoire de travail propre à chaque fil.

---

## Le tool calling — comment NIMM cherche l'information

NIMM dispose de quatre outils qu'il peut appeler lui-même pendant une réponse :

- `search_memory` — mémoire personnelle de l'utilisateur
- `search_bibliotheque` — conversations passées archivées
- `search_anecdotes` — moments forts ou souvenirs partagés
- `search_web` — recherche internet (uniquement pour l'information datée par nature)

Le LLM décide seul s'il en a besoin. Il ne reçoit pas les données en avance —
il les demande. Ça évite de polluer le contexte avec des informations non pertinentes
pour la conversation en cours.

`search_web` est soumis à une règle stricte : uniquement pour ce qui change
dans le temps (actualité, prix, météo). Jamais pour analyser un document
déjà fourni par l'utilisateur dans le message.

---

## La bibliothèque — l'os des conversations

Quand une conversation se termine, elle disparaît du contexte. La bibliothèque
est ce qui reste — pas un transcript, pas un résumé, mais **l'os**.

### Os / Peau / Mood

NIMM sépare trois couches dans tout ce qu'il produit :

- **L'os** — la structure de pensée, indépendante du contexte. Ce qui a été
  réellement construit dans la conversation : les idées développées, les tensions
  traversées, les positions atteintes, les questions restées ouvertes.
- **La peau** — le masque actif. La même pensée peut être exprimée par Lia,
  Morse ou Iris — le fond ne change pas, la forme si.
- **Le mood** — l'état émotionnel du moment. Il colore la peau, pas l'os.

La bibliothèque archive l'os pur. Quand le LLM rappelle une fiche six mois
plus tard, il reçoit la structure de pensée — il peut l'habiller avec son
masque actuel et l'ajuster au mood du moment.

### Les 7 composantes de l'os

Une fiche riche contient :

1. **Fil conducteur** — la question ou tension centrale qui a traversé la conversation
2. **Nœuds** — 4 à 8 idées développées (1–3 phrases chacune, pas des résumés)
3. **Positions** — ce qui a été conclu, décidé, ou assumé comme non tranché
4. **Questions ouvertes** — ce qui tourne encore, mériterait d'être poursuivi
5. **Formulations clés** — phrases ou tournures qui ont bien capturé quelque chose
6. **Climat** — le mode de la conversation (chercher ensemble, buter, construire, léger, tendu)
7. **Ramifications** — pistes frôlées, sujets qui affleuraient sans être traités

Le **climat** n'est pas l'état émotionnel — ça, la dominante le capture déjà.
C'est la texture du travail intellectuel : comment on pensait ensemble.

Les **ramifications** sont la pièce la plus précieuse : elles permettent au LLM
de proposer "la dernière fois on avait frôlé tel sujet, tu veux qu'on y revienne ?"
C'est la seule composante orientée vers l'avenir.

### Catégories émoji

Chaque fiche reçoit 1 à 3 émojis choisis parmi une liste prédéfinie de 17 catégories.
Ils taguent la fiche entière (pas des idées individuelles) et permettent une
navigation par domaine en complément de la recherche textuelle.

Le LLM choisit les émojis — il ne les invente pas, il sélectionne dans la liste.

### Ce que le recall transmet

Quand le LLM appelle `search_bibliotheque`, il ne reçoit pas une étiquette —
il reçoit l'os : fil conducteur, nœuds développés, positions, questions ouvertes,
ramifications. Assez pour que la pensée soit reconstituable et réutilisable,
sans avoir à relire la conversation d'origine.

---

## Les masques — personnalité et mémoire séparées

Un masque est un fichier JSON qui définit la personnalité et le style de réponse
de l'assistant. Il est distinct du system prompt technique.

Règle fondamentale : **le masque ne touche pas à la mémoire**.
Le masque dit *comment* répondre. Le system prompt dit *quoi* savoir et *quelles règles* suivre.
Quand les deux se mélangent, les instructions se contredisent et le LLM se perd.

Les masques peuvent être simples (personnalité en quelques lignes) ou complexes
(système d'états avec transitions, registres de réponse, mécanique émotionnelle).
La règle reste la même : compact et orthogonal au reste.

---

## L'injection du system prompt — ordre et priorité

Le system prompt est assemblé à chaque message dans un ordre précis :

1. Masque / personnalité
2. Lexique contractuel (règles techniques — SONDE, AGENDA, IMAGE…)
3. Date et heure
4. Signal émotionnel dominant (si actif)
5. Situation courante (lieu ou activité détectés)
6. Rappels actifs
7. Présence temporelle (si retour après longue absence)
8. Bilans de session (faits confirmés dans le fil courant)
9. Carnet de bord (si la conversation est longue)
10. Index thématique mémoire
11. Bibliothèque (si recherche pertinente)
12. Outils disponibles
13. Format de sortie (tags techniques attendus)

Cet ordre n'est pas arbitraire. Ce qui vient en premier a plus d'influence
sur le comportement du LLM. La personnalité en tête, les contraintes techniques
en bas — le LLM est d'abord lui-même, puis il suit les règles.

---

## Les tags techniques — contrat de sortie

Le LLM produit des balises `%%TAG%%` dans ses réponses. Ces balises sont
interceptées par le hub avant d'être transmises au frontend.

Elles permettent de déclencher des actions sans que l'utilisateur ait à
formuler de commande explicite : créer un rappel agenda, stocker un souvenir,
archiver un bilan, générer une image. Le LLM n'exécute pas — il signale.
Le hub exécute.

---

## Ce que NIMM n'est pas

NIMM n'est pas conçu pour être un assistant généraliste. Il ne cherche pas
à tout savoir ni à tout faire. Il est conçu pour **connaître une personne**
et lui parler en tenant compte de ce qu'il sait d'elle.

La recherche web existe mais est contrainte. L'agenda existe mais reste simple.
La bibliothèque archive mais ne résume pas tout. Chaque fonctionnalité est là
parce qu'elle sert la relation entre l'assistant et l'utilisateur — pas pour
faire une liste de features.
