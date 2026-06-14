"""
Recherche par sens dans l'historique des conversations.

Réutilise l'infrastructure d'embeddings de `modules/memory.py` (même modèle,
même format sérialisé que `modules/enrichissement.py`). Les messages sont
indexés à la demande (rattrapage progressif par lots) plutôt qu'à l'envoi,
pour ne pas alourdir la conversation en cours.
"""

# Nombre de messages sans embedding traités à chaque appel de recherche.
_BACKFILL_BATCH = 40


def _backfill_embeddings():
    """Calcule les embeddings manquants pour un lot de messages récents."""
    try:
        from modules.memory import _embed, _serialize_embedding
    except Exception:
        return
    from core.database import get_messages_missing_embedding, save_message_embedding
    for msg in get_messages_missing_embedding(_BACKFILL_BATCH):
        try:
            v = _embed(msg['content'])
            if v is not None:
                save_message_embedding(msg['id'], _serialize_embedding(v))
        except Exception as e:
            print(f"[RECHERCHE] Embedding impossible pour le message {msg['id']} : {e}")


def search_conversations(query, k=8):
    """Recherche par sens dans les messages de tous les fils.
    Retourne une liste de dicts {thread_id, thread_name, role, content, created_at, score},
    triée par pertinence, ou [] si la requête est vide ou les embeddings indisponibles."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        from modules.memory import _embed, _parse_embedding, _cosine
    except Exception:
        return []

    _backfill_embeddings()

    qv = _embed(query)
    if qv is None:
        return []

    from core.database import get_all_message_embeddings
    scored = []
    for msg in get_all_message_embeddings():
        rv, _m = _parse_embedding(msg.get("embedding"))
        if rv is None:
            continue
        scored.append((_cosine(qv, rv), msg))
    scored.sort(key=lambda x: x[0], reverse=True)

    resultats = []
    for s, msg in scored[:k]:
        contenu = msg.get("content") or ""
        resultats.append({
            "thread_id":   msg.get("thread_id"),
            "thread_name": msg.get("thread_name"),
            "role":        msg.get("role"),
            "content":     contenu[:300] + ("…" if len(contenu) > 300 else ""),
            "created_at":  msg.get("created_at"),
            "score":       round(float(s), 3),
        })
    return resultats
