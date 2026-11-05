# ScrapperDPEC

Given that I'm fed up with being left without electricity due to a scheduled service outage, and not having any information about it, I created this repository to "web scrape" data from DPEC official page. Thus one day prior to the scheduled outage, the application send a message to me so I can be aware of scheduled power cuts.

> Proyecto personal, sin relación con la DPEC. La información oficial es siempre la de [dpec.com.ar](https://www.dpec.com.ar/comercial/cortes-programados/).

## Cómo funciona

```
GitHub Actions (cada 3 h)
   └─ dpec run
        ├─ scraper:     lista JSON + página de cada aviso nuevo de la DPEC ─► PostgreSQL (Supabase)
        └─ notificador: cortes de hoy y mañana × suscripciones ─► Notifier ─► email
```

- **Fuente:** `GET https://www.dpec.com.ar/es/seccion/17-articulos.json?rows=50&page=1`. El título tiene la fecha y un resumen; la página del aviso tiene las zonas y los horarios reales. Los avisos son texto escrito a mano, así que el parser se mide contra todo el histórico (`backend/tests/fixtures/titulos_historicos.json`).
- **Publicador-suscriptor sin broker:** el scraper solo guarda y el notificador solo lee. La tabla `notificaciones` garantiza que cada día de cada corte se avise una vez por suscripción.
- **Notifier (patrón Strategy):** para agregar WhatsApp o Telegram, se crea una subclase de `Notifier` y se registra en `crear_notifier` (`backend/src/scrapper_dpec/notifiers/`).
- **Ante un error:** si la DPEC no responde, igual se envían los avisos ya conocidos. El workflow termina fallido y GitHub te avisa por email.

## Desarrollo local

Requiere Python 3.12+, Docker y Node 22 (solo para el frontend).

```powershell
docker compose up -d --wait db
docker compose exec db createdb -U dpec dpec_test

cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env      # y completar las credenciales

$env:TEST_DATABASE_URL = "postgresql://dpec:dpec@127.0.0.1:54329/dpec_test"
pytest                      # sin esa variable se omiten los tests de base de datos
ruff check .

alembic upgrade head
dpec cargar-historico       # una sola vez: arma el catálogo de zonas con unos 2000 títulos
dpec run
uvicorn scrapper_dpec.api:app --reload   # API en http://127.0.0.1:8000/docs
```

Los comandos se ejecutan desde `backend/`, que es donde se lee el archivo `.env`.

## Puesta en marcha

### 1. Email (Gmail)

1. Activar la [verificación en dos pasos](https://myaccount.google.com/security) de la cuenta.
2. Crear una [contraseña de aplicación](https://myaccount.google.com/apppasswords).
3. Completar `SMTP_USER` y `SMTP_PASSWORD` en `backend/.env` y probar: `dpec probar-email --para tu@email.com`

### 2. Base de datos (Supabase)

1. Crear un proyecto gratuito en [supabase.com](https://supabase.com).
2. Ir a **Connect** y copiar la cadena del **Session pooler**. La conexión directa solo funciona por IPv6, que GitHub Actions no soporta.
3. Ponerla en `DATABASE_URL` en `backend/.env` y aplicar las migraciones: `alembic upgrade head`
4. Cargar el catálogo y tu suscripción:

```powershell
dpec cargar-historico
dpec suscribir --nombre "Tu nombre" --email tu@email.com --clave "tu zona" --excluir "otra localidad"
```

`--clave` y `--excluir` se pueden repetir. Volver a ejecutar `suscribir` con el mismo email reemplaza los valores. El aviso se descarta solo si todas sus localidades están excluidas: ante la duda, se avisa.

Las migraciones activan Row Level Security en todas las tablas, para que la API pública de Supabase no pueda leer los datos.

### 3. GitHub Actions

En **Settings → Secrets and variables → Actions**, crear `DATABASE_URL`, `SMTP_USER` y `SMTP_PASSWORD`. Después, subir el código a `main` y ejecutar una vez **Actions → Scrape → Run workflow**.

Para recibir los avisos de fallos, revisar en **[Notifications](https://github.com/settings/notifications) → Actions** que estén activados los emails. Los de un workflow programado le llegan a quien modificó el `cron` por última vez.

## Limitaciones conocidas

- **"Zonas de influencia" es ambiguo:** si un corte te afecta pero el aviso no nombra tu zona, no se detecta. Conviene agregar como palabras clave los lugares vecinos que suelen salir junto al tuyo.
- **Demoras:** GitHub puede retrasar las ejecuciones programadas, a veces varios minutos.
- **Repos públicos:** GitHub desactiva los workflows programados tras 60 días sin actividad en el repo (y avisa antes), y los logs de Actions son visibles para cualquiera. Por eso el código nunca imprime emails ni palabras clave.
- **Datos personales:** para abrirlo a más gente hay que cumplir la Ley 25.326 (consentimiento, baja, política de privacidad) y verificar los emails en el alta.

## A futuro

- Canales: `WhatsAppNotifier`, `TelegramNotifier`.
- Frontend (`frontend/`, hoy solo una base con Vite y React): calendario de cortes, suscripción eligiendo del catálogo de zonas, historial y métricas. La API de solo lectura (`/cortes`, `/zonas`) ya existe, pero todavía no se despliega.
- Detectar cortes cancelados: los avisos que desaparecen de la lista antes de su fecha.
