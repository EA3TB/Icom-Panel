"""
ic7610_inspect.py — Inspección de icom_lan
===========================================
Conecta a la radio, vuelca todos los métodos/propiedades disponibles
en el objeto IcomRadio y escucha el stream de paquetes entrantes
durante 30 segundos, mostrando todos los tipos de datos recibidos.

Resultado guardado en ic7610_inspect.log

Uso:
    python ic7610_inspect.py
"""

import asyncio
import json
import os
import inspect
import logging
import logging.handlers
from datetime import datetime

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PATH_CONFIG = os.path.join(BASE_DIR, "radio_config.json")
PATH_LOG    = os.path.join(BASE_DIR, "ic7610_inspect.log")


# ---------------------------------------------------------------------------
# Logger que escribe en fichero Y en consola
# ---------------------------------------------------------------------------

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("inspect")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt = logging.Formatter("%(message)s")

    # Fichero — sobreescribe cada ejecución
    fh = logging.FileHandler(PATH_LOG, mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Consola
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Silenciar icom_lan en el logger raíz
    logging.getLogger("icom_lan").setLevel(logging.CRITICAL)
    logging.getLogger().setLevel(logging.CRITICAL)

    return logger


log = setup_logger()


def out(msg: str = ""):
    log.info(msg)

def sep(title: str = ""):
    out()
    out("=" * 60)
    if title:
        out(f"  {title}")
        out("=" * 60)


# ---------------------------------------------------------------------------

def load_config() -> dict:
    defaults = {"ip": "192.168.1.25", "user": "ea3tb", "pass": "ea3aiiea3aii", "civ_addr": 0x98}
    if os.path.exists(PATH_CONFIG):
        try:
            with open(PATH_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            defaults.update(cfg)
        except Exception:
            pass
    return defaults


# ---------------------------------------------------------------------------

async def inspect_radio(cfg: dict):
    from icom_lan import IcomRadio, CONTROLLER_ADDR

    out(f"ic7610_inspect — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out(f"Radio: {cfg['ip']}  usuario: {cfg['user']}  CIV: {hex(cfg['civ_addr'])}")

    # ------------------------------------------------------------------
    sep("1 · Inspeccion estatica de la clase IcomRadio")
    # ------------------------------------------------------------------

    members = [(n, o) for n, o in inspect.getmembers(IcomRadio) if not n.startswith("__")]
    methods = [(n, o) for n, o in members if callable(o)]
    props   = [(n, o) for n, o in members if isinstance(o, property)]
    attrs   = [(n, o) for n, o in members if not callable(o) and not isinstance(o, property)]

    out(f"\n  Metodos ({len(methods)}):")
    for name, obj in sorted(methods):
        try:
            sig = str(inspect.signature(obj))
            doc = (inspect.getdoc(obj) or "").split("\n")[0][:70]
            out(f"    . {name}{sig}")
            if doc:
                out(f"        -> {doc}")
        except Exception:
            out(f"    . {name}")

    out(f"\n  Propiedades ({len(props)}):")
    for name, _ in sorted(props):
        out(f"    . {name}")

    out(f"\n  Atributos de clase ({len(attrs)}):")
    for name, val in sorted(attrs):
        out(f"    . {name} = {repr(val)[:80]}")

    # ------------------------------------------------------------------
    sep("2 · Conexion y atributos de instancia")
    # ------------------------------------------------------------------

    out("  Conectando a la radio...")

    seen_types = {}
    seen_attrs = {}   # attr -> ejemplo de valor

    try:
        async with IcomRadio(
            cfg["ip"],
            username=cfg["user"],
            password=cfg["pass"],
            radio_addr=cfg["civ_addr"]
        ) as radio:

            out("  OK Conectado correctamente.\n")

            # Atributos de la instancia
            inst = {k: v for k, v in vars(radio).items() if not k.startswith("_")}
            out(f"  Atributos publicos de instancia ({len(inst)}):")
            for k, v in sorted(inst.items()):
                out(f"    . {k} = {repr(v)[:80]}")

            # Comprobar iterabilidad async
            is_async_iter = hasattr(radio, "__aiter__")
            out(f"\n  Iterable async (__aiter__)? {'SI' if is_async_iter else 'NO'}")

            # Buscar métodos de lectura
            read_candidates = [
                "read", "recv", "receive", "get_packet", "next_packet",
                "drain", "read_civ", "get_civ", "get_message", "poll",
                "get_frequency", "get_smeter", "get_mode", "get_ptt",
                "subscribe", "on_packet", "packets", "events",
            ]
            found_readers = [n for n in read_candidates if hasattr(radio, n)]
            out(f"\n  Metodos de lectura encontrados: {found_readers if found_readers else 'ninguno'}")

            # ------------------------------------------------------------------
            sep("3 · Escucha de paquetes entrantes (30 segundos)")
            # ------------------------------------------------------------------

            if is_async_iter:
                out("  Escuchando via __aiter__...\n")
                try:
                    async with asyncio.timeout(30):
                        async for packet in radio:
                            ptype = (
                                getattr(packet, "ptype", None)
                                or getattr(packet, "type", None)
                                or type(packet).__name__
                            )
                            seen_types[ptype] = seen_types.get(ptype, 0) + 1

                            # Registrar atributos nuevos con valor de ejemplo
                            if hasattr(packet, "__dict__"):
                                for attr, val in vars(packet).items():
                                    if not attr.startswith("_") and attr not in seen_attrs:
                                        seen_attrs[attr] = repr(val)[:80]
                                        out(f"  [NUEVO] {type(packet).__name__}.{attr} = {repr(val)[:60]}")

                except TimeoutError:
                    out("\n  30 segundos completados.")
                except Exception as e:
                    out(f"  Error durante escucha: {type(e).__name__}: {e}")

            elif found_readers:
                read_fn = getattr(radio, found_readers[0])
                out(f"  Usando radio.{found_readers[0]}() durante 30s...\n")
                end = asyncio.get_event_loop().time() + 30
                while asyncio.get_event_loop().time() < end:
                    try:
                        packet = await read_fn()
                        if packet is None:
                            await asyncio.sleep(0.02)
                            continue
                        ptype = (
                            getattr(packet, "ptype", None)
                            or getattr(packet, "type", None)
                            or type(packet).__name__
                        )
                        seen_types[ptype] = seen_types.get(ptype, 0) + 1
                        if hasattr(packet, "__dict__"):
                            for attr, val in vars(packet).items():
                                if not attr.startswith("_") and attr not in seen_attrs:
                                    seen_attrs[attr] = repr(val)[:80]
                                    out(f"  [NUEVO] {type(packet).__name__}.{attr} = {repr(val)[:60]}")
                    except Exception as e:
                        out(f"  Error leyendo: {type(e).__name__}: {e}")
                        await asyncio.sleep(0.1)
                out("  30 segundos completados.")

            else:
                out("  No se encontro metodo de lectura ni iterador async.")
                out("  Esperando 10s para observar actividad interna...")
                await asyncio.sleep(10)

    except Exception as e:
        out(f"\n  ERROR de conexion: {type(e).__name__}: {e}")
        return

    # ------------------------------------------------------------------
    sep("4 · Resumen de paquetes recibidos")
    # ------------------------------------------------------------------

    if seen_types:
        total = sum(seen_types.values())
        out(f"\n  Total paquetes capturados: {total}\n")
        for ptype, count in sorted(seen_types.items(), key=lambda x: -x[1]):
            out(f"    {str(ptype):<30s}  {count:6d} paquetes")
    else:
        out("  No se capturaron paquetes tipados.")

    if seen_attrs:
        sep("5 · Atributos observados en paquetes")
        out(f"  {'Atributo':<30s}  Ejemplo de valor")
        out(f"  {'-'*30}  {'-'*40}")
        for attr, val in sorted(seen_attrs.items()):
            out(f"  {attr:<30s}  {val}")

    sep()
    out(f"  Log guardado en: {PATH_LOG}")
    out()


if __name__ == "__main__":
    cfg = load_config()
    asyncio.run(inspect_radio(cfg))
