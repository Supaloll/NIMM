# coaNIMM : discuter ou agir ? — Note de réflexion

Note préparée par Laurent (avec Claude) suite à une session de debug sur la boucle
d'outils de coaNIMM. Objet : une réflexion de fond sur son comportement, à discuter
ensemble avant toute implémentation.

## Le point de départ

En testant coaNIMM sur une tâche concrète (convertir un .svg en .png), deux modèles
ont réagi très différemment au même message :

- **DeepSeek** a posé des questions avant d'agir ("tu veux découper ou imprimer ?"),
  a même suggéré une meilleure méthode que celle demandée.
- **Mistral** a foncé directement sur l'outil, sans vérifier que la demande était
  claire.

Même prompt, même contexte, deux comportements opposés. Ça a lancé une réflexion :
et si ce n'était pas au tempérament du modèle du jour de décider s'il faut agir ou
discuter ?

## Le biais du créateur

Nando connaît coaNIMM de l'intérieur — il sait ce qu'il peut faire et comment le
formuler, parce qu'il l'a construit. Laurent, en utilisateur qui découvre, tape ce
qui lui vient naturellement, sans connaître les attentes de l'outil, et tombe parfois
à côté. C'est un biais classique en conception d'outils : celui qui construit ne peut
plus vraiment se mettre à la place de celui qui découvre. Si coaNIMM ne répond bien
qu'aux questions de quelqu'un qui sait déjà comment il fonctionne, c'est l'outil qui
a un point à travailler, pas l'utilisateur.

## L'idée : un "réviseur" avant la réponse

Le principe : avant que coaNIMM ne réponde, un passage rapide analyse le message et
tranche — *discussion simple, ou demande d'action (produire une image, un document,
classer/renommer des fichiers...) ?*

- Si discussion → la conversation part normalement, comme aujourd'hui.
- Si action → coaNIMM active ses outils et sa boucle de travail (voir plus bas).

Ce mécanisme a un nom reconnu : un **routeur d'intention**. Et bonne nouvelle : la
place où il devrait vivre existe déjà dans le code — `modules/intent_gate.py`. Ce
fichier a un rôle prévu à l'origine pour juger un message avant qu'il n'atteigne la
conversation ; aujourd'hui il a été réduit à ne filtrer que les messages vides. L'idée
ne demande donc pas d'inventer un nouvel étage, juste de redonner du travail à un
étage existant.

## Ce que ça résout

- **Cohérence** : la décision "agir ou discuter" ne dépend plus de l'humeur du modèle
  branché ce jour-là (DeepSeek, Mistral, autre).
- **Ça rejoint l'esprit d'origine du projet** : NIMM, à l'époque où il s'appelait
  IN-VICTUS, devait être un "anti-SillyTavern" — un outil qui *comprend* plutôt qu'un
  outil à régler par des commandes rigides.

## Ce que ça ne résout pas — à garder en tête

- Le réviseur devra, lui aussi, parfois se tromper sur des messages ambigus. Le
  problème n'est pas éliminé, il est *déplacé* — d'un comportement dépendant du
  modèle vers un seul filtre bien identifié, plus facile à régler et à tester.
- Petit coût : un appel de plus avant chaque réponse, donc un peu de latence en plus
  (gérable avec un modèle rapide/léger pour ce tri).
- Différence de fond avec Cline (l'outil de code que Laurent utilise pour développer
  NIMM) : Cline a un juge objectif à chaque étape — le code compile ou pas, un test
  passe ou échoue. coaNIMM n'a rien d'équivalent pour juger si une réponse est
  "pertinente". D'où l'intérêt, dans le doute, de préférer demander plutôt que
  d'agir : c'est une façon de compenser l'absence de ce juge.

## Un exemple qui illustre le principe

Une IA de génération d'image, à qui on demande de "mettre la police devant" sur un
visuel qui contient déjà un texte, a dessiné des policiers au premier plan. Le mot
"police" est ambigu (police de caractères / police qui arrête les voleurs), et le
module de génération a suivi l'association la plus fréquente dans ses données
d'entraînement plutôt que de vérifier le contexte immédiat (un texte était déjà
présent dans l'image). Même défaut de fond que "agir vs discuter" : un système qui
traite une instruction isolément, sans bien regarder ce qu'il y a autour, se trompe.

## Pour la suite

À discuter ensemble : la formulation exacte de la consigne du réviseur, comment la
tester sur des cas concrets par fournisseur (un peu comme pour les prompts de
mémoire, qui sont déjà adaptés par modèle), et le compromis latence/cohérence selon
le modèle choisi pour ce tri.
