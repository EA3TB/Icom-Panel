"""
ic7610_diag.py — Diagnóstico de conectividad IC-7610
=====================================================
Comprueba:
  1. Alcanzabilidad de red (ping ICMP)
  2. Puerto UDP 50001 (protocolo Icom LAN)
  3. Puerto TCP 50001 (RemoteUtility / RS-BA1)
  4. Sesiones UDP activas hacia la radio (netstat)
  5. Procesos locales que usan ese puerto
  6. Intento de autenticación con credenciales de radio_config.json
     — distingue "credenciales incorrectas" de "conexión ocupada"

Uso:
    python ic7610_diag.py
    python ic7610_diag.py --ip 192.168.1.25
"""

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import platform
import socket
import struct
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PATH_CONFIG = os.path.join(BASE_DIR, "radio_config.json")
PATH_LOG    = os.path.join(BASE_DIR, "ic7610_diag.log")

ICOM_UDP_PORT = 50001
ICOM_TCP_PORT = 50001
TIMEOUT       = 3.0   # segundos

# Códigos de error conocidos del protocolo Icom LAN
ICOM_ERRORS = {
    0xFEFFFFFF: "Authentication failed — usuario/contraseña incorrectos",
    0xFBFFFFFF: "Connection busy — otra sesión activa",
    0xFDFFFFFF: "Connection refused — radio no acepta más conexiones",
}

# ---------------------------------------------------------------------------
# Colores ANSI (desactivados en Windows sin soporte)
# ---------------------------------------------------------------------------
_USE_COLOR = sys.stdout.isatty() and platform.system() != "Windows"

def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text

OK   = lambda t: _c(t, "32")   # verde
WARN = lambda t: _c(t, "33")   # amarillo
ERR  = lambda t: _c(t, "31")   # rojo
INFO = lambda t: _c(t, "36")   # cian
BOLD = lambda t: _c(t, "1")    # negrita


# ---------------------------------------------------------------------------
# Logging a fichero (sin colores ANSI)
# ---------------------------------------------------------------------------

def _setup_logging():
    handler = logging.handlers.RotatingFileHandler(
        PATH_LOG, maxBytes=500_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def _log_print(level: str, plain_text: str):
    """Escribe en consola (con color) y en el fichero de log (sin color)."""
    if level == "ok":
        logging.info(plain_text)
    elif level == "warn":
        logging.warning(plain_text)
    elif level == "err":
        logging.error(plain_text)
    else:
        logging.info(plain_text)


def section(title):
    print(f"\n{BOLD('─' * 55)}")
    print(BOLD(f"  {title}"))
    print(BOLD('─' * 55))


# ---------------------------------------------------------------------------
# 1. Ping ICMP
# ---------------------------------------------------------------------------

def check_ping(ip: str) -> bool:
    section("1 · Alcanzabilidad de red (ping)")
    param = "-n" if platform.system() == "Windows" else "-c"
    try:
        result = subprocess.run(
            ["ping", param, "3", ip],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            # Extraer tiempo medio si está disponible
            for line in result.stdout.splitlines():
                if "ms" in line.lower() and ("avg" in line.lower() or "media" in line.lower() or "promedio" in line.lower()):
                    print(OK(f"  ✔ {ip} responde al ping"))
                    print(f"    {line.strip()}")
                    _log_print("ok", f"PING OK: {ip} — {line.strip()}")
                    return True
            print(OK(f"  ✔ {ip} responde al ping"))
            _log_print("ok", f"PING OK: {ip}")
            return True
        else:
            print(ERR(f"  ✘ {ip} no responde al ping"))
            print(WARN("    ¿Está encendida la radio? ¿IP correcta?"))
            _log_print("err", f"PING FAIL: {ip} no responde")
            return False
    except subprocess.TimeoutExpired:
        print(ERR(f"  ✘ Timeout al hacer ping a {ip}"))
        _log_print("err", f"PING TIMEOUT: {ip}")
        return False
    except FileNotFoundError:
        print(WARN("  ⚠ Comando ping no disponible"))
        _log_print("warn", "Comando ping no disponible")
        return False


# ---------------------------------------------------------------------------
# 2. Puerto UDP 50001 — sondeo básico
# ---------------------------------------------------------------------------

def check_udp_port(ip: str) -> bool:
    section("2 · Puerto UDP 50001")
    # Enviamos un paquete mínimo "Are You There" del protocolo Icom LAN
    # y esperamos cualquier respuesta (indica que el puerto está activo)
    ARE_YOU_THERE = bytes([
        0x10, 0x00, 0x00, 0x00,  # longitud = 16
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
    ])
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)
    try:
        sock.sendto(ARE_YOU_THERE, (ip, ICOM_UDP_PORT))
        data, addr = sock.recvfrom(1024)
        print(OK(f"  ✔ Puerto UDP {ICOM_UDP_PORT} activo — respuesta recibida ({len(data)} bytes)"))
        _log_print("ok", f"UDP {ICOM_UDP_PORT} activo — respuesta recibida ({len(data)} bytes)")
        return True
    except socket.timeout:
        print(WARN(f"  ⚠ Puerto UDP {ICOM_UDP_PORT} no respondió en {TIMEOUT}s"))
        print(WARN("    Puede ser normal si la radio filtra sondeos sin handshake completo"))
        _log_print("warn", f"UDP {ICOM_UDP_PORT} no respondió en {TIMEOUT}s")
        return False
    except OSError as e:
        print(ERR(f"  ✘ Error UDP: {e}"))
        _log_print("err", f"UDP error: {e}")
        return False
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 3. Puerto TCP 50001 — RS-BA1 / RemoteUtility
# ---------------------------------------------------------------------------

def check_tcp_port(ip: str) -> bool:
    section("3 · Puerto TCP 50001 (RS-BA1 / RemoteUtility)")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    try:
        result = sock.connect_ex((ip, ICOM_TCP_PORT))
        if result == 0:
            print(OK(f"  ✔ Puerto TCP {ICOM_TCP_PORT} abierto"))
            _log_print("ok", f"TCP {ICOM_TCP_PORT} abierto")
            return True
        else:
            print(WARN(f"  ⚠ Puerto TCP {ICOM_TCP_PORT} cerrado o filtrado (código {result})"))
            _log_print("warn", f"TCP {ICOM_TCP_PORT} cerrado o filtrado (código {result})")
            return False
    except OSError as e:
        print(ERR(f"  ✘ Error TCP: {e}"))
        _log_print("err", f"TCP error: {e}")
        return False
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 4. Sesiones activas desde este PC (netstat)
# ---------------------------------------------------------------------------

def check_local_sessions(ip: str):
    section("4 · Sesiones activas desde este equipo")
    try:
        if platform.system() == "Windows":
            cmd = ["netstat", "-ano"]
        else:
            cmd = ["ss", "-unp"]   # UDP + procesos

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        lines = [l for l in result.stdout.splitlines() if ip in l and "50001" in l]

        if lines:
            print(WARN(f"  ⚠ Conexiones locales hacia {ip}:50001 encontradas:"))
            for line in lines:
                print(f"    {line.strip()}")
                _log_print("warn", f"Sesión activa: {line.strip()}")
        else:
            print(OK(f"  ✔ No hay sesiones locales activas hacia {ip}:50001"))
            _log_print("ok", f"Sin sesiones locales activas hacia {ip}:50001")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(WARN(f"  ⚠ No se pudo ejecutar netstat/ss: {e}"))
        _log_print("warn", f"netstat/ss no disponible: {e}")


# ---------------------------------------------------------------------------
# 5. Procesos locales usando el puerto (lsof / netstat -b)
# ---------------------------------------------------------------------------

def check_local_processes():
    section("5 · Procesos locales usando puerto 50001")
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=10
            )
            lines = [l for l in result.stdout.splitlines() if "50001" in l]
            pids = set()
            for line in lines:
                parts = line.split()
                if parts:
                    try:
                        pids.add(int(parts[-1]))
                    except ValueError:
                        pass
            if pids:
                print(WARN(f"  ⚠ PIDs usando puerto 50001: {pids}"))
                _log_print("warn", f"PIDs usando puerto 50001: {pids}")
                for pid in pids:
                    try:
                        r2 = subprocess.run(
                            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True, timeout=5
                        )
                        print(f"    PID {pid}: {r2.stdout.strip()}")
                        _log_print("warn", f"PID {pid}: {r2.stdout.strip()}")
                    except Exception:
                        print(f"    PID {pid}: (no se pudo obtener nombre)")
                        _log_print("warn", f"PID {pid}: (no se pudo obtener nombre)")
            else:
                print(OK("  ✔ Ningún proceso local usa el puerto 50001"))
                _log_print("ok", "Ningún proceso local usa el puerto 50001")

        else:
            result = subprocess.run(
                ["lsof", "-i", f"UDP:{ICOM_UDP_PORT}"],
                capture_output=True, text=True, timeout=10
            )
            if result.stdout.strip():
                print(WARN("  ⚠ Procesos usando UDP 50001:"))
                for line in result.stdout.splitlines():
                    print(f"    {line}")
                    _log_print("warn", f"Proceso UDP 50001: {line.strip()}")
            else:
                print(OK("  ✔ Ningún proceso local usa UDP 50001"))
                _log_print("ok", "Ningún proceso local usa UDP 50001")

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(WARN(f"  ⚠ No se pudo listar procesos: {e}"))
        _log_print("warn", f"No se pudo listar procesos: {e}")


# ---------------------------------------------------------------------------
# 6. Intento de autenticación real (usa icom_lan si está disponible)
# ---------------------------------------------------------------------------

async def _try_auth(cfg: dict) -> str:
    """
    Intenta conectar con icom_lan y devuelve un string con el resultado.
    Distingue entre credenciales incorrectas y conexión ocupada.
    """
    try:
        from icom_lan import IcomRadio
    except ImportError:
        return "icom_lan no instalado — omitiendo prueba de autenticación"

    try:
        async with IcomRadio(
            cfg["ip"],
            username=cfg["user"],
            password=cfg["pass"],
            radio_addr=cfg.get("civ_addr", 0x98)
        ) as radio:
            return "OK"
    except Exception as e:
        msg = str(e)
        # Intentar identificar el código de error numérico
        for code, description in ICOM_ERRORS.items():
            if hex(code) in msg.lower() or str(code) in msg:
                return f"ERROR {hex(code)}: {description}"
        return f"ERROR: {msg}"


def check_auth(cfg: dict):
    section("6 · Prueba de autenticación")
    print(f"  IP      : {cfg['ip']}")
    print(f"  Usuario : {cfg['user']}")
    print(f"  CIV     : {hex(cfg.get('civ_addr', 0x98))}")
    print()

    result = asyncio.run(_try_auth(cfg))

    if result == "OK":
        print(OK("  ✔ Autenticación correcta — conexión establecida"))
        _log_print("ok", f"AUTH OK: {cfg['ip']} usuario={cfg['user']}")
    elif "icom_lan no instalado" in result:
        print(WARN(f"  ⚠ {result}"))
        _log_print("warn", result)
    elif "Authentication failed" in result:
        print(ERR(f"  ✘ {result}"))
        print(WARN("    → Verifica usuario y contraseña en radio_config.json"))
        print(WARN("    → En la radio: MENU > SET > Network > Remote Settings"))
        _log_print("err", f"AUTH FAIL (credenciales): {cfg['ip']} usuario={cfg['user']}")
    elif "busy" in result.lower() or "0xfbffffff" in result.lower():
        print(ERR(f"  ✘ {result}"))
        print(WARN("    → Otra aplicación (RS-BA1, WFVIEW, otro panel) tiene la sesión abierta"))
        print(WARN("    → Cierra esa aplicación o espera a que libere la conexión"))
        _log_print("err", f"AUTH FAIL (conexión ocupada): {cfg['ip']}")
    else:
        print(ERR(f"  ✘ {result}"))
        _log_print("err", f"AUTH FAIL (desconocido): {result}")


# ---------------------------------------------------------------------------
# Carga de configuración
# ---------------------------------------------------------------------------

def load_config(ip_override: str | None) -> dict:
    defaults = {"ip": "192.168.1.25", "user": "", "pass": "", "civ_addr": 0x98}
    if os.path.exists(PATH_CONFIG):
        try:
            with open(PATH_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            defaults.update(cfg)
        except (json.JSONDecodeError, IOError) as e:
            print(WARN(f"  ⚠ No se pudo leer radio_config.json: {e}"))
    if ip_override:
        defaults["ip"] = ip_override
    return defaults


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Diagnóstico de conectividad IC-7610")
    parser.add_argument("--ip", help="IP de la radio (sobreescribe radio_config.json)")
    args = parser.parse_args()

    _setup_logging()

    cfg = load_config(args.ip)
    ip  = cfg["ip"]

    logging.info(f"{'=' * 50}")
    logging.info(f"Inicio diagnóstico — Radio: {ip}:{ICOM_UDP_PORT}")
    logging.info(f"{'=' * 50}")

    print(BOLD(f"\n{'═' * 55}"))
    print(BOLD(f"  IC-7610 · Diagnóstico de conectividad"))
    print(BOLD(f"  Radio: {ip}:{ICOM_UDP_PORT}"))
    print(BOLD(f"  Log  : {PATH_LOG}"))
    print(BOLD(f"{'═' * 55}"))

    reachable = check_ping(ip)
    if not reachable:
        print(ERR("\n  La radio no responde al ping. Comprueba red y alimentación."))
        print(ERR("  El resto de pruebas pueden fallar.\n"))

    check_udp_port(ip)
    check_tcp_port(ip)
    check_local_sessions(ip)
    check_local_processes()
    check_auth(cfg)

    logging.info("Diagnóstico finalizado.")
    print(f"\n{BOLD('═' * 55)}")
    print(BOLD(f"  Log guardado en: {PATH_LOG}"))
    print(BOLD('═' * 55) + "\n")


if __name__ == "__main__":
    main()
