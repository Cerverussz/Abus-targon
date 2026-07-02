# Targon Watch — Monitor de stock Abus Targon MIPS (talla M)

Monitorea la disponibilidad del casco **Abus Targon MIPS** en **talla M (55–58 cm)**
en varias tiendas, corre **3 veces al día** y avisa por **Telegram** únicamente cuando
hay un **cambio relevante**:

- la talla M **pasa a estar DISPONIBLE**, o
- **cambia el precio** mientras sigue disponible.

Diseñado para **cero falsos positivos** (solo avisa "disponible" cuando la M es realmente
comprable) y **notificaciones idempotentes** (no repite el mismo aviso en cada corrida).

---

## ¿Cómo funciona?

Por cada tienda definida en `config/stores.yaml`:

1. Carga la página del producto (o de la colección, para catálogos).
2. Localiza la opción de **talla M**.
3. Determina el estado real: `AVAILABLE`, `OUT_OF_STOCK`, `PREORDER` o `NOT_LISTED`.
4. Captura el precio (y el color, cuando es posible) si está disponible.

El estado de cada tienda se guarda en `state.json`. En la siguiente corrida se compara
contra ese estado y **solo se notifica si algo cambió**, priorizando la transición a
DISPONIBLE. Un fallo en una tienda se registra como `ERROR` y **no rompe la corrida**.

### Métodos de detección (config-driven)

Cada tienda declara su `method` en `stores.yaml`:

| método       | uso                                                | cómo decide disponibilidad |
|--------------|----------------------------------------------------|----------------------------|
| `shopify`    | tiendas Shopify (DSCBike, BiciMarket)              | `variant.available` del JSON de Shopify (dato estructurado, fiable) |
| `static`     | páginas estáticas (HTML servido tal cual)          | `httpx` + BeautifulSoup + keywords/selectores |
| `playwright` | sitios con JS sin anti-bot (All4cycling)           | Chromium headless: la M debe ser seleccionable y el carrito habilitado |
| `scraper`    | sitios con anti-bot (LordGun/Cloudflare, Abus/Akamai) | servicio externo renderiza y resuelve el challenge; se parsea el HTML con keywords/selectores |

Las tiendas colombianas usan `shopify` apuntando a la colección `/collections/abus`:
se busca el término `targon`; si no aparece, se busca en toda la tienda
(`/search/suggest.json`) y, si tampoco está, se marca `NOT_LISTED` (sirve para detectar
cuándo el modelo aterriza en Colombia).

Si un sitio bloquea al navegador (Cloudflare "Un momento…", Akamai "Access Denied"),
el detector **no inventa un estado**: devuelve `ERROR` (no "agotado"), para no perder
una eventual disponibilidad. El método `scraper` enruta esos sitios por un servicio
externo que sí supera el bloqueo (ver abajo).

---

## Requisitos

- Python 3.11+
- Un bot de Telegram (token de [@BotFather](https://t.me/BotFather)) y tu `chat_id`.

## Setup paso a paso

```bash
# 1. Clonar e instalar dependencias
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Navegador para el método playwright
python -m playwright install chromium

# 3. Configurar credenciales
cp .env.example .env
# edita .env y rellena TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID
```

### Probar Telegram

Valida que las credenciales funcionan antes de la primera corrida real:

```bash
python -m src.notifier --test
```

Debe llegarte un mensaje de prueba al chat.

### Servicio de scraping (tiendas con anti-bot)

LordGun (Cloudflare) y Abus US (Akamai) bloquean al navegador headless, así que usan
`method: scraper`, que enruta la petición por un servicio externo que resuelve el
challenge y devuelve el HTML renderizado. Pasos:

1. Crea una cuenta en un proveedor (cualquiera de estos sirve; todos tienen plan
   gratuito que cubre de sobra ~6 peticiones/día):
   - [ScraperAPI](https://www.scraperapi.com/) → `SCRAPER_PROVIDER=scraperapi`
   - [ZenRows](https://www.zenrows.com/) → `SCRAPER_PROVIDER=zenrows`
   - [ScrapingBee](https://www.scrapingbee.com/) → `SCRAPER_PROVIDER=scrapingbee`
2. En `.env` (local) y/o en los *secrets* de GitHub, define:
   ```
   SCRAPER_PROVIDER=scraperapi
   SCRAPER_API_KEY=tu_api_key
   ```
3. Para cualquier otro proveedor con API tipo GET, usa `SCRAPER_PROVIDER=custom` y
   define `SCRAPER_BASE_URL`, `SCRAPER_PARAMS` (JSON), `SCRAPER_KEY_PARAM`,
   `SCRAPER_URL_PARAM` (ver `.env.example`).

> Si **no** configuras el servicio, esas dos tiendas quedan en `ERROR` (no rompen la
> corrida) y el resto del monitor funciona normal. No hay falsos positivos.

**Modo reforzado (`scraper_hard`).** LordGun (Cloudflare) y Abus (Akamai) tienen anti-bot
duro; en `stores.yaml` llevan `scraper_hard: true`, que activa el modo premium del
proveedor (ScraperAPI `ultra_premium`, ZenRows/ScrapingBee `premium_proxy`). **Consume
más créditos por petición** (p. ej. ScraperAPI cobra ~10–30 créditos en vez de 1), así
que revisa el plan de tu proveedor. Con 3 corridas/día son ~6 peticiones duras diarias.
El detector reintenta ante errores 5xx/429 y registra el cuerpo del error para diagnóstico.

### Corrida manual

```bash
python -m src.checker
```

Revisa todas las tiendas, deja un resumen en el log y actualiza `state.json`.
La primera vez crea `state.json`; las tiendas colombianas deberían dar `NOT_LISTED`.
Si ejecutas dos veces seguidas sin cambios reales, la segunda **no envía notificaciones**.

---

## Agregar / quitar una tienda

Edita **solo** `config/stores.yaml`. Añade una entrada bajo `stores:` con su `method`
y un bloque `detect:`. No hay que tocar código. Ejemplo mínimo (Shopify):

```yaml
  mi_tienda:
    name: Mi Tienda
    country: Colombia
    currency: COP
    url: https://mitienda.com/collections/abus
    method: shopify
    detect:
      require_mips: true
      search_term: "targon"
      size_keywords: ["M", "55-58", "Medium"]
```

Para desactivar una tienda temporalmente, añade `enabled: false`.

Los campos de `detect:` están documentados al inicio de `config/stores.yaml`.

> **Nota sobre selectores:** para los sitios `playwright`/`static`, los selectores CSS
> incluidos son una primera aproximación. Si una tienda cambia su maquetación, ajusta
> `size_selector` / `add_to_cart_selector` / `price_selector` en el YAML.

---

## Scheduling (3 corridas/día)

### Opción recomendada: GitHub Actions

El workflow `.github/workflows/check.yml` ya está incluido y corre a las
**13:00, 19:00 y 01:00 UTC** (≈ 8:00 a.m., 2:00 p.m. y 8:00 p.m. hora Colombia).

1. En GitHub: **Settings → Secrets and variables → Actions → New repository secret** y crea:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `SCRAPER_PROVIDER` y `SCRAPER_API_KEY` (opcionales; solo si quieres monitorear
     LordGun/Abus, que están tras anti-bot)
2. El workflow instala dependencias + Chromium, ejecuta `python -m src.checker` y hace
   **commit/push de `state.json`** de vuelta a la rama (por eso `state.json` **no** está
   en `.gitignore`): así el estado sobrevive entre corridas en runners efímeros.
3. Puedes lanzar una corrida manual desde la pestaña **Actions → Targon stock check →
   Run workflow** (`workflow_dispatch`).

### Alternativa local

**Linux/macOS (cron):**

```cron
# crontab -e  (las horas son UTC; ajusta a tu zona)
0 13,19,1 * * * cd /ruta/a/targon-watch && /ruta/.venv/bin/python -m src.checker >> run.log 2>&1
```

**Windows (Task Scheduler):**

1. Crea una tarea básica con 3 desencadenadores diarios (8:00, 14:00, 20:00 hora local).
2. Acción → *Iniciar un programa*:
   - Programa: `C:\ruta\.venv\Scripts\python.exe`
   - Argumentos: `-m src.checker`
   - Iniciar en: `C:\ruta\targon-watch`

En local, `state.json` se guarda en el directorio del proyecto y persiste entre corridas
sin necesidad de commitear.

---

## Estructura del proyecto

```
config/stores.yaml              # tiendas + reglas de detección (editar aquí)
src/checker.py                  # orquestador: recorre tiendas, evalúa, notifica
src/notifier.py                 # Telegram Bot API (+ modo --test)
src/state.py                    # leer/guardar state.json + diff (idempotencia)
src/models.py                   # Status enum + CheckResult
src/stores/                     # un detector por método
  ├─ base.py                    # interfaz + utilidades de clasificación
  ├─ shopify_store.py           # método "shopify"
  ├─ static_store.py            # método "static" (httpx + BeautifulSoup)
  └─ playwright_store.py        # método "playwright" (Chromium)
.github/workflows/check.yml     # cron 3×/día + commit de state.json
.env.example                    # plantilla de credenciales
requirements.txt
```

## Variables de entorno

| variable             | obligatoria | descripción                                   |
|----------------------|-------------|-----------------------------------------------|
| `TELEGRAM_BOT_TOKEN` | sí          | token del bot de Telegram                     |
| `TELEGRAM_CHAT_ID`   | sí          | chat al que enviar los avisos                 |
| `SCRAPER_PROVIDER`   | si hay `scraper` | `scraperapi` \| `zenrows` \| `scrapingbee` \| `custom` |
| `SCRAPER_API_KEY`    | si hay `scraper` | API key del servicio de scraping          |
| `STORES_CONFIG`      | no          | ruta del YAML (por defecto `config/stores.yaml`) |
| `STATE_FILE`         | no          | ruta del estado (por defecto `state.json`)    |
| `LOG_LEVEL`          | no          | `DEBUG` / `INFO` / `WARNING` (por defecto `INFO`) |
