# ============================================================
# NIMM — tests/diag_famille.py
# Diagnostic extraction triplets — famille complète
#
# Simule 10 messages conversationnels couvrant tout le texte
# "L'Histoire de la Famille" : Laurent, Nadia, Innès,
# Maïssane, Maya, Hélène, Nando.
#
# Ce script NE modifie PAS la base de données.
#
# Usage (depuis le dossier racine de NIMM) :
#   python tests/diag_famille.py
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
import requests
from datetime import datetime

# ── Chemin vers la DB Laurent ──────────────────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, '..', 'data', 'nimm_laurent.db')

MAX_TOKENS_EXTRACTION = 700
DELAI = 3  # secondes entre chaque appel

# ══════════════════════════════════════════════════════════
# 10 MESSAGES — famille complète, ordre conversationnel
# ══════════════════════════════════════════════════════════
MESSAGES = [
    {
        "id": 1,
        "label": "Laurent — identité + parents",
        "user": "Je suis né le 5 juillet 1980. Je suis français. Mon père s'appelle Jean, ma mère Jeannette.",
        "assistant": "Noté. Tu as des frères et sœurs ?",
    },
    {
        "id": 2,
        "label": "Laurent — métier + formation",
        "user": "Je suis chauffeur poids lourd. J'ai un BEP Conduite et Services dans le transport routier, que j'ai passé entre 1995 et 1997. Je préfère le transport régional.",
        "assistant": "Tu travailles depuis combien de temps dans le transport ?",
    },
    {
        "id": 3,
        "label": "Laurent — loisirs",
        "user": "Pendant mes trajets en camion j'écoute des livres audio. Le soir je regarde des matchs sur Footballia.",
        "assistant": "Tu as une équipe préférée ou c'est plutôt les matchs anciens que tu regardes ?",
    },
    {
        "id": 4,
        "label": "Laurent + Nadia — couple + domicile",
        "user": "Je vis avec ma femme Nadia à Colmar. On est 5 dans la maison.",
        "assistant": "Vous êtes installés à Colmar depuis longtemps ?",
    },
    {
        "id": 5,
        "label": "Nadia — identité + profession",
        "user": "Nadia est née le 18 juin 1983 à Guelma, en Algérie. Elle est arrivée en France à 18 ans. Elle est micro-entrepreneuse, elle tient un atelier de couture à domicile qui s'appelle LIMM Couture et Créations.",
        "assistant": "Elle reçoit des clients chez elle ?",
    },
    {
        "id": 6,
        "label": "Nadia — loisir + bénévolat",
        "user": "Nadia fait de la course à pied. Elle est aussi secrétaire bénévole au club Colmar Judo.",
        "assistant": "C'est elle qui a amené les filles au judo ?",
    },
    {
        "id": 7,
        "label": "Innès — identité + études",
        "user": "Notre fille aînée s'appelle Innès, elle a 22 ans, elle est née le 24 mars 2004. Elle est partie faire ses études à Nancy, elle est en Master 1 Droit de la santé à l'Université de Nancy.",
        "assistant": "Elle rentre souvent à Colmar ?",
    },
    {
        "id": 8,
        "label": "Maïssane + Maya — identité + judo",
        "user": "La deuxième c'est Maïssane, 18 ans, née le 15 novembre 2008. Elle est en Terminale au lycée Bartholdi à Colmar. La petite c'est Maya, 12 ans, née le 19 août 2014, elle est en 6ème au collège Victor Hugo. Toutes les deux font du judo. Maïssane est ceinture marron.",
        "assistant": "Elles sont dans le même club que la maman suit en tant que secrétaire ?",
    },
    {
        "id": 9,
        "label": "Hélène + Nando — fratrie + beau-frère",
        "user": "J'ai une sœur qui s'appelle Hélène. Son mari c'est Nando.",
        "assistant": "Tu vois souvent Hélène et Nando ?",
    },
    {
        "id": 10,
        "label": "Laurent — valeur + trait de caractère",
        "user": "J'accorde beaucoup d'importance à mon indépendance. C'est quelque chose de fondamental pour moi.",
        "assistant": "Ça se retrouve dans ton choix de métier aussi, je suppose.",
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

def charger_config() -> tuple:
    if not os.path.exists(DB_PATH):
        print(f"❌ DB introuvable : {os.path.abspath(DB_PATH)}")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    cur.execute("SELECT value FROM settings WHERE key = 'provider' LIMIT 1")
    row = cur.fetchone()
    provider = row[0].strip().lower() if row else 'deepseek'

    cur.execute("SELECT value FROM settings WHERE key = 'chat_model' LIMIT 1")
    row = cur.fetchone()
    model = row[0].strip() if row and row[0] else 'deepseek-chat'

    cur.execute("SELECT value FROM settings WHERE key = 'api_keys' LIMIT 1")
    row = cur.fetchone()
    conn.close()

    if not row:
        print("❌ Clé 'api_keys' absente dans settings.")
        sys.exit(1)
    try:
        keys    = json.loads(row[0])
        api_key = keys.get('deepseek', '')
        if not api_key:
            print("❌ Clé deepseek vide dans api_keys.")
            sys.exit(1)
        return 'deepseek', api_key, model
    except Exception as e:
        print(f"❌ Impossible de parser api_keys : {e}")
        sys.exit(1)

# ══════════════════════════════════════════════════════════
# PROMPT D'EXTRACTION
# ══════════════════════════════════════════════════════════

def build_prompt(user_msg: str, assistant_reply: str, user_name: str = "Laurent") -> str:
    context_block = f"Utilisateur : {user_msg}\nAssistant : {assistant_reply[:400]}"
    return (
        f"Analyse les échanges suivants et émets des tags %%MEM%% pour chaque fait stable "
        f"concernant l'utilisateur ({user_name}) OU ses proches (enfants, conjoint, amis, famille).\n\n"
        f"Format strict :\n"
        f"%%MEM:type|sujet|prédicat|objet|contexte|mem_type|profondeur|temporal%%\n"
        f"- type      : trait / relation / activite\n"
        f"- sujet     : prénom exact de la personne concernée par le fait.\n"
        f"  → Si le fait concerne un proche, utilise SON prénom (ex: Maïssane), pas celui de {user_name}.\n"
        f"  → Si tu ne connais pas le prénom du proche, utilise le prénom de {user_name} avec prédicat 'enfant'/'conjoint'.\n"
        f"  → Jamais 'utilisateur', 'je', 'il', 'elle', 'fille', 'fils' comme sujet.\n"
        f"- prédicat  : 1 mot canonique parmi les suivants :\n"
        f"    age · date_naissance · metier · diplome · conjoint · enfant · domicile · vehicule\n"
        f"    ecole · sport · loisir · competence · objectif · valeur · trait · nationalite\n"
        f"    bénévolat · anciennete_debut · prenom_pere · prenom_mere · frere · soeur\n"
        f"    probleme_sante — UNIQUEMENT maladie/douleur/handicap, jamais un défaut de caractère\n"
        f"- objet     : valeur concrète (prénom, chiffre, mot-clé) — jamais vide.\n"
        f"  → Pour les faits chiffrés (date, âge, durée) : mets le chiffre dans l'objet.\n"
        f"- contexte  : circonstance courte en 5 mots max — vide si aucune\n"
        f"- mem_type  : identite / activite\n"
        f"- profondeur: 1 (identité stable) à 5 (anecdotique)\n"
        f"- temporal  : permanent (identité/caractère) / persistant (projet/habitude) / episodique (événement passé)\n\n"
        f"RÈGLES :\n"
        f"- Plusieurs faits dans un message → autant de tags indépendants, un par fait.\n"
        f"- Un fait sur un proche → sujet = prénom du proche, pas {user_name}.\n"
        f"- Ne pas mémoriser : questions posées · états purement temporaires · métaphores · conditionnels.\n"
        f"- Aucun fait stable détecté → ne rien émettre.\n\n"
        f"EXEMPLES :\n"
        f"Utilisateur : 'Ma fille Léa a 16 ans et fait de la natation depuis 3 ans.'\n"
        f"%%MEM:trait|Léa|age|16 ans||identite|1|permanent%%\n"
        f"%%MEM:activite|Léa|sport|natation||activite|2|persistant%%\n\n"
        f"Utilisateur : 'Je suis mécanicien. Mon fils Tom manque de confiance en lui.'\n"
        f"%%MEM:trait|{user_name}|metier|mécanicien||identite|1|permanent%%\n"
        f"%%MEM:trait|Tom|trait|manque de confiance en lui||identite|2|permanent%%\n\n"
        f"Utilisateur : 'Ma sœur s'appelle Claire. Son mari c'est Paul.'\n"
        f"%%MEM:relation|{user_name}|soeur|Claire||identite|1|permanent%%\n"
        f"%%MEM:relation|Claire|conjoint|Paul||identite|1|permanent%%\n\n"
        f"Échanges récents :\n"
        f"{context_block}\n"
    )

# ══════════════════════════════════════════════════════════
# APPEL API DEEPSEEK
# ══════════════════════════════════════════════════════════

def appel_deepseek(prompt: str, api_key: str, model: str) -> tuple:
    model = model or "deepseek-chat"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    body = {
        "model":       model,
        "max_tokens":  MAX_TOKENS_EXTRACTION,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": "Tu es un extracteur de faits. Tu ne produis que des tags %%MEM%%, rien d'autre."},
            {"role": "user",   "content": prompt},
        ],
    }
    r = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=body, timeout=30)
    r.raise_for_status()
    data    = r.json()
    choice  = data["choices"][0]
    texte   = choice["message"]["content"]
    tokens  = data.get("usage", {}).get("completion_tokens", "?")
    tronque = choice.get("finish_reason") == "length"
    return texte, tokens, tronque

# ══════════════════════════════════════════════════════════
# PARSING + FILTRES (miroir de memory.py / save_inline_memory)
# ══════════════════════════════════════════════════════════

_SUJETS_BLOQUES = {
    'nimm', 'assistant', 'ia', 'bot', 'pere', 'mere', 'fils', 'fille',
    'enfant', 'collegue', 'voisin', 'medecin', 'ami', 'amie', 'chef', 'patron'
}
_VALEURS_CREUSES = {
    '', 'oui', 'non', 'non specifie', 'non_specifie', 'inconnu',
    'aucun', 'aucune', 'n/a', 'na', '?', 'vide', 'unknown',
    'non precise', 'non_precise', 'pas precise',
}

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

def parser_tags(texte: str) -> list:
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
            records.append({'_erreur': f"{len(parts)} champs (attendu 7 ou 8)", '_raw': raw})
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
    if '_erreur' in record:
        return False, f"Format invalide : {record['_erreur']}"
    sujet    = record.get('sujet', '').strip()
    objet    = record.get('objet', '').strip().lower()
    predicat = record.get('predicat', '')
    if objet in _VALEURS_CREUSES:
        return False, f"Valeur creuse : '{objet}'"
    if not _is_prenom_local(sujet) or sujet.lower() in _SUJETS_BLOQUES:
        return False, f"Sujet rejeté : '{sujet}'"
    if not predicat.strip():
        return False, "Prédicat vide"
    return True, "✅ Accepté"

# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

# Faits attendus par message — pour mesurer le taux de capture
ATTENDUS = {
    1:  ["Laurent/date_naissance", "Laurent/nationalite", "Laurent/prenom_pere", "Laurent/prenom_mere"],
    2:  ["Laurent/metier", "Laurent/diplome", "Laurent/anciennete_debut"],
    3:  ["Laurent/loisir(livres audio)", "Laurent/loisir(Footballia)"],
    4:  ["Laurent/conjoint(Nadia)", "Laurent/domicile(Colmar)"],
    5:  ["Nadia/date_naissance", "Nadia/nationalite ou culture_origine", "Nadia/metier"],
    6:  ["Nadia/sport", "Nadia/bénévolat ou engagement"],
    7:  ["Innès/age", "Innès/date_naissance", "Innès/domicile(Nancy)", "Innès/etudes"],
    8:  ["Maïssane/age", "Maïssane/date_naissance", "Maïssane/ecole", "Maïssane/sport(grade)",
         "Maya/age", "Maya/date_naissance", "Maya/ecole", "Maya/sport"],
    9:  ["Laurent/soeur(Hélène)", "Hélène/conjoint(Nando)"],
    10: ["Laurent/valeur(indépendance)"],
}

def main():
    provider, api_key, model = charger_config()

    _titre(f"NIMM — DIAGNOSTIC EXTRACTION FAMILLE ({provider.upper()} / {model})")
    print(f"  DB       : {os.path.abspath(DB_PATH)}")
    print(f"  max_tokens : {MAX_TOKENS_EXTRACTION}")
    print(f"  Messages : {len(MESSAGES)}")
    print(f"  Début    : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    _sep()
    print(f"🔑 Clé chargée : {api_key[:8]}{'*' * (len(api_key) - 8)}")

    resultats = []

    for msg in MESSAGES:
        _sep("─")
        print(f"\n📨 Message #{msg['id']} — {msg['label']}")
        print(f"   USER : « {msg['user'][:120]}{'...' if len(msg['user']) > 120 else ''} »")

        prompt = build_prompt(msg['user'], msg['assistant'])

        try:
            rep, tok, tronc = appel_deepseek(prompt, api_key, model)
        except Exception as e:
            print(f"   ❌ Erreur API : {e}")
            rep, tok, tronc = "", "ERR", False

        time.sleep(DELAI)

        print(f"\n   ┌─ Réponse brute ──────────────────────────────────")
        if rep.strip():
            for ligne in rep.strip().splitlines():
                print(f"   │  {ligne}")
        else:
            print(f"   │  (vide)")
        tronc_label = "⚠️ TRONQUÉ" if tronc else "ok"
        print(f"   └─ tokens : {tok} | fin : {tronc_label}")

        records  = parser_tags(rep)
        acceptes = []

        print(f"\n   ── Simulation pipeline ──")
        if not records:
            print(f"   ⭕ Aucun tag %%MEM%% produit")
        for r in records:
            ok, raison = simuler_filtres(r)
            if '_erreur' in r:
                print(f"   ❌ Parsing : {raison}  (raw: {r.get('_raw','')})")
            elif ok:
                print(f"   ✅ {r['sujet']} / {r['predicat']} = {r['objet']}  [{r['type_temporal']}]")
                acceptes.append(r)
            else:
                print(f"   🚫 {r.get('sujet','?')} / {r.get('predicat','?')} = {r.get('objet','?')}  → REJETÉ : {raison}")

        # Faits attendus pour ce message
        attendus = ATTENDUS.get(msg['id'], [])
        if attendus:
            print(f"\n   ── Faits attendus ({len(attendus)}) ──")
            for fa in attendus:
                print(f"   ·  {fa}")

        resultats.append({
            'id':       msg['id'],
            'label':    msg['label'],
            'tags':     acceptes,
            'tronque':  tronc,
            'vide':     not rep.strip(),
            'attendus': len(attendus),
        })

    # ── Rapport final ──────────────────────────────────────
    _titre("RAPPORT FINAL")
    col_w = 44
    print(f"  {'#':<3} {'Label':<{col_w}} {'Tags OK':>7}  {'Attendus':>8}  {'Tronc':>5}")
    _sep("·", 72)

    total_ok  = 0
    total_att = 0
    for r in resultats:
        n   = len(r['tags'])
        att = r['attendus']
        t   = "⚠️ " if r['tronque'] else "—"
        val = "(vide)" if r['vide'] else f"{n} tag(s)"
        total_ok  += n
        total_att += att
        print(f"  {r['id']:<3} {r['label'][:col_w]:<{col_w}} {val:>9}  {att:>8}  {t:>5}")

    _sep("═")
    print(f"\n  Total triplets acceptés : {total_ok}")
    print(f"  Total faits attendus    : {total_att}")
    print(f"  Fin : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"  📝 Ce script n'a écrit aucune donnée en base.")
    print()

if __name__ == "__main__":
    main()
