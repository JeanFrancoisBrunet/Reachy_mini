"""
reachy_client.py
Client HTTP minimal pour l'API REST du daemon Reachy Mini Wireless.
Réutilisé par pilotage_reachy_Pi5.py et par reachy_cmd.py.

Doc de référence : http://reachy-mini.local:8000/docs (Swagger, une fois le robot sur le réseau)
"""

import json
import math
import mimetypes
import os
import uuid
import urllib.request
import urllib.error

REACHY_BASE_URL = "http://reachy-mini.local:8000/api"
REACHY_TIMEOUT = 3  # secondes — ne jamais bloquer l'appelant si le robot dort/hors ligne
REACHY_UPLOAD_TIMEOUT = 10  # secondes — un peu plus long pour l'upload de fichiers son


class ReachyUnavailable(Exception):
    """Levée quand le robot ne répond pas (éteint, hors Wi-Fi, daemon down)."""
    pass


def _request(method: str, path: str, payload: dict | None = None, timeout: float = REACHY_TIMEOUT) -> dict:
    url = f"{REACHY_BASE_URL}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except (urllib.error.URLError, TimeoutError, ConnectionRefusedError) as e:
        raise ReachyUnavailable(f"Robot injoignable ({e})") from e


# =============================================================================
#  ÉTAT
# =============================================================================

def get_state() -> dict:
    """État complet : pose tête, yaw corps, antennes, direction du son, control_mode, batterie..."""
    return _request("GET", "/state/full")


# =============================================================================
#  MOTEURS / RÉVEIL
# =============================================================================

def wake_up() -> dict:
    """Réveille le robot (POST /api/move/play/wake_up, sans body)."""
    return _request("POST", "/move/play/wake_up")


def goto_sleep() -> dict:
    """Met le robot en veille (POST /api/move/play/goto_sleep, sans body)."""
    return _request("POST", "/move/play/goto_sleep")


def enable_motors() -> dict:
    """
    Active le contrôle moteur (control_mode -> "enabled").
    Indispensable après wake_up() : sans ça, les commandes de mouvement sont
    acceptées par l'API (pas d'erreur) mais n'ont aucun effet physique.
    """
    return _request("POST", "/motors/set_mode/enabled")


def disable_motors() -> dict:
    """Repasse le contrôle moteur en mode désactivé."""
    return _request("POST", "/motors/set_mode/disabled")


# =============================================================================
#  MOUVEMENT
# =============================================================================

def move_head(pitch: float = 0.0, yaw: float = 0.0, roll: float = 0.0, duration: float = 0.8) -> dict:
    """
    Déplace la tête vers une pose cible (angles en RADIANS, conforme au schéma
    GotoModelRequest/XYZRPYPose réel de la spec OpenAPI du daemon).
    """
    payload = {"head_pose": {"pitch": pitch, "yaw": yaw, "roll": roll}, "duration": duration}
    return _request("POST", "/move/goto", payload)


def look(direction: str, amplitude_deg: float = 15.0, duration: float = 0.8) -> dict:
    """Raccourcis pratiques pour le tool `robot look <direction>` (conversion degrés → radians) avec un pas de 15° ici."""
    amp = math.radians(amplitude_deg)
    presets = {
        "left":   dict(yaw=-amp),               # chgt sens avec le signe (-/+)
        "right":  dict(yaw=amp),                # chgt sens avec le signe (-/+)
        "up":     dict(pitch=-amp),
        "down":   dict(pitch=amp),
        "center": dict(pitch=0, yaw=0, roll=0),
    }
    if direction not in presets:
        raise ValueError(f"Direction inconnue : {direction} (attendu : {', '.join(presets)})")
    return move_head(duration=duration, **presets[direction])


def antennas(left_deg: float, right_deg: float, duration: float = 0.6) -> dict:
    """Positionne les deux antennes (angles en degrés en entrée, convertis en radians)."""
    payload = {
        "antennas": [math.radians(left_deg), math.radians(right_deg)],
        "duration": duration,
    }
    return _request("POST", "/move/goto", payload)


def play_recorded_move(move_name: str, dataset_name: str = "default") -> dict:
    """
    Rejoue un mouvement pré-enregistré via /api/move/play/recorded-move-dataset/{dataset_name}/{move_name}
    (POST sans body, noms dans l'URL — pas de route générique /move/play).
    dataset_name="default" est un choix provisoire : à confirmer une fois le robot connecté,
    via GET /api/move/recorded-move-datasets/list/{dataset_name} pour voir les moves disponibles.
    """
    return _request("POST", f"/move/play/recorded-move-dataset/{dataset_name}/{move_name}")


# =============================================================================
#  SON / VOIX (POST /api/media/...)
# =============================================================================

def list_sounds() -> dict:
    """Liste les fichiers son déjà présents sur le robot."""
    return _request("GET", "/media/sounds")


def play_sound(filename: str) -> dict:
    """Joue un fichier son déjà uploadé sur le robot (haut-parleur)."""
    return _request("POST", "/media/play_sound", {"file": filename})


def stop_sound() -> dict:
    """Arrête le son en cours de lecture sur le robot."""
    return _request("POST", "/media/stop_sound")


def delete_sound(filename: str) -> dict:
    """Supprime un fichier son du robot."""
    return _request("DELETE", f"/media/sounds/{filename}")


def upload_sound(filepath: str) -> dict:
    """
    Envoie un fichier .wav local vers le robot (POST /api/media/sounds/upload,
    multipart/form-data — le seul endpoint qui n'est pas du JSON pur, donc pas
    géré par _request()).
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(filepath)

    filename = os.path.basename(filepath)
    mime_type = mimetypes.guess_type(filepath)[0] or "audio/wav"
    boundary = uuid.uuid4().hex

    with open(filepath, "rb") as f:
        file_content = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + file_content + f"\r\n--{boundary}--\r\n".encode("utf-8")

    url = f"{REACHY_BASE_URL}/media/sounds/upload"
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REACHY_UPLOAD_TIMEOUT) as resp:
            resp_body = resp.read()
            return json.loads(resp_body) if resp_body else {}
    except (urllib.error.URLError, TimeoutError, ConnectionRefusedError) as e:
        raise ReachyUnavailable(f"Upload son impossible ({e})") from e
