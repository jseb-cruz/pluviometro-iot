"""Mezcla la narracion con el video compuesto por componer.py --voz.

Uso: python mezclar.py <video_mudo.mp4> <carpeta_voz> <salida.mp4>
Lee <video_mudo.mp4>.cues.json (instante de cada frase), coloca cada <carpeta_voz>/<id>.wav en su sitio,
normaliza a -16 LUFS (loudnorm en dos pasadas, pico -1,5 dBTP) y codifica AAC 192 kbps / 48 kHz.
El video se copia sin recodificar.
"""
import json
import os
import subprocess
import sys
import wave

import numpy as np


def duracion(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True, check=True).stdout)


def main():
    video, carpeta, salida = sys.argv[1:4]
    cues = json.load(open(video + ".cues.json"))
    sr = 22050
    pista = np.zeros(int(duracion(video) * sr) + sr, dtype=np.float32)
    ocupado = []
    for c in cues:
        with wave.open(os.path.join(carpeta, c["id"] + ".wav")) as w:
            assert w.getframerate() == sr and w.getnchannels() == 1
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        i = int(round(c["voz"] * sr))
        assert not pista[i:i + len(x)].any(), f"frase encimada: {c['id']}"
        pista[i:i + len(x)] += x
        ocupado.append((c["voz"], c["voz"] + len(x) / sr, c["id"]))
    pista = pista[: int(duracion(video) * sr)]
    crudo = salida + ".voz_cruda.wav"
    with wave.open(crudo, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(pista, -1, 1) * 32767).astype(np.int16).tobytes())

    objetivo = "I=-16:TP=-1.5:LRA=11"
    med = subprocess.run(["ffmpeg", "-hide_banner", "-i", crudo, "-af", f"loudnorm={objetivo}:print_format=json",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    m = json.loads(med[med.rindex("{"):med.rindex("}") + 1])
    filtro = (f"loudnorm={objetivo}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,"
              "aresample=48000")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", crudo, "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-af", filtro, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                    "-shortest", "-movflags", "+faststart", salida], check=True)
    os.remove(crudo)
    print(f"{len(cues)} frases; voz medida antes de normalizar: {m['input_i']} LUFS")


if __name__ == "__main__":
    main()
