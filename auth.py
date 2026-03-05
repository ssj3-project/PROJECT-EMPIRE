'''
auth.py — authentification Dokkan Battle.

FLOW COMPLET CRÉATION DE COMPTE
  1. POST /captcha/inquiry
  2. GET  /auth/nonce         → auth_transaction_id
  3. POST /auth/sign_up       → HTTP 401 + NeedsCaptchaError
  4. POST /auth/sign_up       (avec captcha_session_key) → HTTP 200
  5. POST /auth/sign_in       → access_token (Bearer)
  6. GET  /user               → user_id, rank, stones
  7. GET  /resources/login    → initialise le compte (AVANT gasha)
  8. POST /tutorial/gasha     → invocation tutorial (APRÈS resources/login)
  9. GET  /resources/login    → recharge après gasha
  10.POST /auth/link_codes    → Transfer Code

POINTS CRITIQUES
  - auth_transaction_id IDENTIQUE dans appels 3, 4, 5
  - ad_id/unique_id IDENTIQUES dans appels 3, 4, 5
  - Appel 4 : PAS de device_token/reason
  - sign_in ne retourne PAS user_id → GET /user obligatoire après
  - Bearer token = access_token retourné par sign_in
  - Basic auth = base64(password:username) (inversé)
  - resources/login AVANT tutorial/gasha (sinon gasha → HTTP 400)
  - POST /tutorial/finish N'EXISTE PAS (→ HTTP 404)

FIX v2 :
  - _extract_identifier() / _extract_secret() : recherche récursive dans tout le body
  - sign_in() retourne aussi le secret → récupéré dans _finalize()
  - Fallback : si identifier vide après sign_up, on tente sign_in quand même
  - Logs ✓/✗ sur identifier et secret pour diagnostic
'''

import hashlib
import logging
import requests
import config
import crypto
import json
from typing import Optional, Dict


log = logging.getLogger('DokkanBot')


class NeedsCaptchaError(Exception):
    def __init__(self, captcha_url: str = '', captcha_session_key: str = ''):
        self.captcha_url         = captcha_url
        self.captcha_session_key = captcha_session_key
        super().__init__(f'Captcha requis : {captcha_url}')


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def _base(ver):   return config.gb_url    if ver == 'gb' else config.jp_url
def _bundle(ver): return config.bundle_id if ver == 'gb' else config.bundle_id_jp
def _code(ver):   return config.gb_code   if ver == 'gb' else config.jp_code
def _dua(os):     return config.device_agent1 if os == 'android' else config.device_agent2
def _dev(os):
    if os == 'android':
        return config.device_name1, config.device_model1, config.device_ver1, config.device_agent1
    return config.device_name2, config.device_model2, config.device_ver2, config.device_agent2

def _headers_noauth(ver, os):
    return {
        'Accept-Encoding': 'gzip',
        'Connection':      'Keep-Alive',
        'Content-Type':    'application/json',
        'X-Platform':      os,
        'X-ClientVersion': _code(ver),
        'X-Language':      config.lang,
        'User-Agent':      _dua(os),
    }

def _headers_bearer(ver, os, token):
    return {
        'Accept':            '*/*',
        'Accept-Encoding':   'gzip',
        'Authorization':     f'Bearer {token}',
        'Connection':        'Keep-Alive',
        'Content-Type':      'application/json',
        'X-AssetVersion':    config.file_ts1 or '0',
        'X-ClientVersion':   _code(ver),
        'X-DatabaseVersion': config.db_ts1 or '0',
        'X-Language':        config.lang,
        'X-Platform':        os,
        'X-RequestVersion':  '4',
        'User-Agent':        _dua(os),
    }


# ══════════════════════════════════════════════════════════════
#  EXTRACTION ROBUSTE identifier / secret
# ══════════════════════════════════════════════════════════════

def _extract_identifier(body: dict) -> str:
    '''
    Cherche identifier dans toutes les structures connues du body sign_up/sign_in.
    Retourne la première valeur non-vide trouvée.
    '''
    # Niveau racine
    v = body.get('identifier', '')
    if v:
        return str(v)

    # Sous-objets courants
    for key in ('user_account', 'account', 'user'):
        sub = body.get(key)
        if isinstance(sub, dict):
            v = sub.get('identifier', '')
            if v:
                return str(v)

    # Recherche récursive niveau 2
    for val in body.values():
        if isinstance(val, dict):
            for k2, v2 in val.items():
                if k2 == 'identifier' and v2:
                    return str(v2)

    return ''


def _extract_secret(body: dict) -> str:
    '''
    Cherche secret dans toutes les structures connues du body sign_up/sign_in.
    Retourne la première valeur non-vide trouvée.
    Recherche récursive complète sur tous les niveaux d'imbrication.
    '''
    def _recursive_search(obj, depth=0):
        if depth > 10:
            return ''
        if isinstance(obj, dict):
            v = obj.get('secret', '')
            if v:
                return str(v)
            for val in obj.values():
                found = _recursive_search(val, depth + 1)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _recursive_search(item, depth + 1)
                if found:
                    return found
        return ''

    # Niveau racine
    v = body.get('secret', '')
    if v:
        return str(v)

    # Sous-objets courants en priorité
    for key in ('user_account', 'account', 'user'):
        sub = body.get(key)
        if isinstance(sub, dict):
            v = sub.get('secret', '')
            if v:
                return str(v)

    # Recherche récursive complète sur tout le body
    return _recursive_search(body)


# ══════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════

def captcha_inquiry(ver: str, os: str, ad_id: str) -> dict:
    url    = _base(ver) + '/captcha/inquiry'
    hashed = hashlib.sha1(ad_id.encode()).hexdigest()
    try:
        r = requests.post(url, data=json.dumps({'hashed_device_id': hashed, 'platform': os}),
                          headers=_headers_noauth(ver, os), timeout=10)
        return r.json()
    except Exception:
        return {}


def get_nonce(ver: str, os: str) -> dict:
    url = _base(ver) + '/auth/nonce'
    try:
        r = requests.get(url, headers={
            'Accept-Encoding': 'gzip', 'Connection': 'Keep-Alive',
            'X-Platform': os, 'X-ClientVersion': _code(ver), 'User-Agent': _dua(os),
        }, timeout=10)
        return r.json()
    except Exception:
        return {}


def sign_up_request(ver: str, os: str, ad_id: str, unique_id: str,
                    tx_id: str, captcha_key: Optional[str] = None) -> requests.Response:
    dn, dm, dv, _ = _dev(os)
    body = {
        'bundle_id':           _bundle(ver),
        'auth_transaction_id': tx_id,
        'user_account': {
            'ad_id':           ad_id,
            'country':         config.country,
            'currency':        config.currency,
            'device':          dn,
            'device_model':    dm,
            'os_version':      dv,
            'platform':        os,
            'unique_id':       unique_id,
            'graphics_api':    'vulkan1.1.0,gles3.1',
            'is_usable_astc':  True,
            'os_architecture': 'x86_64,arm64-v8a',
        },
    }
    if captcha_key:
        body['captcha_session_key'] = captcha_key
    else:
        body['device_token'] = 'failed'
        body['reason']       = 'PLAY_STORE_NOT_FOUND'
    return requests.post(_base(ver) + '/auth/sign_up',
                         data=json.dumps(body),
                         headers=_headers_noauth(ver, os), timeout=15)


def sign_in_request(ver: str, os: str, identifier: str,
                    ad_id: str, unique_id: str, tx_id: Optional[str] = None) -> dict:
    dn, dm, dv, dua = _dev(os)
    basic = crypto.basic(identifier)
    headers = {
        'Accept-Encoding': 'gzip',
        'Authorization':   'Basic ' + basic,
        'Connection':      'Keep-Alive',
        'Content-Type':    'application/json',
        'Host':            _base(ver).replace('https://', ''),
        'X-UserCountry':   config.country,
        'X-UserCurrency':  config.currency,
        'X-Platform':      os,
        'X-ClientVersion': _code(ver),
        'X-Language':      config.lang,
        'User-Agent':      dua,
    }
    body = {
        'bundle_id':    _bundle(ver),
        'user_account': {
            'ad_id':           ad_id,
            'device':          dn,
            'device_model':    dm,
            'os_version':      dv,
            'platform':        os,
            'unique_id':       unique_id,
            'graphics_api':    'vulkan1.1.0,gles3.1',
            'is_usable_astc':  True,
            'os_architecture': 'x86_64,arm64-v8a',
            'voice':           'ja',
        },
    }
    if tx_id:
        body['auth_transaction_id'] = tx_id
    try:
        r = requests.post(_base(ver) + '/auth/sign_in',
                          data=json.dumps(body), headers=headers, timeout=15)
        return r.json()
    except Exception as e:
        return {'error': str(e)}


def get_user_request(ver: str, os: str, token: str) -> dict:
    try:
        r = requests.get(_base(ver) + '/user', headers={
            'Accept': '*/*', 'Accept-Encoding': 'gzip',
            'Authorization':     f'Bearer {token}',
            'Connection':        'Keep-Alive',
            'X-AssetVersion':    '////',
            'X-ClientVersion':   _code(ver),
            'X-DatabaseVersion': '////',
            'X-Language':        config.lang,
            'X-Platform':        os,
            'X-RequestVersion':  '4',
            'User-Agent':        _dua(os),
        }, timeout=10)
        data = r.json()
        data['_http_status'] = r.status_code
        return data
    except Exception as e:
        return {'error': str(e), '_http_status': 0}


def client_assets_database_request(ver: str, os: str, token: str) -> dict:
    try:
        r = requests.get(_base(ver) + '/client_assets/database',
                         headers=_headers_bearer(ver, os, token), timeout=15)
        if r.status_code == 200:
            data   = r.json()
            db_ver = (data.get('database_version') or data.get('version')
                      or data.get('db_version') or str(data.get('id', '')))
            if db_ver and str(db_ver).isdigit():
                if ver == 'gb':
                    config.db_ts1 = str(db_ver)
                else:
                    config.db_ts2 = str(db_ver)
            return data
        return {'_http_status': r.status_code}
    except Exception as e:
        return {'error': str(e)}


def resources_login_request(ver: str, os: str, token: str,
                             user_card_updated_at: int = 0,
                             mission_updated_at: Optional[int] = None) -> dict:
    ep = ('/resources/login?act_items=true&announcements=true&awakening_items=true'
          '&budokai=true&card_sticker_items=true&card_tags=true&cards=true'
          '&cooperation_campaigns=true&dragonball_sets=true&equipment_skill_items=true'
          '&eventkagi_items=true&friendships=true&gashas=true&genkai_battles=true'
          '&gifts=true&joint_campaigns=true&jukeboxes=true&link_skill_lv_up_items=true'
          '&login_movies=true&missions=true&platform_country=&potential_items=true'
          '&rmbattles=true&sd/battle=true&sd/characters=true&sd/packs=true'
          '&secret_treasure_boxes=true&shops/treasure/items=true&sns_campaign=true'
          '&special_items=true&support_films=true&support_items=true&support_leaders=true'
          '&support_memories=true&support_memory_enhancement_items=true&teams=true'
          '&training_fields=true&training_items=true&treasure_items=true&user=true'
          f'&user_areas=true&user_card_updated_at={user_card_updated_at}'
          + (f'&mission_updated_at={mission_updated_at}' if mission_updated_at else '')
          + '&user_subscription=true&wallpaper_items=true')

    hdrs = {
        'Accept': '*/*', 'Accept-Encoding': 'gzip',
        'Authorization':     f'Bearer {token}',
        'Connection':        'Keep-Alive',
        'Content-Type':      'application/json',
        'X-AssetVersion':    config.file_ts1 or '0',
        'X-ClientVersion':   _code(ver),
        'X-DatabaseVersion': config.db_ts1 or '0',
        'X-Language':        config.lang,
        'X-Platform':        os,
        'X-RequestVersion':  '40',
        'User-Agent':        _dua(os),
    }

    def _do():
        return requests.get(_base(ver) + ep, headers=hdrs, timeout=30)

    try:
        r = _do()
        if r.status_code == 400:
            try:
                err_body = r.json()
                err_code = str(err_body.get('error', {}).get('code', '')
                               if isinstance(err_body.get('error'), dict)
                               else err_body.get('error', ''))
            except Exception:
                err_code = ''
            if 'new_version_exists' in err_code or 'client_database' in err_code:
                log.warning('[resources_login] 400 new_version_exists → fetch client_assets/database')
                client_assets_database_request(ver, os, token)
                hdrs['X-DatabaseVersion'] = config.db_ts1 or '0'
                r = _do()
        data = r.json()
        data['_http_status'] = r.status_code
        return data
    except Exception as e:
        return {'error': str(e)}


def tutorial_gasha_request(ver: str, os: str, token: str, gasha_id: int = 0) -> dict:
    dua  = config.device_agent1 if True else config.device_agent2
    code = config.gb_code if ver == "gb" else config.jp_code
    hdrs = {
        "Accept":            "*/*",
        "Accept-Encoding":   "gzip",
        "Authorization":     f"Bearer {token}",
        "Connection":        "Keep-Alive",
        "Content-Type":      "application/json",
        "X-AssetVersion":    "0",
        "X-ClientVersion":   code,
        "X-DatabaseVersion": "0",
        "X-Language":        config.lang,
        "X-Platform":        "android",
        "X-RequestVersion":  "4",
        "User-Agent":        dua,
    }
    try:
        r = requests.post(
            _base(ver) + "/tutorial/gasha",
            data=json.dumps({}),
            headers=hdrs,
            timeout=15,
        )
        print(f"[tutorialGasha raw] HTTP {r.status_code} — {r.text[:400]}")
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:200]}
        data["_http_status"] = r.status_code
        return data
    except Exception as e:
        return {"error": str(e), "_http_status": 0}


def link_code_request(ver: str, os: str, token: str) -> dict:
    try:
        r = requests.post(_base(ver) + '/auth/link_codes',
                          data=json.dumps({'eternal': True}),
                          headers=_headers_bearer(ver, os, token), timeout=15)
        return r.json()
    except Exception as e:
        return {'error': str(e)}


def _is_routing_error(data: dict) -> bool:
    err = data.get('error', data)
    if isinstance(err, dict):
        return 'routing_error' in str(err.get('code', ''))
    return 'routing_error' in str(err)


def link_google_request(ver: str, os: str, token: str, google_token: str) -> dict:
    raw_code = access_token = id_token = ''
    for part in google_token.split('|'):
        if part.startswith('CODE:'):    raw_code     = part[5:]
        elif part.startswith('ACCESS:'): access_token = part[7:]
        elif part.startswith('ID:'):     id_token     = part[3:]
    if not raw_code and not access_token and not id_token:
        access_token = id_token = google_token

    bodies = []
    if raw_code:     bodies.append({'server_auth_code': raw_code})
    if access_token: bodies.append({'access_token': access_token})
    if id_token:     bodies.append({'id_token': id_token})
    if access_token and id_token:
        bodies.append({'access_token': access_token, 'id_token': id_token})

    last_data = {'error': 'Aucun body na fonctionne'}
    for body in bodies:
        try:
            r = requests.post(_base(ver) + '/user/link/google',
                              data=json.dumps(body),
                              headers=_headers_bearer(ver, os, token), timeout=15)
            print(f'[link_google] body_keys={list(body.keys())} -> HTTP {r.status_code} -- {r.text[:250]}')
            data     = r.json()
            err_code = ''
            if isinstance(data.get('error'), dict):
                err_code = str(data['error'].get('code', ''))
            elif 'error' in data:
                err_code = str(data['error'])
            if r.status_code in (200, 201) and 'error' not in data:
                return data
            if 'parameter_missing' not in err_code and 'routing_error' not in err_code:
                return data
            last_data = data
        except Exception as e:
            last_data = {'error': str(e)}
    return last_data


# ══════════════════════════════════════════════════════════════
#  CLASSE PRINCIPALE
# ══════════════════════════════════════════════════════════════

class DokkanAuth:

    def __init__(self, ver: str = 'gb', os_type: str = 'android'):
        self.ver      = ver.lower()
        self.os_type  = os_type.lower()
        self.region   = 'GLOBAL' if self.ver == 'gb' else 'JP'
        self.base_url = config.gb_url if self.ver == 'gb' else config.jp_url

        self.user_id:    Optional[str] = None
        self.token:      Optional[str] = None
        self.secret:     Optional[str] = None
        self.identifier: Optional[str] = None
        self.ad_id:      Optional[str] = None
        self.unique_id:  Optional[str] = None
        self.name:       Optional[str] = None
        self.stones:     int           = 0
        self.rank:       int           = 0

        self._pending_ad:    Optional[str] = None
        self._pending_uniq:  Optional[str] = None
        self._pending_tx_id: Optional[str] = None

    # ── Création de compte ────────────────────────────────────

    def sign_up(self, captcha_key: Optional[str] = None) -> Dict:
        if captcha_key:
            ad_id     = self._pending_ad
            unique_id = self._pending_uniq
            tx_id     = self._pending_tx_id
            if not ad_id or not tx_id:
                raise RuntimeError('IDs manquants. Appelle sign_up() sans captcha_key d\'abord.')
        else:
            ids       = crypto.guid()
            ad_id     = ids[0]
            unique_id = ids[1]

            captcha_inquiry(self.ver, self.os_type, ad_id)

            nonce = get_nonce(self.ver, self.os_type)
            tx_id = nonce.get('auth_transaction_id')
            if not tx_id:
                raise RuntimeError(f'get_nonce() sans auth_transaction_id : {nonce}')

            self._pending_ad    = ad_id
            self._pending_uniq  = unique_id
            self._pending_tx_id = tx_id

            r    = sign_up_request(self.ver, self.os_type, ad_id, unique_id, tx_id)
            body = r.json()
            print(f'[sign_up appel3] HTTP {r.status_code} — {json.dumps(body)[:200]}')

            if r.status_code == 401:
                _curl = body.get('captcha_url', '')
                _csk  = body.get('captcha_session_key', '')
                if not _csk and _curl:
                    from urllib.parse import urlparse as _up, parse_qs as _pqs
                    _csk = _pqs(_up(_curl).query).get('captcha_session_key', [''])[0]
                print(f'[captcha_session_key] len={len(_csk)} preview={_csk[:20]}...')
                raise NeedsCaptchaError(captcha_url=_curl, captcha_session_key=_csk)
            return self._finalize(body, ad_id, unique_id, tx_id)

        r    = sign_up_request(self.ver, self.os_type, ad_id, unique_id, tx_id, captcha_key)
        body = r.json()
        print(f'[sign_up appel4] HTTP {r.status_code} — {json.dumps(body)[:300]}')

        if r.status_code != 200:
            raise RuntimeError(
                f'sign_up appel4 HTTP {r.status_code} : '
                f'{body.get("message") or json.dumps(body)[:200]}'
            )
        return self._finalize(body, ad_id, unique_id, tx_id)

    def _finalize(self, body: dict, ad_id: str, unique_id: str, tx_id: str) -> Dict:
        '''
        Séquence post-sign_up :
          5. sign_in         → Bearer token
          6. GET /user       → user_id
          7. resources/login → initialise le compte  ← AVANT gasha
          8. tutorial/gasha  → invocation tutorial   ← APRÈS resources/login
          9. resources/login → recharge après gasha
        '''
        # ── Extraction robuste de identifier et secret ────────────────────────
        identifier = _extract_identifier(body)
        secret     = _extract_secret(body)

        log.info('[_finalize] identifier=%s secret=%s body_keys=%s',
                 '✓' if identifier else '✗VIDE',
                 '✓' if secret     else '✗VIDE',
                 list(body.keys()))

        if not identifier:
            log.warning('[_finalize] identifier introuvable — body complet : %s',
                        json.dumps(body)[:500])
            raise RuntimeError(
                f'sign_up réponse sans identifier : {json.dumps(body)[:300]}'
            )

        self.identifier = identifier
        self.secret     = secret if secret else identifier
        self.ad_id      = ad_id
        self.unique_id  = unique_id

        self._pending_ad = self._pending_uniq = self._pending_tx_id = None
        config.ad   = self.ad_id
        config.uuid = self.unique_id

        # 5. sign_in → Bearer token (récupère aussi le secret si absent du sign_up)
        creds = self.sign_in(tx_id=tx_id)

        # Si sign_in a retourné un secret et qu'on n'en avait pas, on le garde
        if not self.secret and creds.get('secret'):
            self.secret = creds['secret']
            log.info('[_finalize] secret récupéré depuis sign_in ✓')

        # 6. GET /user → user_id réel
        self._load_user_info()
        creds['user_id'] = self.user_id
        creds['secret']  = self.secret  # garantir que le secret final est dans creds

        log.info('[_finalize] Final — user_id=%s identifier=%s secret=%s',
                 self.user_id,
                 '✓' if self.identifier else '✗VIDE',
                 '✓' if self.secret     else '✗VIDE')

        # 7. resources/login — OBLIGATOIRE avant tutorial/gasha
        res1 = resources_login_request(self.ver, self.os_type, self.token,
                                       user_card_updated_at=0)
        print(f'[resourcesLogin1] http={res1.get("_http_status","?")} '
              f'areas={len(res1.get("user_areas", []))}')

        # 8. tutorial/gasha — APRÈS resources/login
        tuto = tutorial_gasha_request(self.ver, self.os_type, self.token)
        print(f'[tutorialGasha] http={tuto.get("_http_status","?")} '
              f'cards={len(tuto.get("cards", []))}')

        # 9. resources/login — recharge après gasha
        res2 = resources_login_request(self.ver, self.os_type, self.token)
        print(f'[resourcesLogin2] http={res2.get("_http_status","?")} '
              f'areas={len(res2.get("user_areas", []))}')

        return creds

    # ── Connexion ─────────────────────────────────────────────

    def sign_in(self, tx_id: Optional[str] = None) -> Dict:
        if not self.identifier:
            raise RuntimeError('identifier manquant.')
        config.ad   = self.ad_id    or ''
        config.uuid = self.unique_id or ''

        result = sign_in_request(
            ver        = self.ver,
            os         = self.os_type,
            identifier = self.identifier,
            ad_id      = self.ad_id     or '',
            unique_id  = self.unique_id or '',
            tx_id      = tx_id,
        )
        print(f'[sign_in] {json.dumps(result)[:300]}')

        token = result.get('access_token') or result.get('token')
        if not token:
            raise RuntimeError(f'sign_in échoué : {result.get("message") or json.dumps(result)[:200]}')

        self.token = token

        # Extraction robuste du secret depuis la réponse sign_in
        sign_in_secret = _extract_secret(result)
        if sign_in_secret:
            self.secret = sign_in_secret
            log.info('[sign_in] secret extrait ✓')
        elif not self.secret:
            log.warning('[sign_in] secret introuvable — résultat : %s',
                        json.dumps(result)[:300])

        return {
            'user_id':    self.user_id,
            'token':      self.token,
            'secret':     self.secret,
            'identifier': self.identifier,
            'ad_id':      self.ad_id,
            'unique_id':  self.unique_id,
            'region':     self.region,
        }

    def _load_user_info(self) -> None:
        data = get_user_request(self.ver, self.os_type, self.token)
        print(f'[GET /user] {json.dumps(data)[:300]}')
        user = data.get('user', {})
        if user:
            self.user_id = str(user.get('id', self.user_id or ''))
            self.name    = user.get('name', '???')
            self.rank    = user.get('rank', 0)
            self.stones  = user.get('stone', 0)
            print(f'[user_info] user_id={self.user_id} name={self.name} rank={self.rank} stones={self.stones}')

    def refresh(self) -> Dict:
        creds = self.sign_in()
        self._load_user_info()
        return creds

    # ── Transfer Code ─────────────────────────────────────────

    def get_transfer_code(self) -> str:
        data = link_code_request(self.ver, self.os_type, self.token)
        print(f'[link_codes] {json.dumps(data)[:200]}')
        code = data.get('link_code') or data.get('transfer_code') or data.get('code')
        if not code:
            raise RuntimeError(f'link_codes réponse inattendue : {json.dumps(data)[:200]}')
        return code

    def link_google(self, google_id_token: str) -> dict:
        if not self.token:
            raise RuntimeError('Non authentifié — appelle sign_in() avant link_google().')
        data = link_google_request(self.ver, self.os_type, self.token, google_id_token)
        if data.get('error'):
            raise RuntimeError(f'link_google API error : {data["error"]}')
        if not (data.get('user') or data.get('ok') or data.get('id')):
            raise RuntimeError(f'link_google réponse inattendue : {json.dumps(data)[:300]}')
        return data

    # ── Credentials ───────────────────────────────────────────

    def load_credentials(self, user_id: str, token: str, secret: str = '',
                         identifier: str = '', ad_id: str = '',
                         unique_id: str = '') -> None:
        self.user_id    = user_id
        self.token      = token
        self.secret     = secret
        self.identifier = identifier
        self.ad_id      = ad_id
        self.unique_id  = unique_id
        config.ad       = ad_id
        config.uuid     = unique_id
        if not secret:
            log.warning('[load_credentials] secret vide pour user_id=%s — refresh() risque d\'échouer', user_id)
        if not identifier:
            log.warning('[load_credentials] identifier vide pour user_id=%s', user_id)

    def verify(self) -> bool:
        if not self.token:
            return False
        data = get_user_request(self.ver, self.os_type, self.token)
        if data.get('user'):
            user = data['user']
            self.user_id = str(user.get('id', self.user_id or ''))
            self.name    = user.get('name', '???')
            self.rank    = user.get('rank', 0)
            self.stones  = user.get('stone', 0)
            return True
        return False

    def to_dict(self) -> Dict:
        return {
            'user_id':    self.user_id,    'token':      self.token,
            'secret':     self.secret,     'identifier': self.identifier,
            'ad_id':      self.ad_id,      'unique_id':  self.unique_id,
            'region':     self.region,     'os_type':    self.os_type,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'DokkanAuth':
        ver = 'gb' if data.get('region', 'GLOBAL').upper() == 'GLOBAL' else 'jp'
        obj = cls(ver=ver, os_type=data.get('os_type', 'android'))
        obj.load_credentials(
            user_id    = data.get('user_id', ''),
            token      = data.get('token', ''),
            secret     = data.get('secret', ''),
            identifier = data.get('identifier', ''),
            ad_id      = data.get('ad_id', ''),
            unique_id  = data.get('unique_id', ''),
        )
        return obj

    def __repr__(self):
        return (f'DokkanAuth(ver={self.ver!r}, user_id={self.user_id!r}, '
                f'name={self.name!r}, stones={self.stones}, authenticated={bool(self.token)})')
