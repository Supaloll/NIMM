_DĂŠcrit l'ĂŠtat rĂŠel du code. RĂŠfĂŠrence unique â mettre Ă  jour quand une logique change._

---

## Structure du dossier

```
nimm/
âââ main.py                  â Point d'entrĂŠe FastAPI, toutes les routes HTTP
âââ core/
â   âââ hub.py               â Orchestrateur central (tout passe ici)
â   âââ engine.py            â Moteur LLM multi-providers + gĂŠnĂŠration image
â   âââ database.py          â AccĂ¨s SQLite (nimm.db)
âââ modules/
â   âââ memory.py            â Recall, extraction, normalisation, dĂŠduplication
â   âââ intent_gate.py       â Filtre prĂŠ-LLM pour intentions simples
â   âââ websearch.py         â Recherche web (Brave Search API)
â   âââ tts.py               â SynthĂ¨se vocale (Kokoro / Piper / Edge)
â   âââ stt.py               â Reconnaissance vocale Whisper (lazy via _get_model())
â   âââ pdf_reader.py        â Extraction texte PDF
â   âââ quiz.py              â Rattrapage tags %%QUIZ%% non balisĂŠs (wrap_bare_quiz)
â   âââ bibliotheque.py      â GĂŠnĂŠration fiches archivage + recall thĂŠmatique
â   âââ coanimm.py           â Agent exĂŠcution code Python (run_script, run_generated, generate_plan, explore_directory)
â   âââ enrichissement.py    â Ingestion documents web/fichiers â zone de rĂŠfĂŠrence RAG
â   âââ export_nimm.py       â Export messages marquĂŠs (txt, docx, pdf, rtf, odt, epub, mp3)
â   âââ masks/               â PersonnalitĂŠs LLM (fichiers JSON)
âââ frontend/
â   âââ index.html
â   âââ app.js
â   âââ styles.css
âââ data/
â   âââ nimm.db              â Base SQLite principale
â   âââ mood_prompts.json    â Prompts par catĂŠgorie ĂŠmotionnelle
âââ tests/
â   âââ test_memory.py       â Test qualitĂŠ mĂŠmoire (7 groupes, 28 assertions)
â   âââ clear_memory.py      â Vide la mĂŠmoire sauf predicat=prenom
â   âââ auto_fill.py         â Remplissage automatique par scĂŠnarios
â   âââ seed_memory.py       â Peuple la mĂŠmoire avec donnĂŠes de test
â   âââ audit_routes.py      â Audit complet des routes API
âââ ARCHITECTURE.md          â Ce fichier
```

---

## Principe fondamental : Hub-and-Spoke

**RĂ¨gle absolue** : tout passe par `core/hub.py`.
Aucun module ne parle directement Ă  un autre. Le hub orchestre, les modules exĂŠcutent.

---

## Pipeline d'un message

### Deux points d'entrĂŠe â comportement identique

| Fonction | Route | ParticularitĂŠ |
|---|---|---|
| `process_message_stream()` | `/api/chat/stream` (frontend) | Yield SSE token par token |
| `process_message()` | `/api/chat` (API externe, tests) | Retourne dict complet |

### Ordre d'exĂŠcution

1. **Garde provider** â vĂŠrifie provider + clĂŠ API configurĂŠs
2. **IntentGate** â rĂŠponse immĂŠdiate sans LLM si intention simple (heure, salutation, commande directe)
3. **Push mĂŠmoire** â `build_memory_context_permanent_only()` retourne `''` â aucune injection de triplets bruts. Le prĂŠnom est injectĂŠ via `user_name`. L'index thĂŠmatique remplace l'injection de masse (voir Â§ System prompt).
4. **System prompt** â assemblĂŠ par `build_system_prompt()` (voir Â§ System prompt)
5. **Historique** â 80 derniers messages du fil
6. **Phase 1 LLM** â `call_llm_stream_with_tools()` : stream normal ou dĂŠtection tool_call
7. **ExĂŠcution outil** â si tool_call : `_execute_tool()` â rĂŠsultat injectĂŠ
8. **Phase 2 LLM** â si tool call : `call_llm_stream()` avec contexte enrichi
9. **Extraction tags** â `extract_all_tags()` parse les balises techniques :
   `%%DOMINANT%%` `%%ANECDOTE%%` `%%BILAN%%` `%%SITUATION%%` `%%RAPPEL%%` `%%IMAGE%%`
   `%%MEM%%` retirĂŠ du LLM de chat â traitĂŠ exclusivement par le worker async.
10. **Traitement rappels** â si `rappel_actions` : `perimer_rappels_depasses()` puis actions CREER / MODIFIER / CLOS / EMIS
11. **Sauvegarde** â messages DB (`processed_for_memory = 0` par dĂŠfaut), anecdotes, dominant
12. **ArriĂ¨re-plan** â `classify_topic()` + `maybe_generate_carnet_note()` + `memory_worker()` (cycle 30s)

**Worker mĂŠmoire** : `memory_worker()` tourne en boucle async toutes les 30s.
Principe ĂŠcrivain unique â seul ce worker ĂŠcrit dans la table `memory` pendant une conversation.
Pour chaque fil avec `processed_for_memory = 0` : charge 80 messages de contexte â `extract_memories_from_window()` â marque traitĂŠs.
`memorize_thread()` (archivage manuel) fait de mĂŞme et marque aussi les messages traitĂŠs.

---

## MĂŠmoire (memory.py)

### PrĂŠdicats canoniques

`PREDICATS_CANONIQUES` est la liste exhaustive des prĂŠdicats acceptĂŠs en base.
Tout prĂŠdicat produit par le LLM est normalisĂŠ vers cette liste avant stockage.

CatĂŠgories complĂ¨tes :
- **IDENTITĂ** : `prenom` `nom` `age` `date_naissance` `taille_cm` `poids_kg` `sexe` `handicap` `groupe_sanguin` `nationalite`
- **FAMILLE** : `conjoint` `enfant` `parent` `frere` `soeur` `grand_parent` `petit_enfant` `beau_parent` `statut_relation`
- **TRAVAIL & ĂTUDES** : `metier` `employeur` `anciennete` `horaire_travail` `diplome` `ecole` `competence` `permis` `recherche_emploi` `etudes`
- **SANTĂ** : `probleme_sante` `traitement` `allergie` `medecin` `operation` `suivi_medical` `addiction` `regime_alimentaire`
- **GOĂTS** : `aime` `n_aime_pas` `plat_prefere` `aversion_alimentaire` `boisson_preferee` `musique_preferee` `artiste_prefere` `film_prefere` `serie_preferee` `livre_prefere` `auteur_prefere`
- **LOISIRS** : `sport` `lecture` `jeu_video` `cuisine` `bricolage` `jardinage` `musique_instrument` `danse` `ecriture` `photographie` `art` `loisir` `anciennete_pratique`
- **POSSESSIONS** : `vehicule` `domicile` `logement` `equipement` `animal`
- **RELATIONS** : `ami` `collegue` `voisin` `relation_sociale` `mentor`
- **VALEURS** : `valeur` `croyance` `religion` `politique` `engagement`
- **OPINIONS** : `stance` `opinion`
- **PROJETS** : `objectif` `reve` `intention` `projet` `envie` `apprentissage`
- **ĂVĂNEMENTS** : `evenement_vie` `deuil` `accident` `demenagement` `anecdote`
- **FINANCES** : `budget` `salaire` `patrimoine` `credit` `epargne`
- **TECHNOLOGIE** : `ordinateur` `tel_portable` `logiciel_prefere` `reseau_social` `habitude_num`
- **LANGUE & CULTURE** : `langue_maternelle` `langue_parlee` `culture_origine`
- **CARACTĂRE** : `trait` `force` `faiblesse` `peur` `qualite`
- **HABITUDES** : `habitude` `rituel` `sommeil` `fumeur`
- **BIEN-ĂTRE** : `moral` `stress` `bien_etre` `humeur`
- **ORIENTATION** : `orientation_sexuelle`

### PrĂŠdicats protĂŠgĂŠs (`PREDICATS_PROTEGES`)

Liste fermĂŠe de prĂŠdicats Ă  haute stabilitĂŠ : `prenom` `nom` `age` `conjoint` `metier` `domicile` `pere` `mere` `frere` `soeur` `valeur_principale` etc.
Ces prĂŠdicats ne sont **jamais ĂŠcrasĂŠs** par le LLM, sauf en prĂŠsence d'un signal de correction explicite (`SIGNAUX_CORRECTION`) dans le message utilisateur.

Signaux de correction reconnus : "en fait", "maintenant je suis", "je ne suis plus", "j'ai changĂŠ", "nouveau travail", "on s'est sĂŠparĂŠ", "on s'est mariĂŠ"âŚ

Comportement :
- Signal absent + prĂŠdicat protĂŠgĂŠ â renforcement du poids uniquement (objet conservĂŠ)
- Signal prĂŠsent â mise Ă  jour de l'objet mĂŞme sur prĂŠdicat protĂŠgĂŠ

### Normalisation des prĂŠdicats (`normalize_predicat`)

Pipeline en 10 ĂŠtapes â le premier match retourne :

1. Minuscules + strip + suppression accents + normalisation apostrophes/tirets
2. NĂŠgations (`_NEGATIONS`) â prĂŠdicat canonique (`n_aime_pas`, `aversion_alimentaire`, `allergie`âŚ)
3. Fautes d'orthographe connues (`_FAUTES`) â forme correcte
4. Table de normalisation principale (`PREDICAT_NORMALISATION`) â canonique
5. DĂŠjĂ  canonique (`PREDICATS_CANONIQUES`) â retour immĂŠdiat
6. Correspondance par groupe de synonymes (`PREDICAT_SYNONYMES`)
7. InfĂŠrence par mots-clĂŠs dans le prĂŠdicat
8. DĂŠjĂ  canonique aprĂ¨s nettoyage accents (filet de sĂŠcuritĂŠ)
9. **RĂŠducteur verbal automatique** â suffixes conjuguĂŠs 1er groupe (-e, -es, -ent, -ons, -ait, -ais, -iez, -aientâŚ) â reconstruit l'infinitif â lookup dans `PREDICAT_NORMALISATION`
   - Ex : `etudie` â strip `-e` â `etudi` + `er` = `etudier` â `etudes`
10. PrĂŠdicat libre (inconnu) â retour brut nettoyĂŠ + log

**Table d'infinitifs** (rĂŠfĂŠrence pour le rĂŠducteur verbal) :
`etudierâetudes` Âˇ `apprendreâetudes` Âˇ `travaillerâmetier` Âˇ `bosserâmetier`
`habiterâdomicile` Âˇ `demeurerâdomicile` Âˇ `vivreâdomicile`
`pratiquerâsport` Âˇ `jouerâloisir` Âˇ `aimerâaime` Âˇ `detesterân_aime_pas` Âˇ `conduireâmetier`

### DĂŠduplication (`_find_duplicate`)

Avant tout stockage, `_find_duplicate(record, existing)` cherche un doublon dans `existing` :
- Correspondance par groupe de synonymes sur le prĂŠdicat
- Pour les prĂŠdicats **multi-valeurs** (`PREDICATS_MULTI_VALEUR` : `enfant` `fils` `fille` `frere` `soeur` `frere_ou_soeur` `ami` `collegue`âŚ) :
  la dĂŠduplication exige sujet + prĂŠdicat + **objet** identiques â deux enfants diffĂŠrents = deux entrĂŠes
- Pour les prĂŠdicats mono-valeur : sujet + prĂŠdicat suffisent

### Poids, renforcement et dĂŠcroissance

Chaque souvenir a un champ `poids` (dĂŠfaut 1.0, max 5.0).

**Renforcement** : Ă  chaque rĂŠapparition d'un fait dĂŠjĂ  connu, `poids += RENFORCEMENT[categorie]` (0.2 Ă  0.5 selon catĂŠgorie). Cooldown de 24h entre deux renforcements du mĂŞme fait.

**DĂŠcroissance** (`DECAY_RATES`) : appliquĂŠe selon la catĂŠgorie (% par 24h). `famille`, `sante`, `croyances` â taux 0 (permanent). `projets` â 1.5%/j. `quotidien` â 1%/j.

**Promotion automatique** : si `poids >= 2.5` ou `repetitions >= 3`, le souvenir passe en `type_temporal = permanent`.

**CatĂŠgories permanent dĂ¨s crĂŠation** : `famille` Âˇ `sante` Âˇ `croyances`.

### Verrous mĂŠmoire (`lock_memory`)

Les souvenirs ĂŠditĂŠs manuellement depuis l'UI (bouton đ§ ) sont verrouillĂŠs.
Un souvenir verrouillĂŠ n'est **jamais ĂŠcrasĂŠ** par l'extraction LLM â ni renforcĂŠ, ni corrigĂŠ.
StockĂŠ dans les settings DB (`memory_locks` = liste JSON de clĂŠs).

### Alias de prĂŠnoms (`ALIASES`)

RĂŠsolution automatique avant dĂŠduplication : `MeĂŻ` / `Mei` / `MeĂŻssane` â `MaĂŻssane`.

### Valeurs creuses

Objets ignorĂŠs Ă  la sauvegarde : `''` `oui` `non` `inconnu` `aucun` `n/a` `?` `vide` `unknown` `non prĂŠcisĂŠ`âŚ

### Relations symĂŠtriques (`_save_symmetric`)

AprĂ¨s chaque enregistrement, si le prĂŠdicat est dans `PREDICATS_INVERSES`,
la relation inverse est crĂŠĂŠe automatiquement :
- `Laurent / enfant = MaĂŻssane` â crĂŠe `MaĂŻssane / parent = Laurent`
- `Laurent / conjoint = Nadia` â crĂŠe `Nadia / conjoint = Laurent`

Le prĂŠdicat inverse est normalisĂŠ via `normalize_predicat()` avant stockage â
ĂŠvite les formes non canoniques (`frere_ou_soeur`, `subordonnĂŠ`, etc.).

### Moteur d'infĂŠrence (`run_inference_engine`)

Tourne en thread daemon au dĂŠmarrage. Non-bloquant, idempotent.
Seuil minimum : `poids >= 1.5` pour qu'un fait soit utilisĂŠ comme source d'infĂŠrence.

4 rĂ¨gles appliquĂŠes dans l'ordre :
1. **SymĂŠtrie** â rĂŠpare les inverses manquants sur donnĂŠes antĂŠrieures
2. **TransitivitĂŠ** â `parent(A,B)` + `parent(B,C)` â `grand_parent(A,C)` + `petit_enfant(C,A)`
3. **Fratrie** â A et B partagent le mĂŞme parent â `frere_ou_soeur(A,B)` (bidirectionnel)
4. **Ăge dynamique** â `date_naissance(A, YYYYâŚ)` â calcule et met Ă  jour `age(A, N ans)`

Garde : ne pas infĂŠrer de fratrie si l'un est dĂŠjĂ  parent de l'autre.
Pseudo-entitĂŠs exclues : `filles` `papa` `maman` `enfants` `innes_maissane_maya`âŚ

### Embeddings

ModĂ¨le `paraphrase-multilingual-MiniLM-L12-v2`, chargement lazy (`_get_model()`),
activĂŠ/dĂŠsactivĂŠ dans les paramĂ¨tres (DB). Vecteurs normalisĂŠs (cosinus = produit scalaire).

CalculĂŠ sur `sujet + prĂŠdicat + valeur + objet` au stockage. Chaque vecteur est
sĂŠrialisĂŠ **avec le nom du modĂ¨le** (`_serialize_embedding` / `_parse_embedding`) :
un changement de modĂ¨le est dĂŠtectĂŠ, les vecteurs d'un autre modĂ¨le sont ignorĂŠs au
scoring et recalculĂŠs (l'ancien format ÂŤ liste nue Âť reste lu, rĂŠtro-compat).

`recall()` combine **deux sources de candidats** : FTS5 (mots-clĂŠs) et similaritĂŠ
vectorielle (`_vector_candidate_keys` â parcours force brute de tous les vecteurs via
`get_all_embeddings()`), plus les permanents. La recherche par sens retrouve donc aussi
les souvenirs sans mot commun avec la requĂŞte. Seuil d'entrĂŠe : `VECTOR_CANDIDATE_MIN`.

Rattrapage : `backfill_embeddings()` recalcule par lots (50/cycle) les vecteurs
manquants ou issus d'un autre modĂ¨le ; dĂŠclenchĂŠ par `memory_worker()` Ă  chaque cycle,
dans un thread.

### Chemins d'extraction

**Worker async (principal)** :
`memory_worker()` dans `hub.py` â boucle toutes les 30s. Lit tous les messages `processed_for_memory = 0`,
tous fils confondus. Appelle `extract_memories_from_window()` â LLM dĂŠdiĂŠ extrait les faits â `save_inline_memory()`.
Marque les messages traitĂŠs. Ăcrivain unique â zĂŠro doublon possible.
En fin de cycle : `backfill_embeddings()` â rattrapage des vecteurs manquants ou pĂŠrimĂŠs, dans un thread.

**Path A2 â archivage manuel** :
`POST /api/threads/{id}/memorize` â `memorize_thread()` â `extract_memories_from_window()`.
Marque ĂŠgalement les messages traitĂŠs aprĂ¨s extraction.

**Path A (inline) â supprimĂŠ** :
Le LLM de chat n'ĂŠmet plus `%%MEM%%`. RetirĂŠ du Format de sortie et du system prompt.
Causait une dilution de l'attention conversationnelle.

**Path B â supprimĂŠ** :
`extract_memories_background` â retirĂŠ prĂŠcĂŠdemment (doublons).

---

## System prompt (`build_system_prompt`)

### Composition (ordre d'injection)

1. **Masque ou Potards** â personnalitĂŠ et style de rĂŠponse
2. **Lexique contractuel** â rĂ¨gles techniques pures (SONDE, AGENDA, SIGNALâŚ)
3. **Date / heure**
4. **Signal mood** (si actif)
5. **Situation courante** (`%%SITUATION%%` â lieu ou activitĂŠ dĂŠtectĂŠs)
6. **Rappels actifs** (si ĂŠchĂŠances Ă  signaler)
7. **PrĂŠsence temporelle** (`_build_presence_note` â si retour aprĂ¨s longue absence)
8. **Bilans de session** (`đ Points acquis cette session` â faits/ĂŠvĂŠnements confirmĂŠs dans le fil courant)
9. **Carnet de bord** (si `count_messages > CARNET_WINDOW=80`)
10. **Index thĂŠmatique mĂŠmoire** â deux sections compactes gĂŠnĂŠrĂŠes en direct depuis `get_memory_index_by_theme()` dans `database.py` :
    - **Tiers** (famille, amisâŚ) : noms propres groupĂŠs par thĂ¨me â le LLM appelle `search_memory(prĂŠnom)`.
    - **Profil** : liste des prĂŠdicats disponibles pour l'utilisateur (mĂŠtier, aime, sportâŚ) â le LLM appelle `search_memory(prĂŠdicat)`.
    Plus de valeurs brutes dans l'index. Instruction LLM : `search_memory(prĂŠnom ou prĂŠdicat)`.
11. **BibliothĂ¨que** â conversations archivĂŠes pertinentes (si rĂŠsultat de recherche)
12. **Outils disponibles** â rappel des 4 outils tool calling
13. **Format de sortie** â structure des tags techniques

### Lexique contractuel â concepts opĂŠrationnels

InjectĂŠ en tĂŞte du system prompt, avant tout contexte dynamique.

Concepts actifs dans le code :
`SONDE` Âˇ `AGENDA` Âˇ `SIGNAL` Âˇ `SITUATION` Âˇ `IMAGE`

Section `ââ RĂGLES ââ` : `VIGNETTE` Âˇ `FIN` Âˇ `FIL` Âˇ `COULISSES` Âˇ `OUTIL` Âˇ `WEB` Âˇ `HONNĂTETĂ`

Concepts retirĂŠs (prĂŠsents dans versions antĂŠrieures, absents du code) :
`ANCRE` Âˇ `C[1-5]` Âˇ `GRAIN` Âˇ `SEUIL` Âˇ `PARSE` Âˇ `CLARIF` Âˇ `VOILE` Âˇ `ĂCHO` Âˇ `DELTA`

### Format de sortie â ordre des tags

```
1. %%RAPPEL%%        â action agenda
2. %%ANECDOTE%%      â moment fort, drĂ´le ou touchant
3. %%BILAN%%         â rĂŠsultat/ĂŠvĂŠnement confirmĂŠ dans le fil (â¤ 10 mots, 1 par fait clos)
4. %%DOMINANT%%      â ĂŠtat ĂŠmotionnel dominant (obligatoire, 1 par tour)
5. %%QUIZ%%          â carte QCM ou Vrai/Faux (JSON structurĂŠ, mode quiz uniquement)
6. %%QUIZ_BILAN%%    â bilan de fin de quiz (score + rĂŠcap, mode quiz uniquement)
7. %%IMAGE%%         â gĂŠnĂŠration image (dĂŠclenchĂŠ par prĂŠfixe đźď¸ ou langage naturel)
8. %%SITUATION%%     â lieu ou activitĂŠ dĂŠtectĂŠs dans le message utilisateur
```

Tags gĂŠrĂŠs hors LLM de chat :
- `%%MEM%%` â retirĂŠ du LLM de chat, gĂŠrĂŠ exclusivement par le worker async
- `%%QUIZ%%` / `%%QUIZ_BILAN%%` â rattrapage automatique si JSON non balisĂŠ : `_wrap_bare_quiz()` (Python, hub.py) + `_wrapBareQuiz()` (JS, app.js)

### Format du TAG %%MEM%% (worker uniquement)

Le prompt du worker (`extract_memories_from_window`) utilise ce format en interne :

```
%%MEM:type|sujet|prĂŠdicat|objet|contexte|memoire_type|profondeur|temporal%%
```

| Champ | Valeurs |
|---|---|
| type | `trait` Âˇ `relation` Âˇ `activite` |
| sujet | prĂŠnom rĂŠel â jamais "utilisateur", "je", "moi" |
| prĂŠdicat | NOM canonique â jamais verbe conjuguĂŠ ni infinitif |
| objet | valeur courte (3-5 mots max) |
| contexte | fil thĂŠmatique libre |
| memoire_type | `identite` Âˇ `activite` |
| profondeur | 1 (identitĂŠ stable) âŚ 5 (anecdotique) |
| temporal | `permanent` Âˇ `persistant` Âˇ `episodique` |

### Modes de personnalitĂŠ

**Masque** (`personality_mode='mask'`) : fichier JSON dans `modules/masks/`.
**Potards** (`personality_mode='potards'`) : prompt gĂŠnĂŠrĂŠ depuis curseurs.
- Curseurs normaux (0/1/2) : `serieux` `formel` `expressif` `direct` `metaphorique` `bienveillant` `collaboratif` `emojis`
- Curseurs WTF (0=off, 1=modĂŠrĂŠ, 2=Ă  fond) : `wtf_cafe` `wtf_jargon` `wtf_ado` `wtf_theatral` `wtf_metaphores` `wtf_tension`

---

## BibliothĂ¨que (bibliotheque.py)

GĂŠnĂŠration et recall des fiches d'archivage. Une fiche = l'os d'une conversation.

### GĂŠnĂŠration (`generate_bibliotheque_entry`)

Trois appels LLM sĂŠquentiels :

1. **Appel C** (temperature=0) â extraction mĂŠcanique des faits confirmĂŠs (ancre de rĂŠalitĂŠ). Produit un tableau JSON de faits â¤ 10 mots.
2. **Appel OS** (temperature=0.3, max_tokens=1500) â gĂŠnĂ¨re l'os complet en JSON :
   - `titre` Âˇ `tags` Âˇ `categories` (1â3 ĂŠmojis de la liste prĂŠdĂŠfinie)
   - `fil_conducteur` â la question ou tension centrale
   - `noeuds` â 4 Ă  8 idĂŠes dĂŠveloppĂŠes (1â3 phrases chacune)
   - `positions` â ce qui a ĂŠtĂŠ conclu ou assumĂŠ non tranchĂŠ
   - `questions_ouvertes` â ce qui tourne encore
   - `formulations_cles` â phrases qui ont fait tilt
   - `climat` â mode de la conversation
   - `ramifications` â pistes frĂ´lĂŠes non traitĂŠes

Stockage : `os_riche` = JSON complet des 7 composantes Âˇ `categories` = ĂŠmojis Âˇ `resume_texte` = fallback assemblĂŠ depuis `os_riche` pour rĂŠtrocompat.

### Recall (`recall_bibliotheque`)

AppelĂŠ par `search_bibliotheque` (tool calling). Recherche FTS5 â injecte dans le system prompt :
- Fiches riches (`os_riche`) : fil conducteur + nĹuds + positions + questions ouvertes + ramifications
- Fiches anciennes (fallback) : conclusions + mots-clĂŠs depuis `os_json`

### CatĂŠgories ĂŠmoji prĂŠdĂŠfinies

đŠˇ Ămotions Âˇ đ RĂŠflexions Âˇ âď¸ Projets & Travail Âˇ đĄ Quotidien & Famille Âˇ đ Monde & SociĂŠtĂŠ Âˇ đŽ Loisirs & Passion Âˇ đ CrĂŠation & Imaginaire Âˇ đŹ Souvenirs & MĂŠmoire Âˇ đ§Ź SantĂŠ & Corps Âˇ đŻď¸ SpiritualitĂŠ & Sens Âˇ âď¸ Voyages & Ailleurs Âˇ đ§° MĂŠtier & Savoir-faire Âˇ đŞ Rapport Ă  soi Âˇ đŽ Futur & Possibles Âˇ đłď¸ Zones d'Ombre Âˇ đ¤ Lien Social Âˇ đ§Š SynchronicitĂŠs

---

## Tool calling

Le LLM reĂ§oit plusieurs outils et dĂŠcide lui-mĂŞme s'il en a besoin :

```
search_memory(query)        â recall() dans memory.py
search_bibliotheque(query)  â recall_bibliotheque() dans hub.py
search_anecdotes(query)     â recall_anecdotes() dans memory.py
search_web(query)           â websearch.search() via Brave Search
search_carnet(query)        â notes du carnet de bord du fil (hub.py)
find_skill(query)           â fiches skills CoaNIMM rĂŠutilisables (hub.py)
```

**RĂ¨gles de dĂŠclenchement** (dans le system prompt) :
- Question personnelle sur l'utilisateur ou son entourage â `search_memory`
- RĂŠfĂŠrence Ă  une discussion passĂŠe â `search_bibliotheque`
- RĂŠfĂŠrence Ă  un moment vĂŠcu, souvenir partagĂŠ â `search_anecdotes`
- Information datĂŠe par nature (actualitĂŠ, mĂŠtĂŠo, prix) â `search_web`
- TĂ˘che d'automatisation ressemblant Ă  un process dĂŠjĂ  validĂŠ â `find_skill` (avant de gĂŠnĂŠrer)
- Question gĂŠnĂŠrale, factuelle, technique â aucun outil

`_execute_tool()` est **async**. `search_web` ne doit jamais ĂŞtre appelĂŠ pour analyser un document fourni dans le message.

**Cache des recherches (`search_with_cache`, table `web_reference`)** : `search_web`
passe par `search_with_cache()`, qui rĂŠutilise un rĂŠsultat dĂŠjĂ  obtenu pour une
requĂŞte sĂŠmantiquement proche et **non pĂŠrimĂŠe** (sans rappeler Brave), et mĂŠmorise
les nouveaux rĂŠsultats. Chaque entrĂŠe porte une expiration selon la pĂŠrissabilitĂŠ
de l'information, **estimĂŠe par le LLM** (`classify_perissabilite_jours` dans hub,
Ă  partir de la requĂŞte et d'un extrait du contenu trouvĂŠ : ĂŠphĂŠmĂ¨re 1 j / normale
30 j / durable 365 j / permanente = jamais), avec repli sur une heuristique par
mots-clĂŠs si le LLM est indisponible. Classement uniquement en cas de dĂŠfaut de
cache ; stockage en arriĂ¨re-plan (zĂŠro latence). Zone sĂŠparĂŠe de la mĂŠmoire
personnelle. Le `memory_worker` purge les entrĂŠes expirĂŠes Ă  chaque cycle.

---

## Web search

Deux mĂŠcanismes indĂŠpendants :

| MĂŠcanisme | DĂŠclencheur | Comportement |
|---|---|---|
| Bouton web (frontend) | `web_search=True` dans la requĂŞte | Recherche avant le LLM, rĂŠsultat injectĂŠ |
| Tool calling (`search_web`) | LLM dĂŠcide | Appel Brave Search via `_execute_tool()` |

`_needs_web_search()` et `_WEB_PATTERNS` prĂŠsents dans le code mais **dĂŠsactivĂŠs**.

---

## Moteur LLM (engine.py)

### Providers chat

`anthropic` Âˇ `deepseek` Âˇ `gemini` Âˇ `openai` Âˇ `openrouter` Âˇ `ollama` Âˇ `mistral` Âˇ `stability-ai` Âˇ `local`

### GĂŠnĂŠration image

| Provider | ModĂ¨le | Notes |
|---|---|---|
| Gemini | `gemini-2.5-flash-image` | DĂŠfaut. 1 500 images/jour gratuites. Retourne base64. |
| OpenAI | `gpt-image-1` | NĂŠcessite vĂŠrification d'org. |

Retouche d'image : `edit_gemini_image(prompt, image_b64)` â route `POST /api/image/edit`.

---

## Base de donnĂŠes â tables (database.py)

Fichier : `data/nimm.db`. AccĂ¨s via `core/database.py` uniquement (Hub-and-Spoke).

| Table | RĂ´le |
|---|---|
| `memory` | Triplets mĂŠmoire (sujet / prĂŠdicat / objet). ClĂŠ primaire : `key`. |
| `web_reference` | Cache des recherches web scrapĂŠes (sĂŠparĂŠ de la mĂŠmoire personnelle). Colonnes : `query` `query_norm` `content` `embedding` `captured_at` `expiration` `source`. RĂŠutilisĂŠ par `search_with_cache()` ; purgĂŠ Ă  expiration par le worker. |
| `messages` | Historique des conversations (thread_id, role, content, timestamp). |
| `threads` | Fils de conversation (id, title, mask, created_at). |
| `rappels` | Agenda â ĂŠchĂŠances et rappels (description, date_echeance, type, statut, rappels_emis). |
| `anecdotes` | Moments forts extraits par le LLM (titre, contenu, contexte, tags). FTS5 activĂŠ. |
| `bibliotheque` | Conversations archivĂŠes. Colonnes : `titre` `sujet_principal` `tags` `categories` `resume_texte` `os_json` `os_riche` `status` `thread_id_source` `date_conversation` `mask_id`. FTS5 activĂŠ sur `titre + tags + sujet_principal + os_json + os_riche`. `mask_id` = masque actif au moment de l'archivage â restaurĂŠ Ă  la reprise âś. |
| `bibliotheque_fts` | Table virtuelle FTS5 liĂŠe Ă  `bibliotheque` (sync par triggers). |
| `carnet` | Notes de bord LLM (thread_id, note_number, content, created_at). |
| `interets` | Centres d'intĂŠrĂŞt dĂŠtectĂŠs (topic, score, timestamp). |
| `cost_wallets` | Suivi des coĂťts API par provider (provider, tokens_in, tokens_out, cost). |
| `settings` | ParamĂ¨tres clĂŠ/valeur globaux (provider, model, embeddings_enabled, locksâŚ). |

**FTS5** (recherche plein texte) : activĂŠ sur `anecdotes` et `bibliotheque`.
Les triggers SQLite maintiennent la cohĂŠrence entre tables principales et tables FTS5.

**Fonctions principales exposĂŠes** :
- `save_memory(record)` Âˇ `get_all_memory()` Âˇ `delete_memory(key)` Âˇ `update_memory_value(key, valeur)`
- `get_permanent_memories()` Âˇ `get_memory_index_by_theme()` Âˇ `purge_episodic_memories()`
- `search_anecdotes_db(query, limit)` Âˇ `get_all_anecdotes()` Âˇ `delete_anecdote(id)`
- `save_bibliotheque_entry(...)` Âˇ `get_bibliotheque_entries()` Âˇ `search_bibliotheque_fts(query)`
- `create_rappel(...)` Âˇ `get_rappels_actifs()` Âˇ `update_rappel_date(...)` Âˇ `close_rappel(id)` Âˇ `perimer_rappels_depasses()`
- `add_carnet_note(...)` Âˇ `get_carnet_notes(thread_id)` Âˇ `count_carnet_notes(thread_id)` Âˇ `delete_carnet_note(thread_id, note_number)`
- `get_setting(key, default)` Âˇ `set_setting(key, value)`
- `search_messages_text(query, limit)` â recherche LIKE sur `messages.content` (recherche exacte)
- `delete_last_assistant(thread_id)` â supprime le dernier message `role='assistant'` d'un fil
- `delete_last_pair(thread_id)` â supprime la derniĂ¨re paire user+assistant (pour rĂŠ-ĂŠdition)

---

## Carnet de bord

Remplace l'ancien OS (rĂŠsumĂŠ glissant). Notes courtes gĂŠnĂŠrĂŠes par le LLM.

**Calendrier** :
- Note #0 : aprĂ¨s le 1er ĂŠchange (2 messages)
- Note #n : tous les 7 ĂŠchanges (14 messages)

**Injection** : uniquement si `count_messages > CARNET_WINDOW (80)` â transparent pour le LLM.

**Constantes** : `CARNET_WINDOW = 80` Âˇ `CARNET_INTERVAL = 7`

**Table DB** : `carnet` (id, thread_id, note_number, content, created_at)

---

## IntentGate (intent_gate.py)

Court-circuite le LLM pour les intentions simples dĂŠtectĂŠes par pattern matching :
heure, salutation, commande directe, question rĂŠflexe.
RĂŠponse immĂŠdiate â pipeline arrĂŞtĂŠ, aucun appel LLM.

---

## Frontend

### ThĂ¨me
Toggle clair/sombre (localStorage). Variables CSS globales â pas de classes conditionnelles.

### Onglets (tabs)
SystĂ¨me de fils organisĂŠs en onglets dans la sidebar.
- Desktop : badge sur chaque onglet parent, enfants visibles en sous-liste
- Mobile : enfants affichĂŠs en bullets indentĂŠs cliquables, suppression directe
- Titre auto-gĂŠnĂŠrĂŠ par LLM au premier ĂŠchange (1 emoji + 2-3 mots)
- Bouton âś Reprendre sur chaque fiche bibliothĂ¨que â crĂŠe un nouveau fil

### Sidebar
Boutons permanents : Nouveau fil Âˇ BibliothĂ¨que Âˇ MĂŠmoire Âˇ ParamĂ¨tres Âˇ Mise Ă  jour.
Indicateur masque actif affichĂŠ sous le nom de l'assistant.
BanniĂ¨re provider visible (provider + modĂ¨le en cours).

### GĂŠnĂŠration image
PrĂŠfixe emoji `đźď¸` ou langage naturel â gĂŠnĂŠration via `/api/image/generate`.
Bouton âď¸ Modifier sur chaque image gĂŠnĂŠrĂŠe â appel `/api/image/edit`.

### TTS
Lecteur flottant persistent : lecture auto ou manuelle des rĂŠponses assistant.
Voix disponibles chargĂŠes dynamiquement depuis le backend (liste variable selon moteur actif).
Moteurs : Kokoro Âˇ Piper Âˇ Edge TTS â sĂŠlection dans les paramĂ¨tres.

### STT (push-to-talk)
Bouton micro dans la zone de saisie â transcription Whisper via `/api/stt`.
RĂŠsultat injectĂŠ directement dans le champ texte.

### Citation
SĂŠlection de texte dans une rĂŠponse â bouton contextuel "Citer" â
insĂ¨re le passage sĂŠlectionnĂŠ en rĂŠfĂŠrence dans le champ de saisie.

### Menu contextuel
Clic droit (ou appui long mobile) sur un message â actions : copier Âˇ citer Âˇ supprimer.

### Menus d'action par message

**Menu "Ma saisie"** (sur chaque message utilisateur) â aria-label `Ma saisie` :
- đ Copier â copie le texte dans le presse-papier
- âď¸ Modifier â appelle `editLastUserMessage()` : supprime la derniĂ¨re paire en DB (`DELETE /api/chat/{id}/last_pair`), remet le texte dans le champ de saisie

**Menu "La rĂŠponse"** (sur chaque message assistant) â aria-label `La rĂŠponse` :
- đ Copier â copie le texte
- â Onglet â envoie le contenu dans un nouveau fil (tab)
- đ RĂŠgĂŠnĂŠrer â supprime le dernier message assistant en DB (`DELETE /api/chat/{id}/last_assistant`) puis re-stream le dernier message utilisateur
- â­ Marquer pour export â ajoute/retire le message de `_exportItems[]` ; contour visuel sur la bulle

Tous les menus sont accessibles au clavier grĂ˘ce Ă  `_menuKeyboard()` : focus auto sur le premier item Ă  l'ouverture, navigation FlĂ¨che Haut/Bas, Ăchap pour fermer.

### Export messages
- Bouton flottant `#export-float-btn` (coin bas-droit) apparaĂŽt dĂ¨s qu'un message est marquĂŠ â indique le nombre d'ĂŠlĂŠments
- Modal `#export-modal` : sĂŠlecteur de format + bouton "Tout dĂŠmarquer"
- Appel `POST /api/export` â `modules/export_nimm.py` â tĂŠlĂŠchargement direct
- Formats : **TXT** (texte brut), **DOCX** (python-docx), **PDF** (fpdf2), **RTF** (manuel), **ODT** (zip XML), **EPUB** (zip XHTML), **MP3** (edge-tts, voix fr-FR-DeniseNeural)

### Recherche messages (modale Recherches)
Deux niveaux complĂŠmentaires dans la mĂŞme modale :
- **Par sens** â embeddings (sentence-transformers), retrouve l'idĂŠe sans les mots exacts
- **Texte exact** â SQLite `LIKE` via `search_messages_text()`, retrouve le mot tel quel

### Upload
Bouton trombone â upload de fichier (PDFâŚ) via `/api/upload`.
Contenu extrait et injectĂŠ dans le contexte du message suivant.

### Modales
| Modale | DĂŠclencheur | Contenu |
|---|---|---|
| Onboarding | Premier lancement | Saisie prĂŠnom + choix provider |
| ParamĂ¨tres | Bouton sidebar | Provider, modĂ¨le, voix, longueur rĂŠponses, embeddings, prĂŠsence temporelle |
| MĂŠmoire | Bouton sidebar | Liste des souvenirs, ĂŠdition manuelle đ§ , suppression, verrou |
| BibliothĂ¨que | Bouton sidebar | Fiches archivĂŠes, recherche, reprise |
| Agenda | Commande naturelle | Rappels actifs, modification, clĂ´ture |
| CoĂťts | Bouton sidebar | Suivi tokens/coĂťt par provider (cost_wallets) |
| Suppression | IcĂ´ne poubelle | Confirmation avant suppression d'un fil |
| Font picker | ParamĂ¨tres | Choix de la police d'affichage |
| Export | Bouton flottant | SĂŠlection format + dĂŠclenchement export |
| Recherches | Bouton sidebar | Recherche sĂŠmantique + texte exact + bibliothĂ¨que + mĂŠmoire |

### ClĂŠs API
`_saveApiKeys()` â sauvegarde automatique sur `keydown` + `blur`.
8 champs : `anthropic` Âˇ `deepseek` Âˇ `gemini` Âˇ `openai` Âˇ `openrouter` Âˇ `mistral` Âˇ `stability-ai` Âˇ `brave`

### Ămojis expressifs
Le LLM peut ĂŠmettre des ĂŠmojis de rĂŠaction contextuelle affichĂŠs dans l'interface.

### Loader
Animation "bretzel" pendant la gĂŠnĂŠration de rĂŠponse.

### Mobile
- Trash icon toujours visible (pas de hover)
- Auto-focus conditionnel sur modales (supprime l'ouverture clavier Samsung)
- Scroll horizontal sur blocs code
- AccĂ¨s via Tailscale en HTTPS â `tailscale serve --bg http://localhost:8080` expose le port en HTTPS automatiquement
- URL mobile : `https://<machine>.tail<id>.ts.net` (domaine propre Ă  chaque installation)
- PWA installĂŠe sur Android (mode standalone, sans barre d'adresse)
- Sur PC : accĂ¨s local via `http://localhost:8080` (inchangĂŠ)
- GĂŠolocalisation : `_getLocation()` dans app.js â GPS + Nominatim (gratuit, sans clĂŠ API) â position injectĂŠe dans le system prompt Ă  chaque message

---

## CoaNIMM (coanimm.py)

Agent d'exĂŠcution Python autonome â dĂŠclenchĂŠ depuis le panneau CoaNIMM (sidebar). CoaNIMM peut exĂŠcuter n'importe quelle requĂŞte en langage naturel, avec ou sans validation intermĂŠdiaire, en bouclant avec l'utilisateur via l'interface si nĂŠcessaire.

### Deux modes d'exĂŠcution

| Mode | Fonction | DĂŠclencheur |
|---|---|---|
| Script PromptothĂ¨que | `run_script(script_id, âŚ)` | SĂŠlection dans la liste des scripts enregistrĂŠs |
| GĂŠnĂŠration libre | `run_generated(consigne, âŚ)` | Consigne en langage naturel |

### Flow PlanâExploreâGenerateâExecute (run_generated)

1. **Planification** (`generate_plan()`) â LLM gĂŠnĂ¨re un plan en texte brut (sans markdown, lisible braille) et indique si une exploration disque est nĂŠcessaire (`EXPLORER: oui/non`)
2. **Exploration** optionnelle (`explore_directory()`, permission `EXPLORE_ACTION='explorer_disque'`) â liste arborescente du dossier workspace, injectĂŠe dans le contexte de gĂŠnĂŠration
3. **GĂŠnĂŠration** (`run_generated()`, permission `GENERATED_ACTION='exec_generated_code'`) â LLM produit un script Python ; retry automatique si `SyntaxError`
4. **ExĂŠcution en streaming** â le script tourne en sous-processus ; stdout transmis en temps rĂŠel via SSE (`/api/coanimm/run_code_stream`) avec `PYTHONUNBUFFERED=1` et flag `-u`

### SystĂ¨me de permissions (deux niveaux)

- `EXPLORE_ACTION = 'explorer_disque'` â lecture seule du disque
- `GENERATED_ACTION = 'exec_generated_code'` â ĂŠcriture / exĂŠcution

Si l'accord n'est pas dĂŠjĂ  en base, le backend retourne `{'status': 'permission_required', 'action': âŚ}` ; le frontend affiche le panneau de permission avec 3 niveaux : une fois / pour ce fil / toujours.

### ExĂŠcution streaming (SSE)

Route `GET /api/coanimm/run_code_stream?script_path=âŚ` â `StreamingResponse` (text/event-stream). Chaque ligne de stdout du script est ĂŠmise sous la forme :

```
data: {"type": "line", "text": "..."}
```

Fin de stream : `data: {"type": "done", "returncode": N, "files_list": [...]}`. Si `interaction_needed` est prĂŠsent dans le payload `done`, le frontend affiche le panneau d'interaction.

Variables d'environnement du sous-processus : `PYTHONIOENCODING=utf-8`, `PYTHONUNBUFFERED=1`.
Timeout : 300 secondes (augmentĂŠ de 30 s pour les tĂ˘ches longues et les appels LLM internes).

### Protocole `__NIMM_DEMANDE__` (boucle agentique)

Quand un script gĂŠnĂŠrĂŠ a besoin de la validation de l'utilisateur avant une action destructive ou ambiguĂŤ, il ne bloque pas (`input()` interdit) â il ĂŠmet un marqueur :

```python
print('__NIMM_DEMANDE__: Confirmez-vous la suppression des 42 dossiers dĂŠtectĂŠs ?')
import sys; sys.exit(0)
```

Le backend dĂŠtecte ce marqueur dans le stream et inclut `interaction_needed: {question, output_so_far}` dans le payload `done`. Le frontend :

1. Affiche le panneau `#coanimm-interact-panel` avec la question
2. L'utilisateur tape sa rĂŠponse et clique Envoyer (ou EntrĂŠe)
3. Le frontend appelle `POST /api/coanimm/continue` avec `{consigne_originale, output_precedent, question_posee, reponse_utilisateur, thread_id}`
4. Le backend reconstruit le contexte complet et rĂŠgĂŠnĂ¨re un script en tenant compte de la rĂŠponse
5. Le nouveau script est prĂŠsentĂŠ et exĂŠcutĂŠ â la boucle peut recommencer

Cette boucle est entiĂ¨rement dans l'interface ; aucun `input()` n'est jamais utilisĂŠ.

### Sandbox

RĂŠpertoire dĂŠdiĂŠ par fil : `data/coanimm_workspace/{nom_fil}_{thread_id[:8]}/`.
Scripts exĂŠcutĂŠs avec `PYTHONIOENCODING=utf-8` et `PYTHONUNBUFFERED=1` (emojis + stdout non buffĂŠrisĂŠ).
Timeout : 300 secondes.

### PLANNING_SYSTEM_PROMPT

Texte brut uniquement (interdictions explicites de tout markdown, balises, astĂŠrisques, backticks). Format de rĂŠponse : ligne `EXPLORER: oui|non` + plan en 3â8 phrases numĂŠrotĂŠes.

### GENERATE_SYSTEM_PROMPT (rĂ¨gles clĂŠs)

- Jamais de `input()` ni `sys.stdin` â utiliser le protocole `__NIMM_DEMANDE__` si validation nĂŠcessaire
- Toujours `print()` les actions au fil de l'exĂŠcution (stdout en temps rĂŠel)
- Pour les tĂ˘ches sans risque : exĂŠcuter directement sans demander confirmation
- Encodage : `utf-8` explicite sur toutes les opĂŠrations fichier

### Skills CoaNIMM (mĂŠthodes rĂŠutilisables)

Capturer une mĂŠthode qui a fonctionnĂŠ pour pouvoir la redemander, sans auto-apprentissage autonome : rien ne s'ĂŠcrit sans l'accord explicite de l'utilisateur. Cycle : demande â gĂŠnĂŠration/exĂŠcution â validation â rĂŠdaction d'une fiche skill â une consigne ressemblante retrouve le skill et s'en sert. SchĂŠma de cadrage complet : `CoaNIMM_schema_skills.md` (gardĂŠ local).

**Stockage** â extension de la PromptothĂ¨que, `type='skill'` (aucune table nouvelle, aucune migration). `core/database.py` : `save_prompt(id, label, text, type='skill', meta={...})` / `list_prompts('skill')`. `meta` porte `description` (ÂŤ quand l'utiliser Âť), `mots_cles`, `script_ref`, `consigne_origine`, `valide_par_laurent`, `version`.

**RĂŠdaction â Ătape A** (`modules/coanimm.py`) â `SKILL_WRITER_SYSTEM_PROMPT` (4e consigne, mĂŞme famille que PLANNING/EXPLORE/GENERATE) ; `write_skill(consigne_origine, script, âŚ)` async, calquĂŠ sur `maybe_generate_carnet_note` (appel LLM de fond, lecture des fiches existantes pour ĂŠviter les doublons, option SKIP). RĂ¨gle cardinale : enseigner la LOGIQUE de la mĂŠthode â ÂŤ seuillage binaire Âť pour la dĂŠcoupe/vectorisation, ÂŤ quantification de palette Âť pour la broderie : deux skills distincts, jamais une fonction ÂŤ retouche Âť gĂŠnĂŠrique â et non l'exemple prĂŠcis. Sortie texte brut accessible plage braille. `_parse_skill_fiche()` dĂŠcoupe la sortie en DESCRIPTION / MOTS-CLES / corps.

**Rappel â Ătape B** (`core/hub.py`, calquĂŠ sur `search_carnet`) â signal lĂŠger dans `build_system_prompt` (prĂŠsent uniquement si au moins un skill existe), outil `find_skill(query)` dĂŠclarĂŠ dans `NIMM_TOOLS`, handler dans `_execute_tool` : recouvrement de mots-clĂŠs (filtrĂŠ par `_MOTS_VIDES`) sur label + description + mots-clĂŠs, renvoie les 1 Ă  3 fiches les plus proches en texte brut. Comparaison volontairement simple au dĂŠpart ; embeddings ĂŠventuellement plus tard.

**Auto-audit â Ătape C** (`modules/coanimm.py`) â avant l'exĂŠcution dans `run_generated`, si une fiche correspond Ă  la consigne (`_find_relevant_skill`, mĂŞme appariement que find_skill), le script gĂŠnĂŠrĂŠ est relu Ă  la lumiĂ¨re de la fiche (`audit_against_skill`, qui rĂŠutilise `generate_code` et donc son filet anti-troncature) et corrigĂŠ s'il s'en ĂŠcarte ; le rĂŠsultat n'est gardĂŠ que s'il reste syntaxiquement valide. Inerte tant qu'aucune fiche n'existe.

**DĂŠclencheur d'ĂŠcriture** (`frontend` + `main.py`) â dans le panneau de validation post-exĂŠcution de CoaNIMM (affichĂŠ aprĂ¨s un run rĂŠussi), une case ÂŤ Aussi mĂŠmoriser la mĂŠthode comme skill rĂŠutilisable Âť. Si cochĂŠe, ÂŤ Enregistrer Âť sauve le script (type='script') ET appelle `POST /api/coanimm/save_skill` â `write_skill()` (fiche rĂŠdigĂŠe par le LLM, nom auto-gĂŠnĂŠrĂŠ). Le rĂŠsultat (crĂŠĂŠe / dĂŠjĂ  couverte / erreur) est annoncĂŠ dans la zone de statut accessible. C'est ce qui rend l'Ătape A active.

**Outils externes â Ătape D** (`modules/coanimm.py` + `main.py`) â deux helpers injectĂŠs dans le prologue confinĂŠ : `nimm_web_search(query)` (rĂŠutilise Brave/Tavily) et `nimm_github_search(query)` (api.github.com : code si `GITHUB_TOKEN`, sinon dĂŠpĂ´ts). Cadrage sĂŠcuritĂŠ retenu : le script passe une REQUĂTE, jamais une URL ; le serveur tape des endpoints FIXES ; le sous-processus reste `allow_network=False` et n'appelle que localhost (exactement comme `nimm_generate_image`) â le confinement rĂŠseau n'est pas touchĂŠ. RĂŠsultats bornĂŠs en taille. Routes : `POST /api/coanimm/web_search`, `POST /api/coanimm/github_search`.

Le volet skills est complet : capture (A) â rappel (B) â auto-audit (C) â dĂŠclencheur d'ĂŠcriture â outils externes (D). **Gestion** : un skill validĂŠ peut ĂŞtre modifiĂŠ (nom, description, mots-clĂŠs, mĂŠthode) â `update_skill()` incrĂŠmente la version et prĂŠserve script et capacitĂŠs â ou supprimĂŠ, depuis le panneau ÂŤ Skills enregistrĂŠs Âť (routes `POST /api/coanimm/skills/{id}/update`, `DELETE /api/coanimm/skills/{id}`). **Rappel sĂŠmantique** : `rank_skills()` mutualise l'appariement pour `find_skill`, `_find_relevant_skill` et `match_skills_for_consignes` â similaritĂŠ par embeddings (`memory._embed`, option ÂŤ recherche par sens Âť) avec **repli automatique** sur le recouvrement de mots-clĂŠs si le modĂ¨le n'est pas installĂŠ.

---

### CapacitĂŠs, validation et workflows CoaNIMM

DeuxiĂ¨me volet greffĂŠ sur CoaNIMM (aprĂ¨s les skills), mĂŞme philosophie : rendre **visible et approuvable** ce que le classifieur de sĂŠcuritĂŠ dĂŠtecte dĂŠjĂ , et **enchaĂŽner** ce que CoaNIMM sait faire Ă  l'unitĂŠ â sans rien retirer au confinement. SchĂŠma de cadrage complet : `CoaNIMM_schema_capacites_workflows.md` (gardĂŠ local).

**CapacitĂŠs dĂŠclarĂŠes â Ătape 1** (`modules/coanimm_safety.py`) â `capabilities_of(code) -> list` projette le classifieur AST existant (`classify_for_execution`) en capacitĂŠs normalisĂŠes : `ecriture`, `recherche` (helpers confinĂŠs `nimm_web_search` / `nimm_github_search`), `image` (`nimm_generate_image`), `reseau` (brut), `programme` (subprocess), `email`, `systeme`, `shell`, `code_dynamique`. `CAPABILITY_LABELS` fournit les libellĂŠs lisibles. La capture d'un skill stocke `meta['capacites']` ; `core/hub.py` `find_skill` les affiche. Lecture seule, ne bloque rien â une seule source de vĂŠritĂŠ, le classifieur.

**Approbation par capacitĂŠ â Ătape 2** (`core/database.py` + `main.py`) â store `coanimm_capabilities` (calquĂŠ sur `coanimm_allowed_paths`) : `list_coanimm_capabilities` / `add` / `remove`. `_COANIMM_GRANTABLE_CAPS = {reseau, programme, email}` â les capacitĂŠs qui, sinon, redemandent confirmation Ă  chaque exĂŠcution. Routes `GET/POST/DELETE /api/coanimm/capabilities`. IntĂŠgration **rĂŠtro-compatible** dans `run_code_stream` : on ne demande confirmation que pour les capacitĂŠs requises *et non encore accordĂŠes* ; `allow_network` suit la capacitĂŠ `reseau`. Sans aucune capacitĂŠ accordĂŠe, le comportement est identique Ă  l'historique. Le confinement d'ĂŠcriture reste le filet runtime, inchangĂŠ. Panneau frontend ÂŤ CapacitĂŠs autorisĂŠes en exĂŠcution Âť (cases par capacitĂŠ, accessible). **Gating propriĂŠtaire** : l'octroi et la rĂŠvocation durables (`POST`/`DELETE`) sont rĂŠservĂŠs au profil **administrateur** (`is_current_user_admin()`, tolĂŠrant pour une install mono-profil) â `403` sinon ; le `GET` expose `is_owner`. L'autorisation **ÂŤ pour cette fois Âť** (`once_caps`, non persistĂŠe) reste ouverte Ă  l'usage courant : une capacitĂŠ requise peut ĂŞtre ouverte pour un seul lancement sans la graver, depuis le panneau de confirmation.

**Workflows â Ătapes 3-4** (`modules/coanimm.py` + `main.py` + `frontend`) â un workflow est une sĂŠquence ordonnĂŠe de skills validĂŠs, rejouable. Stockage : `type='workflow'` dans la PromptothĂ¨que (zĂŠro migration), `meta.etapes` (liste de `{skill_id, label}`) + `meta.capacites` (**union** des capacitĂŠs des ĂŠtapes, calculĂŠe Ă  l'enregistrement). Orchestrateur `run_workflow(workflow_id, thread_id)` : parcourt les ĂŠtapes, exĂŠcute le **script enregistrĂŠ du skill** (`meta['script']`, captĂŠ Ă  la validation), rĂŠutilise l'auto-audit par ĂŠtape, **s'arrĂŞte et rapporte Ă  la premiĂ¨re erreur** (pas d'enchaĂŽnement aveugle). Routes `GET/POST /api/coanimm/workflows`, `POST /{id}/run`, `DELETE /{id}`. UI : composer (sĂŠlecteur de skills validĂŠs, ĂŠtapes rĂŠordonnables monter/descendre avec `aria-label`), enregistrer, rejouer ; rĂŠsultat et statut en zones `aria-live`.

**Workflows et capacitĂŠs prĂŠ-accordĂŠes** â `_execute` accepte un paramĂ¨tre `granted_caps` (dĂŠfaut `None` = comportement historique strict : bloque les actions sensibles, `allow_network=False`). Quand `run_workflow` le fournit, l'exĂŠcution est autorisĂŠe **par capacitĂŠ dĂŠjĂ  accordĂŠe** : `run_workflow` vĂŠrifie en amont que l'union des capacitĂŠs du workflow est couverte (refus clair et anticipĂŠ sinon, avant de lancer la moindre ĂŠtape), puis chaque ĂŠtape s'exĂŠcute avec le rĂŠseau ouvert si `reseau` est accordĂŠ. Les capacitĂŠs **bloquĂŠes** (`systeme`, `shell`, `code_dynamique`) restent toujours refusĂŠes. `run_script` et l'exĂŠcution directe ne passent pas `granted_caps` : aucun changement pour eux.

**Surface autonome + historique** (`modules/coanimm.py` + `frontend` + `main.py`) â `_workspace_dir` retourne un dossier de travail **global unique** (indĂŠpendant du fil) : les fichiers produits arrivent toujours au mĂŞme endroit. Case ÂŤ Partir de la conversation courante Âť (`_coanimmBuildContext`) : pont optionnel, *dĂŠsactivĂŠ* par dĂŠfaut, qui prĂŠfixe la consigne avec les derniers messages du fil. Historique global des tĂ˘ches : store `coanimm_history` + routes `GET/POST/DELETE /api/coanimm/history` + panneau (rĂŠactiver une tĂ˘che pour la relancer).

**AccessibilitĂŠ CoaNIMM** â erreurs de confinement (ĂŠcriture hors dossiers autorisĂŠs) affichĂŠes en `role="alert"` et annoncĂŠes au lecteur d'ĂŠcran, avec un bouton ÂŤ Ajouter ce dossier aux dossiers autorisĂŠs Âť en un clic ; loaders d'attente visuels `aria-hidden` doublĂŠs d'annonces `role="status"` non envahissantes (annonce unique, pas de rĂŠpĂŠtition) ; raccourci Alt+Maj+S contextuel (vise la saisie CoaNIMM si son panneau est ouvert) ; `_linkifyBareUrls` rend cliquables les adresses citĂŠes sans `https://`. **AperĂ§u avant exĂŠcution** (option opt-in, route `/api/coanimm/preview` â analyse statique qui n'exĂŠcute rien) : si activĂŠ, un panneau annonce avant de lancer ce que le script va faire â capacitĂŠs lisibles, dossiers d'ĂŠcriture autorisĂŠs, actions sensibles ou bloquĂŠes â puis demande confirmation (ExĂŠcuter / Annuler), avec `aria-live` et focus.


---

## Export (export_nimm.py)

`async export_messages(items, fmt)` â `(bytes, filename, mime_type)`

| Format | MĂŠcanisme | DĂŠpendance |
|---|---|---|
| TXT | chaĂŽne UTF-8 | aucune |
| RTF | construction manuelle (escape unicode `\uN?`) | aucune |
| ODT | zip XML (ODF 1.3) | aucune |
| EPUB | zip XHTML (EPUB 3) | aucune |
| DOCX | python-docx | `python-docx` (dĂŠjĂ  prĂŠsent) |
| PDF | fpdf2 | `fpdf2` (ajoutĂŠ requirements.txt) |
| MP3 | edge-tts, voix `fr-FR-DeniseNeural` | `edge-tts` (dĂŠjĂ  prĂŠsent) |

Route : `POST /api/export` â retourne le fichier en tĂŠlĂŠchargement direct.

---

## Tests

| Script | Usage |
|---|---|
| `tests/test_memory.py` | 7 groupes, 28 assertions, passe /memorize par groupe. Score rĂŠfĂŠrence : 96% sur base vide. |
| `tests/clear_memory.py` | Vide toute la mĂŠmoire sauf `predicat=prenom`. Demande confirmation. |
| `tests/auto_fill.py` | 7 scĂŠnarios de conversation (littĂŠrature, cuisine, sportâŚ). Observe mĂŠmoire + OS. |
| `tests/seed_memory.py` | Peuple la DB avec donnĂŠes de test (famille Laurent). |
| `tests/audit_routes.py` | Audit complet des routes API (11 groupes, ~40 assertions). |

---

## Changelog (sessions rĂŠcentes)

| Session | Changements clĂŠs |
|---|---|
| 29/06/2026 (Pixtral Large) | **Pixtral Large â choix du modĂ¨le vision Mistral**. [engine.py] `call_vision()` reĂ§oit un paramĂ¨tre optionnel `vision_model` ; la branche Mistral utilise `vision_model or 'pixtral-12b-2409'`. [main.py] rĂŠglage persistĂŠ `pixtral_model` (GET/POST `/api/settings/pixtral-model`) ; les deux routes d'analyse image lisent ce rĂŠglage et le passent Ă  `call_vision`. [index.html] `<div id="pixtral-model-row">` (affichĂŠ seulement si routing vision = Mistral) avec sĂŠlecteur `pixtral-12b-2409` / `pixtral-large-latest`. [app.js] `_updatePixtralModelVisibility()` + chargement/sauvegarde du rĂŠglage ; le listener `routing-vision` rĂŠaffiche/masque la ligne en temps rĂŠel. |
| 29/06/2026 (Batch) | **Mistral Batch â traitement par lots**. [main.py] `MistralBatchSubmitReq` + 4 routes : `POST /api/mistral/batch/submit` (gĂŠnĂ¨re un fichier JSONL, l'uploade via `/v1/files`, crĂŠe le job `/v1/batch/jobs` â renvoie `job_id`), `GET /api/mistral/batch/status/{job_id}` (progression + compteurs succeeded/failed), `GET /api/mistral/batch/results/{job_id}` (tĂŠlĂŠcharge le JSONL de sortie, renvoie liste triĂŠe), `DELETE /api/mistral/batch/{job_id}` (annulation). [index.html] panneau `<details id="mistral-batch-details">` dans les rĂŠglages : sĂŠlecteur de modĂ¨le, tokens max, textarea prompts (une par ligne), boutons Soumettre / Statut / RĂŠsultats / Annuler, zone aria-live statut, rĂŠsultats en `<details>` pliables avec bouton Copier par entrĂŠe. [app.js] IIFE `MISTRAL BATCH` : gestion du job_id courant, polling manuel, affichage accessible (aria-live, aria-label). |
| 29/06/2026 (Pixtral) | **Pixtral â vision Mistral**. [engine.py] `pixtral` ajoutĂŠ Ă  `_MODEL_OWNER` (â `mistral`). `call_vision()` : la branche `provider='mistral'` force dĂŠsormais `model='pixtral-12b-2409'` (les modĂ¨les texte Mistral ne gĂ¨rent pas les images) â image transmise en data-URI `image_url` via `_call_openai_compat`, que Pixtral accepte nativement. [frontend/app.js] `pixtral-12b-2409` (đźď¸đ°) et `pixtral-large-latest` (đźď¸đ°đ°) ajoutĂŠs Ă  `MODELS_BY_PROVIDER.mistral`. Le routing vision Ťđ  Mistral (Pixtral)ť ĂŠtait dĂŠjĂ  prĂŠsent dans `#routing-vision` â fonctionnel sans modification HTML supplĂŠmentaire. `nimm_describe_image` dans CoaNIMM bĂŠnĂŠficie automatiquement de Pixtral si le routing vision est rĂŠglĂŠ sur Mistral. |
| 29/06/2026 (Codestral) | **Codestral â modĂ¨le code + routing CoaNIMM + FIM**. [engine.py] `codestral` ajoutĂŠ Ă  `_MODEL_OWNER` (â provider `mistral`). [frontend] `codestral-latest` (đťđ°) dans `MODELS_BY_PROVIDER.mistral` ; option Ťđľđť Codestral (code)ť dans le sĂŠlecteur routing CoaNIMM (`data-needs-key=mistral`). [hub.py] `get_task_provider_model` : alias `provider='codestral'` â force `('mistral', 'codestral-latest')` â permet de router CoaNIMM vers Codestral sans toucher les autres tĂ˘ches. [modules/coanimm_ops.py] `op_codestral_fim(prefix, suffix, stop, temperature)` â appel `https://codestral.mistral.ai/v1/fim/completions` (Fill-in-the-Middle : complĂ¨te le code entre un prĂŠfixe et un suffixe). [modules/coanimm.py] helper `nimm_codestral_fim(prefix, suffix, stop, temperature)` injectĂŠ dans le prologue. [main.py] `CoanimmCodestralFimReq` + route `POST /api/coanimm/codestral_fim` ; entrĂŠe catalogue Ť ComplĂŠter du code (Codestral FIM) ť (catĂŠgorie Code). [coanimm_safety] `nimm_codestral_fim` â capacitĂŠ Ť recherche ť (appel rĂŠseau). Catalogue = **24 outils**. |
| 29/06/2026 (batch Mistral) | **Mistral â batch complet (tĂ˘ches 8-15)**. [1] **SĂŠlecteur d'agent par conversation** (tĂ˘ches 6-7) : boutons đ¨/đ¤/đ¸ en topbar ; `agent_mode TEXT` dans la table `threads` (valeurs `''`/`'vibe'`/`'coanimm'`) ; routes `GET/POST /api/threads/{id}/agent_mode` ; [hub.py] override du mode CoaNIMM/Vibe selon la valeur stockĂŠe. [2] **Citations Mistral accessibles** : SSE `[CITATIONS]{json}` + `[WEB_SEARCH_LOADING]` interceptĂŠs dans la boucle de stream ; zone aria-live ÂŤ Citations Âť rendue accessible sous la rĂŠponse. [3] **OCR Vibe** : bouton ÂŤ + Âť â upload document â `/api/mistral/ocr` (Mistral OCR `mistral-ocr-latest`) ; texte extrait injectĂŠ comme contexte avant la rĂŠponse Vibe. [4] **Web search routing** : sĂŠlecteur `#routing-websearch` dans les rĂŠglages (Brave/Tavily/Mistral) ; `_search_via_mistral()` dans hub.py via `tools:[{type:'web_search'}]` + ContextVar `_pending_citations`. [5] **Magistral** : `magistral-small-latest` (đ§ đ°) et `magistral-medium-latest` (đ§ đ°đ°) ajoutĂŠs Ă  `MODELS_BY_PROVIDER.mistral` ; `_MODEL_OWNER` ĂŠtendu (`magistral`/`voxtral`/`devstral` â `mistral`). [6] **ModĂŠration Mistral** : `_check_moderation()` en ÂŤ point 0 Âť de `process_message_stream` avant tout LLM ; modĂ¨le `mistral-moderation-latest` ; toggle + 6 sliders par catĂŠgorie (sexual/hate/violence/jailbreak/selfharm/pii) dans les rĂŠglages ; routes `GET/POST /api/settings/moderation`. [7] **GĂŠnĂŠration d'image Mistral** : [engine.py] `_generate_mistral_image()` via agents API ĂŠphĂŠmĂ¨re + outil `image_generation` + tĂŠlĂŠchargement du fichier `/v1/files/{id}/content` ; dispatch `provider='mistral'` dans `generate_image()`. [8] **Voxtral Small â analyse audio** : `AUDIO_EXTS` dans `_processFile()` dĂŠtecte les fichiers audio et route vers `/api/mistral/audio_analyze` (modĂ¨le `voxtral-small-latest`, transcription/analyse) ; fallback si clĂŠ absente. [9] **Code Interpreter Mistral â cloud CoaNIMM** : section `<details id="coanimm-cloud-ci-details">` dans le panneau CoaNIMM ; route `/api/coanimm/mistral_code_interpreter` (agents API + outil `code_interpreter`, fallback chat completions) ; affichage code + sortie + fichiers + bouton ÂŤ injecter dans le fil Âť. |
| 29/06/2026 (expurgate + TTS) | **nimm_expurgate_doc + voix Gemini par dĂŠfaut**. [1] **nimm_expurgate_doc** : [modules/coanimm_ops.py] `op_expurgate_doc(path, consigne, fmt, allow_cloud, thread_id)` â pipeline 3 ĂŠtapes : `enr.extract_any()` â call_llm expurgation (systĂ¨me + consigne libre) â `adoc.build_document()` â workspace timestampĂŠ ; gate cloud aux deux ĂŠtapes. AjoutĂŠ Ă  `ASYNC_OPS_NAMES`, `ASYNC_OPS_TOOLS`, `dispatch_async_op`. [modules/coanimm.py] helper `nimm_expurgate_doc(path, consigne, fmt, allow_cloud)` injectĂŠ dans le prologue. [main.py] `CoanimmExpurgateDocReq` + route `POST /api/coanimm/expurgate_document` ; entrĂŠe catalogue ÂŤ Expurger un document entier Âť (catĂŠgorie Documents). [coanimm_safety] capacitĂŠ ÂŤ recherche Âť (appelle LLM). Catalogue = **23 outils**. [2] **Voix Gemini mono par dĂŠfaut** : [tts.py] `synthesize()` â si `voice` vide et clĂŠ Gemini prĂŠsente, sĂŠlectionne automatiquement `gemini:{gemini_tts_default_voice}` (rĂŠglage persistĂŠ, dĂŠfaut `Kore`). [main.py] routes `GET/POST /api/settings/gemini-tts-default-voice`. [frontend] sĂŠlecteur 8 voix dans `#gemini-tts-rows` (index.html) ; chargĂŠ + sauvegardĂŠ en JS (app.js) ; si Gemini clĂŠ prĂŠsente et aucune voix jamais choisie â sĂŠlection automatique Ă  l'ouverture. |
| 27/06/2026 (Gemini TTS) | **Voix Gemini (TTS) + rĂŠsumĂŠ audio faĂ§on NotebookLM**. [tts.py] `synthesize_gemini` (mono) + `synthesize_gemini_multi` (jusqu'Ă  2 locuteurs) via l'API Gemini `generateContent` (modĂ¨les `gemini-2.5-flash-preview-tts`/`gemini-3.1-flash-tts-preview`, 30 voix, 70+ langues, contrĂ´le du style en langage naturel) ; PCM 24 kHz emballĂŠ en WAV (sans dĂŠpendance) ; prĂŠfixe `gemini:` dans `synthesize()` + 30 voix ajoutĂŠes Ă  `list_voices()` â apparaissent automatiquement dans le sĂŠlecteur (via /api/tts/voices). NotebookLM n'a pas d'API publique â on passe par Gemini TTS, avec la clĂŠ Google dĂŠjĂ  configurĂŠe. [main.py] rĂŠglage `gemini_tts_model` (GET/POST /api/settings/gemini-tts-model). Outil CoaNIMM `nimm_audio_overview(content, voice1, voice2)` â route /api/coanimm/audio_overview : gĂŠnĂ¨re un dialogue podcast Ă  2 voix (call_llm) puis le synthĂŠtise en multi-locuteurs ; cap ÂŤ recherche Âť. Catalogue = 22 outils. |
| 27/06/2026 (tableau + README) | **CoaNIMM â lire un tableau (CSV/TSV) + doc README**. `nimm_read_table(path)` â route `/api/coanimm/read_table` : lit un CSV/TSV (dĂŠlimiteur auto) et renvoie un tableau Markdown lisible (â¤200 lignes). BĂŠnin, catĂŠgorie Documents. Catalogue = **21 outils**. README : nouvelle section ÂŤ Les outils de CoaNIMM Âť (les 21 outils par catĂŠgorie). |
| 26/06/2026 (boĂŽte Ă  outils PDF) | **CoaNIMM â dĂŠcouper un PDF + PDF depuis images**. `nimm_split_pdf(path, pages)` â route `/api/coanimm/split_pdf` : extrait des pages (ex. '1-3,5') via pypdf. `nimm_pdf_from_images(paths, name)` â route `/api/coanimm/pdf_from_images` : assemble des images en un PDF (une par page) via Pillow. BĂŠnins. CatĂŠgorie ÂŤ Documents Âť. Catalogue = 20 outils. |
| 26/06/2026 (anonymiser & PDF) | **CoaNIMM â anonymiser un texte + fusionner des PDF**. `nimm_anonymize(text)` â route `/api/coanimm/anonymize` : masque les donnĂŠes personnelles (noms, e-mails, tĂŠlĂŠphones, adresses, IBANâŚ) via call_llm â confidentialitĂŠ. `nimm_merge_pdf(paths, name)` â route `/api/coanimm/merge_pdf` : combine plusieurs PDF en un (pypdf). [coanimm_safety] anonymize â ÂŤ recherche Âť ; merge_pdf bĂŠnin. CatĂŠgories ÂŤ Texte & langue Âť et ÂŤ Documents Âť. Catalogue = 18 outils. |
| 26/06/2026 (FALC & image) | **CoaNIMM â simplifier (FALC) + redimensionner une image**. `nimm_simplify(text, niveau)` â route `/api/coanimm/simplify` : rĂŠĂŠcriture en **FALC** (Facile Ă Lire et Ă  Comprendre â accessibilitĂŠ cognitive) via call_llm. `nimm_resize_image(path, max_width, fmt)` â route `/api/coanimm/resize_image` : Pillow, redimensionne et/ou convertit (jpg/png/webpâŚ), sauvegarde workspace. [coanimm_safety] simplify â ÂŤ recherche Âť ; resize bĂŠnin. CatĂŠgories ÂŤ Texte & langue Âť et ÂŤ Images Âť. Catalogue = 16 outils. |
| 26/06/2026 (voix & vision) | **CoaNIMM â synthĂ¨se vocale + description d'image**. `nimm_speak(text, voice)` â route `/api/coanimm/speak` (TTS via `modules.tts.synthesize`, audio sauvegardĂŠ dans le workspace) â pour un livre audio. `nimm_describe_image(path, prompt)` â route `/api/coanimm/describe_image` (modĂ¨le de vision via `engine.call_vision`, texte alternatif accessible). Nouvelle catĂŠgorie ÂŤ Audio & voix Âť (transcribe, speak) ; describe_image dans ÂŤ Images Âť. [coanimm_safety] describe_image â ÂŤ recherche Âť (envoi au modĂ¨le de vision). Catalogue = 14 outils. |
| 26/06/2026 (audio) | **CoaNIMM â transcription audio**. Outil `nimm_transcribe(audio_path)` â route gatĂŠe `/api/coanimm/transcribe` qui rĂŠutilise le Whisper local de NIMM (`get_stt().transcribe_file`, run_in_executor). Lecture seule, local (rien n'est envoyĂŠ au cloud). EntrĂŠe catalogue ÂŤ Documents Âť. Catalogue = 12 outils. |
| 26/06/2026 (pptx) | **CoaNIMM â PowerPoint accessible**. `accessible_doc.py` gagne `build_pptx` (diapo de titre, une diapo par section avec TITRE repĂ¨re lecteur d'ĂŠcran, corps en paragraphes, images avec **texte alternatif** `descr`) ; `pptx` ajoutĂŠ au dispatcher â `nimm_make_document(..., fmt='pptx')` fonctionne sans nouvelle route. [requirements.txt] `python-pptx>=0.6.21` ajoutĂŠ (Ă  installer). LibellĂŠ catalogue : ÂŤ CrĂŠer un document accessible (docx/pdf/epub/pptx) Âť. |
| 26/06/2026 (presse-papier) | **CoaNIMM â bouton ÂŤ Copier (mise en forme) Âť**. Sur les fichiers `.html` produits par CoaNIMM (`_coanimmShowFiles` + rendu inline du flux), un bouton copie le contenu HTML enrichi dans le presse-papier (`ClipboardItem` text/html + repli text/plain via `navigator.clipboard.write`) pour le coller directement dans une messagerie web â alternative volontaire Ă  l'envoi SMTP. Accessible (aria-label + annonce). Cache-bust `20260626-v8`. |
| 26/06/2026 (documents) | **CoaNIMM â gĂŠnĂŠrer des documents ACCESSIBLES**. Nouveau module `modules/accessible_doc.py` : `build_document(title, sections, fmt, lang)` produit **docx / pdf / epub / html / txt** avec titre, langue dĂŠclarĂŠe, sous-titres (headings) et images TOUJOURS accompagnĂŠes de leur description (alt). Helper `nimm_make_document(title, sections, fmt='docx', lang='fr')` + route gatĂŠe `/api/coanimm/make_document` (sauvegarde workspace) + entrĂŠe catalogue (catĂŠgorie ÂŤ Documents Âť). Le format `html` (images en data-URI, autonome) sert au copier-coller enrichi vers une messagerie. Catalogue = 11 outils. |
| 26/06/2026 (outils 2) | **CoaNIMM â traduire, expurger (versions enfants), coloriage**. `nimm_translate(text, target_lang)` ; `nimm_expurgate(text, consigne)` = version ADAPTĂE AUX ENFANTS d'un texte (retire/adoucit violence, sexualitĂŠ, horreur, grossiĂ¨retĂŠs en prĂŠservant l'histoire ; peut abrĂŠger) ; `nimm_coloring_page(subject)` = dessin au trait noir et blanc. Helpers + routes gatĂŠes + catalogue (nouvelles catĂŠgories ÂŤ Texte & langue Âť et ÂŤ Images Âť ; `ask_llm`/`image` reclassĂŠs). [coanimm_safety] translate/expurgate â ÂŤ recherche Âť, coloring â ÂŤ image Âť (visibles aperĂ§u+journal). Catalogue = 10 outils. |
| 26/06/2026 (outils) | **CoaNIMM â 4 nouveaux outils + renommages**. Outils ajoutĂŠs (helpers confinĂŠs injectĂŠs dans le prologue + routes serveur gatĂŠes + entrĂŠes catalogue, activables/dĂŠsactivables) : `nimm_search_documents` (interroge la base de connaissances/RAG), `nimm_extract_text` (extrait le texte d'un PDF/Word/ODT/RTF/EPUB/HTML/image+OCR â lecture seule), `nimm_ask_llm` (sous-tĂ˘che IA : rĂŠsumer/classer/traduire), `nimm_read_url` (lit une page web prĂŠcise, anti-SSRF via net_guard). [coanimm_safety] ces helpers (sauf `extract_text`, lecture locale bĂŠnigne) dĂŠclarĂŠs capacitĂŠ ÂŤ recherche Âť â visibles dans l'aperĂ§u et le journal de sĂŠcuritĂŠ. Le panneau ÂŤ Outils de CoaNIMM Âť se peuple automatiquement et **regroupe les outils par catĂŠgorie** (`<details>` repliables avec compteur ÂŤ n/m actifs Âť + rĂŠsumĂŠ global) pour rester compact et navigable au lecteur d'ĂŠcran quel que soit le nombre d'outils (catĂŠgories : Recherche & web, Documents, CrĂŠation & IA). Renommages : modale ÂŤ Enrichissement web Âť â ÂŤ Enrichir la base de connaissances Âť ; bouton đť relibellĂŠ ÂŤ fantĂ´me Âť (au lieu de ÂŤ confidentiel Âť). Cache-bust `20260626-v6`. |
| 26/06/2026 (suite) | **Base de connaissances locale (RAG) â robustesse + injection proactive**. La brique RAG existait dĂŠjĂ  (modale ÂŤ Enrichissement web Âť : ingestion URL/texte/fichier avec OCR â chunks vectorisĂŠs `reference_chunk` â outil `search_documents` ; documents permanents). [enrichissement.py] `search_documents` gagne un **repli mots-clĂŠs** (champ `mode` semantic/keyword) : la base reste interrogeable mĂŞme sans le modĂ¨le d'embeddings. [hub.py] `_match_documents()` + paramĂ¨tre `doc_context` de `build_system_prompt` : **injection proactive** des passages pertinents dans le system prompt (comme `_match_bibliotheque`), seuillĂŠe (cosinus âĽ 0.32 / recouvrement âĽ 2) et gated â le LLM n'a plus Ă  penser Ă  appeler l'outil. **Citation dĂŠterministe** : `_match_documents` renvoie aussi les titres retenus (dĂŠdoublonnĂŠs) ; un bas de rĂŠponse ÂŤ â đ Documents consultĂŠs : âŚ Âť est ajoutĂŠ Ă  la rĂŠponse (diffusĂŠ en direct dans le pipeline stream + sauvegardĂŠ), donc lisible au lecteur d'ĂŠcran et copiable. |
| 26/06/2026 | **CoaNIMM â journal de sĂŠcuritĂŠ + catalogue d'outils**. [database.py] stores `coanimm_security_log` (audit plafonnĂŠ Ă  200 : date, capacitĂŠs, dossiers, fichiers, code retour, statut, rĂŠseau, blocages) et `coanimm_disabled_tools`. [main.py] `run_code_stream` journalise chaque exĂŠcution (et chaque blocage) cĂ´tĂŠ serveur ; routes `GET/DELETE /api/coanimm/security_log` (effacement rĂŠservĂŠ au propriĂŠtaire) et `GET/POST /api/coanimm/tools` ; les routes `web_search`/`github_search`/`generate_image` refusent si l'outil est dĂŠsactivĂŠ. [coanimm.py] `_build_prologue` n'injecte que les outils ACTIVĂS â un outil dĂŠsactivĂŠ est remplacĂŠ par un stub qui lĂ¨ve une erreur claire (pas d'absence silencieuse). [frontend] panneaux ÂŤ Outils de CoaNIMM Âť (cases par outil) et ÂŤ Journal de sĂŠcuritĂŠ Âť (liste accessible, effacement propriĂŠtaire, rechargĂŠ Ă  l'ouverture). Cache-bust `20260625-v5`. |
| 25/06/2026 (suite) | **Skills : gestion + rappel sĂŠmantique ; mode confidentiel**. [coanimm.py + main.py] **ĂŠdition/versionnement des skills** : `update_skill()` (modifie nom/description/mots-clĂŠs/mĂŠthode, incrĂŠmente la version, prĂŠserve script et capacitĂŠs) + routes `POST /api/coanimm/skills/{id}/update` et `DELETE /api/coanimm/skills/{id}` ; panneau frontend ÂŤ Skills enregistrĂŠs Âť (liste, modifier, supprimer, accessible). [coanimm.py + hub.py] **rappel sĂŠmantique** : `rank_skills()` mutualise l'appariement â similaritĂŠ par embeddings (`memory._embed`) avec **repli automatique** mots-clĂŠs si le modĂ¨le est indisponible ; `find_skill`/`_find_relevant_skill`/`match_skills_for_consignes` branchĂŠs dessus. [hub.py] **mode confidentiel** : `_is_ghost_thread()` ; un fil fantĂ´me ne gĂŠnĂ¨re plus de **note de carnet** (mĂŠmoire dĂŠjĂ  coupĂŠe) â aucune trace dĂŠrivĂŠe ; bouton đť relibellĂŠ ÂŤ confidentiel Âť + `aria-pressed`. **Purge de l'espace de travail** : `purge_workspace()` (vide le dossier de travail global, le conserve) + route `DELETE /api/coanimm/workspace` + bouton ÂŤ Vider l'espace de travail Âť (confirmĂŠ, accessible) pour effacer les fichiers produits aprĂ¨s une session confidentielle ; les scripts d'exĂŠcution transitoires ĂŠtaient dĂŠjĂ  supprimĂŠs (`os.unlink`). Cache-bust `20260625-v4`. |
| 25/06/2026 | **CoaNIMM â ÂŤ pour cette fois Âť, workflow depuis l'historique, gating propriĂŠtaire**. [main.py] `run_code_stream` accepte `once_caps` : autorisation d'une capacitĂŠ POUR CE LANCEMENT (non persistĂŠe), fusionnĂŠe aux capacitĂŠs durables (`_effective_caps`). [coanimm.py + main.py] `match_skills_for_consignes()` + route `/api/coanimm/workflow_from_history` : compose un workflow en faisant correspondre des tĂ˘ches de l'historique aux skills validĂŠs les plus proches. [database.py + main.py] **gating propriĂŠtaire** : `is_current_user_admin()` (tolĂŠrant mono-profil) ; `POST`/`DELETE /api/coanimm/capabilities` rĂŠservĂŠs au profil admin (403 sinon) ; `GET` expose `is_owner`. [frontend] panneau de confirmation ÂŤ ExĂŠcuter (pour cette fois) Âť (n'ouvre que la capacitĂŠ requise) + case ÂŤ MĂŠmoriser pour les prochaines fois Âť (propriĂŠtaire seulement) ; cases capacitĂŠs dĂŠsactivĂŠes + note pour non-propriĂŠtaire ; historique avec cases Ă  cocher + ÂŤ Composer un workflow depuis la sĂŠlection Âť. **AperĂ§u avant exĂŠcution** (opt-in, route `/api/coanimm/preview`, analyse statique sans exĂŠcuter) : annonce capacitĂŠs + dossiers d'ĂŠcriture + actions sensibles/bloquĂŠes, puis ExĂŠcuter/Annuler (accessible). Cache-bust `20260625-preview`. |
| 24/06/2026 | **CapacitĂŠs, workflows et surface autonome CoaNIMM**. [coanimm_safety.py] `capabilities_of()` + `CAPABILITY_LABELS` (Ătape 1) : projection du classifieur AST en capacitĂŠs normalisĂŠes (ecriture, recherche, image, reseau, programme, email, systeme, shell, code_dynamique). [database.py + main.py] store `coanimm_capabilities` + routes `/api/coanimm/capabilities` (Ătape 2) : approbation **par capacitĂŠ** ; gate rĂŠtro-compatible dans `run_code_stream` (confirmation seulement si capacitĂŠ requise non accordĂŠe ; `allow_network` suit `reseau`). [coanimm.py + main.py] **workflows** (`type='workflow'`) : `save_workflow` / `list_workflows` / `run_workflow`, sĂŠquences de skills validĂŠs, arrĂŞt-sur-erreur, capacitĂŠs = union ; correctif : le skill stocke son script dans `meta['script']` (run_workflow l'exĂŠcute). `_execute(granted_caps=âŚ)` : les workflows honorent les capacitĂŠs prĂŠ-accordĂŠes (`allow_network` selon `reseau`, refus anticipĂŠ si capacitĂŠ manquante), `run_script` / exĂŠcution directe inchangĂŠs. [coanimm.py] `_workspace_dir` global (surface autonome) + pont contexte optionnel ; store `coanimm_history` + routes + UI historique. [frontend] panneaux CapacitĂŠs / Workflows / Historique accessibles (`aria-live`, `aria-label`, ĂŠtapes rĂŠordonnables) ; erreurs de confinement `role="alert"` + bouton ÂŤ Ajouter ce dossier Âť ; loaders `aria-hidden` + annonces `role="status"` ; Alt+Maj+S contextuel ; `_linkifyBareUrls`. |
| 21/06/2026 (soir) | **Indicateur visuel â recherche web**. [hub.py] `process_message_stream()` envoie desormais `yield "data: [WEB_SEARCH_LOADING]\n\n"` a deux endroits : avant l'appel `search()` (bouton đ force) et avant l'execution de l'outil `search_web` quand le LLM decide seul (tool calling) â corrige le silence visuel pendant une recherche en cours. [styles.css] classe `.web-search-loader` (reutilise l'animation `sttDotPulse` existante, sans le bretzel) pour un indicateur "points qui pulsent" dedie, distinct du loader de reflexion. [app.js] handler SSE intercepte `[WEB_SEARCH_LOADING]` â affiche une bulle `đ Recherche en coursâŚ` ; retrait au moment de la transformation du loader bretzel principal, ET, en filet de securite, des l'arrivee du premier token de texte normal (cas ou le LLM annonce une phrase avant d'appeler l'outil) â evite tout doublon ou bulle persistante. Cache-busting : `20260621-2`. |
| 21/06/2026 | **Skills CoaNIMM + chiffrement des cles API**. [coanimm.py] `SKILL_WRITER_SYSTEM_PROMPT` + `write_skill()` + `_parse_skill_fiche()` (Ătape A) : capture d'une mĂŠthode validĂŠe comme fiche rĂŠutilisable (`type='skill'` dans la PromptothĂ¨que, `meta` description/mots_cles/script_ref), writer de fond calquĂŠ sur le carnet de bord. [hub.py] `find_skill(query)` (Ătape B) : signal lĂŠger dans `build_system_prompt` (si skills existants) + outil dĂŠclarĂŠ dans `NIMM_TOOLS` + handler (recouvrement de mots-clĂŠs filtrĂŠ par `_MOTS_VIDES`, top 1-3 fiches). [coanimm.py] **auto-audit (Ătape C)** : avant exĂŠcution, `run_generated` relit le script Ă  la lumiĂ¨re d'une fiche correspondante (`_find_relevant_skill` + `audit_against_skill`), inerte sans fiche. [database.py] **SĂŠcuritĂŠ point 6/7** : clĂŠs API chiffrĂŠes au repos (Fernet) â `get_api_keys()`/`set_api_keys()` + keyfile `data/.nimm_api_keyfile` (0600) + migration douce d'une valeur en clair ; tous les sites d'accĂ¨s (`hub._load_api_keys`, `main.py`, `websearch.py`) branchĂŠs sur ce point unique. [requirements.txt] `cryptography>=42` ajoutĂŠ, ligne `rapidfuzz` rĂŠparĂŠe. [.gitignore] keyfiles exclus. `modules/main.py` confirmĂŠ code mort (exclu). DĂŠclencheur skill cĂ˘blĂŠ : case Ă  cocher dans le panneau CoaNIMM (frontend) + route `/api/coanimm/save_skill` â `write_skill` (Ătape A active). [coanimm.py + main.py] **Ătape D** : helpers confinĂŠs `nimm_web_search` / `nimm_github_search` (routes serveur vers endpoints fixes Brave/Tavily et api.github.com ; le script passe une requĂŞte, jamais une URL ; `allow_network=False` inchangĂŠ). |
| 14/05/2026 | GĂŠnĂŠration image DALL-E â Gemini. Retouche image. AccessibilitĂŠ NVDA. Installateur refait. |
| 15/05/2026 | Carnet de bord remplace OS. Tool calling `search_web` actif. Web patterns dĂŠsactivĂŠs. |
| 16/05/2026 | Auto-update au lancement (`git pull` dans LANCER_NIMM.bat). HTTPS + PWA mobile via Tailscale. GĂŠolocalisation Nominatim injectĂŠe dans le system prompt. TTS mobile : 5 correctifs sync boutons. Topbar mobile : hamburger visible, titre cachĂŠ. Reprise depuis bibliothĂ¨que (bouton âś Reprendre). Correctifs mĂŠmoire : symĂŠtrie, TAG multi-valeurs. |
| 17/05/2026 | Worker mĂŠmoire async (`memory_worker()` 30s, ĂŠcrivain unique, `%%MEM%%` retirĂŠ du LLM de chat). Ancrage bibliothĂ¨que : appel LLM dĂŠdiĂŠ (prompt_c, temperature=0) avant gĂŠnĂŠration fiche. Upload 30+ extensions. Auto-nommage fils. |
| 18â19/05/2026 | Mode fantĂ´me đť par fil (worker ignore le fil). MĂŠmoire v2 : 5 registres, confiance dĂŠterministe par le hub, curseur Large/Normal/Strict. |
| 20/05/2026 | Multi-utilisateur : DB par profil (`nimm_{id}.db`), `users.json`, middleware `X-User-ID`, onglet đĽ. Extractions hub.py â `quiz.py` + `bibliotheque.py`. SĂŠcuritĂŠ : `.gitignore` DBs + clĂŠs. Onboarding premier lancement. |
| 21â22/05/2026 | Cache-busting. `max_tokens` worker 1500. Anti-chevauchement worker. Refonte injection mĂŠmoire : index thĂŠmatique dynamique, plus d'injection brute de triplets, pull via `search_memory()`. |
| 23/05/2026 | Nettoyage DB (28 entrĂŠes parasites). TTL automatique ĂŠpisodiques. Modale đ§  unifiĂŠe (4 onglets). Scroll mĂŠmoire prĂŠservĂŠ aprĂ¨s suppression. Try/except worker (retry automatique). |
| 24/05/2026 | Scroll libre pendant gĂŠnĂŠration (touchstart). Effet scramble fin de bulle. UI sidebar & menu fil. Nom du masque inline par bulle avec animation. |
| 25/05/2026 | Correctifs worker mĂŠmoire : seuil `< 3` â `< 1`, parser annĂŠe regex. Moteur d'infĂŠrence relancĂŠ Ă  chaque cycle worker. RĂ¨gle 5 : `anciennete_debut` â `anciennete` recalculĂŠe dynamiquement. RĂ¨gles 4 et 5 sur `existing` (pas `source_data`). |
| 25/05/2026 | **Recherche langue DeepSeek â masques** : script `tests/test_morse_formulations.py` crĂŠĂŠ â 8 formulations du systĂ¨me de Crans testĂŠes sur 5 messages sonde (40 appels NIMM). RĂŠsultat : V7 Semantic Tokens produit les rĂŠponses les plus riches et la meilleure gestion Aristote. Apprentissage : DeepSeek rĂŠpond bien aux paraboles hyperboliques et aux semantic tokens ; la question finale est un comportement ancrĂŠ non suppressible par le format. **Masque `morse_deepseek.json`** crĂŠĂŠ (đş Morse, pour Ăric) : expertise aquariophilie/rĂŠtro-gaming/moto/ĂŠsotĂŠrisme, Crans V7, tension aristotĂŠlicienne, humour sec. **Masque `iris_deepseek.json`** crĂŠĂŠ (đ Iris, pour Laurent) : identitĂŠ divinitĂŠ bannie, dilemme existentiel amour/mission, corpus philosophique (StoĂŻcisme, MĂ¨tis, PhronĂ¨sis, Kant, Cynisme antique), Crans V7, gardienne des principes (intĂŠgritĂŠ des moyens, rejet du mensonge, pathos vs logos). |
| 28/05/2026 | **Correctifs carnet & index** : bug asyncio GC corrigĂŠ â `_create_bg_task()` + `_background_tasks` set dans `hub.py` â notes carnet gĂŠnĂŠrĂŠes et conservĂŠes correctement. Route `/api/threads/{id}/carnet` corrigĂŠe (retournait un objet au lieu d'un tableau â UI affichait toujours "vide"). `get_memory_index_by_theme()` refondu : section "Profil" avec prĂŠdicats disponibles pour l'utilisateur (plus de valeurs brutes), noms propres tiers groupĂŠs par thĂ¨me. Instruction LLM mise Ă  jour : `search_memory(prĂŠnom ou prĂŠdicat)`. |
| 25/05/2026 | **NaturalitĂŠ mĂŠmoire & qualitĂŠ rĂŠponses** : rĂ¨gles `MĂMOIRE` et `STYLE` ajoutĂŠes au lexique contractuel (hub.py) â mĂŠmoire utilisĂŠe comme prĂŠmisse sans annonce, interdiction "je me souviens / non ? / c'est Ă§a ?", reprise propre aprĂ¨s appel outil, tiret cadratin â virgule, espacement correct. **Extraction worker renforcĂŠe** (hub.py) : restriction aux proches avec lien nommĂŠ explicite â personnages historiques, cĂŠlĂŠbritĂŠs et tiers sans lien relationnel exclus. **Bloc identitĂŠ injectĂŠ** (hub.py) : mĂŠtier, conjoint, enfants (avec Ă˘ge), domicile injectĂŠs en dur dans chaque system prompt â libellĂŠ "Profil certain" pour lever toute hĂŠsitation. **Index mĂŠmoire corrigĂŠ** (database.py) : sujets filtrĂŠs aux noms propres, objets filtrĂŠs aux attributs de l'utilisateur sans chiffres ni prĂŠdicats structurels, limite 60 chars. **Nettoyage DB** : 110 entrĂŠes corrompues supprimĂŠes via `clear_memory.py` (chemin corrigĂŠ â `nimm_laurent.db`) ; 36 entrĂŠes propres rĂŠinjectĂŠes via `seed_famille.py` (famille Laurent complĂ¨te). **TTS** : tiret cadratin remplacĂŠ par virgule dans `_clean_text()` â pause naturelle sur les trois moteurs. **Masque Lia** : grossiĂ¨retĂŠs interdites mĂŞme en miroir du registre utilisateur. |
| 29/05/2026 | **Fiches riches (bibliothĂ¨que)** : refonte complĂ¨te du systĂ¨me d'archivage. Appels A+B remplacĂŠs par un appel OS unique produisant 7 composantes (`fil_conducteur`, `noeuds`, `positions`, `questions_ouvertes`, `formulations_cles`, `climat`, `ramifications`) + catĂŠgories ĂŠmoji (liste de 17 ĂŠmojis prĂŠdĂŠfinis, 1â3 par fiche). Nouvelles colonnes `os_riche` + `categories` en base avec migration douce. FTS5 ĂŠtendu. Recall enrichi : le LLM reĂ§oit l'os complet (nĹuds dĂŠveloppĂŠs, questions ouvertes, ramifications) au lieu d'ĂŠtiquettes de mots-clĂŠs. Affichage modale bibliothĂ¨que refondu : ĂŠmojis dans l'en-tĂŞte, os structurĂŠ au dĂŠpliage (fallback `resume_texte` pour anciennes fiches). |
| 31/05/2026 | **Carnet de bord â SKIP enrichi** : instruction SKIP reformulĂŠe â ne se dĂŠclenche plus sur le thĂ¨me gĂŠnĂŠral mais uniquement si les ĂŠchanges rĂŠcents n'apportent rien de nouveau (ni fait, ni ĂŠmotion, ni anecdote, ni changement de ton). "En cas de doute, ĂŠcris la note." Ăvite la suppression abusive de notes sur les fils thĂŠmatiquement cohĂŠrents mais riches. **Cache-busting** : version CSS/JS mise Ă  jour Ă  `20250531` â convention date du jour, suffixe `-1`/`-2` si plusieurs sessions le mĂŞme jour. **gitignore** : `liya.json` corrigĂŠ en `lia.json`. |
| 04/06/2026 (session 2) | **Filtrage triplets â double verrou** : [hub.py] prompt `extract_memories_from_window` renforcĂŠ â lien relationnel explicite requis, exemples INTERDITS enrichis (cĂŠlĂŠbritĂŠs, personnages historiques, rĂ´les anonymes), reformulation "prĂŠnom seul ne suffit pas". [memory.py] validation `sujet` dans `save_inline_memory()` â `_is_prenom()` + `_SUJETS_BLOQUES` rejettent rĂ´les gĂŠnĂŠriques, verbes, groupes nominaux et nom de l'assistant avant tout stockage. |
| 08/06/2026 | **Galerie images + correctifs generation** (v2 -- cache 20260608-1) : correctif sauvegarde automatique : le chemin (prefixe direct, route `/api/image/generate`) n'appelait pas `/api/images/save` -- ajout du bloc sauvegarde dans ce second chemin [app.js ligne ~2775]. Cache vide cote navigateur requis pour prise en compte. |
| 08/06/2026 | **Galerie images + correctifs gĂŠnĂŠration** : [engine.py] `gpt-image-1` â `dall-e-3` dans `_generate_dalle()` (accĂ¨s refusĂŠ 403 sur le nouveau modĂ¨le). `generate_image()` refondue : Gemini en principal, dall-e-3 en fallback automatique si Gemini ĂŠchoue. [hub.py] Lexique IMAGE renforcĂŠ : `[SystĂ¨me â image gĂŠnĂŠrĂŠe]` ajoutĂŠ aux chaĂŽnes interdites Ă  reproduire ; rĂ¨gle MODIFICATION simplifiĂŠe avec exemples concrets (`"moins rĂŠaliste"`, `"plus sombre"`âŚ) pour ĂŠviter que Lia formule un prompt verbal sans ĂŠmettre `%%IMAGE:%%`. [database.py] Nouvelle table `images` + 4 fonctions CRUD (`save_image`, `get_images`, `rename_image`, `delete_image`). [main.py] 5 nouvelles routes galerie : `POST /api/images/save`, `GET /api/images`, `GET /api/images/file/{filename}`, `PATCH /api/images/{id}`, `DELETE /api/images/{id}` â dossier `data/images/` crĂŠĂŠ automatiquement. [app.js] Sauvegarde automatique de chaque image gĂŠnĂŠrĂŠe (fire-and-forget). Bouton đźď¸ topbar + modale galerie : grille vignettes, clic plein ĂŠcran, âŹ tĂŠlĂŠcharger, âď¸ renommer (modale dĂŠdiĂŠe + Enter/Escape), đď¸ supprimer (confirm). Cache-busting : `20260608`. |
| 08/06/2026-2 | **SĂŠcurisation token GitHub** : [main.py] `GITHUB_TOKEN` sorti du code source â remplacĂŠ par `os.getenv("GITHUB_TOKEN", "")`. Token stockĂŠ dans `.env` (dĂŠjĂ  prĂŠsent dans `.gitignore`). Ancien token rĂŠvoquĂŠ sur GitHub, nouveau token crĂŠĂŠ. Cache-busting : `20260608-2`. |
| 09/06/2026 | **Matching bibliothĂ¨que automatique** : [database.py] `get_bibliotheque_index()` â retourne l'index lĂŠger des fiches (id, titre, tags, categories, date_conversation). [hub.py] `_MOTS_VIDES` + `_MOTS_RAPPEL` + `_match_bibliotheque(user_message)` â matching fuzzy (`rapidfuzz`) entre le message utilisateur et l'index bibliothĂ¨que. Scoring : tag fuzzy match â +2 pts, mot titre â +1 pt. Seuil normal : 3 pts. Seuil abaissĂŠ Ă  2 pts si mot-clĂŠ de rappel dĂŠtectĂŠ (`souviens`, `rappelle`, `on avait parlĂŠ`âŚ). Max 2 fiches injectĂŠes. Les deux pipelines (`process_message` + `process_message_stream`) appellent `_match_bibliotheque()` â `biblio_context` alimentĂŠ automatiquement si match. [requirements.txt] `rapidfuzz>=3.0.0` ajoutĂŠ. Cache-busting : `20260609`. |
| 07/06/2026 | **AccessibilitĂŠ NVDA â audit et correctifs** : [app.js] Menu fil â items dropdown `Renommer` / `Ăpingler` / `Supprimer` convertis de `<div>` en `<button>` avec `role="menuitem"` ; conteneur dropdown avec `role="menu"` â navigation clavier et annonce NVDA opĂŠrationnelles. [index.html] Modale suppression â ĂŠmoji `đď¸` du titre et ĂŠmojis `đ` / `đď¸` des boutons masquĂŠs via `aria-hidden` ; `aria-label` ajoutĂŠs sur les deux boutons d'action. [index.html] Modale đ§  â titre `đ§ ` masquĂŠ ; onglets convertis en `role="tablist"` / `role="tab"` avec `aria-selected` statique ; ĂŠmojis onglets masquĂŠs ; placeholder champ recherche nettoyĂŠ. [app.js] Onglets đ§  â `aria-selected` synchronisĂŠ dynamiquement au clic et Ă  chaque ouverture. [app.js] Filtres mĂŠmoire â `aria-pressed` ajoutĂŠ sur les trois boutons, synchronisĂŠ au clic et Ă  l'ouverture. [app.js] `buildCard()` â `aria-hidden` sur icĂ´nes profondeur et barres de poids ; `aria-label` contextuel sur chaque ligne (`sujet â prĂŠdicat â valeur, poids`) ; `aria-label` sur boutons âď¸ et đď¸ (`Modifier/Supprimer [prĂŠdicat] de [sujet]`). [app.js] Carnet et Anecdotes â boutons đď¸ avec `aria-label="Supprimer cette note/anecdote"`. Cache-busting : `20260607`. |
| 05/06/2026 | **Onboarding & installation fraĂŽche â suite** : [app.js] Suppression du formulaire de crĂŠation intĂŠgrĂŠ Ă  `showUserPicker()` â en l'absence d'utilisateur, le picker se ferme silencieusement et laisse l'onboarding NIMM prendre le relais. [app.js] `init()` â suppression du `return` et du `showUserPicker()` en mode mono sans utilisateur : le flux descend naturellement jusqu'Ă  l'onboarding. [app.js] Onboarding NIMM crĂŠe dĂŠsormais le profil `users.json` via `POST /api/users` (admin: true) en plus du `POST /api/onboarding`. [app.js] `_saveApiKeys()` â basculement automatique sur le premier provider disponible si le provider actuel est Ollama ou vide, suivi d'un `location.reload()` aprĂ¨s 500ms pour synchroniser provider + modĂ¨le depuis la DB. [main.py] Watchdog dĂŠsactivĂŠ â le kill automatique du port 8080 au lancement (`LANCER_NIMM.bat` / `NIMM_DEBUG.bat`) remplace avantageusement la dĂŠtection par ping. Cache-busting : `20260605`. |
| 04/06/2026 | **Correction onboarding installation fraĂŽche** : suppression de `_migrate_legacy_db()` et toute rĂŠfĂŠrence `laurent` codĂŠe en dur (`database.py`). Nettoyage `_cleanup_data_dir()` â suppression de la logique fantĂ´me spĂŠcifique Ă  `laurent` (`main.py`). Onboarding corrigĂŠ : `_currentUserId` et `localStorage` posĂŠs **avant** le fetch `/api/onboarding` pour que le header `X-User-ID` soit injectĂŠ dĂ¨s la premiĂ¨re requĂŞte â la DB est dĂŠsormais crĂŠĂŠe au nom de l'utilisateur rĂŠel (`app.js`). Ajout de `_slugify()` dans le frontend. Suppression du hardcode `_currentUserId === 'laurent'` comme condition admin (`app.js`). **LANCER_NIMM.bat** : suppression du `pip install` au lancement normal (ĂŠconomie 5-8s) + timeout rĂŠduit Ă  4 secondes. |
| 14/06/2026 (mĂŠmoire) | **Extraction mĂŠmoire â comblement des trous identifiĂŠs le 13/06** : [hub.py] prompt `extract_memories_from_window` enrichi sur 4 points â clarification `registre` (une ĂŠmotion rapportĂŠe calmement, ex. "j'ĂŠtais fier de...", reste `neutre` ; `emotionnel` rĂŠservĂŠ au ton Ă  vif) ; nouveaux prĂŠdicats canoniques `qualite` (traits positifs rapportĂŠs, ex. "douce") et `anciennete_pratique` (durĂŠe d'une pratique, ex. "6 ans de judo") ; exception Ă  la RĂGLE D'AUTONOMIE pour les nuances comparatives/qualitatives, rattachĂŠes en `contexte` du triplet concernĂŠ (ex. "gagne aux points plutĂ´t que par ippon") ; nouveau prĂŠdicat `anecdote` (`memoire_type='autre'`, `profondeur=5`, `type_temporal='episodique'`) pour les moments narratifs qui ne se rĂŠsument pas Ă  un trait stable. [memory.py] `qualite`, `anciennete_pratique`, `anecdote` ajoutĂŠs Ă  `PREDICATS_CANONIQUES` (catĂŠgories CARACTĂRE / LOISIRS / ĂVĂNEMENTS) pour reconnaissance immĂŠdiate par `normalize_predicat()`. |
| 15/06/2026 | **Prompts d'extraction memoire par provider**. Trois fichiers crees dans `data/prompts/` : `memoire_deepseek.txt` (shadow prompting + chain notation, exemples anonymises [H]/[F]), `memoire_anthropic.txt` (structure logique, exemples epures pour Haiku), `memoire_mistral.txt` (garde-fous contre les inferences, interdictions avec alternative). Injection `{{DATE}}` et `{{LOCATION}}` dans `extract_memories_from_window()`. Cache-busting : `20260615`. |
| 16/06/2026 | **Migration JSON v2 des prompts + turbo_test**. [data/prompts/] Tous les prompts provider migres du format `%%MEM%%` vers JSON structure : `memoire_deepseek.txt`, `memoire_anthropic.txt`, `memoire_mistral.txt` recrits avec registre obligatoire (neutre/emotionnel/figure/intention/hypothese), predicats canoniques etendus (ecole, competence, employeur, benevolat, anciennete_debut, prenom_pere/mere...), regles autonomie/nuance/anecdote. `memoire_gemini.txt` cree (provider non actif, prompt pret). `memoire_default.txt` conserve tel quel (deja en JSON). [turbo_test.py] Nouveau script a la racine : teste la vraie route v2 d'extraction (charge prompt, injecte variables, appelle API, parse JSON, compare faits attendus, rapport score). Supporte DeepSeek/Anthropic/Mistral/Gemini. Parser robuste 3 tentatives (tableau unique, tableaux multiples fusionnes, objets isoles) â corrige le comportement Mistral Small. Detection modele incompatible avec le provider (evite 404). **Scores obtenus** : DeepSeek 25/31 (80%), Anthropic Haiku 24/31 (77%), Mistral Medium 25/31 (80%). Mistral Small 15/31 (48%) â probleme de format resolu par le parser robuste et changement vers Medium. Les 6 manques recurrents sont des ambiguites semantiques du script de test (livres audio classe sous lecture, grade marron sous competence, origine sous nationalite) â le fond de l'extraction est correct. |
| 17/06/2026 | **Chiralite des relations memoire + harmonisation UI (ajouts Nando)**. [modules/memory.py] `PREDICATS_SYMETRIQUES` : seules les relations horizontales (conjoint, ami, collegue, frere_ou_soeur) generent une reciproque automatique â toute relation verticale (pere/mere, enfant, chef/subordonne, medecin/patient...) est bloquee dans `_save_symmetric()`, corrige les triplets aberrants du type `Jean / enfant / Laurent`. [data/prompts/] Les trois prompts provider mis a jour : regle ÂŤ un seul triplet par fait, dans le sens naturel de l'enonce, jamais la reciproque Âť. [frontend/styles.css] `#summary-btn` stylise comme `#search-web-btn` (fond bg-input, bordure arrondie). `Recherches` et `Memoire` regroupes cote a cote en haut de sidebar (`sidebar-top-row` / `sidebar-half-btn`) â ancien style `#toggle-memory` topbar retire (ecrasait le cadre). [frontend/app.js] `_saveDraft()` : indicateur supprime pendant la frappe â affiche uniquement a la restauration d'un brouillon au demarrage. |
| 29/05/2026 | **Rendu stream par paragraphes + effet anaglyphe** : pendant le stream, chaque paragraphe terminĂŠ (double `\n\n`) est rendu en Markdown avec un effet glitch anaglyphe (~320ms : texte brut + `text-shadow` rouge/cyan vibrant via CSS variables `--gx`/`--gy`) avant dissolution vers le HTML propre. La bulle est vidĂŠe (`innerHTML = ''`) avant `_renderBubble()` en fin de gĂŠnĂŠration. Classe CSS `.glitch-anaglyph` dans `styles.css`. Fonctions `_scrambleReveal()` et `_flushRenderedParagraphs()` ajoutĂŠes dans la boucle stream de `app.js`. **Carnet de bord â anti-doublon** : `maybe_generate_carnet_note()` lit les 6 derniĂ¨res notes existantes et les injecte dans le prompt avec instruction `SKIP` si le sujet est dĂŠjĂ  couvert. Ăvite la gĂŠnĂŠration de notes quasi-identiques sur les fils longs. |



## Changelog

### Session 07/06/2026
**Correctif moteur d'infĂŠrence â entitĂŠs fantĂ´mes**

- [memory.py] `_ROLES_BLOQUES` dĂŠfini dans `run_inference_engine()` â ensemble des rĂ´les familiaux gĂŠnĂŠriques (`pere`, `mere`, `fils`, `fille`, `enfant`, `frere`, `soeur`, `grand_parent`, `petit_enfant`, `parent`, `beau_pere`, `belle_mere`) fusionnĂŠ avec `_PSEUDO_ENTITES`
- [memory.py] Filtre `source_data` mis Ă  jour : utilise `_ROLES_BLOQUES` au lieu de `_PSEUDO_ENTITES` â les rĂ´les gĂŠnĂŠriques sont exclus dĂ¨s l'alimentation des rĂ¨gles d'infĂŠrence
- [memory.py] Guard dans `_add()` : bloque tout triplet infĂŠrĂŠ dont le sujet ou l'objet normalisĂŠ est dans `_ROLES_BLOQUES`, avec message console `đŤ RĂ´le gĂŠnĂŠrique bloquĂŠ`
- RĂŠsultat : l'entitĂŠ fantĂ´me `đ¤ pere` ne se recrĂŠe plus ; les vrais prĂŠnoms (`Jean`, `Jeannette`) passent correctement et gĂŠnĂ¨rent les bonnes infĂŠrences grand-parent/petit-enfant

## BACKLOG

### [PRIORITĂ] Refonte cycle de vie mĂŠmoire â 6 chantiers liĂŠs

Audit mĂŠmoire du 09/06/2026 â dĂŠcisions validĂŠes :

**A â InfĂŠrence dĂŠclenchĂŠe aprĂ¨s extraction** (au lieu du polling toutes les 30s)
`run_inference_engine()` ne se dĂŠclenche plus sur timer aveugle mais uniquement aprĂ¨s qu'une extraction worker ait effectivement ĂŠcrit un ou plusieurs triplets. Ăconomie CPU + cohĂŠrence causale.

**B â ChiralitĂŠ symĂŠtrie** (fix court terme)
`PREDICATS_INVERSES` : `prenom_pere` et ĂŠquivalents gĂŠnĂ¨rent `enfant_de` comme inverse, pas `parent`. Ăvite la lecture contre-intuitive dans la modale mĂŠmoire.

**C â Poids initial Ă  0.5** (rĂ¨gle Occurrence / CoĂŻncidence / RĂŠcurrence)
Tout nouveau triplet entre avec `poids = 0.5` (fragile). La rĂ¨gle devient :
- Occurrence 1 : poids 0.5 â fragile, soumis au decay normal
- Occurrence 2 : poids 1.0 â coĂŻncidence, survit mieux, remonte dans les recalls
- Occurrence 3+ : poids âĽ 1.5 â consolidĂŠ, immune au decay, ĂŠligible Profil certain
Seuils existants `POIDS_PERMANENT_SEUIL = 2.5` et `REPETITIONS_PERMANENT_SEUIL = 3` conservĂŠs.

**D â Decay actif** (tĂ˘che au dĂŠmarrage de session)
Appliquer `DECAY_RATES` aux mĂŠmoires non-permanentes au dĂŠmarrage du serveur (une fois par session). Objectif : un fait vu une seule fois (poids 0.5) disparaĂŽt du recall entre 3 et 6 mois. Taux cibles Ă  calibrer â base de travail : 0.3â0.5%/24h selon catĂŠgorie. Seuil d'invisibilitĂŠ : `POIDS_RECALL_MIN = 0.1` (dĂŠjĂ  en place).

**E â RĂŠsolution conflit par rĂŠcence**
Si deux triplets ont mĂŞme sujet + prĂŠdicat mais objets diffĂŠrents, le plus rĂŠcent (`timestamp`) prime sur le plus lourd (`poids`). Ăvite qu'un fait ancien bien renforcĂŠ ĂŠcrase une mise Ă  jour rĂŠcente (ex : ancien employeur qui prime sur le nouveau).

**F â Embeddings installation silencieuse**
Au premier dĂŠmarrage : lancer `pip install sentence-transformers` en subprocess non-bloquant, poser un flag en base (`embeddings_status : installing / ready`). `_get_model()` consulte ce flag â mode keyword si installing, modĂ¨le chargĂŠ si ready. L'utilisateur n'a rien Ă  faire, l'installation aboutit au prochain dĂŠmarrage si interrompue.

**G â Normaliseur prĂŠdicats libres** (Ă  la demande)
Passe manuelle dĂŠclenchable depuis l'interface (bouton dans la modale mĂŠmoire ?) qui tente de fusionner les prĂŠdicats libres sĂŠmantiquement proches vers leurs ĂŠquivalents canoniques. Ăvite les doublons du type `conduit_camion` + `metier`.

**Ordre d'implĂŠmentation suggĂŠrĂŠ :** B â C â D â E â A â F â G

---

### [PRIORITĂ] Agrandissement fenĂŞtre active + Carnet progressif

DĂŠcision du 09/06/2026 â objectif : supporter les fils trĂ¨s longs (style de l'utilisateur principal).

**ProblĂ¨me actuel :** fenĂŞtre de 30 messages trop courte â Lia perd le fil d'une conversation soutenue bien avant que le Carnet intervienne (seuil 80 messages).

**Trois constantes Ă  modifier dans `hub.py` :**
- Nombre de messages chargĂŠs : 30 â 60
- `CARNET_WINDOW` : 80 â 50 (Carnet se dĂŠclenche avant que les vieux messages sortent de fenĂŞtre)
- `CARNET_INTERVAL` : 7 â 5 (rĂŠsumĂŠs plus frĂŠquents = plus granulaires = moins de perte)

**RĂŠsultat attendu sur un fil de 200 messages :**
- Messages 141-200 : fenĂŞtre active complĂ¨te (tout le dĂŠtail)
- Messages 1-140 : ~28 notes Carnet courtes, fil conducteur narratif
- Faits importants : mĂŠmoire triplet, permanents en parallĂ¨le

**Vigilance Ă  l'implĂŠmentation :** vĂŠrifier qu'il n'y a pas d'effet de bord sur la gĂŠnĂŠration des notes Carnet (frĂŠquence, dĂŠduplication anti-doublon).

---

### [LIVRĂ 16/06/2026] Export messages marquĂŠs
Marquer des rĂŠponses depuis le menu "La rĂŠponse" â export `POST /api/export` â 7 formats.
Phase 2 possible : instruction directe ("fais-moi un DOCX sur X") via CoaNIMM ou intent_gate.

### [PRIORITĂ] Migration Git pour Ăric et Nando
Ăric et Nando ont NIMM installĂŠ depuis un ZIP (`NIMM-main`). Le `git pull` automatique dans `LANCER_NIMM.bat` ne fonctionne pas chez eux â pas de lien Git.
**Objectif :** un script `MIGRER_VERS_GIT.bat` Ă  exĂŠcuter une seule fois qui installe Git si absent, clone le repo, prĂŠserve `data/users.json` et `data/nimm_*.db`, puis branche le lancement sur le nouveau dossier.
**MĂŠcanisme d'entrĂŠe du chemin :** glisser-dĂŠposer le dossier NIMM sur le `.bat`.
**PrĂŠrequis :** Ăric et Nando sont dĂŠjĂ  collaborateurs sur le repo GitHub privĂŠ.
**Statut :** Ă  construire lors d'un appel test avec Nando â session dĂŠdiĂŠe.

### [FUTUR] Normaliseur prĂŠdicats libres (G)
Passe manuelle dĂŠclenchable depuis l'interface qui tenterait de fusionner les prĂŠdicats libres sĂŠmantiquement proches vers leurs ĂŠquivalents canoniques (ex : `conduit_camion` â `metier: chauffeur poids lourd`). Complexe : une fusion naĂŻve perd l'information contenue dans le prĂŠdicat libre. NĂŠcessite une UI de validation avant application. Ă affiner avant d'implĂŠmenter.

---

| 19/06/2026 (session 2) | **Galerie images â correctif sauvegarde via chat + rĂŠparation encodage app.js**. [app.js] Bug : la sauvegarde automatique d'une image gĂŠnĂŠrĂŠe en langage naturel (chemin chat, gestionnaire `[IMAGE_GEN]`) rĂŠfĂŠrenĂ§ait une variable inexistante `_currentThreadId` (au lieu de `currentTabId`/`currentThreadId`) â `ReferenceError` silencieuse interrompant le `fetch('/api/images/save')` avant son envoi. L'image s'affichait dans le fil mais n'atteignait jamais la table `images` ni le dossier `data/images/`. CorrigĂŠ : `thread_id: currentTabId || currentThreadId || ''`. Le chemin bouton dĂŠdiĂŠ đźď¸ (`/api/image/generate`) n'ĂŠtait pas affectĂŠ. **Incident annexe dĂŠcouvert pendant la correction** : `frontend/app.js` contenait deux octets isolĂŠs en CP1252/Latin-1 au lieu d'UTF-8 (un `ĂŠ` dans un commentaire de `_coanimmShowResult`, un espace insĂŠcable dans un message d'erreur) â hĂŠritage probable d'un ĂŠditeur mal configurĂŠ cĂ´tĂŠ Mac/Linux. Cline (DeepSeek-chat) dĂŠtectait l'ĂŠchec de dĂŠcodage strict et basculait automatiquement en lecture `latin-1` pour contourner, ce qui corrompait l'intĂŠgralitĂŠ des accents/emojis/sĂŠparateurs du fichier Ă  chaque rĂŠĂŠcriture. Les deux octets fautifs ont ĂŠtĂŠ localisĂŠs par script Python (position exacte + contexte) et corrigĂŠs en manipulation d'octets bruts, sans relecture `latin-1` du fichier entier. [.clinerules] Nouvelle section ÂŤ Encodage â tous fichiers Âť : interdiction explicite de tout repli `latin-1`/`cp1252` en cas d'erreur de dĂŠcodage UTF-8 ; obligation de s'arrĂŞter et de remonter l'erreur exacte plutĂ´t que de contourner silencieusement. Nando informĂŠ (commentaire fautif situĂŠ dans son apport CoaNIMM). Cache-busting : `20260619-1`. |
| 19/06/2026 (session 3) | **MĂŠmoire â sujets aberrants dans les triplets (placeholders, possessifs, fonctions)**. Constat terrain : le panneau mĂŠmoire affichait des sujets invalides (`sa femme`, `ma femme`, `[F]`, `[collegue]`) â les en-tĂŞtes de section (`đź Travail`, `đĄ Vie quotidienne`âŚ) ĂŠcartĂŠs du diagnostic car gĂŠnĂŠrĂŠs par l'affichage (`CATEGORIE_LABELS` dans app.js), pas stockĂŠs en base. [data/prompts/memoire_deepseek.txt] Cause racine identifiĂŠe : les exemples de la section EXEMPLES utilisaient `[F]`/`[H]` comme `sujet` pour illustrer l'anonymisation â DeepSeek gĂŠnĂŠralisait ce gabarit non rĂŠsolu comme format de sortie valide. RemplacĂŠs par des prĂŠnoms fictifs concrets (Camille/Julien). Ajout dans INTERDICTIONS : rejet des placeholders non remplis (`[F]`, `[H]`, `[prĂŠnom]`, `X`, `Madame`, `Monsieur`) avec repli sur `sujet={{USER_NAME}}` + lien de parentĂŠ. Ajout dans LOGIQUE : tiers nommĂŠ par sa fonction sans prĂŠnom (`mon commandant`, `le maire`, `mon chef`) â `sujet={{USER_NAME}}`, `predicat="relation_sociale"`, objet = la fonction citĂŠe ; et formule de mĂŠmorisation forcĂŠe (`retiens que`, `souviens-toi que`, `garde en mĂŠmoire`, `n'oublie pas que`) â extraction obligatoire du fait qui suit, mĂŞme jugĂŠ mineur, sujet toujours soumis Ă  la mĂŞme rĂ¨gle de fond. [modules/memory.py] `_is_prenom()` : ajout des dĂŠterminants possessifs (`ma` `ta` `sa` `mon` `ton` `son` `mes` `tes` `ses` `notre` `votre` `leur` `leurs`) au set `mots_outils` â bloque les formulations relationnelles type "sa femme" prĂŠcĂŠdemment acceptĂŠes comme sujet valide (2 mots, pas de mot-outil dĂŠtectĂŠ). **Non traitĂŠ aujourd'hui** : mĂŞmes rĂ¨gles non rĂŠpercutĂŠes sur `memoire_mistral.txt` / `memoire_anthropic.txt` (providers secondaires, pas utilisĂŠs pour la tĂ˘che mĂŠmoire actuellement) â Ă  faire par cohĂŠrence si besoin. Anomalies dĂŠjĂ  prĂŠsentes en base non nettoyĂŠes automatiquement par ce correctif (prĂŠventif uniquement) â nettoyage manuel via panneau mĂŠmoire ou `audit_memory()` Ă  prĂŠvoir. **Ă tester en conditions rĂŠelles** : dictĂŠe vocale variĂŠe en situation de travail, vĂŠrifier qu'aucun nouveau sujet aberrant n'apparaĂŽt. Cache-busting : `20260619-2`. |
| 19/06/2026 | **STT turbo â persistance serveur**. [main.py] Routes `GET`/`POST /api/settings/stt-turbo` ajoutees (manquaient depuis le 18/06) â `get_setting`/`set_setting` sur la cle `stt_turbo`, meme patron que `local-mode`. Le POST accepte `value` (format envoye par le frontend) avec repli sur `enabled`. [app.js] Aucun changement : le frontend appelait deja les bons endpoints, seule la persistance manquait cote serveur. Persistance confirmee par test manuel (toggle + reload). |
| 19/06/2026 | **Carnet de bord â passage en mode pull (search_carnet)**. Constat terrain : sur fil long, l'injection systematique des notes carnet a chaque tour sur-ancrait le LLM sur ces notes au detriment du message courant (rapporte sur l'usage de l'epouse de l'utilisateur). [hub.py] `build_system_prompt` n'injecte plus le contenu des notes â remplace par un signal leger annoncant l'existence du carnet et invitant a appeler `search_carnet(sujet)`. Nouvel outil declare dans `NIMM_TOOLS` (meme patron que `search_documents`) et aiguille dans `_execute_tool` : recherche par mots-cles simple (mots > 2 lettres) dans `get_carnet_notes(thread_id)`, repli sur les 5 notes les plus recentes si aucun mot-cle ne matche. [hub.py] `process_message` et `process_message_stream` : remplacement de l'appel a `get_carnet_notes_actives` (fenetre glissante, devenue obsolete en mode pull) par un simple signal binaire `['actif'] if count_carnet_notes(thread_id) > 0 else None`. Valide par rejeu du test `test_carnet_boucle.py` (80 messages) avant la bascule pull : seuil de declenchement (`CARNET_WINDOW`=50) et frequence (`CARNET_INTERVAL`=5) conformes. Bug de parsing corrige au passage dans `test_carnet_boucle.py` (`lire_derniere_entree_log` ne filtrait pas les blocs vides du split, retournait toujours une chaine vide). **A tester en conditions reelles** : pertinence du filtrage par mots-cles et bon declenchement de `search_carnet` par le LLM sur fil long. Cache-busting : `20260619`. |
| 18/06/2026 | **STT turbo â contexte carnet**. [main.py] Route `/api/stt/transcribe` accepte dĂŠsormais `thread_id` et `turbo` (Form). Si `turbo=true`, rĂŠcupĂ¨re les 3 derniĂ¨res notes du carnet du fil et les injecte comme `initial_prompt` Ă  Whisper (300 car. max) â amĂŠliore la prĂŠcision sur le vocabulaire du contexte en cours. [app.js] FormData enrichi : `thread_id` et `turbo` envoyĂŠs Ă  chaque transcription si turbo actif. Cache-busting : `20260618`. |
| 18/06/2026 | **Carnet de bord â qualitĂŠ et injection glissante**. [hub.py] Prompt `maybe_generate_carnet_note` restructurĂŠ en trois temps : sujet dominant / ĂŠvolution (delta par rapport aux notes existantes) / ĂŠtat (rĂŠsolu, en cours, ouvert) â 2 Ă  3 phrases max. [database.py] Colonne `msg_debut INTEGER DEFAULT 0` ajoutĂŠe Ă  la table `carnet` via migration douce (`ALTER TABLE âŚ ADD COLUMN`) â compatible bases existantes. Nouvelle fonction `get_carnet_notes_actives(thread_id, n_messages, fenetre=60)` : ne retourne que les notes dont `msg_debut < n_messages - fenetre` (les messages rĂŠsumĂŠs sont sortis de la fenĂŞtre active) ; les notes sans `msg_debut` (valeur 0, donnĂŠes antĂŠrieures) sont toujours injectĂŠes. [hub.py] `add_carnet_note` reĂ§oit `msg_debut = max(0, n - CARNET_INTERVAL*2)` Ă  la crĂŠation. Les deux pipelines (`process_message` et `process_message_stream`) utilisent dĂŠsormais `get_carnet_notes_actives` au lieu de `get_carnet_notes`. Cache-busting : `20250618`. |
| 09/06/2026 | **Audit mĂŠmoire â 6 chantiers** : [hub.py] FenĂŞtre active 30â60 msgs. `CARNET_WINDOW` 80â50, `CARNET_INTERVAL` 7â5 â Carnet se dĂŠclenche avant que les vieux messages sortent de fenĂŞtre. Prompt carnet reformulĂŠ : capture ce qui a **bougĂŠ** (delta), note complĂŠmentaire si sujet dĂŠjĂ  couvert, SKIP rĂŠservĂŠ aux ĂŠchanges vides. [memory.py] `PREDICATS_INVERSES` corrigĂŠs : chiralitĂŠ symĂŠtrie â `enfant_1`â`enfant_4`, `fils`, `fille`, `enfant`, `parent` gĂŠnĂ¨rent `enfant_de` comme inverse ; `prenom_pere`/`prenom_mere`â`enfant_de`, `prenom_fils`/`prenom_fille`â`parent` ajoutĂŠs. [hub.py] Poids initial nouveaux triplets 1.0â0.5 (rĂ¨gle Occurrence/CoĂŻncidence/RĂŠcurrence). [memory.py] `apply_decay_on_startup()` â decay appliquĂŠ une fois par session au dĂŠmarrage, suppression sous `POIDS_RECALL_MIN`. [main.py] Thread daemon `_run_decay` lancĂŠ au dĂŠmarrage avant `_run_inference`. [memory.py] RĂŠsolution conflit par rĂŠcence dans `save_inline_memory()` â timestamp nouveau vs existant, le plus rĂŠcent prime mĂŞme sur prĂŠdicat protĂŠgĂŠ. [hub.py] `_worker_process_user()` â `run_inference_engine()` dĂŠclenchĂŠ uniquement si `total_stored > 0` (ĂŠconomie CPU + cohĂŠrence causale). Cache-busting : `20260609-1`. |
| 09/06/2026 (soir) | **Robustesse serveur + refonte recherche mĂŠmoire**. [main.py] `warmup_embeddings` corrigĂŠ (`create_task` sur un `Future` â `TypeError` ; `ThreadPoolExecutor` jamais fermĂŠ â fuite ; `get_event_loop()` dĂŠprĂŠciĂŠ â `get_running_loop()`). `root()` : `index.html` ouvert via `with`. ClĂŠs globales : erreurs de lecture journalisĂŠes ; `save_global_keys` refuse d'ĂŠcrire si le fichier existant est illisible (anti-ĂŠcrasement). [main.py] `/api/update` : archive **publique** GitHub sans jeton (dĂŠpĂ´t public assumĂŠ) â remplace l'approche `.env` ; ancien jeton Ă  rĂŠvoquer. [memory.py] **Vraie recherche vectorielle** : `recall()` ajoute une source de candidats par similaritĂŠ (`_vector_candidate_keys` + `get_all_embeddings`), fusionnĂŠe avec FTS5 â retrouve les souvenirs sans mot commun. Marqueur de modĂ¨le par vecteur (`_serialize_embedding`/`_parse_embedding`, rĂŠtro-compat liste nue) ; `valeur` ajoutĂŠe au texte encodĂŠ ; seuil `VECTOR_CANDIDATE_MIN=0.45`. [database.py] `get_all_embeddings()`. [hub.py] `_worker_process_user()` dĂŠclenche `backfill_embeddings()` Ă  chaque cycle (par lots de 50, dans un thread). |
| 09/06/2026 (soir, suite) | **Decay rĂŠparĂŠ + cache de recherches web**. [memory.py] `apply_decay_on_startup()` rĂŠĂŠcrit : ne persiste plus de poids (l'ancien appel `update_memory_value(..., poids)` levait une `TypeError` et n'ĂŠcrivait pas le poids) â devient une passe de nettoyage qui supprime les souvenirs dont le poids effectif (`effective_poids()`, calculĂŠ Ă  la volĂŠe) est sous `POIDS_RECALL_MIN`. Permanents / consolidĂŠs / catĂŠgories Ă  taux 0 ĂŠpargnĂŠs. [database.py] Table `web_reference` + `save_web_reference` / `get_active_web_references` / `purge_web_references`. [websearch.py] `search_with_cache()` : rĂŠutilise une recherche proche non pĂŠrimĂŠe, mĂŠmorise les nouvelles avec expiration selon pĂŠrissabilitĂŠ (`_ttl_jours`, marqueurs ĂŠphĂŠmĂ¨res) ; repli correspondance exacte si embeddings indisponibles ; constantes `WEBCACHE_*`. [hub.py] `search_web` â `search_with_cache` ; worker purge les rĂŠfĂŠrences expirĂŠes. |
| 09/06/2026 (soir, suite 2) | **PĂŠrissabilitĂŠ par LLM**. [hub.py] `classify_perissabilite_jours()` classe la durĂŠe de validitĂŠ (ĂŠphĂŠmĂ¨re/normale/durable/permanente â 1/30/365/0 j) via `call_llm`, passĂŠ en callback Ă  `search_with_cache`. [websearch.py] classification appelĂŠe uniquement en cas de dĂŠfaut de cache, repli sur l'heuristique `_ttl_jours` si indĂŠterminĂŠ, et **stockage en arriĂ¨re-plan** (`_schedule_store` / `_store_task`) â aucune latence ajoutĂŠe. `ttl=0` â pas d'expiration (permanent). Le classement s'appuie sur la requĂŞte ET un extrait (~800 car.) du contenu trouvĂŠ, pour trancher les cas ambigus. |
| 11/06/2026 | **Enrichissement web (ingestion â zone de rĂŠfĂŠrence) + accessibilitĂŠ**. Nouveau module `modules/enrichissement.py` : portes ÂŤ texte collĂŠ Âť et ÂŤ URL Âť (extraction trafilatura, ĂŠtage lĂŠger sans navigateur), cĹur commun normaliserâvectoriserâranger dans `web_reference` (sĂŠparĂŠ de la mĂŠmoire personnelle, permanent par dĂŠfaut). [main.py] endpoints `/api/enrich/list|text|url` + DELETE. [database.py] colonne `source` sur `web_reference` (+ migration) et `delete_web_reference`. [frontend] panneau ÂŤ đ Enrichissement web Âť (bouton bascule + modale, modĂ¨le Agenda/BibliothĂ¨que). AccessibilitĂŠ : titres masquĂŠs (h1 NIMM, h2 par rĂŠgion) pour la navigation lecteur d'ĂŠcran, et raccourcis clavier globaux Alt+Maj+lettre (C/A/M/G/E/P + S = saisie) annoncĂŠs via `aria-keyshortcuts`. DĂŠpendance : trafilatura. Repli Playwright et PDF/.docx/OCR Mistral â phases suivantes. |
| 11/06/2026 (phase 2) | **Enrichissement web â fichiers, OCR, repli navigateur**. [enrichissement.py] adaptateurs fichiers : `extract_pdf_text` (pypdf), `extract_docx` (python-docx), `ocr_mistral` (API Mistral OCR `mistral-ocr-latest`, PDF image + images), routeur `ingest_file` (PDF texte, sinon OCR si < 40 car. ; .docx ; .rtf ; .odt ; .epub ; .html ; imageâOCR ; .txt/.md/.csv) ; repli navigateur `_render_playwright` (Chromium headless, sans fenĂŞtres) dans `extract_url` quand l'ĂŠtage lĂŠger ramĂ¨ne trop peu de texte. [main.py] endpoint `/api/enrich/file` (UploadFile, traitĂŠ dans un thread ; clĂŠ Mistral via `load_settings`). [frontend] 3áľ mode ÂŤ Fichier Âť dans la modale + envoi multipart + case ÂŤ Forcer l'OCR Âť (drapeau `force_ocr` : court-circuite l'extraction de texte du PDF, utile pour les PDF scannĂŠs ou mixtes). OCR Ă  repli automatique : Mistral si clĂŠ API (qualitĂŠ supĂŠrieure), sinon **Tesseract en local** (`ocr_local`, sans clĂŠ, avec repli de langue eng si fra absent). DĂŠpendances : trafilatura, python-docx, mistralai (OCR cloud), pytesseract/pdf2image/pillow (OCR local), playwright (repli pages JS). |
| 11/06/2026 (phase 3) | **Interrogation des documents ingĂŠrĂŠs (RAG) + dĂŠcoupage**. [database.py] table `reference_chunk` (passages + embeddings, liĂŠs Ă  `web_reference`) ; `save_web_reference` renvoie l'id ; suppression en cascade des passages. [enrichissement.py] `_chunk_text` (passages ~1100 car. avec chevauchement) ; `ingest_text` indexe chaque passage ; `search_documents(query)` = recherche par sens dans les passages, avec source. [hub.py] outil `search_documents` (dĂŠclaration `NIMM_TOOLS` + aiguillage + rĂ¨gle de dĂŠclenchement), pour rĂŠpondre ÂŤ d'aprĂ¨s mes documentsâŚ Âť avec citation. [main.py] `/api/enrich/text` en thread (vectorisation). Le contenu ingĂŠrĂŠ devient rĂŠellement interrogeable, toujours sĂŠparĂŠ de la mĂŠmoire personnelle. |
| 12/06/2026 | **Mode local + accessibilitĂŠ**. [hub.py/main.py/front] interrupteur ÂŤ Mode local Âť (rĂŠglages) : bascule l'infĂŠrence vers **Ollama** (modĂ¨le configurable, dĂŠfaut `llama3.1:8b`) et l'OCR vers **Tesseract** ; la recherche web reste active. Endpoints `/api/settings/local-mode`, `load_settings` expose `local_mode`. [app.js] a11y : les raccourcis clavier dĂŠplacent dĂŠsormais le focus **dans** la modale ouverte (le lecteur d'ĂŠcran suit) ; activation clavier des fils corrigĂŠe (le `keydown` ciblait le `div` au lieu du `span` porteur du clic â EntrĂŠe/Espace charge enfin le fil). |
| 12/06/2026 (chiralitĂŠ) | **Relations genrĂŠes selon le genre dĂŠfini par la personne**. [memory.py] la rĂŠciproque de fratrie concernant l'utilisateur (`frere_ou_soeur`) est genrĂŠe `frĂ¨re`/`sĹur` d'aprĂ¨s le rĂŠglage `user_genre`, que la personne dĂŠfinit elle-mĂŞme (`_est_utilisateur`, `_genrer_fratrie`) ; le conjoint reste ÂŤ conjoint Âť (dĂŠjĂ  neutre). [main.py] endpoints `/api/settings/user-genre`. [front] sĂŠlecteur ÂŤ Comment vous dĂŠfinissez-vous ? Âť (Non prĂŠcisĂŠ / Masculin / FĂŠminin). Non dĂŠfini â neutre conservĂŠ ; anciens souvenirs non rĂŠĂŠcrits. |
| 12/06/2026 (correctifs) | **Ingestion en thread + accessibilitĂŠ des fils**. [main.py] les ingestions (texte/URL/fichier) propagent le contexte utilisateur au thread via `contextvars.copy_context()` â corrige l'ĂŠchec ÂŤ Aucun utilisateur dĂŠfini Âť Ă  l'ouverture de la connexion DB sur gros fichiers. [app.js] chaque fil est dĂŠsormais **un seul bouton activable** (clic sur toute la ligne sauf le menu, EntrĂŠe/Espace) : supprime le double ĂŠnoncĂŠ du nom (
| 16â19/06/2026 | **CoaNIMM â boucle agentique + streaming + accessibilitĂŠ** : [engine.py] tous les `httpx.AsyncClient(timeout=60)` â `timeout=300` (5 occurrences) â corrige `ReadTimeout` sur gĂŠnĂŠration Ă  16 000 tokens. [main.py] exĂŠcution subprocess non buffĂŠrisĂŠe : `env["PYTHONUNBUFFERED"]="1"` + `sys.executable, "-u"` â stdout du script transmis ligne par ligne en temps rĂŠel. [main.py] route SSE `GET /api/coanimm/run_code_stream` â `StreamingResponse` text/event-stream, chaque ligne ĂŠmise immĂŠdiatement, payload `done` inclut `files_list` et `interaction_needed` si marqueur `__NIMM_DEMANDE__` dĂŠtectĂŠ. [main.py] `CoanimmContinueRequest` + `POST /api/coanimm/continue` â reĂ§oit consigne originale, sortie prĂŠcĂŠdente, question posĂŠe, rĂŠponse utilisateur ; reconstruit le contexte complet et rĂŠgĂŠnĂ¨re le script via `generate_code()`. [modules/coanimm.py] `GENERATE_SYSTEM_PROMPT` : rĂ¨gles `input()` interdit, protocole `__NIMM_DEMANDE__`, `print()` en continu, exĂŠcution directe si tĂ˘che sans risque. [frontend/index.html] panneau `#coanimm-interact-panel` (cachĂŠ par dĂŠfaut, `role="region"`, `aria-label="CoaNIMM demande"`) avec question en `aria-live="polite"`, textarea et bouton Envoyer. [frontend/app.js] `_coanimmCurrentConsigne` capturĂŠ Ă  la gĂŠnĂŠration ; done handler : dĂŠtecte `interaction_needed`, affiche panneau, submit handler appelle `/api/coanimm/continue`, relance `runCoanimmExecuteCode` avec le nouveau code (boucle agentique) ; erreur rcâ 0 : `aria-live="assertive"` + `stdoutEl.focus()` pour que le lecteur d'ĂŠcran lise les erreurs. [frontend/app.js] titre boĂŽte risques : `â ď¸ ATTENTION â ce script :`. Annonce NVDA : suppression des announces intermĂŠdiaires qui s'annulaient mutuellement. |
| 25/06/2026 | **MĂŠmoire â un seul partenaire actif Ă  la fois**. [modules/memory.py] `_PARTENAIRE_PREDICATS` (groupe de synonymes conjoint/epoux/epouse/mari/femme/compagnon/compagne/partenaire) + `_purger_partenaires_concurrents(sujet, nouvel_objet, existing)` : supprime tout ancien lien de couple du sujet vers un objet diffĂŠrent avant d'ĂŠcrire un nouveau lien â empĂŞche la coexistence de deux partenaires (ex : `conjoint=Nadia` et `epouse=MaĂŻssane` simultanĂŠment). BranchĂŠ dans `save_inline_memory` (branche crĂŠation d'un nouveau triplet, avant ĂŠcriture) et dans `_save_symmetric` (purge dans les deux sens â sujetâobjet et objetâsujet â avant de crĂŠer la rĂŠciproque). Corrige un cas rĂŠel : triplet orphelin `MaĂŻssane/conjoint/Laurent` + son inverse infĂŠrĂŠ `Laurent/conjoint/MaĂŻssane` se rĂŠgĂŠnĂŠrant en boucle au dĂŠmarrage via le moteur de symĂŠtrie (`run_inference_engine`), faute de garde-fou Ă  l'ĂŠcriture. Note : le moteur d'infĂŠrence lui-mĂŞme (`_add()`) n'a pas encore ce garde-fou â angle mort rĂŠsiduel, acceptĂŠ pour l'instant. |
| 20/06/2026 | **CoaNIMM â fiabilitĂŠ des prompts libres, sĂŠcuritĂŠ (confinement), opĂŠrations Fichiers/Documents, accessibilitĂŠ PDF**. FIABILITĂ [modules/coanimm.py] : `_strip_code_fences` robustifiĂŠ (extrait le bon bloc mĂŞme avec texte parasite, plusieurs blocs, ou rĂŠponse tronquĂŠe) ; `generate_code` fait dĂŠsormais lui-mĂŞme un retry anti-troncature (protĂ¨ge le chemin /api/coanimm/generate de l'UI, pas seulement run_generated) ; auto-rĂŠparation runtime : nouvelle `repair_code` + endpoint `/api/coanimm/repair` + boucle frontend (renvoie l'erreur au modĂ¨le, max 2 tentatives) ; synchronisation plan/code : quand l'exploration disque est requise, le code est gĂŠnĂŠrĂŠ APRĂS l'exploration (plus de code prĂŠ-gĂŠnĂŠrĂŠ puis jetĂŠ) ; correctif `run_script` (appelait `db.get_prompt` inexistant et lisait la clĂŠ 'content' au lieu de 'text' â AttributeError ; corrigĂŠ en `db.list_prompts('script')` + clĂŠ 'text', action 'exec_script'). SĂCURITĂ : nouveau module `modules/coanimm_safety.py` â `classify_for_execution` (analyse AST : bloque eval/exec/os.system/os.popen/ctypes/winreg, demande confirmation pour subprocess/rĂŠseau) et `build_guard_prologue` (code injectĂŠ en tĂŞte du script qui confine au runtime ĂŠcritures, suppressions et dĂŠplacements aux seuls dossiers autorisĂŠs, via interception de open/io.open/os.open/os.remove/rename/shutil ; lectures libres ; connexions rĂŠseau externes bloquĂŠes, localhost perm| 29/06/2026 | **Mistral OCR â extraction de texte structurĂŠ depuis PDF et images**. [main.py] Route `POST /api/mistral/ocr` : accepte un fichier upload (PDF ou image jpg/png/webp/gif/bmp/tiff) **ou** une URL distante. Encode en base64 (fichier local) ou transmet l'URL directement Ă  l'API `mistral-ocr-latest` via `https://api.mistral.ai/v1/ocr`. Retourne le texte extrait en Markdown (titres, tableaux, formules prĂŠservĂŠs) + nombre de pages. EntrĂŠe catalogue CoaNIMM : `ocr_document` (catĂŠgorie Documents). [modules/coanimm.py] Helper `nimm_ocr_document(path='', url='')` : construit un multipart (upload fichier) ou un form-urlencoded (URL) et appelle le endpoint local. PrĂŠfĂŠrable Ă  `nimm_extract_text` pour les PDF scannĂŠs ou contenant des images. AjoutĂŠ au prologue CoaNIMM et Ă  la liste des helpers disponibles. [modules/coanimm_safety.py] `nimm_ocr_document` enregistrĂŠ dans `_CAP_HELPER_CALLS` (capacitĂŠ `recherche`). NĂŠcessite la clĂŠ API Mistral. |
| 29/06/2026 | **Mistral Audio Voices + Audio Speech (TTS preset + clonage zero-shot)**. [modules/tts.py] `list_mistral_voices(api_key)` : appel `GET /v1/audio/voices` Mistral, retourne la liste des voix preset disponibles (robuste : retourne [] si clĂŠ absente). `synthesize_mistral_speech(text, voice_id, ref_audio_b64, fmt, api_key)` : TTS via `voxtral-mini-tts-2603` avec voix preset OU clonage zero-shot (ref_audio base64) via `POST /v1/audio/speech`. IntĂŠgrĂŠe dans `synthesize()` via les prĂŠfixes `mistral:voice_id` (preset) et `mistral-clone:base64` (zero-shot). Voix Mistral preset ajoutĂŠes dans `list_voices()` (đ  Mistral Speech â­â­â­â­â­). [main.py] `GET /api/mistral/audio/voices` : proxy vers Mistral (liste les voix). `POST /api/mistral/audio/speak` : accepte text + voice_id (form) ou text + ref_audio (multipart), produit un fichier audio MP3/WAV/FLAC/OPUS. Catalogue CoaNIMM : entrĂŠe `mistral_speak` (Audio & voix). [modules/coanimm.py] Helper `nimm_mistral_speak(text, voice_id='', ref_audio_path='')` : multipart si ref_audio_path fourni, sinon form-urlencoded ; retourne le chemin du fichier audio produit. [modules/coanimm_safety.py] `nimm_mistral_speak` â capacitĂŠ `recherche`. ClĂŠ Mistral requise. |
| 01/07/2026 | **Modale PIN themee + accessibilite (remplace window.prompt)**. [frontend/index.html] `#pin-modal` : modale sur le pattern `.modal-overlay`/`.modal-box` existant -- pave numerique (0-9, Backspace, Enter), affichage `.pin-dots` (visuel, `aria-hidden`), statut vocal `#pin-modal-status` (`.sr-only`, `aria-live="polite"`), `role="group"` + `aria-label` sur le pave. [frontend/styles.css] `.pin-modal-box`, `.pin-dots`/`.pin-dot`, `.pin-keypad`/`.pin-key`, animation `pinShake` sur erreur, media query mobile (touches agrandies). [frontend/app.js] Controleur `_pinModal` (open/close, saisie tap + clavier physique dont pave numerique, focus trap Tab/Shift+Tab, retour de focus a l'element d'origine a la fermeture, statut vocal du nombre de chiffres saisis). Branche dans `_ensureUnlocked()` (deverrouillage de session, Promise) et `_setUserPin()` (definition/changement de PIN admin, via nouvelle fonction `_askPinModal()`). Remplace tous les `window.prompt`/`window.alert` du flux PIN. Cache-busting : `20260701-2`. |
| 02/07/2026 | **Correction chiralite parent/enfant - le code genere seul les reciproques**. Bug : `enfant_de` collapsait vers `enfant` dans la normalisation, ecrasant le sens inverse (ex : Souleyman/enfant/Khadija au lieu de Souleyman/parent/Khadija). Cause racine reelle : contradiction entre le prompt memoire_deepseek.txt (regle "ne genere jamais la reciproque, le code s'en charge") et son propre exemple (fratrie generait bien la reciproque), plus _save_symmetric() qui bloquait explicitement les relations verticales en attendant que le LLM les fournisse. [modules/memory.py] Modele simplifie a 2 predicats canoniques : `enfant` (sens parent -> enfant) et `parent` (sens enfant -> parent). `PREDICAT_NORMALISATION` : `fils`/`fille`/`enfant_1-4` -> `enfant` ; `enfant_de`/`pere`/`mere`/`prenom_pere`/`prenom_mere` -> `parent` (au lieu de collapser vers `enfant`). `PREDICATS_INVERSES` : inverse de `enfant` est directement `parent` et vice-versa, plus de mot intermediaire `enfant_de`. `_save_symmetric()` : suppression du filtre `PREDICATS_SYMETRIQUES` qui ignorait les relations verticales -- toute relation presente dans `PREDICATS_INVERSES` genere desormais sa reciproque automatiquement, horizontale ou verticale. `_PARENT_PREDS` (moteur d'inference, regle grand-parent) reduit a `{'parent'}` seul. `PREDICATS_MULTI_VALEUR` : `enfant_de` remplace par `parent` (un sujet peut avoir plusieurs parents). [data/prompts/memoire_deepseek.txt] Retrait du 3e triplet de l'exemple fratrie (`Camille/frere/{{USER_NAME}}`) qui contredisait la regle "jamais de reciproque" et poussait le LLM a mal generaliser sur parent/enfant. Nettoyage manuel des triplets `enfant` deja corrompus en base prevu par Laurent depuis NIMM. Cache-busting : `20260702`. |
| 02/07/2026 (2) | **Fiche memoire par personne + systeme "evoques sans lien"**. [frontend/app.js, frontend/styles.css] Refonte de `renderMemory()` : l'affichage passait par categorie en premier niveau (Famille, Travail... repetees pour chaque personne) -- il passe desormais par personne en premier niveau, une fiche unique par sujet, triee alphabetiquement. L'identite (prenom, date_naissance, nationalite...) s'affiche directement en tete de fiche sans sous-titre ; le reste (activite incluse) se range en sous-sections par categorie (`.memory-subsection-title`), dans un ordre fixe (famille, profession, loisirs, quotidien, sante, autre). [modules/memory.py] Nouveau `PREDICATS_LIEN_PERSONNE` : 28 predicats qui expriment un lien avec une personne nommee, repartis horizontal (famille, amitie, voisinage...) et vertical (travail, sante, services...). Nouvelle fonction `sujets_relies(memories)` : construit le graphe de ces liens et parcourt en BFS depuis l'utilisateur pour determiner qui lui est relie, directement ou en chaine (toi -> Khadija -> Nicolas). Objectif : qu'une personne evoquee sans aucun lien reel avec l'utilisateur (ex: une personnalite publique mentionnee en passant) ne se retrouve plus au meme niveau que les vrais proches dans la memoire. [main.py] Route `/api/memory/triplets` : calcule `sujets_relies()` une fois, ajoute un booleen `relie` a chaque triplet retourne. [frontend/app.js] `renderMemory()` separe les fiches reliees (affichees normalement, en premier) des fiches "evoquees sans lien" (regroupees sous un bandeau discret `.memory-section-title--evoques` en bas de liste, memes actions modifier/supprimer). Cache-busting oublie en cours de session (les modifs de renderMemory sont arrivees apres le premier `?v=20260702` du jour) -> corrige en `20260702-2`. A prevoir : afficher le type de lien exact (ami, conjoint, collegue...) dans l'en-tete de chaque fiche reliee, pas seulement le fait qu'un lien existe. Cache-busting : `20260702-2`. |
