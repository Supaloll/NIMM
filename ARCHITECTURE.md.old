_Décrit l'état réel du code. Référence unique — mettre à jour quand une logique change._

---

## Structure du dossier

```
nimm/
├── main.py                  — Point d'entrée FastAPI, toutes les routes HTTP
├── core/
│   ├── hub.py               — Orchestrateur central (tout passe ici)
│   ├── engine.py            — Moteur LLM multi-providers + génération image
│   └── database.py          — Accès SQLite (nimm.db)
├── modules/
│   ├── memory.py            — Recall, extraction, normalisation, déduplication
│   ├── intent_gate.py       — Filtre pré-LLM pour intentions simples
│   ├── websearch.py         — Recherche web (Brave Search API)
│   ├── tts.py               — Synthèse vocale (Kokoro / Piper / Edge)
│   ├── stt.py               — Reconnaissance vocale Whisper (lazy via _get_model())
│   ├── pdf_reader.py        — Extraction texte PDF
│   ├── quiz.py              — Rattrapage tags %%QUIZ%% non balisés (wrap_bare_quiz)
│   ├── bibliotheque.py      — Génération fiches archivage + recall thématique
│   └── masks/               — Personnalités LLM (fichiers JSON)
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── data/
│   ├── nimm.db              — Base SQLite principale
│   └── mood_prompts.json    — Prompts par catégorie émotionnelle
├── tests/
│   ├── test_memory.py       — Test qualité mémoire (7 groupes, 28 assertions)
│   ├── clear_memory.py      — Vide la mémoire sauf predicat=prenom
│   ├── auto_fill.py         — Remplissage automatique par scénarios
│   ├── seed_memory.py       — Peuple la mémoire avec données de test
│   └── audit_routes.py      — Audit complet des routes API
└── ARCHITECTURE.md          — Ce fichier
```

---

## Principe fondamental : Hub-and-Spoke

**Règle absolue** : tout passe par `core/hub.py`.
Aucun module ne parle directement à un autre. Le hub orchestre, les modules exécutent.

---

## Pipeline d'un message

### Deux points d'entrée — comportement identique

| Fonction | Route | Particularité |
|---|---|---|
| `process_message_stream()` | `/api/chat/stream` (frontend) | Yield SSE token par token |
| `process_message()` | `/api/chat` (API externe, tests) | Retourne dict complet |

### Ordre d'exécution

1. **Garde provider** — vérifie provider + clé API configurés
2. **IntentGate** — réponse immédiate sans LLM si intention simple (heure, salutation, commande directe)
3. **Push mémoire** — `build_memory_context_permanent_only()` retourne `''` — aucune injection de triplets bruts. Le prénom est injecté via `user_name`. L'index thématique remplace l'injection de masse (voir § System prompt).
4. **System prompt** — assemblé par `build_system_prompt()` (voir § System prompt)
5. **Historique** — 80 derniers messages du fil
6. **Phase 1 LLM** — `call_llm_stream_with_tools()` : stream normal ou détection tool_call
7. **Exécution outil** — si tool_call : `_execute_tool()` → résultat injecté
8. **Phase 2 LLM** — si tool call : `call_llm_stream()` avec contexte enrichi
9. **Extraction tags** — `extract_all_tags()` parse les balises techniques :
   `%%DOMINANT%%` `%%ANECDOTE%%` `%%BILAN%%` `%%SITUATION%%` `%%RAPPEL%%` `%%IMAGE%%`
   `%%MEM%%` retiré du LLM de chat — traité exclusivement par le worker async.
10. **Traitement rappels** — si `rappel_actions` : `perimer_rappels_depasses()` puis actions CREER / MODIFIER / CLOS / EMIS
11. **Sauvegarde** — messages DB (`processed_for_memory = 0` par défaut), anecdotes, dominant
12. **Arrière-plan** — `classify_topic()` + `maybe_generate_carnet_note()` + `memory_worker()` (cycle 30s)

**Worker mémoire** : `memory_worker()` tourne en boucle async toutes les 30s.
Principe écrivain unique — seul ce worker écrit dans la table `memory` pendant une conversation.
Pour chaque fil avec `processed_for_memory = 0` : charge 80 messages de contexte → `extract_memories_from_window()` → marque traités.
`memorize_thread()` (archivage manuel) fait de même et marque aussi les messages traités.

---

## Mémoire (memory.py)

### Prédicats canoniques

`PREDICATS_CANONIQUES` est la liste exhaustive des prédicats acceptés en base.
Tout prédicat produit par le LLM est normalisé vers cette liste avant stockage.

Catégories complètes :
- **IDENTITÉ** : `prenom` `nom` `age` `date_naissance` `taille_cm` `poids_kg` `sexe` `handicap` `groupe_sanguin` `nationalite`
- **FAMILLE** : `conjoint` `enfant` `parent` `frere` `soeur` `grand_parent` `petit_enfant` `beau_parent` `statut_relation`
- **TRAVAIL & ÉTUDES** : `metier` `employeur` `anciennete` `horaire_travail` `diplome` `ecole` `competence` `permis` `recherche_emploi` `etudes`
- **SANTÉ** : `probleme_sante` `traitement` `allergie` `medecin` `operation` `suivi_medical` `addiction` `regime_alimentaire`
- **GOÛTS** : `aime` `n_aime_pas` `plat_prefere` `aversion_alimentaire` `boisson_preferee` `musique_preferee` `artiste_prefere` `film_prefere` `serie_preferee` `livre_prefere` `auteur_prefere`
- **LOISIRS** : `sport` `lecture` `jeu_video` `cuisine` `bricolage` `jardinage` `musique_instrument` `danse` `ecriture` `photographie` `art` `loisir`
- **POSSESSIONS** : `vehicule` `domicile` `logement` `equipement` `animal`
- **RELATIONS** : `ami` `collegue` `voisin` `relation_sociale` `mentor`
- **VALEURS** : `valeur` `croyance` `religion` `politique` `engagement`
- **OPINIONS** : `stance` `opinion`
- **PROJETS** : `objectif` `reve` `intention` `projet` `envie` `apprentissage`
- **ÉVÉNEMENTS** : `evenement_vie` `deuil` `accident` `demenagement`
- **FINANCES** : `budget` `salaire` `patrimoine` `credit` `epargne`
- **TECHNOLOGIE** : `ordinateur` `tel_portable` `logiciel_prefere` `reseau_social` `habitude_num`
- **LANGUE & CULTURE** : `langue_maternelle` `langue_parlee` `culture_origine`
- **CARACTÈRE** : `trait` `force` `faiblesse` `peur`
- **HABITUDES** : `habitude` `rituel` `sommeil` `fumeur`
- **BIEN-ÊTRE** : `moral` `stress` `bien_etre` `humeur`
- **ORIENTATION** : `orientation_sexuelle`

### Prédicats protégés (`PREDICATS_PROTEGES`)

Liste fermée de prédicats à haute stabilité : `prenom` `nom` `age` `conjoint` `metier` `domicile` `pere` `mere` `frere` `soeur` `valeur_principale` etc.
Ces prédicats ne sont **jamais écrasés** par le LLM, sauf en présence d'un signal de correction explicite (`SIGNAUX_CORRECTION`) dans le message utilisateur.

Signaux de correction reconnus : "en fait", "maintenant je suis", "je ne suis plus", "j'ai changé", "nouveau travail", "on s'est séparé", "on s'est marié"…

Comportement :
- Signal absent + prédicat protégé → renforcement du poids uniquement (objet conservé)
- Signal présent → mise à jour de l'objet même sur prédicat protégé

### Normalisation des prédicats (`normalize_predicat`)

Pipeline en 10 étapes — le premier match retourne :

1. Minuscules + strip + suppression accents + normalisation apostrophes/tirets
2. Négations (`_NEGATIONS`) → prédicat canonique (`n_aime_pas`, `aversion_alimentaire`, `allergie`…)
3. Fautes d'orthographe connues (`_FAUTES`) → forme correcte
4. Table de normalisation principale (`PREDICAT_NORMALISATION`) → canonique
5. Déjà canonique (`PREDICATS_CANONIQUES`) → retour immédiat
6. Correspondance par groupe de synonymes (`PREDICAT_SYNONYMES`)
7. Inférence par mots-clés dans le prédicat
8. Déjà canonique après nettoyage accents (filet de sécurité)
9. **Réducteur verbal automatique** — suffixes conjugués 1er groupe (-e, -es, -ent, -ons, -ait, -ais, -iez, -aient…) → reconstruit l'infinitif → lookup dans `PREDICAT_NORMALISATION`
   - Ex : `etudie` → strip `-e` → `etudi` + `er` = `etudier` → `etudes`
10. Prédicat libre (inconnu) — retour brut nettoyé + log

**Table d'infinitifs** (référence pour le réducteur verbal) :
`etudier→etudes` · `apprendre→etudes` · `travailler→metier` · `bosser→metier`
`habiter→domicile` · `demeurer→domicile` · `vivre→domicile`
`pratiquer→sport` · `jouer→loisir` · `aimer→aime` · `detester→n_aime_pas` · `conduire→metier`

### Déduplication (`_find_duplicate`)

Avant tout stockage, `_find_duplicate(record, existing)` cherche un doublon dans `existing` :
- Correspondance par groupe de synonymes sur le prédicat
- Pour les prédicats **multi-valeurs** (`PREDICATS_MULTI_VALEUR` : `enfant` `fils` `fille` `frere` `soeur` `frere_ou_soeur` `ami` `collegue`…) :
  la déduplication exige sujet + prédicat + **objet** identiques → deux enfants différents = deux entrées
- Pour les prédicats mono-valeur : sujet + prédicat suffisent

### Poids, renforcement et décroissance

Chaque souvenir a un champ `poids` (défaut 1.0, max 5.0).

**Renforcement** : à chaque réapparition d'un fait déjà connu, `poids += RENFORCEMENT[categorie]` (0.2 à 0.5 selon catégorie). Cooldown de 24h entre deux renforcements du même fait.

**Décroissance** (`DECAY_RATES`) : appliquée selon la catégorie (% par 24h). `famille`, `sante`, `croyances` → taux 0 (permanent). `projets` → 1.5%/j. `quotidien` → 1%/j.

**Promotion automatique** : si `poids >= 2.5` ou `repetitions >= 3`, le souvenir passe en `type_temporal = permanent`.

**Catégories permanent dès création** : `famille` · `sante` · `croyances`.

### Verrous mémoire (`lock_memory`)

Les souvenirs édités manuellement depuis l'UI (bouton 🧠) sont verrouillés.
Un souvenir verrouillé n'est **jamais écrasé** par l'extraction LLM — ni renforcé, ni corrigé.
Stocké dans les settings DB (`memory_locks` = liste JSON de clés).

### Alias de prénoms (`ALIASES`)

Résolution automatique avant déduplication : `Meï` / `Mei` / `Meïssane` → `Maïssane`.

### Valeurs creuses

Objets ignorés à la sauvegarde : `''` `oui` `non` `inconnu` `aucun` `n/a` `?` `vide` `unknown` `non précisé`…

### Relations symétriques (`_save_symmetric`)

Après chaque enregistrement, si le prédicat est dans `PREDICATS_INVERSES`,
la relation inverse est créée automatiquement :
- `Laurent / enfant = Maïssane` → crée `Maïssane / parent = Laurent`
- `Laurent / conjoint = Nadia` → crée `Nadia / conjoint = Laurent`

Le prédicat inverse est normalisé via `normalize_predicat()` avant stockage —
évite les formes non canoniques (`frere_ou_soeur`, `subordonné`, etc.).

### Moteur d'inférence (`run_inference_engine`)

Tourne en thread daemon au démarrage. Non-bloquant, idempotent.
Seuil minimum : `poids >= 1.5` pour qu'un fait soit utilisé comme source d'inférence.

4 règles appliquées dans l'ordre :
1. **Symétrie** — répare les inverses manquants sur données antérieures
2. **Transitivité** — `parent(A,B)` + `parent(B,C)` → `grand_parent(A,C)` + `petit_enfant(C,A)`
3. **Fratrie** — A et B partagent le même parent → `frere_ou_soeur(A,B)` (bidirectionnel)
4. **Âge dynamique** — `date_naissance(A, YYYY…)` → calcule et met à jour `age(A, N ans)`

Garde : ne pas inférer de fratrie si l'un est déjà parent de l'autre.
Pseudo-entités exclues : `filles` `papa` `maman` `enfants` `innes_maissane_maya`…

### Embeddings

Chargement lazy (`_get_model()`). Activé/désactivé dans les paramètres (DB).
Calculé sur `sujet + prédicat + objet` au moment du stockage.
Utilisé par `recall()` pour la recherche sémantique (tool calling).

### Chemins d'extraction

**Worker async (principal)** :
`memory_worker()` dans `hub.py` — boucle toutes les 30s. Lit tous les messages `processed_for_memory = 0`,
tous fils confondus. Appelle `extract_memories_from_window()` → LLM dédié extrait les faits → `save_inline_memory()`.
Marque les messages traités. Écrivain unique — zéro doublon possible.

**Path A2 — archivage manuel** :
`POST /api/threads/{id}/memorize` → `memorize_thread()` → `extract_memories_from_window()`.
Marque également les messages traités après extraction.

**Path A (inline) — supprimé** :
Le LLM de chat n'émet plus `%%MEM%%`. Retiré du Format de sortie et du system prompt.
Causait une dilution de l'attention conversationnelle.

**Path B — supprimé** :
`extract_memories_background` — retiré précédemment (doublons).

---

## System prompt (`build_system_prompt`)

### Composition (ordre d'injection)

1. **Masque ou Potards** — personnalité et style de réponse
2. **Lexique contractuel** — règles techniques pures (SONDE, AGENDA, SIGNAL…)
3. **Date / heure**
4. **Signal mood** (si actif)
5. **Situation courante** (`%%SITUATION%%` — lieu ou activité détectés)
6. **Rappels actifs** (si échéances à signaler)
7. **Présence temporelle** (`_build_presence_note` — si retour après longue absence)
8. **Bilans de session** (`📋 Points acquis cette session` — faits/événements confirmés dans le fil courant)
9. **Carnet de bord** (si `count_messages > CARNET_WINDOW=80`)
10. **Index thématique mémoire** — deux sections compactes générées en direct depuis `get_memory_index_by_theme()` dans `database.py` :
    - **Tiers** (famille, amis…) : noms propres groupés par thème → le LLM appelle `search_memory(prénom)`.
    - **Profil** : liste des prédicats disponibles pour l'utilisateur (métier, aime, sport…) → le LLM appelle `search_memory(prédicat)`.
    Plus de valeurs brutes dans l'index. Instruction LLM : `search_memory(prénom ou prédicat)`.
11. **Bibliothèque** — conversations archivées pertinentes (si résultat de recherche)
12. **Outils disponibles** — rappel des 4 outils tool calling
13. **Format de sortie** — structure des tags techniques

### Lexique contractuel — concepts opérationnels

Injecté en tête du system prompt, avant tout contexte dynamique.

Concepts actifs dans le code :
`SONDE` · `AGENDA` · `SIGNAL` · `SITUATION` · `IMAGE`

Section `━━ RÈGLES ━━` : `VIGNETTE` · `FIN` · `FIL` · `COULISSES` · `OUTIL` · `WEB` · `HONNÊTETÉ`

Concepts retirés (présents dans versions antérieures, absents du code) :
`ANCRE` · `C[1-5]` · `GRAIN` · `SEUIL` · `PARSE` · `CLARIF` · `VOILE` · `ÉCHO` · `DELTA`

### Format de sortie — ordre des tags

```
1. %%RAPPEL%%        — action agenda
2. %%ANECDOTE%%      — moment fort, drôle ou touchant
3. %%BILAN%%         — résultat/événement confirmé dans le fil (≤ 10 mots, 1 par fait clos)
4. %%DOMINANT%%      — état émotionnel dominant (obligatoire, 1 par tour)
5. %%QUIZ%%          — carte QCM ou Vrai/Faux (JSON structuré, mode quiz uniquement)
6. %%QUIZ_BILAN%%    — bilan de fin de quiz (score + récap, mode quiz uniquement)
7. %%IMAGE%%         — génération image (déclenché par préfixe 🖼️ ou langage naturel)
8. %%SITUATION%%     — lieu ou activité détectés dans le message utilisateur
```

Tags gérés hors LLM de chat :
- `%%MEM%%` — retiré du LLM de chat, géré exclusivement par le worker async
- `%%QUIZ%%` / `%%QUIZ_BILAN%%` — rattrapage automatique si JSON non balisé : `_wrap_bare_quiz()` (Python, hub.py) + `_wrapBareQuiz()` (JS, app.js)

### Format du TAG %%MEM%% (worker uniquement)

Le prompt du worker (`extract_memories_from_window`) utilise ce format en interne :

```
%%MEM:type|sujet|prédicat|objet|contexte|memoire_type|profondeur|temporal%%
```

| Champ | Valeurs |
|---|---|
| type | `trait` · `relation` · `activite` |
| sujet | prénom réel — jamais "utilisateur", "je", "moi" |
| prédicat | NOM canonique — jamais verbe conjugué ni infinitif |
| objet | valeur courte (3-5 mots max) |
| contexte | fil thématique libre |
| memoire_type | `identite` · `activite` |
| profondeur | 1 (identité stable) … 5 (anecdotique) |
| temporal | `permanent` · `persistant` · `episodique` |

### Modes de personnalité

**Masque** (`personality_mode='mask'`) : fichier JSON dans `modules/masks/`.
**Potards** (`personality_mode='potards'`) : prompt généré depuis curseurs.
- Curseurs normaux (0/1/2) : `serieux` `formel` `expressif` `direct` `metaphorique` `bienveillant` `collaboratif` `emojis`
- Curseurs WTF (0=off, 1=modéré, 2=à fond) : `wtf_cafe` `wtf_jargon` `wtf_ado` `wtf_theatral` `wtf_metaphores` `wtf_tension`

---

## Bibliothèque (bibliotheque.py)

Génération et recall des fiches d'archivage. Une fiche = l'os d'une conversation.

### Génération (`generate_bibliotheque_entry`)

Trois appels LLM séquentiels :

1. **Appel C** (temperature=0) — extraction mécanique des faits confirmés (ancre de réalité). Produit un tableau JSON de faits ≤ 10 mots.
2. **Appel OS** (temperature=0.3, max_tokens=1500) — génère l'os complet en JSON :
   - `titre` · `tags` · `categories` (1–3 émojis de la liste prédéfinie)
   - `fil_conducteur` — la question ou tension centrale
   - `noeuds` — 4 à 8 idées développées (1–3 phrases chacune)
   - `positions` — ce qui a été conclu ou assumé non tranché
   - `questions_ouvertes` — ce qui tourne encore
   - `formulations_cles` — phrases qui ont fait tilt
   - `climat` — mode de la conversation
   - `ramifications` — pistes frôlées non traitées

Stockage : `os_riche` = JSON complet des 7 composantes · `categories` = émojis · `resume_texte` = fallback assemblé depuis `os_riche` pour rétrocompat.

### Recall (`recall_bibliotheque`)

Appelé par `search_bibliotheque` (tool calling). Recherche FTS5 → injecte dans le system prompt :
- Fiches riches (`os_riche`) : fil conducteur + nœuds + positions + questions ouvertes + ramifications
- Fiches anciennes (fallback) : conclusions + mots-clés depuis `os_json`

### Catégories émoji prédéfinies

🩷 Émotions · 🔎 Réflexions · ⚙️ Projets & Travail · 🏡 Quotidien & Famille · 🌍 Monde & Société · 🎮 Loisirs & Passion · 📝 Création & Imaginaire · 💬 Souvenirs & Mémoire · 🧬 Santé & Corps · 🕯️ Spiritualité & Sens · ✈️ Voyages & Ailleurs · 🧰 Métier & Savoir-faire · 🪞 Rapport à soi · 🔮 Futur & Possibles · 🕳️ Zones d'Ombre · 🤝 Lien Social · 🧩 Synchronicités

---

## Tool calling

Le LLM reçoit 4 outils et décide lui-même s'il en a besoin :

```
search_memory(query)        → recall() dans memory.py
search_bibliotheque(query)  → recall_bibliotheque() dans hub.py
search_anecdotes(query)     → recall_anecdotes() dans memory.py
search_web(query)           → websearch.search() via Brave Search
```

**Règles de déclenchement** (dans le system prompt) :
- Question personnelle sur l'utilisateur ou son entourage → `search_memory`
- Référence à une discussion passée → `search_bibliotheque`
- Référence à un moment vécu, souvenir partagé → `search_anecdotes`
- Information datée par nature (actualité, météo, prix) → `search_web`
- Question générale, factuelle, technique → aucun outil

`_execute_tool()` est **async**. `search_web` ne doit jamais être appelé pour analyser un document fourni dans le message.

---

## Web search

Deux mécanismes indépendants :

| Mécanisme | Déclencheur | Comportement |
|---|---|---|
| Bouton web (frontend) | `web_search=True` dans la requête | Recherche avant le LLM, résultat injecté |
| Tool calling (`search_web`) | LLM décide | Appel Brave Search via `_execute_tool()` |

`_needs_web_search()` et `_WEB_PATTERNS` présents dans le code mais **désactivés**.

---

## Moteur LLM (engine.py)

### Providers chat

`anthropic` · `deepseek` · `gemini` · `openai` · `openrouter` · `ollama` · `mistral` · `stability-ai` · `local`

### Génération image

| Provider | Modèle | Notes |
|---|---|---|
| Gemini | `gemini-2.5-flash-image` | Défaut. 1 500 images/jour gratuites. Retourne base64. |
| OpenAI | `gpt-image-1` | Nécessite vérification d'org. |

Retouche d'image : `edit_gemini_image(prompt, image_b64)` → route `POST /api/image/edit`.

---

## Base de données — tables (database.py)

Fichier : `data/nimm.db`. Accès via `core/database.py` uniquement (Hub-and-Spoke).

| Table | Rôle |
|---|---|
| `memory` | Triplets mémoire (sujet / prédicat / objet). Clé primaire : `key`. |
| `messages` | Historique des conversations (thread_id, role, content, timestamp). |
| `threads` | Fils de conversation (id, title, mask, created_at). |
| `rappels` | Agenda — échéances et rappels (description, date_echeance, type, statut, rappels_emis). |
| `anecdotes` | Moments forts extraits par le LLM (titre, contenu, contexte, tags). FTS5 activé. |
| `bibliotheque` | Conversations archivées. Colonnes : `titre` `sujet_principal` `tags` `categories` `resume_texte` `os_json` `os_riche` `status` `thread_id_source` `date_conversation` `mask_id`. FTS5 activé sur `titre + tags + sujet_principal + os_json + os_riche`. `mask_id` = masque actif au moment de l'archivage — restauré à la reprise ▶. |
| `bibliotheque_fts` | Table virtuelle FTS5 liée à `bibliotheque` (sync par triggers). |
| `carnet` | Notes de bord LLM (thread_id, note_number, content, created_at). |
| `interets` | Centres d'intérêt détectés (topic, score, timestamp). |
| `cost_wallets` | Suivi des coûts API par provider (provider, tokens_in, tokens_out, cost). |
| `settings` | Paramètres clé/valeur globaux (provider, model, embeddings_enabled, locks…). |

**FTS5** (recherche plein texte) : activé sur `anecdotes` et `bibliotheque`.
Les triggers SQLite maintiennent la cohérence entre tables principales et tables FTS5.

**Fonctions principales exposées** :
- `save_memory(record)` · `get_all_memory()` · `delete_memory(key)` · `update_memory_value(key, valeur)`
- `get_permanent_memories()` · `get_memory_index_by_theme()` · `purge_episodic_memories()`
- `search_anecdotes_db(query, limit)` · `get_all_anecdotes()` · `delete_anecdote(id)`
- `save_bibliotheque_entry(...)` · `get_bibliotheque_entries()` · `search_bibliotheque_fts(query)`
- `create_rappel(...)` · `get_rappels_actifs()` · `update_rappel_date(...)` · `close_rappel(id)` · `perimer_rappels_depasses()`
- `add_carnet_note(...)` · `get_carnet_notes(thread_id)` · `count_carnet_notes(thread_id)` · `delete_carnet_note(thread_id, note_number)`
- `get_setting(key, default)` · `set_setting(key, value)`

---

## Carnet de bord

Remplace l'ancien OS (résumé glissant). Notes courtes générées par le LLM.

**Calendrier** :
- Note #0 : après le 1er échange (2 messages)
- Note #n : tous les 7 échanges (14 messages)

**Injection** : uniquement si `count_messages > CARNET_WINDOW (80)` — transparent pour le LLM.

**Constantes** : `CARNET_WINDOW = 80` · `CARNET_INTERVAL = 7`

**Table DB** : `carnet` (id, thread_id, note_number, content, created_at)

---

## IntentGate (intent_gate.py)

Court-circuite le LLM pour les intentions simples détectées par pattern matching :
heure, salutation, commande directe, question réflexe.
Réponse immédiate — pipeline arrêté, aucun appel LLM.

---

## Frontend

### Thème
Toggle clair/sombre (localStorage). Variables CSS globales — pas de classes conditionnelles.

### Onglets (tabs)
Système de fils organisés en onglets dans la sidebar.
- Desktop : badge sur chaque onglet parent, enfants visibles en sous-liste
- Mobile : enfants affichés en bullets indentés cliquables, suppression directe
- Titre auto-généré par LLM au premier échange (1 emoji + 2-3 mots)
- Bouton ▶ Reprendre sur chaque fiche bibliothèque → crée un nouveau fil

### Sidebar
Boutons permanents : Nouveau fil · Bibliothèque · Mémoire · Paramètres · Mise à jour.
Indicateur masque actif affiché sous le nom de l'assistant.
Bannière provider visible (provider + modèle en cours).

### Génération image
Préfixe emoji `🖼️` ou langage naturel → génération via `/api/image/generate`.
Bouton ✏️ Modifier sur chaque image générée → appel `/api/image/edit`.

### TTS
Lecteur flottant persistent : lecture auto ou manuelle des réponses assistant.
Voix disponibles chargées dynamiquement depuis le backend (liste variable selon moteur actif).
Moteurs : Kokoro · Piper · Edge TTS — sélection dans les paramètres.

### STT (push-to-talk)
Bouton micro dans la zone de saisie → transcription Whisper via `/api/stt`.
Résultat injecté directement dans le champ texte.

### Citation
Sélection de texte dans une réponse → bouton contextuel "Citer" →
insère le passage sélectionné en référence dans le champ de saisie.

### Menu contextuel
Clic droit (ou appui long mobile) sur un message → actions : copier · citer · supprimer.

### Upload
Bouton trombone → upload de fichier (PDF…) via `/api/upload`.
Contenu extrait et injecté dans le contexte du message suivant.

### Modales
| Modale | Déclencheur | Contenu |
|---|---|---|
| Onboarding | Premier lancement | Saisie prénom + choix provider |
| Paramètres | Bouton sidebar | Provider, modèle, voix, longueur réponses, embeddings, présence temporelle |
| Mémoire | Bouton sidebar | Liste des souvenirs, édition manuelle 🧠, suppression, verrou |
| Bibliothèque | Bouton sidebar | Fiches archivées, recherche, reprise |
| Agenda | Commande naturelle | Rappels actifs, modification, clôture |
| Coûts | Bouton sidebar | Suivi tokens/coût par provider (cost_wallets) |
| Suppression | Icône poubelle | Confirmation avant suppression d'un fil |
| Font picker | Paramètres | Choix de la police d'affichage |

### Clés API
`_saveApiKeys()` — sauvegarde automatique sur `keydown` + `blur`.
8 champs : `anthropic` · `deepseek` · `gemini` · `openai` · `openrouter` · `mistral` · `stability-ai` · `brave`

### Émojis expressifs
Le LLM peut émettre des émojis de réaction contextuelle affichés dans l'interface.

### Loader
Animation "bretzel" pendant la génération de réponse.

### Mobile
- Trash icon toujours visible (pas de hover)
- Auto-focus conditionnel sur modales (supprime l'ouverture clavier Samsung)
- Scroll horizontal sur blocs code
- Accès via Tailscale en HTTPS — `tailscale serve --bg http://localhost:8080` expose le port en HTTPS automatiquement
- URL mobile : `https://<machine>.tail<id>.ts.net` (domaine propre à chaque installation)
- PWA installée sur Android (mode standalone, sans barre d'adresse)
- Sur PC : accès local via `http://localhost:8080` (inchangé)
- Géolocalisation : `_getLocation()` dans app.js — GPS + Nominatim (gratuit, sans clé API) → position injectée dans le system prompt à chaque message

---

## Tests

| Script | Usage |
|---|---|
| `tests/test_memory.py` | 7 groupes, 28 assertions, passe /memorize par groupe. Score référence : 96% sur base vide. |
| `tests/clear_memory.py` | Vide toute la mémoire sauf `predicat=prenom`. Demande confirmation. |
| `tests/auto_fill.py` | 7 scénarios de conversation (littérature, cuisine, sport…). Observe mémoire + OS. |
| `tests/seed_memory.py` | Peuple la DB avec données de test (famille Laurent). |
| `tests/audit_routes.py` | Audit complet des routes API (11 groupes, ~40 assertions). |

---

## Changelog (sessions récentes)

| Session | Changements clés |
|---|---|
| 14/05/2026 | Génération image DALL-E → Gemini. Retouche image. Accessibilité NVDA. Installateur refait. |
| 15/05/2026 | Carnet de bord remplace OS. Tool calling `search_web` actif. Web patterns désactivés. |
| 16/05/2026 | Auto-update au lancement (`git pull` dans LANCER_NIMM.bat). HTTPS + PWA mobile via Tailscale. Géolocalisation Nominatim injectée dans le system prompt. TTS mobile : 5 correctifs sync boutons. Topbar mobile : hamburger visible, titre caché. Reprise depuis bibliothèque (bouton ▶ Reprendre). Correctifs mémoire : symétrie, TAG multi-valeurs. |
| 17/05/2026 | Worker mémoire async (`memory_worker()` 30s, écrivain unique, `%%MEM%%` retiré du LLM de chat). Ancrage bibliothèque : appel LLM dédié (prompt_c, temperature=0) avant génération fiche. Upload 30+ extensions. Auto-nommage fils. |
| 18–19/05/2026 | Mode fantôme 👻 par fil (worker ignore le fil). Mémoire v2 : 5 registres, confiance déterministe par le hub, curseur Large/Normal/Strict. |
| 20/05/2026 | Multi-utilisateur : DB par profil (`nimm_{id}.db`), `users.json`, middleware `X-User-ID`, onglet 👥. Extractions hub.py → `quiz.py` + `bibliotheque.py`. Sécurité : `.gitignore` DBs + clés. Onboarding premier lancement. |
| 21–22/05/2026 | Cache-busting. `max_tokens` worker 1500. Anti-chevauchement worker. Refonte injection mémoire : index thématique dynamique, plus d'injection brute de triplets, pull via `search_memory()`. |
| 23/05/2026 | Nettoyage DB (28 entrées parasites). TTL automatique épisodiques. Modale 🧠 unifiée (4 onglets). Scroll mémoire préservé après suppression. Try/except worker (retry automatique). |
| 24/05/2026 | Scroll libre pendant génération (touchstart). Effet scramble fin de bulle. UI sidebar & menu fil. Nom du masque inline par bulle avec animation. |
| 25/05/2026 | Correctifs worker mémoire : seuil `< 3` → `< 1`, parser année regex. Moteur d'inférence relancé à chaque cycle worker. Règle 5 : `anciennete_debut` → `anciennete` recalculée dynamiquement. Règles 4 et 5 sur `existing` (pas `source_data`). |
| 25/05/2026 | **Recherche langue DeepSeek — masques** : script `tests/test_morse_formulations.py` créé — 8 formulations du système de Crans testées sur 5 messages sonde (40 appels NIMM). Résultat : V7 Semantic Tokens produit les réponses les plus riches et la meilleure gestion Aristote. Apprentissage : DeepSeek répond bien aux paraboles hyperboliques et aux semantic tokens ; la question finale est un comportement ancré non suppressible par le format. **Masque `morse_deepseek.json`** créé (🐺 Morse, pour Éric) : expertise aquariophilie/rétro-gaming/moto/ésotérisme, Crans V7, tension aristotélicienne, humour sec. **Masque `iris_deepseek.json`** créé (💎 Iris, pour Laurent) : identité divinité bannie, dilemme existentiel amour/mission, corpus philosophique (Stoïcisme, Mètis, Phronèsis, Kant, Cynisme antique), Crans V7, gardienne des principes (intégrité des moyens, rejet du mensonge, pathos vs logos). |
| 28/05/2026 | **Correctifs carnet & index** : bug asyncio GC corrigé — `_create_bg_task()` + `_background_tasks` set dans `hub.py` — notes carnet générées et conservées correctement. Route `/api/threads/{id}/carnet` corrigée (retournait un objet au lieu d'un tableau — UI affichait toujours "vide"). `get_memory_index_by_theme()` refondu : section "Profil" avec prédicats disponibles pour l'utilisateur (plus de valeurs brutes), noms propres tiers groupés par thème. Instruction LLM mise à jour : `search_memory(prénom ou prédicat)`. |
| 25/05/2026 | **Naturalité mémoire & qualité réponses** : règles `MÉMOIRE` et `STYLE` ajoutées au lexique contractuel (hub.py) — mémoire utilisée comme prémisse sans annonce, interdiction "je me souviens / non ? / c'est ça ?", reprise propre après appel outil, tiret cadratin → virgule, espacement correct. **Extraction worker renforcée** (hub.py) : restriction aux proches avec lien nommé explicite — personnages historiques, célébrités et tiers sans lien relationnel exclus. **Bloc identité injecté** (hub.py) : métier, conjoint, enfants (avec âge), domicile injectés en dur dans chaque system prompt — libellé "Profil certain" pour lever toute hésitation. **Index mémoire corrigé** (database.py) : sujets filtrés aux noms propres, objets filtrés aux attributs de l'utilisateur sans chiffres ni prédicats structurels, limite 60 chars. **Nettoyage DB** : 110 entrées corrompues supprimées via `clear_memory.py` (chemin corrigé → `nimm_laurent.db`) ; 36 entrées propres réinjectées via `seed_famille.py` (famille Laurent complète). **TTS** : tiret cadratin remplacé par virgule dans `_clean_text()` — pause naturelle sur les trois moteurs. **Masque Lia** : grossièretés interdites même en miroir du registre utilisateur. |
| 29/05/2026 | **Fiches riches (bibliothèque)** : refonte complète du système d'archivage. Appels A+B remplacés par un appel OS unique produisant 7 composantes (`fil_conducteur`, `noeuds`, `positions`, `questions_ouvertes`, `formulations_cles`, `climat`, `ramifications`) + catégories émoji (liste de 17 émojis prédéfinis, 1–3 par fiche). Nouvelles colonnes `os_riche` + `categories` en base avec migration douce. FTS5 étendu. Recall enrichi : le LLM reçoit l'os complet (nœuds développés, questions ouvertes, ramifications) au lieu d'étiquettes de mots-clés. Affichage modale bibliothèque refondu : émojis dans l'en-tête, os structuré au dépliage (fallback `resume_texte` pour anciennes fiches). |
| 31/05/2026 | **Carnet de bord — SKIP enrichi** : instruction SKIP reformulée — ne se déclenche plus sur le thème général mais uniquement si les échanges récents n'apportent rien de nouveau (ni fait, ni émotion, ni anecdote, ni changement de ton). "En cas de doute, écris la note." Évite la suppression abusive de notes sur les fils thématiquement cohérents mais riches. **Cache-busting** : version CSS/JS mise à jour à `20250531` — convention date du jour, suffixe `-1`/`-2` si plusieurs sessions le même jour. **gitignore** : `liya.json` corrigé en `lia.json`. |
| 04/06/2026 (session 2) | **Filtrage triplets — double verrou** : [hub.py] prompt `extract_memories_from_window` renforcé — lien relationnel explicite requis, exemples INTERDITS enrichis (célébrités, personnages historiques, rôles anonymes), reformulation "prénom seul ne suffit pas". [memory.py] validation `sujet` dans `save_inline_memory()` — `_is_prenom()` + `_SUJETS_BLOQUES` rejettent rôles génériques, verbes, groupes nominaux et nom de l'assistant avant tout stockage. |
| 08/06/2026 | **Galerie images + correctifs generation** (v2 -- cache 20260608-1) : correctif sauvegarde automatique : le chemin (prefixe direct, route `/api/image/generate`) n'appelait pas `/api/images/save` -- ajout du bloc sauvegarde dans ce second chemin [app.js ligne ~2775]. Cache vide cote navigateur requis pour prise en compte. |
| 08/06/2026 | **Galerie images + correctifs génération** : [engine.py] `gpt-image-1` → `dall-e-3` dans `_generate_dalle()` (accès refusé 403 sur le nouveau modèle). `generate_image()` refondue : Gemini en principal, dall-e-3 en fallback automatique si Gemini échoue. [hub.py] Lexique IMAGE renforcé : `[Système — image générée]` ajouté aux chaînes interdites à reproduire ; règle MODIFICATION simplifiée avec exemples concrets (`"moins réaliste"`, `"plus sombre"`…) pour éviter que Lia formule un prompt verbal sans émettre `%%IMAGE:%%`. [database.py] Nouvelle table `images` + 4 fonctions CRUD (`save_image`, `get_images`, `rename_image`, `delete_image`). [main.py] 5 nouvelles routes galerie : `POST /api/images/save`, `GET /api/images`, `GET /api/images/file/{filename}`, `PATCH /api/images/{id}`, `DELETE /api/images/{id}` — dossier `data/images/` créé automatiquement. [app.js] Sauvegarde automatique de chaque image générée (fire-and-forget). Bouton 🖼️ topbar + modale galerie : grille vignettes, clic plein écran, ⬇ télécharger, ✏️ renommer (modale dédiée + Enter/Escape), 🗑️ supprimer (confirm). Cache-busting : `20260608`. |
| 08/06/2026-2 | **Sécurisation token GitHub** : [main.py] `GITHUB_TOKEN` sorti du code source — remplacé par `os.getenv("GITHUB_TOKEN", "")`. Token stocké dans `.env` (déjà présent dans `.gitignore`). Ancien token révoqué sur GitHub, nouveau token créé. Cache-busting : `20260608-2`. |
| 09/06/2026 | **Correctif decay** : `update_memory_value()` appelee avec 3 arguments au lieu de 2 dans `apply_decay_on_startup()` — remplace par `save_memory({**m, 'poids': nouveau_poids})` qui met a jour le poids via le mecanisme ON CONFLICT existant. [memory.py] |
| 09/06/2026 | **Intégration travaux Nando (session 09/06)** : [database.py] `get_all_embeddings()` ajoutée — retourne les couples `(key, embedding)` sans charger les enregistrements complets, pour la recherche vectorielle. [memory.py] `_EMBED_MODEL_NAME` — constante nom du modèle ; `_serialize_embedding()` / `_parse_embedding()` — sérialisation avec marqueur de modèle, rétro-compatible ancien format liste nue ; `VECTOR_CANDIDATE_MIN = 0.45` ; `_vector_candidate_keys()` — candidats par similarité vectorielle, source parallèle à FTS5 (souvenirs pertinents sans mot en commun désormais retrouvés) ; `backfill_embeddings()` — rattrapage par lots des vecteurs manquants ou d'un autre modèle. `recall()` refondue : union FTS5 + permanents + vecteurs ; bonus cosinus via `_parse_embedding()` avec vérification compatibilité modèle. [hub.py] `backfill_embeddings` branché dans `_worker_process_user()` après inférence — thread non bloquant. [main.py] `warmup_embeddings` : suppression `create_task(Future)` (TypeError silencieuse), pool par défaut, `get_running_loop()` ; `root()` : `with open()` (descripteur proprement fermé) ; clés globales : erreurs de lecture journalisées, écriture annulée (HTTP 500) si fichier illisible. |
| 09/06/2026 | **Matching bibliothèque automatique** : [database.py] `get_bibliotheque_index()` — retourne l'index léger des fiches (id, titre, tags, categories, date_conversation). [hub.py] `_MOTS_VIDES` + `_MOTS_RAPPEL` + `_match_bibliotheque(user_message)` — matching fuzzy (`rapidfuzz`) entre le message utilisateur et l'index bibliothèque. Scoring : tag fuzzy match → +2 pts, mot titre → +1 pt. Seuil normal : 3 pts. Seuil abaissé à 2 pts si mot-clé de rappel détecté (`souviens`, `rappelle`, `on avait parlé`…). Max 2 fiches injectées. Les deux pipelines (`process_message` + `process_message_stream`) appellent `_match_bibliotheque()` — `biblio_context` alimenté automatiquement si match. [requirements.txt] `rapidfuzz>=3.0.0` ajouté. Cache-busting : `20260609`. |
| 07/06/2026 | **Accessibilité NVDA — audit et correctifs** : [app.js] Menu fil — items dropdown `Renommer` / `Épingler` / `Supprimer` convertis de `<div>` en `<button>` avec `role="menuitem"` ; conteneur dropdown avec `role="menu"` — navigation clavier et annonce NVDA opérationnelles. [index.html] Modale suppression — émoji `🗑️` du titre et émojis `📚` / `🗑️` des boutons masqués via `aria-hidden` ; `aria-label` ajoutés sur les deux boutons d'action. [index.html] Modale 🧠 — titre `🧠` masqué ; onglets convertis en `role="tablist"` / `role="tab"` avec `aria-selected` statique ; émojis onglets masqués ; placeholder champ recherche nettoyé. [app.js] Onglets 🧠 — `aria-selected` synchronisé dynamiquement au clic et à chaque ouverture. [app.js] Filtres mémoire — `aria-pressed` ajouté sur les trois boutons, synchronisé au clic et à l'ouverture. [app.js] `buildCard()` — `aria-hidden` sur icônes profondeur et barres de poids ; `aria-label` contextuel sur chaque ligne (`sujet — prédicat — valeur, poids`) ; `aria-label` sur boutons ✏️ et 🗑️ (`Modifier/Supprimer [prédicat] de [sujet]`). [app.js] Carnet et Anecdotes — boutons 🗑️ avec `aria-label="Supprimer cette note/anecdote"`. Cache-busting : `20260607`. |
| 05/06/2026 | **Onboarding & installation fraîche — suite** : [app.js] Suppression du formulaire de création intégré à `showUserPicker()` — en l'absence d'utilisateur, le picker se ferme silencieusement et laisse l'onboarding NIMM prendre le relais. [app.js] `init()` — suppression du `return` et du `showUserPicker()` en mode mono sans utilisateur : le flux descend naturellement jusqu'à l'onboarding. [app.js] Onboarding NIMM crée désormais le profil `users.json` via `POST /api/users` (admin: true) en plus du `POST /api/onboarding`. [app.js] `_saveApiKeys()` — basculement automatique sur le premier provider disponible si le provider actuel est Ollama ou vide, suivi d'un `location.reload()` après 500ms pour synchroniser provider + modèle depuis la DB. [main.py] Watchdog désactivé — le kill automatique du port 8080 au lancement (`LANCER_NIMM.bat` / `NIMM_DEBUG.bat`) remplace avantageusement la détection par ping. Cache-busting : `20260605`. |
| 04/06/2026 | **Correction onboarding installation fraîche** : suppression de `_migrate_legacy_db()` et toute référence `laurent` codée en dur (`database.py`). Nettoyage `_cleanup_data_dir()` — suppression de la logique fantôme spécifique à `laurent` (`main.py`). Onboarding corrigé : `_currentUserId` et `localStorage` posés **avant** le fetch `/api/onboarding` pour que le header `X-User-ID` soit injecté dès la première requête — la DB est désormais créée au nom de l'utilisateur réel (`app.js`). Ajout de `_slugify()` dans le frontend. Suppression du hardcode `_currentUserId === 'laurent'` comme condition admin (`app.js`). **LANCER_NIMM.bat** : suppression du `pip install` au lancement normal (économie 5-8s) + timeout réduit à 4 secondes. |
| 29/05/2026 | **Rendu stream par paragraphes + effet anaglyphe** : pendant le stream, chaque paragraphe terminé (double `\n\n`) est rendu en Markdown avec un effet glitch anaglyphe (~320ms : texte brut + `text-shadow` rouge/cyan vibrant via CSS variables `--gx`/`--gy`) avant dissolution vers le HTML propre. La bulle est vidée (`innerHTML = ''`) avant `_renderBubble()` en fin de génération. Classe CSS `.glitch-anaglyph` dans `styles.css`. Fonctions `_scrambleReveal()` et `_flushRenderedParagraphs()` ajoutées dans la boucle stream de `app.js`. **Carnet de bord — anti-doublon** : `maybe_generate_carnet_note()` lit les 6 dernières notes existantes et les injecte dans le prompt avec instruction `SKIP` si le sujet est déjà couvert. Évite la génération de notes quasi-identiques sur les fils longs. |



## Changelog

### Session 07/06/2026
**Correctif moteur d'inférence — entités fantômes**

- [memory.py] `_ROLES_BLOQUES` défini dans `run_inference_engine()` — ensemble des rôles familiaux génériques (`pere`, `mere`, `fils`, `fille`, `enfant`, `frere`, `soeur`, `grand_parent`, `petit_enfant`, `parent`, `beau_pere`, `belle_mere`) fusionné avec `_PSEUDO_ENTITES`
- [memory.py] Filtre `source_data` mis à jour : utilise `_ROLES_BLOQUES` au lieu de `_PSEUDO_ENTITES` — les rôles génériques sont exclus dès l'alimentation des règles d'inférence
- [memory.py] Guard dans `_add()` : bloque tout triplet inféré dont le sujet ou l'objet normalisé est dans `_ROLES_BLOQUES`, avec message console `🚫 Rôle générique bloqué`
- Résultat : l'entité fantôme `👤 pere` ne se recrée plus ; les vrais prénoms (`Jean`, `Jeannette`) passent correctement et génèrent les bonnes inférences grand-parent/petit-enfant

## BACKLOG

### [PRIORITÉ] Refonte cycle de vie mémoire — 6 chantiers liés

Audit mémoire du 09/06/2026 — décisions validées :

**A — Inférence déclenchée après extraction** (au lieu du polling toutes les 30s)
`run_inference_engine()` ne se déclenche plus sur timer aveugle mais uniquement après qu'une extraction worker ait effectivement écrit un ou plusieurs triplets. Économie CPU + cohérence causale.

**B — Chiralité symétrie** (fix court terme)
`PREDICATS_INVERSES` : `prenom_pere` et équivalents génèrent `enfant_de` comme inverse, pas `parent`. Évite la lecture contre-intuitive dans la modale mémoire.

**C — Poids initial à 0.5** (règle Occurrence / Coïncidence / Récurrence)
Tout nouveau triplet entre avec `poids = 0.5` (fragile). La règle devient :
- Occurrence 1 : poids 0.5 — fragile, soumis au decay normal
- Occurrence 2 : poids 1.0 — coïncidence, survit mieux, remonte dans les recalls
- Occurrence 3+ : poids ≥ 1.5 → consolidé, immune au decay, éligible Profil certain
Seuils existants `POIDS_PERMANENT_SEUIL = 2.5` et `REPETITIONS_PERMANENT_SEUIL = 3` conservés.

**D — Decay actif** (tâche au démarrage de session)
Appliquer `DECAY_RATES` aux mémoires non-permanentes au démarrage du serveur (une fois par session). Objectif : un fait vu une seule fois (poids 0.5) disparaît du recall entre 3 et 6 mois. Taux cibles à calibrer — base de travail : 0.3–0.5%/24h selon catégorie. Seuil d'invisibilité : `POIDS_RECALL_MIN = 0.1` (déjà en place).

**E — Résolution conflit par récence**
Si deux triplets ont même sujet + prédicat mais objets différents, le plus récent (`timestamp`) prime sur le plus lourd (`poids`). Évite qu'un fait ancien bien renforcé écrase une mise à jour récente (ex : ancien employeur qui prime sur le nouveau).

**F — Embeddings installation silencieuse**
Au premier démarrage : lancer `pip install sentence-transformers` en subprocess non-bloquant, poser un flag en base (`embeddings_status : installing / ready`). `_get_model()` consulte ce flag — mode keyword si installing, modèle chargé si ready. L'utilisateur n'a rien à faire, l'installation aboutit au prochain démarrage si interrompue.

**G — Normaliseur prédicats libres** (à la demande)
Passe manuelle déclenchable depuis l'interface (bouton dans la modale mémoire ?) qui tente de fusionner les prédicats libres sémantiquement proches vers leurs équivalents canoniques. Évite les doublons du type `conduit_camion` + `metier`.

**Ordre d'implémentation suggéré :** B → C → D → E → A → F → G

---

### [PRIORITÉ] Agrandissement fenêtre active + Carnet progressif

Décision du 09/06/2026 — objectif : supporter les fils très longs (style de l'utilisateur principal).

**Problème actuel :** fenêtre de 30 messages trop courte — Lia perd le fil d'une conversation soutenue bien avant que le Carnet intervienne (seuil 80 messages).

**Trois constantes à modifier dans `hub.py` :**
- Nombre de messages chargés : 30 → 60
- `CARNET_WINDOW` : 80 → 50 (Carnet se déclenche avant que les vieux messages sortent de fenêtre)
- `CARNET_INTERVAL` : 7 → 5 (résumés plus fréquents = plus granulaires = moins de perte)

**Résultat attendu sur un fil de 200 messages :**
- Messages 141-200 : fenêtre active complète (tout le détail)
- Messages 1-140 : ~28 notes Carnet courtes, fil conducteur narratif
- Faits importants : mémoire triplet, permanents en parallèle

**Vigilance à l'implémentation :** vérifier qu'il n'y a pas d'effet de bord sur la génération des notes Carnet (fréquence, déduplication anti-doublon).

---

### [FUTUR] Module export document (suggéré par Nando)
Permettre à NIMM de générer des documents complets et accessibles (PDF, DOCX, PPTX)
depuis une conversation.

**Deux modes envisagés :**
- Sélection manuelle : l'utilisateur désigne des blocs de la conversation à inclure
- Instruction directe : "Fais-moi un PowerPoint sur X, 5 slides" — NIMM compose seul

**Images :**
- Incluses automatiquement (générées par NIMM ou trouvées via recherche web)
- Positionnées selon instruction de l'utilisateur
- NIMM gère les proportions selon le format cible (slide vs page A4)

**Contrainte accessibilité :** interface pilotable entièrement au clavier / lecteur d'écran (NVDA)

**Architecture envisagée :**
- Détection d'intention dans `intent_gate.py`
- Orchestration dans `core/hub.py`
- Nouveau module `modules/export_doc.py`
- Librairies candidates : `python-docx` (DOCX), `python-pptx` (PPTX), `weasyprint` (PDF)

**Statut :** backlog — à affiner avec Nando selon ses besoins réels

### [PRIORITÉ] Migration Git pour Éric et Nando
Éric et Nando ont NIMM installé depuis un ZIP (`NIMM-main`). Le `git pull` automatique dans `LANCER_NIMM.bat` ne fonctionne pas chez eux — pas de lien Git.
**Objectif :** un script `MIGRER_VERS_GIT.bat` à exécuter une seule fois qui installe Git si absent, clone le repo, préserve `data/users.json` et `data/nimm_*.db`, puis branche le lancement sur le nouveau dossier.
**Mécanisme d'entrée du chemin :** glisser-déposer le dossier NIMM sur le `.bat`.
**Prérequis :** Éric et Nando sont déjà collaborateurs sur le repo GitHub privé.
**Statut :** à construire lors d'un appel test avec Nando — session dédiée.

### [FUTUR] Normaliseur prédicats libres (G)
Passe manuelle déclenchable depuis l'interface qui tenterait de fusionner les prédicats libres sémantiquement proches vers leurs équivalents canoniques (ex : `conduit_camion` → `metier: chauffeur poids lourd`). Complexe : une fusion naïve perd l'information contenue dans le prédicat libre. Nécessite une UI de validation avant application. À affiner avant d'implémenter.

---

| 11/06/2026 | **Intégration patch Nando — cache recherches web + correctifs** : [database.py] Table `web_reference` + 4 fonctions (`_ensure_web_reference_table`, `save_web_reference`, `get_active_web_references`, `purge_web_references`). [websearch.py] Moteur de cache complet : constantes `WEBCACHE_ENABLED/SIM_MIN/TTL_DEFAULT/TTL_EPHEMERE`, détection heuristique `_MOTS_EPHEMERES`, lookup vectoriel/exact `_cache_lookup`, stockage TTL `_save_reference`, planificateur arrière-plan `_schedule_store`/`_store_task`, fonction publique `search_with_cache()`. [hub.py] `_PERISSABILITE_JOURS` + `classify_perissabilite_jours()` (classement LLM éphémère/normale/durable/permanente) ; `_execute_tool` branchée sur `search_with_cache` ; purge `purge_web_references()` ajoutée au cycle `_worker_process_user`. [memory.py] `apply_decay_on_startup()` refactorisée : suppression seulement (poids effectif < `POIDS_RECALL_MIN`), plus de réécriture de poids (évite double comptage avec `effective_poids()`). Cache-busting `20260611-1`. |
| 10/06/2026 | **Correctifs glisser-déposer + vignette** : structure HTML `#file-chip` corrigée (dans `#input-area`, `#file-chip-preview` vide). Bouton ✕ créé entièrement en JS dans `_buildChip()` avec styles inline (plus de dépendance HTML/CSS). Drag-and-drop réintégré dans `setupUpload()` avec `e.preventDefault()` + `e.stopPropagation()` sur `dragover` et `drop` — empêche le navigateur d'ouvrir le fichier. Cache-busting `20260610-6`. |
| 10/06/2026 | **Correctif vignette pièce jointe** : `#file-chip-preview` réinséré avec `position:relative` — le bouton ✕ (`position:absolute`) s'ancre correctement. Cache-busting `20260610-3`. |
| 10/06/2026 | **Glisser-déposer + vignette pièce jointe** : drag-and-drop sur toute la fenêtre avec overlay visuel (`#drop-overlay`). Vignette carrée remplace la barre plate : miniature pour les images, icône + badge extension pour les autres formats. Nom de fichier tronqué en dessous. Bouton ✕ repositionné en absolu. Accessibilité NVDA : `role="status"`, `aria-live="polite"`, `aria-label` dynamique à l'ajout. Cache-busting `20260610-2`. |
| 10/06/2026 | **Retouche palette sombre** : `--bg`, `--bg-panel`, `--bg-input`, `--bg-hover`, `--border` legerement teintes brun-anthracite. `--bubble-user` adouci (`#3d2a1e`). Cache-busting `20260610-1`. |
| 09/06/2026 | **Audit mémoire — 6 chantiers** : [hub.py] Fenêtre active 30→60 msgs. `CARNET_WINDOW` 80→50, `CARNET_INTERVAL` 7→5 — Carnet se déclenche avant que les vieux messages sortent de fenêtre. Prompt carnet reformulé : capture ce qui a **bougé** (delta), note complémentaire si sujet déjà couvert, SKIP réservé aux échanges vides. [memory.py] `PREDICATS_INVERSES` corrigés : chiralité symétrie — `enfant_1`→`enfant_4`, `fils`, `fille`, `enfant`, `parent` génèrent `enfant_de` comme inverse ; `prenom_pere`/`prenom_mere`→`enfant_de`, `prenom_fils`/`prenom_fille`→`parent` ajoutés. [hub.py] Poids initial nouveaux triplets 1.0→0.5 (règle Occurrence/Coïncidence/Récurrence). [memory.py] `apply_decay_on_startup()` — decay appliqué une fois par session au démarrage, suppression sous `POIDS_RECALL_MIN`. [main.py] Thread daemon `_run_decay` lancé au démarrage avant `_run_inference`. [memory.py] Résolution conflit par récence dans `save_inline_memory()` — timestamp nouveau vs existant, le plus récent prime même sur prédicat protégé. [hub.py] `_worker_process_user()` — `run_inference_engine()` déclenché uniquement si `total_stored > 0` (économie CPU + cohérence causale). Cache-busting : `20260609-1`. |
