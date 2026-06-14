# -*- coding: utf-8 -*-
"""
Test hors-ligne de la recherche par sens dans les conversations.

Le vrai modèle d'embeddings n'est pas chargé en test (pas de réseau/poids) :
on substitue `modules.memory._embed` par un vecteur déterministe basé sur des
mots-clés, ce qui permet de vérifier la logique de bout en bout (rattrapage
des embeddings manquants, calcul de similarité, tri, format du résultat) sans
dépendre du modèle réel. `_serialize_embedding`/`_parse_embedding`/`_cosine`
restent les implémentations réelles (numpy + JSON).

Vérifie :
  1. search_conversations() renvoie [] pour une requête vide.
  2. Les messages sans embedding sont indexés au premier appel (rattrapage).
  3. Le message le plus proche par le sens arrive en tête, avec thread_name.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import core.database as db
import modules.memory as memory


MOTS_CLES = ["chat", "chien", "python"]


def _fake_embed(text):
    """Vecteur déterministe : compte d'occurrences des mots-clés, normalisé."""
    text = (text or "").lower()
    vec = np.array([float(text.count(m)) for m in MOTS_CLES])
    if not vec.any():
        vec = np.array([1e-6, 1e-6, 1e-6])
    norme = np.linalg.norm(vec)
    return vec / norme


def setup_module(_module=None):
    tmpdir = tempfile.mkdtemp(prefix="nimm_test_recherche_")
    db.DATA_DIR = tmpdir
    db.set_user_context('test_recherche')
    db.init_db('test_recherche')
    memory._embed = _fake_embed


def test_recherche_vide():
    from modules.recherche import search_conversations
    assert search_conversations("") == []
    assert search_conversations("   ") == []


def test_recherche_par_sens():
    from modules.recherche import search_conversations

    th1 = 'th-recherche-1'
    th2 = 'th-recherche-2'
    db.create_thread(th1, 'Discussion chats', 'chat')
    db.create_thread(th2, 'Discussion code', 'chat')

    db.add_message(th1, 'user', "Mon chat adore dormir sur le clavier.")
    db.add_message(th1, 'assistant', "Les chats aiment la chaleur du clavier, en effet.")
    db.add_message(th2, 'user', "Comment écrire une boucle en python ?")
    db.add_message(th2, 'assistant', "Avec for ... in ..., en python c'est simple.")

    # Aucun embedding encore calculé à ce stade
    avant = db.get_messages_missing_embedding(100)
    assert len(avant) == 4

    resultats = search_conversations("Parle-moi de mon chat", k=4)

    # Rattrapage : tous les messages doivent maintenant avoir un embedding
    apres = db.get_messages_missing_embedding(100)
    assert len(apres) == 0

    assert len(resultats) > 0
    premier = resultats[0]
    assert premier['thread_id'] == th1
    assert premier['thread_name'] == 'Discussion chats'
    assert 'chat' in premier['content'].lower()
    assert 'score' in premier and 'role' in premier and 'created_at' in premier

    # Les résultats sont triés par score décroissant
    scores = [r['score'] for r in resultats]
    assert scores == sorted(scores, reverse=True)
    print("OK  search_conversations classe par pertinence et indexe les messages")


if __name__ == '__main__':
    setup_module()
    test_recherche_vide()
    test_recherche_par_sens()
    print("\nTous les tests passent.\n")
