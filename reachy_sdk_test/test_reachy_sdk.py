"""
Script de test minimal du SDK officiel reachy-mini.
À copier sur le Pi5 (ex. ~/Projects/Reachy/test_reachy_sdk.py)
et à lancer avec le venv reachy_mini_env activé :

    source ~/reachy_mini_env/bin/activate
    python test_reachy_sdk.py
"""

from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

# Le SDK auto-détecte la connexion : USB/localhost ou réseau (Wi-Fi).
# Comme le Pi5 n'est pas le CM4 du robot, ça devrait se connecter
# via le réseau (Wi-Fi) au démon distant.
with ReachyMini() as mini:
    print("Connecté au robot !")

    print("Mouvement de tête...")
    mini.goto_target(
        head=create_head_pose(z=10, roll=15, degrees=True, mm=True),
        duration=1.0,
    )

    print("Retour position neutre...")
    mini.goto_target(head=create_head_pose(), duration=1.0)

print("Test terminé.")
