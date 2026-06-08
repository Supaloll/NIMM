# ============================================
# NIMM — modules/intent_gate.py
# Filtre d'intention minimal — règle absolue :
# n'intercepte QUE les messages vides ou parasites.
# Tout le reste passe au LLM + masque actif.
# ============================================

import re
from typing import Optional, Dict, Any

# ── Ces messages triviaux sont gérés par le LLM + masque actif ──
# L'intent gate ne court-circuite plus les salutations/remerciements :
# "De rien." de Glaude l'alsacien n'est pas "De rien." de Lia.
# Le seul rôle du gate : bloquer les messages vides ou non-texte parasites.

def process_intent(text: str) -> Optional[Dict[str, Any]]:
    """
    Retourne une action UNIQUEMENT si le message est vide ou parasite.
    Tout le reste — salutations, remerciements, au revoir — passe au LLM.
    """
    if not text or len(text.strip()) < 2:
        return {
            'action':          'empty',
            'response':        None,
            'rule_matched':    'empty_guard',
            'should_continue': False,
        }
    return None


async def intent_gate_filter(user_message: str) -> Optional[str]:
    """Appelé depuis le hub. Retourne None → LLM normal."""
    result = process_intent(user_message)
    if result:
        return result['response']  # None si message vide → hub gère
    return None


# ══════════════════════════════════════════
# TEST
# ══════════════════════════════════════════

if __name__ == '__main__':
    tests = [
        ("Salut !", False),          # ne matche plus → LLM
        ("Bonjour", False),          # ne matche plus → LLM
        ("Merci !", False),          # ne matche plus → LLM
        ("Au revoir", False),        # ne matche plus → LLM
        ("", True),                  # vide → gate
        ("  ", True),                # whitespace → gate
        ("a", True),                 # trop court → gate
        ("Salut ! Je t'ai déjà parlé de mon épouse ?", False),
        ("Merci, et dis-moi aussi...", False),
        ("Quel temps fait-il ?", False),
        ("Comment tu t'appelles ?", False),
    ]
    for t, expected_match in tests:
        res = process_intent(t)
        status = 'OK' if bool(res) == expected_match else 'ERR'
        action = res['action'] if res else 'LLM'
        print(f"{status} '{t}' -> {action}")
