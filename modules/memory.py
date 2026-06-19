# ============================================
# NIMM — modules/memory.py
# Extraction et rappel mémoire
# ============================================

import json
import re
import uuid
from datetime import datetime
from typing import Optional

from core.engine import call_llm
from core.database import save_memory, get_all_memory, delete_memory, update_memory_value

# ══════════════════════════════════════════
# EMBEDDINGS — chargement lazy
# ══════════════════════════════════════════

_embed_model = None   # modèle chargé en mémoire une seule fois
_embed_error  = None  # message d'erreur si le chargement a échoué

# Modèle d'embeddings utilisé. Son nom est enregistré avec chaque vecteur : si
# l'on change de modèle un jour, les anciens vecteurs sont détectés comme
# incompatibles et recalculés par le worker, au lieu de produire des
# similarités erronées (deux modèles ne sont pas comparables).
_EMBED_MODEL_NAME = 'paraphrase-multilingual-MiniLM-L12-v2'

def _is_embeddings_enabled() -> bool:
    """Vérifie si la recherche par sens est activée dans les settings."""
    try:
        from core.database import get_setting
        return get_setting('embeddings_enabled', 'false').lower() == 'true'
    except Exception:
        return False

def _get_model():
    """Charge le modèle sentence-transformers à la demande. Retourne None si désactivé ou erreur."""
    global _embed_model, _embed_error
    if not _is_embeddings_enabled():
        return None
    if _embed_model is not None:
        return _embed_model
    try:
        from sentence_transformers import SentenceTransformer
        print("[MEMORY] 🔄 Chargement du modèle embeddings...")
        _embed_error = None
        _embed_model = SentenceTransformer(_EMBED_MODEL_NAME)
        print("[MEMORY] ✅ Modèle embeddings chargé.")
    except Exception as e:
        print(f"[MEMORY] ⚠️ Modèle embeddings non disponible : {e}")
        _embed_model = None
        _embed_error = str(e)
    return _embed_model

def _embed(text: str):
    """Retourne le vecteur embedding d'un texte, ou None si indisponible."""
    model = _get_model()
    if model is None:
        return None
    try:
        import numpy as np
        vec = model.encode(text, normalize_embeddings=True)
        return vec
    except Exception as e:
        print(f"[MEMORY] ⚠️ Erreur embedding : {e}")
        return None

def _cosine(a, b) -> float:
    """Similarité cosinus entre deux vecteurs numpy normalisés."""
    try:
        import numpy as np
        return float(np.dot(a, b))
    except Exception:
        return 0.0

# Seuil de similarité minimal pour qu'un souvenir devienne candidat « par le sens ».
VECTOR_CANDIDATE_MIN = 0.45

def _serialize_embedding(vec) -> str:
    """Sérialise un vecteur avec le nom du modèle (pour détecter un changement)."""
    import json as _json
    return _json.dumps({'model': _EMBED_MODEL_NAME, 'vec': vec.tolist()})

def _parse_embedding(raw):
    """Parse un embedding stocké. Retourne (vecteur np ou None, nom_modèle ou None).
    Rétro-compatible : l'ancien format est une simple liste JSON (modèle inconnu)."""
    if not raw:
        return None, None
    import json as _json
    import numpy as np
    try:
        data = _json.loads(raw)
    except Exception:
        return None, None
    if isinstance(data, dict):
        vec, model = data.get('vec'), data.get('model')
    else:
        vec, model = data, None  # ancien format : liste nue, modèle inconnu
    if not vec:
        return None, None
    try:
        return np.array(vec, dtype='float32'), model
    except Exception:
        return None, None

def _vector_candidate_keys(query_vec, limit: int = 50) -> list:
    """Candidats par similarité vectorielle : parcourt tous les souvenirs
    vectorisés et renvoie les clés les plus proches du SENS de la requête —
    y compris ceux qui ne partagent aucun mot avec elle. Force brute, adapté
    à quelques milliers de souvenirs ; au-delà, prévoir un index vectoriel."""
    if query_vec is None:
        return []
    try:
        from core.database import get_all_embeddings
    except Exception:
        return []
    sims = []
    for key, raw in get_all_embeddings():
        mem_vec, model = _parse_embedding(raw)
        if mem_vec is None:
            continue
        if model is not None and model != _EMBED_MODEL_NAME:
            continue  # vecteur d'un autre modèle : incomparable
        s = _cosine(query_vec, mem_vec)
        if s >= VECTOR_CANDIDATE_MIN:
            sims.append((s, key))
    sims.sort(key=lambda x: x[0], reverse=True)
    return [k for _, k in sims[:limit]]

def backfill_embeddings(user_id: str = None, batch: int = 50) -> int:
    """Recalcule les vecteurs manquants (souvenirs créés sans embedding) ou
    issus d'un autre modèle. Traité par lots pour borner le coût ; appelé par
    le worker dans un thread. Aucun effet de bord : seul l'embedding change."""
    if not _is_embeddings_enabled() or _get_model() is None:
        return 0
    if user_id:
        try:
            from core.database import set_user_context
            set_user_context(user_id)
        except Exception:
            pass
    from core.database import get_all_memory, save_memory
    done = 0
    for m in get_all_memory():
        if done >= batch:
            break
        raw = m.get('embedding')
        mem_vec, model = _parse_embedding(raw) if raw else (None, None)
        if mem_vec is not None and model == _EMBED_MODEL_NAME:
            continue  # déjà vectorisé avec le modèle courant
        vec = _embed(f"{m.get('sujet','')} {m.get('predicat','')} {m.get('valeur','')} {m.get('objet','')}")
        if vec is None:
            continue
        m['embedding'] = _serialize_embedding(vec)
        save_memory(m)
        done += 1
    if done:
        print(f"[MEMORY] 🧩 {done} vecteur(s) (ré)calculé(s) par le rattrapage.")
    return done

# Prédicats protégés — ne s'écrasent que sur signal de correction explicite.
# Liste volontairement courte : couvre les faits d'identité fondamentale.
# Les prédicats libres équivalents sont couverts par le matching partiel dans save_inline_memory.
PREDICATS_PROTEGES = {
    # Identité
    'prenom', 'nom', 'age', 'anniversaire', 'nationalite',
    # Vie personnelle stable
    'conjoint', 'epoux', 'epouse', 'partenaire', 'compagnon', 'compagne',
    'femme', 'mari', 'domicile',
    # Profession
    'metier', 'emploi', 'profession', 'employeur',
    # Famille directe
    'pere', 'mere', 'frere', 'soeur',
    'enfant_1', 'enfant_2', 'enfant_3', 'enfant_4',
    'fils', 'fille',
    # Valeurs
    'valeur_principale', 'croyance',
}

# ── Mots signalant une correction explicite ──
SIGNAUX_CORRECTION = (
    "en fait", "maintenant je suis", "je ne suis plus", "j'ai changé",
    "nouveau travail", "nouvelle situation", "depuis peu", "désormais",
    "j'ai quitté", "je viens de", "je suis devenu", "je suis devenue",
    "on s'est séparé", "on divorce", "on s'est marié",
)

# ── Taux de décroissance par catégorie (% par 24h) ──
DECAY_RATES = {
    'famille':    0.0,
    'sante':      0.0,
    'croyances':  0.0,
    'profession': 0.005,
    'loisirs':    0.005,
    'projets':    0.015,
    'quotidien':  0.010,
    'etudes':     0.010,
    'amities':    0.005,
}
POIDS_PERMANENT_SEUIL    = 2.5
REPETITIONS_PERMANENT_SEUIL = 3
POIDS_RECALL_MIN         = 0.1

# Catégories dont le type_temporal est permanent dès la création
CATEGORIES_PERMANENT = {'famille', 'sante', 'croyances'}

# Prédicats forcés en memoire_type = activite — prédicats libres inclus.
PREDICATS_ACTIVITE = {
    'projet_principal', 'projet_secondaire', 'debut_activite',
    'activite_en_cours', 'formation_en_cours', 'objectif_actuel',
    # Formes libres courantes
    'projet', 'activite', 'formation', 'stage', 'objectif', 'mission',
}

# ── Alias de prénoms — Meï = Maïssane, etc.
ALIASES = {
    'meï':       'Maïssane',
    'mei':       'Maïssane',
    'meïssane':  'Maïssane',
}

# ── Relations horizontales (symétriques) — le retournement est valide
# Toute relation absente de cette liste est considérée verticale (chirale)
# et ne génère pas de réciproque automatique.
PREDICATS_SYMETRIQUES = {
    'conjoint', 'epoux', 'epouse', 'mari', 'femme',
    'compagnon', 'compagne', 'partenaire',
    'ami', 'amie', 'ami_proche', 'copain', 'copine',
    'collegue',
    'frere_ou_soeur',
}

# ── Relations symétriques — prédicat original → prédicat inverse
PREDICATS_INVERSES = {
    # Relations conjugales
    'conjoint':    'conjoint',
    'epoux':       'epouse',
    'epouse':      'epoux',
    'mari':        'femme',
    'femme':       'mari',
    'compagnon':   'compagne',
    'compagne':    'compagnon',
    'partenaire':  'partenaire',
    # Relations parent-enfant (liste fermée)
    'enfant_1':    'enfant_de',
    'enfant_2':    'enfant_de',
    'enfant_3':    'enfant_de',
    'enfant_4':    'enfant_de',
    # Relations parent-enfant (libres)
    'fils':        'enfant_de',
    'fille':       'enfant_de',
    'enfant':      'enfant_de',
    'parent':      'enfant_de',
    'enfant_de':   'parent',
    # Ascendants
    'pere':        'enfant_de',
    'mere':        'enfant_de',
    'prenom_pere': 'enfant_de',
    'prenom_mere': 'enfant_de',
    'prenom_fils': 'parent',
    'prenom_fille':'parent',
    # Fratrie
    'frere':       'frere_ou_soeur',
    'soeur':       'frere_ou_soeur',
    'frere_ou_soeur': 'frere_ou_soeur',
    # Amis
    'ami_proche':  'ami_proche',
    'ami':         'ami',
    'amie':        'amie',
    'copain':      'copain',
    'copine':      'copine',
    # Relations professionnelles
    'chef':        'subordonné',
    'patron':      'subordonné',
    'manager':     'subordonné',
    'superieur':   'subordonné',
    'subordonné':  'chef',
    'collegue':    'collegue',
    # Soins
    'medecin':     'patient',
    'kine':        'patient',
    'patient':     'soignant',
}

# ══════════════════════════════════════════
# TAXONOMIE CANONIQUE DES PRÉDICATS
# ══════════════════════════════════════════

# Liste fermée des prédicats canoniques acceptés.
# Le LLM génère librement — normalize_predicat() ramène vers cette liste.
PREDICATS_CANONIQUES = {
    # IDENTITÉ
    'prenom', 'nom', 'age', 'date_naissance', 'taille_cm', 'poids_kg',
    'sexe', 'handicap', 'groupe_sanguin', 'nationalite',
    # FAMILLE
    'conjoint', 'enfant', 'parent', 'frere', 'soeur', 'grand_parent',
    'petit_enfant', 'beau_parent', 'statut_relation',
    # TRAVAIL & ÉTUDES
    'metier', 'employeur', 'anciennete', 'anciennete_debut', 'horaire_travail', 'diplome',
    'ecole', 'competence', 'permis', 'recherche_emploi', 'etudes',
    # SANTÉ
    'probleme_sante', 'traitement', 'allergie', 'medecin', 'operation',
    'suivi_medical', 'addiction', 'regime_alimentaire',
    # GOÛTS & PRÉFÉRENCES
    'aime', 'n_aime_pas', 'plat_prefere', 'aversion_alimentaire',
    'boisson_preferee', 'musique_preferee', 'artiste_prefere',
    'film_prefere', 'serie_preferee', 'livre_prefere', 'auteur_prefere',
    # LOISIRS
    'sport', 'lecture', 'jeu_video', 'cuisine', 'bricolage', 'jardinage',
    'musique_instrument', 'danse', 'ecriture', 'photographie', 'art', 'loisir',
    'anciennete_pratique',
    # POSSESSIONS
    'vehicule', 'domicile', 'logement', 'equipement', 'animal',
    # RELATIONS SOCIALES
    'ami', 'collegue', 'voisin', 'relation_sociale', 'mentor',
    # VALEURS & CROYANCES
    'valeur', 'croyance', 'religion', 'politique', 'engagement',
    # OPINIONS
    'stance', 'opinion',
    # PROJETS & INTENTIONS
    'objectif', 'reve', 'intention', 'projet', 'envie', 'apprentissage',
    # ÉVÉNEMENTS MARQUANTS
    'evenement_vie', 'deuil', 'accident', 'demenagement', 'anecdote',
    # FINANCES
    'budget', 'salaire', 'patrimoine', 'credit', 'epargne',
    # TECHNOLOGIE
    'ordinateur', 'tel_portable', 'logiciel_prefere', 'reseau_social', 'habitude_num',
    # LANGUE & CULTURE
    'langue_maternelle', 'langue_parlee', 'culture_origine',
    # CARACTÈRE
    'trait', 'force', 'faiblesse', 'peur', 'qualite',
    # HABITUDES & RITUELS
    'habitude', 'rituel', 'sommeil', 'fumeur',
    # BIEN-ÊTRE
    'moral', 'stress', 'bien_etre', 'humeur',
    # ORIENTATION
    'orientation_sexuelle',
}

# Table de normalisation : prédicat libre → prédicat canonique.
# Le LLM peut inventer n'importe quelle variante — elle est ramenée ici.
PREDICAT_NORMALISATION = {
    # Métier
    'emploi': 'metier', 'travail': 'metier', 'boulot': 'metier',
    'profession': 'metier', 'poste': 'metier', 'fonction': 'metier',
    'job': 'metier', 'activite_professionnelle': 'metier',
    'conducteur': 'metier', 'chauffeur': 'metier',
    'est': 'metier',
    # Infinitifs — table de référence pour le réducteur verbal (step 9)
    'etudier': 'etudes', 'apprendre': 'etudes', 'se_former': 'etudes',
    'travailler': 'metier', 'bosser': 'metier',
    'habiter': 'domicile', 'demeurer': 'domicile',
    'pratiquer': 'sport', 'jouer': 'loisir',
    'aimer': 'aime', 'detester': 'n_aime_pas',
    'conduire': 'metier', 'vivre': 'domicile',
    # Conjoint
    'femme': 'conjoint', 'mari': 'conjoint', 'epoux': 'conjoint',
    'epouse': 'conjoint', 'partenaire': 'conjoint', 'compagnon': 'conjoint',
    'compagne': 'conjoint', 'marie_a': 'conjoint', 'en_couple_avec': 'conjoint',
    # Enfant
    'fils': 'enfant', 'fille': 'enfant', 'enfant_de': 'enfant',
    'enfant_1': 'enfant', 'enfant_2': 'enfant', 'enfant_3': 'enfant', 'enfant_4': 'enfant',
    'a_une_fille': 'enfant', 'a_un_fils': 'enfant', 'a_des_filles': 'enfant',
    # Domicile
    'adresse': 'domicile', 'ville': 'domicile', 'residence': 'domicile',
    'habitation': 'domicile', 'maison': 'domicile', 'habite': 'domicile',
    'vit_a': 'domicile', 'lieu_habitation': 'domicile',
    # Santé
    'diagnostic': 'probleme_sante', 'pathologie': 'probleme_sante',
    'sante': 'probleme_sante', 'maladie': 'probleme_sante',
    'probleme_de_sante': 'probleme_sante',
    # Taille / poids
    'taille': 'taille_cm', 'poids': 'poids_kg',
    # Loisirs
    'hobby': 'loisir', 'passion': 'loisir', 'loisir_principal': 'loisir',
    'activite_principale': 'loisir', 'pratique_sportive': 'sport',
    'type_de_velo': 'sport', 'cyclisme': 'sport',
    # Ami
    'ami_proche': 'ami', 'amie': 'ami', 'copain': 'ami', 'copine': 'ami',
    # Projet / objectif
    'projet_principal': 'projet', 'projet_secondaire': 'projet',
    'activite_en_cours': 'projet', 'objectif_actuel': 'objectif',
    'reve_de': 'reve', 'envie_de': 'envie', 'projet_durable': 'objectif',
    'objectif_durable': 'objectif',
    # Valeurs
    'philosophie': 'valeur', 'principe': 'valeur', 'valeur_principale': 'valeur',
    # Opinions
    'conviction': 'stance', 'position': 'stance',
    # Habitudes
    'habitude_alimentaire': 'habitude', 'rituel_quotidien': 'rituel',
    # Goûts génériques
    'apprécie': 'aime', 'apprecie': 'aime', 'adore': 'aime',
    'preference': 'aime', 'gout': 'aime',
    # Caractère
    'personnalite': 'trait', 'caractere': 'trait',
    # Possessions
    'possede': 'equipement', 'a_recupere': 'equipement',
    # Résidence
    'compagne': 'conjoint',
    # Divers
    'pratique': 'sport', 'frequence_de_pratique': 'habitude',
    'contrainte': 'habitude', 'usage_du_velo': 'sport',
    'participation': 'evenement_vie', 'a_participe_a': 'evenement_vie',
    'a_celebre': 'evenement_vie', 'a_visite': 'evenement_vie',
    'a_voyage': 'evenement_vie',
}

# Mapping des accents courants → ASCII
_ACCENTS = str.maketrans(
    'àâäéèêëîïôöùûüçæœÀÂÄÉÈÊËÎÏÔÖÙÛÜÇÆŒ',
    'aaaeeeeiioouuucaoAAAEEEEIIOOUUUCAO'
)

# Négations → prédicat canonique
_NEGATIONS = {
    "n'aime_pas":              'n_aime_pas',
    "naime_pas":               'n_aime_pas',
    "n_aime_pas":              'n_aime_pas',
    "aime_pas":                'n_aime_pas',
    "deteste":                 'n_aime_pas',
    "ne_supporte_pas":         'n_aime_pas',
    "ne_mange_pas":            'aversion_alimentaire',
    "n'aime_pas_le_poisson":   'aversion_alimentaire',
    "n'aime_pas_manger":       'aversion_alimentaire',
    "intolerante_a":           'allergie',
    "intolerant_a":            'allergie',
    "ne_boit_pas":             'n_aime_pas',
    "n'aime_pas_le":           'n_aime_pas',
    "n'aime_pas_les":          'n_aime_pas',
    "ne_joue_pas":             'n_aime_pas',
    "ne_regarde_pas":          'n_aime_pas',
    "ne_lit_pas":              'n_aime_pas',
}

# Fautes d'orthographe courantes → forme correcte puis canonique
_FAUTES = {
    'practique':      'sport',
    'pracique':       'sport',
    'metiers':        'metier',
    'profésion':      'metier',
    'profesion':      'metier',
    'profestion':     'metier',
    'conjoit':        'conjoint',
    'conjointe':      'conjoint',
    'enfents':        'enfant',
    'allegie':        'allergie',
    'allergie':       'allergie',
    'domicil':        'domicile',
    'addresse':       'domicile',
    'adresse':        'domicile',
    'hobbie':         'loisir',
    'hobbies':        'loisir',
    'objetif':        'objectif',
    'objectifs':      'objectif',
}

def normalize_predicat(predicat: str) -> str:
    """Normalise un prédicat libre vers sa forme canonique.
    Étapes : accents → apostrophes → espaces → négations → fautes → table → canoniques.
    """
    # 1. Minuscules + strip
    p = predicat.lower().strip()
    # 2. Supprimer les accents
    p = p.translate(_ACCENTS)
    # 3. Normaliser apostrophes et tirets
    p = p.replace("'", '_').replace("'", '_').replace('-', '_').replace(' ', '_')
    # 4. Supprimer les doubles underscores
    while '__' in p:
        p = p.replace('__', '_')
    p = p.strip('_')

    # 5. Négations
    if p in _NEGATIONS:
        canon = _NEGATIONS[p]
        print(f"[MEMORY] 🔀 Prédicat normalisé : '{predicat}' → '{canon}'")
        return canon

    # 6. Fautes d'orthographe
    if p in _FAUTES:
        canon = _FAUTES[p]
        print(f"[MEMORY] 🔀 Prédicat normalisé (faute) : '{predicat}' → '{canon}'")
        return canon

    # 7. Table de normalisation principale
    if p in PREDICAT_NORMALISATION:
        canon = PREDICAT_NORMALISATION[p]
        if canon != p:
            print(f"[MEMORY] 🔀 Prédicat normalisé : '{predicat}' → '{canon}'")
        return canon

    # 8. Déjà canonique (après nettoyage accents)
    if p in PREDICATS_CANONIQUES:
        return p

    # 9. Réduction verbale — tente de reconstruire l'infinitif 1er groupe (-er)
    # Couvre toutes les formes conjuguées sans les lister explicitement.
    # ex : 'etudie' → strip 'e' → 'etudi' + 'er' = 'etudier' → 'etudes'
    _VERB_SUFFIXES = ['aient', 'iez', 'ions', 'ait', 'ais', 'ent', 'ons', 'ez', 'es', 'e']
    for suffix in _VERB_SUFFIXES:
        if p.endswith(suffix) and len(p) > len(suffix) + 2:
            candidate = p[:-len(suffix)] + 'er'
            if candidate in PREDICAT_NORMALISATION:
                canon = PREDICAT_NORMALISATION[candidate]
                print(f"[MEMORY] 🔀 Verbe reduit : '{predicat}' -> '{candidate}' -> '{canon}'")
                return canon
            if candidate in PREDICATS_CANONIQUES:
                print(f"[MEMORY] 🔀 Verbe reduit : '{predicat}' -> '{candidate}'")
                return candidate

    # 10. Inconnu — retour brut nettoyé (log uniquement)
    print(f"[MEMORY] Predicat libre : '{predicat}' -> '{p}'")
    return p

# ── Groupes de synonymes — déduplication résiduelle après normalisation ───────
PREDICAT_SYNONYMES = {
    'metier':          {'emploi', 'travail', 'boulot', 'profession', 'poste', 'fonction'},
    'conjoint':        {'femme', 'mari', 'epoux', 'epouse', 'partenaire', 'compagnon', 'compagne'},
    'enfant':          {'fils', 'fille', 'enfant_1', 'enfant_2', 'enfant_3', 'enfant_4'},
    'domicile':        {'maison', 'logement', 'residence', 'adresse', 'habitation', 'ville'},
    'loisir':          {'loisir_principal', 'hobby', 'passion', 'activite_principale'},
    'probleme_sante':  {'sante', 'diagnostic', 'traitement', 'pathologie', 'maladie'},
    'valeur':          {'valeur_principale', 'croyance', 'philosophie', 'principe'},
    'projet':          {'projet_principal', 'projet_secondaire', 'activite_en_cours', 'objectif'},
    'ami':             {'ami_proche', 'copain', 'copine', 'amie'},
    'stance':          {'opinion', 'conviction', 'position'},
    'sport':           {'pratique_sportive', 'cyclisme', 'activite_sportive'},
}

# Table de lookup inverse : predicat → nom du groupe canonique
_SYNONYME_GROUPE: dict[str, str] = {}
for _canon, _syns in PREDICAT_SYNONYMES.items():
    _SYNONYME_GROUPE[_canon] = _canon
    for _s in _syns:
        _SYNONYME_GROUPE[_s] = _canon

# Prédicats pouvant avoir plusieurs valeurs distinctes pour un même sujet.
# Pour ces prédicats, sujet+prédicat ne suffit pas à identifier un doublon :
# l'objet doit aussi correspondre.
PREDICATS_MULTI_VALEUR = {
    # Enfants
    'fils', 'fille', 'enfant', 'enfant_de',
    'enfant_1', 'enfant_2', 'enfant_3', 'enfant_4',
    # Fratrie
    'frere', 'soeur', 'frere_ou_soeur',
    # Amis
    'ami', 'amie', 'ami_proche', 'copain', 'copine',
    # Professionnel
    'collegue',
}

# Bonus de renforcement par catégorie
RENFORCEMENT = {
    'famille':    0.5,
    'sante':      0.5,
    'croyances':  0.5,
    'profession': 0.3,
    'loisirs':    0.3,
    'projets':    0.4,
    'quotidien':  0.2,
    'etudes':     0.3,
    'amities':    0.3,
}

def effective_poids(m: dict) -> float:
    """Calcule le poids effectif d'un souvenir selon la décroissance."""
    if m.get('type_temporal') == 'permanent':
        return float(m.get('poids', 1.0))
    categorie = m.get('categorie', 'quotidien')
    rate = DECAY_RATES.get(categorie, 0.005)
    if rate == 0.0:
        return float(m.get('poids', 1.0))
    try:
        from datetime import datetime
        ts = m.get('timestamp', '')
        if ts:
            dt = datetime.fromisoformat(ts)
            jours = (datetime.now() - dt).total_seconds() / 86400
            poids = float(m.get('poids', 1.0)) * ((1 - rate) ** jours)
            return round(poids, 4)
    except Exception:
        pass
    return float(m.get('poids', 1.0))

# ══════════════════════════════════════════
# VALIDATION + DÉDUPLICATION
# ══════════════════════════════════════════

_SUJETS_INTERDITS = {'utilisateur', 'user', 'je', 'moi', 'tu', 'il', 'elle', ''}

def _is_valid(s: dict) -> bool:
    sujet = (s.get('sujet') or '').strip().lower()
    return bool(
        sujet and
        sujet not in _SUJETS_INTERDITS and
        s.get('predicat') and
        (s.get('objet') or s.get('valeur'))
    )

def _find_duplicate(new: dict, existing: list) -> Optional[dict]:
    """
    Cherche un doublon dans existing.
    Deux souvenirs sont dupliqués si :
      - même sujet (après résolution d'alias)
      - même prédicat exact OU prédicats dans le même groupe de synonymes
    Pour les prédicats MULTI_VALEUR (fille, ami, collègue…),
    l'objet doit aussi correspondre — fille=Maïssane ≠ fille=Maya.
    """
    ns = _normalize(_resolve_alias(new.get('sujet', '')))
    np = _normalize(new.get('predicat', ''))
    no = _normalize(new.get('objet', ''))
    np_groupe = _SYNONYME_GROUPE.get(np)
    is_multi = np in PREDICATS_MULTI_VALEUR

    for e in existing:
        es = _normalize(_resolve_alias(e.get('sujet', '')))
        ep = _normalize(e.get('predicat', ''))
        if es != ns:
            continue
        # Match exact prédicat
        if ep == np:
            if is_multi:
                if _normalize(e.get('objet', '')) == no:
                    return e
            else:
                return e
        # Match par groupe de synonymes
        if np_groupe and _SYNONYME_GROUPE.get(ep) == np_groupe:
            if is_multi:
                if _normalize(e.get('objet', '')) == no:
                    return e
            else:
                return e
    return None

def _normalize(text: str) -> str:
    return text.lower().strip()


def _resolve_alias(name: str) -> str:
    """Résout les alias de prénoms : Meï → Maïssane."""
    return ALIASES.get(name.lower().strip(), name.strip())

def _is_prenom(s: str) -> bool:
    """Retourne True si la chaîne ressemble à un prénom ou nom propre court.
    Rejette les descriptions longues utilisées comme objets de relation.
    """
    s = s.strip()
    if not s:
        return False
    # Trop long = description, pas un prénom
    if len(s) > 25:
        return False
    # Trop de mots = phrase descriptive
    mots = s.split()
    if len(mots) > 3:
        return False
    # Commence par un mot-outil = description
    mots_outils = {'qui', 'que', 'pour', 'avec', 'de', 'du', 'le', 'la',
                   'les', 'un', 'une', 'des', 'non', 'pas', 'très', 'trop',
                   'ma', 'ta', 'sa', 'mon', 'ton', 'son',
                   'mes', 'tes', 'ses', 'notre', 'votre', 'leur', 'leurs'}
    if mots[0].lower() in mots_outils:
        return False
    return True

# ── Identité de l'utilisateur et genre (défini par la personne elle-même) ──
_SELF_TOKENS = {'moi', 'je', 'utilisateur', 'user', 'soi', 'moi-meme', 'moi meme'}

def _est_utilisateur(nom: str) -> bool:
    """True si `nom` désigne l'utilisateur (jeton de soi, ou prénom déclaré)."""
    n = (nom or '').strip().lower()
    if n in _SELF_TOKENS:
        return True
    try:
        from core.database import get_setting
        un = (get_setting('user_name', '') or '').strip().lower()
        return bool(un) and un != 'utilisateur' and n == un
    except Exception:
        return False

def _genrer_fratrie(predicat_neutre: str) -> str:
    """Genre la réciproque de fratrie selon le genre que la personne a défini
    elle-même (réglage `user_genre`). Non défini → neutre conservé."""
    try:
        from core.database import get_setting
        g = (get_setting('user_genre', '') or '').strip().lower()
    except Exception:
        g = ''
    if g == 'masculin':
        return 'frere'
    if g == 'feminin':
        return 'soeur'
    return predicat_neutre

def _save_symmetric(record: dict, existing: list):
    """Crée le souvenir symétrique d'une relation si applicable.
    Seules les relations horizontales (symétriques) génèrent une réciproque.
    Les relations verticales (chirales) sont ignorées — le LLM extrait les deux sens."""
    predicat = record.get('predicat', '')
    if predicat not in PREDICATS_INVERSES:
        return
    if predicat not in PREDICATS_SYMETRIQUES:
        print(f"[MEMORY] ↕️ Relation verticale ignorée : '{predicat}' (chirale, pas de réciproque)")
        return
    sujet = record.get('sujet', '').strip()
    objet = record.get('objet', '').strip()
    if not sujet or not objet:
        return
    # Ne créer la symétrique que si l'objet ressemble à un prénom réel
    if not _is_prenom(objet):
        print(f"[MEMORY] ⏭️ Symétrique ignorée : '{objet}' n'est pas un prénom")
        return

    pred_sym = normalize_predicat(PREDICATS_INVERSES[predicat])
    # Réciproque de fratrie concernant l'utilisateur → genrer selon le genre défini par la personne.
    if pred_sym == 'frere_ou_soeur' and _est_utilisateur(objet):
        pred_sym = _genrer_fratrie(pred_sym)
    sym = {
        'key':             f"mem_{uuid.uuid4().hex[:8]}",
        'type':            'relation',
        'sujet':           _resolve_alias(objet),
        'predicat':        pred_sym,
        'objet':           sujet,
        'valeur':          sujet,
        'confiance':       record.get('confiance', 0.9),
        'valence':         0.0,
        'sensibilite':     'neutre',
        'cumulatif':       0,
        'categorie':       'famille',
        'profondeur':      record.get('profondeur', 3),
        'type_temporal':   'permanent',
        'expiration':      None,
        'timestamp':       datetime.now().isoformat(),
        'repetitions':     0,
        'poids':           record.get('poids', 1.0),
        'embedding':       None,
        'memoire_type':    'identite',
        'last_reinforced': None,
        'contexte':        record.get('contexte', ''),
        'registre':        record.get('registre', 'neutre'),
    }
    if not _find_duplicate(sym, existing):
        save_memory(sym)
        existing.append(sym)
        print(f"[MEMORY] 🔁 Symétrique : {sym['sujet']} / {sym['predicat']} = {sym['objet']}")

# ══════════════════════════════════════════
# RAPPEL CONTEXTUEL
# ══════════════════════════════════════════

def recall(query: str, limit: int = 20) -> list:
    from difflib import SequenceMatcher
    from core.database import search_memory_fts, get_memories_by_keys, get_permanent_memories

    # ── Résolution des alias dans la requête (Meï → maïssane, etc.)
    query_resolved = query.lower()
    for alias, canon in ALIASES.items():
        query_resolved = query_resolved.replace(alias, canon.lower())

    # ── Mots significatifs : > 1 char pour capturer les prénoms courts
    words = [w for w in re.split(r'\W+', query_resolved) if len(w) > 1]

    def _fuzzy(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    # ── Embedding de la requête — calculé une seule fois (candidats ET scoring)
    query_vec = _embed(query_resolved) if _is_embeddings_enabled() else None

    # ── 1. Candidats FTS5 (pré-filtrage rapide par mots-clés côté SQLite)
    fts_keys  = set(search_memory_fts(query_resolved, limit=50))

    # ── 2. Candidats vectoriels (recherche par sens, même sans mot commun)
    vec_keys  = set(_vector_candidate_keys(query_vec, limit=50))

    # ── 3. Permanents — toujours injectés quelle que soit la requête
    permanents = get_permanent_memories()
    perm_keys  = {m['key'] for m in permanents}

    # ── 4. Récupérer uniquement les enregistrements utiles
    candidate_keys = list(fts_keys | vec_keys | perm_keys)
    if not candidate_keys:
        return []

    memories = get_memories_by_keys(candidate_keys)

    scored = []
    permanent_fallback = []

    for m in memories:
        ep = effective_poids(m)
        is_permanent = m.get('type_temporal') == 'permanent'

        if ep < POIDS_RECALL_MIN and not is_permanent:
            continue

        sujet = m.get('sujet', '').lower()
        text  = f"{sujet} {m.get('predicat','')} {m.get('valeur','')} {m.get('objet','')}".lower()

        score = 0.0

        # Match exact mot-à-mot
        for w in words:
            if w in text:
                score += 1.0

        # Match flou sur le sujet (fautes d'orthographe sur noms propres)
        for w in words:
            if len(w) > 3:
                fs = _fuzzy(w, sujet)
                if fs > 0.75:
                    score += fs * 0.8

        # Bonus FTS5 (candidat confirmé par l'index)
        if m.get('key') in fts_keys:
            score += 0.5

        # Bonus cosinus (recherche par sens)
        raw_emb = m.get('embedding')
        if raw_emb and query_vec is not None:
            mem_vec, _emb_model = _parse_embedding(raw_emb)
            if mem_vec is not None and (_emb_model is None or _emb_model == _EMBED_MODEL_NAME):
                sim = _cosine(query_vec, mem_vec)
                if sim > 0.7:
                    score += sim * 1.5
                elif sim > 0.5:
                    score += sim * 0.8

        # Bonus poids effectif + confiance
        score += ep * 0.2
        score += float(m.get('confiance', 1.0)) * 0.1

        if score > 0:
            scored.append((score, m))
        elif is_permanent:
            permanent_fallback.append((ep * 0.1, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    result = [m for _, m in scored[:limit]]

    # ── Compléter avec les permanents sans score
    result_keys = {m.get('key') for m in result}
    for _, m in sorted(permanent_fallback, key=lambda x: x[0], reverse=True):
        if len(result) >= limit:
            break
        if m.get('key') not in result_keys:
            result.append(m)
            result_keys.add(m.get('key'))

    return result


# ══════════════════════════════════════════
# VERROUS MÉMOIRE — éditions manuelles (🧠)
# ══════════════════════════════════════════

def _get_locks() -> set:
    """Retourne l'ensemble des clés verrouillées manuellement."""
    from core.database import get_setting
    raw = get_setting('memory_locks', '[]')
    try:
        return set(json.loads(raw))
    except Exception:
        return set()

def _add_lock(key: str):
    from core.database import get_setting, set_setting
    locks = _get_locks()
    locks.add(key)
    set_setting('memory_locks', json.dumps(list(locks)))

def is_locked(key: str) -> bool:
    return key in _get_locks()

def lock_memory(key: str):
    """Verrouille un souvenir — ne sera plus jamais écrasé par extraction."""
    _add_lock(key)
    print(f"[MEMORY] 🔒 Verrouillé : {key}")


def save_inline_memory(record: dict, user_msg: str = '', existing: list = None):
    """
    Sauvegarde un souvenir issu du path inline (%%MEM%%).
    - Souvenir verrouillé (édition manuelle 🧠) → ignoré
    - Signal de correction explicite → met à jour objet/valeur même sur prédicat protégé
    - Sinon → renforce le poids uniquement si prédicat protégé
    - existing : liste pré-chargée (évite un SELECT * par appel si plusieurs tags %%MEM%%)
    """
    if existing is None:
        existing = get_all_memory()

    # Filtre valeurs creuses -- aucun interet semantique a stocker
    _VALEURS_CREUSES = {
        '', 'oui', 'non', 'non specifie', 'non_specifie', 'inconnu',
        'aucun', 'aucune', 'n/a', 'na', '?', 'vide', 'unknown',
        'non precise', 'non_precise', 'pas precise',
    }
    objet_brut = record.get('objet', '').strip().lower()
    if objet_brut in _VALEURS_CREUSES:
        print(f"[MEMORY] ⏭️ Valeur creuse ignoree : {record.get('sujet')} / {record.get('predicat')} = '{record.get('objet')}'")
        return

    # Validation du sujet — doit ressembler à un prénom réel
    # Bloque : groupes nominaux ('mon fils'), verbes ('mis_au_chomage'),
    # rôles génériques ('père', 'collègue non nommé'), nom de l'assistant ('NIMM')
    _sujet_brut = record.get('sujet', '').strip()
    _SUJETS_BLOQUES = {'nimm', 'assistant', 'ia', 'bot', 'pere', 'mere', 'fils', 'fille',
                       'enfant', 'collegue', 'voisin', 'medecin', 'ami', 'amie', 'chef', 'patron'}
    if not _is_prenom(_sujet_brut) or _sujet_brut.lower() in _SUJETS_BLOQUES:
        print(f"[MEMORY] ⛔ Sujet rejeté (non-prénom) : '{_sujet_brut}' / {record.get('predicat')} = {record.get('objet')}")
        return

    # Normalisation du predicat vers la taxonomie canonique
    record['predicat'] = normalize_predicat(record.get('predicat', ''))
    # Garantie registre — valeur par défaut si absent (anciens chemins, %%MEM%% legacy)
    record.setdefault('registre', 'neutre')
    duplicate = _find_duplicate(record, existing)

    if duplicate:
        # Priorité absolue : édition manuelle
        if is_locked(duplicate['key']):
            print(f"[MEMORY] 🔒 Ignoré (verrouillé) : {duplicate['sujet']} / {duplicate['predicat']}")
            return

        now = datetime.now()
        last_reinforced = duplicate.get('last_reinforced')
        cooldown_ok = True
        if last_reinforced:
            try:
                delta = (now - datetime.fromisoformat(last_reinforced)).total_seconds()
                if delta < 86400:
                    cooldown_ok = False
            except Exception:
                pass

        categorie     = duplicate.get('categorie', 'quotidien')
        predicat_norm = _normalize(record.get('predicat', ''))

        if cooldown_ok:
            bonus         = RENFORCEMENT.get(categorie, 0.3)
            nouveau_poids = min(float(duplicate.get('poids', 1.0)) + bonus, 5.0)
            nouvelles_rep = int(duplicate.get('repetitions', 0)) + 1
        else:
            nouveau_poids = float(duplicate.get('poids', 1.0))
            nouvelles_rep = int(duplicate.get('repetitions', 0))

        # Correction naturelle : signal explicite, prédicat non protégé, ou nouveau plus récent
        correction_explicite = any(s in user_msg.lower() for s in SIGNAUX_CORRECTION) if user_msg else False
        # Résolution par récence — le triplet le plus récent prime sur le plus lourd
        try:
            ts_new = datetime.fromisoformat(record.get('timestamp', ''))
            ts_old = datetime.fromisoformat(duplicate.get('timestamp', ''))
            plus_recent = ts_new > ts_old
        except Exception:
            plus_recent = False
        if correction_explicite or predicat_norm not in PREDICATS_PROTEGES or plus_recent:
            nouvel_objet    = record.get('objet',  duplicate.get('objet', ''))
            nouvelle_valeur = record.get('valeur', duplicate.get('valeur', ''))
        else:
            nouvel_objet    = duplicate.get('objet', '')
            nouvelle_valeur = duplicate.get('valeur', '')

        type_temporal = duplicate.get('type_temporal', 'persistant')
        if nouveau_poids >= POIDS_PERMANENT_SEUIL or nouvelles_rep >= REPETITIONS_PERMANENT_SEUIL:
            type_temporal = 'permanent'

        updated = {
            **duplicate,
            'objet':           nouvel_objet,
            'valeur':          nouvelle_valeur,
            'poids':           nouveau_poids,
            'repetitions':     nouvelles_rep,
            'type_temporal':   type_temporal,
            'last_reinforced': now.isoformat() if cooldown_ok else duplicate.get('last_reinforced'),
            'timestamp':       now.isoformat(),
        }
        save_memory(updated)
        existing.append(updated)
        _save_symmetric(updated, existing)
        label = '✏️ Corrigé' if correction_explicite else '🔄 Renforcé'
        print(f"[MEMORY] {label} : {duplicate['sujet']} / {duplicate['predicat']} (poids={nouveau_poids:.2f})")
    else:
        # Calcul embedding si disponible (sujet + prédicat + valeur + objet)
        vec = _embed(f"{record.get('sujet','')} {record.get('predicat','')} {record.get('valeur','')} {record.get('objet','')}")
        if vec is not None:
            record['embedding'] = _serialize_embedding(vec)
        record.setdefault('registre', 'neutre')
        save_memory(record)
        existing.append(record)
        _save_symmetric(record, existing)
        print(f"[MEMORY] ✅ {record['sujet']} / {record['predicat']} = {record['objet']} (poids={record['poids']:.2f})")


# ══════════════════════════════════════════
# EXTRACTION TAGS — parse %%MEM%% / %%DOMINANT%%
# ══════════════════════════════════════════

_CATEGORIE_KEYWORDS = {
    'profession': {
        'metier', 'emploi', 'travail', 'boulot', 'employeur', 'entreprise',
        'societe', 'poste', 'fonction', 'profession', 'projet', 'activite',
        'formation', 'stage', 'salaire', 'contrat', 'debut', 'carriere',
    },
    'famille': {
        'conjoint', 'femme', 'mari', 'epoux', 'epouse', 'partenaire',
        'compagnon', 'compagne', 'enfant', 'fils', 'fille', 'pere', 'mere',
        'frere', 'soeur', 'parent', 'grand', 'cousin', 'oncle', 'tante',
        'beau', 'belle', 'famille', 'neveu', 'niece',
    },
    'loisirs': {
        'loisir', 'sport', 'hobby', 'passion', 'cinema', 'musique',
        'lecture', 'jeu', 'cuisine', 'jardinage', 'bricolage', 'voyage',
        'collection', 'danse', 'art', 'dessin', 'photo',
    },
    'croyances': {
        'valeur', 'croyance', 'philosophie', 'religion', 'principe',
        'ethique', 'moral', 'foi', 'spirituel', 'conviction',
    },
    'sante': {
        'maladie', 'sante', 'medecin', 'traitement', 'handicap',
        'douleur', 'allergie', 'medicament', 'operation', 'kine',
        'therapie', 'regime', 'poids', 'fatigue',
    },
    'amities': {
        'ami', 'amie', 'copain', 'copine', 'collegue', 'chef', 'patron',
        'manager', 'superieur', 'voisin', 'connaissance',
    },
}


def _infer_categorie(predicat: str) -> str:
    """Infère la catégorie depuis un prédicat libre par matching de mots-clés."""
    p = predicat.lower().strip()
    for cat, keywords in _CATEGORIE_KEYWORDS.items():
        if p in keywords:
            return cat
    for cat, keywords in _CATEGORIE_KEYWORDS.items():
        for kw in keywords:
            if kw in p or p in kw:
                return cat
    return 'quotidien'


def extract_bilan_tag(text: str) -> Optional[str]:
    """Extrait le contenu du tag %%BILAN%% s'il est présent, ou None."""
    m = re.search(r'%%BILAN:([^%]+)%%', text)
    return m.group(1).strip() if m else None


def extract_all_tags(text: str) -> tuple:
    """
    Extrait tous les tags de la réponse LLM.
    Retourne (texte_nettoyé, dominant, memories, anecdotes).

    Format MEM:      %%MEM:type|sujet|predicat|objet|memoire_type|profondeur|type_temporal%%
    Format ANECDOTE: %%ANECDOTE:titre|contenu|contexte|tags%%
    """
    mem_pattern = r'%%MEM:([^%]+)%%'
    mem_matches = re.findall(mem_pattern, text)

    memories = []
    for raw in mem_matches:
        try:
            parts = raw.split('|')
            if len(parts) == 8:
                type_val, sujet, predicat, objet, contexte, memoire_type, profondeur_str, type_temporal = parts
            elif len(parts) == 7:
                type_val, sujet, predicat, objet, memoire_type, profondeur_str, type_temporal = parts
                contexte = ''
            else:
                print(f"[MEMORY] Tag MEM ignore -- {len(parts)} champs (attendu 7 ou 8) : {raw}")
                continue
            type_val      = type_val.strip()
            sujet         = sujet.strip()
            predicat      = predicat.strip()
            objet         = objet.strip()
            contexte      = contexte.strip()
            memoire_type  = memoire_type.strip()
            type_temporal = type_temporal.strip()
            try:
                profondeur = int(profondeur_str.strip())
            except Exception:
                profondeur = 4
            categorie = _infer_categorie(predicat)
            memory_record = {
                'key':             f"mem_{uuid.uuid4().hex[:8]}",
                'type':            type_val,
                'sujet':           sujet,
                'predicat':        predicat,
                'objet':           objet,
                'valeur':          objet,
                'contexte':        contexte,
                'confiance':       0.9,
                'valence':         0.0,
                'sensibilite':     'neutre',
                'cumulatif':       0,
                'categorie':       categorie,
                'profondeur':      profondeur,
                'type_temporal':   type_temporal,
                'expiration':      None,
                'timestamp':       datetime.now().isoformat(),
                'repetitions':     0,
                'poids':           1.0,
                'embedding':       None,
                'memoire_type':    memoire_type,
                'last_reinforced': None,
            }
            memories.append(memory_record)
        except Exception as e:
            print(f"[MEMORY] Erreur parsing tag MEM: {e}, raw: {raw}")

    # ── Tags ANECDOTE ──
    anecdote_pattern = r'%%ANECDOTE:([^|]+)\|([^|]+)\|([^|]+)\|([^%]+)%%'
    anecdote_matches = re.findall(anecdote_pattern, text)

    anecdotes = []
    for match in anecdote_matches:
        try:
            titre, contenu, contexte, tags = match
            anecdotes.append({
                'titre':    titre.strip(),
                'contenu':  contenu.strip(),
                'contexte': contexte.strip(),
                'tags':     tags.strip(),
            })
        except Exception as e:
            print(f"[MEMORY] Erreur parsing tag ANECDOTE: {e}, match: {match}")

    _VALID_EMOTIONS_SET = {
        'joie', 'confiance', 'anticipation', 'tristesse', 'peur',
        'colere', 'degout', 'surprise', 'reflexion', 'neutre'
    }
    dominant_match = re.search(r'%%DOMINANT:([^%]+)%%', text)
    dominant = 'neutre'
    if dominant_match:
        raw = dominant_match.group(1).strip()
        if '|' in raw:
            # Nouveau format vectoriel : "joie:7|tristesse:3|surprise:2"
            vec_parts = raw.split('|')
            if len(vec_parts) == 3:
                validated = []
                ok = True
                for vp in vec_parts:
                    kv = vp.split(':')
                    if len(kv) == 2:
                        emo = kv[0].strip().lower()
                        try:
                            score = int(kv[1].strip())
                        except ValueError:
                            ok = False; break
                        if emo in _VALID_EMOTIONS_SET and 0 <= score <= 10:
                            validated.append(f"{emo}:{score}")
                        else:
                            ok = False; break
                    else:
                        ok = False; break
                dominant = '|'.join(validated) if ok else 'neutre'
            else:
                dominant = 'neutre'
        else:
            # Ancien format ou plain word — rétrocompatibilité
            word = raw.lower()
            dominant = word if word in _VALID_EMOTIONS_SET else 'neutre'

    situation_match = re.search(r'%%SITUATION:([^%]+)%%', text)
    situation = situation_match.group(1).strip() if situation_match else None

    # ── Tags RAPPEL ──
    rappel_actions = []

    for m in re.finditer(r'%%RAPPEL:CREER:(.+?):(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?|None|):(\w+)%%', text):
        rappel_actions.append({
            'action':      'creer',
            'description': m.group(1).strip(),
            'date':        m.group(2).strip() or None,
            'type':        m.group(3).strip().lower(),
        })

    for m in re.finditer(r'%%RAPPEL:MODIFIER:(\d+):(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?)%%', text):
        rappel_actions.append({
            'action': 'modifier',
            'id':     int(m.group(1)),
            'date':   m.group(2).strip(),
        })

    for m in re.finditer(r'%%RAPPEL:CLOS:(\d+)%%', text):
        rappel_actions.append({
            'action': 'clos',
            'id':     int(m.group(1)),
        })

    for m in re.finditer(r'%%RAPPEL:EMIS:(\d+):([^%]+)%%', text):
        rappel_actions.append({
            'action': 'emis',
            'id':     int(m.group(1)),
            'seuil':  m.group(2).strip(),
        })

    # ── Tag IMAGE ──
    image_match = re.search(r'%%IMAGE:([^%]+)%%', text)
    image_prompt = image_match.group(1).strip() if image_match else None

    text = re.sub(r'%%MEM:[^%]+%%', '', text)
    text = re.sub(r'%%ANECDOTE:[^%]+%%', '', text)
    text = re.sub(r'%%DOMINANT:[^%]+%%', '', text)
    text = re.sub(r'%%SITUATION:[^%]+%%', '', text)
    text = re.sub(r'%%RAPPEL:[^%]+%%', '', text)
    text = re.sub(r'%%IMAGE:[^%]+%%', '', text)
    text = re.sub(r'%%BILAN:[^%]+%%', '', text)
    text = text.strip()

    return text, dominant, memories, anecdotes, situation, rappel_actions, image_prompt


def recall_anecdotes(query: str, limit: int = 3) -> list:
    """
    Recherche des anecdotes par FTS5.
    Retourne une liste de dicts prêts à être formatés pour le LLM.
    """
    from core.database import search_anecdotes_db
    return search_anecdotes_db(query, limit=limit)


# ══════════════════════════════════════════
# MOTEUR D'INFÉRENCE MÉMORIELLE (tâche de fond)
# ══════════════════════════════════════════

def apply_decay_on_startup(user_id: str = None) -> int:
    """
    Passe de nettoyage, une fois par session au démarrage.

    La décroissance elle-même est calculée à la volée par effective_poids() au
    moment du rappel (poids × (1 - taux)^jours depuis le dernier renforcement).
    Cette passe ne réécrit donc AUCUN poids — elle se contente de supprimer
    définitivement les souvenirs non permanents dont le poids effectif est tombé
    sous POIDS_RECALL_MIN, pour éviter que la base se remplisse de souvenirs
    devenus invisibles. Réécrire le poids ici provoquerait un double comptage
    avec effective_poids() à chaque démarrage.

    Retourne le nombre de souvenirs supprimés.
    """
    if user_id:
        from core.database import set_user_context
        set_user_context(user_id)

    supprimes = 0
    try:
        for m in get_all_memory():
            # Permanents et souvenirs consolidés : immunisés
            if m.get('type_temporal') == 'permanent':
                continue
            if float(m.get('poids', 1.0)) >= POIDS_PERMANENT_SEUIL:
                continue
            # Catégories sans décroissance (famille / santé / croyances)
            if DECAY_RATES.get(m.get('categorie', 'quotidien'), 0.005) == 0.0:
                continue

            if effective_poids(m) < POIDS_RECALL_MIN:
                delete_memory(m['key'])
                supprimes += 1
                print(f"[DECAY] Oubli : {m.get('sujet','')} / {m.get('predicat','')} "
                      f"(poids effectif < {POIDS_RECALL_MIN})")

        print(f"[DECAY] Nettoyage terminé — {supprimes} souvenir(s) oublié(s).")
        return supprimes

    except Exception as e:
        import traceback
        print(f"[DECAY] Erreur : {e}")
        traceback.print_exc()
        return supprimes


def run_inference_engine(user_id: str = None):
    """
    Parcourt les triplets existants et applique des règles logiques
    pour déduire de nouveaux faits. Tourne en thread daemon au démarrage.
    Non-bloquant, sans doublon, idempotent.

    Règles :
    1. Symétrie      — répare les inverses manquants (données antérieures)
    2. Transitivité  — parent(A,B) + parent(B,C) → grand_parent(A,C)
    3. Fratrie       — A et B partagent le même parent → frere_ou_soeur(A,B)
    4. Âge dynamique — date_naissance(A, YYYY...) → met à jour age(A, N ans)
    """
    if user_id:
        from core.database import set_user_context
        set_user_context(user_id)
    print("[INFERENCE] 🔍 Démarrage du moteur d'inférence…")
    try:
        existing = get_all_memory()
        added = 0

        # Entités agrégées ou alias à ne pas traiter comme de vraies personnes
        _PSEUDO_ENTITES = {
            'filles', 'papa', 'maman', 'fils', 'enfants',
            'innes_maissane_maya', 'ami_anonyme', 'projet',
        }

        # Rôles génériques interdits comme sujet ou objet d'un triplet inféré
        _ROLES_BLOQUES = {
            'pere', 'mere', 'fils', 'fille', 'enfants', 'enfant',
            'frere', 'soeur', 'grand_parent', 'petit_enfant',
            'parent', 'grands_parents', 'beau_pere', 'belle_mere',
        } | _PSEUDO_ENTITES

        # Seuil minimum : n'inférer qu'à partir de faits établis
        _POIDS_MIN = 1.5
        source_data = [
            r for r in existing
            if float(r.get('poids', 1.0)) >= _POIDS_MIN
            and _normalize(r.get('sujet', '')) not in _ROLES_BLOQUES
            and _normalize(r.get('objet', '')) not in _ROLES_BLOQUES
        ]

        # ── Index local (sujet_normalisé, predicat) → [objets] ──
        idx: dict = {}
        for r in existing:
            k = (_normalize(r.get('sujet', '')), r.get('predicat', ''))
            idx.setdefault(k, []).append(r.get('objet', ''))

        def _exists(sujet, predicat, objet):
            objs = idx.get((_normalize(sujet), predicat), [])
            return any(_normalize(o) == _normalize(objet) for o in objs)

        def _add(sujet, predicat, objet, src):
            nonlocal added
            if not sujet or not objet:
                return
            if _normalize(sujet) in _ROLES_BLOQUES or _normalize(objet) in _ROLES_BLOQUES:
                print(f"[INFERENCE] 🚫 Rôle générique bloqué : {sujet} / {predicat} → {objet}")
                return
            if _exists(sujet, predicat, objet):
                return
            rec = {
                'key':             f"inf_{uuid.uuid4().hex[:8]}",
                'type':            'relation',
                'sujet':           sujet,
                'predicat':        predicat,
                'objet':           objet,
                'valeur':          objet,
                'confiance':       round(float(src.get('confiance', 0.9)) * 0.85, 2),
                'valence':         0.0,
                'sensibilite':     'neutre',
                'cumulatif':       0,
                'categorie':       src.get('categorie', 'famille'),
                'profondeur':      src.get('profondeur', 3),
                'type_temporal':   'permanent',
                'expiration':      None,
                'timestamp':       datetime.now().isoformat(),
                'repetitions':     0,
                'poids':           1.0,
                'embedding':       None,
                'memoire_type':    'inferee',
                'last_reinforced': None,
                'contexte':        '',
                'registre':        'neutre',
            }
            save_memory(rec)
            idx.setdefault((_normalize(sujet), predicat), []).append(objet)
            existing.append(rec)
            print(f"[INFERENCE] ✨ {sujet} / {predicat} → {objet}")
            added += 1

        # ── Règle 1 : Symétrie ──
        for r in list(source_data):
            pred = r.get('predicat', '')
            if pred in PREDICATS_INVERSES:
                subj = r.get('sujet', '').strip()
                obj  = r.get('objet', '').strip()
                if subj and obj and _is_prenom(obj):
                    inv = PREDICATS_INVERSES[pred]
                    _add(obj, inv, subj, r)

        # ── Règle 2 : Transitivité parent → grand-parent ──
        _PARENT_PREDS = {'parent', 'pere', 'mere', 'enfant_de'}
        parent_rels = [r for r in source_data if r.get('predicat', '') in _PARENT_PREDS]

        for r1 in parent_rels:
            A = r1.get('sujet', '').strip()
            B = r1.get('objet', '').strip()
            if not A or not B:
                continue
            for r2 in parent_rels:
                if _normalize(r2.get('sujet', '')) == _normalize(B):
                    C = r2.get('objet', '').strip()
                    if C and _normalize(C) != _normalize(A) and _is_prenom(A) and _is_prenom(C):
                        _add(A, 'grand_parent', C, r1)
                        _add(C, 'petit_enfant', A, r1)

        # ── Règle 3 : Fratrie (même parent commun) ──
        from collections import defaultdict
        parent_to_children: dict = defaultdict(set)
        for r in source_data:
            if r.get('predicat', '') in _PARENT_PREDS:
                parent = _normalize(r.get('objet', ''))
                child  = r.get('sujet', '').strip()
                if parent and _is_prenom(child) and _normalize(child) not in _PSEUDO_ENTITES:
                    parent_to_children[parent].add(child)

        for children in parent_to_children.values():
            kids = list(children)
            for i, c1 in enumerate(kids):
                for c2 in kids[i + 1:]:
                    n1, n2 = _normalize(c1), _normalize(c2)
                    if n1 == n2:
                        continue
                    # Garde : ne pas créer fratrie si l'un est déjà parent de l'autre
                    if _exists(c1, 'parent', c2) or _exists(c2, 'parent', c1):
                        continue
                    if _exists(c1, 'enfant', c2) or _exists(c2, 'enfant', c1):
                        continue
                    src = {'confiance': 0.85, 'profondeur': 3, 'categorie': 'famille'}
                    _add(c1, 'frere_ou_soeur', c2, src)
                    _add(c2, 'frere_ou_soeur', c1, src)

        # ── Règle 4 : Âge dynamique depuis date_naissance ──
        for r in list(existing):
            if r.get('predicat', '') != 'date_naissance':
                continue
            subj  = r.get('sujet', '').strip()
            objet = r.get('objet', '').strip()
            if not subj or len(objet) < 4:
                continue
            try:
                _m = re.search(r'\b(\d{4})\b', objet)
                if not _m:
                    continue
                annee   = int(_m.group(1))
                age_val = datetime.now().year - annee
                if not (0 < age_val < 130):
                    continue
                age_str = f"{age_val} ans"
                age_rec = next(
                    (x for x in existing
                     if _normalize(x.get('sujet', '')) == _normalize(subj)
                     and x.get('predicat', '') == 'age'),
                    None
                )
                if age_rec:
                    if age_rec.get('objet', '') != age_str:
                        save_memory({**age_rec, 'objet': age_str, 'valeur': age_str})
                        print(f"[INFERENCE] 📅 Âge recalculé : {subj} → {age_str}")
                else:
                    _add(subj, 'age', age_str, r)
            except Exception:
                pass

        # ── Règle 5 : Ancienneté dynamique depuis anciennete_debut ──
        for r in list(existing):
            if r.get('predicat', '') != 'anciennete_debut':
                continue
            subj  = r.get('sujet', '').strip()
            objet = r.get('objet', '').strip()
            if not subj or len(objet) < 4:
                continue
            try:
                _m = re.search(r'\b(\d{4})\b', objet)
                if not _m:
                    continue
                annee_debut = int(_m.group(1))
                duree_val   = datetime.now().year - annee_debut
                if not (0 < duree_val < 80):
                    continue
                duree_str = f"{duree_val} ans"
                anc_rec = next(
                    (x for x in existing
                     if _normalize(x.get('sujet', '')) == _normalize(subj)
                     and x.get('predicat', '') == 'anciennete'),
                    None
                )
                if anc_rec:
                    if anc_rec.get('objet', '') != duree_str:
                        save_memory({**anc_rec, 'objet': duree_str, 'valeur': duree_str})
                        print(f"[INFERENCE] ⏱️ Ancienneté recalculée : {subj} → {duree_str}")
                else:
                    _add(subj, 'anciennete', duree_str, r)
            except Exception:
                pass

        print(f"[INFERENCE] ✅ Terminé — {added} triplet(s) ajouté(s).")
    except Exception as e:
        import traceback
        print(f"[INFERENCE] ⚠️ Erreur : {e}")
        traceback.print_exc()
