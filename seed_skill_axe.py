"""Ce fichier a été déplacé dans bonds/seed_skill_axe.py.
Lancez-le depuis bonds/ : python bonds/seed_skill_axe.py
"""
import subprocess, sys, os
subprocess.run([sys.executable,
                os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bonds', 'seed_skill_axe.py')
                ] + sys.argv[1:])
