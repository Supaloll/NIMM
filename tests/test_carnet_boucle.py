# -*- coding: utf-8 -*-
"""
test_carnet_boucle.py
=====================
Simule 80 messages sur un fil NIMM pour observer le comportement du Carnet de bord.
- 8 sujets de 10 messages chacun (changement de sujet tous les 10 tours)
- Utilise /api/chat (route synchrone)
- Le patch DEBUG CARNET dans hub.py ecrit dans tests/carnet_debug.log
- Ce script genere en plus un rapport court : tests/carnet_rapport.txt

USAGE : python tests/test_carnet_boucle.py
NIMM doit etre lance (localhost:8000).
"""

import requests
import time
import os
import json

# -- Config ---------------------------------------------
BASE_URL  = "http://localhost:8080"
USER_ID   = "laurent"
NB_MSG    = 80
DELAI_SEC = 3       # secondes entre chaque message (laisser le carnet se generer)
LOG_PATH  = os.path.join(os.path.dirname(__file__), "carnet_debug.log")
RAPPORT   = os.path.join(os.path.dirname(__file__), "carnet_rapport.txt")

# -- 8 sujets x 10 messages -----------------------------
SUJETS = [
    # Sujet 1 : Camion / travail
    [
        "Aujourd'hui j'ai fait la route Paris-Lyon, pas trop de trafic.",
        "Mon camion a un petit bruit cote moteur depuis ce matin.",
        "J'ai charge 24 tonnes de palettes ce matin a l'entrepot.",
        "Le chronotachygraphe m'a donne une alerte, je dois regarder ca.",
        "Mon chef m'a appele pour une livraison urgente demain a 5h.",
        "J'aime bien rouler la nuit, c'est plus calme sur les autoroutes.",
        "J'ai croise un collegue sur une aire d'autoroute, on a bu un cafe.",
        "Les nouvelles normes Euro 7 vont compliquer la vie des transporteurs.",
        "Je dois renouveler ma carte conducteur dans trois mois.",
        "Cette semaine j'ai fait 3200 kilometres au total.",
    ],
    # Sujet 2 : Cuisine
    [
        "J'ai essaye de faire une tarte aux pommes hier soir.",
        "Ma femme m'a appris a faire une bechamel sans grumeaux.",
        "Je cherche une bonne recette de pot-au-feu pour l'hiver.",
        "J'ai achete un nouveau couteau de cuisine, ca change tout.",
        "Le tajine que j'ai prepare dimanche etait vraiment bon.",
        "Je rate toujours mes crepes, elles accrochent a la poele.",
        "Est-ce qu'on peut congeler du gratin dauphinois ?",
        "J'ai decouvert les epices ras-el-hanout, c'est delicieux.",
        "Ma fille veut qu'on fasse des sushis maison ce weekend.",
        "J'ai trouve un marche avec de bons legumes frais pas loin.",
    ],
    # Sujet 3 : Jardinage
    [
        "J'ai plante des tomates ce weekend, j'espere qu'il ne gele plus.",
        "Mon carre de courgettes envahit tout le jardin.",
        "Est-ce que je dois tailler mes rosiers maintenant ?",
        "J'ai mis du compost autour de mes plants de haricots.",
        "Les limaces ont mange toutes mes salades cette nuit.",
        "Je veux installer un systeme d'arrosage automatique cet ete.",
        "Mon voisin m'a donne des graines de basilic a planter.",
        "Les pommes de terre que j'ai recoltees sont enormes cette annee.",
        "J'hesite a planter un arbre fruitier, un pommier ou un poirier.",
        "Mon gazon est tout jaune, je pense que c'est le manque d'eau.",
    ],
    # Sujet 4 : Voyage
    [
        "On pense partir en vacances en Espagne cet ete.",
        "Je n'ai jamais pris l'avion, ca m'angoisse un peu.",
        "Ma femme veut voir la Sagrada Familia a Barcelone.",
        "On hesite entre louer un appartement ou aller a l'hotel.",
        "J'ai vu des prix interessants pour des vacances en Crete.",
        "La derniere fois qu'on est partis c'etait a la montagne en hiver.",
        "Les enfants preferent la mer, moi je prefere la campagne.",
        "Est-ce qu'il faut une carte europeenne de sante pour voyager en Espagne ?",
        "On pourrait faire la route jusqu'en Italie avec le camion familial.",
        "Je reve de voir les fjords en Norvege un jour.",
    ],
    # Sujet 5 : Football
    [
        "Tu as vu le match hier soir ? C'etait serre.",
        "Je suis supporter de l'OL depuis tout petit.",
        "Mon fils commence a jouer au foot dans un club local.",
        "La Ligue des Champions cette annee est vraiment imprevisible.",
        "Je trouve que les arbitres sifflent trop de hors-jeux.",
        "Le PSG a encore depense une fortune pour un joueur.",
        "J'ai joue au foot amateur jusqu'a 35 ans, le genou m'a lache.",
        "Les retransmissions a la tele sont de plus en plus cheres.",
        "La Coupe du Monde 2026 va se jouer aux Etats-Unis.",
        "Mon equipe favorite a perdu trois matchs de suite, c'est decavant.",
    ],
    # Sujet 6 : Musique
    [
        "J'ecoute beaucoup de rock des annees 80 sur la route.",
        "J'ai redecouvert AC/DC cette semaine, c'est intemporel.",
        "Ma fille m'a fait ecouter du rap francais, c'est pas si mal.",
        "J'aurais voulu apprendre la guitare quand j'etais jeune.",
        "La radio en camion c'est mon meilleur compagnon de route.",
        "J'ai vu un concert de Johnny Hallyday a l'epoque, memorable.",
        "Est-ce que Spotify vaut vraiment l'abonnement mensuel ?",
        "Le son dans les nouvelles voitures est vraiment bon maintenant.",
        "Ma femme adore la variete francaise, Brel, Brassens.",
        "J'ai achete des ecouteurs sans fil pour le bureau a la maison.",
    ],
    # Sujet 7 : Sante
    [
        "J'ai mal au dos depuis quelques jours, c'est le siege du camion.",
        "Mon medecin m'a dit de marcher 30 minutes par jour.",
        "J'ai arrete de fumer il y a deux ans, je respire mieux.",
        "Je dors mal quand je suis en deplacement longue distance.",
        "J'ai pris rendez-vous chez le kine pour mes lombaires.",
        "Je mange souvent des sandwiches sur la route, c'est pas terrible.",
        "Mon bilan sanguin est bon mais le cholesterol est limite.",
        "Je fais quelques etirements le matin, ca aide pour le dos.",
        "L'assurance maladie a rembourse mes lunettes cette annee.",
        "Je dois passer une visite medicale obligatoire pour mon permis.",
    ],
    # Sujet 8 : Famille
    [
        "Ma fille a eu ses resultats scolaires, elle est dans la moyenne.",
        "Mon fils veut faire un apprentissage en mecanique.",
        "On fete les 60 ans de ma belle-mere le mois prochain.",
        "Ma femme a repris le travail a mi-temps depuis janvier.",
        "On a adopte un chat il y a trois semaines, il s'appelle Milo.",
        "Mon pere me donne des conseils de jardinage, il s'y connait.",
        "On s'est disputes avec mon frere sur un heritage, c'est complique.",
        "Ma fille veut partir en echange scolaire en Allemagne.",
        "Ce weekend on va rendre visite aux grands-parents en Alsace.",
        "On essaie de diner ensemble en famille au moins trois fois par semaine.",
    ],
]

# -- Rapport en memoire ----------------------------------
rapport_lignes = []

def log(msg):
    print(msg)
    rapport_lignes.append(msg)

# -- Creer le fil de test --------------------------------
def creer_fil():
    r = requests.post(
        f"{BASE_URL}/api/threads",
        json={"name": "[TEST CARNET] Simulation 80 messages"},
        headers={"X-User-ID": USER_ID},
    )
    r.raise_for_status()
    thread_id = r.json()["thread_id"]
    log(f"[INIT] Fil de test cree : {thread_id}")
    return thread_id

# -- Envoyer un message ----------------------------------
def envoyer(thread_id, message, num):
    r = requests.post(
        f"{BASE_URL}/api/chat",
        json={
            "message":   message,
            "thread_id": thread_id,
            "user_id":   USER_ID,
        },
        timeout=60,
    )
    if r.status_code != 200:
        log(f"  [ERREUR] msg #{num} - HTTP {r.status_code} : {r.text[:100]}")
        return None
    return r.json()

# -- Lire le log debug et extraire la derniere entree -----
def lire_derniere_entree_log():
    if not os.path.exists(LOG_PATH):
        return None
    with open(LOG_PATH, encoding="utf-8") as f:
        contenu = f.read()
    blocs = contenu.split("=" * 60)
    if len(blocs) < 2:
        return None
    return blocs[-1].strip()

# -- Extraire stats depuis une entree log -----------------
def extraire_stats(entree):
    if not entree:
        return {}
    stats = {}
    for ligne in entree.splitlines():
        if ligne.startswith("MSG #"):
            parts = ligne.split("|")
            try:
                stats["n_msg"]    = int(parts[0].replace("MSG #", "").strip())
                stats["n_carnet"] = int(parts[1].replace("carnet_notes=", "").strip())
                stats["sp_len"]   = int(parts[2].replace("system_prompt=", "").replace(" car.", "").strip())
                stats["hist"]     = int(parts[3].replace("historique=", "").replace(" msgs", "").strip())
            except Exception:
                pass
        if ligne.strip().startswith("NOTE["):
            stats.setdefault("notes", []).append(ligne.strip())
    return stats

# -- Main ------------------------------------------------
def main():
    # Vider le log debug precedent
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
        print(f"[INIT] Log precedent supprime : {LOG_PATH}")

    thread_id = creer_fil()
    log(f"[INIT] Debut simulation - {NB_MSG} messages, {DELAI_SEC}s entre chaque\n")
    log(f"{'N':>4}  {'Sujet':<12}  {'#Carnet':>7}  {'SP (car)':>9}  {'Hist':>5}  Apercu notes")
    log("-" * 80)

    num_global = 0
    for i_sujet, messages_sujet in enumerate(SUJETS):
        nom_sujet = [
            "Camion", "Cuisine", "Jardinage", "Voyage",
            "Football", "Musique", "Sante", "Famille"
        ][i_sujet]

        for i_msg, message in enumerate(messages_sujet):
            num_global += 1

            reponse = envoyer(thread_id, message, num_global)
            time.sleep(DELAI_SEC)

            entree = lire_derniere_entree_log()
            stats  = extraire_stats(entree)

            n_carnet = stats.get("n_carnet", "?")
            sp_len   = stats.get("sp_len",   "?")
            hist     = stats.get("hist",      "?")
            notes    = stats.get("notes",     [])
            apercu   = " | ".join(n[:50] for n in notes) if notes else "-"

            log(f"{num_global:>4}  {nom_sujet:<12}  {str(n_carnet):>7}  {str(sp_len):>9}  {str(hist):>5}  {apercu}")

            if num_global >= NB_MSG:
                break
        if num_global >= NB_MSG:
            break

    log("\n[FIN] Simulation terminee.")
    log(f"[FIN] Log complet : {LOG_PATH}")
    log(f"[FIN] Fil de test a supprimer manuellement dans NIMM : {thread_id}")

    with open(RAPPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(rapport_lignes))
    print(f"\n[FIN] Rapport sauvegarde : {RAPPORT}")

if __name__ == "__main__":
    main()
