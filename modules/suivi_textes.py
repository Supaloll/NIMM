# -*- coding: utf-8 -*-
"""Suivre un texte réglementaire dans le temps — ce qui a changé depuis la version précédente.

Un projet de décret revient trois fois en commission, chaque fois « légèrement
modifié ». Relire les deux versions côte à côte pour trouver les trois mots qui
ont bougé est exactement le travail où l'on rate l'essentiel.

PRINCIPE : LE CODE COMPARE, LE MODÈLE COMMENTE — ET ON SAIT QUI A DIT QUOI.
  - Ce qui a changé (article ajouté, supprimé, modifié ; mots remplacés) est
    établi par une comparaison automatique des deux versions (difflib). Aucun
    modèle n'intervient : on ne laisse pas une IA dire ce qui a changé dans un
    texte de loi, elle « lisserait » précisément ce qu'on cherche.
  - La « portée probable » de chaque changement est, elle, une analyse du
    modèle — optionnelle, et présentée comme telle, à vérifier.

LES VERSIONS SONT CONSERVÉES dans la base du profil (table texte_suivi_version),
sous le nom donné au texte. Chaque nouvelle version est comparée à la
précédente. On peut aussi comparer deux versions sans rien conserver (fil
fantôme, ou deux documents de la base).

DÉCOUPAGE : par article quand le texte en a (« Article 1er », « Art. 3 bis »,
« Article L. 111-7 »), ce qui permet d'aligner les articles même si le texte a
été réordonné ; sinon par paragraphe.
"""

import difflib
import hashlib
import re
from datetime import datetime

from modules.citations import chaine, extraire_json, liste_de_dicts, normaliser

MAX_VERSIONS = 20          # par texte suivi : au-delà, les plus anciennes sont retirées
MAX_EXTRAIT = 3000         # longueur d'un « avant / après » cité en entier
MAX_DETAILS = 8            # au-delà, on parle de réécriture plutôt que d'énumérer

PREAMBULE = 'Préambule'


# ── Conservation des versions ─────────────────────────────────────────────

def _conn():
    from core.database import get_conn
    conn = get_conn()
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS texte_suivi_version (
               id             INTEGER PRIMARY KEY AUTOINCREMENT,
               nom            TEXT NOT NULL,
               nom_norm       TEXT NOT NULL,
               enregistre_le  TEXT NOT NULL,
               source         TEXT,
               empreinte      TEXT NOT NULL,
               texte          TEXT NOT NULL
           )''')
    return conn


def empreinte(texte: str) -> str:
    """Deux versions qui ne diffèrent que par les espaces sont la même version."""
    return hashlib.sha256(re.sub(r'\s+', ' ', texte or '').strip().encode('utf-8')).hexdigest()


def versions(nom: str) -> list:
    """Versions conservées d'un texte, de la plus ancienne à la plus récente (sans le texte)."""
    conn = _conn()
    rows = conn.execute(
        'SELECT id, nom, enregistre_le, source, LENGTH(texte) AS nb_car FROM texte_suivi_version '
        'WHERE nom_norm = ? ORDER BY id', (normaliser(nom),)).fetchall()
    conn.close()
    return [dict(r, numero=i) for i, r in enumerate(rows, 1)]


def textes_suivis() -> list:
    conn = _conn()
    rows = conn.execute(
        'SELECT nom, COUNT(*) AS n, MAX(enregistre_le) AS derniere FROM texte_suivi_version '
        'GROUP BY nom_norm ORDER BY derniere DESC').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def derniere_version(nom: str) -> dict:
    conn = _conn()
    row = conn.execute(
        'SELECT id, nom, enregistre_le, source, empreinte, texte FROM texte_suivi_version '
        'WHERE nom_norm = ? ORDER BY id DESC LIMIT 1', (normaliser(nom),)).fetchone()
    conn.close()
    return dict(row) if row else {}


def enregistrer_version(nom: str, texte: str, source: str = '') -> dict:
    """Conserve la version si elle diffère de la dernière. Rend {numero, nouvelle, enregistre_le}."""
    der = derniere_version(nom)
    emp = empreinte(texte)
    if der and der['empreinte'] == emp:
        return {'numero': len(versions(nom)), 'nouvelle': False,
                'enregistre_le': der['enregistre_le']}
    quand = datetime.now().isoformat(timespec='seconds')
    conn = _conn()
    conn.execute('INSERT INTO texte_suivi_version (nom, nom_norm, enregistre_le, source, '
                 'empreinte, texte) VALUES (?, ?, ?, ?, ?, ?)',
                 (nom, normaliser(nom), quand, source, emp, texte))
    ids = [r[0] for r in conn.execute(
        'SELECT id FROM texte_suivi_version WHERE nom_norm = ? ORDER BY id', (normaliser(nom),))]
    for vieux in ids[:-MAX_VERSIONS]:
        conn.execute('DELETE FROM texte_suivi_version WHERE id = ?', (vieux,))
    conn.commit()
    conn.close()
    return {'numero': min(len(ids), MAX_VERSIONS), 'nouvelle': True, 'enregistre_le': quand}


# ── Découpage ─────────────────────────────────────────────────────────────

_RE_TETE = re.compile(
    r'^[ \t]*((?:Article|ARTICLE|Art\.)\s+((?:[LRDA]\.?\s*)?(?:\d+(?:[-–.]\d+)*|premier|1er|unique)'
    r'(?:\s+(?:bis|ter|quater|quinquies|sexies))?))\b[ \t.:–-]*', re.M)


def _cle_article(num: str) -> str:
    a = re.sub(r'\s+', ' ', num.strip().lower()).replace('–', '-')
    a = re.sub(r'^([lrda])\.?\s*', r'\1', a)
    return {'premier': '1', '1er': '1'}.get(a, a)


def decouper(texte: str) -> tuple:
    """Rend (mode, unités). mode = 'article' ou 'paragraphe'.

    unités : liste de {cle, intitule, contenu}. En mode article, le texte qui
    précède le premier article (visas, considérants) forme le « Préambule ».
    """
    texte = (texte or '').replace('\r\n', '\n')
    tetes = list(_RE_TETE.finditer(texte))
    if len(tetes) >= 2:
        unites, vus = [], {}
        debut = texte[:tetes[0].start()].strip()
        if debut:
            unites.append({'cle': '_preambule', 'intitule': PREAMBULE, 'contenu': debut})
        for i, m in enumerate(tetes):
            fin = tetes[i + 1].start() if i + 1 < len(tetes) else len(texte)
            cle = _cle_article(m.group(2))
            if cle in vus:                  # même numéro deux fois : on garde les deux
                vus[cle] += 1
                cle = '%s#%d' % (cle, vus[cle])
            else:
                vus[cle] = 1
            unites.append({'cle': cle, 'intitule': 'Article ' + m.group(2).strip(),
                           'contenu': texte[m.end():fin].strip()})
        return 'article', unites
    paras = [p.strip() for p in re.split(r'\n\s*\n', texte) if p.strip()]
    if len(paras) < 2:
        paras = [p.strip() for p in texte.split('\n') if p.strip()]
    return 'paragraphe', [{'cle': str(i), 'intitule': 'Paragraphe %d' % i, 'contenu': p}
                          for i, p in enumerate(paras, 1)]


# ── Comparaison ───────────────────────────────────────────────────────────

def _mots(t: str) -> list:
    return re.findall(r'\S+', t or '')


def details_mot_a_mot(avant: str, apres: str) -> list:
    """Phrases « X remplacé par Y », « X supprimé », « Y ajouté », dans l'ordre du texte."""
    a, b = _mots(avant), _mots(apres)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    sortie = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        x, y = ' '.join(a[i1:i2]), ' '.join(b[j1:j2])
        if op == 'replace':
            sortie.append('« %s » remplacé par « %s »' % (x, y))
        elif op == 'delete':
            sortie.append('« %s » supprimé' % x)
        elif op == 'insert':
            sortie.append('« %s » ajouté' % y)
    return sortie


def _change(nature, unite, avant='', apres=''):
    c = {'nature': nature, 'unite': unite, 'avant': avant, 'apres': apres, 'details': []}
    if nature == 'modifié':
        d = details_mot_a_mot(avant, apres)
        c['details'] = d if len(d) <= MAX_DETAILS else []
        c['reecriture'] = len(d) > MAX_DETAILS
    return c


def comparer(ancien: str, nouveau: str) -> dict:
    """Rend {mode, changements, nb_unites_avant, nb_unites_apres}. Déterministe."""
    mode_a, ua = decouper(ancien)
    mode_b, ub = decouper(nouveau)
    changements = []
    if mode_a == mode_b == 'article':
        da = {u['cle']: u for u in ua}
        db = {u['cle']: u for u in ub}
        for u in ub:                                    # ordre du NOUVEAU texte
            if u['cle'] not in da:
                changements.append(_change('ajouté', u['intitule'], apres=u['contenu']))
            elif normaliser(da[u['cle']]['contenu']) != normaliser(u['contenu']):
                changements.append(_change('modifié', u['intitule'],
                                           da[u['cle']]['contenu'], u['contenu']))
        for u in ua:
            if u['cle'] not in db:
                changements.append(_change('supprimé', u['intitule'], avant=u['contenu']))
        mode = 'article'
    else:
        # Paragraphes : on aligne les séquences, puis on apparie les remplacements.
        mode = 'paragraphe'
        na = [normaliser(u['contenu']) for u in ua]
        nb = [normaliser(u['contenu']) for u in ub]
        sm = difflib.SequenceMatcher(None, na, nb, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == 'equal':
                continue
            if op == 'replace':
                for k in range(max(i2 - i1, j2 - j1)):
                    a = ua[i1 + k] if i1 + k < i2 else None
                    b = ub[j1 + k] if j1 + k < j2 else None
                    if a and b:
                        changements.append(_change('modifié', b['intitule'], a['contenu'], b['contenu']))
                    elif b:
                        changements.append(_change('ajouté', b['intitule'], apres=b['contenu']))
                    else:
                        changements.append(_change('supprimé', 'ancien ' + a['intitule'].lower(),
                                                   avant=a['contenu']))
            elif op == 'insert':
                for b in ub[j1:j2]:
                    changements.append(_change('ajouté', b['intitule'], apres=b['contenu']))
            elif op == 'delete':
                for a in ua[i1:i2]:
                    changements.append(_change('supprimé', 'ancien ' + a['intitule'].lower(),
                                               avant=a['contenu']))
    return {'mode': mode, 'changements': changements,
            'nb_unites_avant': len(ua), 'nb_unites_apres': len(ub)}


# ── Portée : l'analyse du modèle, à part ─────────────────────────────────

PROMPT_PORTEE = (
    "Tu reçois la liste des changements entre deux versions d'un texte réglementaire, "
    "établie par comparaison automatique. Pour chaque changement, dis en une ou deux "
    "phrases sa portée probable : ce qu'il change concrètement pour les personnes "
    "concernées (obligation renforcée ou affaiblie, délai, champ d'application, "
    "dérogation, contrôle, sanction).\n\n"
    "Réponds UNIQUEMENT par un tableau JSON, sans une ligne avant ni après :\n"
    '[{"numero": 1, "portee": "..."}]\n\n'
    "RÈGLES : appuie-toi uniquement sur les deux versions citées. Si la portée ne peut "
    "pas être établie à partir d'elles (un renvoi à un autre texte, par exemple), "
    "écris-le plutôt que de supposer. Un changement purement rédactionnel se dit "
    "« rédactionnel, sans effet sur le fond ».\n"
)


async def analyser_portee(changements: list, settings: dict) -> str:
    """Remplit c['portee'] quand c'est possible. Rend un message d'erreur, ou ''."""
    from core.engine import call_llm
    if not changements:
        return ''
    blocs = []
    for i, c in enumerate(changements, 1):
        blocs.append('Changement %d — %s (%s)%sAvant : %s%sAprès : %s' % (
            i, c['unite'], c['nature'], chr(10),
            (c['avant'][:MAX_EXTRAIT] or '(absent)'), chr(10),
            (c['apres'][:MAX_EXTRAIT] or '(absent)')))
    try:
        reponse = await call_llm(
            messages=[{'role': 'user', 'content': (chr(10) * 2).join(blocs)}],
            provider=settings.get('provider', ''), model=settings.get('model'),
            system_prompt=PROMPT_PORTEE, max_tokens=4000, temperature=0.0,
            api_keys=settings.get('api_keys', {}))
    except Exception as e:
        return "L'analyse de portée a échoué : %s. Les changements restent exacts." % e
    for e in liste_de_dicts(extraire_json(reponse, list)):
        try:
            k = int(e.get('numero')) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= k < len(changements) and chaine(e.get('portee')):
            changements[k]['portee'] = chaine(e.get('portee'))
    return ''


# ── Rendu ─────────────────────────────────────────────────────────────────

def _date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime('%d/%m/%Y à %H:%M')
    except Exception:
        return iso or 'date inconnue'


def _extrait(t: str) -> str:
    if len(t) <= MAX_EXTRAIT:
        return t
    return t[:MAX_EXTRAIT] + ' […] (texte coupé ici dans ce document ; la version complète est conservée)'


def rendre_markdown(nom: str, comp: dict, libelle_avant: str, libelle_apres: str,
                    avertissements=None, portee_demandee: bool = True) -> str:
    ch = comp['changements']
    n = {k: sum(1 for c in ch if c['nature'] == k) for k in ('ajouté', 'modifié', 'supprimé')}
    unite = 'article' if comp['mode'] == 'article' else 'paragraphe'
    L = ['# Suivi du texte — %s' % nom, '']
    L.append('Comparaison de %s avec %s, établie le %s.' % (
        libelle_avant, libelle_apres, datetime.now().strftime('%d/%m/%Y')))
    L.append('')
    L.append('%d changement(s) : %d %s(s) modifié(s), %d ajouté(s), %d supprimé(s). '
             'Découpage par %s.' % (len(ch), n['modifié'], unite, n['ajouté'],
                                    n['supprimé'], unite))
    for a in (avertissements or []):
        L += ['', 'Avertissement : ' + a]
    L += ['', "Les changements sont établis par comparaison automatique des deux versions, "
          "sans interprétation : ce qui est cité est le texte exact."
          + (" Seule la rubrique « Portée probable » est une analyse de NIMM, à vérifier."
             if portee_demandee else '')]
    if not ch:
        L += ['', 'Aucun changement de fond : les deux versions sont identiques, aux '
              'espaces et à la casse près.']
        return chr(10).join(L) + chr(10)

    L += ['', '## Récapitulatif', '', '| %s | Changement |' % unite.capitalize(), '|---|---|']
    for c in ch:
        L.append('| %s | %s |' % (c['unite'].replace('|', '/'), c['nature']))

    for c in ch:
        L += ['', '## %s — %s' % (c['unite'], c['nature'])]
        if c['nature'] == 'modifié':
            if c.get('details'):
                L += ['', 'Changements mot à mot :']
                L += ['- ' + d for d in c['details']]
            elif c.get('reecriture'):
                L += ['', 'Réécriture importante : trop de changements pour les énumérer '
                      'mot à mot. Comparer les deux rédactions ci-dessous.']
            L += ['', 'Avant : « %s »' % _extrait(c['avant']), '',
                  'Après : « %s »' % _extrait(c['apres'])]
        elif c['nature'] == 'ajouté':
            L += ['', 'Nouveau texte : « %s »' % _extrait(c['apres'])]
        else:
            L += ['', 'Texte retiré : « %s »' % _extrait(c['avant'])]
        if c.get('portee'):
            L += ['', 'Portée probable (analyse de NIMM, à vérifier) : ' + c['portee']]
    return chr(10).join(L) + chr(10)


def rendre_note_carnet(nom: str, comp: dict, libelle_apres: str) -> str:
    ch = comp['changements']
    if not ch:
        return 'Suivi du texte « %s » : aucun changement dans %s.' % (nom, libelle_apres)
    unites = ', '.join('%s (%s)' % (c['unite'], c['nature']) for c in ch[:5])
    reste = (' et %d autre(s)' % (len(ch) - 5)) if len(ch) > 5 else ''
    return 'Suivi du texte « %s » : %d changement(s) dans %s — %s%s.' % (
        nom, len(ch), libelle_apres, unites, reste)
