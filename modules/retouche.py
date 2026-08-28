# -*- coding: utf-8 -*-
"""Manipuler une image en la décrivant — et savoir QUI a travaillé.

D'OÙ VIENT CE MODULE
Du dossier « papillons » de Fernando, où les noms de fichiers étaient les
consignes elles-mêmes : « Il faut garder le papillon qui est au premier plan,
posé sur un bras, mais si possible sans voir le bras, et surtout enlever la
dame en arrière-plan avec son sac ». En relisant ce dossier, une chose saute
aux yeux : le travail était de DEUX natures, et il ne faut pas les confondre.

  1. Des opérations EXACTES — recadrer au plus près, agrandir, redresser.
     Le résultat est prévisible au pixel près. Rien n'est inventé.
  2. Des retouches INVENTIVES — faire disparaître une personne, un mur, une
     barre de fer. Il faut alors imaginer ce qu'il y avait derrière.

Confier la première catégorie à un modèle génératif est une mauvaise idée : il
ne DÉCOUPE pas, il REDESSINE. Sur une photo de famille, tous les pixels
changent, et les visages avec. Inversement, aucune bibliothèque locale ne fera
disparaître la dame au sac.

CE MODULE AIGUILLE DONC, ET LE DIT
`analyser()` lit la consigne et choisit la voie. `appliquer()` exécute la voie
locale. La voie inventive part chez le modèle, via `modules/imagerie.py`. Dans
les deux cas, la réponse porte QUI a travaillé — parce qu'on ne relit pas de la
même façon une image découpée et une image redessinée. Pour quelqu'un qui ne
voit pas le résultat, cette phrase EST le résultat.

RÈGLE D'AIGUILLAGE, ET SA JUSTIFICATION
Si la consigne mélange les deux natures (« recadre et enlève la dame »), tout
part chez le modèle. Faire la moitié localement puis l'autre moitié autrement
donnerait un résultat dont personne ne saurait dire ce qu'il contient.

PRUDENCE
Aucune fonction ne lève : les erreurs reviennent en français dans le résultat.
"""

import re as _re
import io as _io

# ── Ce qui exige d'INVENTER. La présence d'un seul de ces motifs suffit à
#    envoyer toute la consigne au modèle : on ne découpe pas une demande.
_MOTIFS_INVENTIFS = [
    r"\benl[eè]ve\b", r"\bsupprim", r"\beffac", r"\bretir", r"\bvire\b",
    r"\bfais dispara", r"\bdispara[iî]tre\b", r"\bsans (?:le|la|les|l')\b",
    r"\bajoute\b", r"\brajoute\b", r"\bmets? un\b", r"\bmets? une\b",
    r"\bremplace", r"\bchange (?:le|la|les|l')\b", r"\btransforme",
    r"\bd[ée]toure", r"\bcolorise", r"\bfond\b", r"\barri[eè]re[- ]plan\b",
    r"\bg[ée]n[eè]re\b", r"\bdessine\b", r"\bimagine\b", r"\bstyle\b",
    r"\bam[ée]liore\b", r"\brestaure\b", r"\bnettoie\b", r"\bretouche\b",
]

# ── Exceptions : « enlever les bords », « supprimer la marge blanche » sont des
#    RECADRAGES, pas des inventions. Elles sont testées AVANT les motifs
#    inventifs, sinon un simple rognage partirait chez le modèle pour rien.
_MOTIFS_ROGNAGE = [
    r"\b(?:enl[eè]ve|supprim\w*|retir\w*|coupe|rogne)\b[^.]{0,30}"
    r"\b(?:bords?|marges?|blanc autour|contour blanc|cadre blanc)\b",
]

_FORCE = {
    'un peu': 0.5, 'l[ée]g[eè]rement': 0.5, 'un poil': 0.4, 'un chouïa': 0.4,
    'beaucoup': 1.8, 'vraiment': 1.6, 'fortement': 1.8, 'nettement': 1.5,
    'franchement': 1.6, 'tr[eè]s': 1.5, 'un maximum': 2.0, 'au maximum': 2.0,
}

RATIOS_CONNUS = {
    'carr': (1, 1), '1:1': (1, 1), '16:9': (16, 9), '16/9': (16, 9),
    '4:3': (4, 3), '4/3': (4, 3), '3:2': (3, 2), '3/2': (3, 2),
    '9:16': (9, 16), '9/16': (9, 16), '2:3': (2, 3), '3:4': (3, 4),
}


def _force(texte):
    """Combien ? « un peu » et « beaucoup » ne demandent pas la même chose."""
    for motif, valeur in _FORCE.items():
        if _re.search(r'\b' + motif + r'\b', texte):
            return valeur
    return 1.0


def analyser(consigne):
    """Lit la consigne et décide de la voie. Fonction PURE.

    Rend {'voie': 'local'|'modele', 'operations': [...], 'raison': str}.

    Le champ `raison` n'est pas décoratif : c'est ce qui sera dit à
    l'utilisateur. Quelqu'un qui ne voit pas l'image doit savoir si elle a été
    découpée (donc fidèle) ou redessinée (donc réinventée).
    """
    t = (consigne or '').strip().lower()
    if not t:
        return {'voie': 'modele', 'operations': [],
                'raison': "Aucune consigne : dis ce que tu veux changer."}

    ops = []

    # ── Rognage exprimé comme un retrait (« enlève les bords ») ──
    rognage_bords = any(_re.search(m, t) for m in _MOTIFS_ROGNAGE)

    # ── Rotation ──
    m = _re.search(r'\b(?:pivote|tourne|fais pivoter|fais tourner)\b[^.]{0,40}?'
                   r'(\d{1,3})\s*(?:°|degr)', t)
    if m:
        ops.append({'op': 'rotation', 'angle': int(m.group(1)) % 360})
    elif _re.search(r'\b(?:pivote|tourne|fais pivoter|fais tourner|bascule)\b', t):
        if _re.search(r'\b(?:[aà] gauche|anti[- ]horaire|sens inverse)\b', t):
            ops.append({'op': 'rotation', 'angle': 90})
        else:
            ops.append({'op': 'rotation', 'angle': 270})   # à droite

    if _re.search(r'\b(?:redresse|remets? d.aplomb|remets? [aà] l.endroit|'
                  r'oriente correctement)\b', t):
        ops.append({'op': 'redresser'})

    if _re.search(r'\b(?:miroir|retourne|inverse)\b', t):
        vertical = bool(_re.search(r'\bvertical', t))
        ops.append({'op': 'miroir', 'axe': 'vertical' if vertical else 'horizontal'})

    # ── Recadrage ──
    for cle, (rw, rh) in RATIOS_CONNUS.items():
        if _re.search(r'\b(?:recadre|rogne|coupe|format|passe|mets?)\b[^.]{0,40}'
                      + _re.escape(cle), t):
            ops.append({'op': 'recadrer', 'ratio': (rw, rh)})
            break
    else:
        m = _re.search(r'\b(?:recadre|rogne|coupe)\b[^.]{0,40}?(\d{1,2})\s*%', t)
        if m:
            ops.append({'op': 'recadrer', 'marge': min(45, int(m.group(1))) / 100.0})
        elif rognage_bords:
            ops.append({'op': 'recadrer', 'marge': 0.05})
        elif _re.search(r'\b(?:recadre|rogne)\b', t):
            ops.append({'op': 'recadrer', 'marge': 0.08})

    # ── Taille ──
    m = _re.search(r'\b(?:agrandis?|agrandir|upscale|multiplie)\b[^.]{0,30}?'
                   r'(?:x|×|par|fois)\s*([234])\b', t)
    if m:
        ops.append({'op': 'echelle', 'facteur': float(m.group(1))})
    else:
        m = _re.search(r'\b(?:redimensionne|mets?|passe|fais)\b[^.]{0,30}?'
                       r'(\d{3,5})\s*(?:px|pixels?)\b', t)
        if m:
            ops.append({'op': 'largeur', 'px': int(m.group(1))})
        elif _re.search(r'\b(?:double|doubler)\b[^.]{0,20}\btaille\b', t):
            ops.append({'op': 'echelle', 'facteur': 2.0})
        elif _re.search(r'\b(?:r[ée]duis|r[ée]duire|diminue)\b[^.]{0,30}\bmoiti[ée]\b', t):
            ops.append({'op': 'echelle', 'facteur': 0.5})
        elif _re.search(r'\b(?:agrandis?|agrandir|upscale)\b', t):
            ops.append({'op': 'echelle', 'facteur': 2.0})

    # ── Lumière, contraste, netteté, couleur ──
    f = _force(t)
    if _re.search(r'\b(?:[ée]claircis|[ée]claircir|plus clair|moins sombre)\b', t):
        ops.append({'op': 'luminosite', 'facteur': 1 + 0.25 * f})
    elif _re.search(r'\b(?:assombris|assombrir|plus sombre|moins clair)\b', t):
        ops.append({'op': 'luminosite', 'facteur': max(0.2, 1 - 0.25 * f)})

    if _re.search(r'\bplus de contraste\b|\bcontraste\w*\b(?![^.]{0,15}moins)', t) \
            and not _re.search(r'\bmoins de contraste\b', t):
        ops.append({'op': 'contraste', 'facteur': 1 + 0.3 * f})
    elif _re.search(r'\bmoins de contraste\b|\badoucis le contraste\b', t):
        ops.append({'op': 'contraste', 'facteur': max(0.2, 1 - 0.3 * f)})

    if _re.search(r'\bplus nett?e?s?\b|\bnettet[ée]\b|\baiguise\b|\bpiqu[ée]\b', t):
        ops.append({'op': 'nettete', 'facteur': 1 + 0.6 * f})
    elif _re.search(r'\badoucis\b|\bplus doux\b|\bflou l[ée]ger\b', t):
        ops.append({'op': 'nettete', 'facteur': max(0.1, 1 - 0.4 * f)})

    if _re.search(r'\bnoir et blanc\b|\bniveaux? de gris\b|\bd[ée]satur', t):
        ops.append({'op': 'gris'})

    # ── L'aiguillage proprement dit ──
    inventif = any(_re.search(m, t) for m in _MOTIFS_INVENTIFS)
    if inventif and rognage_bords and len(ops) == 1 and ops[0]['op'] == 'recadrer':
        # « enlève les bords blancs » : le mot « enlève » ne fait pas de cette
        # demande une invention.
        inventif = False

    if inventif:
        return {'voie': 'modele', 'operations': [],
                'raison': ("Cette demande suppose d'inventer ce qui n'est pas sur "
                           "la photo : elle part au modèle, qui REDESSINE l'image."
                           if not ops else
                           "La demande mélange une retouche exacte et une retouche "
                           "inventée : tout part au modèle, sinon personne ne "
                           "saurait dire ce que contient le résultat.")}
    if ops:
        return {'voie': 'local', 'operations': ops,
                'raison': ("Fait sur ta machine, au pixel près : rien n'est "
                           "inventé, rien ne sort de chez toi.")}
    return {'voie': 'modele', 'operations': [],
            'raison': ("Aucune opération exacte reconnue dans ta phrase : elle "
                       "part au modèle, qui redessinera l'image.")}


# ══════════════════════════════════════════════════════════════════════
#  LA VOIE LOCALE — exacte, gratuite, hors ligne
# ══════════════════════════════════════════════════════════════════════

def _poids(n):
    """Un poids de fichier en toutes lettres : « 1,3 Mo » plutôt que 1288966."""
    if n < 1024:
        return "%d octets" % n
    if n < 1024 * 1024:
        return ("%.0f Ko" % (n / 1024.0))
    return ("%.1f Mo" % (n / 1048576.0)).replace('.', ',')


def _recadrer(img, op):
    l, h = img.size
    if op.get('ratio'):
        rw, rh = op['ratio']
        cible = rw / rh
        if l / h > cible:
            nl, nh = int(h * cible), h
        else:
            nl, nh = l, int(l / cible)
        x, y = (l - nl) // 2, (h - nh) // 2
        return img.crop((x, y, x + nl, y + nh)), \
            "recadré au format %d:%d (%d×%d pixels)" % (rw, rh, nl, nh)
    marge = float(op.get('marge', 0.08))
    dx, dy = int(l * marge), int(h * marge)
    return img.crop((dx, dy, l - dx, h - dy)), \
        "rogné de %d %% sur chaque bord (%d×%d pixels)" % (
            round(marge * 100), l - 2 * dx, h - 2 * dy)


def appliquer(octets, operations):
    """Exécute les opérations locales. Rend (octets, mime, journal, erreur).

    `journal` est une liste de phrases décrivant ce qui a VRAIMENT été fait,
    avec les dimensions obtenues. Pour quelqu'un qui ne voit pas le résultat,
    c'est la seule preuve que l'opération a eu lieu — et la seule façon de
    repérer qu'elle n'a pas fait ce qu'on croyait.
    """
    if not octets:
        return b'', '', [], "Aucune image reçue."
    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError:
        return b'', '', [], ("La bibliothèque Pillow manque. Installe-la avec "
                             "« pip install Pillow », puis relance NIMM.")
    try:
        img = Image.open(_io.BytesIO(octets))
        img.load()
    except Exception as e:
        return b'', '', [], f"Image illisible : {e}"

    depart = img.size
    journal = []
    try:
        for op in (operations or []):
            n = op.get('op')
            if n == 'redresser':
                # L'orientation vit dans les métadonnées EXIF : beaucoup de
                # photos de téléphone sont « couchées » dans le fichier et
                # redressées seulement à l'affichage.
                img = ImageOps.exif_transpose(img)
                journal.append("redressée d'après l'orientation enregistrée par l'appareil")
            elif n == 'rotation':
                a = int(op.get('angle', 270)) % 360
                if a:
                    img = img.rotate(a, expand=True)
                    sens = "vers la gauche" if a == 90 else (
                        "vers la droite" if a == 270 else "de %d degrés" % a)
                    journal.append("pivotée %s" % sens)
            elif n == 'miroir':
                if op.get('axe') == 'vertical':
                    img = ImageOps.flip(img); journal.append("retournée de haut en bas")
                else:
                    img = ImageOps.mirror(img); journal.append("retournée en miroir")
            elif n == 'recadrer':
                img, phrase = _recadrer(img, op)
                journal.append(phrase)
            elif n == 'echelle':
                f = max(0.1, min(4.0, float(op.get('facteur', 2.0))))
                nl, nh = max(1, int(img.width * f)), max(1, int(img.height * f))
                img = img.resize((nl, nh), Image.LANCZOS)
                journal.append("redimensionnée ×%g (%d×%d pixels) — agrandissement "
                               "simple, sans détail inventé" % (f, nl, nh))
            elif n == 'largeur':
                px = max(16, min(10000, int(op.get('px', 1024))))
                nh = max(1, round(img.height * px / img.width))
                img = img.resize((px, nh), Image.LANCZOS)
                journal.append("redimensionnée à %d pixels de large (%d de haut)" % (px, nh))
            elif n in ('luminosite', 'contraste', 'nettete'):
                classe = {'luminosite': ImageEnhance.Brightness,
                          'contraste': ImageEnhance.Contrast,
                          'nettete': ImageEnhance.Sharpness}[n]
                if img.mode not in ('RGB', 'RGBA', 'L'):
                    img = img.convert('RGB')
                f = float(op.get('facteur', 1.2))
                img = classe(img).enhance(f)
                mot, genre = {'luminosite': ('luminosité', 'e'),
                              'contraste': ('contraste', ''),
                              'nettete': ('netteté', 'e')}[n]
                journal.append("%s %s (facteur %.2f)" % (
                    mot, ("augmenté" + genre) if f > 1 else ("diminué" + genre), f))
            elif n == 'gris':
                img = ImageOps.grayscale(img)
                journal.append("convertie en noir et blanc")
    except Exception as e:
        return b'', '', journal, f"L'opération a échoué : {e}"

    if not journal:
        return b'', '', [], "Aucune opération à appliquer."

    # PNG systématiquement : c'est sans perte. Réencoder une photo en JPEG à
    # chaque retouche la dégraderait un peu plus à chaque fois, et sur une
    # série de reprises successives cela finit par se voir.
    try:
        if img.mode not in ('RGB', 'RGBA', 'L'):
            img = img.convert('RGB')
        sortie = _io.BytesIO()
        img.save(sortie, format='PNG')
    except Exception as e:
        return b'', '', journal, f"Enregistrement impossible : {e}"

    resultat = sortie.getvalue()
    journal.append("dimensions : %d×%d au départ, %d×%d à l'arrivée"
                   % (depart[0], depart[1], img.width, img.height))
    # Le poids est dit, parce qu'il surprend : le PNG est SANS PERTE, donc plus
    # lourd qu'un JPEG — souvent plusieurs fois. C'est le prix à payer pour
    # pouvoir enchaîner les retouches sans dégrader un peu plus à chaque tour.
    journal.append("fichier : %s au départ, %s à l'arrivée (PNG, sans perte)"
                   % (_poids(len(octets)), _poids(len(resultat))))
    return resultat, 'image/png', journal, ''


def options(api_keys=None):
    """Ce que sait faire ce panneau, dit sans exagérer."""
    cle = ((api_keys or {}).get('gemini') or '').strip()
    return {
        'cle_gemini': bool(cle),
        'exemples_locaux': [
            "recadre au format carré",
            "pivote à droite",
            "redresse la photo",
            "agrandis ×2",
            "éclaircis un peu",
            "plus de contraste",
            "mets-la en noir et blanc",
            "enlève les bords blancs",
        ],
        'exemples_modele': [
            "enlève la dame en arrière-plan avec son sac",
            "fais disparaître la barre en fer entre les deux nichoirs",
            "on voit un bout du mur, il faut l'enlever",
            "remplace le fond par un ciel dégagé",
        ],
        'note': ("Les demandes exactes (recadrer, pivoter, agrandir, éclaircir) "
                 "sont faites sur ta machine : rien ne sort de chez toi, et rien "
                 "n'est inventé. Les autres partent au modèle, qui REDESSINE "
                 "l'image — les pixels changent partout. NIMM te dit à chaque "
                 "fois lequel des deux a travaillé."
                 if cle else
                 "Aucune clé Gemini : seules les retouches exactes (recadrer, "
                 "pivoter, agrandir, éclaircir, noir et blanc) sont possibles. "
                 "Faire disparaître un objet demande un modèle."),
    }
