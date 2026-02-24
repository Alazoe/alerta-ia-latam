import requests
import json
import os
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

# ============================================================
# CONFIGURACIÓN
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1003622058328")
WHATSAPP_PHONE = os.environ.get("WHATSAPP_PHONE")
WHATSAPP_APIKEY = os.environ.get("WHATSAPP_APIKEY")
SEEN_FILE = "seen_alerts.json"
MAP_DATA_FILE = "docs/map_data.json"
MAX_AGE_DAYS = 90  # Solo noticias de los últimos 3 meses

# ============================================================
# PAÍSES - búsqueda dedicada por cada uno
# ============================================================
LATAM_COUNTRIES = [
    # Sudamérica
    {"name": "Chile",      "es": "chile",      "coords": (-35.6751, -71.5430)},
    {"name": "Argentina",  "es": "argentina",  "coords": (-38.4161, -63.6167)},
    {"name": "Perú",       "es": "peru",        "coords": (-9.1900,  -75.0152)},
    {"name": "Brasil",     "es": "brasil",      "coords": (-14.2350, -51.9253)},
    {"name": "Colombia",   "es": "colombia",    "coords": (4.5709,   -74.2973)},
    {"name": "Ecuador",    "es": "ecuador",     "coords": (-1.8312,  -78.1834)},
    {"name": "Bolivia",    "es": "bolivia",     "coords": (-16.2902, -63.5887)},
    {"name": "Paraguay",   "es": "paraguay",    "coords": (-23.4425, -58.4438)},
    {"name": "Uruguay",    "es": "uruguay",     "coords": (-32.5228, -55.7658)},
    {"name": "Venezuela",  "es": "venezuela",   "coords": (6.4238,   -66.5897)},
    {"name": "Guyana",     "es": "guyana",      "coords": (4.8604,   -58.9302)},
    {"name": "Surinam",    "es": "surinam",     "coords": (3.9193,   -56.0278)},
    # Centroamérica y México
    {"name": "México",     "es": "mexico",      "coords": (23.6345,  -102.5528)},
    {"name": "Guatemala",  "es": "guatemala",   "coords": (15.7835,  -90.2308)},
    {"name": "Honduras",   "es": "honduras",    "coords": (15.1999,  -86.2419)},
    {"name": "El Salvador","es": "el salvador", "coords": (13.7942,  -88.8965)},
    {"name": "Nicaragua",  "es": "nicaragua",   "coords": (12.8654,  -85.2072)},
    {"name": "Costa Rica", "es": "costa rica",  "coords": (9.7489,   -83.7534)},
    {"name": "Panamá",     "es": "panama",      "coords": (8.5380,   -80.7821)},
    {"name": "Cuba",       "es": "cuba",        "coords": (21.5218,  -77.7812)},
    {"name": "Rep. Dominicana","es": "republica dominicana","coords": (18.7357, -70.1627)},
]

COUNTRY_COORDS = {c["es"]: c["coords"] for c in LATAM_COUNTRIES}
COUNTRY_NAMES  = {c["es"]: c["name"]   for c in LATAM_COUNTRIES}

# ============================================================
# FUENTES BASE
# ============================================================
def build_sources():
    sources = [
        {
            "name": "WOAH/OIE",
            "url": "https://wahis.woah.org/api/v1/public/event/filtered-events?pageNumber=0&pageSize=20&disease=Influenza+Aviar&status=Resolved,Ongoing",
            "type": "woah_api"
        },
        {
            "name": "SAG Chile",
            "url": "https://www.sag.gob.cl/ambitos-de-accion/influenza-aviar",
            "type": "html_keywords",
            "country": "chile"
        },
        {
            "name": "SENASA Argentina",
            "url": "https://www.argentina.gob.ar/senasa/programas-y-proyectos/influenza-aviar",
            "type": "html_keywords",
            "country": "argentina"
        },
        {
            "name": "FAO EMPRES",
            "url": "https://www.fao.org/ag/againfo/programmes/en/empres/news.html",
            "type": "html_keywords",
            "country": None
        },
    ]
    # Búsqueda dedicada por país en Google News
    for country in LATAM_COUNTRIES:
        q = f"influenza+aviar+{country['es'].replace(' ', '+')}"
        sources.append({
            "name": f"Google News - {country['name']}",
            "url": f"https://news.google.com/rss/search?q={q}&hl=es&gl=CL&ceid=CL:es",
            "type": "rss",
            "country": country["es"]
        })
    return sources

KEYWORDS = [
    "influenza aviar", "bird flu", "avian influenza",
    "H5N1", "H5N8", "H7N3", "H7N9", "HPAI", "IAAP",
    "brote", "outbreak", "foco", "confirmado", "alerta",
    "influenza de alta patogenicidad"
]

# ============================================================
# UTILIDADES
# ============================================================
def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except Exception:
            pass
    return {}

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=2)

def load_map_data():
    if os.path.exists(MAP_DATA_FILE):
        try:
            with open(MAP_DATA_FILE, "r") as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except Exception:
            pass
    return {"alerts": [], "last_updated": ""}

def save_map_data(data):
    os.makedirs("docs", exist_ok=True)
    with open(MAP_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def make_hash(text):
    return hashlib.md5(text.encode()).hexdigest()

def is_recent(date_str):
    """Retorna True si la fecha está dentro de los últimos 90 días."""
    if not date_str:
        return True  # Si no hay fecha, incluir de todas formas
    try:
        # Intentar parsear fecha RSS (RFC 2822)
        dt = parsedate_to_datetime(date_str)
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        try:
            # Intentar formato ISO
            dt = datetime.fromisoformat(date_str[:10])
        except Exception:
            return True
    cutoff = datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)
    return dt >= cutoff

# ============================================================
# ENVÍO DE MENSAJES
# ============================================================
def send_telegram(message):
    if not TELEGRAM_TOKEN:
        print("⚠️  Sin TELEGRAM_TOKEN configurado")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        print(f"Telegram: {r.status_code} - {r.text[:200]}")
        return r.status_code == 200
    except Exception as e:
        print(f"Error Telegram: {e}")
        return False

def send_whatsapp(message):
    if not WHATSAPP_PHONE or not WHATSAPP_APIKEY:
        return False
    encoded = quote(message)
    url = f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={encoded}&apikey={WHATSAPP_APIKEY}"
    try:
        r = requests.get(url, timeout=15)
        print(f"WhatsApp: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"Error WhatsApp: {e}")
        return False

# ============================================================
# FETCHERS
# ============================================================
def detect_country(text):
    text = text.lower()
    for country in LATAM_COUNTRIES:
        if country["es"] in text:
            return country["es"]
    return "unknown"

def fetch_rss(source, seen):
    alerts = []
    url = source["url"]
    source_name = source["name"]
    forced_country = source.get("country")
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:20]:
            title       = item.findtext("title", "")
            link        = item.findtext("link", "")
            pub_date    = item.findtext("pubDate", "")
            description = item.findtext("description", "")
            content     = (title + " " + description).lower()

            # Filtro por fecha
            if not is_recent(pub_date):
                continue

            has_disease = any(k.lower() in content for k in KEYWORDS)
            if not has_disease:
                continue

            h = make_hash(title + link)
            if h not in seen:
                seen[h] = True
                country = forced_country or detect_country(content)
                alerts.append({
                    "source": source_name,
                    "title": title,
                    "link": link,
                    "date": pub_date,
                    "country": country
                })
    except Exception as e:
        print(f"Error RSS {source_name}: {e}")
    return alerts

def fetch_html_keywords(source, seen):
    alerts = []
    url = source["url"]
    source_name = source["name"]
    forced_country = source.get("country")
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        content = r.text.lower()
        has_disease = any(k.lower() in content for k in KEYWORDS)
        if has_disease:
            h = make_hash(url + r.text[:500])
            if h not in seen:
                seen[h] = True
                country = forced_country or detect_country(content)
                alerts.append({
                    "source": source_name,
                    "title": f"Actualización detectada en {source_name}",
                    "link": url,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "country": country
                })
    except Exception as e:
        print(f"Error HTML {source_name}: {e}")
    return alerts

def fetch_woah_api(source, seen):
    alerts = []
    url = source["url"]
    source_name = source["name"]
    latam_keys = list(COUNTRY_COORDS.keys())
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        data = r.json()
        events = data.get("data", {}).get("content", []) if isinstance(data, dict) else []
        for event in events[:30]:
            country_raw = str(event.get("country", {}).get("name", "")).lower()
            disease     = str(event.get("disease", {}).get("name", "")).lower()
            event_id    = str(event.get("id", ""))
            report_date = event.get("reportDate", "")

            if not is_recent(report_date):
                continue

            matched = next((c for c in latam_keys if c in country_raw), None)
            if matched:
                h = make_hash(event_id + country_raw + disease)
                if h not in seen:
                    seen[h] = True
                    alerts.append({
                        "source": source_name,
                        "title": f"Evento oficial WOAH: {disease.upper()} en {COUNTRY_NAMES.get(matched, matched.title())}",
                        "link": "https://wahis.woah.org/#/event-management",
                        "date": report_date,
                        "country": matched
                    })
    except Exception as e:
        print(f"Error WOAH API: {e}")
    return alerts

# ============================================================
# FORMATO MENSAJES
# ============================================================
def format_telegram_alert(alerts):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    msg = f"🚨 *ALERTA INFLUENZA AVIAR* 🦅\n"
    msg += f"📅 {now} UTC\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n\n"
    for i, a in enumerate(alerts, 1):
        country_name = COUNTRY_NAMES.get(a.get("country",""), a.get("country","").title())
        msg += f"*{i}. {a['source']}*\n"
        msg += f"📌 {a['title']}\n"
        if a.get("date"):
            msg += f"🗓 {a['date']}\n"
        if country_name and country_name != "Unknown":
            msg += f"📍 {country_name}\n"
        if a.get("link"):
            msg += f"🔗 {a['link']}\n"
        msg += "\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"🌎 @AlertaIALatam | 🗺 https://alazoe.github.io/alerta-ia-latam"
    return msg

def format_daily_summary():
    now = datetime.now().strftime("%d/%m/%Y")
    return (f"✅ *Resumen diario - {now}*\n\n"
            f"Sin nuevos eventos de Influenza Aviar detectados en Latinoamérica.\n\n"
            f"Países monitoreados: Chile, Argentina, Uruguay, Perú, Brasil, Colombia, "
            f"Ecuador, Bolivia, Paraguay, Venezuela, México, Guatemala, Honduras, "
            f"El Salvador, Nicaragua, Costa Rica, Panamá, Cuba y más.\n\n"
            f"🌎 @AlertaIALatam | 🗺 https://alazoe.github.io/alerta-ia-latam")

# ============================================================
# ACTUALIZAR MAPA
# ============================================================
def update_map_data(alerts):
    map_data = load_map_data()
    existing_ids = {a.get("id") for a in map_data["alerts"]}

    for alert in alerts:
        alert_id = make_hash(alert["title"] + alert.get("link", ""))
        if alert_id not in existing_ids:
            country = alert.get("country", "unknown")
            coords  = COUNTRY_COORDS.get(country)
            if coords:
                map_data["alerts"].append({
                    "id":      alert_id,
                    "title":   alert["title"],
                    "source":  alert["source"],
                    "date":    alert.get("date", ""),
                    "country": COUNTRY_NAMES.get(country, country.title()),
                    "lat":     coords[0],
                    "lng":     coords[1],
                    "link":    alert.get("link", "")
                })

    # Conservar solo eventos de los últimos 90 días
    cutoff = datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)
    def entry_is_recent(entry):
        try:
            dt = datetime.fromisoformat(entry["date"][:10])
            return dt >= cutoff
        except Exception:
            return True

    map_data["alerts"] = [a for a in map_data["alerts"] if entry_is_recent(a)]
    map_data["alerts"] = map_data["alerts"][-200:]
    map_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    save_map_data(map_data)
    print(f"Mapa actualizado: {len(map_data['alerts'])} eventos")

# ============================================================
# MAIN
# ============================================================
def main():
    print(f"=== Monitoreo: {datetime.now()} ===")
    seen = load_seen()
    all_alerts = []

    for source in build_sources():
        print(f"Revisando: {source['name']}")
        if source["type"] == "rss":
            alerts = fetch_rss(source, seen)
        elif source["type"] == "woah_api":
            alerts = fetch_woah_api(source, seen)
        else:
            alerts = fetch_html_keywords(source, seen)
        all_alerts.extend(alerts)
        if alerts:
            print(f"  → {len(alerts)} nuevas alertas")

    save_seen(seen)

    if all_alerts:
        update_map_data(all_alerts)
        for i in range(0, len(all_alerts), 5):
            batch   = all_alerts[i:i+5]
            message = format_telegram_alert(batch)
            send_telegram(message)
            send_whatsapp(message)
        print(f"✅ {len(all_alerts)} alertas enviadas")
    else:
        update_map_data([])
        current_hour = datetime.utcnow().hour
        if current_hour == 11:
            send_telegram(format_daily_summary())
            print("✅ Resumen diario enviado")
        else:
            print("Sin nuevas alertas.")

if __name__ == "__main__":
    main()
