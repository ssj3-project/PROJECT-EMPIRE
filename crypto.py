'''
crypto.py — fonctions cryptographiques pour l'API Dokkan Battle.
'''
import base64
import hashlib
import hmac
import json
import os
import time
import uuid
import config
from Crypto.Cipher import AES

BLOCK_SIZE = 16
pad   = lambda s: s + (BLOCK_SIZE - len(s) % BLOCK_SIZE) * chr(BLOCK_SIZE - len(s) % BLOCK_SIZE)
unpad = lambda s: s[:-ord(s[len(s) - 1:])]

def guid():
    '''
    Génère ad_id et unique_id — deux UUID v4.
    FIX: unique_id ne doit PAS contenir "-" → illegal_device_token_error sinon.
    '''
    ad_id     = str(uuid.uuid4())
    unique_id = str(uuid.uuid4()).replace('-', '')
    return [ad_id, unique_id]

def basic(identifier):
    if '\n' in identifier:
        temp = identifier.replace('\n', '')
    else:
        temp = identifier
    if len(temp) < 159:
        while len(temp) < 159:
            temp = temp.ljust(159, '\u0008')
    decode  = base64.b64decode(temp).decode()
    part    = decode.split(':')
    flipped = part[1] + ':' + part[0]
    return base64.b64encode(flipped.encode()).decode()

def mac(ver, token, secret, method, endpoint):
    '''
    FIX MULTI-UTILISATEUR: ne lit plus config.ad/config.uuid (globals partagés).
    FIX PORT: utilise config.gb_port / config.jp_port (définis dans config.py).
    '''
    if ver == 'gb':
        host = config.gb_url.replace('https://', '').split(':')[0]
        port = config.gb_port   # ← défini dans config.py via _read_host()
    else:
        host = config.jp_url.replace('https://', '').split(':')[0]
        port = config.jp_port   # ← défini dans config.py via _read_host()
    ts    = str(int(round(time.time(), 0)))
    nonce = ts + ':' + str(hashlib.md5(ts.encode()).hexdigest())
    sig   = '' + ts + '\n' + nonce + '\n' + method + '\n' + endpoint + '\n' + host + '\n' + str(port) + '\n\n'
    hmac_hex_bin = hmac.new(secret.encode('utf-8'), sig.encode('utf-8'), hashlib.sha256).digest()
    mac_b64 = base64.b64encode(hmac_hex_bin).decode()
    return 'MAC id=\"' + token + '\", nonce=\"' + nonce + '\", ts=\"' + ts + '\", mac=\"' + mac_b64 + '\"'

def get_key_and_iv(password, salt, klen=32, ilen=16, msgdgst='md5'):
    mdf      = getattr(__import__('hashlib', fromlist=[msgdgst]), msgdgst)
    password = password.encode('ascii', 'ignore')
    try:
        maxlen = klen + ilen
        keyiv  = mdf(password + salt).digest()
        tmp    = [keyiv]
        while len(keyiv) < maxlen:
            tmp.append(mdf(tmp[-1] + password + salt).digest())
            keyiv += tmp[-1]
        return keyiv[:klen], keyiv[klen:klen + ilen]
    except UnicodeDecodeError:
        return (None, None)

def encrypt_sign(data):
    data     = pad(data)
    key1     = str.encode(data)
    password = 'fk0I+QfaSOz9fqGt3Ocn8T7uMzuUj2RyDtm8PQEEon6C9huxF1IkLnFzfF5kYfUm'#la clé fonctionne que pour la glo
    salt     = os.urandom(8)
    key, iv  = get_key_and_iv(password, salt, klen=32, ilen=16, msgdgst='md5')
    cipher   = AES.new(key, AES.MODE_CBC, iv)
    a        = cipher.encrypt(key1)
    return base64.b64encode(salt + a).decode()

def decrypt_sign(sign):
    buffer   = base64.b64decode(sign)
    password = 'fk0I+QfaSOz9fqGt3Ocn8T7uMzuUj2RyDtm8PQEEon6C9huxF1IkLnFzfF5kYfUm'#la clé fonctionne que pour la glo
    salt     = buffer[0:8]
    key, iv  = get_key_and_iv(password, salt, klen=32, ilen=16, msgdgst='md5')
    data     = buffer[8:]
    cipher   = AES.new(key, AES.MODE_CBC, iv)
    return json.loads(unpad(cipher.decrypt(data)).decode('utf8'))
