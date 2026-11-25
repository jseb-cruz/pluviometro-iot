"""Sintetiza con Piper cada frase de narracion.json y guarda sus duraciones.

Uso: python narrar.py <modelo.onnx> <carpeta_salida> [--length-scale 0.85]
Genera <carpeta_salida>/<id>.wav (22,05 kHz, mono) y <carpeta_salida>/duraciones.json.
Requiere: pip install piper-tts  (voz: python -m piper.download_voices es_MX-claude-high)
"""
import argparse
import json
import os
import wave

from piper import PiperVoice, SynthesisConfig

AQUI = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modelo")
    ap.add_argument("salida")
    ap.add_argument("--length-scale", type=float, default=0.85)
    ap.add_argument("--guion", default=os.path.join(AQUI, "narracion.json"))
    a = ap.parse_args()
    os.makedirs(a.salida, exist_ok=True)
    guion = json.load(open(a.guion, encoding="utf-8"))
    voz = PiperVoice.load(a.modelo)
    cfg = SynthesisConfig(length_scale=a.length_scale)
    dur = {}
    for f in guion["frases"]:
        ruta = os.path.join(a.salida, f"{f['id']}.wav")
        with wave.open(ruta, "wb") as w:
            voz.synthesize_wav(f["voz"], w, syn_config=cfg)
        with wave.open(ruta) as w:
            dur[f["id"]] = round(w.getnframes() / w.getframerate(), 3)
        print(f"{f['id']:20s} {dur[f['id']]:6.2f} s")
    json.dump(dur, open(os.path.join(a.salida, "duraciones.json"), "w"), indent=1)
    print(f"total {sum(dur.values()):.1f} s de voz")


if __name__ == "__main__":
    main()
