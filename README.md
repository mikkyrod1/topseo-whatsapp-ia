# Bot de WhatsApp con IA (API oficial de Meta + Claude)

## Qué vas a construir

Un bot que contesta a tus clientes en WhatsApp, a cualquier hora. Tu cliente escribe, Meta le avisa a un programa en
tu computadora, ese programa le pregunta a Claude (la IA de Anthropic) y la respuesta sale por la API oficial de Meta.
Viene con un negocio de ejemplo inventado, «Taller Demo», que cambias por el tuyo.

Video con todo el proceso, paso a paso: [ver el video](VIDEO_URL)

Esta guía es para copiar y pegar. El video te enseña que funciona y por qué. Los minutos que ves en cada paso son los
del video. Yo lo hice en una Mac; en Windows o Linux algunos comandos cambian.

## Antes de empezar: siete palabras

- **Terminal**: una ventana donde le escribes instrucciones a tu computadora. En Mac se llama «Terminal».
- **API**: la puerta que Meta (o Anthropic) te abre para que tu programa hable con su sistema, con su permiso.
- **Token (llave)**: la contraseña larga que abre esa puerta. Quien la tenga puede mandar mensajes a nombre de tu
  negocio. No se comparte.
- **Webhook (timbre)**: el aviso que Meta le manda a tu programa cada vez que alguien te escribe. Meta toca el timbre y
  tu programa abre.
- **Túnel**: le da a tu computadora una dirección pública en internet, como un desvío de llamadas: lo que llega a esa
  dirección se pasa a tu computadora.
- **Variable de entorno (.env)**: un archivo en tu computadora donde guardas tus llaves y datos, uno por línea. El
  programa los lee de ahí; así nunca van dentro del código.
- **Workspace (espacio de trabajo)**: dentro de tu cuenta de Anthropic, el apartado donde viven tus llaves y donde se
  separa lo que gastas.

## Requisitos

- **Cuenta de Facebook y registro como desarrollador de Meta.** Con tu cuenta de Facebook abierta, te registras aquí:
  https://developers.facebook.com/documentation/development/register
- **Python 3.11 o más nuevo** (con esa versión lo probé). Para ver cuál tienes, escribe en la terminal:

  ```bash
  python3 --version
  ```

  Debe decir `Python 3.11` o un número más alto. Si sale un número menor, o la terminal no lo encuentra, instala la
  versión nueva desde https://www.python.org/downloads/ y vuelve a revisar.
- **Llave de API de Anthropic** (la IA): la creas en https://platform.claude.com/settings/keys. Al crearla, elige que
  funcione en un solo workspace (por ejemplo, el que viene por defecto). Así el programa la usa tal cual.
- **Saldo en Anthropic.** La API de Anthropic cobra por uso: necesitas saldo para que el bot conteste. Precios
  oficiales: https://platform.claude.com/docs/en/about-claude/pricing (el saldo se compra en
  https://platform.claude.com/settings/billing).
- **Homebrew** (en Mac, para instalar lo demás). Si al escribir `brew` la terminal dice que no lo encuentra, instálalo
  con el comando que da su página oficial (https://brew.sh/). Es este:

  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```

  Al terminar, Homebrew te muestra una sección 'Next steps' con unos comandos: cópialos y córrelos en la terminal antes de seguir.

- **cloudflared** (el túnel): https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/
  En Mac se instala con Homebrew. Lo instalamos en el paso g.
- **git**, para bajar el código: https://git-scm.com/downloads
- **jq**, para que las respuestas de Meta se lean bonito en la terminal: https://jqlang.org/download/ (en Mac:
  `brew install jq`).
- Tu celular con WhatsApp, para probar.

## Pasos

### a. Crear la app en Meta

- **Dónde:** https://developers.facebook.com/apps/
- **Qué haces:**
  1. Clic en **Crear app**.
  2. Le pones un nombre (el de tu negocio, para que la ubiques) y un correo que sí revises.
  3. En el caso de uso eliges **Conectarte con los clientes a través de WhatsApp** (en inglés: *Connect with customers
     through WhatsApp*).
  4. Eliges el portafolio comercial de tu negocio. Luego Meta te enseña los requisitos y un resumen.
  5. Clic en **Crear app**.
  6. Conecta la app a una cuenta de WhatsApp Business: eliges la tuya y confirmas. Ahí vive tu número.
- **Cómo sabes que quedó:** en el panel de tu app aparece el caso de uso de WhatsApp («Personalizar el caso de uso
  Conectarte con los clientes a través de WhatsApp»).
- **En el video:** 01:52 (lista de apps), 02:06 (nombre y correo), 02:23 (caso de uso), 03:09 (conectar la cuenta).

### b. Número de prueba y lista «Para»

- **Dónde:** en el panel de tu app, entra al caso de uso de WhatsApp y luego a **Configuración de la API**.
- **Qué haces:**
  1. En **De**, elige el **Número de prueba** que te presta Meta.
  2. Copia el **Identificador de número de teléfono**. Va en tu `.env` como `META_PHONE_NUMBER_ID`.
  3. Copia también el **Identificador de la cuenta de mensajes**, que sale a un lado. Va en tu `.env` como
     `META_MESSAGING_ACCOUNT_ID`. Es el de la cuenta donde vive el número (lo usamos en el paso i).
  4. En **Para**, agrega tu propio celular con los pasos que te pide Meta. Con la app sin publicar, el bot recibe y responde mensajes de los números que agregaste a la lista de destinatarios.
- **Cómo sabes que quedó:** en **De** se ve el número de prueba y, abajo, sus identificadores.
- **En el video:** 03:35 (Configuración de la API), 03:56 (número e identificadores), 04:13 (campo «Para»).

Ojo: el botón **Generar token de acceso** de esa página da una llave temporal, que dura menos de 24 horas. Sirve para
probar un rato, no para un bot. La llave buena sale del paso c. (En el video: 04:52.)

### c. Usuario del sistema y token permanente

Un usuario del sistema es un usuario para tus programas, no para una persona. Su llave no caduca y no depende de que
alguien de tu equipo siga en el negocio.

- **Dónde:** https://business.facebook.com/latest/settings/system_users (la configuración de tu portafolio comercial,
  sección **Usuarios del sistema**).
- **Qué haces:**
  1. Crea un usuario del sistema nuevo.
  2. Dale acceso a tu app y a la cuenta de mensajes donde vive tu número, la del paso b. En la configuración de mi
     portafolio se ve con su nombre, «Test Messaging Account», y abajo dice «Messaging account» (en el video: 14:35).
  3. Clic en **Generar token**. Meta te pide tres cosas, una por pantalla: la app, la caducidad (elige que no caduque
     nunca) y los permisos. Marca `whatsapp_business_messaging` y `whatsapp_business_management`. Con esos dos me
     funcionó todo; la guía oficial de Meta pide además `business_management`.
  4. Copia el token y guárdalo en tu `.env` como `META_ACCESS_TOKEN`. No lo pegues en ningún chat.
- **Cómo sabes que quedó:** lo compruebas en el paso d con el primer comando.
- **En el video:** 05:37 (usuarios del sistema), 05:59 (generar token).
- Guía oficial de Meta (pasos 1 a 5): https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started

### d. Consultar y registrar el número

Estos comandos se escriben en la terminal, dentro de la carpeta del proyecto y con tu `.env` ya lleno. Si todavía no
bajas el código ni llenas el `.env`, haz primero el paso e y regresa aquí.

Primero carga tus datos en la terminal, sin que se vean en pantalla:

```bash
set -a; . ./.env; set +a
```

Desde aquí, la llave va como `$META_ACCESS_TOKEN`: la terminal ya la tiene guardada y nunca la escribes a mano.

**1. Revisa tu llave.** Este comando solo lee; no cambia nada.

```bash
curl -s "https://graph.facebook.com/$META_GRAPH_VERSION/debug_token?input_token=$META_ACCESS_TOKEN" -H "Authorization: Bearer $META_ACCESS_TOKEN" | jq '.data | {type, application, expires_at, is_valid, scopes}'
```

Cómo sabes que está bien: `"type": "SYSTEM_USER"`, el nombre de tu app en `"application"`, `"expires_at": 0` (cero
quiere decir que no caduca), `"is_valid": true` y, en `"scopes"`, los dos permisos de WhatsApp. En el video: 07:01.

**2. Pregúntale a Meta cómo está tu número.**

```bash
curl -s "https://graph.facebook.com/$META_GRAPH_VERSION/$META_PHONE_NUMBER_ID?fields=status,code_verification_status,display_phone_number,verified_name" -H "Authorization: Bearer $META_ACCESS_TOKEN" | jq
```

Cómo sabes que está bien: `"status": "CONNECTED"`. Si dice `"PENDING"`, te falta registrarlo (abajo). A mí la primera
vez me salió `PENDING`, y WhatsApp decía que ese número no estaba en WhatsApp. En el video: 07:31.

**3. Solo si salió `PENDING`: registra el número.** Meta solo deja registrarlo por la API. Lleva un PIN de seis
dígitos: si tu número ya tiene verificación en dos pasos, es ese PIN; si no, inventa uno de seis dígitos y ese queda
como tu PIN. Si ya la tenía y no recuerdas el PIN, Meta deja cambiarlo:
https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/two-step-verification/
Va en tu `.env`, en `META_REGISTER_PIN` (paso e). Si lo llenaste después de cargar el `.env`, vuelve a
cargarlo (el comando `set -a` de arriba). Luego corre:

```bash
curl -s -X POST "https://graph.facebook.com/$META_GRAPH_VERSION/$META_PHONE_NUMBER_ID/register" -H "Authorization: Bearer $META_ACCESS_TOKEN" -H "Content-Type: application/json" -d '{"messaging_product":"whatsapp","pin":"'"$META_REGISTER_PIN"'"}' | jq
```

Cómo sabes que quedó: Meta contesta `"success": true`. Repite el comando 2: ahora debe decir `CONNECTED`. En el
video: 08:16 (registro) y 08:40 (respuesta).
Documentación oficial: https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/registration/

### e. Llenar el .env

Abre la terminal y escribe estos comandos, uno por uno.

Baja el código:

```bash
git clone https://github.com/mikkyrod1/topseo-whatsapp-ia.git
```

Entra a su carpeta:

```bash
cd topseo-whatsapp-ia
```

Copia la plantilla del archivo de configuración:

```bash
cp .env.example .env
```

Ábrelo para llenarlo (en Mac se abre en TextEdit):

```bash
open -e .env
```

En el video la plantilla se ve un poco distinta; usa la de este repo, que es la actualizada.

Llena cada línea después del `=`, sin espacios ni comillas:

| Línea | Qué va | De dónde sale |
|---|---|---|
| `META_ACCESS_TOKEN` | la llave permanente | paso c |
| `META_PHONE_NUMBER_ID` | el identificador del número | paso b |
| `META_MESSAGING_ACCOUNT_ID` | el identificador de la cuenta de mensajes, donde vive el número | paso b (se comprueba en el paso i) |
| `META_APP_SECRET` | la clave secreta de la app; con ella el servidor revisa que cada aviso venga de Meta | en tu app, menú **Configuración de la app** → **Básica**, campo **Clave secreta de la app** (botón **Mostrar**) |
| `META_VERIFY_TOKEN` | una contraseña que tú inventas, solo letras y números | tú; la misma va en el paso h |
| `META_REGISTER_PIN` | un PIN de 6 dígitos: el de la verificación en dos pasos de tu número o, si no tiene, uno que tú eliges | tú; solo se usa si en el paso d el número sale `PENDING` |
| `META_GRAPH_VERSION` | ya viene llena con `v23.0`, la que usé; solo cámbiala si la guía oficial indica otra | https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started |
| `ANTHROPIC_API_KEY` | tu llave de Anthropic | https://platform.claude.com/settings/keys |
| `CLAUDE_MODEL` | el modelo de Claude que vas a usar (yo usé un Sonnet); copia su «Claude API ID» | lista oficial: https://platform.claude.com/docs/en/models/overview |

Guarda el archivo. Se queda solo en tu computadora.

- **En el video:** 06:14 y 10:57 (la plantilla), 10:39 (los comandos).

### f. Correr el servidor

En la misma carpeta, instala lo que el programa necesita (solo la primera vez):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Arranca el servidor:

```bash
.venv/bin/python -m uvicorn servidor:crear_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

- **Cómo sabes que quedó:** la terminal dice `Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)`. Abre
  http://127.0.0.1:8000/salud en tu navegador: debe decir `{"estado":"ok"}`. En http://127.0.0.1:8000/prompt ves las
  instrucciones que lee la IA.
- Si falta algo en tu `.env`, no arranca y te dice qué: `servidor.py no arranca: faltan variables en .env: …`
- Deja esa ventana abierta. Si cambias el `.env` o el prompt, detén el servidor con `CTRL+C` y vuelve a arrancarlo: lee
  todo al arrancar. A mí me pasó: cambié la llave y el bot seguía fallando, porque el servidor tenía la vieja en
  memoria.
- **En el video:** 10:39 (el comando) y 16:38 (la página del prompt).

### g. Abrir el túnel

Abre **otra** ventana de la terminal (la del servidor sigue corriendo). Instala cloudflared (en Mac con Homebrew):

```bash
brew install cloudflared
```

Abre el túnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

- **Cómo sabes que quedó:** sale un recuadro con «Your quick Tunnel has been created!» y una dirección
  `https://algo-al-azar.trycloudflare.com`. Esa es tu dirección pública.
- Es temporal: cada vez que abres el túnel te da una distinta, y si cierras esa ventana o apagas tu computadora, se
  cae. Déjala abierta mientras pruebas. Si la dirección cambia, repite el paso h con la nueva.
- **En el video:** 11:15 (instalar), 11:34 (abrir), 11:45 (la dirección).
- Documentación oficial: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/

### h. Webhook y «Verificar y guardar»

El timbre necesita tres cosas, y si falta cualquiera, no llega nada: verificar la dirección, elegir el aviso de
mensajes (este paso) y suscribir la app a la cuenta que tiene el número (paso i).

- **Dónde:** en tu app, caso de uso de WhatsApp → **Configuración** → tarjeta **Webhook**.
- **Qué haces:**
  1. En **URL de devolución de llamada** pega la dirección de tu túnel y agrégale `/webhook` al final.
  2. En **Token de verificación** pega lo mismo que pusiste en `META_VERIFY_TOKEN`.
  3. Clic en **Verificar y guardar**. Meta le hace una pregunta de prueba a tu servidor; si la contraseña coincide, la
     acepta.
  4. Más abajo, en **Campos del webhook**, busca `messages` y suscríbete (debe decir **Suscritos**).
- **Cómo sabes que quedó:** la dirección se queda guardada en el campo y, en la ventana del servidor, aparece una línea
  con `Webhook verificado por Meta`.
- **En el video:** 12:06 (las tres piezas), 12:45 (los dos campos), 13:03 (verificado), 13:18 (`messages`).
- Documentación oficial: https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint/

### i. Suscribir la app (Messaging account)

Aquí está la trampa en la que yo caí. En mi portafolio había dos cuentas: «WhatsApp account» y «Messaging account». El
número vivía en la Messaging account, y la suscripción solo funciona en la cuenta donde vive el número.
En el video, a las 14:12, la primera cuenta que pruebo da error 2388339: esa es la equivocada. Usa la Messaging account.

En la terminal del paso d (con tu `.env` cargado), primero confirma que tu cuenta tiene tu número:

```bash
curl -s "https://graph.facebook.com/$META_GRAPH_VERSION/$META_MESSAGING_ACCOUNT_ID/phone_numbers" -H "Authorization: Bearer $META_ACCESS_TOKEN" | jq
```

Cómo sabes que es la cuenta buena: en la lista sale tu número de prueba. Si sale un error con `2388339`, es la cuenta
equivocada (ver «Errores comunes»).

Suscribe la app a esa cuenta:

```bash
curl -s -X POST "https://graph.facebook.com/$META_GRAPH_VERSION/$META_MESSAGING_ACCOUNT_ID/subscribed_apps" -H "Authorization: Bearer $META_ACCESS_TOKEN" | jq
```

Cómo sabes que quedó: contesta `"success": true`. Para revisarlo:

```bash
curl -s "https://graph.facebook.com/$META_GRAPH_VERSION/$META_MESSAGING_ACCOUNT_ID/subscribed_apps" -H "Authorization: Bearer $META_ACCESS_TOKEN" | jq
```

Ahí aparece el nombre de tu app. A mí, antes de esto, esa lista salía vacía, y a partir de aquí empezaron a llegar
los mensajes.

- **En el video:** 14:03 (la cuenta equivocada), 14:35 (de dónde sale el identificador), 14:55 (la cuenta buena),
  15:15 (suscripción).

### j. Probar desde WhatsApp

Con el servidor y el túnel abiertos, escríbele al número de prueba desde el celular que agregaste en «Para». Pregunta
algo que contestaría tu negocio, por ejemplo: «¿Qué servicios tienen y en qué horario atienden?».

- **Cómo sabes que funciona:** en unos segundos llega la respuesta, escrita por la IA con los datos del prompt.
- **En el video:** 18:31 (el mensaje) y 18:42 (la respuesta).

## Errores comunes

**«Object with ID '…' does not exist» al elegir el número en el panel.** A mí el panel me marcaba que el número no
existía, y sí existía. Por la API, con la llave permanente, me lo regresó completo. Si el panel te falla, haz lo mismo
por la API: el comando 2 del paso d y, si sale `PENDING`, el registro. En el video: 04:28.

**Error `2388339` («This API is not supported for this WhatsApp Business Account»).** Estás usando la cuenta
equivocada. Usa la Messaging account, la que tiene tu número: es el **Identificador de la cuenta de mensajes** de
Configuración de la API, y también sale en la configuración de tu portafolio, en las cuentas de WhatsApp. Ponlo en
`META_MESSAGING_ACCOUNT_ID`, vuelve a cargar el `.env` y repite el paso i. En el video: 14:03 y 14:35.

**Error `131030` («Recipient phone number not in allowed list») si estás en México.** Cuando te escribes desde un
celular de México, el aviso de Meta trae tu número como `521` más 10 dígitos. Si le contestas a ese número, Meta lo
rechaza, aunque sí esté en tu lista: la lista lo guarda sin el 1, como `52` más 10 dígitos. El servidor ya lo corrige
solo (la función `normalizar_destinatario`). Si quieres probar el envío a mano, escríbele primero al bot desde tu
celular y luego corre este comando. Donde dice `TU_NUMERO_WHATSAPP`, cámbialo por tu número: `52` más tus 10
dígitos, sin `+` ni espacios.

```bash
curl -s -X POST "https://graph.facebook.com/$META_GRAPH_VERSION/$META_PHONE_NUMBER_ID/messages" -H "Authorization: Bearer $META_ACCESS_TOKEN" -H "Content-Type: application/json" -d '{"messaging_product":"whatsapp","to":"TU_NUMERO_WHATSAPP","type":"text","text":{"body":"Prueba con 52"}}' | jq
```

Si sale bien, contesta con `"messages"` y te llega «Prueba con 52». En el video: 15:42 (el error), 15:57 (sin el 1)
y 16:25 (la función del servidor).

**El bot inventa servicios o precios.** La IA solo sabe lo que trae el prompt. Sin tus datos, rellena los huecos con
cosas que suenan bien pero que tu negocio a lo mejor ni ofrece. Abre `servidor.py`, busca `NEGOCIO_DEMO` y cambia
«Taller Demo» por tu nombre, tu giro, tus servicios y tu horario. Guarda y reinicia el servidor. Las reglas del prompt
(`SYSTEM_PROMPT`) le piden contestar solo con esa información y pasar lo demás a un asesor. En el video: 16:38 y 17:21.

**Cambiaste el `.env` y sigue fallando.** Reinicia el servidor (paso f).

## Pasar a producción

El túnel es temporal: depende de que tu computadora esté prendida y la dirección cambia cada vez. Para atender
clientes de verdad, el programa tiene que vivir en un servidor fijo, prendido todo el día y con una dirección que no
cambie. Esa dirección es la que pones en el webhook. En el video: 20:52.

## Seguridad

- **Nunca subas tu `.env`** a GitHub ni a ningún lado, y no lo pegues en un chat. El `.gitignore` de este repositorio
  ya lo deja fuera. Lo único que se comparte es `.env.example`, que va vacío.
- **Si se filtra tu llave de Meta:** genera una nueva para tu usuario del sistema (paso c) y borra la vieja de tu
  `.env`: pon la nueva en su lugar y reinicia el servidor.
- **Si se filtra tu llave de Anthropic:** desactívala o bórrala en https://platform.claude.com/settings/keys, crea
  otra, cámbiala en tu `.env` y reinicia el servidor.
- **Privacidad:** el servidor no guarda teléfonos, identificadores de mensaje, llaves ni lo que escriben tus clientes.
  `registro.jsonl` solo lleva tiempos, el modelo y el resultado de cada respuesta, con un código corto en lugar del
  número.

## Licencia

El código es MIT. Lo puedes usar, cambiar y compartir. El texto completo está en [LICENSE](LICENSE).

## Créditos

TopSEO by SEO en México. Canal: [TopSEO en YouTube](CANAL_URL)
