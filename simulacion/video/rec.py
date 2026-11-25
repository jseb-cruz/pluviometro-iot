"""Graba la salida de un comando en un pty con marcas de tiempo (formato tipo asciicast v2)."""
import os, pty, sys, time, json, subprocess, fcntl, termios, struct, select

def grabar(comando, salida, cwd, env_extra=None, cols=100, filas=40, mostrar=None):
    env = dict(os.environ, PYTHONUNBUFFERED="1", COLUMNS=str(cols), LINES=str(filas), TERM="dumb")
    if env_extra: env.update(env_extra)
    m, s = pty.openpty()
    fcntl.ioctl(s, termios.TIOCSWINSZ, struct.pack("HHHH", filas, cols, 0, 0))
    t0 = time.time()
    pr = subprocess.Popen(["bash", "-c", comando], stdin=s, stdout=s, stderr=s, cwd=cwd, env=env, close_fds=True)
    os.close(s)
    eventos = []
    while True:
        r, _, _ = select.select([m], [], [], 0.2)
        if r:
            try: d = os.read(m, 65536)
            except OSError: d = b""
            if not d: break
            eventos.append([round(time.time() - t0, 4), d.decode("utf-8", "replace")])
        elif pr.poll() is not None:
            break
    pr.wait()
    with open(salida, "w") as f:
        f.write(json.dumps({"version": 2, "width": cols, "height": filas, "timestamp": t0,
                            "command": mostrar or comando, "exit": pr.returncode}) + "\n")
        for e in eventos: f.write(json.dumps([e[0], "o", e[1]]) + "\n")
    return pr.returncode

if __name__ == "__main__":
    # rec.py salida.cast cwd "comando" ["comando mostrado"]
    rc = grabar(sys.argv[3], sys.argv[1], sys.argv[2], mostrar=sys.argv[4] if len(sys.argv) > 4 else None)
    print("exit", rc)
