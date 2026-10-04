#!/usr/bin/env python3
"""
reachy_cmd.py — écrit une commande dans la file JSON lue par pilotage_reachy_Pi5.py.

Appelé par agent_groq_ng.py via le tool `shell` existant (whitelist étendue à `python3`) :
    /tool shell python3 ~/Projects/Reachy/reachy_cmd.py look right
    /tool shell python3 ~/Projects/Reachy/reachy_cmd.py gesture nod
    /tool shell python3 ~/Projects/Reachy/reachy_cmd.py state
    /tool shell python3 ~/Projects/Reachy/reachy_cmd.py speak "Bonjour Jean-François"

agent_groq_ng.py ne connaît jamais le format JSON interne : cet unique script fait le pont,
avec un verrou fcntl (même pattern que append_exchange_to_history() dans agent_groq_ng.py)
pour éviter toute écriture concurrente corrompue si plusieurs commandes arrivent vite.
"""

import sys
import json
import fcntl
import time
import os

QUEUE_FILE = "/home/jfbrunet/Projects/Reachy/reachy_cmd_queue.json"  

ALLOWED_ACTIONS = {"look", "gesture", "state", "antennas", "speak"}


def append_command(action: str, args: str) -> None:
    if action not in ALLOWED_ACTIONS:
        print(f"❌ Action non autorisée : {action} (autorisées : {', '.join(sorted(ALLOWED_ACTIONS))})")
        sys.exit(1)

    entry = {"action": action, "args": args, "ts": time.time()}

    if not os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "w") as f:
            json.dump([], f)

    with open(QUEUE_FILE, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            raw = f.read()
            cmds = json.loads(raw) if raw.strip() else []
            cmds.append(entry)
            f.seek(0)
            f.truncate()
            json.dump(cmds, f)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

    print(f"🤖 Commande '{action}' ({args or '—'}) mise en file.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : reachy_cmd.py <action> [args...]")
        sys.exit(1)
    action = sys.argv[1]
    args = " ".join(sys.argv[2:])
    append_command(action, args)
