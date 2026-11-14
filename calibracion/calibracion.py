"""
Pluviómetro gravimétrico IoT — Análisis de calibración
Lee datos_calibracion.csv (líneas CAL, del sketch) y calcula:
  1) Factor y offset de la celda para el firmware: masa_g = (raw - offset) / factor
  2) Análisis de error sistemático (diapositiva 8): bias, regresión, corrección, RMSE
  3) Calibración del potenciómetro: mm de lluvia en función de mV

Uso:  python calibracion.py [datos_calibracion.csv]
Requiere: numpy (matplotlib es opcional, para la gráfica)
"""
import sys
import numpy as np

DIAMETRO_EMBUDO_M = 0.160
AREA_M2 = np.pi * (DIAMETRO_EMBUDO_M / 2) ** 2
G_POR_MM = AREA_M2 * 1000          # 1 mm = 1 kg/m²  ->  ~20,1 g por mm


def cargar(ruta):
    filas = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            partes = linea.strip().split(",")
            if len(partes) == 5 and partes[0] == "CAL":
                try:
                    filas.append([float(x) for x in partes[1:]])
                except ValueError:
                    pass   # encabezado
    if len(filas) < 3:
        sys.exit("Se necesitan al menos 3 puntos CAL, (idealmente 6 o más).")
    d = np.array(filas)
    return d[:, 0], d[:, 1], d[:, 2], d[:, 3]


def rmse(x):
    return float(np.sqrt(np.mean(np.square(x))))


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else "datos_calibracion.csv"
    ref, raw, raw_desv, pot = cargar(ruta)
    print(f"Área del embudo: {AREA_M2:.5f} m²  ->  1 mm = {G_POR_MM:.2f} g\n")

    # ---- 1) Calibración de la celda: raw = factor * g + offset ----
    factor, offset = np.polyfit(ref, raw, 1)
    masa_cal = (raw - offset) / factor
    print("== 1) Constantes para el firmware ==")
    print(f"  factor = {factor:.4f} cuentas/g")
    print(f"  offset = {offset:.1f} cuentas")
    print(f"  Ruido típico: {np.mean(raw_desv) / abs(factor):.2f} g "
          f"({np.mean(raw_desv) / abs(factor) / G_POR_MM:.3f} mm)")
    print(f"  RMSE tras calibrar: {rmse(masa_cal - ref):.2f} g "
          f"({rmse(masa_cal - ref) / G_POR_MM:.3f} mm)\n")

    # ---- 2) Error sistemático con calibración provisional de un solo punto ----
    # "Medido" = lo que entregaría el sensor calibrado con tara + una sola masa
    # (la práctica habitual). Así se ve el bias real que corrige la regresión.
    i0 = int(np.argmin(ref))
    i1 = int(np.argsort(ref)[len(ref) // 2])          # masa intermedia
    f_prov = (raw[i1] - raw[i0]) / (ref[i1] - ref[i0])
    medido = (raw - raw[i0]) / f_prov
    bias = float(np.mean(medido - ref))
    a, b = np.polyfit(ref, medido, 1)
    corregido = (medido - b) / a
    print("== 2) Error sistemático (calibración provisional de 1 punto) ==")
    print(f"  Bias medio: {bias:+.2f} g ({bias / G_POR_MM:+.3f} mm)")
    print(f"  Regresión: medido = {a:.5f} · real + {b:+.2f} g")
    print(f"     offset b = {b:+.2f} g | error de ganancia = {(a - 1) * 100:+.3f} %")
    print(f"  RMSE antes:  {rmse(medido - ref):.2f} g | "
          f"después: {rmse(corregido - ref):.2f} g\n")

    print(f"  {'ref (g)':>9} {'medido':>9} {'corregido':>10} {'error':>8} {'mm':>7}")
    for r, m, c in zip(ref, medido, corregido):
        print(f"  {r:9.1f} {m:9.1f} {c:10.1f} {c - r:+8.2f} {r / G_POR_MM:7.2f}")

    # ---- 3) Potenciómetro: mm de lluvia en función de mV ----
    mm_ref = ref / G_POR_MM
    if np.ptp(pot) > 20:
        k_pot, c_pot = np.polyfit(pot, mm_ref, 1)
        r2 = np.corrcoef(pot, mm_ref)[0, 1] ** 2
        mm_pot = k_pot * pot + c_pot
        print("\n== 3) Potenciómetro (solo vale si calibraste con AGUA) ==")
        print(f"  mm = {k_pot:.5f} · mV + {c_pot:+.3f}   (R² = {r2:.4f})")
        print(f"  RMSE: {rmse(mm_pot - mm_ref):.3f} mm")
    else:
        print("\n== 3) Potenciómetro: casi no varió (¿calibraste con pesas en vez de agua?)")

    try:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 2, figsize=(11, 4))
        ax[0].plot(ref, medido - ref, "o-", label="antes de corregir")
        ax[0].plot(ref, corregido - ref, "s-", label="después de corregir")
        ax[0].axhline(0, color="gray", lw=0.8)
        ax[0].set(xlabel="Masa de referencia (g)", ylabel="Error (g)",
                  title="Error de la celda de carga")
        ax[0].legend()
        ax[1].plot(pot, mm_ref, "o")
        ax[1].set(xlabel="Potenciómetro (mV)", ylabel="Lluvia equivalente (mm)",
                  title="Potenciómetro frente a referencia")
        fig.tight_layout()
        fig.savefig("calibracion.png", dpi=150)
        print("\nGráfica guardada en calibracion.png")
    except ImportError:
        print("\n(Instala matplotlib para generar la gráfica)")


if __name__ == "__main__":
    main()
