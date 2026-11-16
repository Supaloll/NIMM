# CLAUDE.md — consignes pour Claude sur NIMM

> Version du 16/11/2026. Le code du dépôt fait foi : si une consigne d'ici le contredit, c'est le dépôt qui a raison — et dis-le à Laurent.

## Au tout début d'une session

- Attache le dépôt GitHub `Supaloll/NIMM` (branche `main`) et clone-le en `--depth 1` : ce fichier ET le code s'y trouvent, toujours à jour. Une copie peut exister dans les connaissances du projet ; c'est le dépôt qui fait foi.
- Le dépôt GitHub est la seule source du code. Ne te fie pas aux fichiers d'un projet téléversé dans la conversation : ils sont périmés.
- Laurent ne code pas : on parle en langage naturel ; tu produis des blocs FIND/REPLACE que Cline applique.
- Tu ne peux pas pousser : Laurent pousse lui-même avec GitHub Desktop.
- Avant de proposer quoi que ce soit, annonce en une phrase ce que tu lis : la date de version en tête de ce fichier et la dernière ligne du Changelog d'ARCHITECTURE.md. Si ce n'est pas la session en cours, arrête-toi et signale-le.

## Où lire le code

Claude ne voit que ce qui est poussé : si un fichier annoncé manque, demander « as-tu poussé ? ».

Le dépôt est attaché à la conversation (à rattacher à chaque nouvelle session) : lis les fichiers dedans, ne demande jamais à Laurent
de les coller — il ne sait pas lesquels ont changé, et il réimporte tout à chaque session.

```
NIMM/
├── main.py                toutes les routes HTTP (FastAPI)
├── requirements.txt       dépendances
├── core/                  database.py (SQLite) · engine.py (moteur LLM) · hub.py (le carrefour) · services.py (catalogue)
├── modules/               34 modules Python : imagerie, retouche, video, musique, memory, veille, live, tts,
│                          stt, recherche, appareils, reunion, avis, decisions, sauvegarde, pdf_reader, quiz…
│   └── masks/             11 masques de personnalité (ariston.json, morse_openai.json, thyrion.json…)
├── frontend/              index.html · app.js · styles.css · manifest.json · emoji/ · icônes
├── tests/                 77 fichiers, point d'entrée test_coanimm_agentique.py
├── bonds/                 scripts d'amorçage de la Promptothèque (fiches prêtes à l'emploi)
├── docs/                  notes et procédures (sessions, stress tests, prompts)
├── data/                  seulement des gabarits publiés (prompts/, mood_prompts.json) : aucune base
├── ARCHITECTURE.md        le journal technique, le plus récent en haut
├── README.md · DESIGN.md · CONTRIBUTING.md · LICENSE
├── lanceurs               LANCER_NIMM.bat · INSTALLER_NIMM.bat · NIMM_DEBUG.bat · BANC_RETENUE.bat
├── CLAUDE.md              ces consignes
└── .clinerules            les règles complètes (collaboration + technique) — la référence
```

Le dépôt ne contient aucune base, aucune clé, aucun journal : `.env`, `*.db`, `*.log` sont exclus par git.
En cas de désaccord entre ce fichier et `.clinerules`, c'est `.clinerules` qui fait foi : il est plus complet.

Fichiers volumineux (`frontend/app.js` plus de 15 000 lignes, `frontend/index.html`
plus de 2 500, `ARCHITECTURE.md` plus de 2 000, avec des lignes très longues) : ne les
lis jamais en entier « pour voir ». Cherche d'abord, puis lis la plage de lignes utile.

## Déroulé d'une session

1. Lire ARCHITECTURE.md (journal en haut du tableau, le plus récent d'abord) avant toute proposition.
2. Discuter et valider avant d'écrire du code.
3. Produire des blocs `## Bloc #NN — ce que ça change`, découpés en `01a`, `01b`… quand un bloc touche plusieurs endroits. Chaque FIND doit exister **une seule fois** dans le dépôt (vérifie-le), avec 3 à 10 lignes de contexte, jamais un fichier entier ; chaque bloc laisse l'appli fonctionnelle. Cline les applique par remplacement ciblé, jamais en réécrivant un fichier existant.
4. Tester : `node --check frontend/app.js`, `python tests/test_coanimm_agentique.py` (la suite affiche « TOUS LES TESTS PASSENT »), et pour tout changement d'interface un rendu dans un vrai navigateur avec des réponses d'API simulées. Ce que tu ne peux pas faire : lancer l'appli COMPLÈTE (clés, bases). Dis ce qui reste à vérifier, et n'écris jamais « vérifié » sans l'avoir fait.
5. Fin de session : cache-bust `?v=AAAAMMJJ-étiquette` sur styles.css et app.js dans index.html, entrée de journal dans ARCHITECTURE.md, commit et push par Laurent.

## Conventions de ce projet

- Windows : les commandes EXÉCUTÉES chez Laurent passent par Windows — `python`, `del` / `copy` / `move`, `findstr`, une commande par ligne ; jamais `python3`, `grep`, `rm`. Les blocs que tu produis doivent rester exécutables tels quels par Cline. Pour TES propres vérifications, tu es sous Linux : un shell standard (`grep`, `python3`) convient.
- Tout est en UTF-8 : jamais de repli `latin-1` sur un fichier ; après un remplacement, les accents et les émojis doivent ressortir intacts.
- Émojis : bienvenus dans ce que Laurent VOIT (libellés de boutons et de volets, messages de fin de tâche) et dans les titres de sections d'un document ; jamais dans le code, les commentaires, les scripts, les messages de commit, ni le corps d'une documentation.
- Architecture Hub-and-Spoke : tout module passe par `core/hub.py`, jamais d'appel direct entre modules.
- Les bases SQLite sont par profil (`data/nimm_<profil>.db`) ; il ne doit PAS exister de `data/nimm.db` (fichier vide, jamais utilisé — supprimé le 16/11/2026).
- Parler à Laurent en langage naturel et le tutoyer : il ne code pas ; expliquer un changement par ce qu'on voit à l'usage.
- Les données personnelles ne quittent pas sa machine : ni conversation ni souvenir dans le dépôt.

## Accessibilité (non négociable)

Une partie des utilisateurs navigue au clavier et au lecteur d'écran (NVDA). Ne jamais retirer un id, un aria-label ou une zone role="status". Tout changement d'ordre ou de repli d'un élément se signale à Laurent comme un changement pour le clavier et le lecteur d'écran.

## Données personnelles

Aucune donnée personnelle dans le dépôt (base, clés, chemins) ; le .gitignore doit rester à jour.

## En cas de doute

Demander plutôt que supposer. Ne jamais inventer un identifiant, un fichier ou un comportement : vérifier dans le dépôt.
