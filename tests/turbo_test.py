# ============================================================
# NIMM — turbo_test.py
# Test de la vraie route d'extraction mémoire v2 (JSON)
#
# Simule EXACTEMENT ce que fait hub.extract_memories_from_window :
#   - Charge data/prompts/memoire_<provider>.txt
#   - Injecte {{USER_NAME}} {{DATE}} {{LOCATION}} {{CONV_TEXT}}
#   - Appelle l'API du provider
#   - Parse le JSON retourné
#   - Compare aux faits attendus
#
# Ce script NE modifie PAS la base de données.
# NIMM n'a PAS besoin de tourner.
#
# Usage (depuis le dossier racine de NIMM) :
#   python turbo_test.py
#   python turbo_test.py deepseek
#   python turbo_test.py anthropic
#   python turbo_test.py mistral
# ============================================================

import sqlite3
import json
import re
import os
import sys
import time
import requests
from datetime import datetime

# ── Chemins ───────────────────────────────────────────────────
_HERE       = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(_HERE, 'data', 'nimm_laurent.db')
PROMPTS_DIR = os.path.join(_HERE, 'data', 'prompts')

# ── Paramètres ────────────────────────────────────────────────
MAX_TOKENS  = 1500
USER_NAME   = "Laurent"
LOCATION    = "Ferrals-les-Corbières, France"

# Délai entre appels selon provider (secondes)
DELAI_DEFAUT = 2
DELAI_MISTRAL = 35   # 2 req/min max

# ══════════════════════════════════════════════════════════════
# 10 MESSAGES — famille complète, ordre conversationnel
# ══════════════════════════════════════════════════════════════
MESSAGES = [
    {
        "id": 1,
        "label": "Laurent — identité + parents",
        "user": "Je suis né le 5 juillet 1980. Je suis français. Mon père s'appelle Jean, ma mère Jeannette.",
        "assistant": "Noté. Tu as des frères et sœurs ?",
        "attendus": ["Laurent/date_naissance", "Laurent/nationalite", "Laurent/prenom_pere", "Laurent/prenom_mere"],
    },
    {
        "id": 2,
        "label": "Laurent — métier + formation",
        "user": "Je suis chauffeur poids lourd. J'ai un BEP Conduite et Services dans le transport routier, que j'ai passé entre 1995 et 1997. Je préfère le transport régional.",
        "assistant": "Tu travailles depuis combien de temps dans le transport ?",
        "attendus": ["Laurent/metier", "Laurent/diplome", "Laurent/anciennete_debut"],
    },
    {
        "id": 3,
        "label": "Laurent — loisirs",
        "user": "Pendant mes trajets en camion j'écoute des livres audio. Le soir je regarde des matchs sur Footballia.",
        "assistant": "Tu as une équipe préférée ou c'est plutôt les matchs anciens que tu regardes ?",
        "attendus": ["Laurent/loisir(livres audio)", "Laurent/loisir(Footballia)"],
    },
    {
        "id": 4,
        "label": "Laurent + Nadia — couple + domicile",
        "user": "Je vis avec ma femme Nadia à Colmar. On est 5 dans la maison.",
        "assistant": "Vous êtes installés à Colmar depuis longtemps ?",
        "attendus": ["Laurent/conjoint(Nadia)", "Laurent/domicile(Colmar)"],
    },
    {
        "id": 5,
        "label": "Nadia — identité + profession",
        "user": "Nadia est née le 18 juin 1983 à Guelma, en Algérie. Elle est arrivée en France à 18 ans. Elle est micro-entrepreneuse, elle tient un atelier de couture à domicile qui s'appelle LIMM Couture et Créations.",
        "assistant": "Elle reçoit des clients chez elle ?",
        "attendus": ["Nadia/date_naissance", "Nadia/origine(Algérie)", "Nadia/metier"],
    },
    {
        "id": 6,
        "label": "Nadia — loisir + bénévolat",
        "user": "Nadia fait de la course à pied. Elle est aussi secrétaire bénévole au club Colmar Judo.",
        "assistant": "C'est elle qui a amené les filles au judo ?",
        "attendus": ["Nadia/sport(course)", "Nadia/bénévolat(judo)"],
    },
    {
        "id": 7,
        "label": "Innès — identité + études",
        "user": "Notre fille aînée s'appelle Innès, elle a 22 ans, elle est née le 24 mars 2004. Elle est partie faire ses études à Nancy, elle est en Master 1 Droit de la santé à l'Université de Nancy.",
        "assistant": "Elle rentre souvent à Colmar ?",
        "attendus": ["Innès/age", "Innès/date_naissance", "Innès/domicile(Nancy)", "Innès/etudes"],
    },
    {
        "id": 8,
        "label": "Maïssane + Maya — identité + judo",
        "user": "La deuxième c'est Maïssane, 18 ans, née le 15 novembre 2008. Elle est en Terminale au lycée Bartholdi à Colmar. La petite c'est Maya, 12 ans, née le 19 août 2014, elle est en 6ème au collège Victor Hugo. Toutes les deux font du judo. Maïssane est ceinture marron.",
        "assistant": "Elles sont dans le même club que la maman suit en tant que secrétaire ?",
        "attendus": [
            "Maïssane/age", "Maïssane/date_naissance", "Maïssane/ecole", "Maïssane/sport(grade marron)",
            "Maya/age", "Maya/date_naissance", "Maya/ecole", "Maya/sport(judo)",
        ],
    },
    {
        "id": 9,
        "label": "Hélène + Nando — fratrie + beau-frère",
        "user": "J'ai une sœur qui s'appelle Hélène. Son mari c'est Nando.",
        "assistant": "Tu vois souvent Hélène et Nando ?",
        "attendus": ["Laurent/soeur(Hélène)", "Hélène/conjoint(Nando)"],
    },
    {
        "id": 10,
        "label": "Laurent — valeur + trait de caractère",
        "user": "J'accorde beaucoup d'importance à mon indépendance. C'est quelque chose de fondamental pour moi.",
        "assistant": "Ça se retrouve dans ton choix de métier aussi, je suppose.",
        "attendus": ["Laurent/valeur(indépendance)"],
    },
]

# ══════════════════════════════════════════════════════════════
# HELPERS AFFICHAGE
# ══════════════════════════════════════════════════════════════

def _sep(char="─", n=68):
    print(char * n)

def _titre(texte):
    _sep("═")
    print(f"  {texte}")
    _sep("═")

# ══════════════════════════════════════════════════════════════
# CHARGEMENT CONFIG (DB)
# ══════════════════════════════════════════════════════════════

_PROVIDER_DEFAULT_MODEL = {
    'anthropic': 'claude-haiku-4-5-20251001',
    'deepseek':  'deepseek-chat',
    'mistral':   'mistral-medium-latest',
    'gemini':    'gemini-1.5-flash',
    'ollama':    'llama3.1:8b',
}

_MODEL_OWNER_PREFIX = {
    'claude':     'anthropic',
    'deepseek':   'deepseek',
    'mistral':    'mistral',
    'ministral':  'mistral',
    'gemini':     'gemini',
    'gpt':        'openai',
    'llama':      'ollama',
}

def _model_compatible(provider: str, model: str) -> bool:
    """Vérifie que le modèle en DB appartient bien au provider demandé."""
    if not model:
        return False
    m = model.lower()
    for prefix, owner in _MODEL_OWNER_PREFIX.items():
        if m.startswith(prefix):
            return owner == provider
    return True  # inconnu → on laisse passer

def charger_config(provider_force=None) -> tuple:
    if not os.path.exists(DB_PATH):
        print(f"❌ DB introuvable : {os.path.abspath(DB_PATH)}")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    cur.execute("SELECT value FROM settings WHERE key = 'provider' LIMIT 1")
    row = cur.fetchone()
    provider = (provider_force or (row[0].strip().lower() if row else 'deepseek'))

    cur.execute("SELECT value FROM settings WHERE key = 'chat_model' LIMIT 1")
    row = cur.fetchone()
    model_db = row[0].strip() if row and row[0] else None

    # Si le modèle en DB ne correspond pas au provider → on prend le défaut du provider
    if _model_compatible(provider, model_db):
        model = model_db
    else:
        model = _PROVIDER_DEFAULT_MODEL.get(provider)
        print(f"  ⚠️  Modèle DB '{model_db}' incompatible avec {provider} → utilisation de '{model}'")

    cur.execute("SELECT value FROM settings WHERE key = 'api_keys' LIMIT 1")
    row = cur.fetchone()
    conn.close()

    if not row:
        print("❌ Clé 'api_keys' absente dans settings.")
        sys.exit(1)
    try:
        keys    = json.loads(row[0])
        api_key = keys.get(provider, '')
        if not api_key:
            print(f"❌ Clé '{provider}' vide dans api_keys.")
            sys.exit(1)
        return provider, api_key, model
    except Exception as e:
        print(f"❌ Impossible de parser api_keys : {e}")
        sys.exit(1)

# ══════════════════════════════════════════════════════════════
# CHARGEMENT PROMPT (miroir de hub._load_memoire_prompt_template)
# ══════════════════════════════════════════════════════════════

def _model_slug(model: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', (model or '').lower()).strip('_')

def charger_prompt_template(provider: str, model: str = None) -> tuple:
    """
    Même logique que hub._load_memoire_prompt_template.
    Retourne (template, nom_fichier_chargé).
    """
    slug = _model_slug(model)
    candidates = []
    if slug:
        candidates.append(f'memoire_{provider}_{slug}.txt')
    candidates.append(f'memoire_{provider}.txt')
    candidates.append('memoire_default.txt')

    for fname in candidates:
        path = os.path.join(PROMPTS_DIR, fname)
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read(), fname
            except Exception as e:
                print(f"⚠️  Lecture {fname} impossible : {e}")

    # Repli minimal (identique au fallback de hub.py)
    fallback = (
        "Voici une conversation. La personne qui parle s'appelle {{USER_NAME}}.\n\n"
        "{{CONV_TEXT}}\n\n"
        "Extrais les faits mémorisables sur {{USER_NAME}} sous forme de tableau JSON "
        "d'objets {\"registre\":\"neutre\",\"type\":\"trait\",\"sujet\":\"...\",\"predicat\":\"...\","
        "\"objet\":\"...\",\"memoire_type\":\"autre\",\"profondeur\":3,\"type_temporal\":\"persistant\","
        "\"contexte\":\"\"}. Si aucun fait : réponds [].\n"
        "Réponds UNIQUEMENT avec le tableau JSON."
    )
    return fallback, "(fallback intégré)"

def forger_prompt(template: str, user_msg: str, assistant_msg: str) -> str:
    """Injecte les variables exactement comme hub.extract_memories_from_window."""
    conv_text = f"Utilisateur : {user_msg}\nAssistant : {assistant_msg[:600]}"
    date_str  = datetime.now().strftime('%d/%m/%Y')
    return (
        template
        .replace('{{USER_NAME}}', USER_NAME)
        .replace('{{DATE}}',      date_str)
        .replace('{{LOCATION}}',  LOCATION)
        .replace('{{CONV_TEXT}}', conv_text)
    )

# ══════════════════════════════════════════════════════════════
# APPELS API
# ══════════════════════════════════════════════════════════════

def appel_deepseek(prompt: str, api_key: str, model: str) -> tuple:
    model = model or 'deepseek-chat'
    r = requests.post(
        'https://api.deepseek.com/chat/completions',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json={
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': MAX_TOKENS,
            'temperature': 0.1,
        },
        timeout=60,
    )
    r.raise_for_status()
    data    = r.json()
    choice  = data['choices'][0]
    texte   = choice['message']['content']
    tokens  = data.get('usage', {}).get('completion_tokens', '?')
    tronque = choice.get('finish_reason') == 'length'
    return texte, tokens, tronque

def appel_anthropic(prompt: str, api_key: str, model: str) -> tuple:
    model = model or 'claude-haiku-4-5-20251001'
    r = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers={
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json',
        },
        json={
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': MAX_TOKENS,
            'temperature': 0.1,
        },
        timeout=60,
    )
    r.raise_for_status()
    data    = r.json()
    texte   = data['content'][0]['text']
    tokens  = data.get('usage', {}).get('output_tokens', '?')
    tronque = data.get('stop_reason') == 'max_tokens'
    return texte, tokens, tronque

def appel_gemini(prompt: str, api_key: str, model: str) -> tuple:
    model = model or 'gemini-1.5-flash'
    import urllib.request, urllib.error
    payload = json.dumps({
        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
        'generationConfig': {'maxOutputTokens': MAX_TOKENS, 'temperature': 0.1},
    }).encode('utf-8')
    req = urllib.request.Request(
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    parts    = (data.get('candidates') or [{}])[0].get('content', {}).get('parts', []) or []
    texte    = ''.join(p.get('text', '') for p in parts if 'text' in p)
    meta     = data.get('usageMetadata', {})
    tokens   = meta.get('candidatesTokenCount', '?')
    tronque  = (data.get('candidates') or [{}])[0].get('finishReason') == 'MAX_TOKENS'
    return texte, tokens, tronque

def appel_mistral(prompt: str, api_key: str, model: str) -> tuple:
    model = model or 'mistral-small-latest'
    r = requests.post(
        'https://api.mistral.ai/v1/chat/completions',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json={
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': MAX_TOKENS,
            'temperature': 0.1,
        },
        timeout=60,
    )
    r.raise_for_status()
    data    = r.json()
    choice  = data['choices'][0]
    texte   = choice['message']['content']
    tokens  = data.get('usage', {}).get('completion_tokens', '?')
    tronque = choice.get('finish_reason') == 'length'
    return texte, tokens, tronque

def appel_api(provider: str, prompt: str, api_key: str, model: str) -> tuple:
    if provider == 'anthropic':
        return appel_anthropic(prompt, api_key, model)
    elif provider == 'mistral':
        return appel_mistral(prompt, api_key, model)
    elif provider == 'gemini':
        return appel_gemini(prompt, api_key, model)
    else:
        return appel_deepseek(prompt, api_key, model)

# ══════════════════════════════════════════════════════════════
# PARSE JSON (miroir de hub._parse_llm_json)
# ══════════════════════════════════════════════════════════════

def parse_json(raw: str) -> list:
    cleaned = re.sub(r'```(?:json)?\s*', '', raw).replace('```', '').strip()

    # Tentative 1 : un seul tableau JSON valide
    match = re.search(r'\[.*\]', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Tentative 2 : plusieurs tableaux séparés (comportement Mistral Small)
    # On extrait tous les tableaux et on les fusionne
    resultats = []
    for m in re.finditer(r'\[.*?\]', cleaned, re.DOTALL):
        try:
            items = json.loads(m.group())
            if isinstance(items, list):
                resultats.extend(items)
        except json.JSONDecodeError:
            pass
    if resultats:
        return resultats

    # Tentative 3 : objets JSON individuels non encadrés
    resultats = []
    for m in re.finditer(r'\{[^{}]+\}', cleaned, re.DOTALL):
        try:
            obj = json.loads(m.group())
            if isinstance(obj, dict) and 'sujet' in obj:
                resultats.append(obj)
        except json.JSONDecodeError:
            pass
    if resultats:
        return resultats

    print(f"   ⚠️  Impossible de parser le JSON")
    return []

# ══════════════════════════════════════════════════════════════
# VÉRIFICATION FAITS ATTENDUS
# ══════════════════════════════════════════════════════════════

_ACCENTS = [
    ("é","e"),("è","e"),("ê","e"),("ë","e"),
    ("à","a"),("â","a"),("î","i"),("ï","i"),
    ("ô","o"),("û","u"),("ù","u"),("ü","u"),
    ("ç","c"),("œ","oe"),("æ","ae"),
]

def _norm(s: str) -> str:
    s = s.lower()
    for a, b in _ACCENTS:
        s = s.replace(a, b)
    return s

def verifier_fait(items: list, attendu_label: str) -> tuple:
    """
    Vérifie si un fait attendu (format "Sujet/predicat(valeur_optionnelle)")
    est présent dans la liste JSON retournée par le LLM.
    Recherche souple : le mot-clé doit apparaître dans sujet, prédicat ou objet.
    Retourne (trouvé, item_correspondant_ou_None).
    """
    # Parse le label attendu
    match = re.match(r'^([^/]+)/([^(]+)(?:\((.+)\))?$', attendu_label)
    if not match:
        return False, None
    sujet_att, pred_att, val_att = match.group(1), match.group(2), match.group(3)

    for item in items:
        sujet  = _norm(item.get('sujet',    '') or '')
        pred   = _norm(item.get('predicat', '') or '')
        objet  = _norm(item.get('objet',    '') or '')
        valeur = _norm(item.get('valeur',   '') or '')
        tout   = f"{sujet} {pred} {objet} {valeur}"

        # Le sujet attendu doit être présent
        if _norm(sujet_att) not in sujet:
            continue
        # Le prédicat attendu doit être présent (dans prédicat ou champ tout)
        if _norm(pred_att) not in tout:
            continue
        # La valeur optionnelle doit être présente si précisée
        if val_att and _norm(val_att) not in tout:
            continue
        return True, item

    return False, None

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    provider_force = sys.argv[1].lower() if len(sys.argv) > 1 else None
    provider, api_key, model = charger_config(provider_force)

    delai = DELAI_MISTRAL if provider == 'mistral' else DELAI_DEFAUT

    # Charger le prompt template
    template, fname_prompt = charger_prompt_template(provider, model)

    _titre(f"NIMM — TURBO TEST EXTRACTION v2 ({provider.upper()})")
    print(f"  DB       : {os.path.abspath(DB_PATH)}")
    print(f"  Provider : {provider}  |  Modèle : {model or '(défaut provider)'}")
    print(f"  Prompt   : {fname_prompt}")
    print(f"  Location : {LOCATION}")
    print(f"  Délai    : {delai}s entre appels")
    print(f"  Début    : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    _sep()
    print(f"🔑 Clé chargée : {api_key[:8]}{'*' * max(0, len(api_key) - 8)}")
    _sep()

    resultats = []
    total_items_bruts = 0

    for msg in MESSAGES:
        print(f"\n📨 Message #{msg['id']} — {msg['label']}")
        print(f"   USER : « {msg['user'][:110]}{'...' if len(msg['user']) > 110 else ''} »")

        prompt = forger_prompt(template, msg['user'], msg['assistant'])

        try:
            rep, tok, tronc = appel_api(provider, prompt, api_key, model)
        except Exception as e:
            print(f"   ❌ Erreur API : {e}")
            resultats.append({
                'id': msg['id'], 'label': msg['label'],
                'items': [], 'attendus': msg['attendus'],
                'captures': [], 'manques': msg['attendus'],
                'tronque': False, 'erreur': True,
            })
            continue

        if provider == 'mistral':
            print(f"   ⏳ Pause Mistral {delai}s...")
        time.sleep(delai)

        tronc_label = "⚠️ TRONQUÉ" if tronc else "ok"
        print(f"   └─ tokens : {tok} | fin : {tronc_label}")

        # Parse JSON
        items = parse_json(rep)
        total_items_bruts += len(items)

        if not items:
            print(f"   ⭕ Aucun item JSON extrait")
            if rep.strip():
                print(f"   ┌─ Réponse brute ──")
                for ligne in rep.strip().splitlines()[:5]:
                    print(f"   │  {ligne}")
                print(f"   └──")
        else:
            print(f"   ✅ {len(items)} item(s) JSON extrait(s) :")
            for it in items:
                sujet  = it.get('sujet',    '?')
                pred   = it.get('predicat', '?')
                objet  = it.get('objet',    it.get('valeur', '?'))
                reg    = it.get('registre', '?')
                tmp    = it.get('type_temporal', '?')
                print(f"      • {sujet} / {pred} = {objet}  [{reg}|{tmp}]")

        # Vérification faits attendus
        captures = []
        manques  = []
        print(f"\n   ── Faits attendus ({len(msg['attendus'])}) ──")
        for att in msg['attendus']:
            found, item = verifier_fait(items, att)
            if found:
                pred_cap = item.get('predicat', '?')
                obj_cap  = item.get('objet', item.get('valeur', '?'))
                print(f"   ✅ {att}  → [{pred_cap}]={obj_cap}")
                captures.append(att)
            else:
                print(f"   ❌ {att}  → non capturé")
                manques.append(att)

        resultats.append({
            'id':       msg['id'],
            'label':    msg['label'],
            'items':    items,
            'attendus': msg['attendus'],
            'captures': captures,
            'manques':  manques,
            'tronque':  tronc,
            'erreur':   False,
        })

        _sep("·", 68)

    # ── Rapport final ─────────────────────────────────────────
    _titre("RAPPORT FINAL")

    col_w = 40
    print(f"  {'#':<3} {'Label':<{col_w}} {'Capturés':>9}  {'Manqués':>8}  {'Items':>6}")
    _sep("·", 68)

    total_cap = 0
    total_att = 0
    for r in resultats:
        n_cap = len(r['captures'])
        n_att = len(r['attendus'])
        n_it  = len(r['items'])
        total_cap += n_cap
        total_att += n_att
        flag  = " ⚠️" if r['tronque'] else ("  ❌ERR" if r['erreur'] else "")
        pct   = f"{int(100*n_cap/n_att)}%" if n_att else "—"
        print(f"  {r['id']:<3} {r['label'][:col_w]:<{col_w}} {n_cap}/{n_att} ({pct:>4}){'':<2} {len(r['manques']):>7}  {n_it:>6}{flag}")

    _sep("═")
    pct_total = int(100 * total_cap / total_att) if total_att else 0
    print(f"\n  Score global    : {total_cap}/{total_att} faits capturés ({pct_total}%)")
    print(f"  Items JSON bruts: {total_items_bruts} au total")

    # Faits manqués récapitulatif
    tous_manques = [(r['id'], m) for r in resultats for m in r['manques']]
    if tous_manques:
        print(f"\n  ── Faits NON capturés ──")
        for mid, m in tous_manques:
            print(f"     #{mid} → {m}")

    print(f"\n  Fin : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"  📝 Ce script n'a écrit aucune donnée en base.\n")


if __name__ == "__main__":
    main()
