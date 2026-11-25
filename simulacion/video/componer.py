"""Compone el video de demostracion (1920x1080, 30 fps) a partir de las grabaciones.

Uso:
  python componer.py <grabaciones> <salida.mp4> [--voz <carpeta con duraciones.json>]

Los subtitulos salen de narracion.json ("pantalla"). Con --voz, cada tramo de subtitulo dura al menos
lo que su frase hablada + 0,3 s: las tomas fijas se alargan, las grabaciones a velocidad normal congelan
su ultimo cuadro y los tramos acelerados bajan su aceleracion (la voz nunca se acelera). Ademas escribe
<salida>.cues.json con el instante en que empieza cada frase, para mezclar.py.
Variables de entorno: CUENTA_AWS (se reemplaza por XXXXXXXXXXXX), SOLO=2,5 (solo esos segmentos),\nSECO=1 (solo calcula la linea de tiempo y los cues, sin renderizar).
"""
import argparse, bisect, glob, json, math, os, re, subprocess
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont

AQUI = os.path.dirname(os.path.abspath(__file__))
R = os.path.abspath(os.path.join(AQUI, "..", ".."))
W, H, FPS = 1920, 1080, 30
PAUSA = 0.3
CUENTA = os.environ.get("CUENTA_AWS", "")
SOLO = os.environ.get("SOLO")

F_REG = "/usr/share/fonts/noto/NotoSans-Regular.ttf"
F_BOLD = "/usr/share/fonts/noto/NotoSans-Bold.ttf"
F_MONO = "/usr/share/fonts/TTF/JetBrainsMonoNerdFontMono-Regular.ttf"
F_MONOB = "/usr/share/fonts/TTF/JetBrainsMonoNerdFontMono-Bold.ttf"
F_SYM = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
F_ALT = {F_REG: "/usr/share/fonts/TTF/DejaVuSans.ttf", F_BOLD: "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"}
FALTAN = set("→▶")   # glifos que Noto Sans no trae en esta instalacion

GUION = {f["id"]: f for f in json.load(open(os.path.join(AQUI, "narracion.json"), encoding="utf-8"))["frases"]}
DUR = {}   # duracion de cada frase hablada (se llena con --voz)
CUES = []  # (id, t_voz_absoluto, t_ini, t_fin) en el video de salida

@lru_cache(None)
def fuente(path, size): return ImageFont.truetype(path, size)

def P(i): return GUION[i]["pantalla"] or ""

# ---------------------------------------------------------------- texto
def _corridas(s, f):
    alt = F_ALT.get(f.path)
    if not alt or not (set(s) & FALTAN): return [(s, f)]
    fa = fuente(alt, f.size); out = []
    for ch in s:
        ff = fa if ch in FALTAN else f
        if out and out[-1][1] is ff: out[-1] = (out[-1][0] + ch, ff)
        else: out.append((ch, ff))
    return out

def largo(s, f): return sum(ff.getlength(t) for t, ff in _corridas(s, f))

def dtexto(d, xy, s, font, fill, anchor="la"):
    runs = _corridas(s, font)
    if len(runs) == 1: d.text(xy, s, font=font, fill=fill, anchor=anchor); return
    x, y = xy; total = largo(s, font)
    if anchor[0] == "m": x -= total / 2
    elif anchor[0] == "r": x -= total
    for t, ff in runs:
        d.text((x, y), t, font=ff, fill=fill, anchor="l" + anchor[1]); x += ff.getlength(t)

AZUL_OSC = (11, 26, 46); AMBAR = (180, 110, 10)

def ease(x): x = min(1, max(0, x)); return x * x * (3 - 2 * x)

def envolver(texto, f, ancho):
    lineas, actual = [], ""
    for pal in texto.split(" "):
        prueba = (actual + " " + pal).strip()
        if largo(prueba, f) <= ancho: actual = prueba
        else: lineas.append(actual); actual = pal
    if actual: lineas.append(actual)
    return lineas

def subtitulo(img, texto, y_base=H - 36):
    if not texto: return
    f = fuente(F_REG, 40)
    lineas = envolver(texto, f, 1600)
    lh = 54
    alto = lh * len(lineas) + 28
    ancho = max(largo(l, f) for l in lineas) + 64
    x0 = (W - ancho) / 2; y0 = y_base - alto
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    d.rounded_rectangle([x0, y0, x0 + ancho, y_base], 16, fill=(8, 12, 20, 205))
    for i, l in enumerate(lineas):
        dtexto(d, (W / 2, y0 + 14 + i * lh + lh / 2), l, font=f, fill=(255, 255, 255), anchor="mm")
    img.alpha_composite(capa)

def etiqueta(img, texto, x=24, y=20, color=(15, 23, 42, 215), f=None, derecha=False):
    f = f or fuente(F_BOLD, 26)
    w = largo(texto, f) + 36
    if derecha: x = W - x - w
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(capa)
    d.rounded_rectangle([x, y, x + w, y + 46], 23, fill=color)
    dtexto(d, (x + w / 2, y + 23), texto, font=f, fill=(255, 255, 255), anchor="mm")
    img.alpha_composite(capa)

def acelerado(img, factor):
    etiqueta(img, f"▶▶ {factor}x", x=24, y=6, color=(200, 40, 40, 235), f=fuente(F_SYM, 28), derecha=True)

@lru_cache(1)
def _fondo():
    img = Image.new("RGBA", (W, H), AZUL_OSC)
    d = ImageDraw.Draw(img)
    for y in range(0, H, 4):
        k = y / H
        d.rectangle([0, y, W, y + 4], fill=(int(11 + 10 * k), int(26 + 30 * k), int(46 + 50 * k)))
    return img

def fondo(): return _fondo().copy()

def encajar(im, caja):
    x, y, w, h = caja
    s = min(w / im.width, h / im.height)
    nueva = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    return nueva, (int(x + (w - nueva.width) / 2), int(y + (h - nueva.height) / 2))

@lru_cache(64)
def abrir(path): return Image.open(path).convert("RGBA")

def recorte(im, caja):
    x, y, w, h = caja
    return im.crop((int(x), int(y), int(x + w), int(y + h))).resize((W, H), Image.LANCZOS)

def caja_en(t, claves, trans=0.8):
    actual = claves[0][1]
    for i, (ti, caja) in enumerate(claves):
        if t < ti: break
        previa = claves[i - 1][1] if i else caja
        k = ease((t - ti) / trans)
        actual = tuple(a + (b - a) * k for a, b in zip(previa, caja))
    return actual

# ---------------------------------------------------------------- terminal
SGR = {30: (110, 118, 129), 31: (255, 123, 114), 32: (126, 231, 135), 33: (227, 179, 65), 34: (121, 192, 255),
       35: (210, 168, 255), 36: (118, 227, 234), 37: (230, 237, 243), 39: None}
FG = (230, 237, 243); BG = (13, 17, 23)
RESALTE = [("FUERA_RANGO", (255, 110, 100)), ("SOSPECHOSA", (255, 166, 87)), ("CORREGIDA", (240, 190, 60)),
           ("EQUIVALENTES", (90, 230, 120)), ("180/180", (90, 230, 120)), (" OK", (126, 231, 135))]
PROMPT = "~/pluviometro-iot $ "

def sanear(s):
    if CUENTA: s = s.replace(CUENTA, "XXXXXXXXXXXX")
    s = s.replace(os.path.dirname(R) + "/", "~/")
    return re.sub(r"(arn:aws:[a-z0-9-]*:[a-z0-9-]*:)\d{12}", r"\1XXXXXXXXXXXX", s)

class Terminal:
    def __init__(s, cols):
        s.cols = cols; s.lineas = [[]]; s.col = 0; s.color = None; s.negrita = False
    def nueva(s): s.lineas.append([]); s.col = 0
    def poner(s, ch, color=None, negrita=None):
        if s.col >= s.cols: s.nueva()
        fila = s.lineas[-1]
        cel = (ch, color if color is not None else s.color, s.negrita if negrita is None else negrita)
        if s.col < len(fila): fila[s.col] = cel
        else: fila.append(cel)
        s.col += 1
    def alimentar(s, data):
        i = 0
        while i < len(data):
            c = data[i]
            if c == "\x1b":
                m = re.match(r"\x1b\[([0-9;?]*)([A-Za-z])", data[i:])
                if m:
                    if m.group(2) == "m":
                        for p in (m.group(1) or "0").split(";"):
                            p = int(p) if p.isdigit() else 0
                            if p == 0: s.color = None; s.negrita = False
                            elif p == 1: s.negrita = True
                            elif p in SGR: s.color = SGR[p]
                            elif 90 <= p <= 97: s.color = SGR.get(p - 60)
                    i += len(m.group(0)); continue
                i += 1; continue
            if c == "\n": s.nueva()
            elif c == "\r": s.col = 0
            elif c == "\b": s.col = max(0, s.col - 1)
            elif c >= " ": s.poner(c)
            i += 1

class Cast:
    def __init__(s, path, escribir=2.0, pausa=0.4):
        L = open(path).read().splitlines()
        s.cab = json.loads(L[0]); s.ev = [json.loads(l) for l in L[1:]]
        s.cmd = sanear(s.cab["command"]); s.cols = s.cab["width"]
        s.escribir = escribir; s.pausa = pausa
        s.fin = s.escribir + s.pausa + (s.ev[-1][0] if s.ev else 0)
    def estado(s, t):
        term = Terminal(s.cols)
        n = len(s.cmd) if s.escribir <= 0 else int(len(s.cmd) * min(1, max(0, t) / s.escribir))
        for ch in PROMPT: term.poner(ch, (126, 231, 135), True)
        for ch in s.cmd[:n]: term.poner(ch, FG, False)
        if n < len(s.cmd) or t < s.escribir + s.pausa:
            term.poner("█", (200, 200, 200), False)
            return term.lineas
        term.nueva()
        tt = t - s.escribir - s.pausa
        for e in s.ev:
            if e[0] > tt: break
            term.alimentar(sanear(e[2]))
        if s.ev and tt >= s.ev[-1][0] + 0.3:
            if term.lineas and term.lineas[-1]: term.nueva()
            for ch in PROMPT: term.poner(ch, (126, 231, 135), True)
            term.poner("█", (200, 200, 200), False)
        return term.lineas

def dibujar_terminal(lineas, w, h, tam=24, titulo="bash — pluviometro-iot"):
    f = fuente(F_MONO, tam); fb = fuente(F_MONOB, tam)
    cw = f.getlength("M"); lh = int(tam * 1.32)
    img = Image.new("RGBA", (w, h), BG); d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 40], fill=(36, 41, 47))
    for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([16 + i * 26, 13, 30 + i * 26, 27], fill=col)
    d.text((w / 2, 20), titulo, font=fuente(F_REG, 20), fill=(170, 177, 186), anchor="mm")
    filas = (h - 56) // lh
    for r, lin in enumerate(lineas[-filas:]):
        texto = "".join(c[0] for c in lin)
        extra = {}
        for pal, col in RESALTE:
            for m in re.finditer(re.escape(pal), texto):
                for k in range(m.start(), m.end()): extra[k] = col
        y = 50 + r * lh
        for k, (ch, col, neg) in enumerate(lin):
            if ch == " ": continue
            d.text((14 + k * cw, y), ch, font=fb if (neg or k in extra) else f, fill=extra.get(k, col or FG))
    return img

# ---------------------------------------------------------------- escritor y linea de tiempo
class Video:
    def __init__(s, salida):
        s.n = 0
        if os.environ.get("SECO"): s.p = None; return
        s.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                                "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", salida],
                               stdin=subprocess.PIPE)
        s.n = 0
    def t(s): return s.n / FPS
    def frame(s, img):
        s.p.stdin.write(img.convert("RGB").tobytes()); s.n += 1
    def cerrar(s):
        if s.p: s.p.stdin.close(); s.p.wait()

def con_fundido(img, t, dur, fi=0.35, fo=0.35):
    a = min(1, t / fi if fi else 1, (dur - t) / fo if fo else 1)
    if a >= 1: return img
    return Image.blend(Image.new("RGBA", img.size, (0, 0, 0, 255)), img, max(0, a))

def plan_tiempo(src_dur, cues, tramos=None):
    """Arma los tramos de salida: lista de (dur_salida, src_ini, velocidad, cue).
    cues = [(src_ini, src_fin, id, desfase_voz)], contiguos y en orden; tramos = [(src_ini, src_fin, vel)].
    velocidad 0 = cuadro congelado."""
    tramos = tramos or [(0, src_dur, 1)]
    def vel_en(a, b):
        out = []
        for ta, tb, v in tramos:
            x, y = max(a, ta), min(b, tb)
            if y > x: out.append((x, y, v))
        return out
    piezas = []
    for a, b, cid, desf in cues:
        partes = vel_en(a, b)
        dur = sum((y - x) / v for x, y, v in partes)
        need = desf + DUR.get(cid, 0) + PAUSA if cid in DUR else 0
        if dur < need:
            rapidas = [(x, y, v) for x, y, v in partes if v > 1]
            if rapidas:
                lentas = sum((y - x) / v for x, y, v in partes if v <= 1)
                largo_r = sum(y - x for x, y, v in rapidas)
                nueva = max(1, math.floor(largo_r / max(1e-6, need - lentas)))
                partes = [(x, y, min(v, nueva)) for x, y, v in partes]
                dur = sum((y - x) / v for x, y, v in partes)
        for x, y, v in partes: piezas.append(((y - x) / v, x, v, cid))
        if dur < need: piezas.append((need - dur, b - 1e-3, 0, cid))
    return piezas

def segmento(video, dibujar, src_dur, cues, tramos=None, fi=0.35, fo=0.35):
    """dibujar(t_src, subtitulo, velocidad) -> imagen. Registra el inicio de cada frase en CUES."""
    piezas = plan_tiempo(src_dur, cues, tramos)
    t0 = video.t()
    inicio = {}; acum = 0
    for d, s, v, cid in piezas:
        inicio.setdefault(cid, acum); acum += d
    total = acum
    fin_cue = {}
    acum = 0
    for d, s, v, cid in piezas: acum += d; fin_cue[cid] = acum
    for a, b, cid, desf in cues:
        if cid in GUION: CUES.append((cid, round(t0 + inicio[cid] + desf, 3), round(t0 + inicio[cid], 3), round(t0 + fin_cue[cid], 3)))
    n = math.ceil(total * FPS - 1e-6)   # hacia arriba: nunca recorta la pausa tras la ultima frase
    if os.environ.get("SECO"):   # solo calcula la linea de tiempo
        video.n += n; return
    limites = []; acum = 0
    for p in piezas: limites.append(acum); acum += p[0]
    for i in range(n):
        t = i / FPS
        k = max(0, bisect.bisect_right(limites, t) - 1)
        d, s, v, cid = piezas[k]
        ts = s + (t - limites[k]) * v if v else s
        img = dibujar(ts, P(cid) if cid in GUION else "", v)
        video.frame(con_fundido(img, t, total, fi, fo))

def estatico(img_fn, src_dur, cid, desf=0.0):
    return dict(dibujar=lambda t, sub, v: img_fn(sub), src_dur=src_dur, cues=[(0, src_dur, cid, desf)])

# ---------------------------------------------------------------- tarjetas
def tarjeta(num, titulo, bajada):
    img = fondo(); d = ImageDraw.Draw(img)
    d.text((W / 2, 390), f"{num} / 7", font=fuente(F_BOLD, 40), fill=(120, 170, 255), anchor="mm")
    dtexto(d, (W / 2, 490), titulo, font=fuente(F_BOLD, 84), fill=(255, 255, 255), anchor="mm")
    d.line([W / 2 - 120, 560, W / 2 + 120, 560], fill=(120, 170, 255), width=4)
    for i, l in enumerate(envolver(bajada, fuente(F_REG, 40), 1500)):
        dtexto(d, (W / 2, 620 + i * 56), l, font=fuente(F_REG, 40), fill=(205, 215, 230), anchor="mm")
    return img

def seg_tarjeta(video, num, titulo, bajada):
    img = tarjeta(num, titulo, bajada)
    segmento(video, **estatico(lambda sub: img, 3.5, f"tarjeta_{num}", 0.25))

# ---------------------------------------------------------------- 1. portada
def seg_portada(video, G):
    img = fondo(); d = ImageDraw.Draw(img)
    dtexto(d, (W / 2, 300), "Pluviómetro gravimétrico IoT – demo", font=fuente(F_BOLD, 92), fill=(255, 255, 255), anchor="mm")
    d.line([W / 2 - 200, 385, W / 2 + 200, 385], fill=(120, 170, 255), width=5)
    dtexto(d, (W / 2, 470), "Juan Sebastian Cruz Gallo", font=fuente(F_BOLD, 56), fill=(230, 236, 245), anchor="mm")
    dtexto(d, (W / 2, 540), "Ingeniería de Datos e IA · USTA Tunja", font=fuente(F_REG, 38), fill=(190, 200, 215), anchor="mm")
    dtexto(d, (W / 2, 650), "Cloud Computing", font=fuente(F_REG, 44), fill=(220, 228, 240), anchor="mm")
    dtexto(d, (W / 2, 712), "Sistemas de Adquisición y Procesamiento de Datos", font=fuente(F_REG, 44), fill=(220, 228, 240), anchor="mm")
    f = fuente(F_BOLD, 42); txt = "Prototipo simulado: gemelo digital + AWS"
    w = largo(txt, f) + 80
    d.rounded_rectangle([W / 2 - w / 2, 810, W / 2 + w / 2, 890], 40, fill=AMBAR)
    dtexto(d, (W / 2, 850), txt, font=f, fill=(255, 255, 255), anchor="mm")
    dtexto(d, (W / 2, 990), "Noviembre de 2026", font=fuente(F_REG, 30), fill=(150, 165, 185), anchor="mm")
    segmento(video, **estatico(lambda sub: img, 9, "portada_bienvenida", 0.8), fi=0.6, fo=0.6)

# ---------------------------------------------------------------- 2. arquitectura
def seg_arquitectura(video, G):
    seg_tarjeta(video, 2, "Arquitectura", "Del sensor al navegador: todo desplegado con Terraform en AWS (us-east-1)")
    arq = Image.open(f"{R}/docs/arquitectura.png").convert("RGBA")
    blanco = Image.new("RGBA", arq.size, (255, 255, 255, 255)); blanco.alpha_composite(arq); arq = blanco
    AW, AH = arq.size
    ch = AW * 9 / 16
    lienzo = Image.new("RGBA", (AW, int(ch) + 2), (255, 255, 255, 255))
    lienzo.paste(arq, (0, int((ch - AH) / 2)))
    oy = (ch - AH) / 2
    def zona(cx, w=1300):
        h = w * 9 / 16
        cx = min(max(cx, w / 2), AW - w / 2)
        return (cx - w / 2, oy + AH / 2 - h / 2 + 20, w, h)
    general = (0, 0, AW, ch)
    pasos = [(0.0, general, "arq_1"), (5.0, zona(560), "arq_2"), (12.0, zona(1300), "arq_3"),
             (19.0, zona(2250, 1250), "arq_4"), (26.0, zona(2450, 1300), "arq_5"),
             (33.0, zona(1450, 1500), "arq_6"), (40.0, general, "arq_7")]
    claves = [(a, c) for a, c, _ in pasos]
    cues = [(a, (pasos[i + 1][0] if i + 1 < len(pasos) else 46), cid, 0) for i, (a, c, cid) in enumerate(pasos)]
    def dib(t, sub, v):
        img = recorte(lienzo, caja_en(t, claves, 1.2))
        etiqueta(img, "2 · Arquitectura")
        subtitulo(img, sub)
        return img
    segmento(video, dib, 46, cues)

# ---------------------------------------------------------------- 3. wokwi
def seg_wokwi(video, G):
    seg_tarjeta(video, 3, "Montaje virtual en Wokwi", "ESP32 + celda de carga con HX711 + potenciómetro, simulados en el navegador")
    d = f"{G}/wokwi"
    fs = sorted(glob.glob(f"{d}/f_*.jpg")); ts = [float(os.path.basename(f)[2:-4]) for f in fs]
    rel = [x - ts[0] for x in ts]
    ev = {e["evento"]: e["t"] - ts[0] for e in json.load(open(f"{d}/eventos.json"))}
    full = (0, 0, W, H); codigo = (0, 70, 1000, 562.5); serie = (520, 292, 1400, 787.5)
    claves = [(0, full), (3.0, codigo), (ev["divisor"] - 0.3, full), (ev["play"] + 4.0, serie),
              (ev["celda_click"] - 0.5, full)]
    dur = rel[-1] + 0.5
    bordes = [0, 3.0, ev["divisor"], ev["play"], ev["menu"], ev["cmd_t"], ev["cmd_s"], ev["celda_click"],
              ev["pot_mover"], ev["peso_2kg"], dur]
    cues = [(bordes[i], bordes[i + 1], f"wokwi_{i + 1}", 0) for i in range(10)]
    def dib(t, sub, v):
        k = max(0, bisect.bisect_right(rel, t) - 1)
        img = recorte(abrir(fs[k]), caja_en(t, claves, 0.8))
        etiqueta(img, "3 · Wokwi", derecha=True, y=60)
        subtitulo(img, sub)
        return img
    segmento(video, dib, dur, cues)

# ---------------------------------------------------------------- 4. gemelo
def pantalla_terminal(lineas, sub, num_label, tam=24):
    img = fondo()
    img.alpha_composite(dibujar_terminal(lineas, 1720, 860, tam), (100, 40))
    etiqueta(img, num_label, derecha=True, y=50)
    subtitulo(img, sub)
    return img

def seg_cast(video, c, cid1, cid2, espera, label):
    def dib(t, sub, v): return pantalla_terminal(c.estado(t), sub, label)
    segmento(video, dib, c.fin + espera, [(0, c.fin + 0.5, cid1, 0), (c.fin + 0.5, c.fin + espera, cid2, 0)], fi=0.2, fo=0.2)

def seg_figura(video, path, cid, label, dur=8):
    im = Image.open(path).convert("RGBA")
    blanco = Image.new("RGBA", im.size, (255, 255, 255, 255)); blanco.alpha_composite(im)
    base = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    e, pos = encajar(blanco, (60, 30, W - 120, H - 230))
    base.alpha_composite(e, pos)
    etiqueta(base, label, derecha=True, y=24)
    img = base.copy(); subtitulo(img, P(cid))
    segmento(video, **estatico(lambda sub: img, dur, cid), fi=0.3, fo=0.3)

def seg_gemelo(video, G):
    seg_tarjeta(video, 4, "Gemelo digital", "Mismo algoritmo que el firmware, con una tormenta simulada de 3 horas")
    L = "4 · Gemelo digital"
    seg_cast(video, Cast(f"{G}/gemelo.cast", escribir=1.8), "gemelo_1", "gemelo_2", 5, L)
    seg_cast(video, Cast(f"{G}/verificar.cast", escribir=2.2), "verif_1", "verif_2", 6, L)
    RS = f"{R}/simulacion/resultados"
    seg_figura(video, f"{RS}/fig_filtros.png", "fig_filtros", L)
    seg_figura(video, f"{RS}/fig_umbral.png", "fig_umbral", L)
    seg_figura(video, f"{RS}/fig_validacion.png", "fig_validacion", L)

# ---------------------------------------------------------------- 5. prueba en vivo
def seg_vivo(video, G):
    seg_tarjeta(video, 5, "Prueba en vivo", "El gemelo publica 180 lecturas a AWS IoT Core y el dashboard real (CloudFront) se llena")
    d = f"{G}/live"
    fs = sorted(glob.glob(f"{d}/dash/f_*.jpg")); ts = [float(os.path.basename(f)[2:-4]) for f in fs]
    cast = Cast(f"{d}/live.cast", escribir=0, pausa=0)
    t0c = cast.cab["timestamp"]
    reg = {}
    for l in open(f"{d}/registro_publicacion.jsonl"):
        j = json.loads(l); reg[j["seq"]] = j["t_unix"]
    T0, TF = ts[0], ts[-1] + 4
    e58, e137, e141 = reg[58], reg[137], reg[141]
    tramos_real = [(T0, reg[2] + 1.0, 1), (reg[2] + 1.0, e58 - 4, 8), (e58 - 4, e58 + 7, 1), (e58 + 7, e137 - 4, 8),
                   (e137 - 4, e141 + 9, 1), (e141 + 9, reg[180] - 1, 8), (reg[180] - 1, TF, 1)]
    bordes = [T0, t0c + 0.8, reg[2] + 1.0, e58 - 4, e58 + 7, e137 - 4, e141 - 0.3, e141 + 9, reg[180] - 1, TF]
    ids = ["vivo_1", "vivo_2", "vivo_3", "vivo_58", "vivo_4", "vivo_137", "vivo_141", "vivo_5", "vivo_fin"]
    cues = [(bordes[i] - T0, bordes[i + 1] - T0, ids[i], 0) for i in range(9)]
    tramos = [(a - T0, b - T0, v) for a, b, v in tramos_real]
    escribir = max(0.1, t0c - T0 - 0.6)
    def dib(t, sub, v):
        tr = T0 + t
        k = max(0, bisect.bisect_right(ts, tr) - 1)
        img = Image.new("RGBA", (W, H), (20, 24, 32, 255))
        dr = ImageDraw.Draw(img)
        dr.rectangle([0, 0, W, 58], fill=(15, 23, 42))
        dtexto(dr, (24, 29), "5 · Prueba en vivo: gemelo digital → AWS IoT Core → DynamoDB → API → dashboard",
               font=fuente(F_BOLD, 26), fill=(255, 255, 255), anchor="lm")
        if tr >= t0c: lineas = cast.estado(tr - t0c)
        else:
            c2 = Cast.__new__(Cast); c2.__dict__.update(cast.__dict__); c2.escribir = escribir; c2.pausa = 99
            lineas = c2.estado(tr - T0)
        img.alpha_composite(dibujar_terminal(lineas, 762, 870, 19, "bash — publicación"), (4, 62))
        img.alpha_composite(abrir(fs[k]), (770, 62))
        if v > 1: acelerado(img, int(v))
        subtitulo(img, sub, y_base=H - 14)
        return img
    segmento(video, dib, TF - T0, cues, tramos, fi=0.3, fo=0.5)

# ---------------------------------------------------------------- 6. evidencia
def seg_evidencia(video, G):
    seg_tarjeta(video, 6, "Evidencia en AWS", "La API, DynamoDB y la consola confirman lo que se publicó")
    L = "6 · Evidencia en AWS"
    seg_cast(video, Cast(f"{G}/api.cast", escribir=3.0), "api_1", "api_2", 7, L)
    seg_cast(video, Cast(f"{G}/dynamo.cast", escribir=3.5), "dynamo_1", "dynamo_2", 7, L)
    seg_figura(video, f"{R}/docs/evidencia/anexo_dynamodb.png", "anexo_dynamo", L, 7)
    seg_figura(video, f"{R}/docs/evidencia/anexo_iot.png", "anexo_iot", L, 7)

# ---------------------------------------------------------------- 7. cierre
CONCLUSIONES = ["Funciona de punta a punta: ESP32 simulado → IoT Core → DynamoDB → API → dashboard.",
                "Mediana + EMA bajan el RMSE de 4,33 a 1,44 g; los golpes quedan como FUERA_RANGO.",
                "La validación con el potenciómetro detecta el drift en 5 min: error −9,9 % → −0,4 %.",
                "Firmware y gemelo son equivalentes (180/180); el prototipo cuesta 0,94 USD/mes en AWS."]

def cierre_img(activa):
    img = fondo(); d = ImageDraw.Draw(img)
    d.text((W / 2, 130), "Conclusiones", font=fuente(F_BOLD, 76), fill=(255, 255, 255), anchor="mm")
    for i, c in enumerate(CONCLUSIONES):
        y = 260 + i * 90
        on = activa is None or activa == i
        d.ellipse([150, y - 9, 168, y + 9], fill=(120, 170, 255) if on else (70, 95, 140))
        dtexto(d, (195, y), c, font=fuente(F_REG, 40), fill=(240, 244, 250) if on else (125, 140, 165), anchor="lm")
    d.line([W / 2 - 300, 680, W / 2 + 300, 680], fill=(120, 170, 255), width=3)
    d.text((W / 2, 760), "github.com/jseb-cruz/pluviometro-iot", font=fuente(F_BOLD, 48), fill=(255, 255, 255), anchor="mm")
    d.text((W / 2, 840), "wokwi.com/projects/481702637981326337", font=fuente(F_BOLD, 48), fill=(255, 255, 255), anchor="mm")
    dtexto(d, (W / 2, 950), "Juan Sebastian Cruz Gallo · USTA Tunja · Noviembre de 2026", font=fuente(F_REG, 32), fill=(170, 185, 205), anchor="mm")
    etiqueta(img, "7 · Cierre", derecha=True, y=24)
    return img

def seg_cierre(video, G):
    ids = ["cierre_c1", "cierre_c2", "cierre_c3", "cierre_c4", "cierre_gracias"]
    # la conclusion que se esta leyendo se resalta; al final se ven todas
    imgs = [cierre_img(i if i < 4 else None) for i in range(5)]
    largos = [2.0, 3.5, 3.5, 3.5, 2.0]          # sin voz suman 14,5 s (+1,5 s de cola = 16 s)
    cues, a = [], 0
    for k, cid in enumerate(ids):
        cues.append((a, a + largos[k], cid, 0.5 if k == 0 else 0)); a += largos[k]
    cues.append((a, a + 1.5, None, 0))           # cola: el fundido final no tapa la ultima frase
    def dib(t, sub, v):
        k = min(4, max(i for i, c in enumerate(cues) if c[0] <= t))
        return imgs[k]
    segmento(video, dib, a + 1.5, cues, fi=0.5, fo=1.0)

SEGS = [("1", seg_portada), ("2", seg_arquitectura), ("3", seg_wokwi), ("4", seg_gemelo),
        ("5", seg_vivo), ("6", seg_evidencia), ("7", seg_cierre)]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("grabaciones"); ap.add_argument("salida"); ap.add_argument("--voz")
    a = ap.parse_args()
    if a.voz: DUR.update(json.load(open(os.path.join(a.voz, "duraciones.json"))))
    v = Video(a.salida)
    for k, fn in SEGS:
        if SOLO and k not in SOLO.split(","): continue
        n0 = v.n; fn(v, os.path.abspath(a.grabaciones)); print(f"segmento {k}: {(v.n - n0) / FPS:.1f} s", flush=True)
    v.cerrar()
    json.dump([{"id": c[0], "voz": c[1], "sub_ini": c[2], "sub_fin": c[3], "dur_voz": DUR.get(c[0])} for c in CUES],
              open(a.salida + ".cues.json", "w"), indent=1)
    print(f"total {v.n / FPS:.1f} s")
