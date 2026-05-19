A la derecha de tu monitor en "Releases" encontarás el ejecutable para descargar 



ICOM - Memory Panel
===================
Control remoto de memorias de voz y CW para transceptores Icom
Windows 11  |  Python 3.11+  |  EA3TB


DESCRIPCIÓN
-----------
Panel gráfico que controla las 8 memorias de voz TX (T1-T8) y envía
texto CW (M1-M8) del transceptor Icom a través de la red LAN/WiFi,
sin necesidad de wfview, RS-BA1 ni ningún software intermediario.


ARCHIVOS
--------
ic7610_voice_panel.py   Script principal
radio_config.json       Configuración de conexión (IP, usuario, contraseña)
labels.json             Etiquetas y textos CW (auto-generado)
icom_voice_memory.ico   Icono de la aplicación

panel.bat               Lanzar el panel sin consola
install.bat             Instalar dependencias Python
build_exe.bat           Compilar a EXE standalone


MODELOS COMPATIBLES
-------------------
  Icom IC-7610   CIV 0x98
  Icom IC-7851   CIV 0x8E
  Icom IC-7800   CIV 0x6A
  Icom IC-7700   CIV 0x74
  Icom IC-9700   CIV 0xA2
  Icom IC-705    CIV 0xA4
  Manual (otro)  CIV configurable

Nota: modelos sin LAN nativo (IC-7300, IC-718...) no son compatibles.


INICIO RÁPIDO
-------------
1. Doble clic en install.bat  (solo la primera vez)
2. Doble clic en panel.bat
3. En el primer arranque se abre automáticamente la ventana de
   configuración — introduce IP, usuario y contraseña de la radio
4. Pulsar Guardar y conectar


CONFIGURACIÓN (radio_config.json)
----------------------------------
{
  "model":    "Icom IC-7610",
  "ip":       "192.168.1.25",   <- IP del transceptor en tu red
  "user":     "**",          <- Usuario configurado en la radio
  "pass":     "**",   <- Contraseña de la radio
  "civ_addr": 152               <- Dirección CIV (no cambiar para IC-7610)
}

Para encontrar la IP en la radio:
  MENU > SET > Network > WLAN/LAN > IP Address

Para verificar usuario/contraseña:
  MENU > SET > Network > Remote Control Settings


MODO VOICE (USB / LSB)
-----------------------
Controla las 8 memorias de voz TX de la radio (T1-T8).

- Al conectar, el panel lee el modo actual de la radio y se sincroniza
- Al pulsar VOICE, la radio cambia automáticamente a USB o LSB según
  la frecuencia activa:
    < 10 MHz  →  LSB
    >= 10 MHz →  USB
- Pulsar una tarjeta lanza la memoria de voz correspondiente
- La tarjeta activa se ilumina en rojo mientras transmite
- Pulsar STOP interrumpe la transmisión
- Las memorias de voz deben estar grabadas en la radio:
    Pulsar VOICE en el panel frontal → mantener T1...T8 → hablar → soltar

Teclas rápidas:
  F1-F8  o  1-8 (teclado numérico)  →  Play/Stop memorias T1-T8


MODO CW
--------
Envía texto CW directamente desde el PC via CI-V (comando 0x17).
No usa las memorias internas del Keyer del IC-7610 (no accesibles
por CI-V), sino textos configurados en el propio panel.

- Al pulsar CW, la radio cambia automáticamente a modo CW
- Cada tarjeta muestra el texto CW configurado
- Al pulsar SEND:
    1. PTT ON
    2. Envía el texto CW a la radio
    3. PTT OFF automático al terminar
- Pulsar STOP interrumpe la transmisión inmediatamente

Textos CW por defecto:
  M1  CQ DX DE EA*XXX
  M2  599 599
  M3  QSL TU 73
  M4  EA*XXX EA*XXX
  M5  CQ TEST DE EA*XXX
  M6  NR
  M7  73 DE EA*XXX SK
  M8  QRZ?

Editar textos CW:
  Doble clic sobre la tarjeta en modo CW → escribir → Enter para guardar
  Los textos se guardan en labels.json y persisten entre sesiones.
  Sustituye EA*XXX por tu indicativo.

Nota sobre el sidetone:
  El IC-7610 genera sidetone CW durante la transmisión de forma fija.
  Es el comportamiento normal del equipo, no un bug del panel.
  Para reducirlo, baja el volumen AF del equipo mientras usas CW.

Teclas rápidas:
  F1-F8  o  1-8 (teclado numérico)  →  Send/Stop memorias M1-M8


ETIQUETAS
---------
Doble clic sobre cualquier tarjeta (en modo VOICE) para editar
su nombre. Se guarda automáticamente en labels.json.


COMPILAR A EXE
--------------
Para distribuir sin necesitar Python instalado:
  1. Ejecutar install.bat primero
  2. Ejecutar build_exe.bat
  3. El ejecutable aparece en dist\ICOM - Memory Panel.exe

Junto al .exe deben estar siempre:
  radio_config.json
  labels.json  (opcional, se crea en el primer arranque)

En el primer uso en un PC nuevo, Windows Defender puede mostrar
una advertencia — pulsar "Más información → Ejecutar de todas formas".
Es normal en ejecutables sin firma digital.


ERRORES COMUNES
---------------
civ_port=0
  Otra app (wfview, RS-BA1) tiene la sesión abierta.
  Cerrar esa app y esperar 15 segundos.

NAK / sin respuesta en VOICE
  Radio en modo DATA (USB-D, LSB-D) — cambiar a USB/LSB normal.
  O la memoria de voz está vacía — grabarla en la radio.

Error de conexión / reintentando
  Radio apagada, IP incorrecta o firewall bloqueando UDP 50001-50003.

Abrir puertos en el Firewall de Windows (si es necesario):
  Ejecutar PowerShell como Administrador:
  New-NetFirewallRule -DisplayName "ICOM Panel" `
    -Direction Outbound -Protocol UDP `
    -RemotePort 50001-50003 -Action Allow


DEPENDENCIAS
------------
  icom-lan >= 0.13.0     Protocolo UDP Icom (requiere Python 3.11+)
  customtkinter >= 5.2.2 Interfaz gráfica
  pynput                 Teclas rápidas globales


PROTOCOLO CI-V IMPLEMENTADO
-----------------------------
  0x06        Cambio de modo (USB/LSB/CW)
  0x17        Envío de texto CW directo
  0x1C 0x00   PTT ON/OFF
  0x28 0x00   Voice TX Memory play/stop
  Discovery + autenticación UDP Icom LAN (puerto 50001)
  CI-V sobre UDP (puerto 50002)


---
EA3TB  ·  Caldes de Montbui  ·  2026
