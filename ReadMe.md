# Pilotage Reachy Mini — Raspberry Pi 5

Application Tkinter de pilotage du robot **Reachy Mini Wireless** (Pollen Robotics / Hugging Face) depuis un Raspberry Pi 5, avec possibilité de recevoir des ordres depuis [agent_groq_ng.py](../Groq_agent) (agent IA personnel basé sur l'API Groq, boucle agentique à function-calling natif).

**Statut : en développement — le robot n'est pas encore reçu.** Le schéma de `/api/move` dans `reachy_client.py` (poses en radians, `head_pose`, endpoints `/move/play/...`) a été mis à jour à partir de la spécification OpenAPI/Swagger publique du daemon — reste à valider en direct dès réception du robot (`http://reachy-mini.local:8000/docs`).

## Matériel
- Raspberry Pi 5 (16 Go RAM, SSD NVMe 256 Go, Raspberry Pi OS Bookworm) — poste de pilotage, usage bureautique classique (écran, clavier, souris)
- Reachy Mini Wireless (CM4 embarqué, Wi-Fi, batterie) — tête 6 ddl, rotation du corps, 2 antennes animées, caméra IMX708, 4 micros, haut-parleur 5 W

## Architecture
Le robot expose nativement une API REST + WebSocket via son daemon embarqué (`http://reachy-mini.local:8000/api`) — aucun serveur pont n'est nécessaire côté Pi5, seulement un client HTTP.

```
┌───────────────────────┐        /tool shell            ┌───────────────┐
│   agent_groq_ng.py    │ ───────────────────────────▶ │ reachy_cmd.py │
│  (Telegram / terminal)│                               └───────┬───────┘
└───────────────────────┘                                       │ écrit (fcntl.flock)
                                                                ▼
                                                    reachy_cmd_queue.json
                                                                │ lu toutes les 250 ms
                                                                ▼
                                                   ┌────────────────────────┐
                                                   │ pilotage_reachy_Pi5.py │
                                                   │      (Tkinter)         │
                                                   └───────────┬────────────┘
                                                                │ REST (reachy_client.py)
                                                                ▼
                                                    daemon Reachy Mini (CM4)
                                                    http://reachy-mini.local:8000/api
```

**Principe clé : `agent_groq_ng.py` n'a reçu qu'une modification minimale (une ligne).** Le tool `shell` existant a été étendu pour autoriser `python3` dans sa whitelist — aucun tool `robot` dédié n'a été créé. `agent_groq_ng.py` appelle `reachy_cmd.py`, qui dépose une commande dans une file JSON. `pilotage_reachy_Pi5.py` — lancé manuellement au démarrage de session (raccourci bureau / autostart) — lit cette file et exécute les commandes reçues, en plus de son pilotage manuel via l'interface graphique.

## Fichiers
| Fichier                  | Rôle                                                                                                                             |
|---                       |---                                                                                                                               |
| `pilotage_reachy_Pi5.py` | Appli Tkinter principale — onglets État / Tête / Antennes / Voix (à venir), splash de démarrage, polling de la file de commandes |
| `reachy_client.py`       | Client HTTP minimal vers l'API REST du daemon Reachy Mini (état, mouvements de tête, antennes, rejeu de mouvements enregistrés)  |
| `reachy_cmd.py`          | Pont en ligne de commande — écrit une commande dans la file JSON ; c'est le seul point que `agent_groq_ng.py` appelle            |
| `icons/reachy-mini.png`  | Image du splash de démarrage                                                                                                     |
| `reachy_cmd_queue.json`  | File de commandes (générée automatiquement, pas versionnée — voir `.gitignore`)                                                  |

## Installation
```bash
git clone <url-du-repo> ~/Projects/Reachy
cd ~/Projects/Reachy
python3 -m venv .venv
source .venv/bin/activate
pip install pillow          # pour le splash ; l'appli fonctionne aussi sans (repli texte)
```

Placer une icône `reachy-mini.png` dans `~/Projects/Reachy/icons/` (facultatif — un splash texte de secours s'affiche sinon).

Le Reachy Mini doit être allumé, connecté au même réseau Wi-Fi que le Pi5, et résoluble via `reachy-mini.local`.

## Lancement

```bash
python3 pilotage_reachy_Pi5.py
```

Pour un lancement automatique à l'ouverture de session, ajouter un fichier `.desktop` dans `~/.config/autostart/`.

## Onglets
- **État** — lecture batterie, pose tête, orientation IMU, direction du son (`GET /api/state/full`)
- **Tête** — 5 boutons de direction (haut/bas/gauche/droite/centre)
- **Antennes** — deux curseurs pour positionner indépendamment chaque antenne
- **Voix** *(à venir)* — conversation vocale (micro/haut-parleur du robot). En attente de vérifier si le SDK audio (`microphones.record()` / `speaker.play_audio()`) fonctionne à distance depuis le Pi5 ou doit tourner sur le CM4 du robot

## Intégration avec agent_groq_ng.py

Une seule ligne a été ajoutée dans `agent_groq_ng.py` : `python3` a été ajouté à la whitelist du tool `shell` existant (aucune restriction de script — autonomie complète). Aucun tool `robot` dédié n'a été créé. Le tool `shell` ainsi étendu suffit à transmettre un ordre à `pilotage_reachy_Pi5.py`, tant que celui-ci tourne en arrière-plan sur le Pi5.

Depuis Telegram ou le terminal de l'agent :

```
/tool shell python3 /home/jfbrunet/Projects/Reachy/reachy_cmd.py look right
/tool shell python3 /home/jfbrunet/Projects/Reachy/reachy_cmd.py gesture nod
/tool shell python3 /home/jfbrunet/Projects/Reachy/reachy_cmd.py antennas 20 -20
/tool shell python3 /home/jfbrunet/Projects/Reachy/reachy_cmd.py state
```

Actions autorisées par `reachy_cmd.py` : `look` (`left`/`right`/`up`/`down`/`center`), `gesture` (nom d'un mouvement pré-enregistré), `antennas` (angles gauche/droite en degrés), `state` (déclenche un rafraîchissement dans l'onglet État de l'appli).

## Roadmap
- [ ] Valider en direct le schéma de `/api/move` (`reachy_client.py`, déjà mis à jour depuis le Swagger public) dès réception du robot
- [ ] Vérifier l'accès réseau au micro/haut-parleur depuis le Pi5 (SDK) ou prévoir un script compagnon sur le CM4
- [ ] Implémenter l'onglet Voix : STT (Faster-Whisper, réutilisé depuis [Studio_Audio](../Studio_Audio)) → Groq → TTS (eSpeak/MBROLA, réutilisé depuis [eSpeak](../eSpeak))
- [ ] Ajouter une action `move` générique dans `reachy_cmd.py` pour rejouer des mouvements pré-enregistrés depuis l'agent

## Auteur
Jean-François BRUNET — JFBConseils - Aout 2026
