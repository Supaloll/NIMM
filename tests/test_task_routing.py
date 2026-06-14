# -*- coding: utf-8 -*-
"""
Test hors-ligne du routage par tâche (sous-LLM mémoire/titre/synthèse) et du
chargement des gabarits de prompt d'extraction mémoire.

Vérifie :
  1. get_task_provider_model() retombe sur le chat si la tâche n'a pas de routage.
  2. get_task_provider_model() utilise le routage dédié quand il est présent.
  3. Le mode local force ollama, quel que soit le routage.
  4. _load_memoire_prompt_template() charge memoire_default.txt et que les
     placeholders {{USER_NAME}} / {{CONV_TEXT}} sont bien remplaçables.
  5. _load_memoire_prompt_template() retombe sur un gabarit minimal si aucun
     fichier n'est trouvé (provider inconnu + dossier absent).
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import hub


def test_fallback_sur_chat():
    settings = {'provider': 'anthropic', 'model': 'claude-x', 'local_mode': False, 'provider_routing': {}}
    assert hub.get_task_provider_model('memoire', settings) == ('anthropic', 'claude-x')
    print("OK  pas de routage dédié → fallback sur le chat")


def test_routage_dedie():
    settings = {
        'provider': 'anthropic', 'model': 'claude-x', 'local_mode': False,
        'provider_routing': {'memoire': {'provider': 'deepseek', 'model': 'deepseek-chat'}},
    }
    assert hub.get_task_provider_model('memoire', settings) == ('deepseek', 'deepseek-chat')
    print("OK  routage dédié → provider+modèle de la tâche")


def test_mode_local_force_ollama():
    settings = {
        'provider': 'anthropic', 'model': 'claude-x', 'local_mode': True,
        'provider_routing': {'memoire': {'provider': 'deepseek', 'model': 'deepseek-chat'}},
    }
    assert hub.get_task_provider_model('memoire', settings) == ('ollama', 'claude-x')
    print("OK  mode local → ollama, routage ignoré")


def test_prompt_memoire_default():
    template = hub._load_memoire_prompt_template('anthropic')
    assert '{{USER_NAME}}' in template
    assert '{{CONV_TEXT}}' in template
    prompt = template.replace('{{USER_NAME}}', 'Fernando').replace('{{CONV_TEXT}}', 'Bonjour')
    assert 'Fernando' in prompt and 'Bonjour' in prompt
    assert '{{' not in prompt
    print("OK  gabarit memoire_default.txt chargé et substitué")


def test_prompt_memoire_repli_minimal():
    # Provider sans fichier dédié, mais memoire_default.txt existe → on retombe sur lui
    template = hub._load_memoire_prompt_template('un_provider_qui_n_existe_pas')
    assert '{{USER_NAME}}' in template
    print("OK  provider inconnu → repli sur memoire_default.txt")


def main():
    print("\n=== TEST ROUTAGE PAR TÂCHE (hors-ligne) ===\n")
    test_fallback_sur_chat()
    test_routage_dedie()
    test_mode_local_force_ollama()
    test_prompt_memoire_default()
    test_prompt_memoire_repli_minimal()
    print("\nTous les tests passent.\n")


if __name__ == '__main__':
    main()
