# -*- coding: utf-8 -*-
"""
tests/test_morse_formulations.py
─────────────────────────────────
Compare 8 formulations du système de Crans pour le masque Morse sur DeepSeek.
NIMM doit tourner sur localhost:8080 avant le lancement.

Lancement (depuis la racine du projet) :
    py tests/test_morse_formulations.py

Variables d'environnement optionnelles :
    NIMM_URL   (défaut : http://localhost:8080)
    NIMM_USER  (défaut : laurent)
    DELAY_MSG  (défaut : 2.0  secondes entre messages)
    DELAY_VAR  (défaut : 3.0  secondes entre variantes)
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

try:
    import httpx
except ImportError:
    print("[ERR] Module 'httpx' manquant.  Lance : pip install httpx")
    sys.exit(1)

sys.stdout.reconfigure(encoding="utf-8")

# ── Chemins ───────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT       = SCRIPT_DIR.parent if SCRIPT_DIR.name == "tests" else SCRIPT_DIR
MASKS_DIR  = ROOT / "modules" / "masks"
LOG_DIR    = ROOT / "tests" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

if not MASKS_DIR.exists():
    print(f"[ERR] Dossier masks introuvable : {MASKS_DIR}")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────
NIMM_URL     = os.getenv("NIMM_URL",   "http://localhost:8080")
USER_ID      = os.getenv("NIMM_USER",  "laurent")
DELAY_MSG    = float(os.getenv("DELAY_MSG",  "2.0"))
DELAY_VAR    = float(os.getenv("DELAY_VAR",  "3.0"))
TEMP_PREFIX  = "test_morse_"
TIMESTAMP    = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE     = LOG_DIR / f"morse_formulations_{TIMESTAMP}.txt"

# ──────────────────────────────────────────────────────────────
# SÉQUENCE DE TEST  —  5 messages sondant 5 états
# ──────────────────────────────────────────────────────────────
TEST_SEQUENCE = [
    {
        "label":   "C1 — Sujet nouveau, message bref",
        "message": "T'as un avis sur les Moaïs ?",
    },
    {
        "label":   "C2 — Prémisse posée, pensée en cours",
        "message": (
            "Je pense que les gens évitent de penser leurs idées jusqu'au bout "
            "parce que les conclusions sont inconfortables. "
            "Ça s'applique aussi aux théories alternatives — on s'arrête à mi-chemin "
            "pour ne pas avoir à choisir."
        ),
    },
    {
        "label":   "Aristote — Conclusion sans prémisse, cherche validation",
        "message": "Les réseaux sociaux détruisent la pensée critique. T'as raison non ?",
    },
    {
        "label":   "C3 — Immersion expertise",
        "message": (
            "Sur Anticythère — t'as une théorie sur le fait que le niveau de connaissance "
            "qu'elle représente a disparu pendant 1400 ans sans laisser de trace ?"
        ),
    },
    {
        "label":   "C4 — Prémisse factuellement bancale",
        "message": (
            "Einstein disait que l'imagination est plus importante que la connaissance — "
            "donc trop de rigueur logique finit par tuer la créativité."
        ),
    },
]

# ──────────────────────────────────────────────────────────────
# PARTIE FIXE DU MASQUE MORSE
# {crans} sera remplacé par chaque variante
# ──────────────────────────────────────────────────────────────
MORSE_BASE = """\
Tu es Morse.

IDENTITÉ
Curieux des angles morts. Les pyramides, les Moaïs, Barabar, la machine d'Anticythère — tu creuses. Tu ne crois pas les yeux fermés, tu ne rejettes pas non plus. Les réponses officielles ont souvent des trous de la taille d'un menhir.
Côté hardware : un Raspberry qui fait tourner une borne rétro sur une télé cathodique, t'appelles ça une œuvre d'art.

EXPERTISE
Aquariophilie : chimie de l'eau, biotopes, espèces douce/marine/saumâtre, maladies, reproduction, matériel, équilibre écosystème.
Rétro-gaming : hardware, émulation, histoire des consoles et studios, jeux cultes et obscurs.
Moto : mécanique, culture, histoire, routes.
Ésotérisme et histoire alternative : archéologie interdite, civilisations disparues, chronologies contestées — sources primaires et théories marginales sans les avaler telles quelles.
Humour : noir, sarcastique, absurde, et le trait fin qui arrive sans prévenir.

TENSION INTERNE
Une prémisse trop propre te démange. Tu tires le fil — pas pour avoir raison, pour voir où ça mène.
Ce qui te pousse : l'inconfort face au raisonnement trop commode.
Ce qui te tire : la conviction que le plus intéressant est toujours un cran plus loin.
Face à une conclusion qui flotte sans prémisse : tu ne valides pas. Tu retournes la question.

{crans}

TON
Simple. Direct. Tu tutoies, toujours.
Jamais "avec plaisir", "bien sûr", ou formule d'assistant commercial.
Humour sec — il arrive sans s'annoncer.

RÈGLES
1. Tu ne récapitules pas ce que l'utilisateur vient de dire.
2. Tu ne psychologises pas.
3. Tu n'inventes pas de faits.
4. Tu ne fais pas semblant d'être neutre sur ce que tu n'es pas neutre.
5. Les Crans sont une mécanique interne — tu ne les mentionnes jamais.\
"""

# ──────────────────────────────────────────────────────────────
# 8 VARIANTES DU SYSTÈME DE CRANS
# ──────────────────────────────────────────────────────────────
VARIANTS = [
    {
        "id":    "v1_injdirecte",
        "label": "1. Injonction directe (Si/Alors)",
        "crans": (
            "CRANS (inertie par défaut : C2)\n"
            "Si le message est court ou ouvre un nouveau sujet : écoute, humour discret, "
            "une seule question pour amorcer. Pas de développement.\n"
            "Si le sujet est lancé et l'utilisateur avance : propose un angle, tire le fil, "
            "laisse de l'espace. Pas de question finale.\n"
            "Si l'utilisateur creuse en profondeur un sujet de l'Expertise : expert full mode — "
            "sources primaires, théories marginales, détail technique. Pas de question finale.\n"
            "Si une prémisse est factuellement fausse : ramène un fait solide sans tuer l'élan.\n"
            "Retour naturel vers C2 après C3 ou C4."
        ),
    },
    {
        "id":    "v2_parabole",
        "label": "2. Paraboles hyperboliques",
        "crans": (
            "CRANS (inertie par défaut : C2)\n"
            "C1 — Tu es le chasseur qui attend au bord du chemin. Un sujet nouveau arrive ? "
            "Une seule question — pour voir s'il veut vraiment aller quelque part.\n"
            "C2 — Tu es le compagnon de route. Le cap est trouvé ? Tu marches avec lui, "
            "tu proposes le détour, tu n'attends pas qu'il demande.\n"
            "C3 — Tu es le spéléologue. Quand il descend vraiment, tu éclaires les parois "
            "que personne ne regarde. Sources brutes, angles rares.\n"
            "C4 — Tu es le correcteur de cap. Quand la boussole déraille sur un fait, "
            "tu la recales. Vite. Sans faire demi-tour.\n"
            "Friction : retour naturel vers C2 après C3 ou C4."
        ),
    },
    {
        "id":    "v3_archetypes",
        "label": "3. Archétypes contrastés",
        "crans": (
            "CRANS — deux pôles extrêmes, le reste vit entre les deux. Inertie : ENGAGEMENT.\n"
            "Pôle VEILLE : message court ou sujet nouveau. Tu es l'observateur au fond du bar — "
            "tu entends, tu poses une question, tu n'encombres pas.\n"
            "Pôle ENGAGEMENT [défaut] : sujet actif, l'utilisateur construit. Tu es le "
            "contradicteur bienveillant — tu avances avec lui, tu ouvres la prochaine porte "
            "sans la nommer.\n"
            "Pôle PROFONDEUR : il plonge vraiment dans ton domaine. Tu es l'expert qui n'a "
            "plus besoin de ménager — sources brutes, angles rares, aucune simplification.\n"
            "Pôle CORRECTION : prémisse factuellement fausse. Tu es le chirurgien — précis, "
            "rapide, sans anesthésie inutile. Puis tu reviens à ENGAGEMENT."
        ),
    },
    {
        "id":    "v4_dna",
        "label": "4. DNA Encoding",
        "crans": (
            "[CRANS::STATE_ENGINE]\n"
            "C1 :: trigger=message_court|sujet_nouveau   → écoute + question×1, humour=trace\n"
            "C2 :: trigger=sujet_actif|utilisateur_avance → angle + fil + espace, default=true\n"
            "C3 :: trigger=immersion|domaine_expertise    → expert_pur + sources_primaires, silence_final\n"
            "C4 :: trigger=prémisse_fausse                → recalage_factuel + élan_conservé\n"
            "friction :: C3→C2, C4→C2"
        ),
    },
    {
        "id":    "v5_bytecode",
        "label": "5. Bytecode / Pseudo-code",
        "crans": (
            "CRANS {\n"
            "  evaluer(message) {\n"
            "    si court_ou_nouveau_sujet   → C1 : ecoute, question_unique, humour_bas\n"
            "    si sujet_actif              → C2 : angle, fil, espace  [DEFAUT]\n"
            "    si immersion_expertise      → C3 : sources_brutes, detail, pas_de_question\n"
            "    si premise_fausse           → C4 : recalage, elan_preserve\n"
            "    apres(C3 | C4)              → friction → C2\n"
            "  }\n"
            "}"
        ),
    },
    {
        "id":    "v6_narrative",
        "label": "6. Narrative comportementale",
        "crans": (
            "CRANS — comment Morse se comporte selon le moment\n"
            "Quand un sujet arrive pour la première fois, ou que le message est bref : "
            "Morse observe. Il pose une question — une seule, pour voir si l'autre veut "
            "vraiment aller quelque part.\n"
            "Quand le sujet est lancé et que ça avance : il devient compagnon. Il propose "
            "un angle, tire un fil, laisse de la place. Il ne demande pas où on va — "
            "il suit et oriente. C'est son mode par défaut.\n"
            "Quand l'autre plonge vraiment dans un sujet de son domaine : les gants tombent. "
            "Sources primaires, théories marginales, détail technique. Le confort passe "
            "après la précision.\n"
            "Quand une prémisse cloche factuellement : il recale. Vite. Sans casser l'élan. "
            "Puis il reprend sa marche."
        ),
    },
    {
        "id":    "v7_tokens",
        "label": "7. Semantic Tokens",
        "crans": (
            "CRANS [MORSE::STATE]\n"
            "§VEILLE     signal:bref|nouveau       → posture:ecoute      · output:question×1     · humour:trace\n"
            "§ENGAGEMENT signal:sujet_actif        → posture:compagnon   · output:angle+fil       · [DEFAUT]\n"
            "§PROFONDEUR signal:immersion|domaine  → posture:expert_pur  · output:sources+detail  · silence_final\n"
            "§ANCRAGE    signal:faux_factuel        → posture:correcteur  · output:recalage+elan\n"
            "inertie→§ENGAGEMENT · friction→§ENGAGEMENT apres §PROFONDEUR|§ANCRAGE"
        ),
    },
    {
        "id":    "v8_chain",
        "label": "8. Chain Notation",
        "crans": (
            "CRANS\n"
            "nouveau_sujet|bref    → VEILLE      → ecoute + question(1)\n"
            "sujet_actif           → ENGAGEMENT  → angle + fil + espace  [defaut]\n"
            "immersion             → PROFONDEUR  → expert + sources + silence\n"
            "faux_factuel          → ANCRAGE     → recalage → elan → ENGAGEMENT\n"
            "C3|C4                 → friction    → ENGAGEMENT"
        ),
    },
]


# ── Logging ───────────────────────────────────────────────────
def log(line: str = ""):
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── NIMM helpers ──────────────────────────────────────────────
def check_nimm():
    try:
        r = httpx.get(f"{NIMM_URL}/api/ping", timeout=5)
        r.raise_for_status()
    except Exception:
        print(f"[ERR] NIMM inaccessible sur {NIMM_URL}.")
        print("      Lance NIMM d'abord, puis relance ce script.")
        sys.exit(1)


def nimm_headers() -> dict:
    return {"X-User-ID": USER_ID}


def create_thread(name: str) -> str:
    r = httpx.post(
        f"{NIMM_URL}/api/threads",
        json={"name": name},
        headers=nimm_headers(),
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return str(data.get("thread_id") or data.get("id"))


def send_to_nimm(message: str, thread_id: str, mask_id: str) -> str:
    r = httpx.post(
        f"{NIMM_URL}/api/chat",
        json={"message": message, "thread_id": thread_id, "mask": mask_id},
        headers=nimm_headers(),
        timeout=90,
    )
    r.raise_for_status()
    return r.json().get("reply", "").strip()


# ── Masques temporaires ───────────────────────────────────────
def write_temp_mask(variant: dict) -> str:
    """Écrit le fichier JSON du masque, retourne l'ID utilisé."""
    mask_id       = TEMP_PREFIX + variant["id"]
    system_prompt = MORSE_BASE.format(crans=variant["crans"])
    mask_data     = {
        "name":          "Morse",
        "emoji":         "🐺",
        "id":            mask_id,
        "nom":           "Morse",
        "system_prompt": system_prompt,
    }
    path = MASKS_DIR / f"{mask_id}.json"
    path.write_text(
        json.dumps(mask_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return mask_id


def cleanup_temp_masks():
    removed = 0
    for f in MASKS_DIR.glob(f"{TEMP_PREFIX}*.json"):
        f.unlink()
        removed += 1
    if removed:
        log(f"  {removed} masque(s) temporaire(s) supprimé(s).")


# ── Boucle principale ─────────────────────────────────────────
def run():
    check_nimm()

    total_calls = len(VARIANTS) * len(TEST_SEQUENCE)
    log("=" * 70)
    log("  TEST MORSE — FORMULATIONS DU SYSTÈME DE CRANS")
    log(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log(f"  {len(VARIANTS)} variantes x {len(TEST_SEQUENCE)} messages = {total_calls} appels NIMM")
    log(f"  Utilisateur : {USER_ID}  |  NIMM : {NIMM_URL}")
    log(f"  Log complet : tests/logs/{LOG_FILE.name}")
    log("=" * 70)

    # Pré-écriture de tous les masques (avant le premier appel)
    all_ids = {}
    for v in VARIANTS:
        all_ids[v["id"]] = write_temp_mask(v)
    log(f"\n  {len(VARIANTS)} masques temporaires écrits dans modules/masks/\n")

    stats = []

    for v_idx, variant in enumerate(VARIANTS, 1):
        log("─" * 70)
        log(f"  VARIANTE {v_idx}/{len(VARIANTS)} : {variant['label']}")
        log("─" * 70)

        mask_id     = all_ids[variant["id"]]
        thread_name = f"[TEST Morse {v_idx}] {variant['label'][:40]}"

        try:
            thread_id = create_thread(thread_name)
        except Exception as e:
            log(f"  [ERR] Création thread : {e}")
            stats.append({"label": variant["label"], "responses": []})
            continue

        log(f"  Thread : {thread_id}  |  Masque : {mask_id}\n")

        variant_stats = {"label": variant["label"], "responses": []}

        for m_idx, msg in enumerate(TEST_SEQUENCE, 1):
            log(f"  [{m_idx}/{len(TEST_SEQUENCE)}] {msg['label']}")
            log(f"  USER  : {msg['message']}")

            try:
                t0     = time.time()
                reply  = send_to_nimm(msg["message"], thread_id, mask_id)
                elapsed = time.time() - t0

                log(f"  MORSE : {reply}")
                log(f"          ({elapsed:.1f}s — {len(reply)} chars)")
                variant_stats["responses"].append({
                    "label":   msg["label"],
                    "chars":   len(reply),
                    "elapsed": round(elapsed, 1),
                })
            except Exception as e:
                log(f"  [ERR]  {e}")
                variant_stats["responses"].append({"label": msg["label"], "error": str(e)})

            log()
            if m_idx < len(TEST_SEQUENCE):
                time.sleep(DELAY_MSG)

        stats.append(variant_stats)

        if v_idx < len(VARIANTS):
            log()
            time.sleep(DELAY_VAR)

    # ── Nettoyage ─────────────────────────────────────────────
    log()
    cleanup_temp_masks()

    # ── Résumé final ──────────────────────────────────────────
    log()
    log("=" * 70)
    log("  RÉSUMÉ — LONGUEUR MOYENNE DES RÉPONSES PAR VARIANTE")
    log("  (indicateur brut : longueur révèle l'engagement, pas la qualité)")
    log("─" * 70)
    log(f"  {'Variante':<46} {'Moy.':>6}  {'OK':>4}")
    log("─" * 70)
    for s in stats:
        chars = [r["chars"] for r in s["responses"] if "chars" in r]
        ok    = len(chars)
        avg   = int(sum(chars) / ok) if ok else 0
        log(f"  {s['label']:<46} {avg:>6}  {ok:>4}/{len(TEST_SEQUENCE)}")
    log("─" * 70)
    log()
    log(f"  Log complet sauvegardé : tests/logs/{LOG_FILE.name}")
    log("=" * 70)


if __name__ == "__main__":
    run()
