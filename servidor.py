"""Bot de WhatsApp con IA: webhook de WhatsApp Cloud API (Meta) -> Claude (Anthropic) -> respuesta por la Cloud API.

Arranque (desde la carpeta del proyecto, con el .env lleno):
    .venv/bin/python -m uvicorn servidor:crear_app --factory --host 127.0.0.1 --port 8000 --no-access-log

Rutas:
    GET  /webhook  verificación de Meta (hub.verify_token == META_VERIFY_TOKEN -> devuelve hub.challenge)
    POST /webhook  avisos de mensajes (firma X-Hub-Signature-256 con META_APP_SECRET; 200 inmediato)
    GET  /prompt   el system prompt en HTML, para revisarlo en el navegador
    GET  /salud    comprobación rápida de que el servidor está arriba

Privacidad: ni los logs ni registro.jsonl llevan teléfonos, wa_id, ids de mensaje, tokens ni el texto del
cliente. El remitente se identifica con un hash corto del wa_id.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import anthropic
import httpx
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

DIR_PROYECTO = Path(__file__).resolve().parent
RUTA_ENV = DIR_PROYECTO / ".env"
RUTA_REGISTRO = DIR_PROYECTO / "registro.jsonl"

# Versión de Graph API por defecto; se puede cambiar con META_GRAPH_VERSION en .env.
GRAPH_VERSION_DEFECTO = "v23.0"
GRAPH_URL = "https://graph.facebook.com/{version}/{phone_number_id}/messages"
TIMEOUT_META_S = 15.0
MAX_TOKENS = 1024
MAX_IDS_RECORDADOS = 2000  # ids de mensaje recordados para descartar reintentos de Meta

VARIABLES_REQUERIDAS = (
    "ANTHROPIC_API_KEY",
    "CLAUDE_MODEL",
    "META_ACCESS_TOKEN",
    "META_PHONE_NUMBER_ID",
    "META_APP_SECRET",
    "META_VERIFY_TOKEN",
)

# Negocio de demostración FICTICIO. Cámbialo por los datos de tu negocio y reinicia el servidor.
NEGOCIO_DEMO = {
    "nombre": "Taller Demo",
    "giro": "taller mecánico de autos",
    "servicios": ["afinación de motor", "cambio de aceite y filtros", "revisión y cambio de frenos"],
    "horario": "lunes a viernes de 9:00 a 18:00 y sábados de 9:00 a 14:00",
}

SYSTEM_PROMPT = (
    f"Eres el asistente de atención a clientes por WhatsApp de {NEGOCIO_DEMO['nombre']}, un "
    f"{NEGOCIO_DEMO['giro']}. Atiendes con amabilidad, en español neutro, y respondes de forma breve: "
    "como máximo 4 o 5 líneas, sin listas largas ni formato Markdown.\n"
    "Información del negocio (es TODA la información que tienes; úsala tal cual):\n"
    f"- Servicios: {'; '.join(NEGOCIO_DEMO['servicios'])}.\n"
    f"- Horario de atención: {NEGOCIO_DEMO['horario']}.\n"
    "Reglas obligatorias:\n"
    "- Responde SOLO con la información de arriba. Si preguntan algo que no está ahí (precios, citas, dirección, "
    "otros servicios, promociones), di que un asesor lo confirma por este mismo chat. No inventes nada.\n"
    "- No saludes según la hora del día (nada de «buenos días», «buenas tardes» ni «buenas noches»); "
    "un «¡Hola!» está bien.\n"
    "- NUNCA incluyas números de teléfono, de WhatsApp ni de ningún tipo de contacto en tus respuestas. "
    "Si te piden un teléfono, di que pueden seguir la conversación por este mismo chat.\n"
    "- No uses emoji ni emoticones en tus respuestas; escribe solo texto."
)
TEXTO_REFUSAL = "Disculpa, no puedo ayudarte con eso. ¿Te puedo apoyar con informes de nuestros servicios o el horario?"
TEXTO_OMITIDO = "[dato omitido]"

# Teléfono = un dígito seguido de 9 o más dígitos/espacios/guiones/paréntesis/puntos (más un "(" opcional al inicio, para
# no dejarlo suelto al sustituir). Antes se protegen fechas y horas para que, p. ej., 2026-11-05 no se tome por teléfono.
PATRON_TELEFONO = re.compile(r"\(?\+?\d[\d\s().-]{9,}")
PATRONES_FECHA = (
    re.compile(r"(?<![\d+])(?:19|20)\d{2}([-/.])(?:0?[1-9]|1[0-2])\1(?:0?[1-9]|[12]\d|3[01])(?![-/.]?\d)"),
    re.compile(r"(?<![\d+])(?:0?[1-9]|[12]\d|3[01])([-/.])(?:0?[1-9]|[12]\d|3[01])\1(?:19|20)\d{2}(?![-/.]?\d)"),
    re.compile(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?!\d)"),
)
_MARCA_BASE = 0xE000  # caracteres de uso privado: no son dígitos ni espacios, así que cortan el patrón

log = logging.getLogger("flujo.servidor")


class ErrorConfig(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    modelo: str
    meta_token: str
    phone_number_id: str
    app_secret: str
    verify_token: str
    graph_version: str


def cargar_config(entorno: dict[str, str] | None = None) -> Config:
    """Lee la configuración de .env (junto a este archivo) + entorno. Falla con los NOMBRES que faltan, nunca valores."""
    if entorno is None:
        from dotenv import load_dotenv

        load_dotenv(RUTA_ENV)
        entorno = dict(os.environ)
    faltan = [n for n in VARIABLES_REQUERIDAS if not (entorno.get(n) or "").strip()]
    if faltan:
        raise ErrorConfig("faltan variables en .env: " + ", ".join(faltan))
    return Config(
        modelo=entorno["CLAUDE_MODEL"].strip(),
        meta_token=entorno["META_ACCESS_TOKEN"].strip(),
        phone_number_id=entorno["META_PHONE_NUMBER_ID"].strip(),
        app_secret=entorno["META_APP_SECRET"].strip(),
        verify_token=entorno["META_VERIFY_TOKEN"].strip(),
        graph_version=(entorno.get("META_GRAPH_VERSION") or GRAPH_VERSION_DEFECTO).strip(),
    )


# --- utilidades puras ------------------------------------------------------------------------
def firma_valida(cuerpo: bytes, cabecera: str | None, secreto: str) -> bool:
    """X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256(cuerpo crudo, app secret). Comparación en tiempo constante."""
    if not cabecera or not cabecera.startswith("sha256="):
        return False
    esperado = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecera.removeprefix("sha256="))


def filtrar_telefonos(texto: str) -> str:
    """Sustituye lo que parezca teléfono por TEXTO_OMITIDO sin tocar fechas ni horas."""
    protegidos: list[str] = []

    def proteger(m: re.Match) -> str:
        protegidos.append(m.group(0))
        return chr(_MARCA_BASE + len(protegidos) - 1)

    for patron in PATRONES_FECHA:
        texto = patron.sub(proteger, texto)

    def omitir(m: re.Match) -> str:
        bruto = m.group(0)
        sin_cola = bruto.rstrip(" \t\r\n-.(")
        return TEXTO_OMITIDO + bruto[len(sin_cola):]  # conserva el espacio o salto de línea final

    texto = PATRON_TELEFONO.sub(omitir, texto)
    for i, original in enumerate(protegidos):
        texto = texto.replace(chr(_MARCA_BASE + i), original)
    return texto


def normalizar_destinatario(wa_id: str) -> str:
    """México: el webhook entrega el remitente como 521 + 10 dígitos (prefijo móvil antiguo), pero la lista de
    destinatarios permitidos y el envío esperan 52 + 10 dígitos; responder al 521… da el error 131030
    («Recipient phone number not in allowed list»). Verificado en el ensayo del 2026-11-06. Otros países no cambian."""
    if wa_id.startswith("521") and len(wa_id) == 13 and wa_id.isdigit():
        return "52" + wa_id[3:]
    return wa_id


def hash_corto(wa_id: str) -> str:
    return hashlib.sha256(wa_id.encode()).hexdigest()[:10]


def _de_otro_numero(valor: dict, phone_number_id: str | None) -> bool:
    """El aviso es de OTRO número (o no dice de cuál): value.metadata.phone_number_id distinto del configurado."""
    if phone_number_id is None:
        return False
    return str(((valor or {}).get("metadata") or {}).get("phone_number_id") or "") != phone_number_id


def extraer_mensajes(payload: Any, phone_number_id: str | None = None) -> list[dict[str, str]]:
    """Mensajes de texto entrantes: entry[].changes[] con field 'messages' -> value.messages[] tipo 'text'.
    Ignora statuses y cualquier otro tipo de mensaje. Con `phone_number_id`, ignora también los avisos de otro número
    o sin metadata (la app puede estar suscrita a cuentas que no son la de este bot)."""
    salida: list[dict[str, str]] = []
    if not isinstance(payload, dict):
        return salida
    for entry in payload.get("entry") or []:
        for cambio in (entry or {}).get("changes") or []:
            if (cambio or {}).get("field") != "messages":
                continue
            if _de_otro_numero(cambio.get("value") or {}, phone_number_id):
                continue
            for msg in (cambio.get("value") or {}).get("messages") or []:
                if not isinstance(msg, dict) or msg.get("type") != "text":
                    continue
                cuerpo = ((msg.get("text") or {}).get("body") or "").strip()
                if msg.get("id") and msg.get("from") and cuerpo:
                    salida.append({"id": str(msg["id"]), "wa_id": str(msg["from"]), "texto": cuerpo})
    return salida


def contar_ajenos(payload: Any, phone_number_id: str) -> int:
    """Cuántos mensajes de texto llegaron de OTRO número (o sin metadata): solo el conteo, nunca el número ni el texto."""
    return len(extraer_mensajes(payload)) - len(extraer_mensajes(payload, phone_number_id))


def _iso(t: datetime | None) -> str | None:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z") if t else None


def _segundos(a: datetime | None, b: datetime | None) -> float | None:
    return round((b - a).total_seconds(), 3) if a and b else None


class Deduplicador:
    """Recuerda los últimos ids de mensaje (Meta reintenta el mismo webhook). Seguro entre hilos."""

    def __init__(self, maximo: int = MAX_IDS_RECORDADOS):
        self._ids: OrderedDict[str, None] = OrderedDict()
        self._maximo = maximo
        self._lock = threading.Lock()

    def es_nuevo(self, msg_id: str) -> bool:
        with self._lock:
            if msg_id in self._ids:
                return False
            self._ids[msg_id] = None
            if len(self._ids) > self._maximo:
                self._ids.popitem(last=False)
            return True


# --- aplicación ------------------------------------------------------------------------------
class Bot:
    def __init__(self, config: Config, claude: Any, http: httpx.Client, ruta_registro: Path,
                 reloj: Callable[[], datetime]):
        self.config, self.claude, self.http = config, claude, http
        self.ruta_registro, self.reloj = ruta_registro, reloj
        self._lock_registro = threading.Lock()

    def responder_con_claude(self, texto: str) -> tuple[str, str, str]:
        """Devuelve (respuesta, stop_reason, modelo). Lanza los errores del SDK."""
        resp = self.claude.beta.messages.create(
            model=self.config.modelo,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": texto}],
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        stop = str(resp.stop_reason)
        modelo = str(getattr(resp, "model", None) or self.config.modelo)
        if stop == "refusal":
            return TEXTO_REFUSAL, stop, modelo
        partes = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        respuesta = "\n".join(p.strip() for p in partes if p and p.strip())
        if not respuesta:
            raise RuntimeError(f"Claude no devolvió texto (stop_reason={stop})")
        return filtrar_telefonos(respuesta), stop, modelo

    def enviar_whatsapp(self, wa_id: str, texto: str) -> None:
        url = GRAPH_URL.format(version=self.config.graph_version, phone_number_id=self.config.phone_number_id)
        cuerpo = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalizar_destinatario(wa_id),
            "type": "text",
            "text": {"body": texto},
        }
        r = self.http.post(url, json=cuerpo, headers={"Authorization": f"Bearer {self.config.meta_token}"},
                           timeout=TIMEOUT_META_S)
        if not 200 <= r.status_code < 300:
            raise ErrorMeta(r.status_code, _resumen_error_meta(r))

    def procesar(self, msg: dict[str, str], t_recibido: datetime) -> dict[str, Any]:
        """Claude -> Cloud API. Escribe una línea en registro.jsonl y la devuelve."""
        fila: dict[str, Any] = {"remitente": hash_corto(msg["wa_id"]), "modelo": self.config.modelo,
                                "stop_reason": None, "resultado": None}
        t_claude = t_meta = None
        try:
            respuesta, fila["stop_reason"], fila["modelo"] = self.responder_con_claude(msg["texto"])
            t_claude = self.reloj()
            self.enviar_whatsapp(msg["wa_id"], respuesta)
            t_meta = self.reloj()
            fila["resultado"] = "ok"
        except anthropic.RateLimitError as e:
            fila["resultado"] = "error_claude_429"
            log.error("Claude: límite de uso (429, request_id=%s)", getattr(e, "request_id", None))
        except anthropic.APIStatusError as e:
            fila["resultado"] = f"error_claude_{e.status_code}"
            log.error("Claude: error HTTP %s (%s)", e.status_code, type(e).__name__)
        except anthropic.APIConnectionError as e:
            fila["resultado"] = "error_claude_conexion"
            log.error("Claude: sin conexión o timeout (%s)", type(e).__name__)
        except ErrorMeta as e:
            fila["resultado"] = f"error_meta_{e.status_code}"
            log.error("Meta Cloud API respondió %s: %s", e.status_code, e.detalle)
        except httpx.HTTPError as e:
            fila["resultado"] = "error_meta_conexion"
            log.error("Meta Cloud API: sin conexión o timeout (%s)", type(e).__name__)
        except Exception as e:  # inesperado: se registra con traza, nunca se traga
            fila["resultado"] = "error_interno"
            log.exception("Error inesperado procesando un mensaje (%s)", type(e).__name__)
        fila.update({
            "t_recibido": _iso(t_recibido), "t_claude_ok": _iso(t_claude), "t_meta_ok": _iso(t_meta),
            "s_claude": _segundos(t_recibido, t_claude), "s_meta": _segundos(t_claude, t_meta),
            "s_total": _segundos(t_recibido, t_meta),
        })
        self._registrar(fila)
        return fila

    def _registrar(self, fila: dict[str, Any]) -> None:
        with self._lock_registro, self.ruta_registro.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")


class ErrorMeta(RuntimeError):
    def __init__(self, status_code: int, detalle: str):
        self.status_code, self.detalle = status_code, detalle
        super().__init__(f"Meta {status_code}: {detalle}")


def _resumen_error_meta(r: httpx.Response) -> str:
    """Código, tipo y mensaje del error de Graph (sin cabeceras ni token), con teléfonos filtrados."""
    try:
        err = (r.json() or {}).get("error") or {}
        texto = f"code={err.get('code')} type={err.get('type')} message={str(err.get('message'))[:200]}"
    except ValueError:
        texto = r.text[:200]
    return filtrar_telefonos(texto)


# --- página /prompt ----------------------------------------------------------------------------------
# Etiqueta al inicio de una línea («- Servicios:», «Reglas obligatorias:»): va en <strong> para que se lea fácil.
_ETIQUETA_LINEA = re.compile(r"^(- )?([^:.;()]{1,40}?:)(\s|$)")
_CSS_PROMPT = """
:root { color-scheme: light; }
body { margin: 0; background: #f6f7f9; color: #1c1e21; font: 20px/1.55 -apple-system, BlinkMacSystemFont,
       "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 1180px; margin: 40px auto; padding: 32px 44px; background: #fff; border-radius: 12px;
       box-shadow: 0 1px 3px rgba(0, 0, 0, .12); }
h1 { margin: 0 0 4px; font-size: 26px; }
.sub { margin: 0 0 24px; color: #606770; font-size: 17px; }
.linea { margin: 0 0 10px; white-space: pre-wrap; }
.vineta { padding-left: .75em; text-indent: -.75em; }
"""


def _linea_html(linea: str) -> str:
    m = _ETIQUETA_LINEA.match(linea)
    clase = "linea vineta" if linea.startswith("- ") else "linea"
    if not m:
        return f'<p class="{clase}">{html.escape(linea)}</p>'
    vineta, etiqueta = m.group(1) or "", m.group(2)
    resto = linea[len(vineta) + len(etiqueta):]
    return (f'<p class="{clase}">{html.escape(vineta)}<strong>{html.escape(etiqueta)}</strong>'
            f"{html.escape(resto)}</p>")


def pagina_prompt(texto: str = SYSTEM_PROMPT) -> str:
    """HTML legible del system prompt real, línea por línea y con el texto exacto (solo se escapa).
    No lleva nada de la configuración: ni modelo, ni IDs, ni tokens; solo el texto que recibe Claude."""
    cuerpo = "\n".join(_linea_html(l) for l in texto.split("\n"))
    return ("<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
            "<title>Instrucciones del bot</title>"
            f"<style>{_CSS_PROMPT}</style></head><body><main>"
            "<h1>Instrucciones del bot (system prompt)</h1>"
            "<p class=\"sub\">Lo que lee la IA antes de contestar cada mensaje.</p>"
            f"{cuerpo}</main></body></html>")


def crear_app(config: Config | None = None, *, claude: Any = None, http: httpx.Client | None = None,
              ruta_registro: Path = RUTA_REGISTRO,
              reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> FastAPI:
    """Fábrica de la app (uvicorn --factory). En pruebas se inyectan dobles de Claude, httpx y reloj."""
    if config is None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        try:
            config = cargar_config()
        except ErrorConfig as e:
            raise SystemExit(f"servidor.py no arranca: {e}") from None
    if claude is None:
        claude = anthropic.Anthropic()  # lee ANTHROPIC_API_KEY del entorno
    bot = Bot(config, claude, http or httpx.Client(), ruta_registro, reloj)
    dedup = Deduplicador()
    app = FastAPI(title="Webhook WhatsApp -> Claude (video)", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.bot = bot
    app.state.ignorados_otro_numero = 0

    @app.get("/salud")
    def salud() -> dict[str, str]:
        return {"estado": "ok"}

    @app.get("/prompt", response_class=HTMLResponse)
    def prompt() -> HTMLResponse:
        return HTMLResponse(pagina_prompt(SYSTEM_PROMPT))

    @app.get("/webhook")
    def verificar(request: Request):
        q = request.query_params
        token = q.get("hub.verify_token") or ""
        if q.get("hub.mode") == "subscribe" and hmac.compare_digest(token.encode(), config.verify_token.encode()):
            log.info("Webhook verificado por Meta")
            return PlainTextResponse(q.get("hub.challenge") or "", status_code=200)
        log.warning("Verificación de webhook rechazada (modo o token incorrectos)")
        return PlainTextResponse("forbidden", status_code=403)

    @app.post("/webhook")
    async def recibir(request: Request, tareas: BackgroundTasks):
        t_recibido = reloj()
        cuerpo = await request.body()
        if not firma_valida(cuerpo, request.headers.get("x-hub-signature-256"), config.app_secret):
            log.warning("POST /webhook con firma ausente o inválida: 403")
            return PlainTextResponse("forbidden", status_code=403)
        try:
            payload = json.loads(cuerpo)
        except ValueError:
            log.warning("POST /webhook con cuerpo que no es JSON; se ignora")
            return JSONResponse({"ok": True})
        ajenos = contar_ajenos(payload, config.phone_number_id)
        if ajenos:  # avisos de otro número: no van a Claude ni se contestan; solo se cuentan
            app.state.ignorados_otro_numero += ajenos
            log.warning("Ignorados %d mensaje(s) de otro número (phone_number_id distinto o sin metadata); total %d",
                        ajenos, app.state.ignorados_otro_numero)
        for msg in extraer_mensajes(payload, config.phone_number_id):
            if dedup.es_nuevo(msg["id"]):
                tareas.add_task(bot.procesar, msg, t_recibido)
            else:
                log.info("Mensaje repetido de %s ignorado (reintento de Meta)", hash_corto(msg["wa_id"]))
        return JSONResponse({"ok": True})  # 200 inmediato; Claude y Meta van en segundo plano

    return app
