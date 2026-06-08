# ============================================
# NIMM — modules/bibliotheque.py
# Generation et recall des fiches bibliotheque
# ============================================

import asyncio
import json
import re

from core.engine import call_llm
from core.database import (
    get_messages, get_carnet_notes, get_thread,
    search_bibliotheque_fts, get_bibliotheque_by_ids,
)


# ══════════════════════════════════════════
# RECALL THEMATIQUE
# ══════════════════════════════════════════

def recall_bibliotheque(query: str, limit: int = 3) -> str:
    """
    Recall thematique bibliotheque -- recherche FTS5 sur os_json.
    Retourne un bloc texte injectable dans le system prompt, ou '' si rien.
    Uniquement les entrees status='active'.
    """
    ids = search_bibliotheque_fts(query, limit=limit)
    if not ids:
        return ''

    entries = get_bibliotheque_by_ids(ids)
    if not entries:
        return ''

    lines = []
    for e in entries:
        titre    = e.get('titre', 'Sans titre')
        date     = e.get('date_conversation', '') or e.get('date_creation', '')[:10]
        os_riche = e.get('os_riche', '')
        os_raw   = e.get('os_json', '')

        details = []

        # ── Fiche riche : injecter l'os complet ──
        if os_riche:
            try:
                d = json.loads(os_riche)
                fil = d.get('fil_conducteur', '').strip()
                if fil:
                    details.append(f"Fil : {fil}")
                noeuds = d.get('noeuds', [])
                if isinstance(noeuds, list) and noeuds:
                    for n in noeuds[:6]:
                        if n:
                            details.append(f"• {n}")
                positions = d.get('positions', [])
                if isinstance(positions, list) and positions:
                    details.append(f"Positions : {' / '.join(str(p) for p in positions[:3] if p)}")
                questions = d.get('questions_ouvertes', [])
                if isinstance(questions, list) and questions:
                    details.append(f"Questions ouvertes : {' / '.join(str(q) for q in questions[:2] if q)}")
                ramifications = d.get('ramifications', [])
                if isinstance(ramifications, list) and ramifications:
                    details.append(f"Pistes non explorees : {' / '.join(str(r) for r in ramifications[:2] if r)}")
            except Exception:
                pass

        # ── Fallback : ancienne fiche os_json ──
        elif os_raw:
            try:
                os_data = json.loads(os_raw)
                if os_data.get('conclusions'):
                    details.append(f"Conclusion : {os_data['conclusions']}")
                if os_data.get('mots_cles'):
                    mk = os_data['mots_cles']
                    if isinstance(mk, list) and mk:
                        details.append(f"Mots-cles : {', '.join(str(k) for k in mk[:6])}")
            except Exception:
                pass

        line = f"  . [{date}] {titre}"
        if details:
            line += chr(10) + '    ' + (chr(10) + '    ').join(details)
        lines.append(line)

    return "Conversations archivees sur ce sujet :" + chr(10) + chr(10).join(lines)


# ══════════════════════════════════════════
# GENERATION FICHE ARCHIVAGE
# ══════════════════════════════════════════

async def generate_bibliotheque_entry(
    thread_id: str,
    settings:  dict,
    mask_name: str,
    bilans:    list = None,
) -> dict:
    """
    Genere une fiche d'archivage complete pour un fil de conversation.
    Appel C (extraction faits) -> puis Appel OS (os en 7 composantes + categories).
    Retourne : { titre, sujet_principal, tags, categories, resume_texte, os_json, os_riche, date_conversation }
    """
    messages = get_messages(thread_id, limit=200)
    if not messages:
        return {}

    provider = settings.get('provider', '')
    api_keys = settings.get('api_keys', {})

    # ── Extrait conversation : debut + fin ──
    def _build_excerpt(msgs, char_budget=7000):
        lines = []
        for m in msgs:
            role = 'Utilisateur' if m['role'] == 'user' else mask_name
            lines.append(f"{role} : {m['content'][:600]}")
        full = chr(10).join(lines)
        if len(full) <= char_budget:
            return full
        half = char_budget // 2
        return full[:half] + chr(10) + chr(10) + "[...]" + chr(10) + chr(10) + full[-half:]

    conversation_excerpt  = _build_excerpt(messages)
    date_conversation     = messages[0].get('created_at', '')[:10] if messages else ''

    # ── Carnet de bord ──
    carnet_block = ''
    _carnet = get_carnet_notes(thread_id)
    if _carnet:
        _lines = [f"[{n['note_number']}] {n['content']}" for n in _carnet]
        carnet_block = chr(10) + chr(10) + "Carnet de bord (notes prises au fil de la conversation) :" + chr(10) + chr(10).join(_lines)

    # ── Bilans de session ──
    bilan_block = ''
    _bilans = bilans or []
    if _bilans:
        _blines = chr(10).join(f"— [{b['ts']}] {b['texte']}" for b in _bilans)
        bilan_block = (
            chr(10) + chr(10) + "FAITS CONFIRMES DANS CE FIL (%%BILAN%% estampilles en cours de conversation) :" + chr(10)
            + _blines
            + chr(10) + "Regle absolue : ces faits ont ete explicitement valides — ta fiche doit les refleter "
            "tels quels, sans deformation, sans omission, sans invention d'autres faits du meme type."
        )

    # ── Prompt C (extrait avant appel C) ──
    prompt_c = (
        "Tu es un extracteur de faits. Lis cette conversation et liste UNIQUEMENT "
        "les faits, resultats ou evenements EXPLICITEMENT CONFIRMES par l'utilisateur." + chr(10) + chr(10)
        + "Reponds UNIQUEMENT avec un tableau JSON de strings. Chaque string = 1 fait, <= 10 mots." + chr(10) + chr(10)
        + "Regles strictes :" + chr(10)
        + "- Resultats confirmes : scores, victoires, KO, classements annonces" + chr(10)
        + "- Faits personnels annonces : notes, resultats scolaires, nouvelles familiales" + chr(10)
        + "- Evenements valides : decisions prises, abonnements, achats, rendez-vous confirmes" + chr(10)
        + "- INTERDIT : hypotheses, suggestions, opinions, faits non confirmes, reformulations" + chr(10)
        + "- INTERDIT : predictions ou analyses faites AVANT un evenement" + chr(10)
        + "- Le carnet de bord (si present) est ta reference de verification" + chr(10)
        + "- Tableau vide [] si aucun fait clairement confirme" + chr(10)
        + "- 0 a 10 entrees maximum" + chr(10) + chr(10)
        + f"Conversation :{chr(10)}{conversation_excerpt}{carnet_block}"
    )

    # ── Etape 1 : Appel C — extraction mecanique des faits confirmes ──
    bilan_block = ''
    try:
        raw_c = await call_llm(
            messages    = [{'role': 'user', 'content': prompt_c}],
            provider    = provider,
            max_tokens  = 400,
            temperature = 0.0,
            api_keys    = api_keys,
        )
        if isinstance(raw_c, str):
            clean_c = re.sub(r'```[a-z]*', '', raw_c).strip().strip('`')
            bilans_extraits = json.loads(clean_c)
            if isinstance(bilans_extraits, list) and bilans_extraits:
                _blines = chr(10).join(f"— {b}" for b in bilans_extraits if isinstance(b, str) and b.strip())
                bilan_block = (
                    chr(10) + chr(10) + "FAITS CONFIRMES DANS CE FIL (extraits mecaniquement) :" + chr(10)
                    + _blines
                    + chr(10) + "Regle absolue : ces faits ont ete explicitement valides — ta fiche doit les "
                    "refleter tels quels, sans deformation, sans omission, sans invention d'autres faits du meme type."
                )
                print(f"[BIBLIO] Bilans extraits ({len(bilans_extraits)}) : {bilans_extraits}")
    except Exception as e:
        print(f"[BIBLIO] Appel C bilans echoue : {e}")

    # ── Etape 2 : Appel OS — os en 7 composantes + categories ──
    _CATEGORIES_LIST = (
        "🩷 Emotions  🔎 Reflexions  ⚙️ Projets & Travail  🏡 Quotidien & Famille  "
        "🌍 Monde & Societe  🎮 Loisirs & Passion  📝 Creation & Imaginaire  "
        "💬 Souvenirs & Memoire  🧬 Sante & Corps  🕯️ Spiritualite & Sens  "
        "✈️ Voyages & Ailleurs  🧰 Metier & Savoir-faire  🪞 Rapport a soi  "
        "🔮 Futur & Possibles  🕳️ Zones d'Ombre  🤝 Lien Social  🧩 Synchronicites"
    )

    prompt_os = (
        f"Tu analyses une conversation entre un utilisateur et {mask_name}." + chr(10) + chr(10)
        + "Genere un objet JSON avec ces champs EXACTS :" + chr(10) + chr(10)
        + "- titre : titre court et precis (8 mots max)" + chr(10)
        + "- tags : 4 a 8 mots-cles separes par des virgules (pour la recherche textuelle)" + chr(10)
        + "- categories : 1 a 3 emojis choisis UNIQUEMENT dans cette liste, separes par des virgules :" + chr(10)
        + f"  {_CATEGORIES_LIST}" + chr(10)
        + "- fil_conducteur : 1 phrase — la question ou tension centrale qui a traverse la conversation" + chr(10)
        + "- noeuds : tableau de 4 a 8 strings — les idees substantielles qui ont emerge." + chr(10)
        + "  Chaque noeud = 1 a 3 phrases developpees. Pas des resumes d'une ligne." + chr(10)
        + "- positions : tableau de 0 a 5 strings — ce qui a ete conclu, decide, ou assume comme non tranche" + chr(10)
        + "- questions_ouvertes : tableau de 0 a 4 strings — ce qui tourne encore, meriterait d'etre poursuivi" + chr(10)
        + "- formulations_cles : tableau de 0 a 3 strings — phrases ou tournures qui ont bien capture quelque chose" + chr(10)
        + "- climat : 1 phrase courte — le mode de la conversation (chercher ensemble, buter, construire, leger, tendu...)" + chr(10)
        + "- ramifications : tableau de 0 a 3 strings — pistes frolees, sujets qui affleuraient sans etre traites" + chr(10) + chr(10)
        + "Regles :" + chr(10)
        + "- noeuds = idees developpees en 1 a 3 phrases, pas des mots-cles" + chr(10)
        + "- positions = faits explicitement confirmes ou assumes, pas des suggestions" + chr(10)
        + "- Reponds UNIQUEMENT avec un objet JSON valide, sans markdown ni texte autour." + chr(10) + chr(10)
        + f"Conversation :{chr(10)}{conversation_excerpt}{carnet_block}{bilan_block}"
    )

    try:
        raw_os = await call_llm(
            messages    = [{'role': 'user', 'content': prompt_os}],
            provider    = provider,
            max_tokens  = 1500,
            temperature = 0.3,
            api_keys    = api_keys,
        )
    except Exception as e:
        print(f"[BIBLIO] Erreur generation os bibliotheque : {e}")
        return {}

    # ── Parser Appel OS ──
    data_os = {}
    if isinstance(raw_os, str):
        try:
            data_os = json.loads(re.sub(r'```[a-z]*', '', raw_os).strip().strip('`'))
        except Exception as e:
            print(f"[BIBLIO] Erreur parsing os bibliotheque : {e}")
    else:
        print(f"[BIBLIO] Appel OS bibliotheque echoue : {raw_os}")

    # ── Assembler resume_texte (fallback affichage anciennes fiches) ──
    def _assemble_resume(d: dict) -> str:
        parts = []
        fil = d.get('fil_conducteur', '').strip()
        if fil:
            parts.append(fil)
        noeuds = d.get('noeuds', [])
        if isinstance(noeuds, list) and noeuds:
            parts.append(chr(10).join(f"• {n}" for n in noeuds if n))
        positions = d.get('positions', [])
        if isinstance(positions, list) and positions:
            parts.append("Positions :" + chr(10) + chr(10).join(f"→ {p}" for p in positions if p))
        return (chr(10) + chr(10)).join(parts) if parts else ''

    resume_texte = _assemble_resume(data_os)

    # ── os_json minimal pour compatibilite FTS ──
    os_json_str = json.dumps({
        'mots_cles': [t.strip() for t in data_os.get('tags', '').split(',') if t.strip()],
        'conclusions': data_os.get('positions', []),
        'sujet': data_os.get('fil_conducteur', ''),
    }, ensure_ascii=False)

    # ── os_riche : JSON complet des 7 composantes ──
    _os_keys = ['fil_conducteur', 'noeuds', 'positions', 'questions_ouvertes',
                'formulations_cles', 'climat', 'ramifications']
    os_riche_str = json.dumps(
        {k: data_os.get(k, '' if k in ('fil_conducteur', 'climat') else []) for k in _os_keys},
        ensure_ascii=False
    )

    return {
        'titre':             data_os.get('titre', 'Sans titre')[:120],
        'sujet_principal':   data_os.get('tags', '')[:120],
        'tags':              data_os.get('tags', '')[:250],
        'categories':        data_os.get('categories', '')[:100],
        'resume_texte':      resume_texte,
        'os_json':           os_json_str,
        'os_riche':          os_riche_str,
        'date_conversation': date_conversation,
        'mask_id':           settings.get('mask_id', 'lia'),
    }


# ══════════════════════════════════════════
# SYNTHESE ONGLET
# ══════════════════════════════════════════

async def generate_tab_synthesis(tab_id: str, settings: dict) -> dict:
    """
    Genere une synthese courte du contenu d'un onglet.
    Retourne : { synthesis: str, tab_name: str }
    """
    messages = get_messages(tab_id, limit=200)
    if not messages:
        return {}

    tab      = get_thread(tab_id)
    tab_name = tab.get('name', 'Onglet') if tab else 'Onglet'

    provider = settings.get('provider', '')
    api_keys = settings.get('api_keys', {})
    if not provider or not api_keys.get(provider):
        return {}

    conv_text = chr(10).join(
        f"{'Utilisateur' if m['role'] == 'user' else 'Assistant'} : {m['content'][:600]}"
        for m in messages
    )

    prompt = (
        f"Voici le contenu d'une discussion intitulee \"{tab_name}\"." + chr(10) + chr(10)
        + conv_text + chr(10) + chr(10)
        + "Redige une synthese courte (3 a 6 lignes maximum) a la 2eme personne (tu)." + chr(10)
        + "Couvre : le sujet aborde, les points cles discutes, les decisions ou conclusions si presentes." + chr(10)
        + "Ton : neutre et factuel. Commence directement par les faits, sans formule d'introduction." + chr(10)
        + "Si la discussion est tres courte ou n'a pas abouti, resume simplement ce qui y figure."
    )

    try:
        synthesis = await call_llm(
            messages    = [{'role': 'user', 'content': prompt}],
            provider    = provider,
            max_tokens  = 300,
            temperature = 0.2,
            api_keys    = api_keys,
            model       = settings.get('model'),
        )
        return {'synthesis': synthesis.strip(), 'tab_name': tab_name}
    except Exception as e:
        print(f"[BIBLIO] Erreur generation synthese onglet : {e}")
        return {}


# ══════════════════════════════════════════
# REPRISE ARCHIVE
# ══════════════════════════════════════════

async def resume_from_archive(entry: dict, settings: dict) -> str:
    """
    Genere une courte question de relance (1-2 phrases) a partir
    d'une entree de la bibliotheque.
    """
    provider = settings.get('provider', '')
    api_keys = settings.get('api_keys', {})
    if not provider or not api_keys.get(provider):
        return "On reprend ?"

    titre  = entry.get('titre', '')
    resume = entry.get('resume_texte', '')

    prompt = (
        f"Voici le resume d'une conversation archivee intitulee \"{titre}\" :" + chr(10) + chr(10)
        + resume + chr(10) + chr(10)
        + "L'utilisateur souhaite reprendre cette discussion dans un nouveau fil." + chr(10)
        + "Redige une question de relance courte (1 a 2 phrases maximum), neutre et naturelle, "
        + "a la 2eme personne (tu). Elle doit inviter a continuer sans reformuler le resume. "
        + "Commence directement par la question, sans formule d'introduction."
    )

    try:
        relance = await call_llm(
            messages    = [{'role': 'user', 'content': prompt}],
            provider    = provider,
            max_tokens  = 80,
            temperature = 0.4,
            api_keys    = api_keys,
            model       = settings.get('model'),
        )
        return relance.strip()
    except Exception as e:
        print(f"[BIBLIO] Erreur resume_from_archive : {e}")
        return "On reprend ?"
