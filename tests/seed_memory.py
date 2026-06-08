# -*- coding: utf-8 -*-
"""
seed_memory.py — Peuple la mémoire NIMM avec des données de test réelles.
Lance une seule fois : python tests/seed_memory.py
Écrit directement en DB — ne passe pas par le LLM.
"""
import sqlite3
import uuid
import json
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')


DB_PATH = "data/nimm.db"

def _compute_embedding(sujet: str, predicat: str, objet: str):
    """Calcule l'embedding d'un souvenir si le modèle est disponible. Retourne None sinon."""
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from modules.memory import _embed, _is_embeddings_enabled
        if not _is_embeddings_enabled():
            return None
        vec = _embed(f"{sujet} {predicat} {objet}")
        if vec is not None:
            return json.dumps(vec.tolist())
    except Exception as e:
        print(f"  ⚠️  Embedding non calculé ({e})")
    return None

MEMORIES = [
    # Laurent — identité
    ("trait",    "Laurent", "prenom",           "Laurent",                    "identite", 2, "permanent"),
    ("trait",    "Laurent", "metier",            "routier (chauffeur PL)",     "identite", 4, "persistant"),
    ("trait",    "Laurent", "domicile",          "Ferrals-les-Corbières, Aude","identite", 4, "persistant"),
    ("trait",    "Laurent", "origine",           "alsacien d'origine",         "identite", 3, "permanent"),
    ("trait",    "Laurent", "valeur_principale", "interfaces simples et naturelles","identite", 1, "permanent"),
    # Laurent — famille
    ("relation", "Laurent", "conjoint",          "Nadia",                      "identite", 3, "permanent"),
    ("relation", "Laurent", "enfant_1",          "Maïssane (17 ans, terminale)","identite", 3, "permanent"),
    ("relation", "Laurent", "enfant_2",          "Maya (12 ans, collège)",     "identite", 3, "permanent"),
    ("relation", "Laurent", "enfant_3",          "Innès (22 ans, droit Nancy)","identite", 3, "permanent"),
    # Laurent — projets
    ("trait",    "Laurent", "projet_principal",  "NIMM — assistant IA famille","activite", 4, "persistant"),
    # Nadia
    ("trait",    "Nadia",   "metier",            "couturière, gérante LIMM Couture","identite", 4, "persistant"),
    ("trait",    "Nadia",   "projet_principal",  "LIMM Couture et Créations",  "activite", 4, "persistant"),
    # Relations symétriques
    ("relation", "Nadia",   "conjoint",          "Laurent",                    "identite", 3, "permanent"),
]

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    inserted = 0
    skipped  = 0

    for (type_, sujet, predicat, objet, memoire_type, profondeur, type_temporal) in MEMORIES:
        # Vérifier si déjà présent (sujet + predicat)
        c.execute("SELECT key FROM memory WHERE sujet=? AND predicat=?", (sujet, predicat))
        existing = c.fetchone()
        if existing:
            print(f"  ⏭️  Existe déjà : {sujet} / {predicat}")
            skipped += 1
            continue

        key = f"mem_{uuid.uuid4().hex[:8]}"
        categorie = {
            "metier": "profession", "employeur": "profession",
            "projet_principal": "projets", "projet_secondaire": "projets",
            "conjoint": "famille", "enfant_1": "famille", "enfant_2": "famille",
            "enfant_3": "famille", "enfant_4": "famille", "pere": "famille", "mere": "famille",
            "loisir_principal": "loisirs", "sport": "loisirs",
            "valeur_principale": "croyances", "maladie": "sante",
        }.get(predicat, "quotidien")

        embedding = _compute_embedding(sujet, predicat, objet)
        c.execute("""
            INSERT INTO memory
            (key, type, sujet, predicat, objet, valeur, confiance, valence,
             sensibilite, cumulatif, categorie, profondeur, type_temporal,
             expiration, timestamp, repetitions, poids, embedding,
             memoire_type, last_reinforced)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            key, type_, sujet, predicat, objet, objet,
            1.0, 0.0, "neutre", 0, categorie, profondeur, type_temporal,
            None, now, 0, 1.0, embedding, memoire_type, None
        ))
        emb_label = "✅" if embedding else "✅ (sans embedding)"
        print(f"  {emb_label} {sujet} / {predicat} = {objet}")
        inserted += 1

    conn.commit()
    conn.close()
    print(f"\n  Résultat : {inserted} souvenirs ajoutés, {skipped} déjà présents.")
    print(f"  Ouvre NIMM et pose tes questions — la mémoire est prête.\n")


def patch_embeddings():
    """
    Calcule les embeddings manquants pour les souvenirs déjà en base.
    Lance après seed si les embeddings sont activés dans ⚙️.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT key, sujet, predicat, objet FROM memory WHERE embedding IS NULL")
    rows = c.fetchall()
    if not rows:
        print("  ✅ Tous les souvenirs ont déjà un embedding.")
        conn.close()
        return

    print(f"\n  🔄 Calcul embeddings manquants ({len(rows)} souvenirs)...")
    patched = 0
    for (key, sujet, predicat, objet) in rows:
        embedding = _compute_embedding(sujet, predicat, objet)
        if embedding:
            c.execute("UPDATE memory SET embedding=? WHERE key=?", (embedding, key))
            print(f"  ✅ Patché : {sujet} / {predicat}")
            patched += 1

    conn.commit()
    conn.close()
    print(f"  Résultat : {patched}/{len(rows)} embeddings calculés.\n")


if __name__ == "__main__":
    import sys
    if "--patch-embeddings" in sys.argv:
        patch_embeddings()
    else:
        main()
        patch_embeddings()   # Toujours tenté après le seed — no-op si embeddings désactivés
