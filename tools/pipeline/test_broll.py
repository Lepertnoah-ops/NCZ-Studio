#!/usr/bin/env python3
"""Test von broll.py ohne Drive (~2 s): Stichwörter im Gesagten wählen passende Clips und Zeiten.

    python3 test_broll.py

Ein Sprechteil von gut 14 s mit den Wörtern „Muskelgruppen“ und „Community“, ein kurzer Teil (2 s),
eine Frage und ein Teil, der schon ein `bild` hat; vier Clips in den Tags (Muscle-up, Crew, ein Ausschuss-Clip, ein
Sprecherclip). Erwartung: zwei Vorschläge im langen Teil (Muscle-up zu „Muskelgruppen“, Crew zu „Community“), Anfang
frühestens 0,8 s nach dem Teilanfang, Ende mindestens 0,6 s vor dem Teilende, der Fenster-Moment liegt im sauberen Fenster,
kein Ausschuss, kein Sprecherclip, keine Vorschläge für kurzen Teil, Frage und Teil mit Bild; --einsetzen-Logik schreibt `bei`.
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import broll  # noqa: E402


def ok(text):
    print("OK  ", text, flush=True)


def main():
    text = ("Jedes Mal wenn man eine andere Station geht kommt eine andere Muskelgruppen dazu und dann ist auch die "
            "Stimmung richtig gut in der Community hier bei uns im Park und das macht einfach Spaß").split()
    ws, t = [], 10.0
    zeiten = {}
    for w in text:
        d = 0.22 + 0.04 * len(w)
        ws.append(dict(w=w, s=round(t, 3), e=round(t + d, 3), p=0.95))
        zeiten[w] = t
        t += d + 0.06
    ende = t
    cfg = dict(name="t", clips={"A": "A.mp4"}, transkript="x", teile=[
        dict(clip="A", von=9.9, bis=round(ende + 0.1, 3), notiz="lang"),
        dict(clip="A", von=10.0, bis=12.0),
        dict(clip="A", von=10.0, bis=round(ende, 3), stil="frage"),
        dict(clip="A", von=10.0, bis=round(ende, 3), bild=[dict(clip="6365", src=1.0, ab=1.0, dauer=1.5)])])
    trs = {"A": dict(segmente=[dict(woerter=ws)])}
    tags = {
        "6365": dict(kapitel=[3], tags=["action"], desc="Muscle-up an der Stange", moment=14.0, sauber=[12.0, 17.0]),
        "6370": dict(kapitel=[4], tags=["crew"], desc="Crew jubelt zusammen", moment=3.0),
        "6371": dict(kapitel=[2], tags=["action"], desc="Liegestütze", moment=5.0, ausschuss="Versuch gescheitert"),
        "A": dict(kapitel=[1], tags=["crew"], desc="Sprecherclip", moment=1.0),
    }
    v = broll.vorschlagen(cfg, trs, tags)
    nr = [x["teil"] for x in v]
    assert nr == [1], nr
    b = v[0]["bild"]
    assert [x["clip"] for x in b] == ["6365", "6370"], b
    von = v[0]["von"]
    for x in b:
        assert x["ab"] >= broll.REGELN["ab_min"] - 1e-6, x
        assert x["ab"] + x["dauer"] <= (v[0]["bis"] - von) - broll.REGELN["ende_min"] + 0.02, (x, v[0])
        assert abs((von + x["ab"]) - x["bei"]) < 0.01, x
    assert abs(b[0]["bei"] - zeiten["Muskelgruppen"]) < 0.6, (b[0], zeiten["Muskelgruppen"])
    assert abs(b[1]["bei"] - zeiten["Community"]) < 1.6, (b[1], zeiten["Community"])
    assert 12.0 <= b[0]["src"] and b[0]["src"] + b[0]["dauer"] <= 17.0 + 1e-6, b[0]
    assert "Muskelgruppen" in b[0]["grund"] and "Community" in b[1]["grund"], (b[0]["grund"], b[1]["grund"])
    ok(f"zwei Vorschläge: {b[0]['clip']} zu „Muskelgruppen“ bei {b[0]['bei']:.1f} s, {b[1]['clip']} zu „Community“ bei {b[1]['bei']:.1f} s")
    # meiden und Ausschuss
    v2 = broll.vorschlagen(cfg, trs, tags, meiden=["6365"])
    assert all(x["clip"] != "6365" for x in v2[0]["bild"]), v2
    assert all(x["clip"] not in ("6371", "A") for x in v2[0]["bild"]), v2
    ok("--meiden, Ausschuss und Sprecherclip kommen nicht vor")
    # ohne Stichwort: sauberer Action-Clip in der Mitte
    cfg2 = dict(cfg, teile=[dict(clip="A", von=9.9, bis=round(ende + 0.1, 3))])
    tags2 = {"6365": tags["6365"]}
    ws2 = [dict(w=x["w"].replace("Muskelgruppen", "Dingen").replace("Community", "Gegend"), s=x["s"], e=x["e"], p=1) for x in ws]
    v3 = broll.vorschlagen(cfg2, {"A": dict(segmente=[dict(woerter=ws2)])}, tags2)
    assert v3 and v3[0]["bild"][0]["clip"] == "6365" and "kein Stichwort" in v3[0]["bild"][0]["grund"], v3
    ok("ohne Stichwort: ein sauberer Action-Clip")
    print("alle Tests grün")
    return 0


if __name__ == "__main__":
    sys.exit(main())
