"""
dokkan_captcha.py — résolution du captcha Capy Puzzle de Dokkan Battle.

Flow réel (d'après les traces réseau) :
  1. sign_up() sans captcha → Bandai retourne une URL signée CloudFront :
     https://cf.ishin-global.aktsk.com/html/en/captcha/captcha.html
       ?captcha_session_key=<KEY>&Expires=...&Signature=...
  2. !create → bot détecte NeedsCaptchaError et envoie ce lien à l'user
  3. L'user ouvre la page → le puzzle Capy se charge depuis puzzleauth.captchasolutionweb.com
  4. L'user résout le puzzle → la page POST à Bandai /captcha/authorize
  5. Si succès, la page POST /submit ici avec la captcha_session_key validée
  6. Le bot reçoit la clé et rappelle sign_up(captcha_key=KEY) → compte créé

Le captcha n'est PAS reCAPTCHA — c'est Capy Puzzle (slide puzzle).
La captcha_session_key vient de Bandai dès le premier sign_up() raté,
pas d'un service tiers.
"""

import json
import os
import threading
import asyncio
import requests as _http   # pour proxy /captcha_page et /captcha_auth_proxy
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs

# ── Constantes ────────────────────────────────────────────────────────────────
# Le captcha_key Capy (PUZZLE_xxx) est inclus dans l'URL retournée par Bandai.
# Il peut changer à chaque session — on le stocke par discord_id.
CAPY_AUTHORIZE_URL = 'https://ishin-global.aktsk.com/captcha/authorize'

# discord_id → asyncio.Future[str]  (str = captcha_session_key validée)
pending_captchas: Dict[int, asyncio.Future] = {}

# discord_id → (captcha_session_key, captcha_key_capy, captcha_url_full)
pending_sessions: Dict[int, Tuple[str, str, str]] = {}

# discord_id → asyncio.Future[str]  (str = code de transfert saisi par l'user)
pending_transfers: Dict[int, asyncio.Future] = {}

_SERVER_PORT    = 8765
_server_started = False
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_HTML_PATH = Path(__file__).parent / 'captcha.html'


class _CaptchaHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip('/')

        # Sert la page captcha.html
        if path in ('', '/captcha', '/captcha.html'):
            try:
                html = _HTML_PATH.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'captcha.html introuvable')

        # Fournit session_key + captcha_key au JS quand il ne les a pas dans l'URL
        elif path == '/get_captcha_url':
            qs         = parse_qs(parsed.query)
            discord_id = int(qs.get('id', ['0'])[0])
            session    = pending_sessions.get(discord_id)
            if session:
                session_key, captcha_key, full_url = session
                self._json(200, {
                    'session_key': session_key,
                    'captcha_key': captcha_key,
                    'full_url':    full_url,
                })
            else:
                self._json(404, {'error': 'Aucune session en attente'})

        # ── NOUVEAU : proxy de la page captcha Bandai ─────────────────────────
        # Récupère la page CloudFront Bandai et injecte un intercepteur JS qui
        # redirige les appels /captcha/authorize vers notre serveur local.
        # Notre serveur les retransmet via PROXY_URL (IP US), contournant le
        # blocage géographique qui empêche le navigateur de l'user d'atteindre
        # ishin-global.aktsk.com depuis la France.
        elif path == '/captcha_page':
            qs            = parse_qs(parsed.query)
            discord_id_s  = qs.get('id', ['0'])[0]
            discord_id    = int(discord_id_s)
            session       = pending_sessions.get(discord_id)
            if not session:
                self.send_response(404)
                self.end_headers()
                self.wfile.write('Session expirée — retape !create.'.encode())
                return

            session_key, captcha_key, full_url = session
            host = self.headers.get('Host', f'localhost:{_SERVER_PORT}')
            proxy_auth_url = f'http://{host}/captcha_auth_proxy?id={discord_id_s}'

            # Récupère la page Bandai CF (avec l'URL signée complète)
            try:
                r = _http.get(full_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                    'Accept': 'text/html,application/xhtml+xml,*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                }, timeout=15)
                html = r.text
            except Exception as e:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(f'Erreur récupération page Bandai : {e}'.encode())
                return

            # 1) Balise <base> pour que les assets relatifs (CSS/JS) se chargent
            base_tag = '<base href="https://cf.ishin-global.aktsk.com/">\n'
            html = html.replace('<head>', '<head>\n' + base_tag, 1)

            # 2) Injection JS : intercepte TOUS les appels fetch/XHR vers
            #    /captcha/authorize et les redirige vers notre proxy local.
            #    Fonctionne même si l'URL est construite dynamiquement par le JS Capy.
            intercept_js = f'''<script>
(function() {{
  var TARGET = 'captcha/authorize';
  var PROXY  = {json.dumps(proxy_auth_url)};

  // Intercepteur fetch
  var _fetch = window.fetch.bind(window);
  window.fetch = function(input, init) {{
    var url = (input instanceof Request) ? input.url : String(input);
    if (url.indexOf(TARGET) !== -1) {{
      console.log('[captcha-proxy] fetch intercepté → proxy', url);
      if (input instanceof Request) {{
        input = new Request(PROXY, input);
      }} else {{
        input = PROXY;
      }}
    }}
    return _fetch(input, init);
  }};

  // Intercepteur XMLHttpRequest
  var _open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url) {{
    var rest = Array.prototype.slice.call(arguments, 2);
    if (typeof url === 'string' && url.indexOf(TARGET) !== -1) {{
      console.log('[captcha-proxy] XHR intercepté → proxy', url);
      url = PROXY;
    }}
    return _open.apply(this, [method, url].concat(rest));
  }};
}})();
</script>\n'''

            # Injecter avant </head> (doit être le plus tôt possible)
            if '</head>' in html:
                html = html.replace('</head>', intercept_js + '</head>', 1)
            else:
                html = intercept_js + html

            # 3) Remplacement de chaîne en dur en backup
            for auth_url in [
                'https://ishin-global.aktsk.com/captcha/authorize',
                'http://ishin-global.aktsk.com/captcha/authorize',
            ]:
                html = html.replace(auth_url, proxy_auth_url)

            encoded = html.encode('utf-8', errors='replace')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(encoded)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(encoded)

        # Page web pour !login — saisie du code de transfert
        elif path.startswith('/transfer'):
            try:
                html = _TRANSFER_HTML.encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html)
            except Exception as e:
                self.send_response(500)
                self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/submit':
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)
            try:
                data       = json.loads(body)
                discord_id = int(data.get('discord_id', 0))
                token      = data.get('token', '').strip()

                if not discord_id or not token:
                    self._json(400, {'ok': False, 'error': 'discord_id ou token manquant'})
                    return

                ok = resolve_captcha(discord_id, token)
                if ok:
                    pending_sessions.pop(discord_id, None)
                    self._json(200, {'ok': True})
                else:
                    self._json(400, {'ok': False, 'error': 'Aucune création en attente pour cet ID'})
            except Exception as e:
                self._json(500, {'ok': False, 'error': str(e)})
        elif self.path == '/submit_transfer':
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)
            try:
                data       = json.loads(body)
                discord_id = int(data.get('discord_id', 0))
                code       = data.get('transfer_code', '').strip()
                if not discord_id or not code:
                    self._json(400, {'ok': False, 'error': 'discord_id ou code manquant'})
                    return
                future = pending_transfers.get(discord_id)
                if future and not future.done():
                    if _event_loop and _event_loop.is_running():
                        _event_loop.call_soon_threadsafe(future.set_result, code)
                    else:
                        future.set_result(code)
                    self._json(200, {'ok': True})
                else:
                    self._json(400, {'ok': False, 'error': 'Aucune session !login en attente'})
            except Exception as e:
                self._json(500, {'ok': False, 'error': str(e)})

        # ── NOUVEAU : proxy vers ishin-global.aktsk.com/captcha/authorize ─────
        # Reçoit les appels Capy interceptés depuis /captcha_page et les
        # retransmet à Bandai via PROXY_URL (IP US).
        # En cas de succès (HTTP 200), résout automatiquement la future du bot :
        # l'utilisateur n'a PAS besoin de cliquer "J'ai résolu".
        elif self.path.startswith('/captcha_auth_proxy'):
            length      = int(self.headers.get('Content-Length', 0))
            body        = self.rfile.read(length)
            parsed_path = urlparse(self.path)
            qs          = parse_qs(parsed_path.query)
            discord_id  = int(qs.get('id', ['0'])[0])

            proxy_env = os.getenv('PROXY_URL', '').strip()
            proxies   = {'http': proxy_env, 'https': proxy_env} if proxy_env else None

            try:
                r = _http.post(
                    'https://ishin-global.aktsk.com/captcha/authorize',
                    data=body,
                    headers={
                        'Content-Type': self.headers.get('Content-Type', 'application/json'),
                        'User-Agent':   'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                        'Origin':       'https://cf.ishin-global.aktsk.com',
                        'Referer':      'https://cf.ishin-global.aktsk.com/',
                        'Accept':       '*/*',
                    },
                    proxies=proxies,
                    timeout=15,
                )

                resp_body = r.content
                self.send_response(r.status_code)
                self.send_header('Content-Type',
                                 r.headers.get('Content-Type', 'application/json'))
                self.send_header('Content-Length', str(len(resp_body)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(resp_body)

                print(f'[captcha_proxy] /captcha/authorize → HTTP {r.status_code} | {r.text[:200]}')

                # Résolution automatique si Bandai confirme le captcha
                if r.status_code == 200:
                    session = pending_sessions.get(discord_id)
                    if session:
                        ok = resolve_captcha(discord_id, session[0])
                        if ok:
                            pending_sessions.pop(discord_id, None)
                            print(f'[captcha_proxy] ✅ Auto-résolu discord_id={discord_id}')

            except Exception as e:
                print(f'[captcha_proxy] Erreur forward : {e}')
                self._json(502, {'ok': False, 'error': str(e)})
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def start_server(port: int = _SERVER_PORT,
                 loop: asyncio.AbstractEventLoop = None) -> int:
    global _server_started, _SERVER_PORT, _event_loop
    if _server_started:
        return _SERVER_PORT
    _SERVER_PORT = port
    _event_loop  = loop or asyncio.get_event_loop()
    httpd = HTTPServer(('0.0.0.0', port), _CaptchaHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _server_started = True
    print(f'[captcha] Serveur démarré sur http://0.0.0.0:{port}')
    return port


def register_session(discord_id: int, captcha_session_key: str,
                     captcha_url: str, host: str = 'localhost') -> str:
    """
    Enregistre les infos du captcha pour un user et retourne l'URL à envoyer dans Discord.

    captcha_session_key : la clé retournée par Bandai lors du sign_up raté
    captcha_url         : l'URL complète (cf.ishin-global.aktsk.com/html/en/captcha/...)
                          contenant le captcha_key Capy (PUZZLE_xxx)

    Retourne l'URL locale à partager avec l'utilisateur.
    """
    # Extrait le captcha_key Capy depuis l'URL Bandai
    # L'URL contient ?captcha_session_key=...&Expires=...&Signature=...
    # Le Capy captcha_key est dans les paramètres de la page CF ou dans le body HTML
    # On stocke l'URL complète et on la passe au JS pour qu'il la parse
    captcha_key = _extract_capy_key(captcha_url)

    pending_sessions[discord_id] = (captcha_session_key, captcha_key, captcha_url)

    # URL locale pour l'user : on passe session_key + discord_id
    local_url = (
        f'http://{host}:{_SERVER_PORT}/captcha'
        f'?id={discord_id}'
        f'&key={captcha_session_key}'
        f'&captcha_key={captcha_key}'
    )
    return local_url


def _extract_capy_key(captcha_url: str) -> str:
    """Extrait le PUZZLE_xxx depuis l'URL Bandai ou retourne la valeur par défaut."""
    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(captcha_url)
        params = parse_qs(parsed.query)
        # Bandai inclut parfois captcha_key dans l'URL
        if 'captcha_key' in params:
            return params['captcha_key'][0]
    except Exception:
        pass
    # Valeur observée dans les traces réseau — peut changer
    return 'PUZZLE_MipeuEovNXMZmN9AsSbXQJ1MxghJnA'


def get_captcha_url(host: str = 'localhost', discord_id: int = 0) -> str:
    """URL simple sans paramètres (le JS les récupère via /get_captcha_url)."""
    return f'http://{host}:{_SERVER_PORT}/captcha?id={discord_id}'


async def wait_for_token(discord_id: int, timeout: int = 300) -> Optional[str]:
    """Attend que l'user résolve le captcha. Retourne la captcha_session_key ou None."""
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
    """
    Appelé par /submit quand l'user a résolu le puzzle.
    token = captcha_session_key validée par Bandai.
    Retourne True si quelqu'un attendait.
    """
    future = pending_captchas.get(discord_id)
    if future and not future.done():
        if _event_loop and _event_loop.is_running():
            _event_loop.call_soon_threadsafe(future.set_result, token)
        else:
            future.set_result(token)
        return True
    return False


_TRANSFER_HTML = b"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dokkan Bot - Connexion</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',sans-serif;background:#0f1626;color:#eee;
       display:flex;align-items:center;justify-content:center;min-height:100vh}
  .card{background:#1a2744;border:1px solid #2a3a60;border-radius:14px;
        padding:40px;max-width:480px;width:90%;text-align:center;
        box-shadow:0 8px 32px rgba(0,0,0,0.5)}
  h1{font-size:1.5rem;color:#f4a400;margin-bottom:8px}
  p{color:#aaa;font-size:.9rem;line-height:1.6;margin-bottom:20px}
  hr{border:none;border-top:1px solid #2a3a60;margin:20px 0}
  .step{display:flex;gap:12px;text-align:left;margin-bottom:10px;align-items:flex-start}
  .n{background:#f4a400;color:#000;border-radius:50%;width:24px;height:24px;
     display:flex;align-items:center;justify-content:center;font-weight:bold;
     font-size:.8rem;flex-shrink:0;margin-top:2px}
  .t{font-size:.88rem;color:#ccc}
  input{width:100%;padding:14px;margin:16px 0 8px;border-radius:8px;
        background:#0d1420;border:1px solid #2a3a60;color:#fff;font-size:1rem;
        text-align:center;letter-spacing:.1em}
  input:focus{outline:none;border-color:#f4a400}
  button{width:100%;padding:14px;background:#f4a400;color:#111;border:none;
         border-radius:8px;font-size:1rem;font-weight:bold;cursor:pointer;margin-top:8px}
  button:hover{background:#e09500}
  button:disabled{background:#555;color:#888;cursor:not-allowed}
  #status{margin-top:14px;padding:12px;border-radius:8px;font-size:.88rem;display:none}
  #status.ok{background:#1a4a2e;color:#27ae60;border:1px solid #27ae60}
  #status.err{background:#4a1a1a;color:#e74c3c;border:1px solid #e74c3c}
  #status.wait{background:#1a2a4a;color:#7ec8e3;border:1px solid #3498db}
</style>
</head>
<body>
<div class="card">
  <h1>&#128273; Connexion compte existant</h1>
  <p>Connecte ton compte Dokkan Battle existant via le code de transfert.</p>
  <hr>
  <div class="step"><div class="n">1</div>
    <div class="t">Dans Dokkan &#8594; Menu &#8594; Param&egrave;tres &#8594; <strong>Transfert de donn&eacute;es</strong> &#8594; <strong>&Eacute;mettre un code</strong></div>
  </div>
  <div class="step"><div class="n">2</div>
    <div class="t">Copie le code (16 caract&egrave;res, valable 24h)</div>
  </div>
  <div class="step"><div class="n">3</div>
    <div class="t">Colle-le ci-dessous et clique <strong>Valider</strong></div>
  </div>
  <hr>
  <input type="text" id="code" placeholder="ABCD1234EFGH5678" maxlength="20"
         oninput="document.getElementById('btn').disabled=this.value.trim().length<8">
  <button id="btn" onclick="send()" disabled>&#10003; Valider &amp; Connecter</button>
  <div id="status"></div>
</div>
<script>
const discordId = new URLSearchParams(location.search).get('id');
function setStatus(msg, cls) {
  const el = document.getElementById('status');
  el.textContent = msg; el.className = cls; el.style.display = 'block';
}
async function send() {
  const code = document.getElementById('code').value.trim();
  if (!code) return;
  document.getElementById('btn').disabled = true;
  setStatus('Connexion en cours...', 'wait');
  try {
    const r = await fetch('/submit_transfer', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({discord_id: parseInt(discordId), transfer_code: code})
    });
    const data = await r.json();
    if (data.ok) {
      setStatus('Compte connecte ! Retourne sur Discord.', 'ok');
      document.getElementById('btn').textContent = 'Envoye !';
    } else {
      setStatus(data.error || 'Erreur inconnue', 'err');
      document.getElementById('btn').disabled = false;
    }
  } catch(e) {
    setStatus('Erreur reseau : ' + e.message, 'err');
    document.getElementById('btn').disabled = false;
  }
}
</script>
</body>
</html>"""


async def wait_for_transfer(discord_id: int, timeout: int = 300) -> Optional[str]:
    """Attend que l'user entre son code de transfert. Retourne le code ou None si timeout."""
    loop   = asyncio.get_event_loop()
    future = loop.create_future()
    pending_transfers[discord_id] = future
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        pending_transfers.pop(discord_id, None)
