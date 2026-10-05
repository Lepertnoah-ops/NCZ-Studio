"""Zeitverlauf je Shot: Tempo-Kurve -> Quellzeit. Zeiten im Shot in Beats (b) ab Shot-Start, per = s pro Beat.

Modi (Feld "mode" in der EDL):
  normal     Echtzeit
  fast       1,5× (z. B. Whip-Übergang)
  slow       0,5× (Finale, nur aus 60-fps-Material)
  speed      konstant shot["speed"], z. B. 0.5 oder 0.75
  freeze     Echtzeit bis shot["freeze_at"] (Beats), dann Standbild
  ramp       Anlauf bis ~2,2× bis Beat 2, in ~0,12 Beats auf 0,5× (Hit auf Beat 2), 0,5× bis Beat 3,
             dann bis zum Schnitt auf ~1,7× hochziehen (Rezept: Projektanweisungen Abschnitt 4)
  ramp_hold  wie ramp, bleibt nach dem Hit bei 0,5× (z. B. Sprung mit Landung auf dem Hit)
  split      Split-Screen, jeder Streifen in Echtzeit ab strips[i]["src"]
"""
import numpy as np

_CACHE = {}


def speed(mode, b, beats, shot=None):
    if mode == "fast":
        return 1.5
    if mode == "slow":
        return 0.5
    if mode == "speed":
        return float(shot.get("speed", 1.0))
    if mode == "freeze":
        return 1.0 if b < shot["freeze_at"] else 0.0
    if mode in ("ramp", "ramp_hold"):
        if b < 2:
            return 1 + 1.2 * (b / 2) ** 2
        if b < 2.12:
            return 0.5 + 1.7 * 0.5 * (1 + np.cos(np.pi * (b - 2) / 0.12))
        if b < 3 or mode == "ramp_hold":
            return 0.5
        return 0.5 + 1.2 * (b - 3) ** 2
    return 1.0


def src_curve(shot, per, n=4000):
    """(b-Raster, Quell-Versatz in s) für b in [0, beats]."""
    key = (shot.get("n"), shot["mode"], shot["beats"], shot.get("speed"), shot.get("freeze_at"), per, n)
    if key[0] is not None and key in _CACHE:
        return _CACHE[key]
    beats = shot["beats"]
    b = np.linspace(0, beats, n + 1)
    v = np.array([speed(shot["mode"], x, beats, shot) for x in b])
    cum = np.concatenate([[0], np.cumsum((v[1:] + v[:-1]) / 2 * np.diff(b))]) * per
    _CACHE[key] = (b, cum)
    return b, cum


def src_at(shot, u, per):
    """u = Sekunden im Shot (Reel-Zeit) -> (Quellzeit in s, Tempo)."""
    b, cum = src_curve(shot, per)
    x = np.clip(u / per, 0, shot["beats"])
    return shot["src"] + np.interp(x, b, cum), speed(shot["mode"], x, shot["beats"], shot)


def windows(E):
    """Clip -> (von, bis) in Quellsekunden, das alle Shots der EDL zusammen brauchen."""
    per, win = E["per"], {}
    for s in E["shots"]:
        if s["clip"] == "split":
            items = [(st["clip"], st["src"], st["src"] + s["beats"] * per) for st in s["strips"]]
        else:
            items = [(s["clip"], s["src"], s["src"] + src_curve(s, per)[1][-1])]
        for c, a, b in items:
            win[c] = (min(a, win[c][0]), max(b, win[c][1])) if c in win else (a, b)
    return win
