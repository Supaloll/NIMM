"""
seed_skill_map.py — Insère la fiche skill "Plan de trajet pédestre (OpenStreetMap)"
dans la Promptothèque de NIMM.

Exécuter une seule fois depuis la racine du projet :
    python seed_skill_map.py

Prérequis (à installer une fois) :
    pip install osmnx folium contextily geopandas matplotlib geopy --break-system-packages
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from core.database import save_prompt, list_prompts, get_all_users, set_user_context
except ImportError as e:
    print(f"Erreur d'import : {e}")
    print("Lancez ce script depuis la racine du projet NIMM.")
    sys.exit(1)

# Initialiser le contexte utilisateur (requis par la DB multi-profils)
_users = get_all_users()
if not _users:
    print("Aucun utilisateur trouvé dans la base. Lancez NIMM au moins une fois.")
    sys.exit(1)
set_user_context(_users[0]["id"])
print(f"Contexte utilisateur : {_users[0].get('name', _users[0]['id'])}")

SKILL_LABEL = "Plan de trajet pédestre sur fond OpenStreetMap"

SKILL_TEXT = """Quand utiliser ce skill : quand l'utilisateur décrit un trajet à pied et veut
un plan cartographique — avec des tracés colorés, les vrais noms de rue, ses annotations
personnelles (quel trottoir emprunter, où traverser, quels repères). Exportable en PDF.

Méthode :

1. Lire attentivement la description du trajet et extraire :
   - Les waypoints dans l'ordre : adresses, intersections, repères nommés.
   - Pour chaque waypoint : l'annotation utile (ex. "traversée au feu", "trottoir gauche",
     "entrée du parc", "arrêt de bus").
   - La ville (contexte de géocodage).
   - Si plusieurs portions ont des couleurs ou des statuts différents (trajet aller/retour,
     variante A/B…), les noter comme segments distincts.

2. Construire la liste waypoints au format attendu :
   [
     {"address": "12 rue Lecourbe, Paris", "annotation": "Point de départ — trottoir gauche", "color": "#2c3e50"},
     {"address": "Carrefour rue Vaugirard / rue Lecourbe", "annotation": "Traversée au feu tricolore", "color": "#e74c3c"},
     {"address": "Square Adolphe Chérioux, Paris", "annotation": "Arrivée", "color": "#27ae60"},
   ]

3. Définir les segments si besoin (couleurs différentes par portion) :
   route_segments = [
     {"from_idx": 0, "to_idx": 1, "color": "#e74c3c", "label": "Portion 1 — rue Lecourbe"},
     {"from_idx": 1, "to_idx": 2, "color": "#2980b9", "label": "Portion 2 — rue Vaugirard"},
   ]
   Si une seule couleur suffit, laisser route_segments=None (une couleur par défaut sera assignée).

4. Appeler nimm_generate_map :
   result = nimm_generate_map(
       title="Mon trajet du mardi",
       city="Paris, France",
       waypoints=waypoints,
       route_segments=route_segments,
       output_format="pdf",
   )

5. Présenter le résultat :
   - Lire le retour de nimm_generate_map et rapporter le chemin du PDF généré.
   - Lire la liste des waypoints géocodés pour confirmer que chaque adresse a bien
     été trouvée dans OpenStreetMap.
   - Si une adresse n'a pas été trouvée, le signaler clairement et proposer des
     formulations alternatives (ex. "intersection de X et Y" au lieu du numéro de rue).
   - Mentionner que le plan a été tracé sur le réseau OSM réel — les noms de rue
     sont ceux d'OpenStreetMap, pas inventés.

Règles importantes :
- Ne jamais inventer des coordonnées. Toujours passer les adresses en texte et laisser
  Nominatim géocoder — si Nominatim échoue, reporter l'erreur à l'utilisateur.
- Si l'utilisateur mentionne "trottoir gauche/droite" ou "côté pair/impair", ajouter
  cette précision dans l'annotation du waypoint concerné. La géométrie du trottoir
  n'est pas toujours disponible dans OSM, mais l'annotation textuelle reste visible
  sur la carte.
- Le plan est destiné à être partagé avec des personnes voyantes pour vérification.
  Encourager l'utilisateur à faire valider le PDF par quelqu'un qui connaît le quartier.
- Pour les villes françaises, écrire la ville au format "Nom, France"
  (ex. "Lyon, France") pour un géocodage Nominatim optimal.
"""

SKILL_META = {
    "description": (
        "Générer un plan de trajet pédestre sur fond OpenStreetMap réel, "
        "avec tracés colorés, annotations personnelles et export PDF."
    ),
    "mots_cles": [
        "plan", "carte", "trajet", "pied", "piéton", "itinéraire", "chemin",
        "rue", "trottoir", "traversée", "carrefour", "quartier", "balade",
        "openstreetmap", "osm", "pdf", "cartographie", "route", "parcours",
        "navigation", "repère", "couleur", "tracé", "map",
    ],
    "helper": "nimm_generate_map(title, city, waypoints, route_segments, output_format)",
    "valide": True,
    "version": 1,
}


def main():
    existing = list_prompts("skill")
    for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
        lbl = (sk.get("label") or "").lower()
        if "carte" in lbl or "trajet" in lbl or "openstreetmap" in lbl or "map" in lbl:
            print(f"Skill similaire déjà présent (id={sid}) : {sk.get('label')}")
            print("Supprimez-le d'abord si vous voulez le remplacer.")
            return

    entry = save_prompt(None, SKILL_LABEL, SKILL_TEXT, type="skill", meta=SKILL_META)
    if entry:
        skill_id = entry.get("id") or entry.get("prompt_id") or "?"
        print(f"Skill créé (id={skill_id}) : {SKILL_LABEL}")
    else:
        print("Erreur lors de la création du skill.")


if __name__ == "__main__":
    main()
