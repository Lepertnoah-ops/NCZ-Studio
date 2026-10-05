"""Tonspur-Plan einer Schnittliste (audio_spec.json für tools/reel_audio.py), (Stil-Leitfaden Regeln 1, 11, 12).

schnitt/X/edl.py ruft audio_spec() auf. Die Pegel stehen hier an einer Stelle für alle Reels (Regel 1):
  Einstieg im Video   ab Reel-Start bis zum Drop (EDL-Feld "einstieg", Beats), die Shots dort mit oton="vorn".
                      einstieg_song "gedämpft": Song wie aus einer Box im Park (IM_VIDEO), öffnet sich zum Drop;
                      "aus": nur echter Ton, der Song setzt auf dem Drop ein (Pflicht, wenn im Clip-Ton Musik läuft,
                      tools/analyse/oton.py), wie in vielen Vorbild-Reels.
  O-Ton               Shot-Feld oton: "leise" (PEGEL, im Hintergrund unter dem vollen Song) oder "vorn" (O-Ton-Moment:
                      Song tritt zurück, MOMENT) oder eine Zahl in LU relativ zum Song. Echtzeit-Shots; bei Zeitlupe
                      läuft der Ton trotzdem in Echtzeit (nur Atmo ohne sichtbares Sprechen).
  Dialog              Shot-Feld dialog=True (dialog.py d() in edl.py, seit 30.09.2026): gesprochene Phrase, Song −16 dB und
                      gefiltert, Stimme −4 LU; zählt nicht als O-Ton-Moment. Untertitel brennt render.py ein.
  Überblendung        ueber="blende": der O-Ton des Shots davor läuft 0,4 s weiter und blendet über.
  Ausklang            EDL-Feld "ausklang" (Beats): der Song endet davor auf der Phrasengrenze, danach nur O-Ton.
Clip-Ton: $REEL_WORK/audio/<clip>.flac (extract.py).
"""
import os

PEGEL = dict(leise=-16.0, vorn=-6.0)                              # LU relativ zum Song
IM_VIDEO = dict(gain_db=-10.0, hp_hz=280.0, lp_hz=3200.0, width=0.3)
MOMENT = dict(gain_db=-10.0, lp_hz=2500.0)
DIALOG = dict(gain_db=-16.0, lp_hz=2500.0)                        # Song in einer Dialog-Szene (dialog.py): deutlich tiefer als im O-Ton-Moment
DIALOG_STIMME = -4.0                                              # LU der Stimme relativ zum ungesenkten Song
MOMENT_RAMPE = 0.25                                               # s, Song geht nach dem Schnitt zurück und kommt zum Schnitt wieder
BLENDE_S = 12 / 30                                                # Überblendung 0,4 s (render.py BLENDE)
KANTE = 0.03                                                      # s, Fade des O-Tons an harten Schnitten


def pegel(x):
    return PEGEL[x] if isinstance(x, str) else float(x)


def audio_spec(E, song_datei, song_src, einstieg_auf=0.03, work=None):
    """E wie edl.json (per, beats, shots mit t, beats, clip, src, oton, ueber; einstieg, ausklang in Beats; einstieg_song).
    song_src = Sekunde im Song-Decode am Reel-Start (Decoder-Versatz schon abgezogen). einstieg_auf: s, so lange
    öffnet sich der Song vor dem Drop (0,03 = auf dem Schlag, einige Sekunden = langsam)."""
    work = work or os.environ.get("REEL_WORK", "/home/user/reel")
    per, S = E["per"], E["shots"]
    dur = E["beats"] * per
    ein, aus = E.get("einstieg", 0), E.get("ausklang", 0)
    song_dur = (E["beats"] - aus) * per
    lauf = ein * per if ein and E.get("einstieg_song") == "aus" else 0.0     # Song erst ab dem Drop
    music = [dict(file=song_datei, src=round(song_src + lauf, 4), at=round(lauf, 4), dur=round(song_dur - lauf, 4),
                  fade_in=0.004, fade_out=0.038)]
    fx, oton = [], []
    if ein and not lauf:
        fx.append({"from": 0.0, "to": round(ein * per, 4), "fade_in": 0.0, "fade_out": einstieg_auf, **IM_VIDEO})
    for i, x in enumerate(S):
        if not x.get("oton") or x["clip"] == "split":
            continue
        a, d = x["t"], x["beats"] * per
        prv, nxt = (S[i - 1] if i else None), (S[i + 1] if i + 1 < len(S) else None)
        moment = x["oton"] == "vorn" and ein <= x["beat"] < E["beats"] - aus
        tail = BLENDE_S if nxt and nxt.get("ueber") == "blende" else 0.0
        fi = BLENDE_S if x.get("ueber") == "blende" else KANTE
        fo = BLENDE_S if tail else KANTE
        dlg = bool(x.get("dialog"))
        if moment:
            if fx and abs(fx[-1]["to"] - a) < 1e-6 and fx[-1].get("moment") and bool(fx[-1].get("dialog")) == dlg:
                fx[-1]["to"] = round(a + d, 4)                   # mehrere O-Ton-vorn-Shots: ein Moment
            else:
                fx.append({"from": round(a, 4), "to": round(a + d, 4), "fade_in": MOMENT_RAMPE,
                           "fade_out": MOMENT_RAMPE, "moment": True, **({"dialog": True, **DIALOG} if dlg else MOMENT)})
            if not (prv and prv.get("oton") == "vorn"):
                fi = max(fi, 0.15)
            if not (nxt and nxt.get("oton") == "vorn"):
                fo = max(fo, 0.15)
        oton.append(dict(file=f"{work}/audio/{x['clip']}.flac", src=round(x["src"], 4), at=round(a, 4),
                         dur=round(min(d + tail, dur - a), 4), level_lu=DIALOG_STIMME if dlg else pegel(x["oton"]), fade_in=round(fi, 3),
                         fade_out=round(fo, 3), hp_hz=100))
    spec = dict(duration=dur, music=music, sfx=[], match_loudness=False, target_lufs=None, ceiling_db=-0.3)
    if fx:
        spec["music_fx"] = fx
    if oton:
        spec["oton"] = oton
    return spec
