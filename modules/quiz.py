# ============================================
# NIMM — modules/quiz.py
# Rattrapage des tags QUIZ non balisés par le LLM
# ============================================

import re
import json

_BARE_QUIZ_RE = re.compile(r'\{[^{}]*"type"\s*:\s*"(?:qcm|vf)"[^{}]*\}', re.DOTALL)

def wrap_bare_quiz(text: str) -> str:
    """Enveloppe les JSON quiz que le LLM a oublié de baliser avec %%QUIZ%%."""
    def _wrap(m):
        before = text[max(0, m.start() - 8): m.start()]
        if before.endswith('%%QUIZ%%'):
            return m.group()          # déjà balisé
        try:
            json.loads(m.group())     # JSON valide ?
            return f'%%QUIZ%%{m.group()}%%/QUIZ%%'
        except Exception:
            return m.group()
    return _BARE_QUIZ_RE.sub(_wrap, text)
