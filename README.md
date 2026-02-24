# 🦅 Alerta Influenza Aviar – Latinoamérica

Bot público de monitoreo de Influenza Aviar para Latinoamérica.
Canal Telegram: @AlertaIALatam

## Archivos
- `monitor.py` → Script principal de monitoreo
- `.github/workflows/monitor.yml` → Automatización horaria
- `docs/index.html` → Mapa web público
- `docs/map_data.json` → Datos del mapa (generado automáticamente)

## Configuración en GitHub

### Secrets necesarios (Settings → Secrets → Actions)
| Secret | Valor |
|--------|-------|
| `TELEGRAM_TOKEN` | Token de @BotFather |
| `TELEGRAM_CHAT_ID` | `-1003622058328` |
| `WHATSAPP_PHONE` | Tu número con código país |
| `WHATSAPP_APIKEY` | Tu API key de CallMeBot |

### Activar GitHub Pages
- Settings → Pages → Source: **Deploy from branch**
- Branch: `main` / Folder: `/docs`
- Tu mapa quedará en: `https://TU_USUARIO.github.io/alerta-ia-latam`

## Cómo funciona
1. GitHub Actions corre el script cada hora
2. El script revisa WOAH, SAG, SENASA, PAHO, FAO y Google News
3. Si detecta algo nuevo → publica en Telegram y actualiza el mapa
4. El mapa web se actualiza automáticamente en GitHub Pages
