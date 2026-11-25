"""Graba el proyecto publico de Wokwi con capturas periodicas (marca de tiempo en el nombre)."""
import sys, time, os, json
from playwright.sync_api import sync_playwright
OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
URL = "https://wokwi.com/projects/481702637981326337"
eventos = []

class G:
    def __init__(s, pg): s.pg = pg; s.n = 0
    def snap(s):
        t = time.time()
        s.pg.screenshot(path=f"{OUT}/f_{t:.3f}.jpg", type="jpeg", quality=92)
        s.n += 1
    def esperar(s, seg):
        fin = time.time() + seg
        while time.time() < fin: s.snap()
    def esperar_texto(s, txt, maximo=90, extra=0):
        fin = time.time() + maximo
        while time.time() < fin:
            s.snap()
            if txt in s.pg.locator("body").inner_text(): break
        s.esperar(extra)
    def marca(s, nombre): eventos.append({"t": time.time(), "evento": nombre}); print(nombre, flush=True)
    def arrastrar(s, x0, y0, x1, y1, pasos=20):
        s.pg.mouse.move(x0, y0); s.pg.mouse.down()
        for i in range(1, pasos + 1):
            s.pg.mouse.move(x0 + (x1 - x0) * i / pasos, y0 + (y1 - y0) * i / pasos); s.snap()
        s.pg.mouse.up()
    def escribir(s, texto):
        s.pg.mouse.click(SERIAL_X, 1062)
        for ch in texto: s.pg.keyboard.type(ch); s.snap()
        s.snap(); s.pg.keyboard.press("Enter")

SERIAL_X = 1365
with sync_playwright() as p:
    b = p.firefox.launch(headless=True)
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto(URL, wait_until="domcontentloaded", timeout=90000)
    pg.get_by_label("Start the simulation").wait_for(timeout=60000); time.sleep(4)
    g = G(pg)
    g.marca("inicio_codigo"); g.esperar(7)
    g.marca("divisor")
    g.arrastrar(960, 600, 520, 600, pasos=15); g.esperar(3)
    box = pg.get_by_label("Start the simulation").bounding_box()
    g.marca("circuito"); g.esperar(7)
    g.marca("play"); pg.get_by_label("Start the simulation").click()
    g.esperar_texto("CAL,ref_g", extra=4)
    g.marca("menu"); g.esperar(4)
    SERIAL_X = 1200
    g.marca("cmd_t"); g.escribir("t")
    g.esperar_texto("Tara", maximo=25, extra=3)
    g.marca("cmd_s"); g.escribir("s"); g.esperar(5)
    # celda: buscar el componente de la celda de carga
    cel = pg.locator("wokwi-load-cell, wokwi-hx711").first.bounding_box()
    print("celda", cel, flush=True)
    g.marca("celda_click"); pg.mouse.click(cel["x"] + cel["width"] * 0.9, cel["y"] + cel["height"] * 0.5); g.esperar(1.5)
    rng = pg.locator("input[type=range][max='5']").first.bounding_box()
    print("rango", rng, flush=True)
    x0 = rng["x"] + 8; y = rng["y"] + rng["height"] / 2
    g.marca("peso_1kg"); g.arrastrar(x0, y, x0 + (rng["width"] - 16) * 0.2, y, pasos=15); g.esperar(8)
    pot = pg.locator("wokwi-slide-potentiometer").first.bounding_box()
    print("pot", pot, flush=True)
    py = pot["y"] + pot["height"] * 0.5
    kx = pot["x"] + pot["width"] * 0.2
    g.marca("pot_mover"); g.arrastrar(kx, py, kx + pot["width"] * 0.35, py, pasos=15); g.esperar(8)
    g.marca("peso_2kg"); pg.mouse.click(cel["x"] + cel["width"] * 0.9, cel["y"] + cel["height"] * 0.5); g.esperar(1)
    rng = pg.locator("input[type=range][max='5']").first.bounding_box()
    xa = rng["x"] + 8 + (rng["width"] - 16) * 0.2
    g.arrastrar(xa, y, xa + (rng["width"] - 16) * 0.2, y, pasos=15); g.esperar(7)
    g.marca("fin")
    json.dump(eventos, open(f"{OUT}/eventos.json", "w"), indent=1)
    print("capturas", g.n)
    b.close()
