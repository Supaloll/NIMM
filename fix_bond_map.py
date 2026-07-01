"""
fix_bond_map.py — Met à jour le bond "Plan de trajet pédestre" déjà en base.

Corrections :
- Règle absolue sur le format d'adresse géocodable (plus de "Sortie métro", "angle", etc.)
- output_format='html' explicitement rappelé comme obligatoire
- Suppression des références à PDF

Exécuter une seule fois depuis la racine du projet :
    python fix_bond_map.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from core.database import save_prompt, list_prompts, get_all_users, set_user_context
except ImportError as e:
    print(f"Erreur d'import : {e}")
    sys.exit(1)

_users = get_all_users()
if not _users:
    print("Aucun utilisateur trouvé.")
    sys.exit(1)
set_user_context(_users[0]["id"])

NEW_TEXT = """Quand utiliser ce bond : quand l'utilisateur décrit un trajet à pied et veut
un plan cartographique — avec des tracés colorés, les vrais noms de rue, ses annotations
personnelles (quel trottoir emprunter, où traverser, quels repères). Rendu : carte HTML
interactive Leaflet/OpenStreetMap avec zoom dynamique + section textuelle pour lecteur d'écran.

Méthode :

1. Lire attentivement la description du trajet et extraire :
   - Les waypoints dans l'ordre : adresses, intersections, repères nommés.
   - Pour chaque waypoint : l'annotation utile (ex. "traversée au feu", "trottoir gauche",
     "entrée du parc", "arrêt de bus").
   - La ville (contexte de géocodage).
   - Si plusieurs portions ont des couleurs différentes (aller/retour, variante A/B…),
     les noter comme segments distincts.

2. Construire la liste waypoints au format attendu.
   RÈGLE ABSOLUE pour "address" : utiliser UNIQUEMENT le nom de rue simple + ville,
   géocodable par Nominatim. JAMAIS de descriptions ("Sortie métro", "angle", "entre X et Y").
   Correct : "rue Lecourbe, Paris" ou "6 rue Gager Gabillot, Paris" ou "rue de Vaugirard, Paris".
   Incorrect : "Sortie métro Volontaires", "carrefour rue X / rue Y", "15e arrondissement".
   Pour une intersection, utiliser la rue principale seulement : "rue Lecourbe, Paris" suffit.
   Exemple :
   [
     {"address": "12 rue Lecourbe, Paris", "annotation": "Point de départ — trottoir gauche", "color": "#2c3e50"},
     {"address": "rue de Vaugirard, Paris", "annotation": "Traversée au feu tricolore", "color": "#e74c3c"},
     {"address": "Square Adolphe Chérioux, Paris", "annotation": "Arrivée", "color": "#27ae60"},
   ]

3. Définir les segments si besoin (couleurs différentes par portion) :
   route_segments = [
     {"from_idx": 0, "to_idx": 1, "color": "#e74c3c", "label": "Portion 1 — rue Lecourbe"},
     {"from_idx": 1, "to_idx": 2, "color": "#2980b9", "label": "Portion 2 — rue Vaugirard"},
   ]
   Si une seule couleur suffit, laisser route_segments=None.

4. Appeler nimm_generate_map :
   result = nimm_generate_map(
       title="Mon trajet du mardi",
       city="Paris, France",
       waypoints=waypoints,
       route_segments=route_segments,
       output_format="html",  # TOUJOURS html — carte interactive Leaflet avec zoom dynamique
   )

5. Présenter le résultat :
   - Rapporter le chemin du fichier HTML généré (ouvrable dans un navigateur, zoom dynamique).
   - Signaler tout waypoint non géocodé et proposer une adresse alternative plus simple.
   - Mentionner que le plan a été tracé sur le réseau OSM réel.

Règles importantes :
- "address" = nom de rue simple géocodable, jamais descriptif.
- Ne jamais inventer des coordonnées. Passer les adresses en texte pour le géocodage Nominatim.
- Si Nominatim échoue sur un waypoint, essayer une rue voisine ou un numéro connu dans la rue.
- Mettre les indications de trottoir dans l'annotation, jamais dans l'address.
- Le fichier HTML est interactif : zoom, dézoom, clic sur les marqueurs — parfait pour
  partage avec une personne voyante qui connaît le quartier.
- Pour les villes françaises : "Ville, France" (ex. "Lyon, France") pour Nominatim optimal.
"""

NEW_META = {
    "description": (
        "Générer un plan de trajet pédestre sur fond OpenStreetMap réel, "
        "avec tracés colorés, annotations personnelles et carte HTML interactive "
        "(zoom dynamique, Leaflet). Section textuelle accessible pour lecteurs d'écran."
    ),
    "mots_cles": [
        "plan", "carte", "trajet", "pied", "piéton", "itinéraire", "chemin",
        "rue", "trottoir", "traversée", "carrefour", "quartier", "balade",
        "openstreetmap", "osm", "html", "cartographie", "route", "parcours",
        "navigation", "repère", "couleur", "tracé", "map",
    ],
    "helper": "nimm_generate_map(title, city, waypoints, route_segments, output_format)",
    "valide": True,
    "valide_par_laurent": True,
    "version": 2,
}

existing = list_prompts("skill")
found = []
for sid, sk in (existing.items() if isinstance(existing, dict) else {}):
    lbl = (sk.get("label") or "").lower()
    if "carte" in lbl or "trajet" in lbl or "openstreetmap" in lbl or "map" in lbl:
        found.append((sid, sk))

if not found:
    print("Aucun bond map trouvé en base. Lancez bonds/seed_bond_map.py pour le créer.")
    sys.exit(0)

for sid, sk in found:
    print(f"Bond trouvé : id={sid}, label={sk.get('label')}")
    entry = save_prompt(
        sid,
        "Plan de trajet pédestre sur fond OpenStreetMap",
        NEW_TEXT,
        type="skill",
        meta=NEW_META,
    )
    if entry:
        print(f"✓ Bond mis à jour (id={sid})")
    else:
        print(f"✗ Échec mise à jour (id={sid})")
