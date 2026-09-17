# Cahier des charges — VSBot 🖥️

_Document de cadrage. Rédigé le 17/09/2026. Rien n'est encore codé : ce document
décrit une intention et un plan, pas un état du code._

---

## En une phrase

VSBot est un agent de lecture et d'écriture de fichiers de code qui vit **à côté
de CoaNIMM** : on lui montre un dossier ou un fichier, il lit, il explique, il
propose une modification **en montrant le diff avant d'écrire**, et on peut
annuler ce qu'il a fait.

---

## Le besoin, tel qu'il s'est manifesté

Le 17/09/2026, Laurent voulait, **depuis son mobile**, montrer à Lia des fichiers
de code d'un de ses ateliers dans une conversation. Il a autorisé les dossiers
concernés — et le chatbot était toujours incapable de lire un `.py`.

Ce qui bloque aujourd'hui, vérifié dans le code :

1. **Le chat n'a aucun outil de lecture de fichier local.** Les 27 outils de
   `core/hub.py` (`NIMM_TOOLS`) couvrent la mémoire, le web, les documents, les
   images, la voix, `write_file` (créer un document) et `run_code` (exécuter du
   code sandboxé) — **aucun ne lit un fichier indiqué par l'utilisateur**.
2. **Le seul outil de lecture de documents refuse les fichiers de code.**
   `extract_document_text` (`modules/coanimm_ops.py`) s'appuie sur
   `extract_any` (`modules/enrichissement.py`), dont la liste de texte pur vaut
   `_EXT_TEXTE = {"txt", "md", "csv"}`. Un `.py`, `.js`, `.json`, `.html` reçoit
   « Format non pris en charge ».
3. **Les « Dossiers autorisés » ne concernent que l'écriture.** Le panneau
   l'indique lui-même (« Dossiers autorisés en écriture ») et
   `modules/coanimm_safety.py` ne confinait que les écritures, suppressions et
   déplacements — **les lectures ne sont pas confinées**.

Ce qui fonctionne déjà, mais par la porte de service : le mode CoaNIMM génère un
script Python et l'exécute. Un script peut lire un `.py` (les lectures n'étant
pas confinées) et le contenu revient dans la sortie. C'est opaque, lent, fragile
(le modèle doit écrire le bon chemin), et tronqué au-delà de quelques milliers de
caractères.

**Conclusion : ce n'est pas un réglage manquant, c'est une fonction absente.**
VSBot la comble, dans un espace dédié et sans toucher à CoaNIMM.

---

## Ce que VSBot n'est pas

- **Pas un remplacement de CoaNIMM** : 🐸 reste tel quel, avec ses ricochets, ses
  bonds, ses capteurs, ses dossiers autorisés. VSBot est un **ajout**.
- **Pas un IDE** : pas de terminal libre, pas d'exécution de programme, pas de
  gestion de dépôt Git. Il lit et propose des écritures de fichiers texte.
- **Pas un accès total au disque** : même ceinture de confinement, mêmes dossiers
  autorisés, et une protection particulière pour le dossier de l'application.
- **Pas un outil qui écrit en douce** : chaque écriture est proposée, montrée,
  puis validée.

---

## Place dans l'interface

- Icône : **🖥️** (bouton dans la barre du haut, à côté du 🐸 de CoaNIMM).
- Le sélecteur de mode de la zone de saisie (🗨 standard / 🐸 CoaNIMM / 🤖 Vibe)
  n'est **pas** modifié dans un premier temps : VSBot s'ouvre comme un panneau
  autonome, sur le modèle de la modale CoaNIMM.
- Nom du panneau : **VSBot — fichiers et code**.

## Les cinq briques, et leur état réel dans le code

### 1. Sélecteur explicite Plan / Act (le premier à faire)

**Besoin** — savoir si l'agent réfléchit ou s'il agit, au lieu de subir.

**Déjà là** — le moteur a les deux temps : `generate_plan()` (le modèle décrit ce
qu'il va faire, sans coder) et `run_generated()`. L'interface a déjà un patron de
sélecteur (les boutons `.agent-mode-btn`).

**À faire** — deux boutons dans le panneau, et une posture par défaut : **Plan
est le mode par défaut**, on ne passe en Act que sur décision explicite.

**Effort** — petit (surtout côté interface). **Risque** — aucun : le moteur ne
change pas.

### 2. Canevas d'exploration persistant

**Besoin** — voir l'arborescence d'un dossier, cliquer pour ouvrir un fichier,
repérer ce qui a bougé récemment.

**Déjà là** — `op_list_files()` (`modules/coanimm_ops.py`) liste un dossier en
lecture seule, autorisée partout. C'est la bonne brique.

**Attention** — `explore_directory()` (`modules/coanimm.py`) n'est **pas** un
listing : il demande au modèle d'écrire un script Python d'exploration. Ce n'est
pas ce qu'il faut ici.

**À faire** — une route d'arborescence (profondeur limitée, taille et date de
modification) et un panneau en `<ul>/<li>` cliquable, avec marquage des fichiers
récemment touchés.

**Effort** — moyen. **Risque** — aucun (lecture seule).

### 3. Écriture outillée + panneau de diff avant écriture

**Besoin** — le geste qui manque le plus quand on vient de Cline : voir
exactement ce qui va changer, **avant** que ce soit écrit.

**Déjà là** — rien d'exploitable : `coanimm_ops.py` sait lister, renommer,
déplacer, supprimer, créer un dossier et extraire du texte — **il n'écrit jamais
de contenu**. `file_writer.py` écrit des **documents** (TXT, DOCX, PDF, EPUB,
DAISY, MP3), pas du code. Et il n'y a **aucune coloration syntaxique** dans
l'interface (ni `hljs`, ni `prism`) : le code s'affiche en texte brut.

**À faire** — une couche d'écriture outillée (voir « Le socle » ci-dessous), un
diff unifié calculé avec `difflib` (inclus dans Python, aucune installation), et
un panneau de validation avant écriture. La coloration : au minimum préfixes `+`
et `-` sur les lignes ; une coloration syntaxique simple se décidera à ce
moment-là, elle n'est pas indispensable.

**Effort** — le plus gros morceau. **Risque** — modéré : c'est de l'écriture sur
disque, donc la ceinture de confinement doit couvrir ces nouveaux outils.

### 4. Annulation par étape (« Ctrl+Z »)

**Besoin** — pouvoir défaire une écriture qu'on regrette.

**Déjà là** — le patron existe côté conversation : route
`DELETE /api/chat/{thread_id}/last_assistant` avec son bouton.

**À faire** — garder le contenu précédent de chaque fichier modifié, sous un
identifiant d'exécution, et offrir « annuler cette exécution ».

**Dépend de la brique 3** : sans écriture outillée, NIMM ne sait pas quels
fichiers ont changé (aujourd'hui il ne détecte que les **nouveaux** fichiers
apparus dans son espace de travail, via `_scan_new_files`).

**Effort** — moyen, presque offert une fois la brique 3 faite.

### 5. Timeline d'exécution repliable

**Besoin** — relire le fil d'une tâche : consigne, plan, fichiers lus, diff
proposé, validation, sortie, fichiers produits.

**Déjà là** — un journal de tâches (`coanimm_history`, 50 entrées) et un journal
de sécurité. Mais le journal ne contient que `ts`, `consigne`, `status`,
`summary`, `returncode`, `files_count` : **ni la sortie, ni les fichiers lus, ni
la liste des fichiers produits** n'y sont conservés.

**À faire** — enrichir la collecte, puis la présenter. C'est un chantier
« collecter + afficher », pas seulement « afficher ».

**Effort** — moyen à gros. **À faire en dernier.**

---

## Le socle : des outils, pas des scripts

Aujourd'hui, quand NIMM agit sur des fichiers, il écrit un **script Python** et
l'exécute. Le résultat peut être bon, mais NIMM ne sait pas *ce qui* a été
touché : il compare la liste des fichiers avant/après et ne voit que les
nouveautés.

VSBot propose l'inverse : **le modèle appelle des outils nommés**, et c'est NIMM
qui exécute l'action. Chaque outil est petit, prévisible, journalisé.

| Outil | Ce qu'il fait | Confinement |
|---|---|---|
| `read_file(path, debut, fin)` | lire un fichier texte (avec plage de lignes) | lecture, partout |
| `list_tree(dossier, profondeur)` | arborescence d'un dossier | lecture, partout |
| `write_file(path, contenu)` | écrire ou écraser un fichier texte | dossiers autorisés |
| `replace_in_file(path, ancien, nouveau)` | remplacer un bloc ciblé | dossiers autorisés |

Ce choix a trois conséquences directes :

1. **Le diff devient trivial** : NIMM a l'ancien et le nouveau contenu.
2. **L'annulation devient triviale** : NIMM a gardé l'ancien contenu.
3. **La sécurité reste unique** : ces outils passent par le confinement existant,
   au lieu d'ouvrir une seconde porte à côté de la première.

Le fichier `modules/coanimm_ops.py` documente lui-même cette façon de procéder
(« créer une op_*, une entrée dans OPS_TOOLS, un nom dans OPS_NAMES et un cas
dans dispatch_op ») : le patron est prévu. Mais pour rester **en ajout** et ne
rien bousculer chez Nando, les nouveaux outils de VSBot vivent dans leurs propres
fichiers.

## Fichiers envisagés

| Fichier | Rôle | Nature |
|---|---|---|
| `modules/vsbot.py` | orchestration : lire, planifier, proposer, écrire | nouveau |
| `modules/vsbot_ops.py` | les outils (read_file, list_tree, write_file, replace_in_file) | nouveau |
| `main.py` | routes `/api/vsbot/...` | ajout ciblé |
| `frontend/index.html` | panneau VSBot | ajout ciblé |
| `frontend/app.js` | logique du panneau | ajout ciblé |
| `frontend/styles.css` | styles du panneau et du diff | ajout ciblé |
| `tests/test_vsbot.py` | vérifications permanentes (confinement, diff, annulation) | nouveau |

`modules/coanimm.py`, `modules/coanimm_ops.py` et `modules/coanimm_safety.py`
ne sont **pas modifiés** : VSBot les **appelle**.

---

## Garde-fous

1. **Confinement des écritures** : mêmes dossiers autorisés que CoaNIMM. Un refus
   est un refus, avec le chemin en clair.
2. **Le dossier de l'application est protégé** : VSBot ne doit pas pouvoir casser
   NIMM lui-même. Écriture refusée par défaut dans le dossier de NIMM ; si Laurent
   l'autorise un jour, ce sera un choix explicite et annoncé comme tel.
3. **Rien ne s'écrit sans validation** : en mode Act, le diff est affiché et
   l'écriture attend un accord.
4. **Journalisation** : chaque lecture refusée, chaque écriture, chaque annulation
   laisse une trace (journal de sécurité existant).
5. **Copie de retour arrière** : avant toute écriture, l'ancien contenu est
   conservé. Une copie datée vaut mieux qu'un regret.
6. **Pas de secrets** : un fichier `.env` ou portant une clé est refusé en
   lecture, et aucun contenu de clé ne doit se retrouver dans une réponse.

---

## Accessibilité (non négociable)

- Structure réelle : `<ul>/<li>` pour l'arborescence, `<details>` pour la
  timeline, jamais une `<div>` cliquable.
- Le diff n'est **pas** signalé par la couleur seule : préfixes `+` et `-` en
  début de ligne, et une annonce textuelle (nombre d'ajouts, de suppressions).
- `aria-live` pour les états (lecture en cours, écriture en attente, annulée).
- Toute icône porte un `aria-label` explicite.

---

## Ordre de mise en œuvre proposé

| Étape | Contenu | Nature |
|---|---|---|
| 1 | Le panneau VSBot (icône 🖥️, ouverture/fermeture) + le sélecteur Plan/Act | la plus légère, aucun risque |
| 2 | L'arborescence cliquable + la lecture d'un fichier (plage de lignes) | lecture seule |
| 3 | L'écriture outillée + le diff avant écriture | le cœur du sujet |
| 4 | L'annulation par étape | une fois 3 en place |
| 5 | La timeline repliable (enrichissement du journal) | en dernier |

Une brique par session, chacune utilisable tout de suite.

---

## Points à trancher

1. **Copies de retour arrière** : où ? Proposition : un dossier dédié
   (`data/vsbot_undo/`), plafonné en taille, plutôt qu'une table en base.
2. **Quel moteur** pour VSBot : le routage CoaNIMM existant, ou un routage dédié
   ? Un modèle qui écrit bien du code est préférable.
3. **Écriture dans le dossier de NIMM** : interdite par défaut, ou autorisée avec
   avertissement ?
4. **VSBot dans le sélecteur de mode du chat** (un quatrième bouton dans la zone
   de saisie), ou panneau autonome seulement, dans un premier temps ?

---

## Hors périmètre (pour l'instant)

Terminal libre, exécution de programmes, Git (commit, branche), renommage massif,
surveillance continue du disque, coloration syntaxique complète, écriture binaire
(images, archives, exécutables).



