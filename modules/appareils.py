# -*- coding: utf-8 -*-
"""Mes appareils — les modes d'emploi de la maison, archivés et interrogeables.

« Comment on règle l'heure sur le four ? », « que veut dire le voyant qui
clignote sur le lave-linge ? » : la réponse est dans un PDF de 80 pages qu'on
ne retrouve jamais, et souvent dans un SCHÉMA — illisible quand on ne voit pas.

Ce module :
  1. ARCHIVE un manuel par appareil (nom, marque, modèle, pièce) : le PDF
     d'origine est CONSERVÉ (data/appareils/, ignoré par git) — c'est là que
     sont les schémas — et son texte est découpé PAR PAGE, pour qu'une réponse
     puisse dire « page 23 ».
  2. TROUVE le manuel en ligne si on le lui demande : recherche web, puis
     téléchargement vérifié. Un PDF n'est accepté que s'il mentionne bien la
     référence du modèle — un manuel du mauvais modèle donnerait des réglages
     faux avec aplomb. Beaucoup de sites de fabricants bloquent le
     téléchargement automatique : NIMM le DIT, et on fournit alors le fichier.
  3. RÉPOND à partir du seul corpus de la maison, pages citées ; ce que les
     manuels ne disent pas, il le dit au lieu de l'inventer.
  4. DÉCRIT LES SCHÉMAS À LA DEMANDE (choix de Fernando, 18/10/2026) : seules
     les pages concernées sont envoyées au modèle de vision (Claude, sinon
     Gemini), jamais le manuel entier.

Les manuels scannés (sans texte) restent utilisables : on peut demander à
voir une page précise par son numéro.
"""

import io
import os
import re
import unicodedata
from datetime import datetime

DOSSIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'appareils')
TAILLE_MAX = 60 * 1024 * 1024        # un manuel au-delà est refusé, et on le dit
PAGES_VISION_MAX = 4                 # pages envoyées au modèle de vision pour une question
_MOTS_VISUELS = ('schéma', 'schema', 'figure', 'illustration', 'dessin', 'image', 'photo',
                 'voyant', 'symbole', 'pictogramme', 'icône', 'icone', 'logo', 'où se trouve',
                 'ou se trouve', 'emplacement', 'à quoi ressemble', 'a quoi ressemble',
                 'repère', 'repere', 'flèche', 'fleche', 'décris la page', 'decris la page')


# ── Normalisation ─────────────────────────────────────────────────────────

def sans_accents(s: str) -> str:
    s = unicodedata.normalize('NFD', str(s or ''))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').lower()


def ref_compacte(s: str) -> str:
    """« WAN-28 2H8 FF » et « wan282h8ff » sont la même référence."""
    return re.sub(r'[^a-z0-9]', '', sans_accents(s))


_MOTS_VIDES = {'comment', 'quoi', 'quel', 'quelle', 'quels', 'quelles', 'est', 'les', 'des',
               'une', 'pour', 'sur', 'dans', 'avec', 'mon', 'mes', 'ma', 'son', 'que', 'qui',
               'faire', 'fait', 'peut', 'veut', 'dire', 'faut', 'the', 'and'}


def _racine(mot: str) -> str:
    """Racine grossière : les 4 premières lettres (« regl » pour régler / réglage)."""
    return mot[:4]


def demande_visuelle(question: str) -> bool:
    q = sans_accents(question)
    return any(sans_accents(m) in q for m in _MOTS_VISUELS)


# ── Conservation ──────────────────────────────────────────────────────────

def _conn():
    from core.database import get_conn
    conn = get_conn()
    conn.execute('''CREATE TABLE IF NOT EXISTS appareil (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT NOT NULL, nom_norm TEXT NOT NULL,
        marque TEXT, modele TEXT, piece TEXT, fichier TEXT, source TEXT,
        nb_pages INTEGER, pages_texte INTEGER, ajoute_le TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS appareil_passage (
        id INTEGER PRIMARY KEY AUTOINCREMENT, appareil_id INTEGER NOT NULL,
        page INTEGER, contenu TEXT NOT NULL, embedding TEXT)''')
    return conn


def lister() -> list:
    conn = _conn()
    rows = conn.execute('SELECT id, nom, marque, modele, piece, nb_pages, pages_texte, source, '
                        'ajoute_le, fichier FROM appareil ORDER BY piece, nom').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def trouver(designation: str) -> list:
    """Appareils correspondant à une désignation libre (« le four », « Bosch », « cuisine »)."""
    cible = sans_accents(designation).strip()
    cible = re.sub(r"^(le |la |les |l'|mon |ma |mes )", '', cible)
    if not cible:
        return []
    tous = lister()
    exacts = [a for a in tous if sans_accents(a['nom']) == cible]
    if exacts:
        return exacts
    rc = ref_compacte(cible)
    sortie = []
    for a in tous:
        champs = ' '.join(sans_accents(a.get(c) or '') for c in ('nom', 'marque', 'modele', 'piece'))
        if cible in champs or (len(rc) >= 4 and rc in ref_compacte(a.get('modele') or '')):
            sortie.append(a)
    return sortie


def extraire_pages(pdf_bytes: bytes) -> list:
    """Texte de chaque page (liste, page 1 en tête). Une page sans texte rend ''."""
    from pypdf import PdfReader
    lecteur = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for p in lecteur.pages:
        try:
            pages.append((p.extract_text() or '').strip())
        except Exception:
            pages.append('')
    return pages


def _decouper_page(texte: str, cible: int = 1000) -> list:
    from modules.enrichissement import _chunk_text
    return _chunk_text(texte, target=cible, overlap=120) if texte else []


def ajouter(nom: str, pdf_bytes: bytes, marque: str = '', modele: str = '',
            piece: str = '', source: str = '') -> dict:
    """Archive un manuel. Un appareil du même nom est REMPLACÉ (nouvelle notice).

    Rend {id, nom, nb_pages, pages_texte, avertissements}. Lève ValueError si
    le fichier n'est pas un PDF exploitable.
    """
    nom = (nom or '').strip() or ('%s %s' % (marque, modele)).strip() or 'appareil'
    if not pdf_bytes or not pdf_bytes[:1024].lstrip().startswith(b'%PDF'):
        raise ValueError("ce fichier n'est pas un PDF")
    if len(pdf_bytes) > TAILLE_MAX:
        raise ValueError('PDF trop volumineux (plus de %d Mo)' % (TAILLE_MAX // (1024 * 1024)))
    pages = extraire_pages(pdf_bytes)
    if not pages:
        raise ValueError('PDF sans aucune page lisible')
    avert = []
    pages_texte = sum(1 for p in pages if len(p) >= 40)
    if pages_texte == 0:
        avert.append("Ce manuel est scanné (aucun texte lisible) : la recherche par mots n'y "
                     "trouvera rien, mais on peut demander à voir une page précise par son numéro.")
    elif pages_texte < len(pages) // 2:
        avert.append("Plus de la moitié des pages n'ont pas de texte lisible (schémas ou pages "
                     "scannées) : elles restent consultables par leur numéro.")
    if modele and pages_texte and ref_compacte(modele) not in ref_compacte(' '.join(pages)):
        avert.append("La référence « %s » n'apparaît nulle part dans ce manuel : vérifie qu'il "
                     "s'agit bien du bon modèle." % modele)

    os.makedirs(DOSSIER, exist_ok=True)
    conn = _conn()
    anciens = conn.execute('SELECT id, fichier FROM appareil WHERE nom_norm = ?',
                           (sans_accents(nom),)).fetchall()
    for a in anciens:
        conn.execute('DELETE FROM appareil_passage WHERE appareil_id = ?', (a['id'],))
        conn.execute('DELETE FROM appareil WHERE id = ?', (a['id'],))
        _effacer_fichier(a['fichier'])
    cur = conn.execute(
        'INSERT INTO appareil (nom, nom_norm, marque, modele, piece, source, nb_pages, '
        'pages_texte, ajoute_le) VALUES (?,?,?,?,?,?,?,?,?)',
        (nom, sans_accents(nom), marque, modele, piece, source, len(pages), pages_texte,
         datetime.now().isoformat(timespec='seconds')))
    aid = cur.lastrowid
    fichier = '%d_%s.pdf' % (aid, re.sub(r'[^a-z0-9]+', '_', sans_accents(nom)).strip('_')[:40])
    with open(os.path.join(DOSSIER, fichier), 'wb') as f:
        f.write(pdf_bytes)
    conn.execute('UPDATE appareil SET fichier = ? WHERE id = ?', (fichier, aid))
    from modules.enrichissement import _embedding_for
    entete = ' — '.join(x for x in (nom, marque, modele) if x)
    for num, texte in enumerate(pages, 1):
        for morceau in _decouper_page(texte):
            conn.execute('INSERT INTO appareil_passage (appareil_id, page, contenu, embedding) '
                         'VALUES (?,?,?,?)', (aid, num, morceau, _embedding_for(entete + '\n' + morceau)))
    conn.commit()
    conn.close()
    return {'id': aid, 'nom': nom, 'nb_pages': len(pages), 'pages_texte': pages_texte,
            'avertissements': avert, 'remplace': bool(anciens)}


def _effacer_fichier(fichier):
    if not fichier:
        return
    try:
        os.remove(os.path.join(DOSSIER, os.path.basename(fichier)))
    except OSError:
        pass


def retirer(appareil_id: int) -> bool:
    conn = _conn()
    row = conn.execute('SELECT fichier FROM appareil WHERE id = ?', (appareil_id,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute('DELETE FROM appareil_passage WHERE appareil_id = ?', (appareil_id,))
    conn.execute('DELETE FROM appareil WHERE id = ?', (appareil_id,))
    conn.commit()
    conn.close()
    _effacer_fichier(row['fichier'])
    return True


def chemin_pdf(appareil: dict) -> str:
    return os.path.join(DOSSIER, os.path.basename(appareil.get('fichier') or ''))


# ── Recherche ─────────────────────────────────────────────────────────────

def rechercher(question: str, appareils_ids=None, k: int = 6) -> list:
    """Passages les plus proches : {appareil_id, nom, page, passage, score}.

    Par le sens si les embeddings sont disponibles, sinon par mots-clés (accents
    et casse neutralisés) — la recherche marche donc aussi hors connexion.
    """
    conn = _conn()
    sql = ('SELECT p.appareil_id, p.page, p.contenu, p.embedding, a.nom FROM appareil_passage p '
           'JOIN appareil a ON a.id = p.appareil_id')
    params = ()
    if appareils_ids:
        sql += ' WHERE p.appareil_id IN (%s)' % ','.join('?' * len(appareils_ids))
        params = tuple(appareils_ids)
    lignes = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    if not lignes:
        return []
    try:
        from modules.memory import _embed, _parse_embedding, _cosine
        qv = _embed(question)
    except Exception:
        qv = None
    scores = []
    if qv is not None:
        for l in lignes:
            v, _m = _parse_embedding(l.get('embedding'))
            if v is not None:
                scores.append((float(_cosine(qv, v)), l))
    if not scores:
        # Repli mots-clés, par RACINES : « régler » doit retrouver « Réglage »,
        # « clignote » « clignotant ». Les mots vides ne comptent pas.
        racines = {_racine(m) for m in re.findall(r'\w+', sans_accents(question))
                   if len(m) > 2 and m not in _MOTS_VIDES}
        # Le nom de l'appareil (« four », « Bosch ») ne départage pas les pages
        # d'un même manuel : il désigne l'appareil, pas le sujet de la question.
        noms = {_racine(m) for l in lignes for m in re.findall(r'\w+', sans_accents(l['nom']))}
        racines = (racines - noms) or racines
        for l in lignes:
            mots_page = {_racine(m) for m in re.findall(r'\w+', sans_accents(l['contenu'])) if len(m) > 2}
            s = len(racines & mots_page)
            if s:
                scores.append((float(s), l))
    scores.sort(key=lambda x: x[0], reverse=True)
    return [{'appareil_id': l['appareil_id'], 'nom': l['nom'], 'page': l['page'],
             'passage': l['contenu'], 'score': round(s, 3)} for s, l in scores[:k]]


def pages_en_pdf(appareil: dict, pages: list) -> bytes:
    """Un PDF ne contenant QUE les pages demandées (numérotation du manuel, à partir de 1)."""
    from pypdf import PdfReader, PdfWriter
    lecteur = PdfReader(chemin_pdf(appareil))
    ecrivain = PdfWriter()
    for n in pages:
        if 1 <= n <= len(lecteur.pages):
            ecrivain.add_page(lecteur.pages[n - 1])
    tampon = io.BytesIO()
    ecrivain.write(tampon)
    return tampon.getvalue()


# ── Trouver le manuel en ligne ────────────────────────────────────────────

def telecharger_pdf(url: str) -> tuple:
    """(octets, '') ou (None, raison). Anti-SSRF : net_guard à chaque redirection."""
    from modules.net_guard import safe_request
    try:
        r = safe_request('GET', url, timeout=30, stream=True,
                         headers={'User-Agent': 'Mozilla/5.0 (NIMM; mode d\'emploi)'})
    except Exception as e:
        return None, 'inaccessible (%s)' % str(e)[:80]
    if r.status_code != 200:
        return None, 'refusé par le site (code %d)' % r.status_code
    octets = b''
    for bloc in r.iter_content(65536):
        octets += bloc
        if len(octets) > TAILLE_MAX:
            return None, 'trop volumineux'
    if not octets[:1024].lstrip().startswith(b'%PDF'):
        return None, "ce n'est pas un PDF (page web ou téléchargement bloqué)"
    return octets, ''


def liens_candidats(texte_resultats: str) -> list:
    """Liens d'une page de résultats, ceux qui ressemblent à un PDF de notice en tête."""
    liens = []
    for u in re.findall(r'https?://[^\s<>()"\'\]]+', texte_resultats or ''):
        u = u.rstrip('.,;:')
        if u not in liens:
            liens.append(u)

    def rang(u):
        b = sans_accents(u)
        return (0 if b.endswith('.pdf') or '.pdf?' in b else 1,
                0 if any(m in b for m in ('manual', 'notice', 'mode-d', 'mode_d', 'user', 'guide')) else 1)
    return sorted(liens, key=rang)


async def chercher_en_ligne(marque: str, modele: str, nom: str = '', essais_max: int = 6) -> tuple:
    """Rend (octets, url, journal). journal : ce qui a été essayé, à dire à l'utilisateur."""
    import asyncio
    from modules.websearch import search
    if not (modele or '').strip():
        return None, '', ['Sans référence de modèle, impossible de vérifier que la notice est la bonne.']
    journal = []
    requetes = ['%s %s notice mode d\'emploi pdf' % (marque, modele),
                '%s %s user manual pdf lang:any' % (marque, modele)]
    vus = set()
    loop = asyncio.get_running_loop()
    for q in requetes:
        try:
            res = await search(q.strip(), max_results=8, enrich=False)
        except Exception as e:
            journal.append('Recherche impossible : %s' % e)
            continue
        if res.startswith('⚠️'):
            journal.append(res)
            break
        for url in liens_candidats(res):
            if url in vus or len(vus) >= essais_max:
                continue
            vus.add(url)
            octets, raison = await loop.run_in_executor(None, telecharger_pdf, url)
            if octets is None:
                journal.append('%s : %s' % (url, raison))
                continue
            try:
                texte = ' '.join(extraire_pages(octets))
            except Exception:
                journal.append('%s : PDF illisible' % url)
                continue
            if ref_compacte(modele) not in ref_compacte(texte):
                journal.append('%s : PDF écarté, la référence %s n\'y figure pas' % (url, modele))
                continue
            return octets, url, journal
    return None, '', journal


# ── Répondre ──────────────────────────────────────────────────────────────

PROMPT_REPONSE = (
    "Tu réponds à une question pratique sur un appareil de la maison, à partir des seuls "
    "extraits de ses modes d'emploi fournis ci-dessous (chacun précédé de l'appareil et de "
    "la page). La personne est aveugle : elle utilise un lecteur d'écran.\n\n"
    "RÈGLES :\n"
    "1. Rien n'est deviné. Réponds uniquement avec ce que disent les extraits. Si la réponse "
    "n'y est pas, dis-le clairement et indique quelles pages en parlent peut-être.\n"
    "2. Cite la page de chaque information : « (page 23) ».\n"
    "3. Pour un réglage ou une manipulation : étapes numérotées, une action par étape, en "
    "nommant les boutons et commandes comme le manuel les nomme.\n"
    "4. Le manuel renvoie souvent à une figure (« voir fig. 3 », « bouton A ») : si la réponse "
    "en dépend, dis-le, et précise que la page peut être décrite sur demande.\n"
    "5. Sécurité : reprends tels quels les avertissements de sécurité des extraits concernés.\n"
)


async def repondre(question: str, passages: list, settings: dict) -> str:
    from core.engine import call_llm
    blocs = ['[%s — page %s]\n%s' % (p['nom'], p['page'], p['passage']) for p in passages]
    try:
        return await call_llm(
            messages=[{'role': 'user', 'content': 'Question : %s\n\nExtraits :\n\n%s'
                       % (question, '\n\n'.join(blocs))}],
            provider=settings.get('provider', ''), model=settings.get('model'),
            system_prompt=PROMPT_REPONSE, max_tokens=2500, temperature=0.0,
            api_keys=settings.get('api_keys', {}))
    except Exception as e:
        return '[Réponse impossible : %s]' % e


CONSIGNE_VISION = (
    "Ces pages viennent du mode d'emploi d'un appareil ménager. La personne qui pose la "
    "question est aveugle. Décris les schémas, figures, voyants et symboles utiles pour "
    "répondre : ce qu'ils montrent, où se trouve chaque élément (en haut à gauche, sous "
    "l'écran…), les repères (lettres, chiffres, flèches) et ce qu'ils désignent, en t'appuyant "
    "sur la légende. Indique le numéro de page de chaque description. N'invente rien : ce qui "
    "est illisible ou ambigu, dis-le. Question : ")


async def decrire_pages(pdf_bytes: bytes, question: str, api_keys: dict, pages=None) -> str:
    """Lecture VISUELLE des pages : Claude d'abord, Gemini sinon. Rend un texte ou un message clair.

    `pages` : les numéros RÉELS des pages envoyées, dans l'ordre. Le modèle ne voit
    qu'un extrait du manuel : sans cette indication, il numérote à partir de 1.
    """
    from core.engine import get_api_key, analyze_pdf_anthropic
    consigne = CONSIGNE_VISION + (question or 'décris ces pages.')
    if pages:
        consigne += ('\n\nLes pages envoyées sont, dans l\'ordre, les pages %s du manuel : '
                     'utilise CES numéros.' % ', '.join(str(p) for p in pages))
    if get_api_key('anthropic', api_keys):
        return await analyze_pdf_anthropic(pdf_bytes, consigne, api_keys=api_keys, max_tokens=3000)
    if get_api_key('gemini', api_keys):
        return await _decrire_gemini(pdf_bytes, consigne, api_keys)
    return ("[Description des schémas impossible : il faut une clé Anthropic ou Gemini "
            "(Paramètres, Connexions).]")


async def _decrire_gemini(pdf_bytes: bytes, consigne: str, api_keys: dict) -> str:
    import base64
    import httpx
    from core.engine import get_api_key, _resolve_model
    cle = get_api_key('gemini', api_keys)
    m = _resolve_model('gemini', None)
    charge = {'contents': [{'parts': [
        {'inline_data': {'mime_type': 'application/pdf',
                         'data': base64.standard_b64encode(pdf_bytes).decode()}},
        {'text': consigne}]}], 'generationConfig': {'maxOutputTokens': 3000}}
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post('https://generativelanguage.googleapis.com/v1beta/models/'
                                  '%s:generateContent?key=%s' % (m, cle), json=charge)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return '[Description des schémas impossible (%s)]' % str(e)[:120]
    cand = (data.get('candidates') or [{}])[0]
    texte = ''.join(p.get('text', '') for p in (cand.get('content', {}).get('parts') or []))
    return texte.strip() or '[Aucune description produite.]'


def pages_a_decrire(passages: list, demandees=None) -> list:
    """Pages envoyées à la vision : celles demandées, sinon les plus pertinentes (et voisines)."""
    if demandees:
        return sorted({int(p) for p in demandees if str(p).isdigit()})[:PAGES_VISION_MAX]
    vues = []
    for p in passages:
        if p['page'] not in vues:
            vues.append(p['page'])
        if len(vues) >= PAGES_VISION_MAX:
            break
    return sorted(vues)


def fiche_texte(a: dict) -> str:
    morceaux = [a['nom']]
    if a.get('marque') or a.get('modele'):
        morceaux.append(' '.join(x for x in (a.get('marque'), a.get('modele')) if x))
    if a.get('piece'):
        morceaux.append(a['piece'])
    return ' — '.join(morceaux) + ' (%s page(s))' % a.get('nb_pages', '?')
