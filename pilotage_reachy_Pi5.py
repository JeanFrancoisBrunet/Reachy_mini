#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
#  pilotage_reachy_Pi5.py
#  Raspberry Pi 5 (16 Go RAM, SSD NVMe 256 Go, OS Bookworm)
#
#  Appli Tkinter de pilotage du Reachy Mini Wireless, (raccourci bureau / autostart). 
#  Ne dépend pas d'agent_groq_ng.py et n'est jamais lancée par lui.
#
#  - Onglet État     : lecture batterie/pose/IMU/control_mode via l'API REST du daemon
#  - Onglet Tête     : boutons de direction manuels
#  - Onglet Antennes : positionnement manuel des antennes
#  - Onglet Voix     : synthèse (espeak-ng) → upload → lecture sur le haut-parleur du robot
#                      (micro/écoute en direct : pas encore possible via l'API REST du daemon,
#                      passera par le pipeline WebRTC ~/gst-plugins-rs déjà validé pour la caméra)
#  - File de commandes JSON : lue toutes les 250 ms, alimentée par reachy_cmd.py
#    (lui-même appelé par agent_groq_ng.py via /tool shell) — voir reachy_mini.md
#
#  Réveil auto au lancement : wake_up() + enable_motors()
#
#  Auteur : Jean-François BRUNET – JFBConseils – Aout 2026
# =============================================================================

import json
import os
import fcntl
import subprocess
import tempfile
import tkinter as tk
from tkinter import ttk

import reachy_client as rc

QUEUE_FILE = "/home/jfbrunet/Projects/Reachy/reachy_cmd_queue.json"  # doit correspondre à reachy_cmd.py
POLL_INTERVAL_MS = 250
LOOK_DURATION = 0.3   # secondes — mouvement de tête plus réactif qu'avant (était 0.8)
LOOK_COOLDOWN_MS = int(LOOK_DURATION * 1000) + 50  # désactive les boutons le temps du mouvement

# ─── SPLASH / ICÔNE ───
SPLASH_DURATION_MS = 2500
ICON_DIR   = os.path.expanduser("~/Projects/Reachy/icons")
SPLASH_IMG = os.path.join(ICON_DIR, "reachy-mini.png")

# ─── VOIX (espeak-ng) ───
# Voix française par défaut ; remplace config MBROLA (ex. "-v mb-fr1").
ESPEAK_VOICE = "fr"

# ─── COULEURS & STYLE ───

BG_MAIN      = "#0d0f14"
BG_PANEL     = "#13161e"
BG_HEADER    = "#1a1e2a"

COLOR_GOLD   = "#f0c040"
COLOR_BLUE   = "#4fc3f7"
COLOR_GREEN  = "#4ade80"
COLOR_RED    = "#f87171"
COLOR_WHITE  = "#e8eaf0"
COLOR_GRAY   = "#6b7280"
COLOR_ORANGE = "#fb923c"

FONT_TITLE  = ("Courier New", 17, "bold")
FONT_HEADER = ("Courier New", 12, "bold")
FONT_DATA   = ("Courier New", 13)
FONT_SMALL  = ("Courier New", 11)
FONT_STATUS = ("Courier New", 11)

BTN_KW = dict(
    font=FONT_SMALL, fg=COLOR_GOLD, bg="#252a38",
    activeforeground=COLOR_WHITE, activebackground="#353a50",
    relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
)

BTN_KW_DISABLED = dict(BTN_KW)
BTN_KW_DISABLED.update(fg=COLOR_GRAY)

# =============================================================================
#  SPLASH SCREEN
# =============================================================================

class SplashScreen(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(bg=BG_HEADER)
        self.attributes("-topmost", True)
        self._img_ref = None
        try:
            from PIL import Image, ImageTk
            img = Image.open(SPLASH_IMG)
            img.thumbnail((600, 400), Image.LANCZOS)
            self._img_ref = ImageTk.PhotoImage(img)
            tk.Label(self, image=self._img_ref, bg=BG_HEADER).pack()
        except Exception:
            tk.Label(self, text="🤖  Reachy-Mini  ◆  Pilotage",
                     font=("Courier New", 28, "bold"),
                     fg=COLOR_GOLD, bg=BG_HEADER, pady=30, padx=60).pack()
        tk.Label(self, text="Pilotage Reachy Mini",
                 font=("Courier New", 15, "bold"),
                 fg=COLOR_BLUE, bg=BG_HEADER).pack(pady=(4, 2))
        tk.Label(self, text="Tête · Antennes · État · Voix",
                 font=FONT_SMALL, fg=COLOR_GRAY, bg=BG_HEADER).pack(pady=(0, 8))
        tk.Label(self, text="Réveil du robot en cours…",
                 font=FONT_SMALL, fg=COLOR_GRAY, bg=BG_HEADER).pack(pady=(0, 12))
        self._center()

    def _center(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h   = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{(sw - w)//2}+{(sh - h)//2}")

# =============================================================================
#  FENÊTRE PRINCIPALE
# =============================================================================

class PilotageReachyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("Pilotage Reachy Mini — Pi5")
        self.geometry("900x600")       # largeur x hauteur de la fenêtre
        self.minsize(650, 540)
        self.configure(bg=BG_MAIN)
        self._set_window_icon()

        self._head_buttons = []        # remplis dans _build_tab_tete, pour le cooldown
        self._last_spoken_file = None  # nom du dernier .wav envoyé au robot, pour le nettoyer

        splash = SplashScreen(self)
        self.after(SPLASH_DURATION_MS, lambda: self._start(splash))

    def _set_window_icon(self):
        # tk.PhotoImage seul est trop limité pour certains PNG (palette/alpha) ;
        # on réutilise PIL comme pour le splash, qui lui fonctionne déjà.
        try:
            from PIL import Image, ImageTk
            img = Image.open(SPLASH_IMG)
            self._icon_ref = ImageTk.PhotoImage(img)  # garder une référence, sinon Tk la perd
            self.iconphoto(True, self._icon_ref)
        except Exception:
            pass  # pas bloquant si le fichier n'existe pas ou PIL absent

    # ── Démarrage (après le splash) ──
    def _start(self, splash):
        splash.destroy()
        self.deiconify()
        self._build_ui()
        self._wake_and_enable()
        self._ensure_queue_file()
        self.after(POLL_INTERVAL_MS, self._check_queue)

    def _wake_and_enable(self):
        """Réveille le robot et active le contrôle moteur — sans ça les mouvements
        sont acceptés par l'API mais n'ont aucun effet physique."""
        try:
            rc.wake_up()
            rc.enable_motors()
            self._set_status("Robot réveillé, moteurs activés.", ok=True)
        except rc.ReachyUnavailable as e:
            self._set_status(f"Réveil impossible : {e}", ok=False)

    def _do_sleep(self):
        # Important : on rejoue d'abord le mouvement de repli (goto_sleep), 
        # qui a besoin des moteurs actifs pour bouger — puis on coupe seulement après, 
        # une fois le mouvement terminé.
        try:
            rc.goto_sleep()
            self._set_status("Mise en position de repli…", ok=True)
        except rc.ReachyUnavailable as e:
            self._set_status(str(e), ok=False)
            return
        self.after(2000, self._finish_sleep)  # laisse le temps au mouvement de se terminer

    def _finish_sleep(self):
        try:
            rc.disable_motors()
            self._set_status("Robot en veille, moteurs désactivés.", ok=True)
        except rc.ReachyUnavailable as e:
            self._set_status(str(e), ok=False)

    def _build_ui(self):
        top = tk.Frame(self, bg=BG_HEADER)
        top.pack(fill="x")
        tk.Label(top, text="🤖 Reachy-Mini — Pilotage", font=FONT_TITLE,
                 fg=COLOR_GOLD, bg=BG_HEADER, pady=8, padx=10).pack(side="left")
        tk.Button(top, text="⟳ Statut", command=self._refresh_state, **BTN_KW).pack(
            side="right", padx=(0, 10), pady=6
        )
        tk.Button(top, text="😴 Off", command=self._do_sleep, **BTN_KW).pack(
            side="right", padx=4, pady=6
        )
        tk.Button(top, text="⏻ Réveiller", command=self._wake_and_enable, **BTN_KW).pack(
            side="right", padx=4, pady=6
        )

        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook", background=BG_MAIN, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_HEADER, foreground=COLOR_WHITE,
                         padding=[14, 6], font=FONT_HEADER)
        style.map("TNotebook.Tab", background=[("selected", BG_PANEL)],
                   foreground=[("selected", COLOR_GOLD)])
        style.configure("Reachy.Horizontal.TScale", background=BG_PANEL)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.tab_etat = tk.Frame(notebook, bg=BG_PANEL)
        self.tab_tete = tk.Frame(notebook, bg=BG_PANEL)
        self.tab_antennes = tk.Frame(notebook, bg=BG_PANEL)
        self.tab_voix = tk.Frame(notebook, bg=BG_PANEL)
        for tab, label in [
            (self.tab_etat, "État"),
            (self.tab_tete, "Tête"),
            (self.tab_antennes, "Antennes"),
            (self.tab_voix, "Voix"),
        ]:
            notebook.add(tab, text=label)

        self._build_tab_etat()
        self._build_tab_tete()
        self._build_tab_antennes()
        self._build_tab_voix()

        self.status_var = tk.StringVar(value="Prêt.")
        self._status_label = tk.Label(
            self, textvariable=self.status_var, anchor="w",
            font=FONT_STATUS, fg=COLOR_GRAY, bg=BG_HEADER, padx=10, pady=4,
        )
        self._status_label.pack(fill="x")

    # ---------- Onglet État ----------
    def _build_tab_etat(self):
        self.etat_text = tk.Text(
            self.tab_etat, height=14, wrap="word", state="disabled",
            bg=BG_MAIN, fg=COLOR_WHITE, insertbackground=COLOR_WHITE,
            font=FONT_DATA, relief="flat", bd=0,
        )
        self.etat_text.pack(fill="both", expand=True, padx=8, pady=8)
        tk.Button(self.tab_etat, text="Rafraîchir", command=self._refresh_state, **BTN_KW).pack(
            pady=(0, 8)
        )

    def _refresh_state(self):
        try:
            state = rc.get_state()
            mode = state.get("control_mode", "?")
            self._set_status(f"État lu avec succès (control_mode: {mode}).", ok=True)
        except rc.ReachyUnavailable as e:
            state = {"erreur": str(e)}
            self._set_status(str(e), ok=False)
        self.etat_text.configure(state="normal")
        self.etat_text.delete("1.0", "end")
        self.etat_text.insert("1.0", json.dumps(state, indent=2, ensure_ascii=False))
        self.etat_text.configure(state="disabled")

    # ---------- Onglet Tête ----------
    def _build_tab_tete(self):
        frame = tk.Frame(self.tab_tete, bg=BG_PANEL)
        frame.pack(expand=True)
        grid = [
            (None, "up", None),
            ("left", "center", "right"),
            (None, "down", None),
        ]
        labels = {"up": "▲", "down": "▼", "left": "◀", "right": "▶", "center": "●"}
        self._head_buttons = []
        for r, row in enumerate(grid):
            for c, direction in enumerate(row):
                if direction is None:
                    continue
                btn = tk.Button(
                    frame, text=labels[direction], width=6,
                    command=lambda d=direction: self._do_look(d),
                    font=FONT_HEADER, fg=COLOR_BLUE, bg="#252a38",
                    activeforeground=COLOR_WHITE, activebackground="#353a50",
                    relief="flat", bd=0, cursor="hand2", highlightthickness=0,
                )
                btn.grid(row=r, column=c, padx=6, pady=6)
                self._head_buttons.append(btn)

    def _do_look(self, direction: str):
        self._set_head_buttons_enabled(False)
        try:
            rc.look(direction, duration=LOOK_DURATION)
            self._set_status(f"Tête → {direction}", ok=True)
        except rc.ReachyUnavailable as e:
            self._set_status(str(e), ok=False)
        finally:
            self.after(LOOK_COOLDOWN_MS, lambda: self._set_head_buttons_enabled(True))

    def _set_head_buttons_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for btn in self._head_buttons:
            btn.configure(state=state)

    # ---------- Onglet Antennes ----------
    def _build_tab_antennes(self):
        frame = tk.Frame(self.tab_antennes, bg=BG_PANEL)
        frame.pack(expand=True, fill="both", padx=12, pady=12)

        tk.Label(frame, text="Antenne gauche (°)", font=FONT_SMALL,
                 fg=COLOR_WHITE, bg=BG_PANEL).grid(row=0, column=0, sticky="w")
        self.antenna_left = tk.DoubleVar(value=0)
        ttk.Scale(frame, from_=-90, to=90, variable=self.antenna_left,
                  orient="horizontal", style="Reachy.Horizontal.TScale").grid(
            row=0, column=1, sticky="ew", padx=8
        )

        tk.Label(frame, text="Antenne droite (°)", font=FONT_SMALL,
                 fg=COLOR_WHITE, bg=BG_PANEL).grid(row=1, column=0, sticky="w")
        self.antenna_right = tk.DoubleVar(value=0)
        ttk.Scale(frame, from_=-90, to=90, variable=self.antenna_right,
                  orient="horizontal", style="Reachy.Horizontal.TScale").grid(
            row=1, column=1, sticky="ew", padx=8
        )
        frame.columnconfigure(1, weight=1)

        btn_row = tk.Frame(frame, bg=BG_PANEL)
        btn_row.grid(row=2, column=0, columnspan=2, pady=12)
        tk.Button(btn_row, text="Appliquer", command=self._do_antennas, **BTN_KW).pack(
            side="left", padx=4
        )
        tk.Button(btn_row, text="Centrer (0° / 0°)", command=self._center_antennas, **BTN_KW).pack(
            side="left", padx=4
        )

    def _do_antennas(self):
        try:
            rc.antennas(self.antenna_left.get(), self.antenna_right.get())
            self._set_status("Antennes mises à jour.", ok=True)
        except rc.ReachyUnavailable as e:
            self._set_status(str(e), ok=False)

    def _center_antennas(self):
        self.antenna_left.set(0)
        self.antenna_right.set(0)
        self._do_antennas()

    # ---------- Onglet Voix ----------
    def _build_tab_voix(self):
        frame = tk.Frame(self.tab_voix, bg=BG_PANEL)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        tk.Label(frame, text="Texte à faire dire au robot :", font=FONT_SMALL,
                 fg=COLOR_WHITE, bg=BG_PANEL).pack(anchor="w")

        self.voix_text = tk.Text(
            frame, height=3, wrap="word",
            bg=BG_MAIN, fg=COLOR_WHITE, insertbackground=COLOR_WHITE,
            font=FONT_DATA, relief="flat", bd=0,
        )
        self.voix_text.pack(fill="x", pady=(4, 8))

        btn_row = tk.Frame(frame, bg=BG_PANEL)
        btn_row.pack(fill="x", pady=(0, 8))
        tk.Button(btn_row, text="🗣️ Parler", command=self._do_speak, **BTN_KW).pack(side="left", padx=4)
        tk.Button(btn_row, text="⏹ Stop", command=self._do_stop_sound, **BTN_KW).pack(side="left", padx=4)
        tk.Button(btn_row, text="⟳ Sons sur le robot", command=self._refresh_sounds, **BTN_KW).pack(
            side="left", padx=4
        )
        tk.Button(btn_row, text="🗑️ Nettoyer les sons", command=self._cleanup_all_sounds, **BTN_KW).pack(
            side="left", padx=4
        )

        tk.Label(frame, text="Sons déjà présents sur le robot :", font=FONT_SMALL,
                 fg=COLOR_GRAY, bg=BG_PANEL).pack(anchor="w", pady=(8, 2))
        self.sounds_list = tk.Listbox(
            frame, height=6, bg=BG_MAIN, fg=COLOR_WHITE,
            font=FONT_SMALL, relief="flat", bd=0, selectbackground="#353a50",
        )
        self.sounds_list.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text=("Micro (écoute en direct) : pas encore disponible via l'API REST du daemon.\n"
                  "Passera par le pipeline WebRTC (webrtcsink + alsasrc) déjà validé pour la caméra."),
            font=FONT_SMALL, fg=COLOR_GRAY, bg=BG_PANEL, justify="left", wraplength=500,
        ).pack(anchor="w", pady=(10, 0))

    def _do_speak(self):
        text = self.voix_text.get("1.0", "end").strip()
        if not text:
            self._set_status("Rien à dire : le champ de texte est vide.", ok=False)
            return
        try:
            self._set_status("Synthèse vocale en cours…", ok=True)
            tmp_path = self._synthesize_to_wav(text)
        except Exception as e:
            self._set_status(f"Échec synthèse eSpeak-ng : {e}", ok=False)
            return
        try:
            self._cleanup_last_sound()
            rc.upload_sound(tmp_path)
            filename = os.path.basename(tmp_path)
            rc.play_sound(filename)
            self._last_spoken_file = filename
            self._set_status("Le robot parle.", ok=True)
        except rc.ReachyUnavailable as e:
            self._set_status(f"Échec envoi/lecture : {e}", ok=False)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def _cleanup_last_sound(self):
        """Supprime du robot le fichier son de la dernière phrase, pour ne pas saturer le CM4."""
        if self._last_spoken_file:
            try:
                rc.delete_sound(self._last_spoken_file)
            except rc.ReachyUnavailable:
                pass  # nettoyage manuel possible
            self._last_spoken_file = None

    def _synthesize_to_wav(self, text: str) -> str:
        """Génère un .wav temporaire via espeak-ng. Lève une exception si espeak-ng échoue."""
        fd, tmp_path = tempfile.mkstemp(prefix="reachy_speak_", suffix=".wav")
        os.close(fd)
        subprocess.run(
            ["espeak-ng", "-v", ESPEAK_VOICE, "-w", tmp_path, text],
            check=True, capture_output=True, timeout=15,
        )
        return tmp_path

    def _do_stop_sound(self):
        try:
            rc.stop_sound()
            self._set_status("Son arrêté.", ok=True)
        except rc.ReachyUnavailable as e:
            self._set_status(str(e), ok=False)

    def _refresh_sounds(self):
        try:
            sounds = rc.list_sounds()
            self._set_status("Liste des sons rafraîchie.", ok=True)
        except rc.ReachyUnavailable as e:
            self._set_status(str(e), ok=False)
            return
        self.sounds_list.delete(0, "end")
        # Forme exacte de la réponse pas encore confirmée (liste simple ou {"sounds": [...]})
        items = sounds if isinstance(sounds, list) else sounds.get("sounds", sounds.get("files", []))
        for item in items:
            self.sounds_list.insert("end", item if isinstance(item, str) else json.dumps(item, ensure_ascii=False))

    def _cleanup_all_sounds(self):
        """Supprime du robot tous les fichiers reachy_speak_*.wav déjà accumulés."""
        try:
            sounds = rc.list_sounds()
        except rc.ReachyUnavailable as e:
            self._set_status(str(e), ok=False)
            return
        items = sounds if isinstance(sounds, list) else sounds.get("sounds", sounds.get("files", []))
        names = [i if isinstance(i, str) else i.get("filename", i.get("name", "")) for i in items]
        to_delete = [n for n in names if n.startswith("reachy_speak_")]
        errors = 0
        for name in to_delete:
            try:
                rc.delete_sound(name)
            except rc.ReachyUnavailable:
                errors += 1
        self._last_spoken_file = None
        if errors:
            self._set_status(f"{len(to_delete) - errors}/{len(to_delete)} sons supprimés (échecs: {errors}).", ok=False)
        else:
            self._set_status(f"{len(to_delete)} son(s) supprimé(s) du robot.", ok=True)
        self._refresh_sounds()

    # ---------- File de commandes (venant de agent_groq_ng.py via reachy_cmd.py) ----------
    def _ensure_queue_file(self):
        if not os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE, "w") as f:
                json.dump([], f)

    def _check_queue(self):
        try:
            with open(QUEUE_FILE, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    raw = f.read()
                    cmds = json.loads(raw) if raw.strip() else []
                    if cmds:
                        f.seek(0)
                        f.truncate()
                        json.dump([], f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            for cmd in cmds:
                self._dispatch(cmd)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        finally:
            self.after(POLL_INTERVAL_MS, self._check_queue)

    def _dispatch(self, cmd: dict):
        action = cmd.get("action")
        args = cmd.get("args", "")
        try:
            if action == "look":
                rc.look(args.strip() or "center", duration=LOOK_DURATION)
            elif action == "state":
                self._refresh_state()
            elif action == "gesture":
                rc.play_recorded_move(args.strip())
            elif action == "antennas":
                left, _, right = args.partition(" ")
                rc.antennas(float(left), float(right or left))
            elif action == "speak":
                self._cleanup_last_sound()
                tmp_path = self._synthesize_to_wav(args.strip())
                rc.upload_sound(tmp_path)
                filename = os.path.basename(tmp_path)
                rc.play_sound(filename)
                self._last_spoken_file = filename
                os.remove(tmp_path)
            else:
                self._set_status(f"Commande inconnue reçue : {action}", ok=False)
                return
            self._set_status(f"Commande exécutée depuis agent_groq_ng : {action} {args}", ok=True)
        except (rc.ReachyUnavailable, ValueError, OSError) as e:
            self._set_status(f"Échec commande '{action}': {e}", ok=False)

    # ---------- Divers ----------
    def _set_status(self, text: str, ok: bool = True):
        prefix = "✅ " if ok else "⚠️ "
        self.status_var.set(prefix + text)
        self._status_label.configure(fg=COLOR_GREEN if ok else COLOR_RED)

def main():
    app = PilotageReachyApp()
    app.mainloop()

if __name__ == "__main__":
    main()
