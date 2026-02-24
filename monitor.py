import requests
import json
import os
import hashlib
from datetime import datetime
from urllib.parse import quote
import xml.etree.ElementTree as ET

# ============================================================
# CONFIGURACIÓN
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1003622058328")
WHATSAPP_PHONE = os.environ.get("WHATSAPP_PHONE")
WHATSAPP_APIKEY = os.environ.get("WHATSAPP_APIKEY")
SEEN_FILE = "seen_alerts.json"
MAP_DATA_FILE = "docs/map_data.json"

# ============================================================
# FUENTES
# ============================================================
SOURCES = [
    {
        "name": "WOAH/OIE",
        "url": "https://wahis.woah.org/api/v1/public/event/filtered-events?pageNumber=0&pageSize=20&disease=Influenza+Aviar&status=Resolved,Ongoing",
        "type": "woah_api"
    },
    {
        "name": "SAG Chile",
        "url": "https://www.sag.gob.cl/ambitos-de-accion/influenza-aviar",
        "type": "html_keywords"
    },
    {
        "name": "SENASA Argentina",
        "url": "https://www.argentina.gob.ar/senasa/programas-y-proyectos/influenza-aviar",
        "type": "html_keywords"
    },
    {
        "name": "PANAFTOSA/PAHO",
        "url": "https://panaftosa.paho.org/es/noticias",
        "type": "html_keywords"
    },
    {
        "name": "Google News ES",
        "url": "https://news.google.com/rss/search?q=influenza+aviar+latinoamerica+OR+chile+OR+argentina+OR+peru+OR+brasil+OR+colombia&hl=es&gl=CL&ceid=CL:es",
        "type": "rss"
    },
    {
        "name": "Google News EN",
        "url": "https://news.google.com/rss/search?q=bird+flu+avian+influenza+south+america+latin+america&hl=en&gl=US&ceid=US:en",
        "type": "rss"
    },
    {
        "name": "FAO EMPRES",
        "url": "https://www.fao.org/ag/againfo/programmes/en/empres/news.html",
        "type": "html_keywords"
    }
]

KEYWORDS = [
    "influenza aviar", "bird flu", "avian influenza", "H5N1", "H5N8", "H7N9",
    "HPAI", "brote", "outbreak", "foco", "confirmado", "alert", "alerta"
]

LATAM_KEYWORDS = [
    "chile", "argentina", "perú", "peru", "brasil", "brazil", "colombia",
    "ecuador", "bolivia", "paraguay", "uruguay", "venezuela", "mexico",
    "méxico", "latinoamerica", "latin america", "south america", "sudamerica"
]

# Coordenadas aproximadas de países para el mapa
COUNTRY_COORDS = {
    "chile": (-35.6751, -71.5430),
    "argentina": (-38.4161, -63.6167),
    "peru": (-9.1900, -75.0152),
    "brasil": (-14.2350, -51.9253),
    "brazil": (-14.2350, -51.9253),
    "colombia": (4.5709, -74.2973),
    "ecuador": (-1.8312, -78.1834),
    "bolivia": (-16.2902, -63.5887),
    "paraguay": (-23.4425, -58.4438),
    "uruguay": (-32.5228, -55.7658),
    "venezuela": (6.4238, -66.5897),
    "mexico": (23.6345, -102.5528),
    "méxico": (23.6345, -102.5528),
}

# ============================================================
# UTILIDADES
# ============================================================
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return json.load(f)
    return {}

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=2)

def load_map_data():
    if os.path.exists(MAP_DATA_FILE):
        with open(MAP_DATA_FILE, "r") as f:
            return json.load(f)
    return {"alerts": [], "last_updated": ""}

def save_map_data(data):
    os.makedirs("docs", exist_ok=True)
    with open(MAP_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def make_hash(text):
    return hashlib.md5(text.encode()).hexdigest()

# ============================================================
# ENVÍO DE MENSAJES
# ============================================================
def send_telegram(message):
    if not TELEGRAM_TOKEN:
        print("Sin token Telegram")
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
        print(f"Telegram: {r.status_code}")
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
def fetch_rss(url, source_name, seen):
    alerts = []
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:15]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            description = item.findtext("description", "")
            content = (title + " " + description).lower()
            has_disease = any(k.lower() in content for k in KEYWORDS)
            has_latam = any(k.lower() in content for k in LATAM_KEYWORDS)
            if has_disease and has_latam:
                h = make_hash(title + link)
                if h not in seen:
                    seen[h] = True
                    country = detect_country(content)
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

def fetch_html_keywords(url, source_name, seen):
    alerts = []
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        content = r.text.lower()
        has_disease = any(k.lower() in content for k in KEYWORDS)
        has_latam = any(k.lower() in content for k in LATAM_KEYWORDS) or "chile" in url or "argentina" in url
        if has_disease and has_latam:
            h = make_hash(url + r.text[:500])
            if h not in seen:
                seen[h] = True
                country = detect_country(content)
                if "chile" in url:
                    country = "chile"
                elif "argentina" in url:
                    country = "argentina"
                alerts.append({
                    "source": source_name,
                    "title": f"Actualización en {source_name}",
                    "link": url,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "country": country
                })
    except Exception as e:
        print(f"Error HTML {source_name}: {e}")
    return alerts

def fetch_woah_api(url, source_name, seen):
    alerts = []
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return fetch_html_keywords("https://wahis.woah.org", source_name, seen)
        data = r.json()
        events = data.get("data", {}).get("content", []) if isinstance(data, dict) else []
        latam_countries = list(COUNTRY_COORDS.keys())
        for event in events[:20]:
            country = str(event.get("country", {}).get("name", "")).lower()
            disease = str(event.get("disease", {}).get("name", "")).lower()
            event_id = str(event.get("id", ""))
            if any(c in country for c in latam_countries):
                h = make_hash(event_id + country + disease)
                if h not in seen:
                    seen[h] = True
                    alerts.append({
                        "source": source_name,
                        "title": f"Evento oficial: {disease.upper()} en {country.title()}",
                        "link": "https://wahis.woah.org/#/event-management",
                        "date": event.get("reportDate", datetime.now().strftime("%Y-%m-%d")),
                        "country": country
                    })
    except Exception as e:
        print(f"Error WOAH API: {e}")
    return alerts

def detect_country(text):
    for country in COUNTRY_COORDS:
        if country in text:
            return country
    return "unknown"

# ============================================================
# FORMATO DE MENSAJES
# ============================================================
def format_telegram_alert(alerts):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    msg = f"🚨 *ALERTA INFLUENZA AVIAR* 🦅\n"
    msg += f"📅 {now} (UTC)\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n\n"
    for i, a in enumerate(alerts, 1):
        msg += f"*{i}. {a['source']}*\n"
        msg += f"📌 {a['title']}\n"
        if a.get('date'):
            msg += f"🗓 {a['date']}\n"
        if a.get('country') and a['country'] != 'unknown':
            msg += f"📍 {a['country'].title()}\n"
        if a.get('link'):
            msg += f"🔗 {a['link']}\n"
        msg += "\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"🌎 Canal: @AlertaIALatam\n"
    msg += f"🗺 Mapa: https://TU_USUARIO.github.io/alerta-ia-latam"
    return msg

def format_daily_summary():
    now = datetime.now().strftime("%d/%m/%Y")
    return (f"✅ *Resumen diario - {now}*\n\n"
            f"Sin nuevos eventos de Influenza Aviar detectados en Latinoamérica en las últimas 24 horas.\n\n"
            f"Fuentes monitoreadas:\n"
            f"• WOAH/OIE\n• SAG Chile\n• SENASA Argentina\n"
            f"• PANAFTOSA/PAHO\n• FAO EMPRES\n• Google News\n\n"
            f"🌎 Canal: @AlertaIALatam")

# ============================================================
# ACTUALIZAR DATOS DEL MAPA
# ============================================================
def update_map_data(alerts):
    map_data = load_map_data()
    existing_ids = {a.get("id") for a in map_data["alerts"]}
    
    for alert in alerts:
        alert_id = make_hash(alert["title"] + alert.get("link", ""))
        if alert_id not in existing_ids:
            country = alert.get("country", "unknown")
            coords = COUNTRY_COORDS.get(country, None)
            if coords:
                map_data["alerts"].append({
                    "id": alert_id,
                    "title": alert["title"],
                    "source": alert["source"],
                    "date": alert.get("date", ""),
                    "country": country.title(),
                    "lat": coords[0],
                    "lng": coords[1],
                    "link": alert.get("link", "")
                })
    
    # Mantener solo los últimos 100 eventos
    map_data["alerts"] = map_data["alerts"][-100:]
    map_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    save_map_data(map_data)
    print(f"Mapa actualizado: {len(map_data['alerts'])} eventos totales")

# ============================================================
# MAIN
# ============================================================
def main():
    print(f"=== Monitoreo: {datetime.now()} ===")
    seen = load_seen()
    all_alerts = []

    for source in SOURCES:
        print(f"Revisando: {source['name']}")
        if source["type"] == "rss":
            alerts = fetch_rss(source["url"], source["name"], seen)
        elif source["type"] == "woah_api":
            alerts = fetch_woah_api(source["url"], source["name"], seen)
        else:
            alerts = fetch_html_keywords(source["url"], source["name"], seen)
        all_alerts.extend(alerts)
        if alerts:
            print(f"  → {len(alerts)} nuevas alertas")

    save_seen(seen)

    if all_alerts:
        update_map_data(all_alerts)
        for i in range(0, len(all_alerts), 5):
            batch = all_alerts[i:i+5]
            message = format_telegram_alert(batch)
            send_telegram(message)
            send_whatsapp(message)
        print(f"✅ {len(all_alerts)} alertas enviadas")
    else:
        update_map_data([])
        current_hour = datetime.utcnow().hour
        if current_hour == 11:  # 8 AM Chile
            send_telegram(format_daily_summary())
            print("✅ Resumen diario enviado")
        else:
            print("Sin nuevas alertas.")

if __name__ == "__main__":
    main()
