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
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1003622058328")
WHATSAPP_PHONE   = os.environ.get("WHATSAPP_PHONE")
WHATSAPP_APIKEY  = os.environ.get("WHATSAPP_APIKEY")
GITHUB_TOKEN     = os.environ.get("GITHUB_TOKEN")        # Disponible automáticamente en Actions
GITHUB_REPO      = os.environ.get("GITHUB_REPOSITORY")   # ej: Alazoe/alerta-ia-latam
SEEN_FILE        = "seen_alerts.json"
MAP_DATA_FILE    = "docs/map_data.json"
MAX_AGE_DAYS     = 90

# ============================================================
# PAÍSES
# ============================================================
LATAM_COUNTRIES = [
    {"name": "Chile",            "es": "chile",               "coords": (-35.6751, -71.5430)},
    {"name": "Argentina",        "es": "argentina",           "coords": (-38.4161, -63.6167)},
    {"name": "Perú",             "es": "peru",                "coords": (-9.1900,  -75.0152)},
    {"name": "Brasil",           "es": "brasil",              "coords": (-14.2350, -51.9253)},
    {"name": "Colombia",         "es": "colombia",            "coords": (4.5709,   -74.2973)},
    {"name": "Ecuador",          "es": "ecuador",             "coords": (-1.8312,  -78.1834)},
    {"name": "Bolivia",          "es": "bolivia",             "coords": (-16.2902, -63.5887)},
    {"name": "Paraguay",         "es": "paraguay",            "coords": (-23.4425, -58.4438)},
    {"name": "Uruguay",          "es": "uruguay",             "coords": (-32.5228, -55.7658)},
    {"name": "Venezuela",        "es": "venezuela",           "coords": (6.4238,   -66.5897)},
    {"name": "Guyana",           "es": "guyana",              "coords": (4.8604,   -58.9302)},
    {"name": "Surinam",          "es": "surinam",             "coords": (3.9193,   -56.0278)},
    {"name": "México",           "es": "mexico",              "coords": (23.6345,  -102.5528)},
    {"name": "Guatemala",        "es": "guatemala",           "coords": (15.7835,  -90.2308)},
    {"name": "Honduras",         "es": "honduras",            "coords": (15.1999,  -86.2419)},
    {"name": "El Salvador",      "es": "el salvador",         "coords": (13.7942,  -88.8965)},
    {"name": "Nicaragua",        "es": "nicaragua",           "coords": (12.8654,  -85.2072)},
    {"name": "Costa Rica",       "es": "costa rica",          "coords": (9.7489,   -83.7534)},
    {"name": "Panamá",           "es": "panama",              "coords": (8.5380,   -80.7821)},
    {"name": "Cuba",             "es": "cuba",                "coords": (21.5218,  -77.7812)},
    {"name": "Rep. Dominicana",  "es": "republica dominicana","coords": (18.7357,  -70.1627)},
]

COUNTRY_COORDS    = {c["es"]: c["coords"] for c in LATAM_COUNTRIES}
COUNTRY_NAMES     = {c["es"]: c["name"]   for c in LATAM_COUNTRIES}
PRIORITY_COUNTRIES = {"chile", "argentina", "peru", "bolivia"}

# ============================================================
# KEYWORDS
# ============================================================
KEYWORDS_DISEASE = [
    "influenza aviar", "bird flu", "avian influenza",
    "H5N1", "H5N8", "H7N3", "H7N9", "HPAI", "IAAP",
    "influenza de alta patogenicidad"
]
KEYWORDS_EMERGENCIA = [
    "confirmado", "caso positivo", "brote activo", "foco declarado",
    "detectado en", "H5N1 en", "positivo en", "sacrificio de aves",
    "cuarentena sanitaria", "veda sanitaria", "foco confirmado",
    "confirmed", "positive case", "active outbreak", "depopulation"
]
KEYWORDS_ALERTA = [
    "brote", "foco", "outbreak", "positivo", "detectado",
    "sacrificio", "cuarentena", "eliminación de aves",
    "medidas sanitarias", "restricción", "sospecha confirmada",
    "muestra positiva", "hallazgo", "cull"
]

LEVEL_EMOJI = {"EMERGENCIA": "🔴", "ALERTA": "🟠", "VIGILANCIA": "🟡"}
LEVEL_COLOR = {"EMERGENCIA": "#dc2626", "ALERTA": "#ea580c", "VIGILANCIA": "#ca8a04"}
LEVEL_DESC  = {
    "EMERGENCIA": "Brote confirmado en país prioritario",
    "ALERTA":     "Brote o caso confirmado en Latinoamérica",
    "VIGILANCIA": "Noticia informativa / sin confirmación de brote"
}

def classify_alert(text, country):
    t = text.lower()
    has_emergencia = any(k.lower() in t for k in KEYWORDS_EMERGENCIA)
    has_alerta     = any(k.lower() in t for k in KEYWORDS_ALERTA)
    if has_emergencia and country in PRIORITY_COUNTRIES:
        return "EMERGENCIA"
    if has_emergencia or has_alerta:
        return "ALERTA"
    return "VIGILANCIA"

# ============================================================
# PERSISTENCIA seen_alerts.json via GitHub Releases
# ============================================================
RELEASE_TAG = "seen-data"

def _gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

def load_seen_remote():
    """Descarga seen_alerts.json desde GitHub Releases."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("Sin GitHub token/repo, usando seen local")
        return load_seen_local()
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{RELEASE_TAG}"
        r = requests.get(url, headers=_gh_headers(), timeout=15)
        if r.status_code != 200:
            print("No existe release de seen, empezando desde cero")
            return {}
        assets = r.json().get("assets", [])
        for asset in assets:
            if asset["name"] == "seen_alerts.json":
                dl = requests.get(asset["browser_download_url"], timeout=15)
                data = dl.json()
                print(f"seen_alerts.json cargado remotamente: {len(data)} entradas")
                return data
    except Exception as e:
        print(f"Error cargando seen remoto: {e}")
    return load_seen_local()

def save_seen_remote(seen):
    """Sube seen_alerts.json a GitHub Releases."""
    # Guardar local también como respaldo
    save_seen_local(seen)
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        base = f"https://api.github.com/repos/{GITHUB_REPO}"
        # Buscar o crear el release
        r = requests.get(f"{base}/releases/tags/{RELEASE_TAG}", headers=_gh_headers(), timeout=15)
        if r.status_code == 200:
            release_id = r.json()["id"]
            # Eliminar asset anterior si existe
            for asset in r.json().get("assets", []):
                if asset["name"] == "seen_alerts.json":
                    requests.delete(f"{base}/releases/assets/{asset['id']}", headers=_gh_headers(), timeout=15)
        else:
            # Crear el release
            payload = {"tag_name": RELEASE_TAG, "name": "Seen Data", "body": "Persistencia interna del bot", "draft": False, "prerelease": True}
            cr = requests.post(f"{base}/releases", headers=_gh_headers(), json=payload, timeout=15)
            release_id = cr.json()["id"]

        # Subir el archivo
        upload_url = f"https://uploads.github.com/repos/{GITHUB_REPO}/releases/{release_id}/assets?name=seen_alerts.json"
        headers_upload = {**_gh_headers(), "Content-Type": "application/json"}
        requests.post(upload_url, headers=headers_upload, data=json.dumps(seen), timeout=30)
        print(f"seen_alerts.json guardado remotamente: {len(seen)} entradas")
    except Exception as e:
        print(f"Error guardando seen remoto: {e}")

def load_seen_local():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except Exception:
            pass
    return {}

def save_seen_local(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=2)

# ============================================================
# MAP DATA
# ============================================================
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
    if not date_str:
        return True
    try:
        dt = parsedate_to_datetime(date_str).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        try:
            dt = datetime.fromisoformat(date_str[:10])
        except Exception:
            return True
    return dt >= datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)

def detect_country(text):
    text = text.lower()
    for c in LATAM_COUNTRIES:
        if c["es"] in text:
            return c["es"]
    return "unknown"

# ============================================================
# ENVÍO
# ============================================================
def send_telegram(message):
    if not TELEGRAM_TOKEN:
        print("⚠️  Sin TELEGRAM_TOKEN")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }, timeout=15)
        print(f"Telegram: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"Error Telegram: {e}")
        return False

def send_whatsapp(message):
    if not WHATSAPP_PHONE or not WHATSAPP_APIKEY:
        return False
    try:
        r = requests.get(
            f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={quote(message)}&apikey={WHATSAPP_APIKEY}",
            timeout=15
        )
        print(f"WhatsApp: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        print(f"Error WhatsApp: {e}")
        return False

# ============================================================
# FUENTES
# ============================================================
def build_sources():
    sources = [
        {"name": "WOAH/OIE",     "url": "https://wahis.woah.org/api/v1/public/event/filtered-events?pageNumber=0&pageSize=20&disease=Influenza+Aviar&status=Resolved,Ongoing", "type": "woah_api"},
        {"name": "SAG Chile",    "url": "https://www.sag.gob.cl/ambitos-de-accion/influenza-aviar",                      "type": "html_keywords", "country": "chile"},
        {"name": "SENASA Arg.",  "url": "https://www.argentina.gob.ar/senasa/programas-y-proyectos/influenza-aviar",     "type": "html_keywords", "country": "argentina"},
        {"name": "FAO EMPRES",   "url": "https://www.fao.org/ag/againfo/programmes/en/empres/news.html",                 "type": "html_keywords", "country": None},
    ]
    for c in LATAM_COUNTRIES:
        q = f"influenza+aviar+{c['es'].replace(' ', '+')}"
        sources.append({
            "name": f"Google News - {c['name']}",
            "url":  f"https://news.google.com/rss/search?q={q}&hl=es&gl=CL&ceid=CL:es",
            "type": "rss",
            "country": c["es"]
        })
    return sources

# ============================================================
# FETCHERS
# ============================================================
def fetch_rss(source, seen):
    alerts = []
    try:
        r    = requests.get(source["url"], timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:20]:
            title    = item.findtext("title", "")
            link     = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            desc     = item.findtext("description", "")
            full     = title + " " + desc
            if not is_recent(pub_date): continue
            if not any(k.lower() in full.lower() for k in KEYWORDS_DISEASE): continue
            h = make_hash(title + link)
            if h not in seen:
                seen[h] = True
                country = source.get("country") or detect_country(full)
                alerts.append({"source": source["name"], "title": title, "link": link,
                                "date": pub_date, "country": country, "level": classify_alert(full, country)})
    except Exception as e:
        print(f"Error RSS {source['name']}: {e}")
    return alerts

def fetch_html_keywords(source, seen):
    alerts = []
    try:
        r    = requests.get(source["url"], timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        full = r.text
        if any(k.lower() in full.lower() for k in KEYWORDS_DISEASE):
            h = make_hash(source["url"] + full[:500])
            if h not in seen:
                seen[h] = True
                country = source.get("country") or detect_country(full)
                alerts.append({"source": source["name"], "title": f"Actualización en {source['name']}",
                                "link": source["url"], "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "country": country, "level": classify_alert(full, country)})
    except Exception as e:
        print(f"Error HTML {source['name']}: {e}")
    return alerts

def fetch_woah_api(source, seen):
    alerts = []
    try:
        r = requests.get(source["url"], timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200: return []
        events = r.json().get("data", {}).get("content", [])
        for event in events[:30]:
            country_raw = str(event.get("country", {}).get("name", "")).lower()
            disease     = str(event.get("disease", {}).get("name", "")).lower()
            event_id    = str(event.get("id", ""))
            report_date = event.get("reportDate", "")
            if not is_recent(report_date): continue
            matched = next((c["es"] for c in LATAM_COUNTRIES if c["es"] in country_raw), None)
            if matched:
                h = make_hash(event_id + country_raw)
                if h not in seen:
                    seen[h] = True
                    level = "EMERGENCIA" if matched in PRIORITY_COUNTRIES else "ALERTA"
                    alerts.append({"source": source["name"],
                                   "title": f"Evento WOAH: {disease.upper()} en {COUNTRY_NAMES.get(matched, matched.title())}",
                                   "link": "https://wahis.woah.org/#/event-management",
                                   "date": report_date, "country": matched, "level": level})
    except Exception as e:
        print(f"Error WOAH: {e}")
    return alerts

# ============================================================
# FORMATO MENSAJES
# ============================================================
def format_alert_message(alerts):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    groups = {"EMERGENCIA": [], "ALERTA": [], "VIGILANCIA": []}
    for a in alerts:
        groups[a["level"]].append(a)

    msg = f"🦅 *MONITOREO INFLUENZA AVIAR*\n📅 {now} UTC\n━━━━━━━━━━━━━━━━━━\n\n"

    for level in ["EMERGENCIA", "ALERTA", "VIGILANCIA"]:
        items = groups[level]
        if not items: continue
        msg += f"{LEVEL_EMOJI[level]} *{level}* — _{LEVEL_DESC[level]}_\n\n"
        for a in items:
            cname = COUNTRY_NAMES.get(a.get("country",""), a.get("country","").title())
            msg += f"📌 *{a['title']}*\n"
            msg += f"🗓 {a.get('date','')} | 📍 {cname}\n"
            msg += f"🔗 {a.get('link','')}\n"
            msg += f"_Fuente: {a['source']}_\n\n"

    msg += f"━━━━━━━━━━━━━━━━━━\n🌎 @AlertaIALatam | 🗺 https://alazoe.github.io/alerta-ia-latam"
    return msg

def format_weekly_summary(map_data):
    """Resumen semanal por país para Telegram."""
    cutoff  = datetime.utcnow() - timedelta(days=7)
    weekly  = []
    for a in map_data.get("alerts", []):
        try:
            dt = datetime.fromisoformat(a["date"][:10])
            if dt >= cutoff:
                weekly.append(a)
        except Exception:
            pass

    now = datetime.now().strftime("%d/%m/%Y")
    msg = f"📊 *RESUMEN SEMANAL — {now}*\n"
    msg += f"🦅 Influenza Aviar en Latinoamérica\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n\n"

    if not weekly:
        msg += "✅ Sin eventos registrados esta semana.\n\n"
    else:
        # Agrupar por país
        by_country = {}
        for a in weekly:
            c = a.get("country", "Desconocido")
            if c not in by_country:
                by_country[c] = {"EMERGENCIA": 0, "ALERTA": 0, "VIGILANCIA": 0, "titles": []}
            by_country[c][a.get("level","VIGILANCIA")] += 1
            by_country[c]["titles"].append(a["title"])

        # Ordenar: primero países con emergencia, luego alerta, luego vigilancia
        def sort_key(item):
            v = item[1]
            return (-v["EMERGENCIA"], -v["ALERTA"], -v["VIGILANCIA"])

        for country, data in sorted(by_country.items(), key=sort_key):
            total = data["EMERGENCIA"] + data["ALERTA"] + data["VIGILANCIA"]
            msg += f"📍 *{country}* — {total} evento(s)\n"
            if data["EMERGENCIA"]: msg += f"   🔴 Emergencia: {data['EMERGENCIA']}\n"
            if data["ALERTA"]:     msg += f"   🟠 Alerta: {data['ALERTA']}\n"
            if data["VIGILANCIA"]: msg += f"   🟡 Vigilancia: {data['VIGILANCIA']}\n"
            msg += "\n"

    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"🗺 https://alazoe.github.io/alerta-ia-latam\n"
    msg += f"🌎 @AlertaIALatam"
    return msg

# ============================================================
# MAPA
# ============================================================
def update_map_data(alerts):
    map_data     = load_map_data()
    existing_ids = {a.get("id") for a in map_data["alerts"]}

    for alert in alerts:
        alert_id = make_hash(alert["title"] + alert.get("link",""))
        if alert_id not in existing_ids:
            country = alert.get("country","unknown")
            coords  = COUNTRY_COORDS.get(country)
            if coords:
                # Normalizar fecha a ISO para el mapa
                date_str = alert.get("date","")
                try:
                    dt_iso = parsedate_to_datetime(date_str).strftime("%Y-%m-%d")
                except Exception:
                    dt_iso = date_str[:10] if date_str else datetime.now().strftime("%Y-%m-%d")

                map_data["alerts"].append({
                    "id":      alert_id,
                    "title":   alert["title"],
                    "source":  alert["source"],
                    "date":    dt_iso,
                    "country": COUNTRY_NAMES.get(country, country.title()),
                    "lat":     coords[0],
                    "lng":     coords[1],
                    "link":    alert.get("link",""),
                    "level":   alert.get("level","VIGILANCIA"),
                    "color":   LEVEL_COLOR.get(alert.get("level","VIGILANCIA"), "#ca8a04")
                })

    # Limpiar entradas viejas
    cutoff = datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)
    map_data["alerts"] = [
        a for a in map_data["alerts"]
        if _date_ok(a.get("date",""), cutoff)
    ][-300:]
    map_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    save_map_data(map_data)
    print(f"Mapa: {len(map_data['alerts'])} eventos")
    return map_data

def _date_ok(date_str, cutoff):
    try:
        return datetime.fromisoformat(date_str[:10]) >= cutoff
    except Exception:
        return True

# ============================================================
# MAIN
# ============================================================
def main():
    print(f"=== Monitoreo: {datetime.now()} ===")

    seen       = load_seen_remote()
    all_alerts = []

    for source in build_sources():
        print(f"Revisando: {source['name']}")
        if   source["type"] == "rss":           alerts = fetch_rss(source, seen)
        elif source["type"] == "woah_api":       alerts = fetch_woah_api(source, seen)
        else:                                    alerts = fetch_html_keywords(source, seen)
        all_alerts.extend(alerts)
        if alerts:
            levels = ', '.join(set(a['level'] for a in alerts))
            print(f"  → {len(alerts)} alertas [{levels}]")

    save_seen_remote(seen)
    map_data = update_map_data(all_alerts)

    now_utc = datetime.utcnow()

    # ── Resumen semanal: lunes a las 11 UTC (8 AM Chile)
    if now_utc.weekday() == 0 and now_utc.hour == 11:
        weekly_msg = format_weekly_summary(map_data)
        send_telegram(weekly_msg)
        send_whatsapp(weekly_msg)
        print("✅ Resumen semanal enviado")

    if all_alerts:
        # Mensaje urgente si hay emergencias
        emergencias = [a for a in all_alerts if a["level"] == "EMERGENCIA"]
        if emergencias:
            msg = "🔴 *EMERGENCIA — ACCIÓN INMEDIATA*\n\n"
            for a in emergencias:
                cname = COUNTRY_NAMES.get(a.get("country",""), "")
                msg  += f"⚠️ *{a['title']}*\n📍 {cname}\n🔗 {a.get('link','')}\n\n"
            msg += "@AlertaIALatam"
            send_telegram(msg)
            send_whatsapp(msg)

        # Enviar en grupos de 5
        for i in range(0, len(all_alerts), 5):
            send_telegram(format_alert_message(all_alerts[i:i+5]))
            send_whatsapp(format_alert_message(all_alerts[i:i+5]))
        print(f"✅ {len(all_alerts)} alertas enviadas")

    elif now_utc.hour == 11 and now_utc.weekday() != 0:
        # Resumen diario solo si no es lunes (lunes ya mandamos el semanal)
        msg = (f"✅ *Resumen diario — {now_utc.strftime('%d/%m/%Y')}*\n\n"
               f"Sin nuevos eventos en Latinoamérica.\n\n"
               f"🌎 @AlertaIALatam | 🗺 https://alazoe.github.io/alerta-ia-latam")
        send_telegram(msg)
        print("✅ Resumen diario enviado")
    else:
        print("Sin nuevas alertas.")

if __name__ == "__main__":
    main()
