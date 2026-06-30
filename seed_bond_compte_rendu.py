"""Ce fichier a été déplacé dans bonds/seed_bond_compte_rendu.py.
Lancez-le depuis bonds/ : python bonds/seed_bond_compte_rendu.py
"""
import subprocess, sys, os
subprocess.run([sys.executable,
                os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bonds', 'seed_bond_compte_rendu.py')
                ] + sys.argv[1:])
