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
│   ├── coanimm.py           — Agent exécution code Python (run_script, run_generated, generate_plan, explore_directory)
│   ├── enrichissement.py    — Ingestion documents web/fichiers → zone de référence RAG
│   ├── export_nimm.py       — Export messages marqués (txt, docx, pdf, rtf, odt, epub, mp3)
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
- **LOISIRS** : `sport` `lecture` `jeu_video` `cuisine` `bricolage` `jardinage` `musique_instrument` `danse` `ecriture` `photographie` `art` `loisir` `anciennete_pratique`
- **POSSESSIONS** : `vehicule` `domicile` `logement` `equipement` `animal`
- **RELATIONS** : `ami` `collegue` `voisin` `relation_sociale` `mentor`
- **VALEURS** : `valeur` `croyance` `religion` `politique` `engagement`
- **OPINIONS** : `stance` `opinion`
- **PROJETS** : `objectif` `reve` `intention` `projet` `envie` `apprentissage`
- **ÉVÉNEMENTS** : `evenement_vie` `deuil` `accident` `demenagement` `anecdote`
- **FINANCES** : `budget` `salaire` `patrimoine` `credit` `epargne`
- **TECHNOLOGIE** : `ordinateur` `tel_portable` `logiciel_prefere` `reseau_social` `habitude_num`
- **LANGUE & CULTURE** : `langue_maternelle` `langue_parlee` `culture_origine`
- **CARACTÈRE** : `trait` `force` `faiblesse` `peur` `qualite`
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

Modèle `paraphrase-multilingual-MiniLM-L12-v2`, chargement lazy (`_get_model()`),
activé/désactivé dans les paramètres (DB). Vecteurs normalisés (cosinus = produit scalaire).

Calculé sur `sujet + prédicat + valeur + objet` au stockage. Chaque vecteur est
sérialisé **avec le nom du modèle** (`_serialize_embedding` / `_parse_embedding`) :
un changement de modèle est détecté, les vecteurs d'un autre modèle sont ignorés au
scoring et recalculés (l'ancien format « liste nue » reste lu, rétro-compat).

`recall()` combine **deux sources de candidats** : FTS5 (mots-clés) et similarité
vectorielle (`_vector_candidate_keys` — parcours force brute de tous les vecteurs via
`get_all_embeddings()`), plus les permanents. La recherche par sens retrouve donc aussi
les souvenirs sans mot commun avec la requête. Seuil d'entrée : `VECTOR_CANDIDATE_MIN`.

Rattrapage : `backfill_embeddings()` recalcule par lots (50/cycle) les vecteurs
manquants ou issus d'un autre modèle ; déclenché par `memory_worker()` à chaque cycle,
dans un thread.

### Chemins d'extraction

**Worker async (principal)** :
`memory_worker()` dans `hub.py` — boucle toutes les 30s. Lit tous les messages `processed_for_memory = 0`,
tous fils confondus. Appelle `extract_memories_from_window()` → LLM dédié extrait les faits → `save_inline_memory()`.
Marque les messages traités. Écrivain unique — zéro doublon possible.
En fin de cycle : `backfill_embeddings()` — rattrapage des vecteurs manquants ou périmés, dans un thread.

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

Le LLM reçoit plusieurs outils et décide lui-même s'il en a besoin :

```
search_memory(query)        → recall() dans memory.py
search_bibliotheque(query)  → recall_bibliotheque() dans hub.py
search_anecdotes(query)     → recall_anecdotes() dans memory.py
search_web(query)           → websearch.search() via Brave Search
search_carnet(query)        → notes du carnet de bord du fil (hub.py)
find_skill(query)           → fiches skills CoaNIMM réutilisables (hub.py)
```

**Règles de déclenchement** (dans le system prompt) :
- Question personnelle sur l'utilisateur ou son entourage → `search_memory`
- Référence à une discussion passée → `search_bibliotheque`
- Référence à un moment vécu, souvenir partagé → `search_anecdotes`
- Information datée par nature (actualité, météo, prix) → `search_web`
- Tâche d'automatisation ressemblant à un process déjà validé → `find_skill` (avant de générer)
- Question générale, factuelle, technique → aucun outil

`_execute_tool()` est **async**. `search_web` ne doit jamais être appelé pour analyser un document fourni dans le message.

**Cache des recherches (`search_with_cache`, table `web_reference`)** : `search_web`
passe par `search_with_cache()`, qui réutilise un résultat déjà obtenu pour une
requête sémantiquement proche et **non périmée** (sans rappeler Brave), et mémorise
les nouveaux résultats. Chaque entrée porte une expiration selon la périssabilité
de l'information, **estimée par le LLM** (`classify_perissabilite_jours` dans hub,
à partir de la requête et d'un extrait du contenu trouvé : éphémère 1 j / normale
30 j / durable 365 j / permanente = jamais), avec repli sur une heuristique par
mots-clés si le LLM est indisponible. Classement uniquement en cas de défaut de
cache ; stockage en arrière-plan (zéro latence). Zone séparée de la mémoire
personnelle. Le `memory_worker` purge les entrées expirées à chaque cycle.

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
| `web_reference` | Cache des recherches web scrapées (séparé de la mémoire personnelle). Colonnes : `query` `query_norm` `content` `embedding` `captured_at` `expiration` `source`. Réutilisé par `search_with_cache()` ; purgé à expiration par le worker. |
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
- `search_messages_text(query, limit)` — recherche LIKE sur `messages.content` (recherche exacte)
- `delete_last_assistant(thread_id)` — supprime le dernier message `role='assistant'` d'un fil
- `delete_last_pair(thread_id)` — supprime la dernière paire user+assistant (pour ré-édition)

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

### Menus d'action par message

**Menu "Ma saisie"** (sur chaque message utilisateur) — aria-label `Ma saisie` :
- 📋 Copier — copie le texte dans le presse-papier
- ✏️ Modifier — appelle `editLastUserMessage()` : supprime la dernière paire en DB (`DELETE /api/chat/{id}/last_pair`), remet le texte dans le champ de saisie

**Menu "La réponse"** (sur chaque message assistant) — aria-label `La réponse` :
- 📋 Copier — copie le texte
- → Onglet — envoie le contenu dans un nouveau fil (tab)
- 🔄 Régénérer — supprime le dernier message assistant en DB (`DELETE /api/chat/{id}/last_assistant`) puis re-stream le dernier message utilisateur
- ⭐ Marquer pour export — ajoute/retire le message de `_exportItems[]` ; contour visuel sur la bulle

Tous les menus sont accessibles au clavier grâce à `_menuKeyboard()` : focus auto sur le premier item à l'ouverture, navigation Flèche Haut/Bas, Échap pour fermer.

### Export messages
- Bouton flottant `#export-float-btn` (coin bas-droit) apparaît dès qu'un message est marqué — indique le nombre d'éléments
- Modal `#export-modal` : sélecteur de format + bouton "Tout démarquer"
- Appel `POST /api/export` → `modules/export_nimm.py` → téléchargement direct
- Formats : **TXT** (texte brut), **DOCX** (python-docx), **PDF** (fpdf2), **RTF** (manuel), **ODT** (zip XML), **EPUB** (zip XHTML), **MP3** (edge-tts, voix fr-FR-DeniseNeural)

### Recherche messages (modale Recherches)
Deux niveaux complémentaires dans la même modale :
- **Par sens** — embeddings (sentence-transformers), retrouve l'idée sans les mots exacts
- **Texte exact** — SQLite `LIKE` via `search_messages_text()`, retrouve le mot tel quel

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
| Export | Bouton flottant | Sélection format + déclenchement export |
| Recherches | Bouton sidebar | Recherche sémantique + texte exact + bibliothèque + mémoire |

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

## CoaNIMM (coanimm.py)

Agent d'exécution Python autonome — déclenché depuis le panneau CoaNIMM (sidebar). CoaNIMM peut exécuter n'importe quelle requête en langage naturel, avec ou sans validation intermédiaire, en bouclant avec l'utilisateur via l'interface si nécessaire.

### Deux modes d'exécution

| Mode | Fonction | Déclencheur |
|---|---|---|
| Script Promptothèque | `run_script(script_id, …)` | Sélection dans la liste des scripts enregistrés |
| Génération libre | `run_generated(consigne, …)` | Consigne en langage naturel |

### Flow Plan→Explore→Generate→Execute (run_generated)

1. **Planification** (`generate_plan()`) — LLM génère un plan en texte brut (sans markdown, lisible braille) et indique si une exploration disque est nécessaire (`EXPLORER: oui/non`)
2. **Exploration** optionnelle (`explore_directory()`, permission `EXPLORE_ACTION='explorer_disque'`) — liste arborescente du dossier workspace, injectée dans le contexte de génération
3. **Génération** (`run_generated()`, permission `GENERATED_ACTION='exec_generated_code'`) — LLM produit un script Python ; retry automatique si `SyntaxError`
4. **Exécution en streaming** — le script tourne en sous-processus ; stdout transmis en temps réel via SSE (`/api/coanimm/run_code_stream`) avec `PYTHONUNBUFFERED=1` et flag `-u`

### Système de permissions (deux niveaux)

- `EXPLORE_ACTION = 'explorer_disque'` — lecture seule du disque
- `GENERATED_ACTION = 'exec_generated_code'` — écriture / exécution

Si l'accord n'est pas déjà en base, le backend retourne `{'status': 'permission_required', 'action': …}` ; le frontend affiche le panneau de permission avec 3 niveaux : une fois / pour ce fil / toujours.

### Exécution streaming (SSE)

Route `GET /api/coanimm/run_code_stream?script_path=…` — `StreamingResponse` (text/event-stream). Chaque ligne de stdout du script est émise sous la forme :

```
data: {"type": "line", "text": "..."}
```

Fin de stream : `data: {"type": "done", "returncode": N, "files_list": [...]}`. Si `interaction_needed` est présent dans le payload `done`, le frontend affiche le panneau d'interaction.

Variables d'environnement du sous-processus : `PYTHONIOENCODING=utf-8`, `PYTHONUNBUFFERED=1`.
Timeout : 300 secondes (augmenté de 30 s pour les tâches longues et les appels LLM internes).

### Protocole `__NIMM_DEMANDE__` (boucle agentique)

Quand un script généré a besoin de la validation de l'utilisateur avant une action destructive ou ambiguë, il ne bloque pas (`input()` interdit) — il émet un marqueur :

```python
print('__NIMM_DEMANDE__: Confirmez-vous la suppression des 42 dossiers détectés ?')
import sys; sys.exit(0)
```

Le backend détecte ce marqueur dans le stream et inclut `interaction_needed: {question, output_so_far}` dans le payload `done`. Le frontend :

1. Affiche le panneau `#coanimm-interact-panel` avec la question
2. L'utilisateur tape sa réponse et clique Envoyer (ou Entrée)
3. Le frontend appelle `POST /api/coanimm/continue` avec `{consigne_originale, output_precedent, question_posee, reponse_utilisateur, thread_id}`
4. Le backend reconstruit le contexte complet et régénère un script en tenant compte de la réponse
5. Le nouveau script est présenté et exécuté — la boucle peut recommencer

Cette boucle est entièrement dans l'interface ; aucun `input()` n'est jamais utilisé.

### Sandbox

Répertoire dédié par fil : `data/coanimm_workspace/{nom_fil}_{thread_id[:8]}/`.
Scripts exécutés avec `PYTHONIOENCODING=utf-8` et `PYTHONUNBUFFERED=1` (emojis + stdout non bufférisé).
Timeout : 300 secondes.

### PLANNING_SYSTEM_PROMPT

Texte brut uniquement (interdictions explicites de tout markdown, balises, astérisques, backticks). Format de réponse : ligne `EXPLORER: oui|non` + plan en 3–8 phrases numérotées.

### GENERATE_SYSTEM_PROMPT (règles clés)

- Jamais de `input()` ni `sys.stdin` — utiliser le protocole `__NIMM_DEMANDE__` si validation nécessaire
- Toujours `print()` les actions au fil de l'exécution (stdout en temps réel)
- Pour les tâches sans risque : exécuter directement sans demander confirmation
- Encodage : `utf-8` explicite sur toutes les opérations fichier

### Skills CoaNIMM (méthodes réutilisables)

Capturer une méthode qui a fonctionné pour pouvoir la redemander, sans auto-apprentissage autonome : rien ne s'écrit sans l'accord explicite de l'utilisateur. Cycle : demande → génération/exécution → validation → rédaction d'une fiche skill → une consigne ressemblante retrouve le skill et s'en sert. Schéma de cadrage complet : `CoaNIMM_schema_skills.md` (gardé local).

**Stockage** — extension de la Promptothèque, `type='skill'` (aucune table nouvelle, aucune migration). `core/database.py` : `save_prompt(id, label, text, type='skill', meta={...})` / `list_prompts('skill')`. `meta` porte `description` (« quand l'utiliser »), `mots_cles`, `script_ref`, `consigne_origine`, `valide_par_laurent`, `version`.

**Rédaction — Étape A** (`modules/coanimm.py`) — `SKILL_WRITER_SYSTEM_PROMPT` (4e consigne, même famille que PLANNING/EXPLORE/GENERATE) ; `write_skill(consigne_origine, script, …)` async, calqué sur `maybe_generate_carnet_note` (appel LLM de fond, lecture des fiches existantes pour éviter les doublons, option SKIP). Règle cardinale : enseigner la LOGIQUE de la méthode — « seuillage binaire » pour la découpe/vectorisation, « quantification de palette » pour la broderie : deux skills distincts, jamais une fonction « retouche » générique — et non l'exemple précis. Sortie texte brut accessible plage braille. `_parse_skill_fiche()` découpe la sortie en DESCRIPTION / MOTS-CLES / corps.

**Rappel — Étape B** (`core/hub.py`, calqué sur `search_carnet`) — signal léger dans `build_system_prompt` (présent uniquement si au moins un skill existe), outil `find_skill(query)` déclaré dans `NIMM_TOOLS`, handler dans `_execute_tool` : recouvrement de mots-clés (filtré par `_MOTS_VIDES`) sur label + description + mots-clés, renvoie les 1 à 3 fiches les plus proches en texte brut. Comparaison volontairement simple au départ ; embeddings éventuellement plus tard.

**Auto-audit — Étape C** (`modules/coanimm.py`) — avant l'exécution dans `run_generated`, si une fiche correspond à la consigne (`_find_relevant_skill`, même appariement que find_skill), le script généré est relu à la lumière de la fiche (`audit_against_skill`, qui réutilise `generate_code` et donc son filet anti-troncature) et corrigé s'il s'en écarte ; le résultat n'est gardé que s'il reste syntaxiquement valide. Inerte tant qu'aucune fiche n'existe.

**Déclencheur d'écriture** (`frontend` + `main.py`) — dans le panneau de validation post-exécution de CoaNIMM (affiché après un run réussi), une case « Aussi mémoriser la méthode comme skill réutilisable ». Si cochée, « Enregistrer » sauve le script (type='script') ET appelle `POST /api/coanimm/save_skill` → `write_skill()` (fiche rédigée par le LLM, nom auto-généré). Le résultat (créée / déjà couverte / erreur) est annoncé dans la zone de statut accessible. C'est ce qui rend l'Étape A active.

**Outils externes — Étape D** (`modules/coanimm.py` + `main.py`) — deux helpers injectés dans le prologue confiné : `nimm_web_search(query)` (réutilise Brave/Tavily) et `nimm_github_search(query)` (api.github.com : code si `GITHUB_TOKEN`, sinon dépôts). Cadrage sécurité retenu : le script passe une REQUÊTE, jamais une URL ; le serveur tape des endpoints FIXES ; le sous-processus reste `allow_network=False` et n'appelle que localhost (exactement comme `nimm_generate_image`) — le confinement réseau n'est pas touché. Résultats bornés en taille. Routes : `POST /api/coanimm/web_search`, `POST /api/coanimm/github_search`.

Le volet skills est complet : capture (A) → rappel (B) → auto-audit (C) → déclencheur d'écriture → outils externes (D). **Gestion** : un skill validé peut être modifié (nom, description, mots-clés, méthode) — `update_skill()` incrémente la version et préserve script et capacités — ou supprimé, depuis le panneau « Skills enregistrés » (routes `POST /api/coanimm/skills/{id}/update`, `DELETE /api/coanimm/skills/{id}`). **Rappel sémantique** : `rank_skills()` mutualise l'appariement pour `find_skill`, `_find_relevant_skill` et `match_skills_for_consignes` — similarité par embeddings (`memory._embed`, option « recherche par sens ») avec **repli automatique** sur le recouvrement de mots-clés si le modèle n'est pas installé.

---

### Capacités, validation et workflows CoaNIMM

Deuxième volet greffé sur CoaNIMM (après les skills), même philosophie : rendre **visible et approuvable** ce que le classifieur de sécurité détecte déjà, et **enchaîner** ce que CoaNIMM sait faire à l'unité — sans rien retirer au confinement. Schéma de cadrage complet : `CoaNIMM_schema_capacites_workflows.md` (gardé local).

**Capacités déclarées — Étape 1** (`modules/coanimm_safety.py`) — `capabilities_of(code) -> list` projette le classifieur AST existant (`classify_for_execution`) en capacités normalisées : `ecriture`, `recherche` (helpers confinés `nimm_web_search` / `nimm_github_search`), `image` (`nimm_generate_image`), `reseau` (brut), `programme` (subprocess), `email`, `systeme`, `shell`, `code_dynamique`. `CAPABILITY_LABELS` fournit les libellés lisibles. La capture d'un skill stocke `meta['capacites']` ; `core/hub.py` `find_skill` les affiche. Lecture seule, ne bloque rien — une seule source de vérité, le classifieur.

**Approbation par capacité — Étape 2** (`core/database.py` + `main.py`) — store `coanimm_capabilities` (calqué sur `coanimm_allowed_paths`) : `list_coanimm_capabilities` / `add` / `remove`. `_COANIMM_GRANTABLE_CAPS = {reseau, programme, email}` — les capacités qui, sinon, redemandent confirmation à chaque exécution. Routes `GET/POST/DELETE /api/coanimm/capabilities`. Intégration **rétro-compatible** dans `run_code_stream` : on ne demande confirmation que pour les capacités requises *et non encore accordées* ; `allow_network` suit la capacité `reseau`. Sans aucune capacité accordée, le comportement est identique à l'historique. Le confinement d'écriture reste le filet runtime, inchangé. Panneau frontend « Capacités autorisées en exécution » (cases par capacité, accessible). **Gating propriétaire** : l'octroi et la révocation durables (`POST`/`DELETE`) sont réservés au profil **administrateur** (`is_current_user_admin()`, tolérant pour une install mono-profil) — `403` sinon ; le `GET` expose `is_owner`. L'autorisation **« pour cette fois »** (`once_caps`, non persistée) reste ouverte à l'usage courant : une capacité requise peut être ouverte pour un seul lancement sans la graver, depuis le panneau de confirmation.

**Workflows — Étapes 3-4** (`modules/coanimm.py` + `main.py` + `frontend`) — un workflow est une séquence ordonnée de skills validés, rejouable. Stockage : `type='workflow'` dans la Promptothèque (zéro migration), `meta.etapes` (liste de `{skill_id, label}`) + `meta.capacites` (**union** des capacités des étapes, calculée à l'enregistrement). Orchestrateur `run_workflow(workflow_id, thread_id)` : parcourt les étapes, exécute le **script enregistré du skill** (`meta['script']`, capté à la validation), réutilise l'auto-audit par étape, **s'arrête et rapporte à la première erreur** (pas d'enchaînement aveugle). Routes `GET/POST /api/coanimm/workflows`, `POST /{id}/run`, `DELETE /{id}`. UI : composer (sélecteur de skills validés, étapes réordonnables monter/descendre avec `aria-label`), enregistrer, rejouer ; résultat et statut en zones `aria-live`.

**Workflows et capacités pré-accordées** — `_execute` accepte un paramètre `granted_caps` (défaut `None` = comportement historique strict : bloque les actions sensibles, `allow_network=False`). Quand `run_workflow` le fournit, l'exécution est autorisée **par capacité déjà accordée** : `run_workflow` vérifie en amont que l'union des capacités du workflow est couverte (refus clair et anticipé sinon, avant de lancer la moindre étape), puis chaque étape s'exécute avec le réseau ouvert si `reseau` est accordé. Les capacités **bloquées** (`systeme`, `shell`, `code_dynamique`) restent toujours refusées. `run_script` et l'exécution directe ne passent pas `granted_caps` : aucun changement pour eux.

**Surface autonome + historique** (`modules/coanimm.py` + `frontend` + `main.py`) — `_workspace_dir` retourne un dossier de travail **global unique** (indépendant du fil) : les fichiers produits arrivent toujours au même endroit. Case « Partir de la conversation courante » (`_coanimmBuildContext`) : pont optionnel, *désactivé* par défaut, qui préfixe la consigne avec les derniers messages du fil. Historique global des tâches : store `coanimm_history` + routes `GET/POST/DELETE /api/coanimm/history` + panneau (réactiver une tâche pour la relancer).

**Accessibilité CoaNIMM** — erreurs de confinement (écriture hors dossiers autorisés) affichées en `role="alert"` et annoncées au lecteur d'écran, avec un bouton « Ajouter ce dossier aux dossiers autorisés » en un clic ; loaders d'attente visuels `aria-hidden` doublés d'annonces `role="status"` non envahissantes (annonce unique, pas de répétition) ; raccourci Alt+Maj+S contextuel (vise la saisie CoaNIMM si son panneau est ouvert) ; `_linkifyBareUrls` rend cliquables les adresses citées sans `https://`. **Aperçu avant exécution** (option opt-in, route `/api/coanimm/preview` — analyse statique qui n'exécute rien) : si activé, un panneau annonce avant de lancer ce que le script va faire — capacités lisibles, dossiers d'écriture autorisés, actions sensibles ou bloquées — puis demande confirmation (Exécuter / Annuler), avec `aria-live` et focus.


---

## Export (export_nimm.py)

`async export_messages(items, fmt)` → `(bytes, filename, mime_type)`

| Format | Mécanisme | Dépendance |
|---|---|---|
| TXT | chaîne UTF-8 | aucune |
| RTF | construction manuelle (escape unicode `\uN?`) | aucune |
| ODT | zip XML (ODF 1.3) | aucune |
| EPUB | zip XHTML (EPUB 3) | aucune |
| DOCX | python-docx | `python-docx` (déjà présent) |
| PDF | fpdf2 | `fpdf2` (ajouté requirements.txt) |
| MP3 | edge-tts, voix `fr-FR-DeniseNeural` | `edge-tts` (déjà présent) |

Route : `POST /api/export` — retourne le fichier en téléchargement direct.

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
| 26/06/2026 (outils 2) | **CoaNIMM — traduire, expurger (versions enfants), coloriage**. `nimm_translate(text, target_lang)` ; `nimm_expurgate(text, consigne)` = version ADAPTÉE AUX ENFANTS d'un texte (retire/adoucit violence, sexualité, horreur, grossièretés en préservant l'histoire ; peut abréger) ; `nimm_coloring_page(subject)` = dessin au trait noir et blanc. Helpers + routes gatées + catalogue (nouvelles catégories « Texte & langue » et « Images » ; `ask_llm`/`image` reclassés). [coanimm_safety] translate/expurgate → « recherche », coloring → « image » (visibles aperçu+journal). Catalogue = 10 outils. |
| 26/06/2026 (outils) | **CoaNIMM — 4 nouveaux outils + renommages**. Outils ajoutés (helpers confinés injectés dans le prologue + routes serveur gatées + entrées catalogue, activables/désactivables) : `nimm_search_documents` (interroge la base de connaissances/RAG), `nimm_extract_text` (extrait le texte d'un PDF/Word/ODT/RTF/EPUB/HTML/image+OCR — lecture seule), `nimm_ask_llm` (sous-tâche IA : résumer/classer/traduire), `nimm_read_url` (lit une page web précise, anti-SSRF via net_guard). [coanimm_safety] ces helpers (sauf `extract_text`, lecture locale bénigne) déclarés capacité « recherche » → visibles dans l'aperçu et le journal de sécurité. Le panneau « Outils de CoaNIMM » se peuple automatiquement et **regroupe les outils par catégorie** (`<details>` repliables avec compteur « n/m actifs » + résumé global) pour rester compact et navigable au lecteur d'écran quel que soit le nombre d'outils (catégories : Recherche & web, Documents, Création & IA). Renommages : modale « Enrichissement web » → « Enrichir la base de connaissances » ; bouton 👻 relibellé « fantôme » (au lieu de « confidentiel »). Cache-bust `20260626-v6`. |
| 26/06/2026 (suite) | **Base de connaissances locale (RAG) — robustesse + injection proactive**. La brique RAG existait déjà (modale « Enrichissement web » : ingestion URL/texte/fichier avec OCR → chunks vectorisés `reference_chunk` → outil `search_documents` ; documents permanents). [enrichissement.py] `search_documents` gagne un **repli mots-clés** (champ `mode` semantic/keyword) : la base reste interrogeable même sans le modèle d'embeddings. [hub.py] `_match_documents()` + paramètre `doc_context` de `build_system_prompt` : **injection proactive** des passages pertinents dans le system prompt (comme `_match_bibliotheque`), seuillée (cosinus ≥ 0.32 / recouvrement ≥ 2) et gated — le LLM n'a plus à penser à appeler l'outil. **Citation déterministe** : `_match_documents` renvoie aussi les titres retenus (dédoublonnés) ; un bas de réponse « — 📄 Documents consultés : … » est ajouté à la réponse (diffusé en direct dans le pipeline stream + sauvegardé), donc lisible au lecteur d'écran et copiable. |
| 26/06/2026 | **CoaNIMM — journal de sécurité + catalogue d'outils**. [database.py] stores `coanimm_security_log` (audit plafonné à 200 : date, capacités, dossiers, fichiers, code retour, statut, réseau, blocages) et `coanimm_disabled_tools`. [main.py] `run_code_stream` journalise chaque exécution (et chaque blocage) côté serveur ; routes `GET/DELETE /api/coanimm/security_log` (effacement réservé au propriétaire) et `GET/POST /api/coanimm/tools` ; les routes `web_search`/`github_search`/`generate_image` refusent si l'outil est désactivé. [coanimm.py] `_build_prologue` n'injecte que les outils ACTIVÉS — un outil désactivé est remplacé par un stub qui lève une erreur claire (pas d'absence silencieuse). [frontend] panneaux « Outils de CoaNIMM » (cases par outil) et « Journal de sécurité » (liste accessible, effacement propriétaire, rechargé à l'ouverture). Cache-bust `20260625-v5`. |
| 25/06/2026 (suite) | **Skills : gestion + rappel sémantique ; mode confidentiel**. [coanimm.py + main.py] **édition/versionnement des skills** : `update_skill()` (modifie nom/description/mots-clés/méthode, incrémente la version, préserve script et capacités) + routes `POST /api/coanimm/skills/{id}/update` et `DELETE /api/coanimm/skills/{id}` ; panneau frontend « Skills enregistrés » (liste, modifier, supprimer, accessible). [coanimm.py + hub.py] **rappel sémantique** : `rank_skills()` mutualise l'appariement — similarité par embeddings (`memory._embed`) avec **repli automatique** mots-clés si le modèle est indisponible ; `find_skill`/`_find_relevant_skill`/`match_skills_for_consignes` branchés dessus. [hub.py] **mode confidentiel** : `_is_ghost_thread()` ; un fil fantôme ne génère plus de **note de carnet** (mémoire déjà coupée) — aucune trace dérivée ; bouton 👻 relibellé « confidentiel » + `aria-pressed`. **Purge de l'espace de travail** : `purge_workspace()` (vide le dossier de travail global, le conserve) + route `DELETE /api/coanimm/workspace` + bouton « Vider l'espace de travail » (confirmé, accessible) pour effacer les fichiers produits après une session confidentielle ; les scripts d'exécution transitoires étaient déjà supprimés (`os.unlink`). Cache-bust `20260625-v4`. |
| 25/06/2026 | **CoaNIMM — « pour cette fois », workflow depuis l'historique, gating propriétaire**. [main.py] `run_code_stream` accepte `once_caps` : autorisation d'une capacité POUR CE LANCEMENT (non persistée), fusionnée aux capacités durables (`_effective_caps`). [coanimm.py + main.py] `match_skills_for_consignes()` + route `/api/coanimm/workflow_from_history` : compose un workflow en faisant correspondre des tâches de l'historique aux skills validés les plus proches. [database.py + main.py] **gating propriétaire** : `is_current_user_admin()` (tolérant mono-profil) ; `POST`/`DELETE /api/coanimm/capabilities` réservés au profil admin (403 sinon) ; `GET` expose `is_owner`. [frontend] panneau de confirmation « Exécuter (pour cette fois) » (n'ouvre que la capacité requise) + case « Mémoriser pour les prochaines fois » (propriétaire seulement) ; cases capacités désactivées + note pour non-propriétaire ; historique avec cases à cocher + « Composer un workflow depuis la sélection ». **Aperçu avant exécution** (opt-in, route `/api/coanimm/preview`, analyse statique sans exécuter) : annonce capacités + dossiers d'écriture + actions sensibles/bloquées, puis Exécuter/Annuler (accessible). Cache-bust `20260625-preview`. |
| 24/06/2026 | **Capacités, workflows et surface autonome CoaNIMM**. [coanimm_safety.py] `capabilities_of()` + `CAPABILITY_LABELS` (Étape 1) : projection du classifieur AST en capacités normalisées (ecriture, recherche, image, reseau, programme, email, systeme, shell, code_dynamique). [database.py + main.py] store `coanimm_capabilities` + routes `/api/coanimm/capabilities` (Étape 2) : approbation **par capacité** ; gate rétro-compatible dans `run_code_stream` (confirmation seulement si capacité requise non accordée ; `allow_network` suit `reseau`). [coanimm.py + main.py] **workflows** (`type='workflow'`) : `save_workflow` / `list_workflows` / `run_workflow`, séquences de skills validés, arrêt-sur-erreur, capacités = union ; correctif : le skill stocke son script dans `meta['script']` (run_workflow l'exécute). `_execute(granted_caps=…)` : les workflows honorent les capacités pré-accordées (`allow_network` selon `reseau`, refus anticipé si capacité manquante), `run_script` / exécution directe inchangés. [coanimm.py] `_workspace_dir` global (surface autonome) + pont contexte optionnel ; store `coanimm_history` + routes + UI historique. [frontend] panneaux Capacités / Workflows / Historique accessibles (`aria-live`, `aria-label`, étapes réordonnables) ; erreurs de confinement `role="alert"` + bouton « Ajouter ce dossier » ; loaders `aria-hidden` + annonces `role="status"` ; Alt+Maj+S contextuel ; `_linkifyBareUrls`. |
| 21/06/2026 (soir) | **Indicateur visuel — recherche web**. [hub.py] `process_message_stream()` envoie desormais `yield "data: [WEB_SEARCH_LOADING]\n\n"` a deux endroits : avant l'appel `search()` (bouton 🌐 force) et avant l'execution de l'outil `search_web` quand le LLM decide seul (tool calling) — corrige le silence visuel pendant une recherche en cours. [styles.css] classe `.web-search-loader` (reutilise l'animation `sttDotPulse` existante, sans le bretzel) pour un indicateur "points qui pulsent" dedie, distinct du loader de reflexion. [app.js] handler SSE intercepte `[WEB_SEARCH_LOADING]` → affiche une bulle `🌐 Recherche en cours…` ; retrait au moment de la transformation du loader bretzel principal, ET, en filet de securite, des l'arrivee du premier token de texte normal (cas ou le LLM annonce une phrase avant d'appeler l'outil) — evite tout doublon ou bulle persistante. Cache-busting : `20260621-2`. |
| 21/06/2026 | **Skills CoaNIMM + chiffrement des cles API**. [coanimm.py] `SKILL_WRITER_SYSTEM_PROMPT` + `write_skill()` + `_parse_skill_fiche()` (Étape A) : capture d'une méthode validée comme fiche réutilisable (`type='skill'` dans la Promptothèque, `meta` description/mots_cles/script_ref), writer de fond calqué sur le carnet de bord. [hub.py] `find_skill(query)` (Étape B) : signal léger dans `build_system_prompt` (si skills existants) + outil déclaré dans `NIMM_TOOLS` + handler (recouvrement de mots-clés filtré par `_MOTS_VIDES`, top 1-3 fiches). [coanimm.py] **auto-audit (Étape C)** : avant exécution, `run_generated` relit le script à la lumière d'une fiche correspondante (`_find_relevant_skill` + `audit_against_skill`), inerte sans fiche. [database.py] **Sécurité point 6/7** : clés API chiffrées au repos (Fernet) — `get_api_keys()`/`set_api_keys()` + keyfile `data/.nimm_api_keyfile` (0600) + migration douce d'une valeur en clair ; tous les sites d'accès (`hub._load_api_keys`, `main.py`, `websearch.py`) branchés sur ce point unique. [requirements.txt] `cryptography>=42` ajouté, ligne `rapidfuzz` réparée. [.gitignore] keyfiles exclus. `modules/main.py` confirmé code mort (exclu). Déclencheur skill câblé : case à cocher dans le panneau CoaNIMM (frontend) + route `/api/coanimm/save_skill` → `write_skill` (Étape A active). [coanimm.py + main.py] **Étape D** : helpers confinés `nimm_web_search` / `nimm_github_search` (routes serveur vers endpoints fixes Brave/Tavily et api.github.com ; le script passe une requête, jamais une URL ; `allow_network=False` inchangé). |
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
| 09/06/2026 | **Matching bibliothèque automatique** : [database.py] `get_bibliotheque_index()` — retourne l'index léger des fiches (id, titre, tags, categories, date_conversation). [hub.py] `_MOTS_VIDES` + `_MOTS_RAPPEL` + `_match_bibliotheque(user_message)` — matching fuzzy (`rapidfuzz`) entre le message utilisateur et l'index bibliothèque. Scoring : tag fuzzy match → +2 pts, mot titre → +1 pt. Seuil normal : 3 pts. Seuil abaissé à 2 pts si mot-clé de rappel détecté (`souviens`, `rappelle`, `on avait parlé`…). Max 2 fiches injectées. Les deux pipelines (`process_message` + `process_message_stream`) appellent `_match_bibliotheque()` — `biblio_context` alimenté automatiquement si match. [requirements.txt] `rapidfuzz>=3.0.0` ajouté. Cache-busting : `20260609`. |
| 07/06/2026 | **Accessibilité NVDA — audit et correctifs** : [app.js] Menu fil — items dropdown `Renommer` / `Épingler` / `Supprimer` convertis de `<div>` en `<button>` avec `role="menuitem"` ; conteneur dropdown avec `role="menu"` — navigation clavier et annonce NVDA opérationnelles. [index.html] Modale suppression — émoji `🗑️` du titre et émojis `📚` / `🗑️` des boutons masqués via `aria-hidden` ; `aria-label` ajoutés sur les deux boutons d'action. [index.html] Modale 🧠 — titre `🧠` masqué ; onglets convertis en `role="tablist"` / `role="tab"` avec `aria-selected` statique ; émojis onglets masqués ; placeholder champ recherche nettoyé. [app.js] Onglets 🧠 — `aria-selected` synchronisé dynamiquement au clic et à chaque ouverture. [app.js] Filtres mémoire — `aria-pressed` ajouté sur les trois boutons, synchronisé au clic et à l'ouverture. [app.js] `buildCard()` — `aria-hidden` sur icônes profondeur et barres de poids ; `aria-label` contextuel sur chaque ligne (`sujet — prédicat — valeur, poids`) ; `aria-label` sur boutons ✏️ et 🗑️ (`Modifier/Supprimer [prédicat] de [sujet]`). [app.js] Carnet et Anecdotes — boutons 🗑️ avec `aria-label="Supprimer cette note/anecdote"`. Cache-busting : `20260607`. |
| 05/06/2026 | **Onboarding & installation fraîche — suite** : [app.js] Suppression du formulaire de création intégré à `showUserPicker()` — en l'absence d'utilisateur, le picker se ferme silencieusement et laisse l'onboarding NIMM prendre le relais. [app.js] `init()` — suppression du `return` et du `showUserPicker()` en mode mono sans utilisateur : le flux descend naturellement jusqu'à l'onboarding. [app.js] Onboarding NIMM crée désormais le profil `users.json` via `POST /api/users` (admin: true) en plus du `POST /api/onboarding`. [app.js] `_saveApiKeys()` — basculement automatique sur le premier provider disponible si le provider actuel est Ollama ou vide, suivi d'un `location.reload()` après 500ms pour synchroniser provider + modèle depuis la DB. [main.py] Watchdog désactivé — le kill automatique du port 8080 au lancement (`LANCER_NIMM.bat` / `NIMM_DEBUG.bat`) remplace avantageusement la détection par ping. Cache-busting : `20260605`. |
| 04/06/2026 | **Correction onboarding installation fraîche** : suppression de `_migrate_legacy_db()` et toute référence `laurent` codée en dur (`database.py`). Nettoyage `_cleanup_data_dir()` — suppression de la logique fantôme spécifique à `laurent` (`main.py`). Onboarding corrigé : `_currentUserId` et `localStorage` posés **avant** le fetch `/api/onboarding` pour que le header `X-User-ID` soit injecté dès la première requête — la DB est désormais créée au nom de l'utilisateur réel (`app.js`). Ajout de `_slugify()` dans le frontend. Suppression du hardcode `_currentUserId === 'laurent'` comme condition admin (`app.js`). **LANCER_NIMM.bat** : suppression du `pip install` au lancement normal (économie 5-8s) + timeout réduit à 4 secondes. |
| 14/06/2026 (mémoire) | **Extraction mémoire — comblement des trous identifiés le 13/06** : [hub.py] prompt `extract_memories_from_window` enrichi sur 4 points — clarification `registre` (une émotion rapportée calmement, ex. "j'étais fier de...", reste `neutre` ; `emotionnel` réservé au ton à vif) ; nouveaux prédicats canoniques `qualite` (traits positifs rapportés, ex. "douce") et `anciennete_pratique` (durée d'une pratique, ex. "6 ans de judo") ; exception à la RÈGLE D'AUTONOMIE pour les nuances comparatives/qualitatives, rattachées en `contexte` du triplet concerné (ex. "gagne aux points plutôt que par ippon") ; nouveau prédicat `anecdote` (`memoire_type='autre'`, `profondeur=5`, `type_temporal='episodique'`) pour les moments narratifs qui ne se résument pas à un trait stable. [memory.py] `qualite`, `anciennete_pratique`, `anecdote` ajoutés à `PREDICATS_CANONIQUES` (catégories CARACTÈRE / LOISIRS / ÉVÉNEMENTS) pour reconnaissance immédiate par `normalize_predicat()`. |
| 15/06/2026 | **Prompts d'extraction memoire par provider**. Trois fichiers crees dans `data/prompts/` : `memoire_deepseek.txt` (shadow prompting + chain notation, exemples anonymises [H]/[F]), `memoire_anthropic.txt` (structure logique, exemples epures pour Haiku), `memoire_mistral.txt` (garde-fous contre les inferences, interdictions avec alternative). Injection `{{DATE}}` et `{{LOCATION}}` dans `extract_memories_from_window()`. Cache-busting : `20260615`. |
| 16/06/2026 | **Migration JSON v2 des prompts + turbo_test**. [data/prompts/] Tous les prompts provider migres du format `%%MEM%%` vers JSON structure : `memoire_deepseek.txt`, `memoire_anthropic.txt`, `memoire_mistral.txt` recrits avec registre obligatoire (neutre/emotionnel/figure/intention/hypothese), predicats canoniques etendus (ecole, competence, employeur, benevolat, anciennete_debut, prenom_pere/mere...), regles autonomie/nuance/anecdote. `memoire_gemini.txt` cree (provider non actif, prompt pret). `memoire_default.txt` conserve tel quel (deja en JSON). [turbo_test.py] Nouveau script a la racine : teste la vraie route v2 d'extraction (charge prompt, injecte variables, appelle API, parse JSON, compare faits attendus, rapport score). Supporte DeepSeek/Anthropic/Mistral/Gemini. Parser robuste 3 tentatives (tableau unique, tableaux multiples fusionnes, objets isoles) — corrige le comportement Mistral Small. Detection modele incompatible avec le provider (evite 404). **Scores obtenus** : DeepSeek 25/31 (80%), Anthropic Haiku 24/31 (77%), Mistral Medium 25/31 (80%). Mistral Small 15/31 (48%) — probleme de format resolu par le parser robuste et changement vers Medium. Les 6 manques recurrents sont des ambiguites semantiques du script de test (livres audio classe sous lecture, grade marron sous competence, origine sous nationalite) — le fond de l'extraction est correct. |
| 17/06/2026 | **Chiralite des relations memoire + harmonisation UI (ajouts Nando)**. [modules/memory.py] `PREDICATS_SYMETRIQUES` : seules les relations horizontales (conjoint, ami, collegue, frere_ou_soeur) generent une reciproque automatique — toute relation verticale (pere/mere, enfant, chef/subordonne, medecin/patient...) est bloquee dans `_save_symmetric()`, corrige les triplets aberrants du type `Jean / enfant / Laurent`. [data/prompts/] Les trois prompts provider mis a jour : regle « un seul triplet par fait, dans le sens naturel de l'enonce, jamais la reciproque ». [frontend/styles.css] `#summary-btn` stylise comme `#search-web-btn` (fond bg-input, bordure arrondie). `Recherches` et `Memoire` regroupes cote a cote en haut de sidebar (`sidebar-top-row` / `sidebar-half-btn`) — ancien style `#toggle-memory` topbar retire (ecrasait le cadre). [frontend/app.js] `_saveDraft()` : indicateur supprime pendant la frappe — affiche uniquement a la restauration d'un brouillon au demarrage. |
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

### [LIVRÉ 16/06/2026] Export messages marqués
Marquer des réponses depuis le menu "La réponse" → export `POST /api/export` → 7 formats.
Phase 2 possible : instruction directe ("fais-moi un DOCX sur X") via CoaNIMM ou intent_gate.

### [PRIORITÉ] Migration Git pour Éric et Nando
Éric et Nando ont NIMM installé depuis un ZIP (`NIMM-main`). Le `git pull` automatique dans `LANCER_NIMM.bat` ne fonctionne pas chez eux — pas de lien Git.
**Objectif :** un script `MIGRER_VERS_GIT.bat` à exécuter une seule fois qui installe Git si absent, clone le repo, préserve `data/users.json` et `data/nimm_*.db`, puis branche le lancement sur le nouveau dossier.
**Mécanisme d'entrée du chemin :** glisser-déposer le dossier NIMM sur le `.bat`.
**Prérequis :** Éric et Nando sont déjà collaborateurs sur le repo GitHub privé.
**Statut :** à construire lors d'un appel test avec Nando — session dédiée.

### [FUTUR] Normaliseur prédicats libres (G)
Passe manuelle déclenchable depuis l'interface qui tenterait de fusionner les prédicats libres sémantiquement proches vers leurs équivalents canoniques (ex : `conduit_camion` → `metier: chauffeur poids lourd`). Complexe : une fusion naïve perd l'information contenue dans le prédicat libre. Nécessite une UI de validation avant application. À affiner avant d'implémenter.

---

| 19/06/2026 (session 2) | **Galerie images — correctif sauvegarde via chat + réparation encodage app.js**. [app.js] Bug : la sauvegarde automatique d'une image générée en langage naturel (chemin chat, gestionnaire `[IMAGE_GEN]`) référençait une variable inexistante `_currentThreadId` (au lieu de `currentTabId`/`currentThreadId`) — `ReferenceError` silencieuse interrompant le `fetch('/api/images/save')` avant son envoi. L'image s'affichait dans le fil mais n'atteignait jamais la table `images` ni le dossier `data/images/`. Corrigé : `thread_id: currentTabId || currentThreadId || ''`. Le chemin bouton dédié 🖼️ (`/api/image/generate`) n'était pas affecté. **Incident annexe découvert pendant la correction** : `frontend/app.js` contenait deux octets isolés en CP1252/Latin-1 au lieu d'UTF-8 (un `é` dans un commentaire de `_coanimmShowResult`, un espace insécable dans un message d'erreur) — héritage probable d'un éditeur mal configuré côté Mac/Linux. Cline (DeepSeek-chat) détectait l'échec de décodage strict et basculait automatiquement en lecture `latin-1` pour contourner, ce qui corrompait l'intégralité des accents/emojis/séparateurs du fichier à chaque réécriture. Les deux octets fautifs ont été localisés par script Python (position exacte + contexte) et corrigés en manipulation d'octets bruts, sans relecture `latin-1` du fichier entier. [.clinerules] Nouvelle section « Encodage — tous fichiers » : interdiction explicite de tout repli `latin-1`/`cp1252` en cas d'erreur de décodage UTF-8 ; obligation de s'arrêter et de remonter l'erreur exacte plutôt que de contourner silencieusement. Nando informé (commentaire fautif situé dans son apport CoaNIMM). Cache-busting : `20260619-1`. |
| 19/06/2026 (session 3) | **Mémoire — sujets aberrants dans les triplets (placeholders, possessifs, fonctions)**. Constat terrain : le panneau mémoire affichait des sujets invalides (`sa femme`, `ma femme`, `[F]`, `[collegue]`) — les en-têtes de section (`💼 Travail`, `🏡 Vie quotidienne`…) écartés du diagnostic car générés par l'affichage (`CATEGORIE_LABELS` dans app.js), pas stockés en base. [data/prompts/memoire_deepseek.txt] Cause racine identifiée : les exemples de la section EXEMPLES utilisaient `[F]`/`[H]` comme `sujet` pour illustrer l'anonymisation — DeepSeek généralisait ce gabarit non résolu comme format de sortie valide. Remplacés par des prénoms fictifs concrets (Camille/Julien). Ajout dans INTERDICTIONS : rejet des placeholders non remplis (`[F]`, `[H]`, `[prénom]`, `X`, `Madame`, `Monsieur`) avec repli sur `sujet={{USER_NAME}}` + lien de parenté. Ajout dans LOGIQUE : tiers nommé par sa fonction sans prénom (`mon commandant`, `le maire`, `mon chef`) → `sujet={{USER_NAME}}`, `predicat="relation_sociale"`, objet = la fonction citée ; et formule de mémorisation forcée (`retiens que`, `souviens-toi que`, `garde en mémoire`, `n'oublie pas que`) → extraction obligatoire du fait qui suit, même jugé mineur, sujet toujours soumis à la même règle de fond. [modules/memory.py] `_is_prenom()` : ajout des déterminants possessifs (`ma` `ta` `sa` `mon` `ton` `son` `mes` `tes` `ses` `notre` `votre` `leur` `leurs`) au set `mots_outils` — bloque les formulations relationnelles type "sa femme" précédemment acceptées comme sujet valide (2 mots, pas de mot-outil détecté). **Non traité aujourd'hui** : mêmes règles non répercutées sur `memoire_mistral.txt` / `memoire_anthropic.txt` (providers secondaires, pas utilisés pour la tâche mémoire actuellement) — à faire par cohérence si besoin. Anomalies déjà présentes en base non nettoyées automatiquement par ce correctif (préventif uniquement) — nettoyage manuel via panneau mémoire ou `audit_memory()` à prévoir. **À tester en conditions réelles** : dictée vocale variée en situation de travail, vérifier qu'aucun nouveau sujet aberrant n'apparaît. Cache-busting : `20260619-2`. |
| 19/06/2026 | **STT turbo — persistance serveur**. [main.py] Routes `GET`/`POST /api/settings/stt-turbo` ajoutees (manquaient depuis le 18/06) — `get_setting`/`set_setting` sur la cle `stt_turbo`, meme patron que `local-mode`. Le POST accepte `value` (format envoye par le frontend) avec repli sur `enabled`. [app.js] Aucun changement : le frontend appelait deja les bons endpoints, seule la persistance manquait cote serveur. Persistance confirmee par test manuel (toggle + reload). |
| 19/06/2026 | **Carnet de bord — passage en mode pull (search_carnet)**. Constat terrain : sur fil long, l'injection systematique des notes carnet a chaque tour sur-ancrait le LLM sur ces notes au detriment du message courant (rapporte sur l'usage de l'epouse de l'utilisateur). [hub.py] `build_system_prompt` n'injecte plus le contenu des notes — remplace par un signal leger annoncant l'existence du carnet et invitant a appeler `search_carnet(sujet)`. Nouvel outil declare dans `NIMM_TOOLS` (meme patron que `search_documents`) et aiguille dans `_execute_tool` : recherche par mots-cles simple (mots > 2 lettres) dans `get_carnet_notes(thread_id)`, repli sur les 5 notes les plus recentes si aucun mot-cle ne matche. [hub.py] `process_message` et `process_message_stream` : remplacement de l'appel a `get_carnet_notes_actives` (fenetre glissante, devenue obsolete en mode pull) par un simple signal binaire `['actif'] if count_carnet_notes(thread_id) > 0 else None`. Valide par rejeu du test `test_carnet_boucle.py` (80 messages) avant la bascule pull : seuil de declenchement (`CARNET_WINDOW`=50) et frequence (`CARNET_INTERVAL`=5) conformes. Bug de parsing corrige au passage dans `test_carnet_boucle.py` (`lire_derniere_entree_log` ne filtrait pas les blocs vides du split, retournait toujours une chaine vide). **A tester en conditions reelles** : pertinence du filtrage par mots-cles et bon declenchement de `search_carnet` par le LLM sur fil long. Cache-busting : `20260619`. |
| 18/06/2026 | **STT turbo — contexte carnet**. [main.py] Route `/api/stt/transcribe` accepte désormais `thread_id` et `turbo` (Form). Si `turbo=true`, récupère les 3 dernières notes du carnet du fil et les injecte comme `initial_prompt` à Whisper (300 car. max) — améliore la précision sur le vocabulaire du contexte en cours. [app.js] FormData enrichi : `thread_id` et `turbo` envoyés à chaque transcription si turbo actif. Cache-busting : `20260618`. |
| 18/06/2026 | **Carnet de bord — qualité et injection glissante**. [hub.py] Prompt `maybe_generate_carnet_note` restructuré en trois temps : sujet dominant / évolution (delta par rapport aux notes existantes) / état (résolu, en cours, ouvert) — 2 à 3 phrases max. [database.py] Colonne `msg_debut INTEGER DEFAULT 0` ajoutée à la table `carnet` via migration douce (`ALTER TABLE … ADD COLUMN`) — compatible bases existantes. Nouvelle fonction `get_carnet_notes_actives(thread_id, n_messages, fenetre=60)` : ne retourne que les notes dont `msg_debut < n_messages - fenetre` (les messages résumés sont sortis de la fenêtre active) ; les notes sans `msg_debut` (valeur 0, données antérieures) sont toujours injectées. [hub.py] `add_carnet_note` reçoit `msg_debut = max(0, n - CARNET_INTERVAL*2)` à la création. Les deux pipelines (`process_message` et `process_message_stream`) utilisent désormais `get_carnet_notes_actives` au lieu de `get_carnet_notes`. Cache-busting : `20250618`. |
| 09/06/2026 | **Audit mémoire — 6 chantiers** : [hub.py] Fenêtre active 30→60 msgs. `CARNET_WINDOW` 80→50, `CARNET_INTERVAL` 7→5 — Carnet se déclenche avant que les vieux messages sortent de fenêtre. Prompt carnet reformulé : capture ce qui a **bougé** (delta), note complémentaire si sujet déjà couvert, SKIP réservé aux échanges vides. [memory.py] `PREDICATS_INVERSES` corrigés : chiralité symétrie — `enfant_1`→`enfant_4`, `fils`, `fille`, `enfant`, `parent` génèrent `enfant_de` comme inverse ; `prenom_pere`/`prenom_mere`→`enfant_de`, `prenom_fils`/`prenom_fille`→`parent` ajoutés. [hub.py] Poids initial nouveaux triplets 1.0→0.5 (règle Occurrence/Coïncidence/Récurrence). [memory.py] `apply_decay_on_startup()` — decay appliqué une fois par session au démarrage, suppression sous `POIDS_RECALL_MIN`. [main.py] Thread daemon `_run_decay` lancé au démarrage avant `_run_inference`. [memory.py] Résolution conflit par récence dans `save_inline_memory()` — timestamp nouveau vs existant, le plus récent prime même sur prédicat protégé. [hub.py] `_worker_process_user()` — `run_inference_engine()` déclenché uniquement si `total_stored > 0` (économie CPU + cohérence causale). Cache-busting : `20260609-1`. |
| 09/06/2026 (soir) | **Robustesse serveur + refonte recherche mémoire**. [main.py] `warmup_embeddings` corrigé (`create_task` sur un `Future` → `TypeError` ; `ThreadPoolExecutor` jamais fermé → fuite ; `get_event_loop()` déprécié → `get_running_loop()`). `root()` : `index.html` ouvert via `with`. Clés globales : erreurs de lecture journalisées ; `save_global_keys` refuse d'écrire si le fichier existant est illisible (anti-écrasement). [main.py] `/api/update` : archive **publique** GitHub sans jeton (dépôt public assumé) — remplace l'approche `.env` ; ancien jeton à révoquer. [memory.py] **Vraie recherche vectorielle** : `recall()` ajoute une source de candidats par similarité (`_vector_candidate_keys` + `get_all_embeddings`), fusionnée avec FTS5 — retrouve les souvenirs sans mot commun. Marqueur de modèle par vecteur (`_serialize_embedding`/`_parse_embedding`, rétro-compat liste nue) ; `valeur` ajoutée au texte encodé ; seuil `VECTOR_CANDIDATE_MIN=0.45`. [database.py] `get_all_embeddings()`. [hub.py] `_worker_process_user()` déclenche `backfill_embeddings()` à chaque cycle (par lots de 50, dans un thread). |
| 09/06/2026 (soir, suite) | **Decay réparé + cache de recherches web**. [memory.py] `apply_decay_on_startup()` réécrit : ne persiste plus de poids (l'ancien appel `update_memory_value(..., poids)` levait une `TypeError` et n'écrivait pas le poids) — devient une passe de nettoyage qui supprime les souvenirs dont le poids effectif (`effective_poids()`, calculé à la volée) est sous `POIDS_RECALL_MIN`. Permanents / consolidés / catégories à taux 0 épargnés. [database.py] Table `web_reference` + `save_web_reference` / `get_active_web_references` / `purge_web_references`. [websearch.py] `search_with_cache()` : réutilise une recherche proche non périmée, mémorise les nouvelles avec expiration selon périssabilité (`_ttl_jours`, marqueurs éphémères) ; repli correspondance exacte si embeddings indisponibles ; constantes `WEBCACHE_*`. [hub.py] `search_web` → `search_with_cache` ; worker purge les références expirées. |
| 09/06/2026 (soir, suite 2) | **Périssabilité par LLM**. [hub.py] `classify_perissabilite_jours()` classe la durée de validité (éphémère/normale/durable/permanente → 1/30/365/0 j) via `call_llm`, passé en callback à `search_with_cache`. [websearch.py] classification appelée uniquement en cas de défaut de cache, repli sur l'heuristique `_ttl_jours` si indéterminé, et **stockage en arrière-plan** (`_schedule_store` / `_store_task`) — aucune latence ajoutée. `ttl=0` ⇒ pas d'expiration (permanent). Le classement s'appuie sur la requête ET un extrait (~800 car.) du contenu trouvé, pour trancher les cas ambigus. |
| 11/06/2026 | **Enrichissement web (ingestion → zone de référence) + accessibilité**. Nouveau module `modules/enrichissement.py` : portes « texte collé » et « URL » (extraction trafilatura, étage léger sans navigateur), cœur commun normaliser→vectoriser→ranger dans `web_reference` (séparé de la mémoire personnelle, permanent par défaut). [main.py] endpoints `/api/enrich/list|text|url` + DELETE. [database.py] colonne `source` sur `web_reference` (+ migration) et `delete_web_reference`. [frontend] panneau « 🌐 Enrichissement web » (bouton bascule + modale, modèle Agenda/Bibliothèque). Accessibilité : titres masqués (h1 NIMM, h2 par région) pour la navigation lecteur d'écran, et raccourcis clavier globaux Alt+Maj+lettre (C/A/M/G/E/P + S = saisie) annoncés via `aria-keyshortcuts`. Dépendance : trafilatura. Repli Playwright et PDF/.docx/OCR Mistral → phases suivantes. |
| 11/06/2026 (phase 2) | **Enrichissement web — fichiers, OCR, repli navigateur**. [enrichissement.py] adaptateurs fichiers : `extract_pdf_text` (pypdf), `extract_docx` (python-docx), `ocr_mistral` (API Mistral OCR `mistral-ocr-latest`, PDF image + images), routeur `ingest_file` (PDF texte, sinon OCR si < 40 car. ; .docx ; .rtf ; .odt ; .epub ; .html ; image→OCR ; .txt/.md/.csv) ; repli navigateur `_render_playwright` (Chromium headless, sans fenêtres) dans `extract_url` quand l'étage léger ramène trop peu de texte. [main.py] endpoint `/api/enrich/file` (UploadFile, traité dans un thread ; clé Mistral via `load_settings`). [frontend] 3ᵉ mode « Fichier » dans la modale + envoi multipart + case « Forcer l'OCR » (drapeau `force_ocr` : court-circuite l'extraction de texte du PDF, utile pour les PDF scannés ou mixtes). OCR à repli automatique : Mistral si clé API (qualité supérieure), sinon **Tesseract en local** (`ocr_local`, sans clé, avec repli de langue eng si fra absent). Dépendances : trafilatura, python-docx, mistralai (OCR cloud), pytesseract/pdf2image/pillow (OCR local), playwright (repli pages JS). |
| 11/06/2026 (phase 3) | **Interrogation des documents ingérés (RAG) + découpage**. [database.py] table `reference_chunk` (passages + embeddings, liés à `web_reference`) ; `save_web_reference` renvoie l'id ; suppression en cascade des passages. [enrichissement.py] `_chunk_text` (passages ~1100 car. avec chevauchement) ; `ingest_text` indexe chaque passage ; `search_documents(query)` = recherche par sens dans les passages, avec source. [hub.py] outil `search_documents` (déclaration `NIMM_TOOLS` + aiguillage + règle de déclenchement), pour répondre « d'après mes documents… » avec citation. [main.py] `/api/enrich/text` en thread (vectorisation). Le contenu ingéré devient réellement interrogeable, toujours séparé de la mémoire personnelle. |
| 12/06/2026 | **Mode local + accessibilité**. [hub.py/main.py/front] interrupteur « Mode local » (réglages) : bascule l'inférence vers **Ollama** (modèle configurable, défaut `llama3.1:8b`) et l'OCR vers **Tesseract** ; la recherche web reste active. Endpoints `/api/settings/local-mode`, `load_settings` expose `local_mode`. [app.js] a11y : les raccourcis clavier déplacent désormais le focus **dans** la modale ouverte (le lecteur d'écran suit) ; activation clavier des fils corrigée (le `keydown` ciblait le `div` au lieu du `span` porteur du clic → Entrée/Espace charge enfin le fil). |
| 12/06/2026 (chiralité) | **Relations genrées selon le genre défini par la personne**. [memory.py] la réciproque de fratrie concernant l'utilisateur (`frere_ou_soeur`) est genrée `frère`/`sœur` d'après le réglage `user_genre`, que la personne définit elle-même (`_est_utilisateur`, `_genrer_fratrie`) ; le conjoint reste « conjoint » (déjà neutre). [main.py] endpoints `/api/settings/user-genre`. [front] sélecteur « Comment vous définissez-vous ? » (Non précisé / Masculin / Féminin). Non défini → neutre conservé ; anciens souvenirs non réécrits. |
| 12/06/2026 (correctifs) | **Ingestion en thread + accessibilité des fils**. [main.py] les ingestions (texte/URL/fichier) propagent le contexte utilisateur au thread via `contextvars.copy_context()` — corrige l'échec « Aucun utilisateur défini » à l'ouverture de la connexion DB sur gros fichiers. [app.js] chaque fil est désormais **un seul bouton activable** (clic sur toute la ligne sauf le menu, Entrée/Espace) : supprime le double énoncé du nom (
| 16–19/06/2026 | **CoaNIMM — boucle agentique + streaming + accessibilité** : [engine.py] tous les `httpx.AsyncClient(timeout=60)` → `timeout=300` (5 occurrences) — corrige `ReadTimeout` sur génération à 16 000 tokens. [main.py] exécution subprocess non bufférisée : `env["PYTHONUNBUFFERED"]="1"` + `sys.executable, "-u"` — stdout du script transmis ligne par ligne en temps réel. [main.py] route SSE `GET /api/coanimm/run_code_stream` — `StreamingResponse` text/event-stream, chaque ligne émise immédiatement, payload `done` inclut `files_list` et `interaction_needed` si marqueur `__NIMM_DEMANDE__` détecté. [main.py] `CoanimmContinueRequest` + `POST /api/coanimm/continue` — reçoit consigne originale, sortie précédente, question posée, réponse utilisateur ; reconstruit le contexte complet et régénère le script via `generate_code()`. [modules/coanimm.py] `GENERATE_SYSTEM_PROMPT` : règles `input()` interdit, protocole `__NIMM_DEMANDE__`, `print()` en continu, exécution directe si tâche sans risque. [frontend/index.html] panneau `#coanimm-interact-panel` (caché par défaut, `role="region"`, `aria-label="CoaNIMM demande"`) avec question en `aria-live="polite"`, textarea et bouton Envoyer. [frontend/app.js] `_coanimmCurrentConsigne` capturé à la génération ; done handler : détecte `interaction_needed`, affiche panneau, submit handler appelle `/api/coanimm/continue`, relance `runCoanimmExecuteCode` avec le nouveau code (boucle agentique) ; erreur rc≠0 : `aria-live="assertive"` + `stdoutEl.focus()` pour que le lecteur d'écran lise les erreurs. [frontend/app.js] titre boîte risques : `⚠️ ATTENTION — ce script :`. Annonce NVDA : suppression des announces intermédiaires qui s'annulaient mutuellement. |
| 20/06/2026 | **CoaNIMM — fiabilité des prompts libres, sécurité (confinement), opérations Fichiers/Documents, accessibilité PDF**. FIABILITÉ [modules/coanimm.py] : `_strip_code_fences` robustifié (extrait le bon bloc même avec texte parasite, plusieurs blocs, ou réponse tronquée) ; `generate_code` fait désormais lui-même un retry anti-troncature (protège le chemin /api/coanimm/generate de l'UI, pas seulement run_generated) ; auto-réparation runtime : nouvelle `repair_code` + endpoint `/api/coanimm/repair` + boucle frontend (renvoie l'erreur au modèle, max 2 tentatives) ; synchronisation plan/code : quand l'exploration disque est requise, le code est généré APRÈS l'exploration (plus de code pré-généré puis jeté) ; correctif `run_script` (appelait `db.get_prompt` inexistant et lisait la clé 'content' au lieu de 'text' → AttributeError ; corrigé en `db.list_prompts('script')` + clé 'text', action 'exec_script'). SÉCURITÉ : nouveau module `modules/coanimm_safety.py` — `classify_for_execution` (analyse AST : bloque eval/exec/os.system/os.popen/ctypes/winreg, demande confirmation pour subprocess/réseau) et `build_guard_prologue` (code injecté en tête du script qui confine au runtime écritures, suppressions et déplacements aux seuls dossiers autorisés, via interception de open/io.open/os.open/os.remove/rename/shutil ; lectures libres ; connexions réseau externes bloquées, localhost permis pour nimm_generate_image). Branché dans `_execute` (refus blocked/needs_confirmation) et dans `/api/coanimm/run_code_stream` (param `allow_risky`, statut `confirmation_required`). [core/database.py] `list_coanimm_paths`/`add_coanimm_path`/`remove_coanimm_path` (dossiers autorisés en écriture, settings JSON). [main.py] endpoints `/api/coanimm/paths` (GET/POST/DELETE), `/api/coanimm/cancel` (registre de process + kill, annulation), payload `done` enrichi d'un résumé parlé. [frontend] section « Dossiers autorisés en écriture », bouton « Arrêter le script », panneau de confirmation des actions à risque, annonce assertive du résumé final. OPÉRATIONS VÉRIFIÉES (tool-calling) : nouveau `modules/coanimm_ops.py` — famille Fichiers (list_files/rename_file/move_file/delete_file/make_folder, mutations confinées aux dossiers autorisés) et famille Documents (extract_document_text ; summarize_document, asynchrone, ne renvoie que le résumé) avec politique « cloud sur confirmation » (OCR Mistral ou LLM de synthèse cloud uniquement après accord explicite ; local sinon). [modules/enrichissement.py] `extract_any` (extraction de texte SANS stockage RAG, réutilise extract_*/OCR) + helper `mistral_key_from_settings`. Câblé dans [core/hub.py] (`NIMM_TOOLS` += outils, dispatch sync et async dans `_execute_tool`) — donc disponibles aussi depuis le chat. UNIFICATION : `_analyze_code_risks` (affichage UI) délègue désormais à `coanimm_safety.risks_for_display`, même source de vérité que le blocage. ACCESSIBILITÉ PDF : `GENERATE_SYSTEM_PROMPT` corrige un bug (reportlab annoncé mais absent des dépendances → `reportlab>=4.0.0` ajouté à requirements.txt) et oriente vers le .docx accessible (python-docx, styles de titres) ou reportlab structuré (platypus, titre, langue fr, ordre de lecture), en évitant canvas.drawString ; le prompt indique aussi le confinement (écrire dans le répertoire courant). |
