# ============================================================
# NIMM — tests/diag_extraction.py
# Diagnostic isolé de l'extraction de triplets (DeepSeek)
#
# Ce script NE modifie PAS la base de données.
# Il simule exactement ce que fait le worker NIMM et affiche
# chaque étape : prompt envoyé → réponse brute → parsing → filtres.
#
# Usage (depuis le dossier racine de NIMM) :
#   python tests/diag_extraction.py
#
# Prérequis :
#   - NIMM n'a PAS besoin de tourner
#   - Clé DeepSeek configurée dans data/nimm_laurent.db
# ============================================================

import sqlite3
import json
import re
import os
import sys
import time
import uuid
import requests
from datetime import datetime

# ── Chemin vers la DB Laurent ──────────────────────────────
_HERE    = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(_HERE, '..', 'data', 'nimm_laurent.db')

# ── API DeepSeek ───────────────────────────────────────────
DEEPSEEK_URL   = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
MAX_TOKENS_EXTRACTION = 600   # valeur corrigée dans hub.py

# ── Délai entre deux appels API (secondes) ─────────────────
DELAI = 3

# ══════════════════════════════════════════════════════════
# 10 MESSAGES DE TEST — du plus évident au plus subtil
# ══════════════════════════════════════════════════════════
MESSAGES = [
    # ── BLOC 1 : faits d'identité bruts ──────────────────
    {
        "id": 1,
        "label": "Prénom + âge + lycée",
        "user": "Ma fille Maïssane a 18 ans. Elle est en Terminale au lycée Bartholdi à Colmar.",
        "assistant": "Ah, 18 ans et le bac qui arrive — c'est une période intense ! Elle passe quand exactement ?",
    },
    {
        "id": 2,
        "label": "Sport + durée de pratique",
        "user": "Maïssane fait du judo depuis 6 ans au club Colmar Judo. Cette saison elle a participé à 4 compétitions.",
        "assistant": "6 ans de judo, c'est solide ! Elle est à quel grade en ce moment ?",
    },
    {
        "id": 3,
        "label": "Résultats sportifs chiffrés",
        "user": "Elle a gagné 2 de ces 4 compétitions. Elle s'est classée 3ème au tournoi départemental de mars.",
        "assistant": "Un bilan 2/4 et une 3ème place au départemental, c'est vraiment bien !",
    },

    # ── BLOC 2 : traits de caractère ──────────────────────
    {
        "id": 4,
        "label": "Caractère général (positif)",
        "user": "Maïssane est quelqu'un de très doux, très à l'écoute des autres. Elle s'entend bien avec tout le monde.",
        "assistant": "Ça transparaît dans ton récit — elle a l'air d'une personnalité vraiment attachante.",
    },
    {
        "id": 5,
        "label": "Point faible technique (sport)",
        "user": "Par contre sur le tapis elle manque parfois d'agressivité. Ça lui coûte des points, les arbitres la pénalisent pour passivité.",
        "assistant": "C'est un équilibre difficile à trouver — le judo demande à la fois calme et explosion. Elle en parle avec son coach ?",
    },
    {
        "id": 6,
        "label": "Nuance technique (ippon vs décision)",
        "user": "Elle gagne rarement par ippon. La plupart de ses victoires, c'est aux points, par décision des arbitres. Elle fait un judo très propre mais pas suffisamment tranchant.",
        "assistant": "Un judo propre c'est une excellente base — l'ippon finira par venir avec la confiance.",
    },

    # ── BLOC 3 : émotionnel + anecdotique ─────────────────
    {
        "id": 7,
        "label": "Réaction émotionnelle (défaite)",
        "user": "La semaine dernière elle a perdu une finale départementale d'un seul point. Elle était complètement dévastée après.",
        "assistant": "Perdre d'un point en finale, c'est brutal. Comment elle a réagi ?",
    },
    {
        "id": 8,
        "label": "Fair-play + fierté paternelle",
        "user": "Malgré tout elle a serré la main de son adversaire sans rien dire, sans pleurer devant tout le monde. Je suis vraiment fier d'elle pour ça.",
        "assistant": "Ce genre de tenue, ça forge le caractère autant que les victoires. Tu as raison d'être fier.",
    },

    # ── BLOC 4 : informations mélangées / implicites ──────
    {
        "id": 9,
        "label": "Deux sujets dans le même message (Laurent + Maïssane)",
        "user": "Je suis chauffeur poids lourd et j'ai du mal à suivre ses compétitions à cause des horaires. Mais Maïssane comprend, elle est très mature pour son âge.",
        "assistant": "Ce n'est pas toujours évident de concilier ton rythme de travail et son planning sportif.",
    },
    {
        "id": 10,
        "label": "Info indirecte + futur proche",
        "user": "Après le bac elle voudrait faire une licence STAPS pour devenir prof de sport. Le judo resterait sa discipline principale.",
        "assistant": "STAPS + judo, c'est une voie cohérente. Elle a regardé quelles facs proposent ça dans sa région ?",
    },
]

# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════

def _sep(char="─", n=65):
    print(char * n)

def _titre(texte):
    _sep("═")
    print(f"  {texte}")
    _sep("═")

def charger_cle_api() -> str:
    """Lit la clé DeepSeek depuis nimm_laurent.db → settings."""
    if not os.path.exists(DB_PATH):
        print(f"❌ DB introuvable : {os.path.abspath(DB_PATH)}")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = 'api_keys' LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        print("❌ Clé 'api_keys' absente dans settings.")
        sys.exit(1)
    try:
        keys = json.loads(row[0])
        cle  = keys.get('deepseek', '')
        if not cle:
            print("❌ Clé DeepSeek vide dans api_keys.")
            sys.exit(1)
        return cle
    except Exception as e:
        print(f"❌ Impossible de parser api_keys : {e}")
        sys.exit(1)

def build_prompt(user_msg: str, assistant_reply: str, user_name: str = "Laurent") -> str:
    """Reconstruit exactement le prompt utilisé par NIMM après correction (hub.py)."""
    context_block = f"Utilisateur : {user_msg}\nAssistant : {assistant_reply[:400]}"
    name = user_name
    return (
        f"Analyse les échanges suivants et émets des tags %%MEM%% pour chaque fait stable "
        f"concernant l'utilisateur ({name}) OU ses proches (enfants, conjoint, amis, famille).\n\n"
        f"Format strict :\n"
        f"%%MEM:type|sujet|prédicat|objet|contexte|mem_type|profondeur|temporal%%\n"
        f"- type      : trait / relation / activite\n"
        f"- sujet     : prénom exact de la personne concernée par le fait.\n"
        f"  → Si le fait concerne un proche, utilise SON prénom (ex: Maïssane), pas celui de {name}.\n"
        f"  → Si tu ne connais pas le prénom du proche, utilise le prénom de {name} avec prédicat 'enfant'/'conjoint'.\n"
        f"  → Jamais 'utilisateur', 'je', 'il', 'elle', 'fille', 'fils' comme sujet.\n"
        f"- prédicat  : 1 mot canonique — age · metier · conjoint · enfant · domicile · "
        f"vehicule · aime · n_aime_pas · sport · loisir · trait · competence · "
        f"probleme_sante · traitement · allergie · objectif · diplome · ecole · permis\n"
        f"- objet     : valeur concrète du fait (prénom, chiffre, mot-clé) — jamais vide.\n"
        f"  → Pour les faits chiffrés (durée, score, classement) : mets le chiffre dans l'objet, pas dans le contexte.\n"
        f"- contexte  : circonstance courte en 5 mots max — vide si aucune\n"
        f"- mem_type  : identite / activite\n"
        f"- profondeur: 1 (identité stable) à 5 (anecdotique)\n"
        f"- temporal  : permanent (identité/caractère) / persistant (projet/habitude) / episodique (événement passé)\n\n"
        f"RÈGLES :\n"
        f"- Plusieurs faits dans un message → autant de tags indépendants, un par fait.\n"
        f"- Un fait sur un proche → sujet = prénom du proche, pas {name}.\n"
        f"- Ne pas mémoriser : questions posées · états purement temporaires · métaphores · fiction · "
        f"conditionnels ('j\\'aimerais', 'peut-être', 'voudrait').\n"
        f"- Aucun fait stable détecté → ne rien émettre.\n\n"
        f"EXEMPLES :\n"
        f"Utilisateur : 'Ma fille Léa a 16 ans et fait de la natation depuis 3 ans.'\n"
        f"%%MEM:trait|Léa|age|16||identite|1|permanent%%\n"
        f"%%MEM:activite|Léa|sport|natation||activite|2|persistant%%\n"
        f"%%MEM:activite|Léa|sport|3 ans de natation||activite|3|persistant%%\n\n"
        f"Utilisateur : 'Je suis mécanicien. Mon fils Tom manque de confiance en lui.'\n"
        f"%%MEM:trait|{name}|metier|mécanicien||identite|1|permanent%%\n"
        f"%%MEM:trait|Tom|trait|manque de confiance||identite|2|permanent%%\n\n"
        f"Échanges récents :\n"
        f"{context_block}\n"
    )

def appel_deepseek(prompt: str, api_key: str, max_tokens: int) -> tuple:
    """
    Appelle l'API DeepSeek.
    Retourne (texte_réponse, tokens_utilisés, tronqué).
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    body = {
        "model":       DEEPSEEK_MODEL,
        "max_tokens":  max_tokens,
        "temperature": 0.0,
        "messages": [
            {
                "role":    "system",
                "content": "Tu es un extracteur de faits. Tu ne produis que des tags %%MEM%%, rien d'autre.",
            },
            {
                "role":    "user",
                "content": prompt,
            },
        ],
    }
    r = requests.post(DEEPSEEK_URL, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    data      = r.json()
    choice    = data["choices"][0]
    texte     = choice["message"]["content"]
    tokens    = data.get("usage", {}).get("completion_tokens", "?")
    tronque   = choice.get("finish_reason") == "length"
    return texte, tokens, tronque

# ══════════════════════════════════════════════════════════
# SIMULATION PIPELINE NIMM (sans écriture DB)
# ══════════════════════════════════════════════════════════

_ACCENTS = str.maketrans(
    'àâäéèêëîïôöùûüçæœÀÂÄÉÈÊËÎÏÔÖÙÛÜÇÆŒ',
    'aaaeeeeiioouuucaoAAAEEEEIIOOUUUCAO'
)

def _normaliser_predicat_simple(p: str) -> str:
    """Version locale simplifiée de normalize_predicat — pour le diagnostic."""
    return p.lower().strip().translate(_ACCENTS).replace("'", '_').replace('-', '_').replace(' ', '_')

def _is_prenom_local(s: str) -> bool:
    s = s.strip()
    if not s or len(s) > 25:
        return False
    mots = s.split()
    if len(mots) > 3:
        return False
    mots_outils = {'qui', 'que', 'pour', 'avec', 'de', 'du', 'le', 'la',
                   'les', 'un', 'une', 'des', 'non', 'pas', 'très', 'trop'}
    if mots[0].lower() in mots_outils:
        return False
    return True

_SUJETS_BLOQUES = {
    'nimm', 'assistant', 'ia', 'bot', 'pere', 'mere', 'fils', 'fille',
    'enfant', 'collegue', 'voisin', 'medecin', 'ami', 'amie', 'chef', 'patron'
}
_VALEURS_CREUSES = {
    '', 'oui', 'non', 'non specifie', 'non_specifie', 'inconnu',
    'aucun', 'aucune', 'n/a', 'na', '?', 'vide', 'unknown',
    'non precise', 'non_precise', 'pas precise',
}

def parser_tags(texte: str) -> list:
    """Parse les %%MEM%% — copie exacte du parser NIMM."""
    pattern = r'%%MEM:([^%]+)%%'
    matches = re.findall(pattern, texte)
    records = []
    for raw in matches:
        parts = raw.split('|')
        if len(parts) == 8:
            type_val, sujet, predicat, objet, contexte, memoire_type, profondeur_str, type_temporal = parts
        elif len(parts) == 7:
            type_val, sujet, predicat, objet, memoire_type, profondeur_str, type_temporal = parts
            contexte = ''
        else:
            records.append({
                '_erreur': f"{len(parts)} champs (attendu 7 ou 8)",
                '_raw':    raw,
            })
            continue
        records.append({
            'type':          type_val.strip(),
            'sujet':         sujet.strip(),
            'predicat':      predicat.strip(),
            'objet':         objet.strip(),
            'contexte':      contexte.strip(),
            'memoire_type':  memoire_type.strip(),
            'profondeur':    profondeur_str.strip(),
            'type_temporal': type_temporal.strip(),
        })
    return records

def simuler_filtres(record: dict) -> tuple:
    """
    Simule les filtres de save_inline_memory sans écrire en DB.
    Retourne (accepté: bool, raison: str).
    """
    if '_erreur' in record:
        return False, f"Format invalide : {record['_erreur']}"

    sujet  = record.get('sujet', '').strip()
    objet  = record.get('objet', '').strip().lower()
    predicat = record.get('predicat', '')

    # Filtre 1 : valeur creuse
    if objet in _VALEURS_CREUSES:
        return False, f"Valeur creuse : '{objet}'"

    # Filtre 2 : sujet non-prénom
    if not _is_prenom_local(sujet) or sujet.lower() in _SUJETS_BLOQUES:
        return False, f"Sujet rejeté (non-prénom ou bloqué) : '{sujet}'"

    # Filtre 3 : prédicat vide
    if not predicat.strip():
        return False, "Prédicat vide"

    return True, "✅ Accepté"


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

def main():
    _titre("NIMM — DIAGNOSTIC EXTRACTION TRIPLETS v2 (nouveau prompt)")
    print(f"  DB      : {os.path.abspath(DB_PATH)}")
    print(f"  Modèle  : {DEEPSEEK_MODEL}  |  max_tokens : {MAX_TOKENS_EXTRACTION}")
    print(f"  Messages : {len(MESSAGES)}")
    print(f"  Début   : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

    # ── Charger la clé API ────────────────────────────────
    _sep()
    print("🔑 Chargement de la clé API DeepSeek...")
    api_key = charger_cle_api()
    print(f"   Clé chargée : {api_key[:8]}{'*' * (len(api_key) - 8)}")

    resultats = []

    for msg in MESSAGES:
        _sep("─")
        print(f"\n📨 Message #{msg['id']} — {msg['label']}")
        print(f"   USER : « {msg['user'][:110]}{'...' if len(msg['user']) > 110 else ''} »")

        prompt = build_prompt(msg['user'], msg['assistant'])

        try:
            rep, tok, tronc = appel_deepseek(prompt, api_key, max_tokens=MAX_TOKENS_EXTRACTION)
        except Exception as e:
            print(f"   ❌ Erreur API : {e}")
            rep, tok, tronc = "", "ERR", False

        time.sleep(DELAI)

        # ── Réponse brute ─────────────────────────────────
        print(f"\n   ┌─ Réponse brute ──────────────────────────────")
        if rep.strip():
            for ligne in rep.strip().splitlines():
                print(f"   │  {ligne}")
        else:
            print(f"   │  (vide)")
        tronc_label = "⚠️ TRONQUÉ" if tronc else "ok"
        print(f"   └─ tokens : {tok} | fin : {tronc_label}")

        # ── Simulation pipeline NIMM ──────────────────────
        records  = parser_tags(rep)
        acceptes = []
        print(f"\n   ── Simulation pipeline ──")
        if not records:
            print(f"   ⭕ Aucun tag %%MEM%% produit")
        for r in records:
            ok, raison = simuler_filtres(r)
            if '_erreur' in r:
                print(f"   ❌ Parsing : {raison}")
            elif ok:
                print(f"   ✅ {r['sujet']} / {r['predicat']} = {r['objet']} [{r['type_temporal']}]")
                acceptes.append(r)
            else:
                print(f"   🚫 {r.get('sujet','?')} / {r.get('predicat','?')} = {r.get('objet','?')}  → REJETÉ : {raison}")

        resultats.append({
            'id':      msg['id'],
            'label':   msg['label'],
            'tags':    acceptes,
            'tronque': tronc,
            'vide':    not rep.strip(),
        })

    # ══════════════════════════════════════════════════════
    # RAPPORT FINAL
    # ══════════════════════════════════════════════════════
    _titre("RAPPORT FINAL")

    col_w = 42
    print(f"  {'#':<3} {'Label':<{col_w}} {'Tags OK':>7}  {'Tronc':>5}")
    _sep("·", 65)

    total_tags = 0
    for r in resultats:
        n    = len(r['tags'])
        t    = "⚠️" if r['tronque'] else "—"
        val  = "(vide)" if r['vide'] else f"{n} tag(s)"
        total_tags += n
        label_short = r['label'][:col_w]
        print(f"  {r['id']:<3} {label_short:<{col_w}} {val:>9}  {t:>5}")

    _sep("═")
    print(f"\n  Total triplets acceptés : {total_tags}")
    print(f"  Fin : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"  📝 Ce script n'a écrit aucune donnée en base.")
    print()


if __name__ == "__main__":
    main()
