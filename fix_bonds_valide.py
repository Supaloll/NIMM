"""
fix_bonds_valide.py — Ajoute valide_par_laurent=True sur tous les bonds existants
en base qui ne l'ont pas encore.

Exécuter une seule fois :
    python fix_bonds_valide.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from core.database import list_prompts, save_prompt, get_all_users, set_user_context
except ImportError as e:
    print(f"Erreur d'import : {e}")
    sys.exit(1)

_users = get_all_users()
if not _users:
    print("Aucun utilisateur trouvé. Lancez NIMM au moins une fois.")
    sys.exit(1)
set_user_context(_users[0]["id"])
print(f"Contexte utilisateur : {_users[0].get('name', _users[0]['id'])}\n")

bonds = list_prompts("skill")
if not bonds:
    print("Aucun bond en base.")
    sys.exit(0)

corrige = 0
deja_ok = 0
for bid, sk in bonds.items():
    meta = dict(sk.get("meta") or {})
    if meta.get("valide_par_laurent"):
        deja_ok += 1
        continue
    meta["valide_par_laurent"] = True
    save_prompt(bid, sk.get("label", ""), sk.get("text", ""), type="skill", meta=meta)
    print(f"  ✓ Corrigé : {sk.get('label', bid)}")
    corrige += 1

print(f"\nRésultat : {corrige} bond(s) mis à jour, {deja_ok} déjà conformes.")
print("Les bonds sont maintenant détectables automatiquement par CoaNIMM.")
