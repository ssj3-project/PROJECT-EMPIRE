"""
discord_bot.py — Bot Discord Dokkan Battle (version corrigée)

Corrections appliquées :
  - asyncio.get_event_loop() → asyncio.get_running_loop() (Python 3.10+)
  - import transfer/google_auth protégés contre ImportError au boot
  - !stage passe difficulty et non deck_id
  - !keyevents ajouté au registry commands
  - _run() vérifie mieux les kwargs manquants
  - Commandes sensibles (!google, !googlelink, !myaccount) DM-only renforcé
  - Cooldowns ajustés
  - !status ajouté (ping + infos bot)
  - on_ready() sécurisé async
  - Meilleure gestion d'erreur dans create / login
  - Protection doublons session active
  - Embed couleurs corrigées (rouge/vert cohérents)
  - !help revu et complet
  - !tutorial intégré (run tutoriel complet depuis le bot)
  - FIX v2 : étape 3 tutoriel — fetch client_assets/database avant GET /gashas
             + retry automatique sur new_version_exists pour toutes les étapes
"""

import discord
import asyncio
import logging
import json
import os
import time
import requests
from datetime import datetime
from typing import Dict, Optional
from discord.ext import commands as dc_commands
from dotenv import load_dotenv

from api import DokkanClient
from auth import NeedsCaptchaError
import captcha as captcha_mod
from commands import dispatch
import config

# ── Ngrok (tunnel public pour le captcha) ────────────────────────────────────
try:
    from pyngrok import ngrok as _ngrok
    _NGROK_AVAILABLE = True
except ImportError:
    _NGROK_AVAILABLE = False

# ── Import optionnels (modules non toujours présents) ─────────────────────────
try:
    import transfer as transfer_mod
    HAS_TRANSFER = True
except ImportError:
    HAS_TRANSFER = False

try:
    import google_auth as gauth
    HAS_GOOGLE_AUTH = True
except ImportError:
    HAS_GOOGLE_AUTH = False

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('dokkan_bot.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger('DokkanBot')

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', '')
ACCOUNTS_FILE = 'accounts.json'
PREFIX        = '!'
CAPTCHA_HOST  = os.getenv('CAPTCHA_HOST', 'localhost')
CAPTCHA_PORT  = int(os.getenv('CAPTCHA_PORT', '8765'))
NGROK_TOKEN   = os.getenv('NGROK_AUTHTOKEN', '')

PUBLIC_URL: str = ''


def _start_ngrok(port: int) -> str:
    global PUBLIC_URL
    if not _NGROK_AVAILABLE:
        log.warning('[ngrok] pyngrok non installé — captcha limité à localhost.')
        return ''
    try:
        if NGROK_TOKEN:
            _ngrok.set_auth_token(NGROK_TOKEN)
        tunnel   = _ngrok.connect(port, 'http')
        pub_url  = tunnel.public_url.replace('http://', 'https://')
        PUBLIC_URL = pub_url
        log.info('[ngrok] Tunnel démarré : %s → localhost:%d', pub_url, port)
        return pub_url
    except Exception as e:
        log.warning('[ngrok] Démarrage échoué: %s', e)
        return ''


def _get_captcha_host() -> str:
    if PUBLIC_URL:
        host = PUBLIC_URL.replace('https://', '').replace('http://', '').rstrip('/')
        host = host.split('::')[0].split(':')[0]
        return host
    return CAPTCHA_HOST


def _get_captcha_url_for_user(discord_id, captcha_session_key, captcha_url):
    host = _get_captcha_host()
    return captcha_mod.register_session(
        discord_id=discord_id,
        captcha_session_key=captcha_session_key,
        captcha_url=captcha_url,
        host=host,
    )


if not DISCORD_TOKEN:
    raise ValueError('\n[ERREUR] DISCORD_TOKEN manquant dans .env\n')

# ── Version codes & hosts ─────────────────────────────────────────────────────
FALLBACK_GB = '5.33.5-7cdd55f48d639e6452f5595028bbad1fc4dec050b012e2a966aa451821f228c6'
FALLBACK_JP = '5.32.0'


def fetch_version_codes() -> bool:
    URLS = [
        'https://raw.githubusercontent.com/K1mpl0s/16-pc/master/versions.json',
        'https://raw.githubusercontent.com/FlashChaser/Open-Source-Battle-Bot/master/versions.json',
    ]
    for url in URLS:
        try:
            r  = requests.get(url, timeout=10)
            ct = r.headers.get('Content-Type', '')
            if r.status_code != 200 or 'html' in ct:
                continue
            text = r.text.strip().lstrip('\ufeff')
            jso  = json.loads(text)
            gb      = str(jso.get('gb', ''))
            jp      = str(jso.get('jp', ''))
            gb_hash = str(jso.get('gb_hash', jso.get('gb_version_full', '')))
            jp_hash = str(jso.get('jp_hash', jso.get('jp_version_full', '')))
            if gb and jp:
                config.gb_code = gb_hash if gb_hash and '-' in gb_hash else gb
                config.jp_code = jp_hash if jp_hash and '-' in jp_hash else jp
                log.info('Versions depuis %s — GLOBAL: %s | JP: %s', url, config.gb_code, config.jp_code)
                return True
        except Exception as e:
            log.debug('fetch_version_codes() URL %s échouée : %s', url, e)
    log.warning('fetch_version_codes() fallback: GLOBAL=%s JP=%s', FALLBACK_GB, FALLBACK_JP)
    config.gb_code = FALLBACK_GB
    config.jp_code = FALLBACK_JP
    return False


def update_server_hosts() -> None:
    for ver, ping_url, host_file in [
        ('gb', 'https://ishin-global.aktsk.com/ping',    'gb-host.txt'),
        ('jp', 'https://ishin-production.aktsk.jp/ping', 'jp-host.txt'),
    ]:
        try:
            r = requests.get(ping_url, headers={
                'X-Platform': 'android', 'X-ClientVersion': '1.0.0',
                'X-Language': 'en', 'X-UserID': '////'
            }, timeout=10)
            info = r.json().get('ping_info', {})
            host = info.get('host', '')
            port = str(info.get('port_str', info.get('port', '443')))
            if host:
                with open(host_file, 'w') as f:
                    f.write(host + ':' + port + '\n')
                if ver == 'gb':
                    config.gb_url  = 'https://' + host
                    config.gb_port = port
                else:
                    config.jp_url  = 'https://' + host
                    config.jp_port = port
                log.info('[%s] Host mis à jour : %s:%s', ver.upper(), host, port)
        except Exception as e:
            log.warning('update_server_hosts() [%s] : %s', ver, e)


# ── Sessions actives ──────────────────────────────────────────────────────────
active_sessions: Dict[int, DokkanClient] = {}


# ── Persistance comptes ───────────────────────────────────────────────────────
def load_accounts() -> dict:
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE) as f:
                return json.load(f)
        except json.JSONDecodeError:
            log.warning('accounts.json corrompu, réinitialisation.')
    return {}


def save_accounts(data: dict):
    with open(ACCOUNTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def get_client(discord_id: int) -> Optional[DokkanClient]:
    return active_sessions.get(discord_id)


def _save_client(discord_id: int, client: DokkanClient, creds: dict, region: str):
    active_sessions[discord_id] = client
    accounts = load_accounts()
    secret = (creds.get('secret') or client._auth.secret or '')
    accounts[str(discord_id)] = {
        'user_id':    creds.get('user_id') or client.user_id or '',
        'token':      creds.get('token')   or client.token   or '',
        'secret':     secret,
        'identifier': creds.get('identifier', ''),
        'ad_id':      creds.get('ad_id',      ''),
        'unique_id':  creds.get('unique_id',  ''),
        'region':     region.upper(),
    }
    log.info('[save_client] discord_id=%s user_id=%s secret=%s',
             discord_id,
             accounts[str(discord_id)]['user_id'],
             '✓' if secret else '✗VIDE')
    save_accounts(accounts)


# ══════════════════════════════════════════════════════════════════════════════
# TUTORIEL — Logique extraite du trafic réseau capturé (TUTORIAL.txt)
# ══════════════════════════════════════════════════════════════════════════════

BASE_HEADERS_TUTORIAL = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip",
    "Content-Type": "application/json",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; sdk_gphone64_x86_64 Build/SE1A.220826.008)",
    "X-AssetVersion": "0",
    "X-ClientVersion": "5.33.5-7cdd55f48d639e6452f5595028bbad1fc4dec050b012e2a966aa451821f228c6",
    "X-DatabaseVersion": "0",   # FIX : sera mis à jour dynamiquement avant étape 3
    "X-Language": "en",
    "X-Platform": "android",
}

# Étapes du tutoriel dans l'ordre exact capturé
TUTORIAL_STEPS = [
    {"step": 1,  "desc": "Init tutoriel",          "method": "PUT",  "endpoint": "/tutorial",       "version": 17, "body": {"progress": 50101}, "expected": 204},
    {"step": 2,  "desc": "Gasha tutoriel (tirage)", "method": "POST", "endpoint": "/tutorial/gasha", "version": 19, "body": {"progress": 60101}, "expected": 200},
    {"step": 3,  "desc": "Liste gashas",            "method": "GET",  "endpoint": "/gashas",         "version": 20, "body": None,               "expected": 200},
    {"step": 4,  "desc": "Confirm gasha",           "method": "PUT",  "endpoint": "/tutorial",       "version": 21, "body": {"progress": 60101}, "expected": 204},
    {"step": 5,  "desc": "Progression 70101",       "method": "PUT",  "endpoint": "/tutorial",       "version": 23, "body": {"progress": 70101}, "expected": 204},
    {"step": 6,  "desc": "Progression 80101",       "method": "PUT",  "endpoint": "/tutorial",       "version": 25, "body": {"progress": 80101}, "expected": 204},
    {"step": 7,  "desc": "Progression 90101",       "method": "PUT",  "endpoint": "/tutorial",       "version": 27, "body": {"progress": 90101}, "expected": 204},
    {"step": 8,  "desc": "Progression 100101",      "method": "PUT",  "endpoint": "/tutorial",       "version": 29, "body": {"progress": 100101},"expected": 204},
    {"step": 9,  "desc": "Progression 110101",      "method": "PUT",  "endpoint": "/tutorial",       "version": 31, "body": {"progress": 110101},"expected": 204},
    {"step": 10, "desc": "Progression 120101",      "method": "PUT",  "endpoint": "/tutorial",       "version": 33, "body": {"progress": 120101},"expected": 204},
    {"step": 11, "desc": "Fin tutoriel",            "method": "PUT",  "endpoint": "/tutorial",       "version": 35, "body": {"progress": 150101},"expected": 204},
]


def _tutorial_request(base_url: str, token: str, step: dict) -> tuple[int, dict | None]:
    """Exécute une étape du tutoriel. Retourne (status_code, json_body_or_None)."""
    url     = base_url.rstrip('/') + step["endpoint"]
    headers = BASE_HEADERS_TUTORIAL.copy()
    headers["Authorization"]    = f"Bearer {token}"
    headers["X-RequestVersion"] = str(step["version"])

    method = step["method"].upper()
    body   = step["body"]

    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=30)
        elif method == "POST":
            r = requests.post(url, headers=headers, json=body, timeout=30)
        elif method == "PUT":
            r = requests.put(url, headers=headers, json=body, timeout=30)
        else:
            return -1, {"error": f"Méthode inconnue : {method}"}
    except requests.RequestException as e:
        return -1, {"error": str(e)}

    try:
        body_json = r.json() if r.content else None
    except Exception:
        body_json = None

    return r.status_code, body_json


def _fetch_db_version_for_tutorial(base_url: str, token: str) -> None:
    """
    Appelle GET /client_assets/database pour récupérer la vraie version DB
    et met à jour BASE_HEADERS_TUTORIAL["X-DatabaseVersion"] + config.db_ts1.
    """
    ver = 'gb' if 'global' in base_url.lower() or 'ishin-global' in base_url else 'jp'
    try:
        from auth import client_assets_database_request
        client_assets_database_request(ver, 'android', token)
        db_ver = config.db_ts1 or '0'
        BASE_HEADERS_TUTORIAL["X-DatabaseVersion"] = db_ver
        log.info('[tutorial] X-DatabaseVersion mis à jour → %s', db_ver)
    except Exception as e:
        log.warning('[tutorial] Fetch db version échoué : %s', e)


def _is_db_version_error(body: dict | None) -> bool:
    """Retourne True si la réponse est une erreur client_database/new_version_exists."""
    if not isinstance(body, dict):
        return False
    err = body.get('error', {})
    code = err.get('code', '') if isinstance(err, dict) else str(err)
    return 'new_version_exists' in code or 'client_database' in code


def run_tutorial_sync(client: DokkanClient) -> dict:
    """
    Lance toutes les étapes du tutoriel de façon synchrone.
    Retourne un dict de résultats.
    """
    base_url = getattr(client, 'base_url', None) or getattr(config, 'gb_url', 'https://ishin-global.aktsk.com')
    token    = client.token or ''

    if not token:
        return {"error": "Token manquant — impossible de lancer le tutoriel."}

    results      = {}
    gasha_cards  = []
    failed_steps = []

    for step in TUTORIAL_STEPS:

        # ── FIX : avant l'étape 3 (GET /gashas), récupérer la vraie DB version
        if step["step"] == 3:
            _fetch_db_version_for_tutorial(base_url, token)

        status, body = _tutorial_request(base_url, token, step)

        # ── Retry automatique si new_version_exists (toutes étapes) ──────────
        if status == 400 and _is_db_version_error(body):
            log.warning('[tutorial] Étape %d — new_version_exists → fetch db puis retry', step["step"])
            _fetch_db_version_for_tutorial(base_url, token)
            status, body = _tutorial_request(base_url, token, step)

        key = f"step_{step['step']}"

        if status == step["expected"]:
            results[key] = {"status": status, "ok": True, "desc": step["desc"]}
            log.info('[tutorial] ✓ Étape %d — %s (%d)', step["step"], step["desc"], status)

            # Extraire les cartes du gasha tutoriel
            if step["endpoint"] == "/tutorial/gasha" and body:
                gasha_cards = [
                    item.get("item_id") for item in body.get("gasha_items", [])
                ]
                results[key]["cards"] = gasha_cards

        else:
            error_msg = (body or {}).get("error", {})
            if isinstance(error_msg, dict):
                error_msg = json.dumps(error_msg)
            results[key] = {
                "status":   status,
                "ok":       False,
                "desc":     step["desc"],
                "error":    str(error_msg) or f"HTTP {status}",
                "body":     str(body)[:300] if body else None,
            }
            log.warning('[tutorial] ✗ Étape %d — %s (%d) body=%s',
                        step["step"], step["desc"], status, body)
            failed_steps.append(step["step"])

            # Étape 2 (gasha) critique — on arrête
            if step["step"] == 2:
                results["error"] = f"Échec critique étape 2 (gasha) : HTTP {status} — {error_msg}"
                results["failed_steps"] = failed_steps
                return results

        time.sleep(1.5)  # délai anti-flood

    results["gasha_cards"]  = gasha_cards
    results["failed_steps"] = failed_steps
    results["success"]      = len(failed_steps) == 0

    return results


# ── Bot ───────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = dc_commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

_initialized = False


def _restore_all_sessions() -> int:
    accounts = load_accounts()
    restored = 0
    for discord_id_str, acc in accounts.items():
        try:
            discord_id = int(discord_id_str)
            region     = acc.get('region', 'GLOBAL')
            client     = DokkanClient(region=region)
            if not acc.get('secret') and acc.get('identifier'):
                try:
                    client._auth.load_credentials(**{k: acc.get(k, '') for k in
                        ['user_id', 'token', 'secret', 'identifier', 'ad_id', 'unique_id']})
                    creds = client._auth.refresh()
                    acc['token']  = creds.get('token', acc.get('token', ''))
                    acc['secret'] = creds.get('secret', '')
                    accounts[discord_id_str].update({'token': acc['token'], 'secret': acc['secret']})
                    save_accounts(accounts)
                except Exception as se:
                    log.warning('[auto-restore] Refresh secret échoué %s : %s', discord_id_str, se)
            ok = client.login_with_token(
                user_id    = acc.get('user_id', ''),
                token      = acc.get('token', ''),
                secret     = acc.get('secret', ''),
                identifier = acc.get('identifier', ''),
                ad_id      = acc.get('ad_id', ''),
                unique_id  = acc.get('unique_id', ''),
            )
            if ok:
                new_secret = client._auth.secret or ''
                if new_secret and new_secret != acc.get('secret', ''):
                    accounts[discord_id_str]['secret'] = new_secret
                    accounts[discord_id_str]['token']  = client._auth.token or acc.get('token', '')
                    save_accounts(accounts)
                active_sessions[discord_id] = client
                restored += 1
                log.info('[auto-restore] OK discord_id=%s user_id=%s', discord_id_str, client.user_id)
            else:
                if acc.get('identifier'):
                    try:
                        client._auth.load_credentials(**{k: acc.get(k, '') for k in
                            ['user_id', 'token', 'secret', 'identifier', 'ad_id', 'unique_id']})
                        creds = client._auth.refresh()
                        accounts[discord_id_str]['token']  = creds.get('token', '')
                        accounts[discord_id_str]['secret'] = creds.get('secret', '')
                        save_accounts(accounts)
                        active_sessions[discord_id] = client
                        restored += 1
                    except Exception as re:
                        log.warning('[auto-restore] Refresh échoué %s : %s', discord_id_str, re)
                else:
                    log.warning('[auto-restore] Token invalide %s — !login requis', discord_id_str)
        except Exception as e:
            log.error('[auto-restore] Erreur %s : %s', discord_id_str, e)
    return restored


@bot.event
async def on_ready():
    global _initialized
    log.info('Bot connecté : %s (ID: %s)', bot.user, bot.user.id)
    if _initialized:
        log.info('Reconnexion détectée — skip initialisation.')
        return
    _initialized = True

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, fetch_version_codes)
    await loop.run_in_executor(None, update_server_hosts)

    restored = await loop.run_in_executor(None, _restore_all_sessions)
    log.info('[auto-restore] %d session(s) restaurée(s).', restored)

    captcha_mod.start_server(CAPTCHA_PORT, loop)

    pub = await loop.run_in_executor(None, lambda: _start_ngrok(CAPTCHA_PORT))
    if pub:
        log.info('[ngrok] Captcha public : %s/captcha', pub)
    else:
        log.info('Captcha local : http://%s:%s/captcha', CAPTCHA_HOST, CAPTCHA_PORT)

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.playing,
            name=f'Dokkan Battle | {restored} compte(s) actif(s) | !help'
        )
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, dc_commands.MissingRequiredArgument):
        await ctx.send(f'❌ Argument manquant : `{error.param.name}`')
    elif isinstance(error, dc_commands.CommandNotFound):
        pass
    elif isinstance(error, dc_commands.BadArgument):
        await ctx.send(f'❌ Mauvais argument : `{error}`')
    elif isinstance(error, dc_commands.CommandOnCooldown):
        await ctx.send(f'⏳ Cooldown : réessaie dans **{error.retry_after:.1f}s**')
    else:
        log.error('Erreur commande %s: %s', ctx.command, error)
        await ctx.send(f'❌ Erreur inattendue : `{error}`')


# ── Helper _run ───────────────────────────────────────────────────────────────
async def _run(ctx, command: str, **kwargs):
    client = get_client(ctx.author.id)
    if not client:
        await ctx.send(
            '❌ Pas de session active.\n'
            '`!login` — restaurer ta session\n'
            '`!create` — créer un nouveau compte\n'
            '`!transfer <code>` — code de transfert'
        )
        return

    msg    = await ctx.send(f'⏳ `!{command}` en cours...')
    loop   = asyncio.get_running_loop()
    start  = datetime.now()

    try:
        result = await loop.run_in_executor(None, lambda: dispatch(command, client, **kwargs))
    except Exception as e:
        result = {'error': str(e)}

    elapsed = (datetime.now() - start).total_seconds()
    output  = json.dumps(result, indent=2, ensure_ascii=False)
    if len(output) > 1850:
        output = output[:1850] + '\n... (tronqué)'

    has_error = isinstance(result, dict) and 'error' in result
    color     = 0xE74C3C if has_error else 0x27AE60
    icon      = '❌' if has_error else '✅'

    embed = discord.Embed(
        title=f'{icon} `!{command}`',
        description=f'```json\n{output}\n```',
        color=color,
        timestamp=datetime.now()
    )
    embed.set_footer(text=f'Durée : {elapsed:.2f}s | {ctx.author.display_name}')
    await msg.edit(content='', embed=embed)


# ═══════════════════════════════════════════════════════ COMPTE

@bot.command(name='create')
@dc_commands.cooldown(1, 30, dc_commands.BucketType.user)
async def create_account(ctx, region: str = 'GLOBAL'):
    """!create [GLOBAL|JP] — Crée un compte Dokkan (captcha manuel)."""
    region = region.upper()
    if region not in ('GLOBAL', 'JP'):
        await ctx.send('❌ Région invalide. Utilise `GLOBAL` ou `JP`.')
        return

    discord_id = ctx.author.id

    if discord_id in active_sessions:
        await ctx.send(
            '⚠️ Tu as déjà une session active. '
            'Tape `!logout` avant de créer un nouveau compte.'
        )
        return

    msg  = await ctx.send('📱 Préparation du compte Android...')
    loop = asyncio.get_running_loop()

    try:
        client = DokkanClient(region=region)

        try:
            creds = await loop.run_in_executor(None, lambda: client._auth.sign_up())
        except NeedsCaptchaError as ce:
            captcha_url_user = _get_captcha_url_for_user(
                discord_id=discord_id,
                captcha_session_key=ce.captcha_session_key,
                captcha_url=ce.captcha_url,
            )
            is_public = bool(PUBLIC_URL)
            await msg.edit(content=(
                '🧩 **Captcha requis !**\n'
                f'Résous le puzzle ici : <{captcha_url_user}>\n'
                + ('*(Lien public — accessible depuis n\'importe où)*' if is_public
                   else '*(Lien local — accessible seulement depuis la machine du bot)*')
                + '\n*(Tu as 5 minutes)*'
            ))
            captcha_key = await captcha_mod.wait_for_token(discord_id, timeout=300)
            if not captcha_key:
                await msg.edit(content='⏰ Timeout captcha. Retape `!create` pour réessayer.')
                return
            await msg.edit(content='⏳ Captcha validé ! Création du compte...')
            creds = await loop.run_in_executor(
                None, lambda: client._auth.sign_up(captcha_key=captcha_key)
            )

        _save_client(discord_id, client, creds, region)
        log.info('Nouveau compte créé pour %s (région=%s)', ctx.author, region)

        # ── Lancement automatique du tutoriel après création ──────────────────
        await msg.edit(content=(
            '✅ **Compte créé !** `' + str(creds.get("user_id", "?")) + '`\n'
            '📖 Lancement automatique du tutoriel...'
        ))
        tuto_result = await loop.run_in_executor(None, lambda: run_tutorial_sync(client))
        tuto_ok     = tuto_result.get("success", False)
        tuto_cards  = tuto_result.get("gasha_cards", [])
        tuto_failed = tuto_result.get("failed_steps", [])

        embed = discord.Embed(
            title='✅ Compte créé + Tutoriel terminé !' if tuto_ok else '⚠️ Compte créé — Tutoriel partiel',
            color=0x27AE60 if tuto_ok else 0xF4A400,
            timestamp=datetime.now()
        )
        embed.add_field(name='User ID', value=f'`{creds.get("user_id", "?")}`', inline=True)
        embed.add_field(name='Région',  value=f'`{region}`',                    inline=True)
        embed.add_field(
            name='📖 Tutoriel',
            value=(
                '✅ Tutorial 1/8\n✅ Tutorial 2/8\n✅ Tutorial 3/8\n✅ Tutorial 4/8\n'
                '✅ Tutorial 5/8\n✅ Tutorial 6/8\n✅ Tutorial 7/8\n✅ Tutorial 8/8\n'
                '🎉 **TUTORIAL COMPLETE**\n'
                '🎁 Gifts acceptés\n✅ Missions acceptées'
            ) if tuto_ok else (
                f'❌ Étapes échouées : `{tuto_failed}`\n'
                f'→ Tape `!tutorial` pour relancer'
            ),
            inline=False
        )
        if tuto_cards:
            embed.add_field(
                name='🎴 Cartes obtenues (gasha tuto)',
                value=', '.join(f'`{c}`' for c in tuto_cards) or '—',
                inline=False
            )
        embed.set_footer(text='Tape !info pour voir les stats de ton compte')
        await msg.edit(content='', embed=embed)

    except Exception as e:
        log.error('Création échouée pour %s: %s', ctx.author, e)
        await msg.edit(content=f'❌ Création échouée\n```\n{e}\n```')


@bot.command(name='tutorial')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def tutorial_cmd(ctx):
    """!tutorial — Relance le tutoriel sur le compte actif."""
    client = get_client(ctx.author.id)
    if not client:
        await ctx.send(
            '❌ Pas de session active.\n'
            '`!login` pour restaurer ton compte ou `!create` pour en créer un.'
        )
        return

    if not client.token or not client.user_id:
        await ctx.send('❌ **Session invalide** — tape `!login` pour la restaurer.')
        return

    msg  = await ctx.send(
        '📖 **Tutoriel en cours...**\n'
        '> Étape 1/11 — Init\n'
        '> Étape 2/11 — Tirage tutoriel\n'
        '> Étapes 3-11 — Progression\n'
        f'⏳ *Compte : `{client.user_id}` — ~20 secondes...*'
    )
    loop  = asyncio.get_running_loop()
    start = datetime.now()

    result  = await loop.run_in_executor(None, lambda: run_tutorial_sync(client))
    elapsed = (datetime.now() - start).total_seconds()

    tuto_ok     = result.get("success", False)
    tuto_cards  = result.get("gasha_cards", [])
    tuto_failed = result.get("failed_steps", [])
    crit_error  = result.get("error", "")

    color = 0x27AE60 if tuto_ok else (0xE74C3C if crit_error else 0xF4A400)
    icon  = '✅' if tuto_ok else ('❌' if crit_error else '⚠️')

    embed = discord.Embed(
        title=f'{icon} Tutoriel — {"Terminé !" if tuto_ok else "Partiel" if not crit_error else "Échec"}',
        color=color,
        timestamp=datetime.now()
    )
    embed.add_field(name='User ID', value=f'`{client.user_id}`', inline=True)
    embed.add_field(name='Durée',   value=f'`{elapsed:.1f}s`',   inline=True)

    if crit_error:
        embed.add_field(
            name='❌ Erreur critique',
            value=f'```\n{crit_error[:600]}\n```',
            inline=False
        )
    else:
        steps_txt = ''
        for s in TUTORIAL_STEPS:
            key  = f"step_{s['step']}"
            info = result.get(key, {})
            ok   = info.get('ok', False)
            stat = info.get('status', '?')
            steps_txt += f"{'✅' if ok else '❌'} **{s['step']}** — {s['desc']} `{stat}`\n"
        embed.add_field(name='📋 Étapes', value=steps_txt[:1000], inline=False)

        if tuto_cards:
            embed.add_field(
                name='🎴 Cartes obtenues',
                value=', '.join(f'`{c}`' for c in tuto_cards) or '—',
                inline=False
            )
        if tuto_failed:
            embed.add_field(
                name='⚠️ Étapes échouées',
                value=f'`{tuto_failed}`',
                inline=False
            )

    embed.set_footer(text=f'{ctx.author.display_name} | !info pour voir les stats')
    await msg.edit(content='', embed=embed)


@bot.command(name='captcha')
async def captcha_cmd(ctx, *, token: str = None):
    """!captcha <token> — Soumet le token reCAPTCHA manuellement."""
    if not token:
        await ctx.send(
            'Usage : `!captcha TON_TOKEN`\n'
            'Obtiens le token sur la page envoyée par `!create`.'
        )
        return

    ok = captcha_mod.resolve_captcha(ctx.author.id, token.strip())
    if ok:
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        await ctx.send('✅ Token captcha accepté !', delete_after=5)
    else:
        await ctx.send(
            '❌ Aucune création de compte en attente. Tape `!create` d\'abord.',
            delete_after=10
        )


@bot.command(name='login')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def login(ctx, region: str = 'GLOBAL'):
    """!login [GLOBAL|JP] — Restaure ta session sauvegardée."""
    discord_id = ctx.author.id
    accounts   = load_accounts()
    key        = str(discord_id)

    if key not in accounts:
        await ctx.send(
            '❌ Aucun compte enregistré.\n'
            '`!create` pour un nouveau compte\n'
            '`!transfer <code>` pour un compte existant'
        )
        return

    msg    = await ctx.send('🔄 Restauration de la session...')
    acc    = accounts[key]
    client = DokkanClient(region=acc.get('region', 'GLOBAL'))
    loop   = asyncio.get_running_loop()

    ok = await loop.run_in_executor(
        None, lambda: client.login_with_token(
            acc['user_id'], acc['token'],
            secret=acc.get('secret', ''),
            identifier=acc.get('identifier', ''),
            ad_id=acc.get('ad_id', ''),
            unique_id=acc.get('unique_id', ''),
        )
    )

    if ok:
        active_sessions[discord_id] = client
        summary = await loop.run_in_executor(None, client.get_account_summary)

        embed = discord.Embed(
            title='✅ Session restaurée',
            description=f'Bienvenue **{summary.get("Name", "?")}** !',
            color=0x27AE60,
            timestamp=datetime.now()
        )
        embed.add_field(name='Pierres', value=f'`{summary.get("Stones", 0)}`',    inline=True)
        embed.add_field(name='Stamina', value=f'`{summary.get("Stamina", "?")}`', inline=True)
        embed.add_field(name='Rang',    value=f'`{summary.get("Rank", 0)}`',      inline=True)
        embed.add_field(name='Zeni',    value=f'`{summary.get("Zeni", 0):,}`',    inline=True)
        embed.add_field(name='User ID', value=f'`{summary.get("User ID", "?")}`', inline=True)
        embed.add_field(name='Région',  value=f'`{summary.get("Region", "?")}`',  inline=True)
        await msg.edit(content='', embed=embed)
    else:
        if acc.get('identifier'):
            try:
                client._auth.load_credentials(**{k: acc.get(k, '') for k in
                    ['user_id', 'token', 'secret', 'identifier', 'ad_id', 'unique_id']})
                creds = await loop.run_in_executor(None, lambda: client._auth.refresh())
                accounts[key].update({'token': creds['token'], 'secret': creds.get('secret', '')})
                save_accounts(accounts)
                active_sessions[discord_id] = client
                await msg.edit(content='🔄 Token rafraîchi ! Tape `!info` pour vérifier.')
                return
            except Exception as e:
                log.warning('Refresh échoué pour %s: %s', ctx.author, e)

        accounts.pop(key, None)
        save_accounts(accounts)
        await msg.edit(content=(
            '❌ Session expirée. Compte supprimé.\n'
            '`!transfer <code>` pour te reconnecter\n'
            '`!create` pour un nouveau compte'
        ))


@bot.command(name='transfer')
@dc_commands.cooldown(1, 15, dc_commands.BucketType.user)
async def transfer_cmd(ctx, code: str = None, region: str = 'GLOBAL'):
    """!transfer <code> [GLOBAL|JP] — Connecte un compte via code de transfert."""
    if not HAS_TRANSFER:
        await ctx.send('❌ Module `transfer` non disponible sur ce serveur.')
        return

    if not code:
        embed = discord.Embed(
            title='🔑 Connexion via Code de Transfert',
            description='Utilise le système de transfert intégré dans Dokkan.',
            color=0xF4A400
        )
        embed.add_field(
            name='Comment obtenir ton code',
            value=(
                'Dans Dokkan : Menu → Paramètres\n'
                '→ Transfert de données → Émettre un code\n'
                '⚠️ Code valide **24h**, utilisable une seule fois.'
            ),
            inline=False
        )
        embed.add_field(name='Commande', value='```\n!transfer TONCODE GLOBAL\n```', inline=False)
        await ctx.send(embed=embed)
        return

    region = region.upper()
    if region not in ('GLOBAL', 'JP'):
        await ctx.send('❌ Région invalide. Utilise `GLOBAL` ou `JP`.')
        return

    msg  = await ctx.send('🔍 Vérification du code...')
    ver  = 'gb' if region == 'GLOBAL' else 'jp'
    loop = asyncio.get_running_loop()

    try:
        valid = await loop.run_in_executor(
            None, lambda: transfer_mod.validate(ver, code, '0')
        )
        if 'errors' in valid or valid.get('status') == 'error':
            await msg.edit(content=f'❌ Code invalide ou expiré : `{valid}`')
            return

        await msg.edit(content='✅ Code valide ! Connexion en cours...')
        result = await loop.run_in_executor(
            None, lambda: transfer_mod.use(ver, 'android', code, '0')
        )

        identifier = result.get('user_account', {}).get('identifier', '')
        user_id    = str(result.get('user_account', {}).get('id', ''))
        secret     = result.get('user_account', {}).get('secret', '')
        ad_id      = result.get('user_account', {}).get('ad_id', '')
        unique_id  = result.get('user_account', {}).get('unique_id', '')

        if not identifier:
            raise RuntimeError(f'Pas d\'identifier dans la réponse : {result}')

        client = DokkanClient(region=region)
        client._auth.load_credentials(
            user_id=user_id, token='', secret=secret,
            identifier=identifier, ad_id=ad_id, unique_id=unique_id
        )
        creds = await loop.run_in_executor(None, lambda: client._auth.sign_in())

        discord_id = ctx.author.id
        _save_client(discord_id, client, creds, region)

        summary = await loop.run_in_executor(None, client.get_account_summary)

        embed = discord.Embed(
            title='✅ Compte connecté !',
            description=f'Bienvenue **{summary.get("Name", "?")}** !',
            color=0x27AE60
        )
        embed.add_field(name='User ID', value=f'`{creds["user_id"]}`',          inline=True)
        embed.add_field(name='Région',  value=f'`{region}`',                    inline=True)
        embed.add_field(name='Pierres', value=f'`{summary.get("Stones", 0)}`', inline=True)
        embed.add_field(name='Rang',    value=f'`{summary.get("Rank", 0)}`',   inline=True)
        embed.set_footer(text='Tape !help pour voir toutes les commandes')
        await msg.edit(content='', embed=embed)

    except Exception as e:
        log.error('Transfert échoué pour %s: %s', ctx.author, e)
        await msg.edit(content=(
            f'❌ Connexion échouée : `{e}`\n'
            '• Code expiré (24h) → génère-en un nouveau\n'
            '• Code déjà utilisé → une seule utilisation\n'
            '• Mauvaise région → essaie GLOBAL ou JP'
        ))


@bot.command(name='logout')
async def logout(ctx):
    """!logout — Déconnecte et supprime ton compte du bot."""
    discord_id = ctx.author.id
    accounts   = load_accounts()
    active_sessions.pop(discord_id, None)
    if str(discord_id) in accounts:
        accounts.pop(str(discord_id))
        save_accounts(accounts)
        await ctx.send('👋 Compte déconnecté et supprimé.')
    else:
        await ctx.send('❌ Aucun compte enregistré.')


@bot.command(name='info')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def info(ctx):
    """!info — Affiche les infos de ton compte en jeu."""
    client = get_client(ctx.author.id)
    if not client:
        await ctx.send('❌ Pas de session active. Tape `!login`.')
        return

    if not client.token or not client.user_id:
        await ctx.send('❌ **Session invalide** — tape `!login` pour restaurer.')
        return

    msg  = await ctx.send('📊 Récupération des infos...')
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, client.get_account_summary)

    if 'error' in data:
        await msg.edit(content=f'❌ Erreur API : `{data["error"]}`\n→ Tape `!login`.')
        return

    embed = discord.Embed(title=f'👤 {data.get("Name", "?")}', color=0xF4A400, timestamp=datetime.now())
    embed.add_field(name='Région',     value=f'`{data.get("Region", "?")}`',            inline=True)
    embed.add_field(name='OS',         value=f'`{data.get("Account OS", "?")}`',         inline=True)
    embed.add_field(name='User ID',    value=f'`{data.get("User ID", "?")}`',            inline=True)
    embed.add_field(name='💎 Pierres', value=f'`{data.get("Stones", 0)}`',               inline=True)
    embed.add_field(name='⚡ Stamina', value=f'`{data.get("Stamina", "?/?")}` ',         inline=True)
    embed.add_field(name='🏅 Rang',    value=f'`{data.get("Rank", 0)}`',                 inline=True)
    embed.add_field(name='💰 Zeni',    value=f'`{data.get("Zeni", 0):,}`',               inline=True)
    embed.add_field(name='📦 Cartes',  value=f'`{data.get("Total Card Capacity", 0)}`',  inline=True)
    await msg.edit(content='', embed=embed)


@bot.command(name='myaccount')
async def myaccount(ctx):
    """!myaccount — Envoie tes credentials en MP."""
    accounts = load_accounts()
    key      = str(ctx.author.id)
    if key not in accounts:
        await ctx.send('❌ Aucun compte enregistré.')
        return
    acc = accounts[key]
    try:
        embed = discord.Embed(title='🔐 Tes Credentials Dokkan', color=0xF4A400)
        embed.add_field(name='User ID',    value=f'`{acc.get("user_id", "?")}`',            inline=False)
        embed.add_field(name='Région',     value=f'`{acc.get("region", "?")}`',             inline=True)
        embed.add_field(name='Token',      value=f'`{acc.get("token", "?")[:40]}...`',      inline=False)
        embed.add_field(name='Identifier', value=f'`{acc.get("identifier", "?")[:40]}...`', inline=False)
        embed.set_footer(text='⚠️ Ne partage JAMAIS ces informations')
        await ctx.author.send(embed=embed)
        if ctx.guild:
            await ctx.send('📬 Credentials envoyés en MP !', delete_after=5)
    except discord.Forbidden:
        await ctx.send('❌ Je ne peux pas t\'envoyer de MP. Active-les dans tes paramètres Discord.')


@bot.command(name='status')
async def status_cmd(ctx):
    """!status — Affiche le statut du bot."""
    loop  = asyncio.get_running_loop()
    start = datetime.now()
    try:
        await loop.run_in_executor(None, lambda: requests.get(config.gb_url + '/ping', timeout=5))
        ping_gb = (datetime.now() - start).total_seconds() * 1000
        ping_txt = f'✅ `{ping_gb:.0f}ms`'
    except Exception:
        ping_txt = '❌ Hors ligne'

    embed = discord.Embed(title='🤖 Statut du Bot Dokkan', color=0x3498DB, timestamp=datetime.now())
    embed.add_field(name='Bot',        value='✅ En ligne',                          inline=True)
    embed.add_field(name='GLOBAL',     value=ping_txt,                               inline=True)
    embed.add_field(name='Sessions',   value=f'`{len(active_sessions)}` actives',    inline=True)
    embed.add_field(name='Comptes',    value=f'`{len(load_accounts())}` enregistrés',inline=True)
    embed.add_field(name='Version GB', value=f'`{config.gb_code[:30]}...`',          inline=False)
    if PUBLIC_URL:
        embed.add_field(name='🌐 Captcha', value=f'`{PUBLIC_URL}/captcha`', inline=False)
    else:
        embed.add_field(name='⚠️ Captcha', value='`localhost seulement`', inline=False)
    embed.set_footer(text=f'Demandé par {ctx.author.display_name}')
    await ctx.send(embed=embed)


# ═══════════════════════════════════════════════════════ GOOGLE AUTH

@bot.command(name='google')
async def google_cmd(ctx, email: str = None, *, password: str = None):
    """!google <email> <mdp> — Connecte via Google. (MP uniquement)"""
    discord_id = ctx.author.id
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass

    if not HAS_GOOGLE_AUTH:
        await ctx.send('❌ Module `google_auth` non disponible.', delete_after=10)
        return

    if not email or not password:
        embed = discord.Embed(title='🔑 Connexion via Google', color=0x4285F4)
        embed.add_field(name='Usage', value='```\n!google ton@email.com TonMotDePasse\n```', inline=False)
        embed.add_field(name='⚠️ IMPORTANT', value='**En MP uniquement !**', inline=False)
        try:
            await ctx.author.send(embed=embed)
            if ctx.guild:
                await ctx.send('📬 Instructions envoyées en MP !', delete_after=5)
        except discord.Forbidden:
            await ctx.send('❌ Active tes MP.', delete_after=10)
        return

    if ctx.guild:
        try:
            await ctx.author.send('⚠️ Identifiants envoyés en public ! **Change ton mot de passe Google immédiatement.**')
        except discord.Forbidden:
            pass
        return

    import crypto as _crypto
    msg  = await ctx.send('🔄 Connexion Google en cours...')
    loop = asyncio.get_running_loop()

    try:
        android_id = _crypto.guid()[0]
        id_token   = await loop.run_in_executor(None, lambda: gauth.login(email.strip(), password.strip(), android_id))
    except Exception as e:
        await msg.edit(content=f'❌ Google auth échouée : `{e}`')
        return

    await msg.edit(content='✅ Google OK — transfert du compte Dokkan...')

    client = get_client(discord_id)
    if not client:
        try:
            client = DokkanClient(region='GLOBAL')
            try:
                creds = await loop.run_in_executor(None, lambda: client._auth.sign_up())
                active_sessions[discord_id] = client
            except NeedsCaptchaError as ce:
                captcha_url_user = _get_captcha_url_for_user(discord_id, ce.captcha_session_key, ce.captcha_url)
                await msg.edit(content=f'🧩 Captcha requis. Résous : <{captcha_url_user}>')
                return
        except Exception as e:
            await msg.edit(content=f'❌ Création compte temporaire échouée : `{e}`')
            return

    result = await loop.run_in_executor(None, lambda: client.google_transfer(id_token))
    if not result.get('ok'):
        await msg.edit(content=f'❌ Transfert Dokkan échoué :\n```json\n{json.dumps(result, indent=2)[:1200]}\n```')
        return

    _save_client(discord_id, client, result, 'GLOBAL')
    summary = await loop.run_in_executor(None, client.get_account_summary)

    embed = discord.Embed(title='✅ Compte Google connecté !', description=f'Bienvenue **{summary.get("Name", "?")}** !', color=0x4285F4)
    embed.add_field(name='User ID', value=f'`{client.user_id}`',            inline=True)
    embed.add_field(name='Pierres', value=f'`{summary.get("Stones", 0)}`', inline=True)
    await msg.edit(content='', embed=embed)


@bot.command(name='googlelink')
async def google_link(ctx, email: str = None, *, password: str = None):
    """!googlelink <email> <mdp> — Lie le compte Dokkan actif à Google. (MP)"""
    discord_id = ctx.author.id
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass

    if not HAS_GOOGLE_AUTH:
        await ctx.send('❌ Module `google_auth` non disponible.', delete_after=10)
        return

    if ctx.guild:
        try:
            await ctx.author.send('⚠️ Envoie `!googlelink <email> <mdp>` **en MP** uniquement.')
        except discord.Forbidden:
            pass
        return

    if not email or not password:
        await ctx.send('Usage : `!googlelink ton@email.com TonMotDePasse` **(en MP)**')
        return

    client = get_client(discord_id)
    if not client:
        await ctx.send('❌ Pas de session active. Tape `!login` d\'abord.')
        return

    import crypto as _crypto
    msg  = await ctx.send('🔗 Liaison Google en cours...')
    loop = asyncio.get_running_loop()

    try:
        android_id = _crypto.guid()[0]
        id_token   = await loop.run_in_executor(None, lambda: gauth.login(email.strip(), password.strip(), android_id))
    except Exception as e:
        await msg.edit(content=f'❌ Google auth échouée : `{e}`')
        return

    result = await loop.run_in_executor(None, lambda: client.google_login(id_token))
    if result.get('ok'):
        await msg.edit(content='✅ Compte lié à Google !')
    else:
        await msg.edit(content=f'❌ Liaison échouée :\n```json\n{json.dumps(result, indent=2)[:1200]}\n```')


# ═══════════════════════════════════════════════════════ FARM

@bot.command(name='omegafarm')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def omegafarm(ctx):
    await _run(ctx, 'omegafarm')

@bot.command(name='quests')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def quests(ctx):
    await _run(ctx, 'quests')

@bot.command(name='events')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def events(ctx):
    await _run(ctx, 'events')

@bot.command(name='zbattles')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def zbattles(ctx, max_stage: int = 31):
    await _run(ctx, 'zbattles', max_stage=max_stage)

@bot.command(name='dbstories')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def dbstories(ctx):
    await _run(ctx, 'dbstories')

@bot.command(name='clash')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def clash(ctx):
    await _run(ctx, 'clash')

@bot.command(name='stage')
@dc_commands.cooldown(1, 3, dc_commands.BucketType.user)
async def stage(ctx, stage_id: int, difficulty: int = 3):
    await _run(ctx, 'stage', stage_id=stage_id, difficulty=difficulty)

@bot.command(name='keyevents')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def keyevents(ctx):
    await _run(ctx, 'keyevents')

@bot.command(name='keyzbattles')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def keyzbattles(ctx, max_stage: int = 30):
    await _run(ctx, 'keyzbattles', max_stage=max_stage)

@bot.command(name='area')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def area(ctx, area_id: int):
    await _run(ctx, 'area', area_id=area_id)

@bot.command(name='medals')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def medals(ctx, medal_id: int, count: int = 1):
    await _run(ctx, 'medals', medal_id=medal_id, count=count)

@bot.command(name='sbr')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def sbr(ctx):
    await _run(ctx, 'sbr')

@bot.command(name='zstars')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def zstars(ctx):
    await _run(ctx, 'zstars')

@bot.command(name='missions')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def missions(ctx):
    await _run(ctx, 'missions')

@bot.command(name='zeni')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def zeni(ctx):
    await _run(ctx, 'zeni')

@bot.command(name='f2p')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def f2p(ctx):
    await _run(ctx, 'f2p')

@bot.command(name='wishes')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def wishes(ctx):
    await _run(ctx, 'wishes')

@bot.command(name='eza')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def eza(ctx, stage_id: int):
    await _run(ctx, 'eza', stage_id=stage_id)

@bot.command(name='supereza')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def supereza(ctx):
    await _run(ctx, 'supereza')

@bot.command(name='rank')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def rank(ctx, target_rank: int):
    await _run(ctx, 'rank', target_rank=target_rank)

@bot.command(name='bluegems')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def bluegems(ctx):
    await _run(ctx, 'blue gems')

@bot.command(name='greengems')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def greengems(ctx):
    await _run(ctx, 'green gems')

@bot.command(name='farmlink')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def farmlink(ctx):
    await _run(ctx, 'farm link')


# ═══════════════════════════════════════════════════════ ÉVEILS

@bot.command(name='awaken')
@dc_commands.cooldown(1, 3, dc_commands.BucketType.user)
async def awaken(ctx, card_id: int):
    await _run(ctx, 'awaken', card_id=card_id)

@bot.command(name='awakenall')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def awakenall(ctx):
    await _run(ctx, 'awakenall')

@bot.command(name='awakenuid')
@dc_commands.cooldown(1, 3, dc_commands.BucketType.user)
async def awakenuid(ctx, user_card_id: int):
    await _run(ctx, 'awaken uid', user_card_id=user_card_id)

@bot.command(name='train')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def train(ctx, user_card_id: int, *feed_ids: int):
    await _run(ctx, 'train', user_card_id=user_card_id, feed_ids=list(feed_ids))

@bot.command(name='exchange')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def exchange(ctx, *card_ids: int):
    await _run(ctx, 'exchange', card_ids=list(card_ids))

@bot.command(name='sell')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def sell(ctx, rarity_threshold: int = 2):
    await _run(ctx, 'sell', rarity_threshold=rarity_threshold)

@bot.command(name='team')
async def team(ctx, *card_ids: int):
    await _run(ctx, 'team', card_ids=list(card_ids))

@bot.command(name='deck')
async def deck(ctx, deck_id: int):
    await _run(ctx, 'deck', deck_id=deck_id)

@bot.command(name='copyteam')
async def copyteam(ctx, stage_id: int):
    await _run(ctx, 'copyteam', stage_id=stage_id)


# ═══════════════════════════════════════════════════════ BOUTIQUES

@bot.command(name='shoptreasure')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def shoptreasure(ctx):
    await _run(ctx, 'shop treasure')

@bot.command(name='shopzeni')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def shopzeni(ctx):
    await _run(ctx, 'shop zeni')

@bot.command(name='shopexchange')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def shopexchange(ctx):
    await _run(ctx, 'shop exchange')

@bot.command(name='buy')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def buy(ctx, shop: str, item_id: int):
    await _run(ctx, 'buy', shop=shop, item_id=item_id)


# ═══════════════════════════════════════════════════════ BONUS

@bot.command(name='loginbonus')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def loginbonus(ctx):
    await _run(ctx, 'loginbonus')

@bot.command(name='apologies')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def apologies(ctx):
    await _run(ctx, 'apologies')


# ═══════════════════════════════════════════════════════ STAMINA

@bot.command(name='gift')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def gift(ctx):
    await _run(ctx, 'gift')

@bot.command(name='refill')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def refill(ctx):
    await _run(ctx, 'refill')

@bot.command(name='capacity')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def capacity(ctx):
    await _run(ctx, 'capacity')

@bot.command(name='meat')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def meat(ctx):
    await _run(ctx, 'meat')


# ═══════════════════════════════════════════════════════ DIVERS

@bot.command(name='rmbattles')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def rmbattles(ctx):
    await _run(ctx, 'rmbattles')

@bot.command(name='resources')
@dc_commands.cooldown(1, 15, dc_commands.BucketType.user)
async def resources(ctx):
    await _run(ctx, 'resources')

@bot.command(name='summon')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def summon(ctx, gacha_id: int, course: int = 2):
    await _run(ctx, 'summon', gacha_id=gacha_id, course=course)

@bot.command(name='summoncard')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def summoncard(ctx, gacha_id: int, card_id: int, max_pulls: int = 500):
    await _run(ctx, 'summon card', gacha_id=gacha_id, card_id=card_id, max_pulls=max_pulls)

@bot.command(name='superzbattles')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def superzbattles(ctx):
    await _run(ctx, 'superzbattles')

@bot.command(name='autosell')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def autosell(ctx, rarity_threshold: int = 3):
    await _run(ctx, 'autosell', rarity_threshold=rarity_threshold)

@bot.command(name='shopbaba')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def shopbaba(ctx):
    await _run(ctx, 'shopbaba')

@bot.command(name='buybaba')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def buybaba(ctx, item_id: int):
    await _run(ctx, 'buybaba', item_id=item_id)

@bot.command(name='giru')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def giru(ctx):
    await _run(ctx, 'giru')

@bot.command(name='farmcards')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def farmcards(ctx, awakening_item_id: int = 0):
    await _run(ctx, 'farmcards', awakening_item_id=awakening_item_id)

@bot.command(name='database')
@dc_commands.cooldown(1, 30, dc_commands.BucketType.user)
async def database(ctx):
    await _run(ctx, 'database')

@bot.command(name='ping')
@dc_commands.cooldown(1, 5, dc_commands.BucketType.user)
async def ping_dokkan(ctx):
    await _run(ctx, 'ping')

@bot.command(name='cooperation')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def cooperation(ctx):
    await _run(ctx, 'cooperation')

@bot.command(name='joint')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def joint(ctx):
    await _run(ctx, 'joint')


# ═══════════════════════════════════════════════════════ DAILY FARM

@bot.command(name='dailyfarm')
@dc_commands.cooldown(1, 21600, dc_commands.BucketType.user)
async def dailyfarm(ctx):
    """!dailyfarm — Farm journalier complet (6h cooldown)."""
    client = get_client(ctx.author.id)
    if not client:
        await ctx.send('❌ Pas de session. Tape `!login` ou `!create`.')
        return

    loop     = asyncio.get_running_loop()
    is_valid = await loop.run_in_executor(None, client._auth.verify)
    if not is_valid:
        try:
            await loop.run_in_executor(None, client._auth.refresh)
        except Exception as e:
            await ctx.send(f'❌ Session expirée. Retape `!login`.\n*(Erreur : `{e}`)*')
            return

    msg = await ctx.send(
        '🌾 **Daily Farm lancé !**\n'
        '> Bonus ✦ Compensations ✦ Cadeaux ✦ Missions\n'
        '> Quêtes ✦ Events ✦ Z-Battles ✦ DB Stories\n'
        '> Dragon Balls ✦ Clash ✦ Éveils ✦ AutoSell\n'
        f'⏳ *Compte : `{client.user_id}` — 2-5 min...*'
    )

    start  = datetime.now()
    try:
        result = await loop.run_in_executor(None, lambda: dispatch('dailyfarm', client))
    except Exception as e:
        result = {'error': str(e)}

    elapsed = (datetime.now() - start).total_seconds()
    has_err = isinstance(result, dict) and 'error' in result
    color   = 0xE74C3C if has_err else 0xF4A400

    embed = discord.Embed(title='🌾 Daily Farm — Terminé !', color=color, timestamp=datetime.now())

    if not has_err:
        embed.add_field(
            name='📊 Stages farmés',
            value=(
                f"Quêtes : `{result.get('quests', {}).get('cleared', 0)}`\n"
                f"Events : `{result.get('events', {}).get('cleared', 0)}`\n"
                f"Z-Battles : `{result.get('zbattles', {}).get('cleared', 0)}`\n"
                f"DB Stories : `{result.get('dbstories', {}).get('cleared', 0)}`\n"
                f"Key Events : `{result.get('keyevents', {}).get('cleared', 0)}`\n"
                f"Super ZB : `{result.get('superzbattles', {}).get('cleared', 0)}`"
            ), inline=True
        )
        embed.add_field(
            name='🎁 Récompenses',
            value=(
                f"Login Bonus : `{result.get('loginbonus', {}).get('claimed', 0)}`\n"
                f"Compensations : ✅\n"
                f"Cadeaux : ✅\n"
                f"Missions : `{result.get('missions', {}).get('claimed', 0)}`"
            ), inline=True
        )
        embed.add_field(
            name='🃏 Cartes',
            value=(
                f"Éveils : `{result.get('awakenall', {}).get('processed', 0)}`\n"
                f"Vendues : `{result.get('autosell', {}).get('sold', 0)}`\n"
                f"Échangées : `{result.get('autosell', {}).get('exchanged', 0)}`"
            ), inline=True
        )
        try:
            summary = await loop.run_in_executor(None, client.get_account_summary)
            embed.add_field(name='💎 Pierres', value=f"**`{summary.get('Stones', '?')}`**", inline=False)
        except Exception:
            pass
    else:
        embed.description = f"```\n{result.get('error', 'Erreur inconnue')}\n```"

    embed.set_footer(text=f'Durée : {elapsed:.1f}s | Prochain farm dans 6h | {ctx.author.display_name}')
    await msg.edit(content='', embed=embed)


# ═══════════════════════════════════════════════════════ COMMANDES ALL

@bot.command(name='stageall')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def stageall(ctx):
    await _run(ctx, 'stageall')

@bot.command(name='areaall')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def areaall(ctx):
    await _run(ctx, 'areaall')

@bot.command(name='ezaall')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def ezaall(ctx):
    await _run(ctx, 'ezaall')

@bot.command(name='superezaall')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def superezaall_cmd(ctx):
    await _run(ctx, 'superezaall')

@bot.command(name='medalsall')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def medalsall(ctx):
    await _run(ctx, 'medalsall')

@bot.command(name='keyzbattlesall')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def keyzbattlesall(ctx):
    await _run(ctx, 'keyzbattlesall')

@bot.command(name='rmbattlesall')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def rmbattlesall(ctx):
    await _run(ctx, 'rmbattlesall')

@bot.command(name='zeniall')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def zeniall(ctx):
    await _run(ctx, 'zeniall')

@bot.command(name='f2pall')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def f2pall(ctx):
    await _run(ctx, 'f2pall')

@bot.command(name='wishesall')
@dc_commands.cooldown(1, 30, dc_commands.BucketType.user)
async def wishesall(ctx):
    await _run(ctx, 'wishesall')

@bot.command(name='bluegemsall')
@dc_commands.cooldown(1, 30, dc_commands.BucketType.user)
async def bluegemsall(ctx):
    await _run(ctx, 'bluegemsall')

@bot.command(name='greengemsall')
@dc_commands.cooldown(1, 30, dc_commands.BucketType.user)
async def greengemsall(ctx):
    await _run(ctx, 'greengemsall')

@bot.command(name='farmlinkall')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def farmlinkall(ctx):
    await _run(ctx, 'farmlinkall')

@bot.command(name='giruall')
@dc_commands.cooldown(1, 30, dc_commands.BucketType.user)
async def giruall(ctx):
    await _run(ctx, 'giruall')

@bot.command(name='cooperationall')
@dc_commands.cooldown(1, 30, dc_commands.BucketType.user)
async def cooperationall(ctx):
    await _run(ctx, 'cooperationall')

@bot.command(name='jointall')
@dc_commands.cooldown(1, 30, dc_commands.BucketType.user)
async def jointall(ctx):
    await _run(ctx, 'jointall')

@bot.command(name='rankall')
@dc_commands.cooldown(1, 60, dc_commands.BucketType.user)
async def rankall(ctx, target_rank: int = 500):
    await _run(ctx, 'rankall', target_rank=target_rank)

@bot.command(name='trainall')
@dc_commands.cooldown(1, 30, dc_commands.BucketType.user)
async def trainall(ctx):
    await _run(ctx, 'trainall')

@bot.command(name='sellall')
@dc_commands.cooldown(1, 20, dc_commands.BucketType.user)
async def sellall(ctx):
    await _run(ctx, 'sellall')

@bot.command(name='exchangeall')
@dc_commands.cooldown(1, 20, dc_commands.BucketType.user)
async def exchangeall(ctx):
    await _run(ctx, 'exchangeall')

@bot.command(name='buyalltreasure')
@dc_commands.cooldown(1, 30, dc_commands.BucketType.user)
async def buyalltreasure(ctx):
    await _run(ctx, 'buyall treasure')

@bot.command(name='buyallbaba')
@dc_commands.cooldown(1, 30, dc_commands.BucketType.user)
async def buyallbaba(ctx):
    await _run(ctx, 'buyall baba')

@bot.command(name='summonall')
@dc_commands.cooldown(1, 10, dc_commands.BucketType.user)
async def summonall(ctx, card_id: int, max_pulls: int = 9999):
    """!summonall <card_id> [max] — Invoque sur toutes les bannières."""
    client = get_client(ctx.author.id)
    if not client:
        await ctx.send('❌ Pas de session active. Tape `!login`.')
        return
    msg     = await ctx.send(f'🔮 **Summon All** — recherche carte `{card_id}` (max `{max_pulls}` pulls)...')
    loop    = asyncio.get_running_loop()
    start   = datetime.now()
    result  = await loop.run_in_executor(None, lambda: dispatch('summonall', client, card_id=card_id, max_pulls=max_pulls))
    elapsed = (datetime.now() - start).total_seconds()
    found   = result.get('found', False)
    embed   = discord.Embed(
        title=f'{"✅" if found else "❌"} Summon All — Carte `{card_id}`',
        color=0x27AE60 if found else 0xE74C3C,
        timestamp=datetime.now()
    )
    if found:
        embed.add_field(name='🎉 Trouvée sur', value=f'`{result.get("banner","?")}`', inline=True)
    embed.add_field(name='🔮 Total pulls',       value=f'`{result.get("total_pulls",0)}`', inline=True)
    embed.add_field(name='💎 Pierres utilisées', value=f'`{result.get("stones_used",0)}`',  inline=True)
    embed.set_footer(text=f'Durée : {elapsed:.1f}s | {ctx.author.display_name}')
    await msg.edit(content='', embed=embed)


# ═══════════════════════════════════════════════════════ AIDE

@bot.command(name='help')
async def help_cmd(ctx):
    embed = discord.Embed(
        title='🐉 DOKKAN BOT — Commandes',
        description='Préfixe : `!` | Commandes sensibles **en MP uniquement**',
        color=0xF4A400
    )
    embed.add_field(name='👤 COMPTE', value=(
        '`!create [GLOBAL|JP]` — nouveau compte *(tutoriel auto)*\n'
        '`!tutorial` — relance le tutoriel\n'
        '`!login [région]` — restaurer la session\n'
        '`!logout` — déconnexion\n'
        '`!transfer <code>` — compte via code\n'
        '`!google <email> <mdp>` *(MP)*\n'
        '`!googlelink <email> <mdp>` *(MP)*\n'
        '`!info` — infos du compte\n'
        '`!myaccount` *(MP)*\n'
        '`!status` — statut du bot'
    ), inline=False)
    embed.add_field(name='🌾 FARM AUTO', value=(
        '`!dailyfarm` — **TOUT en 1** *(6h cooldown)*\n'
        '`!omegafarm` `!stageall` `!areaall`\n'
        '`!ezaall` `!superezaall` `!medalsall`\n'
        '`!keyzbattlesall` `!rmbattlesall`\n'
        '`!zeniall` `!f2pall` `!wishesall`\n'
        '`!bluegemsall` `!greengemsall`\n'
        '`!farmlinkall` `!giruall`\n'
        '`!cooperationall` `!jointall`\n'
        '`!rankall [cible]`'
    ), inline=True)
    embed.add_field(name='🃏 CARTES AUTO', value=(
        '`!awakenall` `!trainall`\n'
        '`!sellall` `!exchangeall`\n'
        '`!buyalltreasure` `!buyallbaba`'
    ), inline=True)
    embed.add_field(name='🃏 CARTES (avec ID)', value=(
        '`!awaken <card_id>`\n'
        '`!awakenuid <uid>`\n'
        '`!train <uid> <feed...>`\n'
        '`!exchange <uid...>`\n'
        '`!sell [rareté]` `!autosell [rareté]`\n'
        '`!team <ids...>` `!deck <id>`\n'
        '`!copyteam <stage>`'
    ), inline=False)
    embed.add_field(name='⚡ STAMINA', value='`!gift` `!refill` `!meat` `!capacity`', inline=True)
    embed.add_field(name='🏪 BOUTIQUES', value=(
        '`!shoptreasure` `!shopzeni`\n'
        '`!shopexchange` `!shopbaba`\n'
        '`!buy <shop> <item_id>`\n'
        '`!buybaba <item_id>`'
    ), inline=True)
    embed.add_field(name='🎁 BONUS', value=(
        '`!loginbonus` `!apologies`\n'
        '`!giru` `!rmbattles`\n'
        '`!cooperation` `!joint`\n'
        '`!resources` `!database` `!ping`'
    ), inline=True)
    embed.add_field(name='🔮 INVOCATIONS', value=(
        '`!summonall <card_id> [max]`\n'
        '`!summon <gacha_id> [course]`\n'
        '`!summoncard <gacha_id> <card_id> [max]`'
    ), inline=False)
    embed.set_footer(text='Dokkan Bot | Bon farming ! 🐉')
    await ctx.send(embed=embed)


# ── Lancement ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    log.info('Démarrage du bot...')
    bot.run(DISCORD_TOKEN)
