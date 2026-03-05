'''
captcha.py — serveur HTTP local pour le captcha Capy Puzzle Dokkan.

Flow exact :
  1. sign_up() sans captcha → Bandai répond 401 + captcha_url + captcha_session_key
     captcha_url = "https://cf.ishin-global.aktsk.com/html/en/captcha/captcha.html
                    ?captcha_session_key=XXX&Expires=...&Signature=..."
     captcha_session_key = la clé à réutiliser dans le 2ème sign_up

  2. discord_bot.py appelle register_session(discord_id, captcha_session_key, captcha_url)
     → stocke la session, retourne une URL locale : http://localhost:8765/captcha?id=XXX&key=YYY

  3. L'user ouvre l'URL → voit la vraie page Bandai en iframe (ou onglet)
     → résout le Capy Puzzle (glisser la pièce)
     → clique OK dans le puzzle
     → clique "J'ai résolu" sur notre page

  4. Notre page POST /submit avec { discord_id, token: captcha_session_key }
     → resolve_captcha() débloque le Future
     → discord_bot.py rappelle sign_up(captcha_key=session_key)
     → compte créé

Routes :
  GET  /captcha          → sert captcha.html
  GET  /get_captcha_url  → { session_key, captcha_key, bandai_url }
  POST /submit           → débloque le bot avec la session_key
'''

import json
import threading
import asyncio
import urllib.request
import urllib.error
import urllib.parse
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs, quote

# discord_id → asyncio.Future[str]  (str = captcha_session_key validée)
pending_captchas: Dict[int, asyncio.Future] = {}

# discord_id → asyncio.Future[str]  (str = google id_token reçu via OAuth callback)
pending_google: Dict[int, asyncio.Future] = {}

# discord_id → (session_key, captcha_key_capy, bandai_url_complète)
pending_sessions: Dict[int, Tuple[str, str, str]] = {}

_SERVER_PORT    = 8765
_server_started = False
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_HTML_PATH = Path(__file__).parent / 'captcha.html'


class _Handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers',
                         'Content-Type, ngrok-skip-browser-warning')
        # Indique à ngrok de ne pas servir sa page d'interstitiel
        self.send_header('ngrok-skip-browser-warning', '1')

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip('/')
        qs     = parse_qs(parsed.query)

        # ── Sert captcha.html ─────────────────────────────────
        if path in ('', '/captcha', '/captcha.html'):
            try:
                data = _HTML_PATH.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self._cors()
                self.end_headers()
                self.wfile.write(data)
            except FileNotFoundError:
                self._text(404, 'captcha.html introuvable')

        # ── Fournit les infos de session au JS ────────────────
        elif path == '/get_captcha_url':
            discord_id = _int(qs.get('id', ['0'])[0])
            session    = pending_sessions.get(discord_id)
            if session:
                session_key, captcha_key, bandai_url = session
                self._json(200, {
                    'session_key': session_key,
                    'captcha_key': captcha_key,
                    'bandai_url':  bandai_url,
                })
            else:
                self._json(404, {'error': 'Aucune session en attente'})

        # ── Lance le flow OAuth Google ────────────────────────
        # L'user arrive ici depuis Discord après !create
        # → redirige vers accounts.google.com avec les bons paramètres
        elif path == '/google_auth':
            discord_id    = qs.get('id', ['0'])[0]
            client_id     = os.getenv('GOOGLE_CLIENT_ID', '')
            host_raw      = self.headers.get('Host', f'localhost:{_SERVER_PORT}')
            is_ngrok_cb   = 'ngrok' in host_raw
            scheme        = 'https' if is_ngrok_cb else 'http'
            host          = host_raw.split(':')[0] if is_ngrok_cb else host_raw
            callback_url  = f'{scheme}://{host}/google_callback'
            if not client_id:
                data = _google_error_html('GOOGLE_CLIENT_ID manquant dans .env')
                self._html(500, data)
                return
            params = urllib.parse.urlencode({
                'client_id':     client_id,
                'redirect_uri':  callback_url,
                'response_type': 'code',
                'scope':         'openid email profile',
                'state':         discord_id,
                'access_type':   'offline',
                'prompt':        'select_account',
            })
            self.send_response(302)
            self.send_header('Location', f'https://accounts.google.com/o/oauth2/v2/auth?{params}')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()

        # ── Reçoit le code OAuth de Google et échange contre id_token ─
        elif path == '/google_callback':
            code       = qs.get('code',  [''])[0]
            state      = qs.get('state', ['0'])[0]   # discord_id
            error      = qs.get('error', [''])[0]
            discord_id = _int(state)

            if error or not code:
                html = _google_error_html(
                    f'Google a refusé la connexion : {error or "code manquant"}.<br>'
                    'Retape <strong>!create</strong> sur Discord.'
                )
                self._html(400, html)
                return

            # Échange le code contre un id_token via le token endpoint Google
            client_id     = os.getenv('GOOGLE_CLIENT_ID', '')
            client_secret = os.getenv('GOOGLE_CLIENT_SECRET', '')
            host_raw      = self.headers.get('Host', f'localhost:{_SERVER_PORT}')
            is_ngrok_cb   = 'ngrok' in host_raw
            scheme        = 'https' if is_ngrok_cb else 'http'
            host          = host_raw.split(':')[0] if is_ngrok_cb else host_raw
            callback_url  = f'{scheme}://{host}/google_callback'

            token_resp = _exchange_google_code(
                code, client_id, client_secret, callback_url)

            id_token     = token_resp.get('id_token', '')
            access_token = token_resp.get('access_token', '')

            # Passe TOUT au bot: code brut + tokens echanges
            # Bandai va tester le server_auth_code en premier
            combined = f'CODE:{code}|ACCESS:{access_token}|ID:{id_token}'
            ok = resolve_google(discord_id, combined)
            if ok:
                email = _decode_jwt_payload(id_token).get('email', '?') if id_token else 'compte lié'
                self._html(200, _google_success_html(email))
            else:
                self._html(400, _google_error_html(
                    'Aucun !create en attente pour cet ID Discord.<br>'
                    'Retape <strong>!create</strong> sur Discord.'
                ))

        else:
            self._text(404, 'Not found')

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length)

        # ── Reçoit la session_key une fois le puzzle résolu ───
        if self.path == '/submit':
            try:
                data       = json.loads(body)
                discord_id = _int(data.get('discord_id', 0))
                token      = data.get('token', '').strip()

                if not discord_id or not token:
                    self._json(400, {'ok': False, 'error': 'discord_id ou token manquant'})
                    return

                ok = resolve_captcha(discord_id, token)
                if ok:
                    pending_sessions.pop(discord_id, None)
                    self._json(200, {'ok': True})
                else:
                    self._json(400, {'ok': False, 'error': 'Aucune session en attente pour cet ID'})
            except Exception as e:
                self._json(500, {'ok': False, 'error': str(e)})
        else:
            self._text(404, 'Not found')

    # ── Helpers ───────────────────────────────────────────────
    def _json(self, code, data):
        b = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self._cors()
        self.end_headers()
        self.wfile.write(b)

    def _html(self, code, html: str):
        b = html.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self._cors()
        self.end_headers()
        self.wfile.write(b)

    def _text(self, code, msg):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self._cors()
        self.end_headers()
        self.wfile.write(msg.encode())

    def log_message(self, fmt, *args):
        pass  # Silence les logs HTTP


def _int(v) -> int:
    try:    return int(v)
    except: return 0


def _extract_capy_key(captcha_url: str) -> str:
    '''
    Extrait le PUZZLE_xxx depuis l'URL Bandai.
    L'URL retournée par Bandai est du type :
    https://cf.ishin-global.aktsk.com/html/en/captcha/captcha.html
      ?captcha_session_key=XXX&captcha_key=PUZZLE_yyy&Expires=...&Signature=...
    '''
    try:
        params = parse_qs(urlparse(captcha_url).query)
        if 'captcha_key' in params:
            return params['captcha_key'][0]
    except Exception:
        pass
    # Valeur observée dans les traces réseau (peut changer selon la version)
    return 'PUZZLE_MipeuEovNXMZmN9AsSbXQJ1MxghJnA'


# ══════════════════════════════════════════════════════════════
#  API PUBLIQUE
# ══════════════════════════════════════════════════════════════

def start_server(port: int = _SERVER_PORT,
                 loop: asyncio.AbstractEventLoop = None) -> int:
    global _server_started, _SERVER_PORT, _event_loop
    if _server_started:
        return _SERVER_PORT
    _SERVER_PORT = port
    _event_loop  = loop or asyncio.get_event_loop()
    httpd = HTTPServer(('0.0.0.0', port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _server_started = True
    print(f'[captcha] Serveur démarré sur http://0.0.0.0:{port}')
    return port


def register_session(discord_id: int, captcha_session_key: str,
                     captcha_url: str, host: str = 'localhost') -> str:
    '''
    Enregistre la session captcha et retourne l'URL locale à envoyer à l'user.

    captcha_session_key : la clé retournée par Bandai dans le 401
    captcha_url         : l'URL complète Bandai (avec Signature CloudFront)
                          → passée à l'iframe pour afficher le vrai puzzle
    '''
    captcha_key = _extract_capy_key(captcha_url)
    pending_sessions[discord_id] = (captcha_session_key, captcha_key, captcha_url)

    # Si le host est un tunnel ngrok (ou autre domaine public), utiliser HTTPS sans port.
    # ngrok expose en HTTPS sur le port 443 — pas http://host:8765.
    is_ngrok = ('ngrok' in host or '.' in host.split(':')[0] and not host.startswith('localhost'))
    if is_ngrok:
        # URL publique : https://abc.ngrok-free.app/captcha?...
        base_url = f'https://{host}/captcha'
    else:
        # URL locale : http://localhost:8765/captcha?...
        base_url = f'http://{host}:{_SERVER_PORT}/captcha'

    public_url = (
        f'{base_url}'
        f'?id={discord_id}'
        f'&key={quote(captcha_session_key, safe="")}'
        f'&captcha_key={captcha_key}'
    )
    return public_url


def _exchange_google_code(code: str, client_id: str, client_secret: str,
                          redirect_uri: str) -> dict:
    '''Échange un authorization code Google contre un id_token.'''
    body = urllib.parse.urlencode({
        'code':          code,
        'client_id':     client_id,
        'client_secret': client_secret,
        'redirect_uri':  redirect_uri,
        'grant_type':    'authorization_code',
    }).encode()
    req = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {'error': e.read().decode('utf-8', errors='replace')}
    except Exception as e:
        return {'error': str(e)}


def _decode_jwt_payload(token: str) -> dict:
    '''Décode le payload d'un JWT sans vérification de signature.'''
    import base64
    try:
        parts = token.split('.')
        if len(parts) < 2:
            return {}
        pad = parts[1] + '=' * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(pad))
    except Exception:
        return {}


def _google_success_html(email: str) -> str:
    return f'''<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dokkan Bot — Google lié</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',sans-serif;background:#0f1626;color:#eee;
     display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}}
.card{{background:#1a2744;border:1px solid #27ae60;border-radius:14px;
       padding:40px 32px;max-width:440px;width:100%;text-align:center;
       box-shadow:0 8px 40px rgba(0,0,0,.5)}}
.icon{{font-size:3.5rem;margin-bottom:12px}}
h1{{color:#2ecc71;font-size:1.4rem;margin-bottom:10px}}
.email{{background:#0d1420;border:1px solid #27ae60;border-radius:8px;
        padding:10px 16px;color:#7ec8e3;font-size:.9rem;margin:14px 0;
        word-break:break-all}}
p{{color:#aaa;font-size:.87rem;line-height:1.6}}
strong{{color:#fff}}
</style></head><body>
<div class="card">
  <div class="icon">✅</div>
  <h1>Compte Google lié !</h1>
  <div class="email">{email}</div>
  <p>Ton compte Dokkan Battle est maintenant sauvegardé<br>
  sur ce compte Google.<br><br>
  <strong>Retourne sur Discord</strong> — ton compte est prêt.</p>
</div>
</body></html>'''


def _google_error_html(msg: str) -> str:
    return f'''<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dokkan Bot — Erreur</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',sans-serif;background:#0f1626;color:#eee;
     display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}}
.card{{background:#1a2744;border:1px solid #e74c3c;border-radius:14px;
       padding:40px 32px;max-width:440px;width:100%;text-align:center;
       box-shadow:0 8px 40px rgba(0,0,0,.5)}}
.icon{{font-size:3.5rem;margin-bottom:12px}}
h1{{color:#e74c3c;font-size:1.3rem;margin-bottom:10px}}
p{{color:#ccc;font-size:.87rem;line-height:1.7}}
</style></head><body>
<div class="card">
  <div class="icon">❌</div>
  <h1>Erreur de liaison Google</h1>
  <p>{msg}</p>
</div>
</body></html>'''


# ── API publique Google ────────────────────────────────────────

def get_google_auth_url(discord_id: int, host: str = 'localhost') -> str:
    '''Retourne l'URL locale qui lance le flow OAuth Google.'''
    is_ngrok = ('ngrok' in host or '.' in host.split(':')[0] and not host.startswith('localhost'))
    if is_ngrok:
        return f'https://{host}/google_auth?id={discord_id}'
    return f'http://{host}:{_SERVER_PORT}/google_auth?id={discord_id}'


async def wait_for_google(discord_id: int, timeout: int = 300) -> Optional[str]:
    '''
    Attend que l'user connecte son Google via OAuth.
    Retourne l'id_token Google, ou None si timeout.
    '''
    loop   = asyncio.get_event_loop()
    future = loop.create_future()
    pending_google[discord_id] = future
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        pending_google.pop(discord_id, None)


def resolve_google(discord_id: int, id_token: str) -> bool:
    '''Appelé par GET /google_callback — débloque wait_for_google().'''
    future = pending_google.get(discord_id)
    if future and not future.done():
        if _event_loop and _event_loop.is_running():
            _event_loop.call_soon_threadsafe(future.set_result, id_token)
        else:
            future.set_result(id_token)
        return True
    return False


async def wait_for_token(discord_id: int, timeout: int = 300) -> Optional[str]:
    '''
    Attend que l'user résolve le puzzle.
    Retourne la captcha_session_key validée, ou None si timeout.
    '''
    loop   = asyncio.get_event_loop()
    future = loop.create_future()
    pending_captchas[discord_id] = future
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        pending_captchas.pop(discord_id, None)


def resolve_captcha(discord_id: int, token: str) -> bool:
    '''
    Appelé par POST /submit quand l'user a résolu le puzzle.
    token = captcha_session_key (la même que celle retournée par Bandai dans le 401).
    Retourne True si quelqu'un attendait.
    '''
    future = pending_captchas.get(discord_id)
    if future and not future.done():
        if _event_loop and _event_loop.is_running():
            _event_loop.call_soon_threadsafe(future.set_result, token)
        else:
            future.set_result(token)
        return True
    return False
