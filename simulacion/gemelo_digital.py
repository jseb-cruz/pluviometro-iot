"""
Gemelo digital del pluviometro gravimetrico IoT.

Reemplaza el montaje fisico: genera la senal CRUDA que entregarian el HX711 y el
potenciometro durante una tormenta simulada de 3 horas, con sus fuentes de error, y le
aplica exactamente el mismo tratamiento del firmware (firmware/pluviometro_mqtt):

  1. Mediana de 5 muestras      2. Media exponencial (EMA)     3. Calibracion
  4. Correccion del error sistematico (regresion)               5. Validacion cruzada
     + estimacion y compensacion del drift con el potenciometro

Fuentes de error modeladas (todas configurables en MODELO):
  - ruido blanco del HX711, deriva termica del offset y no linealidad de la celda
  - picos por impacto de gotas (proceso de Poisson proporcional a la intensidad)
  - rafagas de viento (ruido de baja frecuencia)
  - un golpe al equipo (90 s con +400 g) para probar la validacion de rango
  - perdida de ganancia del 10 % (creep de la celda) a partir de t = 2,2 h
  - potenciometro: ruido del ADC, no linealidad, cuantizacion de 12 bits y zona muerta
    por friccion del flotador

Uso:
  python gemelo_digital.py                  # simula, mide y genera figuras en ./resultados
  python gemelo_digital.py --publicar       # ademas publica las lecturas a AWS IoT Core
        [--endpoint X] [--topico Y] [--intervalo 2] [--max-mensajes N]
        (usa boto3 si esta instalado; si no, la AWS CLI ya configurada; guarda
        registro_publicacion.jsonl con la hora de cada envio)

Requiere: numpy, matplotlib
"""
import argparse
import json
import os
import subprocess
import time

import numpy as np

# ---------------------------------------------------------------------------
# Parametros (los del firmware salen de firmware/pluviometro_mqtt/config.h)
# ---------------------------------------------------------------------------
FIRMWARE = {
    "G_POR_MM": 20.106,          # embudo de 160 mm
    "EMA_ALFA": 0.15,
    "MASA_MAX_G": 2000.0,
    "MASA_TOLERANCIA_G": 30.0,
    "SALTO_MAX_G": 200.0,
    "TOL_RATIO": 0.08,           # tolerancia relativa entre sensores
    "TOL_ABS_MM": 0.8,           # piso absoluto: resolucion del flotador (zona muerta + ruido)
    "MM_MIN_VALIDACION": 1.0,
    "N_DRIFT": 5,                # publicaciones seguidas fuera de banda para estimar el drift
    "INTERVALO_S": 60,
}

MODELO = {
    "semilla": 7,
    "fs_hz": 10.0,               # tasa del HX711
    "duracion_h": 3.0,
    "factor_real": 418.7,        # cuentas por gramo (celda real, desconocido para el sistema)
    "offset_real": -8432.0,      # cuentas con el recipiente vacio
    "no_linealidad": 1.5e-6,     # g extra por g^2 (0,3 % a 2 kg)
    "ruido_g": 0.25,             # ruido blanco del HX711 a 10 SPS (desv. estandar, g)
    "deriva_termica_g": 1.2,     # amplitud de la deriva del offset (g)
    "impacto_media_g": 15.0,     # impulso medio de cada gota grande
    "impactos_por_s_a_20mmh": 0.5,
    "viento_g": 1.5,
    "golpe_inicio_h": 0.95, "golpe_dur_s": 90, "golpe_g": 400.0,
    "drift_inicio_h": 2.2, "drift_rampa_min": 5.0, "drift_ganancia": 0.90,
    # potenciometro
    "pot_mv0": 300.0, "pot_mv_por_mm": 20.0, "pot_ruido_mv": 8.0, "pot_promedio": 16,
    "pot_zona_muerta_mm": 0.3, "pot_no_lineal_mv": 15.0,
}

# Tormenta: suma de chubascos gaussianos (centro h, pico mm/h, ancho h)
CHUBASCOS = [(0.60, 30.0, 0.25), (1.35, 8.0, 0.15), (2.45, 22.0, 0.20)]


# ---------------------------------------------------------------------------
# 1) Mundo fisico: lluvia real y senales crudas
# ---------------------------------------------------------------------------
def simular_mundo(m=MODELO):
    rng = np.random.default_rng(m["semilla"])
    fs = m["fs_hz"]
    n = int(m["duracion_h"] * 3600 * fs)
    t = np.arange(n) / fs                                  # s
    th = t / 3600                                          # h

    intensidad = sum(p * np.exp(-0.5 * ((th - c) / w) ** 2) for c, p, w in CHUBASCOS)  # mm/h
    lluvia_mm = np.cumsum(intensidad / 3600 / fs)          # acumulado real
    masa_real = lluvia_mm * FIRMWARE["G_POR_MM"]           # g de agua en el recipiente

    # Ganancia: cae al 90 % con una rampa de 5 min (creep / falla de la celda)
    t0 = m["drift_inicio_h"] * 3600
    rampa = np.clip((t - t0) / (m["drift_rampa_min"] * 60), 0, 1)
    ganancia = 1 - (1 - m["drift_ganancia"]) * rampa

    # Perturbaciones en gramos
    deriva = m["deriva_termica_g"] * np.sin(2 * np.pi * t / (2.5 * 3600))
    ruido = rng.normal(0, m["ruido_g"], n)
    lam = m["impactos_por_s_a_20mmh"] * intensidad / 20 / fs
    impactos = (rng.random(n) < lam) * rng.exponential(m["impacto_media_g"], n)
    viento = np.zeros(n)
    e = rng.normal(0, 1, n)
    for i in range(1, n):                                  # AR(1): ruido de baja frecuencia
        viento[i] = 0.995 * viento[i - 1] + e[i]
    viento *= m["viento_g"] / viento.std() * np.clip(intensidad / 20, 0.15, 1)
    golpe = np.zeros(n)
    g0 = int(m["golpe_inicio_h"] * 3600 * fs)
    golpe[g0:g0 + int(m["golpe_dur_s"] * fs)] = m["golpe_g"]

    carga = masa_real + golpe + impactos + viento
    carga_medida = carga + m["no_linealidad"] * carga ** 2
    raw = m["offset_real"] + m["factor_real"] * (ganancia * carga_medida + deriva + ruido)
    raw = np.round(raw).astype(np.int64)                   # el HX711 entrega enteros

    # Potenciometro: nivel con zona muerta (friccion), luego mV con no linealidad y ruido
    nivel = np.empty(n)
    z = m["pot_zona_muerta_mm"]
    nivel[0] = lluvia_mm[0]
    for i in range(1, n):
        d = lluvia_mm[i] - nivel[i - 1]
        nivel[i] = nivel[i - 1] + (d - np.sign(d) * z if abs(d) > z else 0.0)
    mv = m["pot_mv0"] + m["pot_mv_por_mm"] * nivel
    mv += m["pot_no_lineal_mv"] * ((mv - 1650) / 1650) ** 3
    return dict(t=t, th=th, intensidad=intensidad, lluvia_mm=lluvia_mm, masa_real=masa_real,
                raw=raw, pot_mv_limpio=mv, ganancia=ganancia, golpe=golpe, rng=rng)


def leer_pot(mv_limpio, rng, m=MODELO):
    """Lo que hace leerPotMv(): promedio de 16 lecturas, cuantizadas a 1 mV."""
    lect = mv_limpio + rng.normal(0, m["pot_ruido_mv"], m["pot_promedio"])
    return float(np.mean(np.round(lect)))


# ---------------------------------------------------------------------------
# 2) Calibracion simulada (lo que se haria vertiendo agua medida)
# ---------------------------------------------------------------------------
def calibrar(m=MODELO, puntos=(0, 100, 200, 400, 600, 800, 1000, 1500, 2000)):
    rng = np.random.default_rng(m["semilla"] + 1)
    ref = np.array(puntos, float)
    carga = ref + m["no_linealidad"] * ref ** 2
    raw = np.array([np.mean(m["offset_real"] + m["factor_real"] * (c + rng.normal(0, m["ruido_g"], 30)))
                    for c in carga])
    mm = ref / FIRMWARE["G_POR_MM"]
    pot = np.array([leer_pot(m["pot_mv0"] + m["pot_mv_por_mm"] * x
                             + m["pot_no_lineal_mv"] * (((m["pot_mv0"] + m["pot_mv_por_mm"] * x) - 1650) / 1650) ** 3,
                             rng) for x in mm])
    # Calibracion provisional: tara (0 g) + una pesa de 1000 g, como se hace en la practica
    offset = raw[0]
    i1 = list(puntos).index(1000)
    factor = (raw[i1] - offset) / ref[i1]
    medido = (raw - offset) / factor
    a, b = np.polyfit(ref, medido, 1)                      # medido = a*real + b
    corregido = (medido - b) / a
    k_pot, c_pot = np.polyfit(pot, mm, 1)                  # mm = k*mV + c
    rmse = lambda x: float(np.sqrt(np.mean(np.square(x))))
    return {
        "offset": float(offset), "factor": float(factor), "a": float(a), "b": float(b),
        "k_pot": float(k_pot), "c_pot": float(c_pot),
        "rmse_antes_g": rmse(medido - ref), "rmse_despues_g": rmse(corregido - ref),
        "rmse_pot_mm": rmse(k_pot * pot + c_pot - mm),
        "puntos": {"ref": ref.tolist(), "medido": medido.tolist(), "corregido": corregido.tolist()},
    }


# ---------------------------------------------------------------------------
# 3) El mismo tratamiento del firmware
# ---------------------------------------------------------------------------
def mediana5_causal(x):
    v = np.lib.stride_tricks.sliding_window_view(np.concatenate([np.repeat(x[:1], 4), x]), 5)
    return np.median(v, axis=1)


def ema(x, alfa):
    y = np.empty(len(x))
    y[0] = x[0]
    for i in range(1, len(x)):
        y[i] = alfa * x[i] + (1 - alfa) * y[i - 1]
    return y


def fuera_de_banda(mm_celda, mm_pot, fw=FIRMWARE, tol_abs=None):
    """Regla de validacion cruzada: tolerancia relativa con un piso absoluto."""
    tol_abs = fw["TOL_ABS_MM"] if tol_abs is None else tol_abs
    return abs(mm_celda - mm_pot) > max(fw["TOL_RATIO"] * mm_pot, tol_abs)


def procesar(mundo, cal, fw=FIRMWARE, mm_min=None, tol_abs=None):
    mm_min = fw["MM_MIN_VALIDACION"] if mm_min is None else mm_min
    fs = MODELO["fs_hz"]
    raw = mundo["raw"].astype(float)
    med = mediana5_causal(raw)
    filt = ema(med, fw["EMA_ALFA"])
    a_g = lambda r: (r - cal["offset"]) / cal["factor"]     # paso 3
    rng = np.random.default_rng(MODELO["semilla"] + 2)

    paso = int(fw["INTERVALO_S"] * fs)
    pubs, hist = [], []                                    # (cociente, fuera de banda)
    ganancia_est, masa_ant, seq = 1.0, 0.0, 0
    for k in range(paso - 1, len(raw), paso):
        masa_filt = a_g(filt[k])
        masa_reg = (masa_filt - cal["b"]) / cal["a"]       # paso 4: regresion
        mm_sin = masa_reg / fw["G_POR_MM"]
        pot_mv = leer_pot(mundo["pot_mv_limpio"][k], rng)
        mm_pot = cal["k_pot"] * pot_mv + cal["c_pot"]

        calidad = "OK"                                     # paso 5: validacion
        if (masa_reg < -fw["MASA_TOLERANCIA_G"] or masa_reg > fw["MASA_MAX_G"]
                or abs(masa_reg - masa_ant) > fw["SALTO_MAX_G"]):
            calidad = "FUERA_RANGO"
        ratio = None
        if mm_pot > mm_min and calidad == "OK":
            ratio = mm_sin / mm_pot
            hist.append((ratio, fuera_de_banda(mm_sin, mm_pot, fw, tol_abs)))
            ult = hist[-fw["N_DRIFT"]:]
            if len(ult) == fw["N_DRIFT"] and all(f for _, f in ult):
                ganancia_est = float(np.median([r for r, _ in ult]))   # estimacion del drift
            elif len(ult) == fw["N_DRIFT"] and not any(f for _, f in ult):
                ganancia_est = 1.0                          # la celda volvio a la normalidad
            if hist[-1][1]:
                ok_corr = ganancia_est != 1.0 and not fuera_de_banda(mm_sin / ganancia_est, mm_pot, fw, tol_abs)
                calidad = "CORREGIDA" if ok_corr else "SOSPECHOSA"
        if calidad == "FUERA_RANGO":
            masa_reg = masa_ant                            # se retiene el ultimo valor valido
            mm_sin = masa_reg / fw["G_POR_MM"]
        masa_reg_ant = masa_ant                            # antes de compensar, para la tasa
        masa_ant = masa_reg
        masa_corr = masa_reg / ganancia_est
        mm = masa_corr / fw["G_POR_MM"]
        t_s = mundo["t"][k]
        # Misma ganancia en los dos envios: activar la compensacion no aparece como lluvia
        horas = fw["INTERVALO_S"] / 3600
        tasa = 0.0 if seq == 0 else max(0.0, (masa_reg - masa_reg_ant) / ganancia_est / fw["G_POR_MM"] / horas)
        seq += 1
        pubs.append({
            "seq": seq, "t_h": round(t_s / 3600, 4), "raw": int(mundo["raw"][k]),
            "masa_g": round(masa_corr, 1),
            "lluvia_cruda_mm": round(a_g(raw[k]) / fw["G_POR_MM"], 2),
            "lluvia_mm": round(mm, 2), "lluvia_sin_corregir_mm": round(mm_sin, 2),
            "pot_mv": round(pot_mv), "lluvia_pot_mm": round(mm_pot, 2),
            "tasa_mm_h": round(tasa, 2), "ratio": None if ratio is None else round(ratio, 3),
            "ganancia_est": round(ganancia_est, 3), "calidad": calidad,
            "drift_sim": bool(mundo["ganancia"][k] < 0.999),
            "lluvia_real_mm": round(float(mundo["lluvia_mm"][k]), 2),
        })
    return pubs, dict(raw=raw, med=med, filt=filt)


# ---------------------------------------------------------------------------
# 4) Metricas
# ---------------------------------------------------------------------------
def metricas(mundo, cal, pubs, senales):
    fs = MODELO["fs_hz"]
    rmse = lambda x: float(np.sqrt(np.mean(np.square(x))))
    real = mundo["masa_real"]
    a_g = lambda r: ((r - cal["offset"]) / cal["factor"] - cal["b"]) / cal["a"]
    cerca_golpe = np.convolve(mundo["golpe"] > 0, np.ones(int(20 * fs)), "same") > 0   # +-10 s
    pre = (mundo["ganancia"] > 0.999) & ~cerca_golpe
    lluvia = pre & (mundo["intensidad"] > 5)
    err = {k: a_g(senales[k]) - real for k in ("raw", "med", "filt")}

    t_drift = MODELO["drift_inicio_h"]
    antes = [p for p in pubs if p["t_h"] < t_drift and p["calidad"] != "FUERA_RANGO"]
    despues = [p for p in pubs if p["t_h"] >= t_drift]
    primera = lambda estados: next((p["t_h"] for p in despues if p["calidad"] in estados), None)
    t_det, t_corr = primera(("SOSPECHOSA", "CORREGIDA")), primera(("CORREGIDA",))
    final = pubs[-1]
    golpe_h = (MODELO["golpe_inicio_h"], MODELO["golpe_inicio_h"] + MODELO["golpe_dur_s"] / 3600 + 1 / 60)

    falsas = {}
    reglas = [("Solo relativa, desde 1 mm", 1.0, 0.0), ("Solo relativa, desde 3 mm", 3.0, 0.0),
              ("Solo relativa, desde 5 mm", 5.0, 0.0), ("Relativa + 0,5 mm, desde 1 mm", 1.0, 0.5),
              ("Relativa + 0,8 mm, desde 1 mm", 1.0, 0.8)]
    for nombre, mm_min, tol_abs in reglas:
        p2, _ = procesar(mundo, cal, mm_min=mm_min, tol_abs=tol_abs)
        a2 = [p for p in p2 if p["t_h"] < t_drift and p["calidad"] != "FUERA_RANGO"]
        d2 = next((p["t_h"] for p in p2 if p["t_h"] >= t_drift and p["calidad"] != "OK"), None)
        falsas[nombre] = {"falsas_pct": round(100 * sum(p["calidad"] != "OK" for p in a2) / len(a2), 1),
                          "deteccion_min": None if d2 is None else round((d2 - t_drift) * 60, 1)}

    return {
        "filtros_rmse_g_con_lluvia": {k: round(rmse(err[k][lluvia]), 2) for k in err},
        "filtros_error_max_g_con_lluvia": {k: round(float(np.max(np.abs(err[k][lluvia]))), 1) for k in err},
        "ema_constante_tiempo_s": round((1 - FIRMWARE["EMA_ALFA"]) / FIRMWARE["EMA_ALFA"] / fs, 2),
        "calibracion": {k: round(v, 4) for k, v in cal.items() if k != "puntos"},
        "reglas_validacion": falsas,
        "falsas_alarmas_pct_antes_drift": round(100 * sum(p["calidad"] != "OK" for p in antes) / len(antes), 1),
        "golpe_detectado": any(p["calidad"] == "FUERA_RANGO" and golpe_h[0] <= p["t_h"] <= golpe_h[1] for p in pubs),
        "drift_inicio_h": t_drift,
        "drift_detectado_tras_min": None if t_det is None else round((t_det - t_drift) * 60, 1),
        "drift_corregido_tras_min": None if t_corr is None else round((t_corr - t_drift) * 60, 1),
        "ganancia_estimada": final["ganancia_est"],
        "lluvia_real_final_mm": final["lluvia_real_mm"],
        "lluvia_sin_correccion_final_mm": final["lluvia_sin_corregir_mm"],
        "lluvia_corregida_final_mm": final["lluvia_mm"],
        "error_final_sin_correccion_pct": round(100 * (final["lluvia_sin_corregir_mm"] / final["lluvia_real_mm"] - 1), 1),
        "error_final_corregido_pct": round(100 * (final["lluvia_mm"] / final["lluvia_real_mm"] - 1), 1),
        "publicaciones": len(pubs),
    }


# ---------------------------------------------------------------------------
# 5) Figuras
# ---------------------------------------------------------------------------
def figuras(mundo, cal, pubs, senales, met, carpeta):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    C = {"real": "#1b2631", "raw": "#b4b2a9", "med": "#e8893a", "filt": "#2b6a9e", "pot": "#1d9e75", "mal": "#c0392b"}
    a_g = lambda r: ((r - cal["offset"]) / cal["factor"] - cal["b"]) / cal["a"]
    th = mundo["th"]

    # Fig. A: ventana de 2 minutos en el pico del primer chubasco
    i0 = int(0.60 * 3600 * MODELO["fs_hz"])
    s = slice(i0, i0 + 1200)
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    x = (mundo["t"][s] - mundo["t"][i0])
    ax.plot(x, a_g(senales["raw"][s]), color=C["raw"], lw=0.7, label="Cruda (10 Hz)")
    ax.plot(x, a_g(senales["med"][s]), color=C["med"], lw=0.9, label="Mediana de 5")
    ax.plot(x, a_g(senales["filt"][s]), color=C["filt"], lw=1.5, label="Mediana + EMA")
    ax.plot(x, mundo["masa_real"][s], color=C["real"], lw=1.0, ls="--", label="Masa real")
    ax.set(xlabel="Tiempo (s)", ylabel="Masa (g)", title="Efecto de los filtros en el pico del chubasco")
    ax.legend(ncol=4, fontsize=7, loc="upper left", frameon=False)
    fig.tight_layout(); fig.savefig(os.path.join(carpeta, "fig_filtros.png"), dpi=200); plt.close(fig)

    # Fig. B: lluvia acumulada y validacion
    tp = np.array([p["t_h"] for p in pubs])
    g = lambda k: np.array([np.nan if p[k] is None else p[k] for p in pubs], float)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 5.0), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    a1.plot(th, mundo["lluvia_mm"], color=C["real"], lw=1, ls="--", label="Lluvia real")
    a1.plot(tp, g("lluvia_sin_corregir_mm"), color=C["mal"], lw=1, label="Celda sin compensar")
    a1.plot(tp, g("lluvia_mm"), color=C["filt"], lw=1.6, label="Celda corregida (publicada)")
    a1.plot(tp, g("lluvia_pot_mm"), color=C["pot"], lw=1, ls=":", label="Potenciómetro")
    a1.axvline(MODELO["drift_inicio_h"], color="#888", lw=0.8, ls="--")
    a1.text(MODELO["drift_inicio_h"] + 0.02, 2, "inicio del drift (−10 %)", fontsize=7, color="#555")
    a1.set(ylabel="Lluvia (mm)", title="Tormenta simulada de 3 h: lluvia acumulada")
    a1.legend(fontsize=7, frameon=False, loc="upper left")
    tol = FIRMWARE["TOL_RATIO"]
    a2.axhspan(1 - tol, 1 + tol, color=C["pot"], alpha=0.10, label=f"Banda ±{int(tol*100)} %")
    a2.plot(tp, g("ratio"), color=C["med"], lw=1.2, marker=".", ms=3, label="Cociente celda/potenciómetro")
    for est, col, mk in (("SOSPECHOSA", C["mal"], "x"), ("CORREGIDA", C["filt"], "o"), ("FUERA_RANGO", "#000", "^")):
        sel = [p for p in pubs if p["calidad"] == est]
        if sel:
            y = [p["ratio"] if p["ratio"] is not None else 1.12 for p in sel]
            a2.scatter([p["t_h"] for p in sel], y, color=col, marker=mk, s=14, zorder=3, label=est)
    a2.set(xlabel="Tiempo (h)", ylabel="Cociente", ylim=(0.75, 1.2))
    a2.legend(fontsize=7, frameon=False, ncol=3, loc="lower left")
    fig.tight_layout(); fig.savefig(os.path.join(carpeta, "fig_validacion.png"), dpi=200); plt.close(fig)

    # Fig. C: falsas alarmas segun el umbral minimo de comparacion
    fa = met["reglas_validacion"]
    ks = list(fa.keys())
    v = [fa[k]["falsas_pct"] for k in ks]
    fig, ax = plt.subplots(figsize=(3.6, 2.8))
    etiquetas = ["Rel.\n>1 mm", "Rel.\n>3 mm", "Rel.\n>5 mm", "Rel.\n+0,5 mm", "Rel.\n+0,8 mm"]
    ax.bar(etiquetas, v, color=[C["raw"]] * 4 + [C["filt"]])
    for i, x in enumerate(v):
        ax.text(i, x + 0.3, f"{x:g} %", ha="center", fontsize=8)
    ax.set(ylabel="Falsas alarmas (%)", title="Falsas alarmas sin falla, por regla")
    ax.tick_params(axis="x", labelsize=7)
    fig.tight_layout(); fig.savefig(os.path.join(carpeta, "fig_umbral.png"), dpi=200); plt.close(fig)

    # Fig. D: calibracion
    pts = cal["puntos"]
    ref = np.array(pts["ref"])
    fig, ax = plt.subplots(figsize=(3.6, 2.6))
    ax.plot(ref, np.array(pts["medido"]) - ref, "o-", color=C["mal"], ms=3, label="Antes")
    ax.plot(ref, np.array(pts["corregido"]) - ref, "s-", color=C["filt"], ms=3, label="Después")
    ax.axhline(0, color="#888", lw=0.6)
    ax.set(xlabel="Masa de referencia (g)", ylabel="Error (g)", title="Calibración de la celda")
    ax.legend(fontsize=7, frameon=False)
    fig.tight_layout(); fig.savefig(os.path.join(carpeta, "fig_calibracion.png"), dpi=200); plt.close(fig)


# ---------------------------------------------------------------------------
# 6) Publicacion opcional a AWS IoT Core (misma forma que el firmware)
# ---------------------------------------------------------------------------
CAMPOS_FIRMWARE = ("seq", "raw", "masa_g", "lluvia_cruda_mm", "lluvia_mm", "pot_mv",
                   "lluvia_pot_mm", "tasa_mm_h", "ratio", "calidad", "drift_sim")


def _cliente_publicacion(endpoint):
    """boto3 (cliente iot-data) si esta instalado; si no, la AWS CLI."""
    try:
        import boto3
        cliente = boto3.client("iot-data", endpoint_url=f"https://{endpoint}")
        return "boto3", lambda topico, cuerpo: cliente.publish(topic=topico, qos=1, payload=cuerpo)
    except ImportError:
        def con_cli(topico, cuerpo):
            subprocess.run(["aws", "iot-data", "publish", "--endpoint-url", f"https://{endpoint}",
                            "--topic", topico, "--cli-binary-format", "raw-in-base64-out",
                            "--payload", cuerpo], check=True, stdout=subprocess.DEVNULL)
        return "aws-cli", con_cli


def publicar(pubs, endpoint, topico, intervalo, registro, maximo=None):
    """Publica las lecturas y guarda un registro JSONL con la hora de cada envio
    (sirve para sincronizar la grabacion del dashboard con los eventos)."""
    metodo, enviar = _cliente_publicacion(endpoint)
    print(f"Publicando en {topico} con {metodo} cada {intervalo:g} s", flush=True)
    with open(registro, "w", encoding="utf-8") as reg:
        for p in pubs[:maximo]:
            msg = {k: p[k] for k in CAMPOS_FIRMWARE if p[k] is not None}
            msg["epoch_s"] = int(time.time())
            msg["fuente"] = "gemelo_digital"
            enviar(topico, json.dumps(msg))
            t = time.time()
            hora = time.strftime("%H:%M:%S", time.localtime(t))
            print(f"{hora}  seq {p['seq']:3d}  {p['lluvia_mm']:6.2f} mm  {p['calidad']}", flush=True)
            reg.write(json.dumps({"t_unix": round(t, 3), "hora": hora, "seq": p["seq"],
                                  "lluvia_mm": p["lluvia_mm"], "calidad": p["calidad"],
                                  "topico": topico}) + "\n")
            reg.flush()
            time.sleep(intervalo)
    print(f"Registro de publicacion en {registro}", flush=True)


def montecarlo(n):
    """Repite la tormenta con n semillas de ruido distintas y resume la robustez."""
    fal, det, err_sin, err_cor, golpes = [], [], [], [], 0
    for k in range(n):
        m = dict(MODELO, semilla=1000 + k)
        mundo, cal = simular_mundo(m), calibrar(m)
        pubs, _ = procesar(mundo, cal)
        t_d = m["drift_inicio_h"]
        antes = [p for p in pubs if p["t_h"] < t_d and p["calidad"] != "FUERA_RANGO"]
        fal.append(100 * sum(p["calidad"] != "OK" for p in antes) / len(antes))
        d = next((p["t_h"] for p in pubs if p["t_h"] >= t_d and p["calidad"] != "OK"), None)
        det.append(np.nan if d is None else (d - t_d) * 60)
        f = pubs[-1]
        err_sin.append(100 * (f["lluvia_sin_corregir_mm"] / f["lluvia_real_mm"] - 1))
        err_cor.append(100 * (f["lluvia_mm"] / f["lluvia_real_mm"] - 1))
        g0 = m["golpe_inicio_h"]
        golpes += any(p["calidad"] == "FUERA_RANGO" and g0 <= p["t_h"] <= g0 + 0.05 for p in pubs)
    r = lambda x: round(float(x), 2)
    return {"tormentas": n,
            "falsas_alarmas_pct_media": r(np.mean(fal)), "falsas_alarmas_pct_max": r(np.max(fal)),
            "drift_detectado_pct": r(100 * np.mean(~np.isnan(det))),
            "deteccion_min_media": r(np.nanmean(det)), "deteccion_min_max": r(np.nanmax(det)),
            "error_final_sin_correccion_pct_media": r(np.mean(err_sin)),
            "error_final_corregido_pct_media": r(np.mean(err_cor)),
            "error_final_corregido_pct_max_abs": r(np.max(np.abs(err_cor))),
            "golpe_detectado_pct": r(100 * golpes / n)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados"))
    ap.add_argument("--publicar", action="store_true", help="publica las lecturas en AWS IoT Core")
    ap.add_argument("--endpoint", default=None, help="endpoint ATS (terraform output iot_endpoint)")
    ap.add_argument("--topico", default="pluviometro/pluviometro-esp32-01/telemetria")
    ap.add_argument("--intervalo", type=float, default=2.0, help="segundos entre mensajes al publicar")
    ap.add_argument("--registro", default=None,
                    help="JSONL con la hora de cada envio (por defecto <salida>/registro_publicacion.jsonl)")
    ap.add_argument("--max-mensajes", type=int, default=None, help="publica solo los primeros n mensajes")
    ap.add_argument("--montecarlo", type=int, default=30, help="tormentas para la prueba de robustez (0 = omitir)")
    args = ap.parse_args()
    os.makedirs(args.salida, exist_ok=True)

    mundo = simular_mundo()
    cal = calibrar()
    pubs, senales = procesar(mundo, cal)
    met = metricas(mundo, cal, pubs, senales)
    if args.montecarlo:
        met["montecarlo"] = montecarlo(args.montecarlo)
    figuras(mundo, cal, pubs, senales, met, args.salida)

    with open(os.path.join(args.salida, "metricas.json"), "w", encoding="utf-8") as f:
        json.dump(met, f, indent=2, ensure_ascii=False)
    with open(os.path.join(args.salida, "publicaciones.jsonl"), "w", encoding="utf-8") as f:
        for p in pubs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(json.dumps(met, indent=2, ensure_ascii=False))
    print(f"\nResultados en {args.salida}", flush=True)

    if args.publicar:
        if not args.endpoint:
            args.endpoint = subprocess.run(["aws", "iot", "describe-endpoint", "--endpoint-type", "iot:Data-ATS",
                                            "--query", "endpointAddress", "--output", "text"],
                                           capture_output=True, text=True, check=True).stdout.strip()
        registro = args.registro or os.path.join(args.salida, "registro_publicacion.jsonl")
        publicar(pubs, args.endpoint, args.topico, args.intervalo, registro, args.max_mensajes)


if __name__ == "__main__":
    main()
