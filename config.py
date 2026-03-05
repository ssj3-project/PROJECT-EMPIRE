'''
config.py — constantes globales du bot Dokkan Battle.

Valeurs exactes issues des traces réseau :
  - bundle_id   : com.bandainamcogames.dbzdokkanww (GLOBAL)
  - gb_code     : format "VERSION-SHA256" (ex: 5.33.5-7cdd55...)
  - device      : Google sdk_gphone64_x86_64 Android 16 (émulateur officiel)
  - Hosts       : lus depuis gb-host.txt / jp-host.txt, fallback aktsk.com
'''

# ── Bundle IDs ────────────────────────────────────────────────────────────────
bundle_id    = 'com.bandainamcogames.dbzdokkanww'       # GLOBAL
bundle_id_jp = 'jp.co.bandainamcogames.BNGI0211'        # JP (vu dans binaire)

# ── Hosts ─────────────────────────────────────────────────────────────────────
def _read_host(filename, fallback_host, fallback_port):
    try:
        line  = open(filename).readline().strip()
        parts = line.split(':')
        return parts[0], (parts[1] if len(parts) > 1 else fallback_port)
    except Exception:
        return fallback_host, fallback_port

_gb_host, gb_port = _read_host('gb-host.txt', 'ishin-global.aktsk.com',    '443')
_jp_host, jp_port = _read_host('jp-host.txt', 'ishin-production.aktsk.jp', '443')

gb_url = 'https://' + _gb_host
jp_url = 'https://' + _jp_host

# ── Version codes ─────────────────────────────────────────────────────────────
gb_code = '5.33.5-7cdd55f48d639e6452f5595028bbad1fc4dec050b012e2a966aa451821f228c6'
jp_code = '5.33.5-7cdd55f48d639e6452f5595028bbad1fc4dec050b012e2a966aa451821f228c6'

# ── Asset / DB versions ───────────────────────────────────────────────────────
file_ts1 = '1772085610'
db_ts1   = '1772104803'
file_ts2 = ''
db_ts2   = ''

# ── Locale ────────────────────────────────────────────────────────────────────
lang     = 'en'
country  = 'US'
currency = 'USD'

# ── Device Android ────────────────────────────────────────────────────────────
device_name1  = 'Google'
device_model1 = 'sdk_gphone64_x86_64'
device_ver1   = '12'
device_agent1 = 'Dalvik/2.1.0 (Linux; U; Android 12; sdk_gphone64_x86_64 Build/SE1A.220826.008)'
graphics_api1     = 'vulkan1.1.0,gles3.1'
os_architecture1  = 'x86_64,arm64-v8a'
is_usable_astc1   = True

# ── Device iOS ────────────────────────────────────────────────────────────────
device_name2  = 'iPhone'
device_model2 = 'iPhone XR'
device_ver2   = '13.0'
device_agent2 = 'CFNetwork/808.3 Darwin/16.3.0 (iPhone; CPU iPhone OS 13_0 like Mac OS X)'

# ── SUPPRIMÉ : ad / uuid ne sont plus des globaux partagés ───────────────────
# Ces variables causaient des conflits multi-utilisateurs :
# quand l'user A faisait !create, ses IDs écrasaient ceux de l'user B.
# Chaque DokkanAuth stocke maintenant ses propres ad_id/unique_id en instance.
# ad = ''   ← SUPPRIMÉ
# uuid = '' ← SUPPRIMÉ
