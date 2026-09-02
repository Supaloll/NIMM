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
- **IDENTITÉ** : `prenom` `nom` `age` `date_naissance` `taille_cm` `poids_kg` `sexe` `handicap` `groupe_sanguin` `nationalite` `lieu_naissance` `origine`
- **FAMILLE** : `conjoint` `enfant` `parent` `frere` `soeur` `frere_ou_soeur` `grand_parent` `petit_enfant` `beau_parent` `statut_relation`
- **TRAVAIL & ÉTUDES** : `metier` `employeur` `anciennete` `horaire_travail` `diplome` `ecole` `competence` `permis` `recherche_emploi` `etudes` `lieu_etude` `identifiant_professionnel` `tarif_consultation`
- **SANTÉ** : `probleme_sante` `traitement` `allergie` `medecin` `operation` `suivi_medical` `addiction` `regime_alimentaire`
- **GOÛTS** : `aime` `n_aime_pas` `plat_prefere` `aversion_alimentaire` `boisson_preferee` `musique_preferee` `artiste_prefere` `film_prefere` `serie_preferee` `livre_prefere` `auteur_prefere`
- **LOISIRS** : `sport` `lecture` `jeu_video` `cuisine` `bricolage` `jardinage` `musique_instrument` `danse` `ecriture` `photographie` `art` `loisir` `anciennete_pratique` `interet` `personnage_jeu` `progression_jeu` `objet_jeu` `guide_jeu` `valeur_jeu`
- **POSSESSIONS** : `vehicule` `domicile` `logement` `equipement` `animal` `abonnement`
- **RELATIONS** : `ami` `collegue` `voisin` `relation_sociale` `mentor`
- **VALEURS** : `valeur` `croyance` `religion` `politique` `engagement` `questionnement` `theorie`
- **OPINIONS** : `stance` `opinion`
- **PROJETS** : `objectif` `reve` `intention` `projet` `envie` `apprentissage`
- **ÉVÉNEMENTS** : `evenement_vie` `deuil` `accident` `demenagement` `anecdote`
- **FINANCES** : `budget` `salaire` `patrimoine` `credit` `epargne` `compte_joint` `mutuelle`
- **TECHNOLOGIE** : `ordinateur` `tel_portable` `logiciel_prefere` `reseau_social` `habitude_num`
- **LANGUE & CULTURE** : `langue_maternelle` `langue_parlee` `culture_origine`
- **CARACTÈRE** : `trait` `force` `faiblesse` `peur` `qualite`
- **HABITUDES** : `habitude` `rituel` `sommeil` `fumeur`
- **BIEN-ÊTRE** : `moral` `stress` `bien_etre` `humeur`
- **ORIENTATION** : `orientation_sexuelle`

**Liste fermée** : un prédicat inconnu produit par le LLM est désormais **rejeté**
(triplet ignoré, trace console `⛔ Prédicat inconnu rejeté`) plutôt que stocké brut —
il n'existe plus de repli « prédicat libre » à la sauvegarde. `normalize_predicat()`
mappe les variantes vers la liste ci-dessus (ex. `medecin_traitant` → `medecin`,
`telephone` → `tel_portable`, `possession` → `equipement`,
`etablissement_scolaire` → `ecole`, `comportement` → `trait`, `benevolat` → `engagement`).

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

Depuis l'onglet Triplets, chaque ligne dispose d'un bouton 🔒/🔓 pour verrouiller ou
déverrouiller n'importe quel souvenir à la main (routes `POST /api/memory/{key}/lock`
et `/api/memory/{key}/unlock`, fonctions `lock_memory()` / `unlock_memory()`).
Les faits confirmés (ex. structure familiale) peuvent ainsi être protégés durablement
de l'extraction.

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
4. **Âge dynamique** — `date_naissance(A, JJ mois AAAA)` → calcule et met à jour `age(A, N ans)` avec précision jour/mois (`_parse_date_naissance` / `_age_depuis_naissance`) : l'âge ne progresse qu'après l'anniversaire.

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
| type | `trait` · `relation` · `evenement` |
| sujet | prénom réel — jamais "utilisateur", "je", "moi" |
| prédicat | NOM canonique — jamais verbe conjugué ni infinitif |
| objet | valeur courte (3-5 mots max) |
| contexte | fil thématique libre |
| memoire_type | `identite` (en-tête de fiche) · autre (section par catégorie) |
| profondeur | 1 (identité stable) … 5 (anecdotique) |
| temporal | `permanent` · `persistant` · `episodique` |

### Modes de personnalité

**Masque** (`personality_mode='mask'`) : fichier JSON dans `modules/masks/`.
- Champs : `name` `emoji` `id` `system_prompt` — et éventuellement `owner` (id de profil) pour un **masque privé** : il n'apparaît alors que pour ce compte (`list_masks` le filtre) et `load_mask` le refuse aux autres profils (repli sur `lia.json`, cache indexé par utilisateur). Champ optionnel `voice` : voix TTS par défaut de ce masque (ex. `edge:fr-CH-ArianeNeural`) — appliquée par le frontend tant que l'utilisateur n'a pas choisi de voix explicitement dans le sélecteur TTS (`_resolveVoice()` dans `app.js`).
- Champ `ghost` (booléen) : **mode confidentiel automatique** — tout fil utilisant ce masque est traité en mode fantôme (aucun message persisté, aucune note de carnet, aucune extraction mémoire ; le bouton 👻 l'affiche actif et ne peut pas le désactiver). L'historique de conversation est conservé **en mémoire vive** pendant la session serveur (`_get_llm_history` dans `core/hub.py`) : l'assistant garde le fil de l'échange en cours sans qu'aucune trace ne soit écrite sur disque — le cache disparaît au redémarrage ou à la suppression du fil.
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

### Robustesse et lisibilité (26/07/2026)

- **Diffusion en continu partout** : Anthropic, Gemini et Ollama faisaient un appel bloquant — rien ne s'affichait avant la fin de la génération, d'où un long silence à la synthèse vocale. Les six fournisseurs diffusent désormais au fil de l'eau.
- **Réponses tronquées** : le frontend guettait un signal `[TRUNCATED]` qu'aucun code serveur n'émettait ; le bouton « Continuer » n'apparaissait donc jamais. Signal émis par tous les fournisseurs, et troncature annoncée au lecteur d'écran.
- **Appels d'outils écrits en texte** : convertis en vraie demande d'outil, ET purgés de l'historique — enregistrés comme réponse, ils repartaient au modèle qui les imitait, entretenant le défaut dans le fil.
- **Base de connaissances** : un score sémantique ≥ 0,5 ne suffit plus ; il faut au moins un mot de fond réellement commun (deux textes français sans rapport atteignent couramment ce score). Le pied de source n'est affiché que si la réponse s'appuie vraiment sur le document.
- **Panne de fournisseur** : erreur traduite et qualifiée ; reprise automatique sur un autre fournisseur configuré si l'erreur est récupérable et que rien n'a encore été affiché (sinon on cumulerait deux réponses). Une clé refusée n'est pas récupérable.
- **Journal de fonctionnement** : ces décisions n'existaient que dans la console, inexploitable au lecteur d'écran ; elles sont consignées et consultables, avec compteur de nouveautés.

### Fonctionnalités Anthropic (25/07/2026)

- **Cache des prompts** : mode automatique — un seul `cache_control` au niveau supérieur, l'API pose et avance le point de rupture. NIMM renvoyant system prompt + 80 messages à chaque tour, le gain est permanent. **Repli obligatoire** : ce champ part sur TOUS les appels, y compris le chat streamé ; un refus 400 le désactive durablement et relance le tour, plutôt que de casser toute conversation.
- **Facturation** : `input_tokens` ne compte que le non-caché → `_anthropic_billable_input()` convertit en équivalent plein tarif, sinon le tableau des coûts devient faux.
- **Confinement multi-fournisseurs** : `cache_control`, `thinking`, `output_config` et `mcp_servers` ne sont posés QUE dans les fonctions Anthropic ; un champ inconnu ferait échouer un appel Mistral. Les sorties structurées sont portées aux providers OpenAI-compat via `response_format` avec allowlist stricte. Test statique permanent.
- **Catalogue de modèles** : `list_models()` interroge chaque fournisseur (cache 1 h) ; l'interface FUSIONNE liste conseillée et catalogue vivant en deux groupes — OpenRouter expose des centaines de modèles, un sélecteur brut serait inutilisable au lecteur d'écran.
- **PDF natif** : `nimm_read_pdf_visual` — le modèle voit la page (tableaux, figures, scans), là où l'extraction locale ne voit que le texte.
- **MCP** : serveurs distants, jeton chiffré et jamais réexposé, https obligatoire, gestion propriétaire ; sans serveur configuré l'appel est strictement inchangé.

### Boucle agentique et ricochets robustes (23-24/07/2026)

- `run_generated()` : exécuter → observer stdout/stderr/fichiers → réparer (échec) ou critiquer (succès) → corriger, borné à `AGENT_MAX_ITERATIONS = 3`. Jamais de nouvel essai après un blocage sécurité, une capacité manquante ou un délai dépassé.
- `critique_result(consigne, code, result)` : verdict JSON `{verdict: ok|insuffisant, motif, conseil}`, fail-open vers « ok » (ne bloque jamais un résultat). Route `POST /api/coanimm/critique`, appelée par l'interface après un run à code retour 0 ; si « insuffisant », réparation + relance bornées par `COANIMM_MAX_REPAIR`.
- Ricochets : `run_workflow_stream()` (générateur SSE) est LE moteur ; `run_workflow()` n'est qu'une enveloppe non-stream (compat `/run`). Réparation/critique par étape (`WORKFLOW_STEP_MAX_ITERATIONS = 2`), arrêt-sur-erreur, capacités = union pré-accordée. Le script réparé ou adapté n'est JAMAIS réécrit dans le bond : la version validée reste la référence.
- Entrée du ricochet (facultative) : `adapt_step_code()` adapte chaque script validé à l'entrée fournie au lancement (sujet, fichier, URL, texte) — même méthode, aucun nouvel import ; repli silencieux sur le script d'origine si l'adaptation est invalide ; capacités re-classifiées à l'exécution.
- Journalisation des ricochets : `_log_workflow_run()` alimente l'historique des tâches (entrée relançable : `kind`/`workflow_id`/`parametre`) et le journal de sécurité, sur les 5 chemins de sortie du moteur ; bouton « ↻ Relancer » dans le panneau Historique.
- Pilotage conversationnel : outils `list_ricochets` / `run_ricochet(nom, entree)` dans la couche tool-calling (coanimm_ops.py) — lancement uniquement sur demande explicite de l'utilisateur, mêmes garanties que le panneau.
- Scripts enregistrés : `run_script_agentique()` applique la même boucle (réparation + critique, bornée à 2 exécutions) et remonte les fichiers produits ; `run_script()` reste la primitive synchrone (permissions + exécution simple).
- Annonce des exécutions planifiées : le worker marque `notifie=False` en fin de run ; `POST /api/coanimm/schedules/notifications` renvoie les exécutions non annoncées ET les consomme (lecture unique) ; l'interface sonde toutes les 90 s et annonce dans la zone aria-live GLOBALE (hors panneau) — un ricochet lancé en arrière-plan ne passe donc plus inaperçu, panneau fermé compris.
- Ricochets planifiés : `schedule_worker()` (tick 30 s, démarré dans lifespan) lance `run_workflow` aux échéances de `coanimm_schedules` (jour + heure, rattrapage le même jour au démarrage) ; gestion réservée au propriétaire ; `schedule_due()` est pure et testée.
- Réglage `coanimm_critique_active` : la vérification du résultat (1 appel IA par exécution) se désactive depuis le panneau CoaNIMM — court-circuit AVANT tout import moteur, verdict « ok » immédiat.
- Tests : `python tests/test_coanimm_agentique.py` — 15 scénarios simulés couvrant moteur, entrée, journalisation et outils de chat.
- Fiabilité des bonds : `_bump_skill_stat()` incrémente `meta.runs_ok`/`meta.runs_err` à chaque étape de ricochet ; `_skill_fiabilite()` (entre -1 et 1) pondère `rank_skills` ; affichée dans le panneau « Bonds enregistrés ».

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
| 02/09/2026 (agir ou demander) | **Règle de retenue + outil `demander_precision` — la décision « agir ou discuter » ne dépend plus du modèle branché**. Note de Laurent : sur une même tâche (convertir un .svg en .png), DeepSeek posait une question avant d'agir, Mistral fonçait sur l'outil. Même prompt, deux comportements opposés. Diagnostic complété par lecture du code : le bloc « Outils disponibles » de `build_system_prompt` ne contenait QUE des déclencheurs (« Appeler dès que… », « Appeler quand… ») et pas une ligne sur le cas où la demande est trop floue pour être exécutée — DeepSeek demandait *malgré* le prompt, pas grâce à lui. (1) LEVIER 1 — [hub.py] section « Règle de retenue : agir ou demander » ajoutée au bloc outils : trois questions de contrôle (la cible est-elle nommée ? le résultat attendu est-il déterminé ? un mot peut-il s'entendre de deux façons ?) ; si un seul point reste ouvert, ne pas agir. La CONTRE-RÈGLE est écrite au même endroit et compte autant : ne jamais l'appliquer aux outils de simple consultation (`search_*`, `get_*`, `lookup_*`) ni à une conversation ordinaire — un assistant qui demande à chaque tour est aussi inutilisable qu'un assistant qui se trompe de cible. (2) LEVIER 2 — [hub.py] `DEMANDER_PRECISION_TOOL` (`demander_precision(question, options)`) ajouté à `NIMM_TOOLS`, **outil TERMINAL** : intercepté dans les deux chemins (`process_message_stream` ET `process_message`) AVANT tout nouvel appel au modèle, il coupe la boucle agentique et la question part telle quelle. Sans cette interception, la boucle rendrait la main au LLM outils actifs et un modèle pressé agirait juste après avoir posé sa question — la question affichée ET l'action faite, le pire des deux mondes. Aucune latence ajoutée : c'est le même appel, pas un appel de tri supplémentaire. (3) ACCESSIBILITÉ — `_formater_demande_precision()` : la DÉCISION de demander reste au modèle, la FORME de la question ne lui appartient plus. Texte brut, pas d'astérisques ni de puces, options numérotées (`1.`, `2.`…, bornées à 4) pour qu'un chiffre suffise à répondre ; sauts de ligne échappés comme dans `_flush_buf` (un `\n\n` brut couperait le flux SSE en plein milieu). Entrées douteuses absorbées : question vide, options en chaîne au lieu d'une liste, ponctuation déjà présente. Filet dans `_execute_tool` si un futur chemin d'appel oubliait l'interception. (4) NON RETENU POUR L'INSTANT — le routeur d'intention LLM dans `modules/intent_gate.py` (proposition initiale de la note) : il trancherait AVANT d'avoir le contexte du fil, du document attaché et de la mémoire — or « convertis-le en png » n'est interprétable qu'avec ce qui précède ; avec ce contexte, il coûterait aussi cher que l'appel principal. À reconsidérer, sous la forme d'une évaluation de la CLARTÉ de la demande injectée comme consigne (et non comme aiguillage dur), si la variance résiduelle entre fournisseurs le justifie après mesure. 3 tests permanents ajoutés (`test_regle_de_retenue_dans_le_prompt`, `test_demande_de_precision_accessible`, `test_demander_precision_est_terminal`) — 99 scénarios. |
| 29/08/2026 (sauvegarde + galerie) | **Section "💾 Sauvegarde" et bannière d'alerte réapparues après une perte lors d'un merge Git — HTML absent, logique JS/CSS intacte**. Diagnostic : `app.js` (37 occurrences `backup`) et `main.py` (routes `/api/backup/{status,config,run}`) totalement fonctionnels, mais `index.html` ne contenait plus aucune trace de la section ni de la bannière — perdues silencieusement (aucune erreur, tous les `getElementById` protégés par `?.`). Réinsérées à l'identique des IDs attendus : bannière `#backup-warning-banner` (à côté de `#no-provider-banner`), section `#backup-section` dans les Paramètres (entre MCP et Veille). **Galerie d'images — vignettes écrasées (bandes plates au lieu de carrés), invisibles sur mobile**. Cause : `aspect-ratio:1` en style inline mal interprété dans la grille imbriquée (`display:grid` + carte `display:flex`), plus marqué sur mobile. Remplacé par la technique universelle du cadre par ratio de padding (`padding-top:100%` + `<img>` en `position:absolute`), fiable sur tout navigateur. Vignettes resserrées (`minmax(160px,1fr)` → `minmax(110px,1fr)`, `gap` 12px → 10px) à la demande de Laurent — plus de vignettes visibles d'un coup pour repérer rapidement celles à garder. **Documentation rattrapée** : apport de Nando — nouveau volet "🖌️ Manipuler une image" (module `modules/retouche.py`, routes `/api/retouche/{options,analyser,appliquer}`) intégré au Studio, lui-même déplacé dans la modale Galerie (`#galerie-modal`) plutôt que derrière le menu "+". Aiguillage annoncé avant lancement (retouche exacte locale vs redessinée par modèle), compte rendu en trois parties (voie, journal, description honnête du résultat obtenu). Cache-busting : `20260829-backup-fix`. |
| 09/08/2026 (sauvegarde) | **Sauvegarde automatique multi-profils vers un dossier synchronisé — cloud-agnostique**. Point aveugle identifié en session : `nimm_{uid}.db` n'était sauvegardé nulle part, perte irréversible en cas de panne disque. Plutôt qu'une intégration séparée par fournisseur cloud (Google Drive, pCloud, Dropbox…), choix d'une approche générique : Google Drive, pCloud et Dropbox proposent tous une appli de bureau qui synchronise un dossier local — NIMM dépose un fichier dans ce dossier, l'appli du fournisseur envoie le reste. Zéro clé API, zéro jeton, une seule logique de code pour tous les fournisseurs, chaque profil (Laurent, Nando, Éric) choisissant le sien indépendamment. [database.py] `data/backup_config.json` (config MACHINE, hors du système de settings par profil car une sauvegarde couvre TOUS les profils à la fois) : `get_backup_config()`/`set_backup_config()` (`folder_path`, `auto_enabled`, `dismissed`, `last_backup_at`, `last_backup_ok`, `last_backup_message`) ; `list_user_db_paths()` (scan `nimm_*.db`, avec repli si `users.json` absent). [modules/sauvegarde.py] (nouveau module) `run_backup()` : copie COHÉRENTE via l'API native `sqlite3.Connection.backup()` (sûre en mode WAL, même si NIMM écrit pendant la copie), fichiers horodatés `nimm_{uid}_{YYYYMMDD_HHMMSS}.db`, AUCUNE purge automatique (choix de Laurent : espace Drive abondant, une sauvegarde étant toujours un instantané COMPLET de l'historique — supprimer une ancienne sauvegarde ne fait perdre aucune donnée, seulement un point de restauration). [hub.py] `trigger_backup()` (délégation pure au module, Hub-and-Spoke respecté, diagnostic consigné) ; `backup_scheduler_worker()` (tick horaire, déclenche si `auto_enabled` et dernière sauvegarde RÉUSSIE vieille de +7 jours ; retente à chaque tick si la dernière tentative a échoué plutôt que d'attendre une semaine en silence). [main.py] routes `GET/POST /api/backup/{status,config,run}`, réservées au propriétaire (`is_current_user_admin()` — une sauvegarde couvre les données de toute la famille). [frontend] section « 💾 Sauvegarde » dans les Paramètres (dossier, case auto hebdo, case « je ne souhaite pas de sauvegarde cloud — ne plus me prévenir », bouton manuel, statut horodaté) ; bannière d'alerte (`#backup-warning-banner`, même thème visuel que la bannière fournisseur manquant) si dossier non configuré ou dernière sauvegarde en échec, silencieuse pour les non-propriétaires et pour quiconque a explicitement coché « ne plus me prévenir ». Testé en conditions réelles par Laurent : 5/5 profils sauvegardés vers `G:\Mon Drive\NIMM_Backups`. Cache-busting : `20260809`. |
| 26/07/2026 (robustesse) | **Correctifs issus de l'usage réel + reprise sur panne**. [engine.py] appels d'outils écrits en texte (« <function=nom>{json} ») interceptés et convertis sur TOUS les chemins ; `classer_erreur_fournisseur()` traduit six familles d'erreurs (clé, crédit, débit, surcharge, délai, réseau) et marque le récupérable ; `fournisseur_de_secours()` ; `verify_claims_anthropic()` (vérification des faits) traite `pause_turn` ; import `re` manquant corrigé. [hub.py] reprise automatique sur un autre fournisseur si l'erreur est récupérable ET que rien n'a été affiché ; ancrage lexical de la base de connaissances (un score sémantique ne suffit pas) ; pied de source affiché seulement si le document a servi ; purge des appels en texte dans l'historique (ils s'auto-entretenaient) ; `MAX_TOKENS_CHAT` 3500 → 8000. [database.py] journal de fonctionnement (`nimm_diagnostics`, 80 entrées). [frontend] « Vérifier les faits » dans les DEUX menus d'actions, résultat replié en une ligne ; panneau « Journal de fonctionnement » avec compteur de nouveautés ; signal de troncature relayé → bouton « Continuer » enfin fonctionnel. [tests] 39 scénarios. |
| 25/07/2026 (Anthropic) | **Fonctionnalités de l'API Anthropic + confinement multi-fournisseurs**. [engine.py] mise en cache AUTOMATIQUE des prompts (`cache_control` au niveau supérieur) sur les 3 chemins, avec REPLI : un 400 mentionnant cache_control désactive le réglage et relance (sinon tout le chat tomberait) ; `_anthropic_billable_input()` pondère l'entrée en équivalent plein tarif (écriture 1,25×, relecture 0,1×) ; `output_schema` (sorties structurées, étendu aux providers OpenAI-compat via allowlist) ; `thinking_budget` (réflexion étendue) ; `count_tokens()` (Anthropic + Gemini, -1 = inconnu) ; `list_models()` pour 7 fournisseurs ; `analyze_pdf_anthropic()` (PDF natif, compréhension visuelle) ; `_anthropic_mcp_servers()`. [hub.py] `_search_via_anthropic()` (recherche web serveur, citations au format existant). [database.py] store `mcp_servers` (jeton chiffré Fernet, jamais relu par l'API). [main.py] routes modèles, estimation de tokens (fournisseur COURANT, pas Anthropic en dur), API Batch Anthropic, lecture PDF visuelle, CRUD MCP (propriétaire, https). [frontend] sélecteur de modèles fusionné (conseillés + catalogue vivant), panneau Batch générique, panneau MCP, réglages cache et réflexion. [tests] 26 scénarios. |
| 24/07/2026 (scripts agentiques) | **Boucle agentique pour les scripts enregistrés**. [coanimm.py] `run_script_agentique()` (async) enveloppe `run_script()` — INCHANGÉE, donc gestion de permission identique et `tests/test_coanimm.py` toujours valable : réparation sur échec, `critique_result` sur succès (bornées par `SCRIPT_MAX_ITERATIONS = 2`), remontée des fichiers produits (absente jusqu'ici pour les scripts) ; jamais de nouvel essai après blocage sécurité/capacité/délai ; le script corrigé est renvoyé dans `code_corrige` mais JAMAIS réécrit en base. [main.py] la route `/api/coanimm/run_script` appelle l'enveloppe. [frontend] mention « CoaNIMM a corrigé le script pour cette exécution ; le script enregistré n'a pas été modifié » (annoncée au lecteur d'écran) ; les fichiers produits s'affichent via le rendu existant. [tests] 21 scénarios. |
| 24/07/2026 (planification) | **Ricochets planifiés + fiabilité par ricochet + critique débrayable**. [database.py] store `coanimm_schedules` (list/add/update/remove — {workflow_id, jour None=tous/0-6, heure, minute, parametre, actif, dernier_run, dernier_statut}). [coanimm.py] `schedule_due()` (PURE, testée : rattrapage le même jour si NIMM était fermé) + `schedule_worker()` (boucle 30 s lancée dans lifespan, dernier_run posé AVANT l'exécution — anti double-déclenchement — puis dernier_statut) ; exécutions via `run_workflow` → garanties et journalisation habituelles. `_log_workflow_run` incrémente aussi `meta.runs_ok/runs_err` DU ricochet (fiabilité affichée panneau + `list_ricochets`). `critique_result` court-circuitée sans appel IA si réglage `coanimm_critique_active` désactivé. [main.py] routes GET/POST/DELETE `/api/coanimm/schedules` + `/{id}/toggle` (gestion réservée au propriétaire) ; GET/POST `/api/settings/coanimm-critique`. [frontend] section « Ricochets planifiés » (liste + formulaire ricochet/jour/heure/entrée, accessible) ; case « Vérifier le résultat après chaque exécution » ; fix bouton « Coa ! » malformé (`<//button>`). [tests] 18 scénarios (échéances comprises). |
| 24/07/2026 (ricochets suite) | **Journalisation, relance et pilotage conversationnel des ricochets + tests**. [coanimm.py] `_log_workflow_run()` : chaque exécution de ricochet est journalisée CÔTÉ SERVEUR dans l'historique des tâches (`[Ricochet] Nom — entrée : …`, avec `kind`/`workflow_id`/`parametre` pour la relance) et le journal de sécurité (workflow, étapes, capacités labellisées, motif si erreur) — 5 chemins de sortie couverts, silencieux. [database.py] `add_coanimm_history(..., extra)` accepte des champs additionnels. [frontend] bouton « ↻ Relancer » sur les entrées ricochet de l'historique (pré-remplit l'entrée d'origine) ; rafraîchissement de l'historique après un ricochet. [coanimm_ops.py] outils de chat `list_ricochets` (lecture seule) et `run_ricochet(nom, entree)` — résolution de nom tolérante, exécution via `run_workflow` (mêmes garanties), lancement uniquement sur demande explicite ; câblage hub automatique. [tests] `tests/test_coanimm_agentique.py` : 15 scénarios simulés (moteur, entrée, journal, chat), sans LLM ni réseau ni base réelle. |
| 23-24/07/2026 (agent) | **Boucle agentique CoaNIMM + workflows robustes et paramétrables**. [coanimm.py] Restauration des fonctions workflows perdues par troncature depuis le commit 33ea1a1 (greffe depuis a38c04b). `run_generated()` : boucle bornée `AGENT_MAX_ITERATIONS = 3` — exécuter → observer → réparer (échec) ou critiquer (succès) → corriger ; `critique_result()` : le LLM juge si le RÉSULTAT répond à la consigne (JSON verdict/motif/conseil, fail-open « ok ») ; fiabilité par bond (`_bump_skill_stat` meta runs_ok/runs_err, pondère `rank_skills`). `run_workflow_stream()` : moteur SSE des ricochets (step_start/step_adapt/step_repair/step_critique/step_done/done) avec boucle agentique PAR ÉTAPE (`WORKFLOW_STEP_MAX_ITERATIONS = 2`) ; `run_workflow()` = enveloppe non-stream ; fix bilan d'étape vide (lisait `output`, lit `stdout`). `adapt_step_code()` : adapte le script validé à l'« Entrée du ricochet » (sujet/fichier/URL/texte) sans nouvelle capacité — jamais persisté, repli script d'origine si invalide. [main.py] routes `POST /api/coanimm/critique` et `POST /api/coanimm/workflows/{id}/run_stream` (body JSON `{thread_id, parametre}`). [frontend] critique automatique après un run réussi (bornée par COANIMM_MAX_REPAIR, annonces lecteur d'écran) ; progression des ricochets par la SEULE zone aria-live `#coanimm-wf-result` (suppression d'une double lecture) ; champ « Entrée du ricochet » ; « Fiabilité : X réussites, Y échecs » dans le panneau Bonds. Réparation de l'encodage d'ARCHITECTURE.md (mojibake UTF-8/Latin-2 introduit le 01/07). |
| 29/06/2026 (Pixtral Large) | **Pixtral Large — choix du modèle vision Mistral**. [engine.py] `call_vision()` reçoit un paramètre optionnel `vision_model` ; la branche Mistral utilise `vision_model or 'pixtral-12b-2409'`. [main.py] réglage persisté `pixtral_model` (GET/POST `/api/settings/pixtral-model`) ; les deux routes d'analyse image lisent ce réglage et le passent à `call_vision`. [index.html] `<div id="pixtral-model-row">` (affiché seulement si routing vision = Mistral) avec sélecteur `pixtral-12b-2409` / `pixtral-large-latest`. [app.js] `_updatePixtralModelVisibility()` + chargement/sauvegarde du réglage ; le listener `routing-vision` réaffiche/masque la ligne en temps réel. |
| 29/06/2026 (Batch) | **Mistral Batch — traitement par lots**. [main.py] `MistralBatchSubmitReq` + 4 routes : `POST /api/mistral/batch/submit` (génère un fichier JSONL, l'uploade via `/v1/files`, crée le job `/v1/batch/jobs` — renvoie `job_id`), `GET /api/mistral/batch/status/{job_id}` (progression + compteurs succeeded/failed), `GET /api/mistral/batch/results/{job_id}` (télécharge le JSONL de sortie, renvoie liste triée), `DELETE /api/mistral/batch/{job_id}` (annulation). [index.html] panneau `<details id="mistral-batch-details">` dans les réglages : sélecteur de modèle, tokens max, textarea prompts (une par ligne), boutons Soumettre / Statut / Résultats / Annuler, zone aria-live statut, résultats en `<details>` pliables avec bouton Copier par entrée. [app.js] IIFE `MISTRAL BATCH` : gestion du job_id courant, polling manuel, affichage accessible (aria-live, aria-label). |
| 29/06/2026 (Pixtral) | **Pixtral â vision Mistral**. [engine.py] `pixtral` ajoutĂŠ Ă  `_MODEL_OWNER` (â `mistral`). `call_vision()` : la branche `provider='mistral'` force dĂŠsormais `model='pixtral-12b-2409'` (les modĂ¨les texte Mistral ne gĂ¨rent pas les images) â image transmise en data-URI `image_url` via `_call_openai_compat`, que Pixtral accepte nativement. [frontend/app.js] `pixtral-12b-2409` (đźď¸đ°) et `pixtral-large-latest` (đźď¸đ°đ°) ajoutĂŠs Ă  `MODELS_BY_PROVIDER.mistral`. Le routing vision Ťđ  Mistral (Pixtral)ť ĂŠtait dĂŠjĂ  prĂŠsent dans `#routing-vision` â fonctionnel sans modification HTML supplĂŠmentaire. `nimm_describe_image` dans CoaNIMM bĂŠnĂŠficie automatiquement de Pixtral si le routing vision est rĂŠglĂŠ sur Mistral. |
| 29/06/2026 (Codestral) | **Codestral â modĂ¨le code + routing CoaNIMM + FIM**. [engine.py] `codestral` ajoutĂŠ Ă  `_MODEL_OWNER` (â provider `mistral`). [frontend] `codestral-latest` (đťđ°) dans `MODELS_BY_PROVIDER.mistral` ; option Ťđľđť Codestral (code)ť dans le sĂŠlecteur routing CoaNIMM (`data-needs-key=mistral`). [hub.py] `get_task_provider_model` : alias `provider='codestral'` â force `('mistral', 'codestral-latest')` â permet de router CoaNIMM vers Codestral sans toucher les autres tĂ˘ches. [modules/coanimm_ops.py] `op_codestral_fim(prefix, suffix, stop, temperature)` â appel `https://codestral.mistral.ai/v1/fim/completions` (Fill-in-the-Middle : complĂ¨te le code entre un prĂŠfixe et un suffixe). [modules/coanimm.py] helper `nimm_codestral_fim(prefix, suffix, stop, temperature)` injectĂŠ dans le prologue. [main.py] `CoanimmCodestralFimReq` + route `POST /api/coanimm/codestral_fim` ; entrĂŠe catalogue Ť ComplĂŠter du code (Codestral FIM) ť (catĂŠgorie Code). [coanimm_safety] `nimm_codestral_fim` â capacitĂŠ Ť recherche ť (appel rĂŠseau). Catalogue = **24 outils**. |
| 29/06/2026 (batch Mistral) | **Mistral — batch complet (tâches 8-15)**. [1] **Sélecteur d'agent par conversation** (tâches 6-7) : boutons 🗨/🤖/🐸 en topbar ; `agent_mode TEXT` dans la table `threads` (valeurs `''`/`'vibe'`/`'coanimm'`) ; routes `GET/POST /api/threads/{id}/agent_mode` ; [hub.py] override du mode CoaNIMM/Vibe selon la valeur stockée. [2] **Citations Mistral accessibles** : SSE `[CITATIONS]{json}` + `[WEB_SEARCH_LOADING]` interceptés dans la boucle de stream ; zone aria-live « Citations » rendue accessible sous la réponse. [3] **OCR Vibe** : bouton « + » → upload document → `/api/mistral/ocr` (Mistral OCR `mistral-ocr-latest`) ; texte extrait injecté comme contexte avant la réponse Vibe. [4] **Web search routing** : sélecteur `#routing-websearch` dans les réglages (Brave/Tavily/Mistral) ; `_search_via_mistral()` dans hub.py via `tools:[{type:'web_search'}]` + ContextVar `_pending_citations`. [5] **Magistral** : `magistral-small-latest` (🧠💰) et `magistral-medium-latest` (🧠💰💰) ajoutés à `MODELS_BY_PROVIDER.mistral` ; `_MODEL_OWNER` étendu (`magistral`/`voxtral`/`devstral` → `mistral`). [6] **Modération Mistral** : `_check_moderation()` en « point 0 » de `process_message_stream` avant tout LLM ; modèle `mistral-moderation-latest` ; toggle + 6 sliders par catégorie (sexual/hate/violence/jailbreak/selfharm/pii) dans les réglages ; routes `GET/POST /api/settings/moderation`. [7] **Génération d'image Mistral** : [engine.py] `_generate_mistral_image()` via agents API éphémère + outil `image_generation` + téléchargement du fichier `/v1/files/{id}/content` ; dispatch `provider='mistral'` dans `generate_image()`. [8] **Voxtral Small — analyse audio** : `AUDIO_EXTS` dans `_processFile()` détecte les fichiers audio et route vers `/api/mistral/audio_analyze` (modèle `voxtral-small-latest`, transcription/analyse) ; fallback si clé absente. [9] **Code Interpreter Mistral — cloud CoaNIMM** : section `<details id="coanimm-cloud-ci-details">` dans le panneau CoaNIMM ; route `/api/coanimm/mistral_code_interpreter` (agents API + outil `code_interpreter`, fallback chat completions) ; affichage code + sortie + fichiers + bouton « injecter dans le fil ». |
| 29/06/2026 (expurgate + TTS) | **nimm_expurgate_doc + voix Gemini par défaut**. [1] **nimm_expurgate_doc** : [modules/coanimm_ops.py] `op_expurgate_doc(path, consigne, fmt, allow_cloud, thread_id)` — pipeline 3 étapes : `enr.extract_any()` → call_llm expurgation (système + consigne libre) → `adoc.build_document()` → workspace timestampé ; gate cloud aux deux étapes. Ajouté à `ASYNC_OPS_NAMES`, `ASYNC_OPS_TOOLS`, `dispatch_async_op`. [modules/coanimm.py] helper `nimm_expurgate_doc(path, consigne, fmt, allow_cloud)` injecté dans le prologue. [main.py] `CoanimmExpurgateDocReq` + route `POST /api/coanimm/expurgate_document` ; entrée catalogue « Expurger un document entier » (catégorie Documents). [coanimm_safety] capacité « recherche » (appelle LLM). Catalogue = **23 outils**. [2] **Voix Gemini mono par défaut** : [tts.py] `synthesize()` — si `voice` vide et clé Gemini présente, sélectionne automatiquement `gemini:{gemini_tts_default_voice}` (réglage persisté, défaut `Kore`). [main.py] routes `GET/POST /api/settings/gemini-tts-default-voice`. [frontend] sélecteur 8 voix dans `#gemini-tts-rows` (index.html) ; chargé + sauvegardé en JS (app.js) ; si Gemini clé présente et aucune voix jamais choisie → sélection automatique à l'ouverture. |
| 27/06/2026 (Gemini TTS) | **Voix Gemini (TTS) + résumé audio façon NotebookLM**. [tts.py] `synthesize_gemini` (mono) + `synthesize_gemini_multi` (jusqu'à 2 locuteurs) via l'API Gemini `generateContent` (modèles `gemini-2.5-flash-preview-tts`/`gemini-3.1-flash-tts-preview`, 30 voix, 70+ langues, contrôle du style en langage naturel) ; PCM 24 kHz emballé en WAV (sans dépendance) ; préfixe `gemini:` dans `synthesize()` + 30 voix ajoutées à `list_voices()` → apparaissent automatiquement dans le sélecteur (via /api/tts/voices). NotebookLM n'a pas d'API publique → on passe par Gemini TTS, avec la clé Google déjà configurée. [main.py] réglage `gemini_tts_model` (GET/POST /api/settings/gemini-tts-model). Outil CoaNIMM `nimm_audio_overview(content, voice1, voice2)` → route /api/coanimm/audio_overview : génère un dialogue podcast à 2 voix (call_llm) puis le synthétise en multi-locuteurs ; cap « recherche ». Catalogue = 22 outils. |
| 27/06/2026 (tableau + README) | **CoaNIMM — lire un tableau (CSV/TSV) + doc README**. `nimm_read_table(path)` → route `/api/coanimm/read_table` : lit un CSV/TSV (délimiteur auto) et renvoie un tableau Markdown lisible (≤200 lignes). Bénin, catégorie Documents. Catalogue = **21 outils**. README : nouvelle section « Les outils de CoaNIMM » (les 21 outils par catégorie). |
| 26/06/2026 (boîte à outils PDF) | **CoaNIMM — découper un PDF + PDF depuis images**. `nimm_split_pdf(path, pages)` → route `/api/coanimm/split_pdf` : extrait des pages (ex. '1-3,5') via pypdf. `nimm_pdf_from_images(paths, name)` → route `/api/coanimm/pdf_from_images` : assemble des images en un PDF (une par page) via Pillow. Bénins. Catégorie « Documents ». Catalogue = 20 outils. |
| 26/06/2026 (anonymiser & PDF) | **CoaNIMM — anonymiser un texte + fusionner des PDF**. `nimm_anonymize(text)` → route `/api/coanimm/anonymize` : masque les données personnelles (noms, e-mails, téléphones, adresses, IBAN…) via call_llm — confidentialité. `nimm_merge_pdf(paths, name)` → route `/api/coanimm/merge_pdf` : combine plusieurs PDF en un (pypdf). [coanimm_safety] anonymize → « recherche » ; merge_pdf bénin. Catégories « Texte & langue » et « Documents ». Catalogue = 18 outils. |
| 26/06/2026 (FALC & image) | **CoaNIMM — simplifier (FALC) + redimensionner une image**. `nimm_simplify(text, niveau)` → route `/api/coanimm/simplify` : réécriture en **FALC** (Facile À Lire et à Comprendre — accessibilité cognitive) via call_llm. `nimm_resize_image(path, max_width, fmt)` → route `/api/coanimm/resize_image` : Pillow, redimensionne et/ou convertit (jpg/png/webp…), sauvegarde workspace. [coanimm_safety] simplify → « recherche » ; resize bénin. Catégories « Texte & langue » et « Images ». Catalogue = 16 outils. |
| 26/06/2026 (voix & vision) | **CoaNIMM — synthèse vocale + description d'image**. `nimm_speak(text, voice)` → route `/api/coanimm/speak` (TTS via `modules.tts.synthesize`, audio sauvegardé dans le workspace) — pour un livre audio. `nimm_describe_image(path, prompt)` → route `/api/coanimm/describe_image` (modèle de vision via `engine.call_vision`, texte alternatif accessible). Nouvelle catégorie « Audio & voix » (transcribe, speak) ; describe_image dans « Images ». [coanimm_safety] describe_image → « recherche » (envoi au modèle de vision). Catalogue = 14 outils. |
| 26/06/2026 (audio) | **CoaNIMM — transcription audio**. Outil `nimm_transcribe(audio_path)` → route gatée `/api/coanimm/transcribe` qui réutilise le Whisper local de NIMM (`get_stt().transcribe_file`, run_in_executor). Lecture seule, local (rien n'est envoyé au cloud). Entrée catalogue « Documents ». Catalogue = 12 outils. |
| 26/06/2026 (pptx) | **CoaNIMM — PowerPoint accessible**. `accessible_doc.py` gagne `build_pptx` (diapo de titre, une diapo par section avec TITRE repère lecteur d'écran, corps en paragraphes, images avec **texte alternatif** `descr`) ; `pptx` ajouté au dispatcher → `nimm_make_document(..., fmt='pptx')` fonctionne sans nouvelle route. [requirements.txt] `python-pptx>=0.6.21` ajouté (à installer). Libellé catalogue : « Créer un document accessible (docx/pdf/epub/pptx) ». |
| 26/06/2026 (presse-papier) | **CoaNIMM — bouton « Copier (mise en forme) »**. Sur les fichiers `.html` produits par CoaNIMM (`_coanimmShowFiles` + rendu inline du flux), un bouton copie le contenu HTML enrichi dans le presse-papier (`ClipboardItem` text/html + repli text/plain via `navigator.clipboard.write`) pour le coller directement dans une messagerie web — alternative volontaire à l'envoi SMTP. Accessible (aria-label + annonce). Cache-bust `20260626-v8`. |
| 26/06/2026 (documents) | **CoaNIMM — générer des documents ACCESSIBLES**. Nouveau module `modules/accessible_doc.py` : `build_document(title, sections, fmt, lang)` produit **docx / pdf / epub / html / txt** avec titre, langue déclarée, sous-titres (headings) et images TOUJOURS accompagnées de leur description (alt). Helper `nimm_make_document(title, sections, fmt='docx', lang='fr')` + route gatée `/api/coanimm/make_document` (sauvegarde workspace) + entrée catalogue (catégorie « Documents »). Le format `html` (images en data-URI, autonome) sert au copier-coller enrichi vers une messagerie. Catalogue = 11 outils. |
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

**C — Poids initial à 0.5** — ÉCARTÉ le 31/08/2026 par Fernando (« non, on ne va pas faire ça »). Vérifié dans le code ce jour-là : tout triplet neuf entre encore avec `poids = 1.0`, la règle n'a donc jamais été appliquée. Ce n'est pas un oubli mais une décision — toucher au poids des souvenirs déjà en base pour un gain théorique ne valait pas le risque. À ne plus faire remonter comme priorité.
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
**Statut : PÉRIMÉ (31/08/2026).** Le besoin — « Éric et Nando ne reçoivent pas les mises à jour » — est déjà couvert autrement, et SANS Git : `POST /api/update` télécharge l'archive GitHub et remplace les fichiers, en préservant `data/`. Aucun script de migration n'est nécessaire. En le vérifiant, un défaut bien plus gênant est apparu — voir l'entrée « La mise à jour annonçait le contraire de la vérité ».

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
| 25/06/2026 | **Mémoire — un seul partenaire actif à la fois**. [modules/memory.py] `_PARTENAIRE_PREDICATS` (groupe de synonymes conjoint/epoux/epouse/mari/femme/compagnon/compagne/partenaire) + `_purger_partenaires_concurrents(sujet, nouvel_objet, existing)` : supprime tout ancien lien de couple du sujet vers un objet différent avant d'écrire un nouveau lien — empêche la coexistence de deux partenaires (ex : `conjoint=Nadia` et `epouse=Maïssane` simultanément). Branché dans `save_inline_memory` (branche création d'un nouveau triplet, avant écriture) et dans `_save_symmetric` (purge dans les deux sens — sujet→objet et objet→sujet — avant de créer la réciproque). Corrige un cas réel : triplet orphelin `Maïssane/conjoint/Laurent` + son inverse inféré `Laurent/conjoint/Maïssane` se régénérant en boucle au démarrage via le moteur de symétrie (`run_inference_engine`), faute de garde-fou à l'écriture. Note : le moteur d'inférence lui-même (`_add()`) n'a pas encore ce garde-fou — angle mort résiduel, accepté pour l'instant. |
| 20/06/2026 | **CoaNIMM — fiabilité des prompts libres, sécurité (confinement), opérations Fichiers/Documents, accessibilité PDF**. FIABILITÉ [modules/coanimm.py] : `_strip_code_fences` robustifié (extrait le bon bloc même avec texte parasite, plusieurs blocs, ou réponse tronquée) ; `generate_code` fait désormais lui-même un retry anti-troncature (protège le chemin /api/coanimm/generate de l'UI, pas seulement run_generated) ; auto-réparation runtime : nouvelle `repair_code` + endpoint `/api/coanimm/repair` + boucle frontend (renvoie l'erreur au modèle, max 2 tentatives) ; synchronisation plan/code : quand l'exploration disque est requise, le code est généré APRÈS l'exploration (plus de code pré-généré puis jeté) ; correctif `run_script` (appelait `db.get_prompt` inexistant et lisait la clé 'content' au lieu de 'text' → AttributeError ; corrigé en `db.list_prompts('script')` + clé 'text', action 'exec_script'). SÉCURITÉ : nouveau module `modules/coanimm_safety.py` — `classify_for_execution` (analyse AST : bloque eval/exec/os.system/os.popen/ctypes/winreg, demande confirmation pour subprocess/réseau) et `build_guard_prologue` (code injecté en tête du script qui confine au runtime écritures, suppressions et déplacements aux seuls dossiers autorisés, via interception de open/io.open/os.open/os.remove/rename/shutil ; lectures libres ; connexions réseau externes bloquées, localhost perm| 29/06/2026 | **Mistral OCR — extraction de texte structuré depuis PDF et images**. [main.py] Route `POST /api/mistral/ocr` : accepte un fichier upload (PDF ou image jpg/png/webp/gif/bmp/tiff) **ou** une URL distante. Encode en base64 (fichier local) ou transmet l'URL directement à l'API `mistral-ocr-latest` via `https://api.mistral.ai/v1/ocr`. Retourne le texte extrait en Markdown (titres, tableaux, formules préservés) + nombre de pages. Entrée catalogue CoaNIMM : `ocr_document` (catégorie Documents). [modules/coanimm.py] Helper `nimm_ocr_document(path='', url='')` : construit un multipart (upload fichier) ou un form-urlencoded (URL) et appelle le endpoint local. Préférable à `nimm_extract_text` pour les PDF scannés ou contenant des images. Ajouté au prologue CoaNIMM et à la liste des helpers disponibles. [modules/coanimm_safety.py] `nimm_ocr_document` enregistré dans `_CAP_HELPER_CALLS` (capacité `recherche`). Nécessite la clé API Mistral. |
| 29/06/2026 | **Mistral Audio Voices + Audio Speech (TTS preset + clonage zero-shot)**. [modules/tts.py] `list_mistral_voices(api_key)` : appel `GET /v1/audio/voices` Mistral, retourne la liste des voix preset disponibles (robuste : retourne [] si clé absente). `synthesize_mistral_speech(text, voice_id, ref_audio_b64, fmt, api_key)` : TTS via `voxtral-mini-tts-2603` avec voix preset OU clonage zero-shot (ref_audio base64) via `POST /v1/audio/speech`. Intégrée dans `synthesize()` via les préfixes `mistral:voice_id` (preset) et `mistral-clone:base64` (zero-shot). Voix Mistral preset ajoutées dans `list_voices()` (🟠 Mistral Speech ⭐⭐⭐⭐⭐). [main.py] `GET /api/mistral/audio/voices` : proxy vers Mistral (liste les voix). `POST /api/mistral/audio/speak` : accepte text + voice_id (form) ou text + ref_audio (multipart), produit un fichier audio MP3/WAV/FLAC/OPUS. Catalogue CoaNIMM : entrée `mistral_speak` (Audio & voix). [modules/coanimm.py] Helper `nimm_mistral_speak(text, voice_id='', ref_audio_path='')` : multipart si ref_audio_path fourni, sinon form-urlencoded ; retourne le chemin du fichier audio produit. [modules/coanimm_safety.py] `nimm_mistral_speak` → capacité `recherche`. Clé Mistral requise. |
| 01/07/2026 | **Modale PIN themee + accessibilite (remplace window.prompt)**. [frontend/index.html] `#pin-modal` : modale sur le pattern `.modal-overlay`/`.modal-box` existant -- pave numerique (0-9, Backspace, Enter), affichage `.pin-dots` (visuel, `aria-hidden`), statut vocal `#pin-modal-status` (`.sr-only`, `aria-live="polite"`), `role="group"` + `aria-label` sur le pave. [frontend/styles.css] `.pin-modal-box`, `.pin-dots`/`.pin-dot`, `.pin-keypad`/`.pin-key`, animation `pinShake` sur erreur, media query mobile (touches agrandies). [frontend/app.js] Controleur `_pinModal` (open/close, saisie tap + clavier physique dont pave numerique, focus trap Tab/Shift+Tab, retour de focus a l'element d'origine a la fermeture, statut vocal du nombre de chiffres saisis). Branche dans `_ensureUnlocked()` (deverrouillage de session, Promise) et `_setUserPin()` (definition/changement de PIN admin, via nouvelle fonction `_askPinModal()`). Remplace tous les `window.prompt`/`window.alert` du flux PIN. Cache-busting : `20260701-2`. |
| 02/07/2026 | **Correction chiralite parent/enfant - le code genere seul les reciproques**. Bug : `enfant_de` collapsait vers `enfant` dans la normalisation, ecrasant le sens inverse (ex : Souleyman/enfant/Khadija au lieu de Souleyman/parent/Khadija). Cause racine reelle : contradiction entre le prompt memoire_deepseek.txt (regle "ne genere jamais la reciproque, le code s'en charge") et son propre exemple (fratrie generait bien la reciproque), plus _save_symmetric() qui bloquait explicitement les relations verticales en attendant que le LLM les fournisse. [modules/memory.py] Modele simplifie a 2 predicats canoniques : `enfant` (sens parent -> enfant) et `parent` (sens enfant -> parent). `PREDICAT_NORMALISATION` : `fils`/`fille`/`enfant_1-4` -> `enfant` ; `enfant_de`/`pere`/`mere`/`prenom_pere`/`prenom_mere` -> `parent` (au lieu de collapser vers `enfant`). `PREDICATS_INVERSES` : inverse de `enfant` est directement `parent` et vice-versa, plus de mot intermediaire `enfant_de`. `_save_symmetric()` : suppression du filtre `PREDICATS_SYMETRIQUES` qui ignorait les relations verticales -- toute relation presente dans `PREDICATS_INVERSES` genere desormais sa reciproque automatiquement, horizontale ou verticale. `_PARENT_PREDS` (moteur d'inference, regle grand-parent) reduit a `{'parent'}` seul. `PREDICATS_MULTI_VALEUR` : `enfant_de` remplace par `parent` (un sujet peut avoir plusieurs parents). [data/prompts/memoire_deepseek.txt] Retrait du 3e triplet de l'exemple fratrie (`Camille/frere/{{USER_NAME}}`) qui contredisait la regle "jamais de reciproque" et poussait le LLM a mal generaliser sur parent/enfant. Nettoyage manuel des triplets `enfant` deja corrompus en base prevu par Laurent depuis NIMM. Cache-busting : `20260702`. |
| 02/07/2026 (2) | **Fiche memoire par personne + systeme "evoques sans lien"**. [frontend/app.js, frontend/styles.css] Refonte de `renderMemory()` : l'affichage passait par categorie en premier niveau (Famille, Travail... repetees pour chaque personne) -- il passe desormais par personne en premier niveau, une fiche unique par sujet, triee alphabetiquement. L'identite (prenom, date_naissance, nationalite...) s'affiche directement en tete de fiche sans sous-titre ; le reste (activite incluse) se range en sous-sections par categorie (`.memory-subsection-title`), dans un ordre fixe (famille, profession, loisirs, quotidien, sante, autre). [modules/memory.py] Nouveau `PREDICATS_LIEN_PERSONNE` : 28 predicats qui expriment un lien avec une personne nommee, repartis horizontal (famille, amitie, voisinage...) et vertical (travail, sante, services...). Nouvelle fonction `sujets_relies(memories)` : construit le graphe de ces liens et parcourt en BFS depuis l'utilisateur pour determiner qui lui est relie, directement ou en chaine (toi -> Khadija -> Nicolas). Objectif : qu'une personne evoquee sans aucun lien reel avec l'utilisateur (ex: une personnalite publique mentionnee en passant) ne se retrouve plus au meme niveau que les vrais proches dans la memoire. [main.py] Route `/api/memory/triplets` : calcule `sujets_relies()` une fois, ajoute un booleen `relie` a chaque triplet retourne. [frontend/app.js] `renderMemory()` separe les fiches reliees (affichees normalement, en premier) des fiches "evoquees sans lien" (regroupees sous un bandeau discret `.memory-section-title--evoques` en bas de liste, memes actions modifier/supprimer). Cache-busting oublie en cours de session (les modifs de renderMemory sont arrivees apres le premier `?v=20260702` du jour) -> corrige en `20260702-2`. A prevoir : afficher le type de lien exact (ami, conjoint, collegue...) dans l'en-tete de chaque fiche reliee, pas seulement le fait qu'un lien existe. Cache-busting : `20260702-2`. |
| 06/07/2026 | **Fix recherche web : tool loop silencieux + cache ephemere**. [hub.py] `_phase2_tools = NIMM_TOOLS if provider == 'anthropic' else None` ajoute dans `process_message_stream` et `process_message` -- seuls les providers Anthropic recoivent encore les outils en phase 2 (finalisation apres tool_call), evitant que DeepSeek/Mistral retentent un tool_call au lieu de repondre en texte. [websearch.py] `search_with_cache()` : court-circuit pour les requetes ephemeeres (mots-cles meteo/scores/actualite immediate) -- recherche fraiche systematique, cache ignore. Fichiers modifies : core/hub.py, modules/websearch.py. |
| 28/07/2026 | **Fix chevauchement visuel — routage Reconnaissance image (Mistral/Pixtral)**. [frontend/styles.css] `#pixtral-model-row` (choix Pixtral 12B / Pixtral Large, affiche uniquement quand Mistral est selectionne en reconnaissance image) n'etait pas une paire etiquette+menu comme les autres lignes de `.routing-grid` (grille 2 colonnes en flux auto) -- il consommait une seule case et decalait toutes les lignes suivantes, provoquant un chevauchement de texte visible quand le bloc s'affichait. Ajout de `grid-column: 1 / -1` pour que le bloc occupe toute la largeur de la grille sans perturber l'alternance colonne 1/colonne 2 des lignes suivantes. Correctif CSS pur, aucun changement HTML/JS -- sans impact sur le label ARIA, l'ordre de tabulation ni la navigation lecteur d'ecran. Cache-busting : `20260728`. |
| 30/07/2026 | **Veille qui se signale, banc d'essai du réordonnanceur, Lyria réveillé**. (1) VEILLE — le travailleur de fond `_veille_worker` (main.py) relevait déjà à échéance, mais son résultat n'allait que dans la console et un diagnostic : rien qui se lise au braille en cours de travail. [veille.py] `_merite_signalement()` (fonction PURE) : nouveautés → toujours ; « rien de nouveau » → jamais (sinon l'annonce horaire devient un bruit qu'on cesse d'écouter) ; panne → UNE fois, dédoublonnée par `dernier_signal`. `relever_les_dus(ingerer=…)` pose `notifie=False` + `dernieres_nouveautes` ; `notifications_en_attente()` = LECTURE UNIQUE (même contrat que les ricochets planifiés). `update_sujet` : liste blanche `_CHAMPS_INSCRIPTIBLES`, sans quoi les sujets créés avant la fonctionnalité rejetaient les nouveaux champs en silence. [main.py] `POST /api/veille/notifications` (POST car la lecture consomme) ; le relevé manuel pose `notifie=True` (il est déjà sous les yeux). [app.js] `_veillePollNotifications` toutes les 5 min → annonce groupée dans `#coanimm-status-announce` (une seule annonce : la zone se vide avant d'écrire) + `_veilleRendreNouveautes` qui laisse une trace copiable dans `#veille-out`. (2) BANC D'ESSAI — [reranker.py] `moteurs_testables()` (liste TOUS les moteurs, y compris indisponibles, AVEC leur raison), `banc_essai()` async, `rapport_texte()`. La même question passée dans chaque moteur sur les mêmes passages : classement, scores, temps. `_modele_pour(moteur, modele)` corrige un piège : `rag_rerank_modele` est un réglage UNIQUE pour plusieurs moteurs — sans lui, le banc enverrait `rerank-v3.5` à Jina et conclurait à tort à une panne. `search_documents` et les moteurs HTTP passent par `asyncio.to_thread` (sinon le banc gèlerait la conversation). Le banc n'écrit AUCUN réglage — instrument de mesure, pas réglage déguisé. [main.py] `GET /api/rag/banc/moteurs`, `POST /api/rag/banc`. [index.html/app.js] panneau dans `#rerank-details` : tableau par moteur avec `th scope="col"/"row"` (un classement se parcourt ligne à ligne, il ne s'écoute pas en paragraphe) + rapport texte brut copiable. (3) LYRIA — [modules/musique.py] Lyria 3 via `generateContent` (`lyria-3-clip-preview` 30 s / `lyria-3-pro-preview` quelques minutes, WAV possible), clé Gemini déjà présente. `_extraire()` parcourt TOUTES les parties (l'ordre n'est pas garanti, variantes camelCase/snake_case acceptées) et sépare audio et paroles — les paroles sont la seule partie lisible au braille. `_raison_refus()` : un blocage de sécurité arrive en 200 sans audio, il est dit et non déguisé en panne réseau. Import httpx tardif pour que les refus (consigne vide, clé absente) répondent même sans httpx. [main.py] `data/musiques/` + fiche `.json` par morceau (zéro migration DB), routes `/api/musique/{modeles,generer,fichier/{nom}}` + liste/suppression, `_musique_nom_sur()` confine le nom de fichier. [index.html/app.js] modale `#musique-modal` (Alt+Maj+U), bouton conditionné à la clé Gemini via `_applyProviderConstraints`, lecteur `<audio>` étiqueté, paroles en zone de texte copiable, téléchargement. `data/musiques/` exclu de git. 3 tests permanents ajoutés (`test_veille_se_signale`, `test_banc_essai_reordonnanceur`, `test_musique_lyria`) — 62 scénarios au total. Cache-busting : `20260729-veille-banc-musique`. |
| 30/07/2026 | **Imagerie réglable (Nano Banana) et vidéo (Veo) — Imagen écarté sciemment**. (0) DÉCISION — la demande était « un vrai Imagen ». Vérification faite dans la doc Google : Imagen est **déprécié et cesse de répondre le 17 août 2026**, et Google renvoie lui-même vers Nano Banana, le modèle que NIMM appelait déjà. Coder dessus, c'était programmer une panne à trois semaines. Les réglages qu'on attendait d'Imagen (format, résolution, choix du modèle) sont donc livrés via l'**API Interactions**, là où Google fait vivre ses nouveautés. La raison est écrite dans `modules/imagerie.py` ET `main.py`, et un test l'ancre (`imagen-` interdit dans main.py). Libellés corrigés : « Gemini (Imagen) » → « Gemini (Nano Banana) » (index.html), services.py, README. (1) IMAGERIE — [modules/imagerie.py] `MODELES` (flash / pro / lite avec leurs tailles réelles : lite = 1K seul), `RATIOS` (10 rapports, 1:1 à 21:9), `options()`, `generer()`. POST `/v1beta/interactions` avec `response_format {type:image, aspect_ratio, image_size}` et **`store: false`** — l'API Interactions conserve requêtes ET réponses par défaut (55 jours en offre payante) : même choix RGPD que l'agent Vibe. `_extraire()` parcourt TOUTES les étapes et TOUS les blocs (`steps[].content[]`, `type` text/image, variantes camelCase/snake_case, raccourci `output_image`) — supposer que l'image est le premier bloc, c'est la perdre dès que le modèle commente. Une taille impossible est corrigée, mais la réponse porte la taille RÉELLE. [main.py] `GET /api/imagerie/options`, `POST /api/imagerie/generer` (génère → **décrit via `_vibe_describe_image` (alt WCAG)** → écrit dans `data/images/` + fiche `.json` + galerie DB existante), `GET /api/imagerie/fiche/{nom}`. (2) VIDÉO — [modules/video.py] Veo 3.1 / 3.1 Fast, opération LONGUE (11 s à 6 min) donc découpée en trois : `lancer()` (`:predictLongRunning`) → `etat()` (GET sur le nom d'opération) → `telecharger()`. `regles(duree, resolution)` **pure** : Google impose 8 s en 1080p et 4K — corrigé AVANT de partir, jamais en silence (sinon six minutes d'attente pour un refus). `personGeneration: allow_adult` posé d'office : seule valeur admise en Europe pour Veo 3.x. `_uri_video()` tolère trois formes de réponse. Un hoquet réseau rend `{fait: False, message}` et NON une erreur : la génération continue chez Google. **Rapatriement immédiat obligatoire — Google efface la vidéo de ses serveurs à J+2.** [main.py] `data/videos/` + fiche `.json` (zéro migration DB), routes `/api/video/{options,lancer,etat,en-cours,fichier/{nom}}` + liste/suppression ; marqueur `_en_cours_*.json` pour reprendre une génération après un F5 ou un redémarrage. (3) INTERFACE — modale `#studio-modal` (bouton 🎬, Alt+Maj+I, conditionné à la clé Gemini via `_applyProviderConstraints`), deux volets. Image : format, résolution, modèle, case « décrire », rendu avec `img.alt` = description réelle (**jamais d'alt inventé** quand elle manque : le texte le dit) + description en zone copiable. Vidéo : réglages nommés, suivi par sondage à **30 s** (une annonce toutes les 5 s couvrirait tout le reste à la synthèse vocale), lecteur `<video>` étiqueté, téléchargement, suppression, reprise automatique des générations en cours. `data/videos/` et `data/musiques/` exclus de git. 2 tests permanents ajoutés (`test_imagerie_reglee`, `test_video_veo`) — 64 scénarios. Cache-busting : `20260729-studio`. |
| 30/07/2026 | **Relecture d'après-livraison : un identifiant de modèle inventé, deux défauts d'API non dits**. Passe de vérification du lot précédent — code écrit sans jamais avoir pu être exécuté (pas de clé Gemini en bac à sable), donc contrôle des points que les tests structurels ne voient pas : les identifiants de modèles et les champs de requête. (1) `veo-3.1-fast-generate-preview` N'EXISTE PAS. Il avait été déduit de la mention « Veo 3.1 & Veo 3.1 Fast » dans les tables de paramètres de Google, alors qu'aucun identifiant « Fast » n'est publié : le modèle réellement appelable à côté de Veo 3.1 est **`veo-3.1-lite-generate-preview`**, et il **ne fait pas de 4K**. Remplacé. Leçon : relever les identifiants dans la liste officielle des modèles, jamais dans la prose. Les trois identifiants image (`gemini-3.1-flash-image`, `gemini-3-pro-image`, `gemini-3.1-flash-lite-image`) et les deux Lyria sont vérifiés bons. (2) `regles()` prend désormais les résolutions du modèle : une résolution non gérée est ramenée ET annoncée, et les deux corrections (résolution puis durée) SE CUMULENT dans la note. Auparavant `lancer()` faisait un repli silencieux `resolution = conf['resolutions'][0]` — exactement le défaut que le reste du module s'interdit. (3) `response_format` image : ajout de **`delivery: inline`** (sans lui, rien ne garantit que l'image revienne en octets plutôt qu'en référence — et ce module ne sait lire que des octets) et de `mime_type` explicite. (4) L'extension du fichier écrit suit le format **reçu** (`extension_pour()`), plus un `.png` en dur : un JPEG rangé sous .png trompe l'utilisateur comme le logiciel qui l'ouvrira. Vérifié au passage : le schéma `steps[].content[]` est bien le schéma courant (le `outputs` historique a été retiré le 06/06/2026, l'en-tête `Api-Revision` est désormais ignoré — rien à envoyer) ; les conventions de nommage sont respectées de part et d'autre (camelCase pour `generateContent` et `predictLongRunning`, snake_case pour l'API Interactions). Tests étendus : identifiants de modèles figés, cumul des corrections, table des extensions. 64 scénarios. |
| 30/07/2026 | **Trois portes pour deux idées, et un texte alternatif qui mentait à quatre endroits**. Remarque de Fernando : « Galerie d'images, Studio image et vidéo, et le bouton Ajouter un fichier ou créer une image — ça fait pas un peu beaucoup pour des choses qui se recoupent ? » Cartographie : le « + » générait DANS le fil, multi-fournisseurs (DALL·E/Mistral/Stability/Gemini avec repli) mais sans aucun réglage et avec « Modifier » ; le Studio générait HORS du fil, Gemini seul, réglable et décrit ; la Galerie ne faisait que consulter. Pas des doublons complets : **deux moitiés**, chacune ayant ce qui manquait à l'autre, sans que rien n'indique laquelle choisir. (1) RANGEMENT (choix de Fernando : « Studio absorbé par le + »). `#toggle-studio` retiré de la barre du haut ; entrée `#plus-studio` dans le menu « + », là où se prennent déjà les décisions « je crée quelque chose ». Visibilité toujours conditionnée à la clé Gemini. Le raccourci **Alt+Maj+I survit au déménagement** — un accès direct perdu serait une régression : traité à part dans le gestionnaire (la table générique déduit l'id de la modale du nom du bouton, ce qui ne marche plus), refuse d'ouvrir si l'entrée est cachée, `window._ouvrirStudio` exposé pour que le raccourci n'ait pas à connaître le menu. `aria-keyshortcuts` porté par l'entrée de menu. Libellé du « + » élargi à la vidéo. (2) TEXTE ALTERNATIF MENSONGER — le vrai défaut trouvé au passage. `alt` valait **la consigne** : il disait ce qui avait été DEMANDÉ, pas ce qui avait été PRODUIT ; au lecteur d'écran, impossible de savoir que le modèle a dérivé. Présent aux **quatre** endroits où une image s'affiche — création dans le fil, retouche, historique, galerie — dont **trois manqués au premier passage et sortis par le test**. Pire cas : après une retouche, la consigne est une INSTRUCTION (« mets-le en noir et blanc »), inutilisable comme description. Correctif factorisé en **une** fonction `_decrireImageGeneree(bubble, b64, url, consigne)` (quatre copies auraient divergé) : alt provisoire honnête → vraie description → `<details>` copiable + annonce lecteur d'écran ; **si la description échoue, on l'ÉCRIT** (« Description automatique indisponible : … ») au lieu de retomber sur la consigne. [main.py] route `POST /api/image/decrire` (b64 ou url → `_vibe_describe_image`), ne lève jamais, rend toujours un champ `raison`. Historique : **pas** de description automatique (ce serait un appel de vision par image à chaque ouverture de fil) mais un bouton « 🔎 Décrire » à la demande. Galerie : les descriptions sont jointes à `GET /api/images` côté serveur (cent vignettes = cent allers-retours sinon) et l'extension n'est plus supposée `.png`. 1 test permanent ajouté (`test_alt_honnete`) — 65 scénarios. Cache-busting : `20260729-studio-plus`. |
| 30/07/2026 | **Audit outillé : trois vérificateurs devenus permanents, et mes propres dettes**. Demande de Fernando : « audit tout ça, corrige au besoin ». Constat de méthode retenu : mes relectures trouvent peu, le code exécuté trouve tout — l'audit est donc écrit sous forme de VÉRIFICATEURS, pas de lecture. (1) CONTRAT INTERFACE/SERVEUR (`test_contrat_interface_serveur`) — c'est LA classe de bug récurrente du projet (bouton Vibe absent du HTML, `[TRUNCATED]` guetté mais jamais émis, clés sans champ de saisie : le code existait, la fonction non). Vérifie les DEUX sens : aucun appel `/api/…` du frontend sans route, et aucune route ajoutée sans être branchée. Routes relevées par l'**AST** et non par regex — piège vécu en écrivant ce test : main.py déclare des chemins en guillemets simples ET doubles, une regex sur un seul style est aveugle sur ~9 routes (le test d'audit préexistant, lui, utilisait déjà l'AST : pas d'angle mort de ce côté). Liste blanche EXPLICITE et bornée (≤ 15) des routes légitimement non citées, chacune avec sa raison ; les familles à adresse construite (`'/api/' + fournisseur + '/batch'`) sont admises **sur preuve** de la ligne qui bâtit l'adresse. Contrôle éprouvé sur sources simulées : attrape les deux défauts, aucun faux positif sur trois cas pièges (guillemets simples, chemin paramétré, concaténation). (2) DETTES CORRIGÉES — deux routes que j'avais moi-même ajoutées sans les brancher : `/api/imagerie/fiche/{nom}` **supprimée** (redondante depuis que la description est jointe à `GET /api/images`), `/api/rag/banc/moteurs` **branchée** (le panneau du banc annonce désormais quels moteurs répondront, AVANT une mesure de plusieurs dizaines de secondes, avec la raison des indisponibles). Sept autres routes mortes documentées dans la liste blanche. **CORRECTION du 30/07 (Fernando) : deux d'entre elles avaient été mal étiquetées.** `/api/voice/list-mistral` et `/api/voice/test-tts/{pid}` sont du **DIAGNOSTIC** — leurs docstrings le disent — donc légitimement sans interface : une route de dépannage n'est pas une fonction inatteignable, et confondre les deux m'a fait proposer de « brancher » des outils de débogage. Pire, j'avais annoncé que les voix Mistral manquaient au sélecteur : **elles y sont déjà**. Cause de l'erreur : le docstring de `list_voices()` (tts.py) annonçait « Kokoro + Piper + Edge » alors que la fonction sert SIX familles (Kokoro, Piper, Edge, Gemini, Voxtral, Mistral Speech) ; j'ai lu le début de la fonction et conclu. Docstring corrigé, et le test exige désormais qu'il reste juste ET que les six moteurs figurent dans le sélecteur unique. Leçon : un docstring périmé n'est pas cosmétique, il produit de faux diagnostics. (3) ACCESSIBILITÉ DES MÉDIAS (`test_accessibilite_des_medias`) — balaie l'interface : aucune `<img>` sans alt, aucune image construite en JS sans alt, aucun lecteur audio/vidéo sans nom NI sans contrôles, aucun bouton muet. Défaut trouvé : le repli défensif du lecteur d'aperçu de voix créait un `<audio>` **sans `controls`** — un son qui démarre et qu'on ne peut plus arrêter au clavier ; corrigé, et le lecteur du panneau reçoit un nom. (4) MODÈLES (`test_modeles_conseilles`) — aucun modèle éteint n'est proposé (vérifié contre la liste officielle : `gemini-2.0-flash`, `gemini-3-pro-preview` et les Imagen sont morts, aucun n'est cité). Le catalogue est déjà VIVANT (interrogé chez le fournisseur puis fusionné avec les conseillés) : la liste en dur n'est qu'une recommandation, pas un plafond. Conseils rafraîchis : `claude-sonnet-4-6`/`claude-opus-4-6` → **`claude-sonnet-5`/`claude-opus-5`** (une génération de retard), ajout de `gemini-3.6-flash`. Date de revue inscrite dans le source, et le test l'exige. (5) Traçabilité : les quatre entrées de la veille étaient datées du 29/07 alors qu'on était le 30 — redatées ici et dans le clone. 68 scénarios. Cache-busting : `20260730-audit`. |
| 30/07/2026 | **Noms accessibles : les raccourcir là où ils sont lus en permanence**. Remarque de Fernando : « le bouton pour appeler le créateur de musique a un intitulé très long ». Vérifié, et c'était le pire de la barre du haut — le mien : « Musique, génération et bibliothèque », 35 caractères relus à chaque passage du curseur, alors que la médiane de la barre est de 1 à 2 mots. CORRIGÉ : « Musique » (7 car.) ; « Ouvrir le studio image et vidéo » → « Studio image et vidéo » (le lecteur d'écran annonce déjà « bouton », « Ouvrir » est redondant) ; et le bouton « + », que j'avais moi-même RALLONGÉ le matin en y ajoutant la vidéo (48 car.), redevient « Ajouter » avec `aria-haspopup="menu"` — un bouton qui ouvre un menu n'a pas à énumérer le menu, lequel s'annonce déjà. Deux libellés préexistants traités au passage, même lieu et même raison : « Enrichir la base de connaissances » → « Base de connaissances » (dire la destination est plus court ET plus clair que l'action), « Ouvrir le panneau micro » → « Micro ». Les infobulles `title`, elles, gardent le détail : elles ne se lisent qu'à la demande. BORNÉ PAR UN TEST : 24 caractères dans la barre du haut, 30 dans la zone de saisie et le menu — les trois endroits traversés en permanence. Le test a immédiatement attrapé mon propre bouton « + ». NB : une première version de la règle proscrivait le mot « Ouvrir » et produisait un faux positif sur « Ouvrir le clavier », qui est JUSTE (ce bouton ferme le panneau micro pour revenir au clavier : il décrit son effet). Borner la longueur plutôt qu'interdire des mots. 68 scénarios. Cache-busting : `20260730-libelles`. |
| 08/08/2026 | **Voix Gemini TTS muettes malgré une clé configurée : même piège que les embeddings, la clé lue au mauvais endroit**. Signalement de Laurent : les voix `✨ Gemini` apparaissent bien dans le sélecteur (Nando les avait câblées), mais « Écouter » échouait systématiquement, silencieusement. CAUSE RACINE (même famille que le bug de latence à froid du 06/08 : les `ContextVar` ne traversent pas vers un thread) — la route `/api/tts/speak` (main.py) exécute la synthèse dans `loop.run_in_executor()` pour ne pas bloquer le serveur pendant l'appel réseau à Google. Or `synthesize_gemini()` (tts.py) allait chercher la clé API lui-même, EN PLEIN MILIEU de ce thread, via `_gemini_api_key()` → `get_api_keys()` → `get_setting()` → `get_conn()`, qui a besoin d'un utilisateur identifié pour savoir quelle base ouvrir. Sans contexte utilisateur dans ce thread, `get_conn()` lève une erreur que `get_setting()` avale silencieusement (repli sur défaut `''`) : NIMM concluait donc à « aucune clé configurée », alors qu'elle l'était bel et bien. Le code gérait déjà correctement ce cas pour Voxtral/Mistral (clé lue dans le contexte asyncio, AVANT l'entrée dans le thread — commentaire présent de longue date dans main.py), mais ce même geste n'avait jamais été fait pour Gemini TTS. CORRIGÉ : `synthesize_gemini()` et `synthesize_gemini_multi()` (tts.py) acceptent désormais un paramètre `api_key` optionnel, transmis en priorité (repli sur `_gemini_api_key()` conservé pour les appels directs hors requête HTTP) ; le routeur `synthesize()` le relaie dans la branche `gemini:` ; `/api/tts/speak` (main.py) lit la clé Gemini dans le contexte asyncio au même endroit que la clé Voxtral, avant `run_in_executor`. BONUS — garde-fou ajouté : quand une synthèse échoue quand même (clé invalide, quota, service indisponible), l'endpoint renvoyait un `BytesIO(None)` qui plantait avec un message technique illisible ; renvoie désormais une erreur HTTP 502 explicite invitant à vérifier les clés API. Cache-busting : `20260808`. |
| 07/08/2026 | **Menus "⋯" des messages : débordement d'écran corrigé des deux côtés**. Deux bugs remontés par Laurent après la correction DeepSeek. (1) Côté messages UTILISATEUR : le menu contextuel (`.copy-menu`, Copier/Modifier) s'affichait hors de l'écran, collé au bord droit. Cause : `_positionMenu()` — la fonction qui gère déjà correctement l'ouverture haut/bas et le clamp horizontal pour les messages de Lia — n'était tout simplement jamais appelée pour les messages utilisateur (`appendUserMessage`), qui n'avaient aucune logique de positionnement. CORRIGÉ : `_positionMenu()` étendue avec un paramètre `anchorRight` (ancre le coin droit du menu sur le bouton et ouvre vers la gauche, pour les messages alignés à droite) ; appel ajouté côté `appendUserMessage` avec `anchorRight=true`. En prime, `.message-actions` (conteneur du bouton côté messages utilisateur) n'avait aucune règle CSS `position` définie, ce qui pouvait faire dériver `.copy-menu` (position: absolute) vers un ancêtre positionné imprévu — ajouté `position: relative`. (2) Menu des DERNIERS messages (Lia) : une fois `_positionMenu()` en place partout, un second cas est apparu — le menu s'ouvrait vers le bas et se faisait couper par la barre de saisie (`#input-area`, fixe en bas d'écran), car le calcul de l'espace disponible se basait sur `window.innerHeight` sans tenir compte du fait que cette barre recouvre une partie de la fenêtre. CORRIGÉ : la limite basse utilisée par `_positionMenu()` est désormais le bord haut réel de `#input-area` (mesuré via `getBoundingClientRect()`), et non plus le bas brut de la fenêtre. Cache-busting appliqué deux fois ce jour (`app.js?v=20260807` puis `20260807-1`, `styles.css?v=20260807`) au fil des correctifs successifs. |
| 07/08/2026 | **Chasse à la latence, suite et fin : cause racine trouvée — DeepSeek réfléchit en cachette**. Reprise de la session du 06/08 : le correctif du bug « fils invisibles » (`max_tokens` 20→300 dans `generate_tab_title`) n'a pas suffi — titre toujours vide en test (`{"name":""}`). Ajout d'un log `[PERF-DEBUG]` dans `_call_openai_compat` (engine.py), déclenché uniquement quand le contenu renvoyé est vide, affichant `finish_reason`, `usage` et la présence de `reasoning_content`. Verdict sur le vif, en conditions réelles (une vraie question déclenchant une recherche web) : `[PERF] premier_evenement_llm(tool_calls): 14.39s`, suivi de plusieurs `[PERF-DEBUG] ... reasoning_tokens=1500/150/15/4, finish_reason='length', reasoning_content_present=True`. CAUSE RACINE (commune aux deux bugs de la session précédente) : `deepseek-v4-flash` a activé le mode réflexion par défaut (effort « high », confirmé par la doc officielle DeepSeek : https://api-docs.deepseek.com/guides/thinking_mode/) — un changement côté DeepSeek, pas un bug NIMM, mais qui explique tout : la réflexion invisible (`reasoning_content`) consomme le `max_tokens` avant même la réponse visible, d'où les titres/résumés vides sur les tâches à petit budget, et ajoute plusieurs secondes avant le premier token/tool_call sur le chat principal. CORRIGÉ : `payload['thinking'] = {'type': 'disabled'}` ajouté aux 3 chemins d'appel DeepSeek OpenAI-compatible dans engine.py — `call_llm_stream_with_tools` (chat principal), `_call_openai_compat` (tâches annexes : titre, humeur, mémoire), `_call_openai_compat_stream` (streaming sans détection d'outils). Effet mesuré en conditions réelles : `premier_evenement_llm` 14.39s → 1.56s sur un message similaire ; génération de titre et note de carnet de nouveau fonctionnelles dans la foulée. Non exploré : l'éventuel gain de qualité perdu sur des tâches complexes en désactivant la réflexion (à surveiller à l'usage — réactivable au cas par cas si besoin). Instrumentation `[PERF]` / `[PERF-ENGINE]` / `[PERF-DEBUG]` conservée dans le code à la demande de Laurent (aide au diagnostic futur, coût négligeable). |
| 06/08/2026 | **Chasse à la latence : trois bugs trouvés par instrumentation, deux corrigés**. Signalement de Laurent : réponses parfois > 10-15s, contre quasi-instantané "il y a quelques jours", peu importe le provider. Diagnostic par chronométrage (`time.perf_counter()`) posé étape par étape dans `process_message_stream()` (`hub.py`) et dans l'appel réseau OpenAI-compat (`engine.py`), plus un script `tests/test_perf_message.py` (appel direct `/api/chat/stream` hors navigateur, authentifié profil + PIN via `X-User-ID`/déverrouillage). (1) CAUSE PRINCIPALE DE LA LATENCE À FROID — `_warmup_embeddings()` (main.py) vérifiait `embeddings_enabled` dans un thread Python à part, sans contexte utilisateur (les `ContextVar` ne traversent pas les threads) : `get_setting()` retombait donc toujours sur son défaut `'false'`, quel que soit le réglage réel du profil. Le modèle `sentence-transformers` (embeddings) n'était donc JAMAIS préchargé au démarrage, et se chargeait à froid (~7-8s) au premier message de la session. CORRIGÉ : le warmup vérifie désormais le réglage pour chaque profil (`set_user_context` + `get_setting` par utilisateur) avant de conclure à l'abandon. Latence à froid mesurée : 15s → 7-8s. Piste restante non traitée : réduire encore ces 7-8s (hors périmètre de cette session). (2) FILS INVISIBLES DANS LA SIDEBAR — bug distinct, remonté en cours de session : plusieurs fils créés récemment avaient un `name` vide en base (pas même le placeholder `💬 Nouveau fil`), donc un rendu totalement blanc dans la sidebar (`renderSidebar()` fait `name.textContent = t.name` sans repli). Cause : `POST /api/threads/{id}/title` (main.py) écrasait le nom du fil par le titre généré par `generate_tab_title()` (hub.py) **sans vérifier qu'il n'était pas vide** — confirmé en interrogeant l'endpoint en direct (`{"name":""}`). La cause en amont (pourquoi le LLM de la tâche « titre » renvoie parfois une chaîne vide) reste À INVESTIGUER — non résolue, hors périmètre de cette session. CORRIGÉ (le symptôme) : l'endpoint ne remplace plus le nom si le titre généré est vide ; le placeholder reste affiché et la génération sera retentée au message suivant. Les 7 fils déjà cassés ont été réparés en masse (script `--repair`, remis à `💬 Nouveau fil`). (3) OBSERVATION SANS SUITE — le payload envoyé à DeepSeek à chaque message pèse ~10 000 tokens rien qu'en définitions d'outils (`NIMM_TOOLS` + outils CoaNIMM), envoyés même quand aucun outil n'est pertinent (ex. "raconte-moi une blague"). Mesuré non bloquant cette fois (TTFT DeepSeek ~0,7s), donc non traité, mais à surveiller si la liste d'outils continue de grossir. Instrumentation `[PERF]` / `[PERF-ENGINE]` laissée en place dans le code (désactivable au besoin) ; script `tests/test_perf_message.py` conservé comme outil de diagnostic réutilisable (`--list`, `--title <id>`, `--repair`, mesure par défaut). |
| 30/07/2026 | **Groq et Cerebras branchés, et la duplication qui les guettait supprimée d'abord**. Demande de Fernando : « ça fera toujours des possibilités de plus ». Les deux servent des modèles à poids ouverts (Llama, Qwen, DeepSeek distillés) à très faible latence — l'argument n'est pas le débit mais le **délai avant le premier mot**, qui compte double quand la réponse est écoutée plutôt que lue. Se marient avec le routage par tâche déjà en place : mémoire, titres et synthèses côté rapide, conversation côté fin. (0) REFACTORING PRÉALABLE — l'adresse de base et le modèle de repli étaient recopiés à **TROIS** endroits d'`engine.py` (appel direct, flux, flux avec outils). Trois copies, c'est la garantie qu'un ajout n'en touche que deux, avec un symptôme discret : le fournisseur répond quand on le teste et reste muet en usage réel. Table unique `FOURNISSEURS_OPENAI_COMPAT` (base, modèle de repli, **`outils`** déclaré et non supposé) + helpers `_base_openai_compat()` / `_modele_openai_compat()`. Les trois sites l'utilisent ; `_SUPPORTED` du flux-outils est désormais **dérivé** de la table, si bien qu'un fournisseur sans appel d'outils retombe proprement sur le flux simple au lieu d'envoyer une requête ignorée. PIÈGE RENCONTRÉ : après suppression des tables locales, `models[provider]` subsistait ligne 2212 — `py_compile` passait, c'était un `NameError` à la première utilisation (même famille que `_finish_reason` et `_raisonnement_acc`) ; attrapé par analyse de portée, pas par la compilation. (1) CÂBLAGE — [engine.py] table, ordre de repli (les deux en FIN : rapides, pas plus fins), `env_map` (`GROQ_API_KEY`, `CEREBRAS_API_KEY`), `_PROVIDER_DEFAULT_MODEL`, `_models_endpoint` (catalogue interrogé en direct : leurs modèles ouverts changent souvent, **rien n'est figé dans le code**), dispatch `call_llm`. [database.py] portefeuilles + `TARIFS_DEFAUT` (ordres de grandeur pour un 70B, ajustables dans l'onglet Coûts). [hub.py] clés d'environnement + les DEUX tables `_KEY_MAP` (dupliquées de longue date). [services.py] catalogue → les champs de saisie de clé apparaissent tout seuls, le formulaire étant engendré depuis le serveur. [index.html] 10 sélecteurs de fournisseur complétés par expression régulière en respectant l'indentation de chaque site. [app.js] modèles conseillés minimaux — le catalogue vivant fait le reste, conformément à la leçon du `veo-3.1-fast` inventé. (2) TEST DE COMPLÉTUDE (`test_fournisseurs_cables_partout`) — vérifie que tout fournisseur déclaré est atteignable de bout en bout : entrée de table complète, modèle par défaut, catalogue de services, tarif, clé d'environnement des DEUX côtés, correspondance dans hub, présence dans les sélecteurs, modèles conseillés, place dans l'ordre de repli. Traque les structures dupliquées plutôt que de compter des occurrences d'adresse — les points d'accès annexes (liste de modèles, agents, solde, complétion de code) réutilisent légitimement la même adresse. La table est lue par AST, `engine.py` important `httpx` (absent de certains environnements de test). Éprouvé sur sources simulées : les trois formes de câblage partiel sont attrapées. 69 scénarios. |
| 30/07/2026 | **RÉGRESSION : « 400 Bad Request » sur toute conversation Anthropic — cause, correctif, et le message d'erreur qui la cachait**. Signalée par Fernando en usage réel. (1) CAUSE, et c'est MA régression : le matin même j'avais rafraîchi les modèles conseillés (`claude-sonnet-4-6` → `claude-sonnet-5`). Or **depuis la génération 4.7, plusieurs modèles Anthropic refusent TOUT paramètre d'échantillonnage** : « non-default `temperature`, `top_p`, or `top_k` values return a 400 error on every request, **regardless of whether thinking is used** ». Ce n'est donc PAS lié à la réflexion — c'est vrai sur chaque appel. NIMM envoyait `temperature` en dur. Modèles concernés : Fable 5, Mythos 5/Preview, Opus 5, Opus 4.8, Opus 4.7, Sonnet 5. (2) CORRECTIF — `_ANTHROPIC_SANS_ECHANTILLONNAGE` + `anthropic_accepte_temperature(model)`, fonction PURE donc testable sans clé ni réseau ; comparaison par PRÉFIXE (les identifiants sont figés, pas des alias glissants) ; **modèle inconnu → on conserve le comportement historique** plutôt que de retirer un réglage à un modèle qui l'accepte peut-être. Appliquée sur les **TROIS** chemins Anthropic : appel direct, flux, et flux-avec-outils. Le test ancre le NOMBRE de chemins (== 3) : n'en corriger que deux, c'est le bug qui revient dès qu'on active les outils. (3) LE DÉFAUT QUI A COÛTÉ LE PLUS DE TEMPS — l'erreur affichée était « Erreur inattendue de anthropic : Client error 400 for url … ». L'API expliquait pourtant le refus mot pour mot, dans le corps de la réponse, **jamais lu** : `classer_erreur_fournisseur` n'avait pas de branche 400 et retombait sur `str(exc)`, qui ne contient que l'adresse. Ajout d'une catégorie « requête » + `_detail_erreur_api(corps)` qui accepte les TROIS rangements du message selon les fournisseurs (`error.message`, `message`, `error` en chaîne, plus `detail` de FastAPI) et rend le corps tel quel s'il n'est pas du JSON. Le corps est désormais conservé dans sa casse d'origine (`brut`), le reste du classement travaillant en minuscules. Sans ce correctif, le diagnostic suivant repartira de zéro. (4) LEÇON — j'avais rafraîchi ces modèles conseillés lors d'un audit dont le test exigeait qu'aucun modèle ÉTEINT ne soit proposé. Le test ne vérifiait pas que les modèles proposés soient COMPATIBLES avec la façon dont NIMM les appelle. Un identifiant valide ne suffit pas : encore faut-il que les paramètres envoyés le soient. 71 scénarios.  |
| 31/07/2026 | **Deux remarques de Fernando, deux familles de défauts — dont deux PRÉEXISTANTS**. (1) « Je ne vois pas Cerebras ou Groq dans les options des fils déjà existants. » Exact : **SIX listes de fournisseurs en dur dans app.js** n'avaient pas été complétées (auto-sélection du chat, `KEY_MAP` du bandeau « clé manquante », repli du catalogue de services, bascule automatique quand le fournisseur est vide ou local, sauvegarde automatique des champs de clé, pastilles de l'onglet Coûts). Mon test de complétude ne regardait que les `<option>` du HTML : il les a toutes ratées. Corrigées, et le test vérifie désormais chaque déclaration **bornée à elle-même** — première version fautive : une fenêtre de 500 caractères débordait sur les listes voisines, qui citent les mêmes fournisseurs, si bien qu'un oubli PASSAIT. Contrôle éprouvé sur sources simulées : oubli total, oubli partiel et renommage d'ancre sont attrapés. (2) « Vérifie que tu n'as pas introduit ce même type d'erreur pour tous les autres LLM. » Aucun défaut introduit par moi, mais **deux trous préexistants de la MÊME famille** : le garde des modèles de raisonnement OpenAI (série o — `max_completion_tokens` obligatoire, `temperature` refusée) et de `deepseek-reasoner` existait sur le flux AVEC outils, mais **ni sur l'appel direct, ni sur le flux SIMPLE** — or c'est ce dernier qu'emprunte la conversation ordinaire. Ajouté aussi à la reprise de réponse (« Continuer »), qui était le dernier chemin sans garde. Gemini et Ollama vérifiés et laissés tels quels : le premier range la température dans `generationConfig` (acceptée par tous ses modèles, la réflexion se règle par `thinkingConfig`), le second est un serveur local tolérant. **CONSTAT DE FOND : la même asymétrie s'est produite trois fois** — adresses de base recopiées à trois endroits, température Anthropic sur trois chemins, garde des raisonneurs sur trois chemins. À chaque fois, un chemin traité et les autres oubliés, avec un symptôme discret : ça marche quand on teste, ça casse en usage. Les tests ancrent désormais le NOMBRE de chemins couverts, pas seulement la présence du correctif. 71 scénarios. |
| 10/08/2026 | **Reprise après dix jours de travail de Laurent : fusion contrôlée, un test devenu faux, une config locale versionnée**. (0) CONTRÔLE ANTI-PERTE (procédure de [[nimm-git-workflow]]) — Laurent a poussé 5 commits (03→09/08 : masque + loader base de connaissances, réparation des fils, **fix latence DeepSeek**, voix Gemini, sauvegarde des bases). Vérifié dans les deux sens : son travail ET le mien sont présents des deux côtés. Écart apparent `groq/cerebras` 14 vs 10 fichiers = **faux positif**, la copie qui tourne ayant deux versions de Python donc deux jeux de `.pyc` ; les sources sont identiques. Vrai écart : la copie qui tourne était en RETARD (il lui manquait mes 2 derniers tests et les 5 commits de Laurent). **Mise à niveau clone → NIMM-main faite AVANT tout rsync inverse**, sans quoi le `--delete` aurait réverté 10 jours de travail. (1) TEST DEVENU FAUX — `test_specificites_anthropic_confinees` exigeait que `payload['thinking']` ne soit posé que dans des fonctions Anthropic. Le correctif de latence de Laurent le pose aussi pour **DeepSeek**, en sens INVERSE : Anthropic l'emploie pour ACTIVER une réflexion (`{'type':'enabled', budget}`), DeepSeek pour la DÉSACTIVER (`{'type':'disabled'}`) — son modèle v4 la lançant d'office, ce qui ajoutait plusieurs secondes avant le premier mot et vidait le budget de sortie en jetons invisibles (d'où les titres et résumés vides). Le test avait raison de se déclencher ; c'est sa RÈGLE qui était périmée. Réécrite : `cache_control` et `output_config` restent propres à Anthropic ; `thinking` est admis ailleurs **sur garde explicite du fournisseur**, et une désactivation doit nommer DeepSeek. Éprouvé sur sources simulées : pose sans garde et fournisseur erroné attrapés, le correctif légitime passe. **Leçon : un test qui échoue après la fusion n'a pas forcément tort, mais sa règle peut avoir vieilli — vérifier laquelle des deux est périmée avant de toucher au code.** (2) CONFIDENTIALITÉ — `data/backup_config.json` (fonction de sauvegarde de Laurent) est **versionné dans un dépôt public** et contient le chemin de son disque (`H:\Mon Drive\…`), l'horodatage de ses sauvegardes et son nombre de profils. Deux conséquences : une arborescence personnelle publiée, et le chemin de l'un ÉCRASANT celui de l'autre à chaque mise à jour. Ajouté au `.gitignore` et exclu de la synchronisation ; reste à le retirer du suivi git (`git rm --cached`), geste qui appartient à Fernando. La fonctionnalité elle-même est intacte : `sauvegarde.py` lit sa configuration via la base, pas via ce fichier. 71 scénarios. |
| 10/08/2026 | **Suite du travail de Laurent : un QUATRIÈME chemin DeepSeek, et sa question tranchée par un réglage**. (1) LE CHEMIN OUBLIÉ — son correctif de latence couvrait « les 3 endroits où engine.py appelle DeepSeek » ; il y en a **QUATRE**. `continuer_reponse_stream` (bouton « Continuer ») relançait donc la réflexion, avec la même attente et le même budget mangé. **Troisième occurrence du même motif en dix jours** (adresses de base, température Anthropic, garde des raisonneurs) : un chemin traité, les autres oubliés, symptôme discret. Le test ancre désormais le NOMBRE d'appels (== 4). NB méthode : son correctif était posé sous DEUX formes (`**({...} if provider_name == 'deepseek' else {})` inline ×2, et `if provider == 'deepseek':` ×1) ; un grep sur une seule forme n'en voyait qu'un — d'où l'obligation de raisonner par chemin d'appel, pas par chaîne. (2) SA QUESTION OUVERTE — « pourquoi le mode thinking désactivé pourrait affecter la qualité sur des questions complexes (pas testé en profondeur) ». Elle n'a pas de réponse tranchée, et c'est précisément pour ça que le choix ne doit pas être figé dans le code : c'est un ARBITRAGE entre profondeur et réactivité. `reflexion_deepseek_desactivee()` (pure, défaut « coupée », panne de base tolérée) + routes `/api/settings/deepseek-reflexion` + case à cocher branchée sur le helper `_wireToggleReglage` existant — **contrat `{active}` identique aux autres réglages à case**, un troisième format aurait été une divergence de plus. Un mode « gardée en conversation, coupée sur les tâches courtes » serait le meilleur des deux, mais il suppose que la tâche soit connue dans engine.py : elle ne l'est pas, et le proposer aurait donné un réglage sans effet. Écarté sciemment, raison écrite dans le code. (3) MON PROPRE TEST A FAIT SON TRAVAIL : `test_contrat_interface_serveur` a refusé la route `/api/settings/deepseek-reflexion` tant qu'elle n'était pas branchée à l'interface. (4) PIÈGE D'ÉDITION, rencontré trois fois : après la fusion, `engine.py`, `main.py`, `index.html` et `app.js` sont **entièrement en CRLF** (git normalise au checkout, `.gitattributes` `* text=auto`). Tout motif multi-lignes en `\n` échoue silencieusement — vérifier les fins de ligne AVANT toute greffe, et employer celle du fichier. 72 scénarios. |
| 10/08/2026 (2) | **Documentation : le README avait dix jours de retard, et un tableau cassÃ© par moi**. Question de Fernando : Â« as-tu mis Ã  jour les fichiers de doc ? Â». RÃ©ponse honnÃªte : ARCHITECTURE.md oui (9 entrÃ©es sur la pÃ©riode, c'est le journal technique et il a Ã©tÃ© tenu Ã  chaque lot) ; **le README non**. Il ignorait Groq, Cerebras, le studio image/vidÃ©o, la musique, la veille, le banc d'essai et la sauvegarde de Laurent â soit deux fournisseurs et cinq fonctions livrÃ©es. DÃFAUT DE MA MAIN trouvÃ© au passage : la ligne Gemini du tableau des fournisseurs avait **5 colonnes pour un en-tÃªte qui en dÃ©clare 4** (reliquat de mon remplacement du 30/07). Un tableau dont une ligne dÃ©borde dÃ©cale toute la lecture au lecteur d'Ã©cran ; il est restÃ© ainsi dix jours. CORRIGÃ : ligne Gemini remise Ã  4 colonnes, Groq et Cerebras ajoutÃ©s au tableau (avec l'argument rÃ©el â dÃ©lai avant le premier mot, Ã  rÃ©server au routage par tÃ¢che), et 5 fonctions ajoutÃ©es Ã  Â« Ce que fait NIMM Â». ANCRÃ PAR UN TEST (`test_documentation_a_jour`) : tout fournisseur de la famille Â« conversation Â» du catalogue `services.py` doit figurer dans le README â les deux sources sont **liÃ©es**, un ajout de fournisseur fera dÃ©sormais Ã©chouer le test tant que la doc suit pas ; les fonctions livrÃ©es sont nommÃ©ment exigÃ©es ; et **tous les tableaux sont vÃ©rifiÃ©s bien formÃ©s**, colonne par colonne. ÃprouvÃ© sur sources simulÃ©es : oubli de fournisseur, oubli de fonction et colonne en trop sont attrapÃ©s. 73 scÃ©narios. |
| 10/08/2026 (3) | **Démarrage à froid : deux causes trouvées en suivant la piste de Laurent**. Il avait ramené la latence de 15 s à 7-8 s et signalait « encore un peu de marge », avec ses repères `[PERF]` (11 points dans `process_message_stream`) et `tests/test_perf_message.py`. Deux défauts, tous deux invisibles en régime établi. (1) **`_get_model()` sans verrou** (`modules/memory.py`) — le préchauffage lancé au démarrage et le premier message peuvent demander le modèle d'embeddings EN MÊME TEMPS : le second voyait `_embed_model` encore à `None` et lançait un **second chargement du même modèle**, en concurrence avec le premier pour le disque et le processeur. `threading.Lock` + **double vérification** (test de présence avant le verrou : le régime courant ne paie rien, seuls les appels concurrents du tout premier chargement s'attendent). Vérifié en simulation : 4 appels simultanés → 1 seul chargement, et coût nul une fois le modèle en place. (2) **`_match_documents` appelé DANS la coroutine** (`core/hub.py`, les DEUX chemins) — il calcule un plongement et peut lancer des appels HTTP synchrones vers le réordonnanceur. Exécuté tel quel, il **bloquait toute la boucle asyncio**, donc le serveur entier ; et à froid, le chargement du modèle (plusieurs secondes) s'y ajoutait. Passé par `asyncio.to_thread` sur les deux chemins — **même motif que partout : n'en traiter qu'un, c'est laisser le défaut sur l'autre**. Écartés après vérification : `build_memory_context_permanent_only()` retourne toujours `''` (coût nul), `_match_bibliotheque()` ne fait que du fuzzy local sur un index — ni embedding ni réseau. **HONNÊTETÉ : le gain n'est pas mesuré.** Je ne peux pas exécuter NIMM (ni clé ni serveur) ; ces deux correctifs sont déduits de l'analyse, pas chronométrés. Le script de Laurent permet de le vérifier en conditions réelles. Un test existant tenait `_match_documents` par la forme exacte de son appel : il a détecté le changement, sa règle a été rendue robuste à la forme tout en gardant son intention (les deux chemins). 74 scénarios. |
| 10/08/2026 (4) | **RÉGRESSION VÉCUE : réponse entièrement MUETTE après une recherche web (Anthropic)**. Signalée par Fernando en usage réel : « Content de te retrouver. Je cherche. », puis « Recherche en cours… », puis « NIMM t'a répondu » — et RIEN. DIAGNOSTIC : aucune erreur affichée, donc **aucune exception** (le bloc de rattrapage émet `[ERREUR: …]`) : le flux s'est terminé normalement sans produire un seul caractère. En phase 2 — après l'exécution de l'outil — `process_message_stream` **REDÉCLARE** les outils à Anthropic (`_phase2_tools = NIMM_TOOLS`), ce qui est structurellement obligatoire dès que l'historique contient un `tool_use` et son `tool_result`. Mais le chemin employé alors, `_call_anthropic_stream`, ne sait lire **QUE du texte** : il ignore les blocs d'appel d'outil. Le modèle, autorisé à chercher encore, a redemandé l'outil — dans le vide. **Le commentaire du code tirait déjà cette conclusion pour DeepSeek/Mistral/OpenAI (« ce chemin ne sait pas traiter un deuxième tool_calls, d'où un flux silencieux ») sans la tirer pour Anthropic, le seul à qui l'on repasse les outils.** CORRECTIF DE FOND : `outils_interdits` sur `_call_anthropic_stream` et `call_llm_stream` → les outils restent **déclarés** (on ne peut pas les retirer sans refus de l'API) mais `tool_choice: {'type':'none'}` en **interdit l'usage**. Le modèle répond alors en texte avec ce qu'il a déjà obtenu. Activé en phase 2 uniquement, et seulement quand des outils sont redéclarés. GARDE-FOU INDÉPENDANT DE LA CAUSE : `_avant_phase2` mesure la réponse avant la phase 2 ; si rien n'est venu, NIMM **le dit** et journalise. Une réponse muette est pire qu'une erreur — la synthèse vocale annonce « NIMM t'a répondu » et il n'y a rien à écouter. Ce garde-fou vaut pour tout fournisseur et toute cause future. NB : le chemin NON diffusé (`process_message`) n'a pas ce défaut, `call_llm` sachant lire les appels d'outil. 75 scénarios. |
| 16/08/2026 | **La sortie technique de NIMM était perdue — et de toute façon inaccessible**. Question de Fernando pendant le diagnostic du silence : « comment je fais avec mon lecteur d'écran pour trouver les infos que tu me demandes ? ». Constat : `LANCER_NIMM.bat` démarre uvicorn avec `-WindowStyle Hidden` et **sans aucune redirection** — toute la sortie (`[HUB]`, `[ENGINE]`, `[PERF]`, traces d'erreur) partait dans une fenêtre cachée et disparaissait. Même un utilisateur voyant ne pouvait pas la lire ; au lecteur d'écran, une console défilante est de toute façon impraticable. **Le seul canal de diagnostic du projet était donc inutilisable par son utilisateur principal.** CORRIGÉ : `LANCER_NIMM.bat` redirige vers `nimm.log` (et `nimm.err.log`), avec rotation d'un cran au démarrage ; déjà couvert par `.gitignore`. Route `GET /api/journal-technique?lignes=&filtre=` (bornée à 1000 lignes, filtre insensible à la casse, message explicite si le fichier n'existe pas encore). Panneau « 📜 Journal technique » dans les Réglages, à côté du journal de fonctionnement : champ de filtre (Entrée valide), boutons Afficher et Copier, et surtout une **zone de texte** — navigable ligne à ligne, sélectionnable, copiable au braille, là où une console ne l'est pas. NB : le « Journal de fonctionnement » existant (`add_diagnostic`) reste complémentaire — il consigne les DÉCISIONS expliquées en clair (document écarté, panne de fournisseur, coût, veille, sauvegarde), pas la sortie brute. Son silence depuis le 01/08 avait été pris à tort pour un bug : il n'écrit que sur événement, et aucun ne s'était produit. Vérifié au passage, contre une crainte de ma part : `asyncio.to_thread` **propage** les ContextVar (donc le profil utilisateur) — c'est `threading.Thread` qui les perd, le bug que Laurent avait corrigé dans le préchauffage. Mon passage de `_match_documents` en fil séparé est donc sain. 75 scénarios. |
| 16/08/2026 (2) | **Silence Anthropic, suite : le flux JETAIT la réflexion et AVALAIT ses erreurs**. Le garde-fou posé plus tôt a fait son travail (message à l'écran + trois entrées au journal : « aucun texte en phase 2 »), mais le silence persistait. Retour au parsing du flux Anthropic, et deux défauts MASQUANTS y ont été trouvés — tous deux empêchaient de diagnostiquer. (1) **Seuls les blocs de TEXTE étaient lus** : `data['delta']['text']`, rien d'autre. Or Sonnet 5 et Opus 5 ont la **réflexion adaptative toujours active** et émettent des blocs d'un autre type (`thinking`), purement et simplement jetés. Si la réflexion consomme le budget, il ne reste RIEN à afficher — exactement le défaut que Laurent avait trouvé chez DeepSeek, mais côté Anthropic et sans réglage pour le couper. La réflexion est désormais captée et, si aucun texte n'est sorti, remontée en `__raisonnement__` (que NIMM sait déjà afficher) avec une trace explicite. (2) **`except Exception: continue`** sur chaque ligne du flux : toute erreur de lecture disparaissait sans laisser de trace, ce qui rendait la cause introuvable. Les erreurs sont maintenant comptées et la première est journalisée. (3) Bug annexe : le repli après refus du `cache_control` **rappelait `_call_anthropic_stream` sans transmettre `outils_interdits`** — le silence pouvait donc revenir par ce chemin. Le test ancre les DEUX appels. MÉTHODE : après trois correctifs posés sans jamais voir la cause, le parti pris a changé — rendre le comportement OBSERVABLE plutôt que deviner une quatrième fois. C'est ce que permettent désormais le journal technique (16/08) et ces traces. 75 scénarios. |
| 16/08/2026 (3) | **Silence Anthropic : REPLI SANS OUTILS, après trois correctifs posés à l'aveugle**. Le garde-fou et la lecture de la réflexion n'ont rien changé : toujours aucun texte en phase 2, et pas même de bloc de réflexion. Conclusion : `tool_choice: {'type':'none'}` est vraisemblablement **ignoré** par l'en-tête `anthropic-version: 2023-06-01`, donc le modèle continue de redemander un outil dans un flux qui ne sait pas les lire. CHANGEMENT DE MÉTHODE : cesser de négocier les OPTIONS de l'API et changer la QUESTION. Si la phase 2 reste muette, l'historique est **reconstruit sans aucun appel d'outil** — les messages de rôle `tool` et les `tool_calls` sont retirés, et les résultats obtenus sont **fusionnés dans le dernier message utilisateur** (« Voici le résultat de la recherche… réponds sans utiliser d'outil »). Plus aucun outil n'est alors déclaré (`tools=None`), donc le modèle n'a plus AUCUN moyen d'en redemander : il ne lui reste qu'à répondre. Ce repli ne dépend d'aucune subtilité d'API — ni `tool_choice`, ni version d'en-tête, ni fournisseur. Fusion dans le dernier message plutôt qu'ajout à la suite : deux messages `user` consécutifs sont une forme que tous les fournisseurs n'acceptent pas. Vérifié en simulation : aucun rôle `tool` ni `tool_calls` résiduel, résultats préservés, historique bien formé. Si même ce repli échoue, le message le dit — et le journal aussi. LEÇON : quatre correctifs sur ce seul défaut, dont trois posés sans jamais avoir vu la cause. Le tournant a été d'admettre que je devinais, et de préférer une solution qui ne suppose RIEN du comportement de l'API à une solution élégante qui suppose beaucoup. 75 scénarios. |
| 25/08/2026 | **Mémoire : uniformisation des données, taxonomie fermée, verrous UI, âges précis**. Laurent a demandé une passe d'uniformisation de la vue 🧠 Mémoire. Diagnostic : la base cumulait plusieurs générations de formats — 14 valeurs `type` au lieu de 3, des prédicats hors taxonomie stockés bruts (`normalize_predicat` renvoyait l'inconnu tel quel), des fiches « personnes » factices (`[F]`, pays de la Coupe du Monde, camion de Laurent), des triplés dupliqués (`mere`/`prenom_mere`/`parent` Jeannette), des relations dans le bloc identité, des âges figés et faux (Maïssane « 18 ans » au lieu de 17 — la Règle 4 ne calculait que par année). [modules/memory.py] `normalize_predicat()` devient une LISTE FERMÉE : un prédicat inconnu est rejeté (triplet ignoré, log `⛔`) au lieu d'être stocké brut. Taxonomie étendue (`lieu_naissance`, `origine`, `lieu_etude`, `identifiant_professionnel`, `tarif_consultation`, `abonnement`, `compte_joint`, `mutuelle`, `interet`, `questionnement`, `theorie`, `frere_ou_soeur`, prédicats PoE) et nouvelles normalisations (`medecin_traitant`→`medecin`, `telephone`→`tel_portable`, `possession`→`equipement`, `etablissement_scolaire`→`ecole`, `comportement`→`trait`, `benevolat`→`engagement`). Règle 4 corrigée : âge calculé avec précision jour/mois (`_parse_date_naissance`/`_age_depuis_naissance`), l'âge ne progresse qu'après l'anniversaire. `_add()` accepte type/memoire_type (âges/anciennetés inférés en `trait`). Nouvelle fonction `unlock_memory()`. [main.py] `/api/memory/triplets` expose `locked` ; routes `POST /api/memory/{key}/lock` et `/unlock`. [frontend/app.js] bouton 🔒/🔓 sur chaque ligne mémoire (verrouiller/déverrouiller à la main) ; libellés de catégories `croyances` (🕯️) et `amities` (🤝) ajoutés. [frontend/index.html] cache-busting `20260825-memoire`. NETTOYAGE DES BASES (profils laurent, nadia, maya, mei, innes) : sujets parasites et personnalités publiques sans lien supprimés, `type` reclassé en 3 valeurs, relations sorties du bloc identité, `date_naissance`/`lieu_naissance`/`age` en tête de fiche, âges recalculés, structure familiale réécrite avec les vrais prénoms (Nadia → enfant Innès/Maïssane/Maya, Laurent conjoint Nadia) + nuance belles-filles (`beau_parent`, contexte explicite) et `origine = né sous X` restaurée après erreur de purge ; faits familiaux confirmés verrouillés 🔒 (14 dans la base de Laurent, 9 dans celle de Nadia, via `settings.memory_locks`). Sauvegardes avant nettoyage conservées dans `data/*.bak-20260825*`. |
| 25/08/2026 (masques privés) | **Masques privés par compte** — un masque peut désormais être réservé à un profil avec le champ `owner` (id, ex. `"laurent"`) dans son JSON. [main.py] `list_masks()` filtre : un masque privé disparaît du sélecteur pour les autres comptes. [core/hub.py] `load_mask()` refuse un masque privé aux non-propriétaires (repli `lia.json`, log `🔒`) et indexe son cache par `(mask_id, utilisateur)` pour ne jamais servir le masque d'un profil à un autre. Masque `iris_deepseek.json` passé en privé (`owner: laurent`). ARCHITECTURE.md : section Modes de personnalité documentée. |
 

---

## Conversation Live, et le mode fantôme qui change de place (26/08/2026)

### Le constat qui a lancé le chantier

Fernando, après plusieurs semaines d'usage : le bouton « Mode fantôme » de la
barre du haut ne pouvait être actionné qu'une fois le fil ouvert — donc, en
pratique, après que les premiers échanges avaient déjà été écrits. La promesse
« aucune trace conservée » ne tenait pas à l'endroit où on la faisait.

Deux mouvements, donc :
1. le réglage **descend** dans la création du fil, là où il peut tenir parole ;
2. la place libérée dans la barre, et le raccourci **Alt+F**, vont à une
   fonction qui manquait : **parler à NIMM et pouvoir le couper**.

### Le mode fantôme à la création

- `ThreadCreate` accepte `ghost`. `POST /api/threads` inscrit le fil dans
  `ghost_threads` **avant** que le moindre message existe.
- `_add_to_ghost_list()` — symétrique de `_remove_from_ghost_list()` qui
  existait déjà. Ne perd pas les autres fils, ne crée pas de doublon, et
  reconstruit une liste illisible plutôt que de ne rien protéger.
- La case vit dans la modale « Nouveau fil », **hors** du bloc « Options
  avancées ». Volontairement : une décision de confidentialité ne se cache pas
  derrière un repli, surtout au lecteur d'écran, qui devrait alors déplier pour
  la trouver. Un test l'ancre.
- La case repart **décochée** à chaque ouverture : ne rien conserver reste un
  choix explicite, jamais un reste de la fois précédente.
- La même case sert dans « Paramètres du fil » pour basculer un fil déjà
  ouvert — c'est le seul endroit qui reste depuis que le bouton a disparu. Le
  texte d'aide y change, parce que la promesse n'est pas la même : activer
  après coup n'efface pas ce qui est déjà écrit, et le dire vaut mieux que de
  laisser croire le contraire.
- La route `/ghost` est une **bascule**, pas une affectation : l'interface ne
  l'appelle que si l'état a changé, sinon elle mettrait le fil dans l'état
  inverse de celui demandé.

### La conversation Live — `modules/live.py`

**Ce qui distingue ce mode de `tts.py` + `stt.py`.** La chaîne classique est
séquentielle : enregistrer, transcrire, interroger, synthétiser, jouer. Chaque
maillon attend le précédent, et le total tourne autour de cinq secondes. C'est
utilisable, mais ce n'est pas une conversation : on ne coupe pas la parole à
quelqu'un qui met cinq secondes à commencer sa phrase.

**Deux moteurs, et le second n'est pas un luxe.**

| Moteur | Comment | Latence | Interruption |
|---|---|---|---|
| `gemini` | Live API, audio bidirectionnel natif (WebSocket) | ~1 s | vraie, gérée par Google |
| `chaine` | Whisper local + LLM du fil + voix TTS de NIMM | 3 à 6 s | approximative |

Le repli existe parce que sans lui, quelqu'un sans clé Gemini n'aurait rien du
tout. Sa faiblesse est écrite dans l'interface plutôt que masquée.

**Décisions de conception, et leurs raisons.**

- **La clé ne sort pas du serveur.** L'interface parle à NIMM, NIMM parle à
  Google. Le raccourci « le navigateur se connecte directement » est plus
  rapide à écrire et met la clé dans la page — donc dans l'historique, dans les
  outils de développement, et dans toute extension installée. Écarté. Un test
  vérifie que l'adresse de Google n'apparaît nulle part dans `app.js`.
- **Les deux transcriptions sont demandées, toujours.** `inputAudioTranscription`
  et `outputAudioTranscription`, deux objets vides dont c'est la *présence* qui
  compte. Sans elles, une conversation vocale ne laisse rien de lisible, et
  devient inutilisable sur un afficheur braille.
- **`construire_setup()` est une fonction pure**, donc testée sans ouvrir de
  socket. C'est important : la configuration d'une session Live **n'est pas
  modifiable une fois la connexion ouverte**. Une faute ici ne coûte pas un
  message, elle coûte la session entière.
- **`activityHandling` est écrit** alors que sa valeur est déjà le défaut. Un
  défaut non écrit est un défaut qui change un jour sans prévenir.
- **`interpreter()` est pure elle aussi**, et rend toujours une *liste* : un
  seul message de Google peut porter une interruption, deux transcriptions et
  du son. Elle place **l'interruption en premier**, quel que soit son rang dans
  le message d'origine — l'interface doit vider sa file de lecture avant tout
  le reste, sinon on entend la fin d'une phrase déjà annulée.
- **Un message illisible produit une erreur, jamais un silence.** Et si Google
  demande un outil alors qu'aucun n'est déclaré, c'est dit. Leçon directe de la
  réponse muette : ce qui n'est écrit nulle part coûte trois séances.

### Côté navigateur

- Deux contextes audio **séparés** : entrée à 16 kHz, sortie à 24 kHz. Ce sont
  deux horloges ; les mélanger obligerait à rééchantillonner à la main, avec le
  grésillement qui va avec.
- Les morceaux reçus sont mis **bout à bout sur une horloge** (`_liveProchain`) :
  ils arrivent plus vite qu'ils ne se jouent, et se superposeraient tous à
  l'instant zéro.
- Couper la parole **vide** la file, ne la met pas en pause : reprendre plus
  tard la fin d'une phrase annulée n'aurait aucun sens dans un dialogue.
- `echoCancellation` est indispensable — sans elle, NIMM s'entend parler et se
  coupe lui-même en boucle.
- Capture par `AudioWorklet` chargé depuis une **URL de données**, pour que NIMM
  reste en un seul fichier de script ; repli sur `ScriptProcessor`, déprécié
  mais universel.

### L'accessibilité, et le point contre-intuitif

**La transcription ne s'annonce PAS toute seule.** Un `aria-live` la ferait lire
par le lecteur d'écran *pendant que NIMM parle* : deux voix simultanées, et plus
rien de compréhensible. Elle vit donc dans un `<textarea readonly>` que l'on
parcourt, relit et copie quand on veut — au braille, en silence.

Seul **l'état** (« À toi de parler », « NIMM parle », « Tu as coupé NIMM »)
est annoncé : c'est court, et ça se glisse entre deux phrases.

Autres points : le curseur de lecture ne défile pas si l'on est en train de
relire ; Échap raccroche ; Alt+M coupe le micro ; le focus revient d'où il
venait ; un champ permet d'**écrire au lieu de parler** sans quitter la session,
pour un nom propre ou une adresse qui passe mal à l'oral.

### Confidentialité

`modules/live.py` n'importe **aucune** fonction d'écriture : la garantie est
structurelle, pas seulement promise dans un commentaire, et un test l'ancre.
La transcription reste en mémoire du navigateur ; elle ne touche le disque
qu'après une question posée **une fois, à la fin**, dont le défaut est de ne
rien garder. Le moteur `chaine` s'appuie sur un fil **fantôme** (qui n'enregistre
donc aucun message) détruit au raccroché.

### Deux défauts trouvés en chemin

- **`load_mask()` se repliait sur `lia.json`**, un masque personnel **exclu du
  dépôt** (il figure dans la liste d'exclusion de synchronisation). Sur toute
  machine autre que celle où il a été créé — un clone neuf, la machine de
  Laurent — le repli visait donc un fichier absent, et la seconde ouverture
  levait **hors** du rattrapage.
  NIMM ne répondait alors plus du tout. Repli refait sur le premier masque
  réellement présent, avec un masque minimal en dernier recours.
- **Deux caractères écrits en latin-1** dans une greffe binaire de `app.js`. Le
  contrôle de syntaxe JavaScript passait, la page se chargeait, et le fichier
  n'était plus lisible en UTF-8. D'où un nouveau test qui balaie **tous** les
  fichiers sources (167 aujourd'hui) et refuse le moindre octet non conforme.
  C'est le genre de faute qu'une relecture ne voit pas et qu'une machine voit
  en une seconde — et c'est exactement pour cela qu'il est permanent.

### Ce qui n'a pas été essayé pour de vrai

Ni le moteur Gemini Live, ni le repli Whisper n'ont été éprouvés au micro :
aucune clé, aucun micro de mon côté. Les parties pures sont testées, le contrat
interface/serveur est vérifié, le reste attend un vrai essai.

Tests : 83 scénarios (`tests/test_coanimm_agentique.py`).

---

## Les outils de NIMM dans la conversation Live (26/08/2026, second lot)

### La question qui a lancé le lot

Fernando, juste après le premier lot : « si j'utilise l'option via Gemini Live,
tout se fera via Gemini — les recherches, le raisonnement ? »

Oui, et c'était le compromis que je n'avais pas assez souligné. Sans outils
déclarés, une session Live donne **un Gemini rapide qui te connaît**, pas
**NIMM** : il part avec la mémoire longue, le prénom et le masque, mais il est
coupé de la recherche web, de la base de connaissances, du carnet, de l'agenda
et des vingt-cinq outils.

### Ce qui a été trouvé en ouvrant le capot — le vrai sujet du lot

`_execute_tool()` commençait par :

```python
query = args.get('query', '').strip()
if not query:
    return '[Aucun résultat — paramètre query vide]'
```

Ce garde était **inconditionnel** et placé **avant tout aiguillage**. Or dix des
vingt-cinq outils n'ont pas de paramètre `query` :

`get_weather` (city), `run_code` (code), `write_file` (filename),
`geocode_address` (address), `extract_url_content` (url), `describe_image`
(url), `get_exchange_rate` (amount), `get_jours_feries` (year),
`get_country_info` (country), `search_acceslibre` (name/city).

Ils étaient déclarés au modèle, appelés par lui, et répondaient invariablement
« paramètre query vide » **sans jamais atteindre leur branche**. Le modèle, lui,
ne proteste pas : il enchaîne sur autre chose. Rien dans l'interface, rien dans
les journaux, rien à voir — seulement quelque chose qui n'arrivait jamais.

C'est le genre de défaut qu'aucune relecture ne trouve. Celui-ci est sorti
parce qu'il fallait **réutiliser** la fonction ailleurs. Confirmation, encore,
que le code qu'on exécute en dit plus que le code qu'on relit.

Correction : le garde ne s'applique qu'aux outils qui déclarent vraiment
`query`, et la liste se **déduit des déclarations** (`_outils_exigeant_query()`)
au lieu d'être écrite à la main — sans quoi elle vieillirait au premier outil
ajouté.

### La traduction vers la Live API

`outils_pour_live()` — fonction pure, donc vérifiable sans réseau, et il le
faut : une déclaration mal formée est refusée **à l'ouverture de la session**,
pas au moment de l'appel, et emporte donc toute la conversation.

- NIMM déclare au format OpenAI (`{'type':'function','function':{…}}`), Google
  attend une liste plate de `functionDeclarations` dans **une seule** entrée
  `tools`.
- Les types restent en **minuscules** : c'est la forme employée par la
  documentation REST de Google, et déjà celle de NIMM.
- Un `required` nommant un paramètre inexistant est nettoyé.
- Un objet **sans propriété** fait échouer la déclaration : on n'envoie alors
  aucun schéma plutôt qu'un schéma vide.

### Ce qui est écarté, et pourquoi ce n'est pas un oubli

`run_code` et `write_file` restent dehors :

- une session Live **ne conserve rien** ; y produire un effet durable sur le
  disque serait contradictoire, et invisible dans la transcription ;
- CoaNIMM demande l'accord **capacité par capacité**, dans une fenêtre qu'on ne
  peut ni lire ni atteindre au milieu d'une conversation parlée.

On ne bricole pas une approbation à la voix : on ferme la porte, et on l'écrit.
Vingt-trois outils en lecture restent disponibles.

### L'exécution, et le piège qu'elle contenait

L'outil tourne dans une **tâche à part** (`create_task`). L'attendre dans la
boucle de réception arrêterait la lecture des paquets venant de Google — donc
la voix — pendant toute sa durée. Mieux vaut un silence pendant qu'il travaille
qu'une parole hachée.

Trois garde-fous :

- **un nom jamais déclaré ne s'exécute pas** — la règle protège autant d'une
  dérive du modèle que d'un outil écarté exprès ;
- **`toolCallCancellation`** : si l'on coupe NIMM pendant qu'un outil tourne,
  sa réponse n'est pas renvoyée — elle relancerait une phrase qu'on venait
  justement d'interrompre ;
- **les tâches en cours sont annulées à la fin de la session**, sinon elles
  écriraient dans une connexion déjà fermée.

### L'annonce, et pourquoi elle est double

Un outil coûte une à deux secondes **au tour qui l'emploie**. Pendant ce temps,
NIMM se tait. Dans une conversation parlée, un silence inexpliqué ressemble à
une panne.

Le passage est donc **annoncé dans l'état** (« NIMM consulte le web… ») **et
écrit dans la transcription**, sur sa propre ligne, entre crochets. En relisant
au braille, on distingue d'un coup ce que NIMM a **dit** de ce qu'il est allé
**chercher**. La conservation en fil normal garde cette distinction.

Les noms sont **traduits en français** : `search_acceslibre` ou
`get_jours_feries` ne veulent rien dire à l'oreille. Un outil absent de la table
est annoncé sous son nom brut plutôt que passé sous silence — et un test
signale l'oubli d'étiquette.

### Une course corrigée avant d'être vue

La case « Donner ses outils à NIMM » était envoyée sans attendre
(`fetch(...).catch()`), puis la session s'ouvrait aussitôt. Le serveur lit ce
réglage **au moment de configurer la session** : la requête arrivait parfois
après, et la case était sans effet une fois sur deux. L'enregistrement est
désormais **attendu**.

Tests : 86 scénarios. Les contrôles de ce lot ont été éprouvés sur des sources
simulées (garde restauré, outil d'écriture laissé passer, schéma vide, étiquette
manquante) : les quatre défauts sont bien vus.

---

## Manipuler une image, et le raccourci du mode Live (28/08/2026)

### Le raccourci

`Alt+F` ne convenait pas — trop proche des raccourcis du navigateur. La
conversation Live rejoint **`Alt+Maj+K`**, la famille où vivent déjà tous les
panneaux (`Alt+Maj+F` fils, `A` agenda, `M` mémoire, `G` galerie, `E`
enrichissement, `P` paramètres, `O` promptothèque, `R` recherches, `T` CoaNIMM,
`U` musique, `S` saisie, `I` studio). `Alt+F` est rendu.

Traité **à part** de la table `SHORTCUTS` plutôt qu'ajouté dedans : le bouton
sert aussi à **raccrocher** quand une conversation est en cours, et il ne faut
alors pas envoyer le focus dans une modale fermée.

Un test relève désormais les deux mécanismes (table et cas particuliers) et
**refuse qu'une lettre soit attribuée deux fois** — un doublon ferait gagner le
premier arrivé, en silence. Treize lettres restent libres.

### « Manipuler une image » — d'où vient l'idée

Du dossier `dossier_papillons` de Fernando, où **les noms de fichiers étaient
les consignes** : « Il faut garder le papillon qui est au premier plan, posé
sur un bras, mais si possible sans voir le bras, et surtout enlever la dame en
arrière-plan avec son sac ».

En relisant ce dossier, une chose saute aux yeux : le travail était de **deux
natures**, et les confondre serait une faute.

| | Nature | Exemple | Qui le fait |
|---|---|---|---|
| Exacte | découper, transformer | recadrer au carré, pivoter, agrandir, éclaircir | **la machine**, au pixel près |
| Inventive | imaginer ce qui manque | enlever la dame, effacer un mur, une barre de fer | **le modèle**, qui redessine |

Confier un recadrage à un modèle génératif est une mauvaise idée : il ne
**découpe** pas, il **redessine**. Sur une photo de famille, tous les pixels
changent, et les visages avec. Inversement, aucune bibliothèque locale ne fera
disparaître la dame au sac.

### `modules/retouche.py`

- **`analyser(consigne)`** — fonction pure. Lit la phrase, reconnaît les
  opérations exactes (rotation, redressement EXIF, miroir, recadrage par ratio
  ou par marge, échelle, largeur imposée, luminosité, contraste, netteté, noir
  et blanc), repère les marqueurs inventifs, et tranche.
- **Règle du mélange** : si la consigne contient les deux natures
  (« recadre et enlève la dame »), **tout** part au modèle. Faire la moitié
  localement puis l'autre moitié autrement donnerait un résultat dont personne
  ne saurait dire ce qu'il contient.
- **Exception nécessaire** : « enlève les bords blancs » est un **rognage**,
  pas une invention. Sans elle, le mot « enlève » suffisait à envoyer un simple
  recadrage chez le modèle. Elle est testée **avant** les marqueurs inventifs.
- **Nuance d'intensité** : « un peu », « beaucoup », « légèrement » modulent le
  facteur. Un test vérifie que « beaucoup » fait plus que « un peu ».
- Le champ **`raison`** n'est pas décoratif : c'est ce qui sera lu à
  l'utilisateur. Il est toujours rempli, y compris quand la consigne est vide.

### Ce qui est dit du résultat — et c'est tout le sujet

Fernando ne voit pas l'image. **La phrase qui la décrit EST le résultat.** Le
panneau en produit trois, dans un champ de texte copiable :

1. **la voie** — « Retouche EXACTE, faite sur ta machine » ou « Image
   REDESSINÉE par le modèle : tous les pixels ont changé » ;
2. **le journal** — les opérations réelles, avec dimensions de départ et
   d'arrivée, et le **poids** (le PNG sans perte pèse plusieurs fois le JPEG
   d'origine : le dire évite la surprise) ;
3. **la description** — ce que NIMM **voit** dans l'image obtenue.

La description part des **octets obtenus**, jamais de la consigne. C'est la
règle du texte alternatif honnête, corrigée le 29/07 pour les images créées et
appliquée ici aussi : servir la demande à la place de la description, c'est
répondre à côté sans que personne puisse s'en apercevoir. Le commentaire du
modèle est rendu **séparément**, sous son propre nom, pour qu'on ne le prenne
pas pour une description. Et une description absente est **dite**.

La voie est en outre annoncée **avant** de lancer, pendant qu'on tape : savoir
si l'image sera découpée ou redessinée change la confiance qu'on lui accorde.

### Deux détails qui comptent

- **PNG systématiquement en sortie.** Réencoder une photo en JPEG à chaque
  retouche la dégrade un peu plus, et sur une série de reprises successives
  cela finit par se voir. Le bouton « Repartir de ce résultat » rend ces
  reprises normales : le prix du sans-perte est donc justifié.
- **Pillow travaille en bloquant** : l'appel passe par `asyncio.to_thread`,
  sinon un agrandissement de grande image fige tout le serveur.

### Ce qui n'est PAS fait, et pourquoi

Le dossier papillons employait **Real-ESRGAN** (67 Mo de poids) pour agrandir
sans flou. Ce n'est pas repris : ce serait `torch` et des centaines de Mo pour
une fonction ponctuelle. L'agrandissement local est un simple rééchantillonnage
LANCZOS, et le journal **le dit** — « agrandissement simple, sans détail
inventé ». Ne pas le dire aurait été laisser croire à mieux.

### Deux défauts trouvés par l'usage, dans la minute

**Le focus ne suivait pas l'ouverture d'un panneau.** Fernando : « je vois que
le focus n'est pas déplacé quand j'active le bouton Galerie d'images ». Le
panneau s'ouvrait, mais le focus restait sur le bouton : au lecteur d'écran,
rien ne se passe.

La cause tenait à l'histoire du code. Le déplacement du focus n'existait que
dans le gestionnaire de **raccourci** `Alt+Maj`. Chaque bouton avait son propre
gestionnaire de **clic**, écrit à un moment différent, et aucun ne s'en
occupait. Onze panneaux, onze occasions d'oublier — et onze corrections auraient
laissé le douzième derrière.

Corrigé **par délégation**, en une fois, à partir de la table qui recense déjà
les panneaux. La délégation n'est pas un raffinement : trois de ces boutons
(mémoire, promptothèque, recherches) **n'existent pas dans la page**, ils sont
créés par `renderSidebar()` qui les recrée à chaque rendu — un gestionnaire posé
sur l'élément disparaîtrait avec lui.

Ajouté au passage : à la fermeture, **le focus revient d'où il venait**. La
fermeture passe par plusieurs chemins (croix, clic à côté, Échap, bouton
bascule) ; plutôt que de les suivre un par un, on observe la classe du panneau.

**« Manipuler une image » n'était pas là où on le cherche.** Fernando l'a
cherché dans la **galerie**, et c'est logique : c'est l'endroit où l'on pense
aux images qu'on possède déjà. L'outil vit dans le studio, mais rien n'oblige à
ce que ce soit la seule porte. La galerie en ouvre une, qui ferme la galerie,
ouvre le studio, **déplie le volet** et y met le focus — arriver sur un titre
fermé ressemble à une impasse au lecteur d'écran.

Tests : 91 scénarios. Les contrôles de ce lot ont été éprouvés sur sources

simulées (consigne déguisée en description, absence de description tue, Pillow
dans la boucle, recadrage envoyé au modèle pour rien) : les quatre défauts sont
bien vus.

---

## Deux défauts trouvés en cherchant un bouton (28/08/2026, soir)

### La question

Fernando : « il me semblait que fut un temps il y avait aussi un moteur pour
générer une image, une vidéo, et je ne vois plus rien de tout ça : c'est
normal ? »

Rien n'avait été retiré. Le studio vit dans le menu « + » depuis le 30/07 —
mais le nom accessible de ce bouton était **« Ajouter »**. L'infobulle disait
bien « Ajouter un fichier, créer une image ou une vidéo », seulement un
`aria-label` **écrase** le `title` pour le lecteur d'écran. La porte existait,
son écriteau était faux.

Corrigé, avec une contrainte que Fernando avait lui-même posée le 30/07 : ces
boutons sont traversés en permanence, un nom de cinquante caractères y coûte du
temps à chaque passage. La première correction faisait 48 et 71 caractères — le
test de longueur l'a refusée sur-le-champ. Retenu : **« Fichier, image ou
vidéo »** (23) et **« Studio image, vidéo, retouche »** (29).

Ajouté au passage : `aria-expanded` sur le bouton de menu, **accroché à la
classe** plutôt qu'aux cinq endroits qui ouvrent ou ferment le menu. Un
attribut posé une fois pour toutes mentirait dès la première ouverture.

### Le défaut trouvé en chemin, et il est plus grave

En vérifiant pourquoi l'entrée du studio pouvait être masquée, ceci est apparu
dans `main.py` :

```python
class ApiKeysSetting(BaseModel):
    anthropic:  Optional[str] = None
    deepseek:   Optional[str] = None
    ...          # neuf champs, écrits à la main
```

Le catalogue `core/services.py` en compte **quinze**. Six services n'étaient
pas déclarés : `groq`, `cerebras`, `exa`, `cohere`, `voyage`, `jina`.

Or **Pydantic ignore en silence un champ qu'il ne connaît pas**. L'interface
envoyait la clé Groq, le serveur répondait `{"status": "ok"}`, et rien n'était
enregistré. **Groq et Cerebras étaient inutilisables depuis leur câblage du
30/07** — déclarés partout, présents dans les listes, sans aucun moyen de leur
donner une clé.

La même énumération figée servait à la **lecture** : l'interface croyait ces
clés absentes et grisait leurs options même lorsqu'elles existaient.

Et un troisième décalage du même genre : la page demandait
`data-needs-key="stability"` quand le catalogue dit `stability_ai`. L'option
restait grisée pour toujours, sans que rien ne le signale.

Les deux routes se **déduisent** désormais du catalogue, et le modèle accepte
tout champ dont l'identifiant y figure. La réponse à l'enregistrement dit
maintenant **quelles clés ont été retenues** — c'est précisément ce qui
manquait pour s'apercevoir que six services partaient à la poubelle.

### Le motif, pour la troisième fois

Adresses de fournisseurs dupliquées trois fois (30/07), six listes de
fournisseurs oubliées dans `app.js` (10/08), et maintenant les clés. À chaque
fois : une énumération recopiée à la main, qui vieillit sans rien dire. À
chaque fois la même correction — **une table, et tout le reste s'en déduit** —
et un test qui ancre la dérivation plutôt que le contenu.

Le nouveau test vérifie aussi que **chaque `data-needs-key` de la page désigne
un service réel**. Un nom qui ne correspond à rien ne lève pas : il grise, en
silence, pour toujours.

Tests : 93 scénarios.

---

## Le studio fusionne dans le panneau Images (28/08/2026, troisième passe)

### Trois fois au même endroit

Fernando a cherché la création d'image et de vidéo **dans la galerie** trois
fois de suite :

1. « Si c'est dans le menu galerie, je ne vois rien de tout ça » ;
2. « Il me semblait qu'il y avait aussi un moteur pour générer une image, une
   vidéo, et je ne vois plus rien » ;
3. « Si je dois trouver d'autres choses que le studio dans le popup galerie
   d'images, ça n'a pas marché ».

Après la deuxième, j'ai ajouté un **bouton de renvoi** de la galerie vers le
studio. C'était traiter le symptôme. Une passerelle ne répare pas un mauvais
rangement : elle l'avoue.

### Ce que le va-et-vient a coûté

Le studio a vécu dans la barre du haut, puis derrière le menu « + » (30/07,
pour réduire une redondance que Fernando avait lui-même signalée), et enfin
dans le panneau Images (28/08). Deux déménagements, une passerelle inutile, et
trois signalements — parce qu'à chaque fois j'ai raisonné en termes
d'**organisation du code** (« le + est là où se prennent les décisions de
création ») plutôt qu'en termes de **réflexe de l'utilisateur** (« quand je
pense image, je vais aux images »).

### L'état d'arrivée

| Porte | Raccourci | Ce qu'elle tient |
|---|---|---|
| **Images** | Alt+Maj+G | galerie, créer une image, créer une vidéo, manipuler une image |
| **+** (zone de saisie) | — | joindre un fichier, créer une image DANS la conversation, document Vibe |

Le partage n'est plus « consulter / produire » mais « ce qui s'ajoute au
message que j'écris » contre « ce qui produit et conserve des fichiers ».
`plus-imagegen` reste dans le « + » : il préfixe la zone de saisie, c'est un
geste de conversation, pas de production.

Quatre entrées deviennent deux. `Alt+Maj+I` est rendu.

### Ce que la fusion a failli casser

Le risque propre à ce genre de déménagement : le code survit, la page change,
**et rien ne lève**. Les fonctions cessent simplement de répondre.

C'est exactement ce qui s'est produit : en retirant le câblage de la
passerelle, j'ai emporté **tout le corps de `_retoucheCabler()`**. Le panneau
de retouche n'écoutait plus rien. Le contrôle du contrat interface/serveur l'a
signalé dans la minute — « `/api/retouche/options` ajoutée sans être branchée ».

Deux tests ont par ailleurs vu leur **règle vieillir**, et ont été réécrits
plutôt que contournés :
- celui qui exigeait `id="plus-studio"` dans le menu ;
- celui qui exigeait le mot « vidéo » dans le nom du bouton « + » — un nom qui
  promet plus qu'il ne donne fait perdre autant de temps qu'un nom trop pauvre.

Le nouveau test vérifie qu'**aucun élément cherché par le script n'a disparu
de la page**, et que le corps de `_retoucheCabler` n'est pas vide.

Tests : 94 scénarios.

---

## La mise à jour annonçait le contraire de la vérité (31/08/2026)

### Comment on y arrive

Demande de Fernando : « je pense que dans les .md à la racine on a consigné des
choses à faire : analyse et dis-moi ce qu'on pourrait faire ». Le BACKLOG date
du 9 juin. Plutôt que de le lire, il a été **vérifié dans le code** — et
l'écart est instructif :

| Ligne du backlog | Réalité du code, 31/08 |
|---|---|
| Refonte mémoire A→G | 5 sur 7 déjà faites |
| Fenêtre active + carnet progressif | fait le jour même de l'écriture |
| Export, phase 2 | devenue possible : `write_file` était mort jusqu'au 28/08 |
| Migration Git pour Éric et Nando | **périmée** : `/api/update` fait déjà le travail, sans Git |

Un backlog non vérifié coûte plus qu'il ne rapporte : il fait travailler sur
des choses faites, et il cache celles qui ne le sont pas.

### Ce que la vérification a mis au jour

`POST /api/update` télécharge l'archive GitHub et remplace les fichiers. Puis
l'interface annonçait : « ✅ Mise à jour appliquée ! Rechargement dans 3
secondes… ».

**C'est faux sur les trois quarts du logiciel.** Python a déjà chargé
`main.py`, `core/` et `modules/` en mémoire : les remplacer sur le disque ne
change rien au processus en cours. Seuls les fichiers statiques — page, script,
feuille de style — sont relus par le navigateur.

Le résultat est une **interface neuve sur un serveur ancien**. C'est exactement
la panne « contrat interface / serveur » que nos tests traquent depuis juillet,
sauf qu'elle se produit chez l'utilisateur, à l'exécution. Le lot de cette
semaine l'illustre : la nouvelle page appelle `/api/live/ws` et
`/api/retouche/appliquer`, que l'ancien serveur ne connaît pas.

Et si la version exige une bibliothèque de plus — **Pillow** pour la retouche,
**websockets** pour le mode Live, tous deux ajoutés cette semaine — personne ne
l'installe. Les modules le disent honnêtement à l'usage, mais après coup.

### Ce que la route rend maintenant

- **ce qui a changé** : seuls les fichiers réellement différents sont recopiés
  (`filecmp`), sans quoi le compte vaudrait toujours la totalité du dépôt ;
- **s'il faut relancer** : la route distingue le code serveur (`main.py`,
  `core/`, `modules/`) des fichiers statiques ;
- **les bibliothèques apparues**, nommées, avec la commande à taper ;
- et elle ne touche plus aux fichiers qui appartiennent à la machine
  (`nimm.log`, `.env`), qu'elle écrasait avec ceux du dépôt.

L'archive est décompressée **avant** toute copie : une archive abîmée ne doit
pas laisser l'installation à moitié remplacée. C'était déjà le cas ; le test
l'ancre désormais.

### Côté interface

Plus de rechargement automatique — il donnait à croire que tout était actif. Le
message du serveur est affiché tel quel, **annoncé au lecteur d'écran**
(l'instruction « relance NIMM » n'existe pas si on ne l'entend pas), la liste
des fichiers est **copiable**, et le bouton devient « Relance NIMM pour
appliquer » quand c'est le cas.

### Une bévue à consigner

La première tentative d'écrire cette entrée a été **avalée en silence** : mon
garde-fou testait la présence de la phrase-titre, or je venais de l'écrire dans
le renvoi du backlog. Le script a conclu « déjà présent » et n'a rien fait —
sans rien afficher, puisque le message de confirmation était à l'intérieur du
`if`. Deux leçons : garder sur une chaîne qui n'existe QUE dans le bloc ajouté,
et faire dire au script ce qu'il a fait **dans les deux cas**, pas seulement
quand il agit.

Tests : 95 scénarios.
---

## coaNIMM s'arrêtait au milieu du travail (01/09/2026)

### Un "<" et puis plus rien

« Il me dit qu'il travaille, mais il ne fait rien. » Laurent demandait à
coaNIMM de convertir un `.svg` en `.png` : le modèle confirmait le chemin du
fichier, annonçait qu'il lançait la conversion — et s'arrêtait net, parfois
sur un simple `<` orphelin affiché à l'écran. Il fallait relancer la
conversation pour voir la suite.

Deux symptômes, une seule cause : **coaNIMM n'avait le droit d'utiliser qu'un
seul outil par tour de parole.** Le code avait été construit ainsi
volontairement — un commentaire de l'époque explique qu'autoriser un second
appel d'outil provoquait un flux muet ou coupé en pleine phrase. Le
contournement retenu à l'époque avait été de **retirer les outils** dès le
deuxième tour plutôt que de réparer l'enchaînement.

Or une tâche réelle demande souvent plus d'une étape : lister le fichier,
*puis* l'exécuter. Privé de la possibilité de rappeler un outil normalement,
DeepSeek tentait parfois d'en écrire un en texte brut (un format spécial du
modèle, commençant par `<`) — et c'est ce texte mal formé, coupé entre deux
paquets du flux, qui laissait fuiter le `<` avant de couper l'affichage.

### La boucle agentique bornée

coaNIMM redonne maintenant la main au modèle **avec les outils toujours
actifs** après chaque exécution, façon agent Cline : il peut enchaîner
plusieurs appels à la suite, jusqu'à `_MAX_TOOL_LOOPS = 4`. Si le plafond est
atteint sans que le modèle ne conclue de lui-même — erreur de raisonnement,
boucle sur lui-même — coaNIMM s'arrête proprement et le dit : « ⚠️ Je m'arrête
là après plusieurs étapes à la suite — dis-moi si je dois continuer. » plutôt
que de rester silencieux.

Le repli sans outils (dernier recours si même la boucle ne produit rien) est
conservé tel quel.

### Un oubli débusqué en cours de route

Le chemin utilisé par la boucle (`call_llm_stream_with_tools`) accumulait déjà
la chaîne de pensée des modèles de raisonnement (`reasoning_content`) mais ne
l'avait **jamais émise** — contrairement à l'ancien chemin de phase 2. Sans
correction, la boucle agentique aurait fait disparaître l'affichage du
raisonnement replié dans les échanges concernés. Ajout du `yield` manquant
côté `engine.py`, et de la branche correspondante côté `hub.py`.

### Une fusion au passage

Le merge avec la branche de Nando a touché deux fichiers sans lien avec la
boucle : `index.html` et un test de cache-busting. Le test de Nando remplace
une valeur figée (`v=20260829-2`, qui cassait à chaque changement de numéro)
par une vérification de **forme** — un numéro daté doit exister sur `app.js`
ET sur `styles.css`. En résolvant le conflit, `styles.css` référençait encore
l'ancien numéro pendant que `app.js` avait le nouveau : navigateur servant un
CSS périmé depuis son cache pendant que le JS était à jour. Harmonisé sur
`20260831-maj`.

Tests : 96 scénarios.
---
