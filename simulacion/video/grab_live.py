import sys, time, os, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rec import grabar
from playwright.sync_api import sync_playwright
OUT = sys.argv[1]; os.makedirs(f"{OUT}/dash", exist_ok=True)
R = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CMD = "python simulacion/gemelo_digital.py --publicar --intervalo 1 --montecarlo 0"
fin = {}
def correr():
    fin["rc"] = grabar(CMD, f"{OUT}/live.cast", R, cols=64, filas=40)
    fin["t"] = time.time()
with sync_playwright() as p:
    b = p.firefox.launch(headless=True)
    pg = b.new_page(viewport={"width": 1150, "height": 870})
    pg.goto("https://d2nb5zllocqacr.cloudfront.net/?refresco=2", timeout=60000)
    pg.get_by_text("Sin lecturas en el periodo").wait_for(timeout=30000)
    def snap(): pg.screenshot(path=f"{OUT}/dash/f_{time.time():.3f}.jpg", type="jpeg", quality=92)
    t_fin = time.time() + 4
    while time.time() < t_fin: snap(); time.sleep(0.09)
    th = threading.Thread(target=correr); th.start()
    while "t" not in fin or time.time() < fin["t"] + 14:
        snap(); time.sleep(0.09)
    th.join(); b.close()
print("rc", fin["rc"], "capturas", len(os.listdir(f"{OUT}/dash")))
