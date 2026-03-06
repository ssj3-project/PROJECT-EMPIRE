'''
ingame.py — appels API Dokkan Battle in-game.
Toutes les fonctions sont pures : (ver, os, token, secret, *args) → dict

CORRECTIONS vs original :
  - user() : paramètre "first" supprimé (inutile, GET /user n'en a pas besoin)
  - getSupports() : "difficulty" passé correctement en query param
  - startStage() : condition len(str(friend)) >= 4 → plus robuste avec is_cpu
  - finishStage() : elapsed_time cohérent (ms, pas secondes)
  - Toutes les fonctions : timeout=15 ajouté sur requests pour éviter les blocages
  - Gestion d'erreur HTTP basique (status_code != 200 → dict erreur)
'''
import requests
import config
import crypto
import json
import time
import base64
from random import randint


# ── Timeout global ────────────────────────────────────────────────────────────
_TIMEOUT = 15  # secondes


def _base_url(ver: str) -> str:
    return config.gb_url if ver == 'gb' else config.jp_url


def _headers(ver, os, token, secret, method, endpoint):
    '''Headers standards pour une requête authentifiée.'''
    dua   = config.device_agent1 if os == 'android' else config.device_agent2
    code  = config.gb_code  if ver == 'gb' else config.jp_code
    asset = config.file_ts1 if ver == 'gb' else config.file_ts2
    db    = config.db_ts1   if ver == 'gb' else config.db_ts2
    auth  = crypto.mac(ver, token, secret, method, endpoint)
    return {
        'X-Platform':        os,
        'X-Language':        config.lang,
        'X-ClientVersion':   code,
        'X-AssetVersion':    asset,
        'X-DatabaseVersion': db,
        'Content-Type':      'application/json',
        'Accept':            '*/*',
        'Authorization':     auth,
        'User-Agent':        dua,
    }


def _headers_sign(ver, os, token, secret, method, endpoint):
    '''Headers pour les requêtes avec sign chiffré (AssetVersion/DatabaseVersion = ////).'''
    dua  = config.device_agent1 if os == 'android' else config.device_agent2
    code = config.gb_code if ver == 'gb' else config.jp_code
    auth = crypto.mac(ver, token, secret, method, endpoint)
    return {
        'User-Agent':        dua,
        'Accept':            '*/*',
        'Authorization':     auth,
        'Content-Type':      'application/json',
        'X-Platform':        os,
        'X-Language':        config.lang,
        'X-AssetVersion':    '////',
        'X-DatabaseVersion': '////',
        'X-ClientVersion':   code,
    }


def _safe(r: requests.Response) -> dict:
    '''Retourne r.json() ou un dict erreur si le statut HTTP est mauvais.'''
    try:
        data = r.json()
    except Exception:
        data = {'raw': r.text}
    if r.status_code not in (200, 201):
        # Ajoute le code HTTP pour faciliter le debug
        if isinstance(data, dict):
            data['_http_status'] = r.status_code
        else:
            data = {'error': data, '_http_status': r.status_code}
    return data


# ══════════════════════════════════════════════════════════════ COMPTE

def user(ver, os, token, secret):
    '''GET /user — infos du compte connecté.'''
    # CORRECTION : "first" supprimé, inutile pour GET /user
    url = _base_url(ver) + '/user'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/user'), timeout=_TIMEOUT)
    return _safe(r)


def cards(ver, os, token, secret):
    '''GET /cards — toutes les cartes de la boîte.'''
    url = _base_url(ver) + '/cards'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/cards'), timeout=_TIMEOUT)
    return _safe(r)


def changeName(ver, os, token, secret, name: str):
    '''PUT /user — change le pseudo en jeu.'''
    url  = _base_url(ver) + '/user'
    data = {'user': {'name': name}}
    r    = requests.put(url, data=json.dumps(data),
                        headers=_headers(ver, os, token, secret, 'PUT', '/user'), timeout=_TIMEOUT)
    return _safe(r)


def capacity(ver, os, token, secret):
    '''POST /user/capacity/card — augmente la capacité de cartes.'''
    url = _base_url(ver) + '/user/capacity/card'
    r   = requests.post(url, data=None,
                        headers=_headers(ver, os, token, secret, 'POST', '/user/capacity/card'), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ STAMINA

def actRefill(ver, os, token, secret):
    '''PUT /user/recover_act_with_stone — refill stamina avec une pierre.'''
    ep  = '/user/recover_act_with_stone'
    url = _base_url(ver) + ep
    r   = requests.put(url, data=None,
                       headers=_headers(ver, os, token, secret, 'PUT', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ CARTES

def sell(ver, os, token, secret, card_ids: list):
    '''POST /cards/sell — vend une liste de cartes.'''
    url  = _base_url(ver) + '/cards/sell'
    data = {'card_ids': card_ids}
    r    = requests.post(url, data=json.dumps(data),
                         headers=_headers(ver, os, token, secret, 'POST', '/cards/sell'), timeout=_TIMEOUT)
    return _safe(r)


def getTeams(ver, os, token, secret):
    '''GET /teams — récupère les équipes configurées.'''
    url = _base_url(ver) + '/teams'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/teams'), timeout=_TIMEOUT)
    return _safe(r)


def setTeam(ver, os, token, secret, team_num: int, cards_data: list):
    '''POST /teams — sauvegarde une équipe.'''
    url  = _base_url(ver) + '/teams'
    data = {'selected_team_num': team_num, 'user_card_teams': cards_data}
    r    = requests.post(url, data=json.dumps(data),
                         headers=_headers(ver, os, token, secret, 'POST', '/teams'), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ CADEAUX / MISSIONS

def gifts(ver, os, token, secret):
    '''GET /gifts — liste des cadeaux en attente.'''
    url = _base_url(ver) + '/gifts'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/gifts'), timeout=_TIMEOUT)
    return _safe(r)


def acceptGifts(ver, os, token, secret, gift_ids: list):
    '''POST /gifts/accept — accepte une liste de cadeaux.
    CORRECTION : header X-Analytics: 1 obligatoire (vu dans les traces réseau).
    '''
    url  = _base_url(ver) + '/gifts/accept'
    data = {'gift_ids': gift_ids}
    hdrs = _headers(ver, os, token, secret, 'POST', '/gifts/accept')
    hdrs['X-Analytics'] = '1'
    r    = requests.post(url, data=json.dumps(data), headers=hdrs, timeout=_TIMEOUT)
    return _safe(r)


def missions(ver, os, token, secret):
    '''GET /missions — liste des missions.'''
    url = _base_url(ver) + '/missions'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/missions'), timeout=_TIMEOUT)
    return _safe(r)


def missionPutForward(ver, os, token, secret, since: int = None):
    '''POST /missions/put_forward — vérifie les nouvelles missions complétées.
    CORRECTION (trace) : body = {"mission_put_forward_since": <timestamp unix>}
    since = timestamp (int). Si None, utilise le timestamp actuel.
    '''
    ep   = '/missions/put_forward'
    url  = _base_url(ver) + ep
    ts   = since if since is not None else int(time.time())
    data = {'mission_put_forward_since': ts}
    r    = requests.post(url, data=json.dumps(data),
                         headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def acceptMissions(ver, os, token, secret, mission_ids: list):
    '''POST /missions/accept — réclame les récompenses de missions terminées.'''
    url  = _base_url(ver) + '/missions/accept'
    data = {'mission_ids': mission_ids}
    r    = requests.post(url, data=json.dumps(data),
                         headers=_headers(ver, os, token, secret, 'POST', '/missions/accept'), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ INVOCATIONS

def banners(ver, os, token, secret):
    '''GET /gashas — liste des bannières d'invocation actives.'''
    url = _base_url(ver) + '/gashas'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/gashas'), timeout=_TIMEOUT)
    return _safe(r)


def summon(ver, os, token, secret, gacha_id: int, course: int):
    '''POST /gashas/{id}/courses/{course}/draw — effectue une invocation.'''
    ep  = f'/gashas/{gacha_id}/courses/{course}/draw'
    url = _base_url(ver) + ep
    r   = requests.post(url, data=None,
                        headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ EVENTS / QUESTS

def events(ver, os, token, secret):
    '''GET /events — liste des événements en cours.'''
    url = _base_url(ver) + '/events'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/events'), timeout=_TIMEOUT)
    return _safe(r)


def quests(ver, os, token, secret):
    '''GET /user_areas — toutes les zones de quêtes avec leur progression.'''
    url = _base_url(ver) + '/user_areas'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/user_areas'), timeout=_TIMEOUT)
    return _safe(r)


def getMedals(ver, os, token, secret):
    '''GET /awakening_items — médailles d'éveil disponibles.'''
    url = _base_url(ver) + '/awakening_items'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/awakening_items'), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ STAGES NORMAUX

def getSupports(ver, os, token, secret, quest_id: int, difficulty: int):
    '''
    GET /quests/{quest_id}/stages/{stage_id}/supporters — supporters disponibles.
    CORRECTION CRITIQUE : deux IDs distincts (quest_id ET stage_id).
    quest_id  = sugoroku_map_id // 10
    stage_id  = sugoroku_map_id  (le vrai stage, identique à sugoroku_map_id sans diff)
    '''
    #stage_id est inutile faut garder que quest_id et recuperer le team_num pour la requete
    decks = getTeams(ver, os, token, secret)
    team_num = decks.get('selected_team_num', 1)

    ep  = f'/quests/{quest_id}/briefing?difficulty={difficulty}&force_update=&team_num={team_num}'
    url = _base_url(ver) + ep 
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def startStage(ver, os, token, secret, quest_id: int, difficulty: int,
               friend_id: int, friend_card_id: int, is_cpu: bool = False):
    '''
    POST /quests/{quest_id}/stages/{stage_id}/sugoroku_maps/start — démarre un stage.
    CORRECTION CRITIQUE : endpoint avec quest_id ET stage_id séparés.
    quest_id = sugoroku_map_id // 10
    '''
    #stage_id est inutile faut garder que quest_id
    ep    = f'/quests/{quest_id}/sugoroku_maps/start'
    url   = _base_url(ver) + ep
    decks = getTeams(ver, os, token, secret)
    team_num = decks.get('selected_team_num', 1)

    if is_cpu:
        payload = {
            'difficulty':        int(difficulty),
            'cpu_friend_id':     int(friend_id),
            'is_playing_script': True,
            'selected_team_num': team_num,
        }
    else:
        payload = {
            'difficulty':        int(difficulty),
            'friend_id':         int(friend_id),
            'is_playing_script': True,
            'selected_team_num': team_num,
            'support_leader': {
                'card_id':                 int(friend_card_id),
                'exp':                     0,
                'optimal_awakening_step':  0,
                'released_rate':           0,
            },
        }

    enc_sign = crypto.encrypt_sign(json.dumps(payload))
    r = requests.post(url, data=json.dumps({'sign': enc_sign}),
                      headers=_headers_sign(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def finishStage(ver, os, token, secret, quest_id: int, difficulty: int,
                paces: list, defeated: list, stoken: str):
    '''
    POST /quests/{quest_id}/stages/{stage_id}/sugoroku_maps/finish — termine un stage.
    CORRECTION CRITIQUE : endpoint avec quest_id ET stage_id séparés.
    '''

    #stage_id est inutile faut garder que quest_id
    ep     = f'/quests/{quest_id}/sugoroku_maps/finish'
    url    = _base_url(ver) + ep
    steps  = list(paces)

    # Timestamps en ms (le serveur attend des ms)
    finish_ms = int(time.time() * 1000) + 90_000          # +90s simulés
    start_ms  = finish_ms - randint(6_200_000, 8_200_000)  # ~1h45 à 2h17 de jeu
    elapsed   = finish_ms - start_ms

    damage = randint(500_000, 1_000_000)
    # Hercule punching bag event (stages spéciaux)
    if str(quest_id)[:3] in ('711', '185'):
        damage = randint(100_000_000, 101_000_000)

    sign_payload = {
        'actual_steps':                       steps,
        'difficulty':                         int(difficulty),
        'elapsed_time':                       elapsed,
        'energy_ball_counts_in_boss_battle':  [4, 6, 0, 6, 4, 3, 0, 0, 0, 0, 0, 0, 0],
        'has_player_been_taken_damage':       False,
        'is_cheat_user':                      False,
        'is_cleared':                         True,
        'is_defeated_boss':                   True,
        'is_player_special_attack_only':      True,
        'max_damage_to_boss':                 damage,
        'min_turn_in_boss_battle':            len(defeated),
        'passed_round_ids':                   defeated,
        'quest_finished_at_ms':               finish_ms,
        'quest_started_at_ms':                start_ms,
        'steps':                              steps,
        'token':                              stoken,
    }
    enc_sign = crypto.encrypt_sign(json.dumps(sign_payload))
    r = requests.post(url, data=json.dumps({'sign': enc_sign}),
                      headers=_headers_sign(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ Z-BATTLES (EZA)

def zSupports(ver, os, token, secret, eza_id: int):
    '''GET /z_battles/{id}/supporters — supporters pour un Z-Battle.'''
    ep  = f'/z_battles/{eza_id}/supporters'
    url = _base_url(ver) + ep
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def zStart(ver, os, token, secret, eza_id: int, level: int,
           friend_id: int, friend_card_id: int):
    '''POST /z_battles/{id}/start — démarre un Z-Battle.'''
    ep    = f'/z_battles/{eza_id}/start'
    url   = _base_url(ver) + ep
    decks = getTeams(ver, os, token, secret)
    payload = {
        'friend_id':         int(friend_id),
        'level':             int(level),
        'selected_team_num': decks.get('selected_team_num', 1),
        'support_leader': {
            'card_id':                int(friend_card_id),
            'exp':                    0,
            'optimal_awakening_step': 0,
            'released_rate':          0,
        },
    }
    enc_sign = crypto.encrypt_sign(json.dumps(payload))
    r = requests.post(url, data=json.dumps({'sign': enc_sign}),
                      headers=_headers_sign(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def zFinish(ver, os, token, secret, eza_id: int, level: int,
            stoken: str, em_atk: int, em_hp: list):
    '''POST /z_battles/{id}/finish — termine un Z-Battle.'''
    ep        = f'/z_battles/{eza_id}/finish'
    url       = _base_url(ver) + ep
    finish_ms = int(time.time() * 1000) + 90_000
    start_ms  = finish_ms - randint(6_200_000, 8_200_000)

    summary = {
        'summary': {
            'enemy_attack':         int(em_atk),
            'enemy_attack_count':   1,
            'enemy_heal_counts':    [0],
            'enemy_heals':          [0],
            'enemy_max_attack':     int(em_atk),
            'enemy_min_attack':     int(em_atk),
            'player_attack_counts': [3],
            'player_attacks':       em_hp,
            'player_heal':          0,
            'player_heal_count':    0,
            'player_max_attacks':   em_hp,
            'player_min_attacks':   em_hp,
            'type':                 'summary',
        }
    }
    data = {
        'elapsed_time':            finish_ms - start_ms,
        'is_cleared':              True,
        'level':                   int(level),
        'reason':                  'win',
        's':                       'iwM9xu4mM/7fZyLfKV93JaquLtLzpP35CKBoDiB+X8k=',
        't':                       base64.b64encode(json.dumps(summary).encode()).decode(),
        'token':                   str(stoken),
        'used_items':              [],
        'z_battle_finished_at_ms': finish_ms,
        'z_battle_started_at_ms':  start_ms,
    }
    r = requests.post(url, data=json.dumps(data),
                      headers=_headers_sign(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ AMIS

def friends(ver, os, token, secret):
    '''GET /friendships — liste des amis.'''
    url = _base_url(ver) + '/friendships'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/friendships'), timeout=_TIMEOUT)
    return _safe(r)


def findFriend(ver, os, token, secret, user_id: int):
    '''GET /users/{id} — profil public d'un utilisateur.'''
    ep  = f'/users/{user_id}'
    url = _base_url(ver) + ep
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def addFriend(ver, os, token, secret, user_id: int):
    '''POST /users/{id}/friendships — envoie une demande d'ami.'''
    ep  = f'/users/{user_id}/friendships'
    url = _base_url(ver) + ep
    r   = requests.post(url, headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def acceptFriend(ver, os, token, secret, friendship_id: int):
    '''PUT /friendships/{id}/accept — accepte une demande d'ami.'''
    ep  = f'/friendships/{friendship_id}/accept'
    url = _base_url(ver) + ep
    r   = requests.put(url, headers=_headers(ver, os, token, secret, 'PUT', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ DRAGON BALLS

def dragonballs(ver, os, token, secret):
    '''GET /dragonball_sets — état des Dragon Balls collectées.'''
    url = _base_url(ver) + '/dragonball_sets'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/dragonball_sets'), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ MISC

def news(ver, os, token, secret):
    '''GET /announcements — actualités du jeu.'''
    ep  = '/announcements?display=home'
    url = _base_url(ver) + ep
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/announcements'), timeout=_TIMEOUT)
    return _safe(r)


def dashStatus(ver, os, token, secret):
    '''GET /start_dash_gasha_status — état des invocations de démarrage.'''
    url = _base_url(ver) + '/start_dash_gasha_status'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', '/start_dash_gasha_status'), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ LOGIN BONUSES

def loginBonuses(ver, os, token, secret):
    """
    GET /resources/home — bonus de connexion (dans champ login_bonuses de la réponse).
    CORRECTION : GET /login_bonuses N'EXISTE PAS dans l'API.
    Les bonus de connexion sont retournés par /resources/home.
    """
    ep = ('/resources/home?apologies=true&budokai=true&comeback_campaigns=true'
          '&dot_characters=true&dragonball_sets=true&gifts=true&login_bonuses=true'
          '&random_login_bonuses=true&rmbattles=true&sns_campaign=true'
          '&user_subscription=true&webstore=true')
    r  = requests.get(_base_url(ver) + ep,
                      headers=_headers(ver, os, token, secret, 'GET', '/resources/home'),
                      timeout=30)
    return _safe(r)


def acceptLoginBonus(ver, os, token, secret, bonus_id: int = None):
    """
    POST /login_bonuses/accept — réclame TOUS les bonus de connexion (bulk).
    CORRECTION : l'API accepte un seul POST sans corps — réclame tout d'un coup.
    bonus_id ignoré : l'API n'accepte pas de per-id, seulement bulk.
    """
    ep = '/login_bonuses/accept'
    r  = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                       headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ APOLOGIES (COMPENSATIONS)

def apologies(ver, os, token, secret):
    """
    GET /resources/home — compensations Bandai (champ apologies dans la réponse).
    CORRECTION : GET /apologies N'EXISTE PAS dans l'API.
    Les compensations sont retournées par /resources/home avec apologies=true.
    """
    ep = ('/resources/home?apologies=true&budokai=true&comeback_campaigns=true'
          '&dot_characters=true&dragonball_sets=true&gifts=true&login_bonuses=true'
          '&random_login_bonuses=true&rmbattles=true&sns_campaign=true'
          '&user_subscription=true&webstore=true')
    r  = requests.get(_base_url(ver) + ep,
                      headers=_headers(ver, os, token, secret, 'GET', '/resources/home'),
                      timeout=30)
    return _safe(r)


def acceptApologies(ver, os, token, secret):
    """POST /apologies/accept — réclame toutes les compensations."""
    ep   = '/apologies/accept'
    r    = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                         headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ STAMINA

def actRefillWithItems(ver, os, token, secret):
    """PUT /user/recover_act_with_items — refill stamina avec viande."""
    ep = '/user/recover_act_with_items'
    r  = requests.put(_base_url(ver) + ep, data=json.dumps({}),
                      headers=_headers(ver, os, token, secret, 'PUT', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ TUTORIAL

def tutorialFinish(ver, os, token, secret):
    '''
    NE PAS UTILISER — POST /tutorial/finish n'existe pas dans l'API Bandai.
    La vraie séquence est PUT /tutorial avec des progress values (Bearer).
    Utilise auth.tutorial_full_sequence() à la place.
    Cet alias lève une erreur explicite pour éviter les appels silencieux.
    '''
    raise NotImplementedError(
        'tutorialFinish: POST /tutorial/finish n\'existe pas. '
        'Utilise auth.tutorial_full_sequence(ver, os, bearer_token) à la place.'
    )


def tutorialGasha(ver, os, token, secret):
    '''
    NE PAS UTILISER avec MAC auth — POST /tutorial/gasha requiert Bearer.
    Utilise auth.tutorial_gasha_request(ver, os, bearer_token) à la place.
    Cet alias lève une erreur explicite pour éviter les appels avec mauvais token.
    '''
    raise NotImplementedError(
        'tutorialGasha: requiert Bearer token, pas MAC. '
        'Utilise auth.tutorial_gasha_request(ver, os, bearer_token) à la place.'
    )


# ══════════════════════════════════════════════════════════════ RESOURCES

def resourcesLogin(ver, os, token, secret):
    """
    GET /resources/login — ressources complètes à la connexion.
    CORRECTION : query string complet extrait des .pyd compilés (40+ paramètres).
    """
    ep = ('/resources/login?act_items=true&announcements=true&awakening_items=true'
          '&budokai=true&card_sticker_items=true&card_tags=true&cards=true'
          '&chain_battles=true&comeback_campaigns=true&cooperation_campaigns=true'
          '&db_stories=true&dragonball_sets=true&equipment_skill_items=true'
          '&eventkagi_items=true&friendships=true&gashas=true&genkai_battles=true'
          '&gifts=true&joint_campaigns=true&jukeboxes=true&login_bonuses=true'
          '&login_movies=true&login_popups=true&missions=true&potential_items=true'
          '&rmbattles=true&sd/battle=true&sd/characters=true&sd/packs=true'
          '&secret_treasure_boxes=true&shops/treasure/items=true&sns_campaign=true'
          '&support_films=true&support_items=true&support_leaders=true'
          '&support_memories=true&support_memory_enhancement_items=true'
          '&teams=true&training_fields=true&training_items=true&treasure_items=true'
          '&user_areas=true&user_card_updated_at=0&user_subscription=true'
          '&wallpaper_items=true')
    r  = requests.get(_base_url(ver) + ep,
                      headers=_headers(ver, os, token, secret, 'GET', '/resources/login'),
                      timeout=30)
    return _safe(r)


def resourcesHome(ver, os, token, secret):
    """
    GET /resources/home — ressources de l'écran d'accueil.
    CORRECTION : query string complet extrait des .pyd compilés.
    Contient : apologies, login_bonuses, gifts, rmbattles, dragonball_sets...
    """
    ep = ('/resources/home?apologies=true&budokai=true&comeback_campaigns=true'
          '&dot_characters=true&dragonball_sets=true&gifts=true&login_bonuses=true'
          '&random_login_bonuses=true&rmbattles=true&sns_campaign=true'
          '&user_subscription=true&webstore=true')
    r  = requests.get(_base_url(ver) + ep,
                      headers=_headers(ver, os, token, secret, 'GET', '/resources/home'),
                      timeout=30)
    return _safe(r)


def resourcesItems(ver, os, token, secret):
    """
    GET /resources/items — ressources objets.
    CORRECTION : query string complet extrait des .pyd compilés.
    """
    ep = ('/resources/items?act_items=true&awakening_items=true&card_sticker_items=true'
          '&equipment_skill_items=true&eventkagi_items=true&potential_items=true'
          '&sd/packs=true&special_items=true&support_films=true&support_items=true'
          '&support_memories=true&support_memory_enhancement_items=true'
          '&training_fields=true&training_items=true&treasure_items=true'
          '&wallpaper_items=true')
    r  = requests.get(_base_url(ver) + ep,
                      headers=_headers(ver, os, token, secret, 'GET', '/resources/items'),
                      timeout=30)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ DB STORIES

def dbStories(ver, os, token, secret):
    """GET /db_stories — chapitres DB Stories."""
    ep = '/db_stories'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ WISHES

def wishes(ver, os, token, secret):
    """GET /dragonball_sets — état des Dragon Balls."""
    ep = '/dragonball_sets'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def makeWish(ver, os, token, secret, dragonball_set_id: int, wish_ids: list):
    """POST /dragonball_sets/<id>/wishes/make — exauce un vœu."""
    ep   = f'/dragonball_sets/{dragonball_set_id}/wishes/make'
    data = {'wish_ids': wish_ids}
    r    = requests.post(_base_url(ver) + ep, data=json.dumps(data),
                         headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def dragonballWishes(ver, os, token, secret, dragonball_set_id: int):
    """GET /dragonball_sets/<id>/wishes — vœux disponibles."""
    ep = f'/dragonball_sets/{dragonball_set_id}/wishes'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ CARDS

def awakenCard(ver, os, token, secret, user_card_id: int):
    """
    PUT /user_cards/{user_card_id}/awake — éveille une carte (Dokkan Awakening).
    CORRECTION : méthode PUT (pas POST) + path /awake (pas /awaken).
    """
    ep = f'/user_cards/{user_card_id}/awake'
    r  = requests.put(_base_url(ver) + ep, data=json.dumps({}),
                      headers=_headers(ver, os, token, secret, 'PUT', ep), timeout=_TIMEOUT)
    return _safe(r)


def bulkOptimalAwake(ver, os, token, secret, user_card_id: int):
    """
    PUT /user_cards/{user_card_id}/bulk_optimal_awake — éveil optimal automatique.
    CORRECTION : méthode PUT (pas POST).
    """
    ep = f'/user_cards/{user_card_id}/bulk_optimal_awake'
    r  = requests.put(_base_url(ver) + ep, data=json.dumps({}),
                      headers=_headers(ver, os, token, secret, 'PUT', ep), timeout=_TIMEOUT)
    return _safe(r)


def trainCard(ver, os, token, secret, user_card_id: int, feed_card_ids: list):
    """
    PUT /user_cards/{user_card_id}/bulk_train — monte le SA d'une carte.
    CORRECTION : méthode PUT (pas POST) + path /bulk_train (pas /train).
    """
    ep   = f'/user_cards/{user_card_id}/bulk_train'
    data = {'feed_user_card_ids': feed_card_ids}
    r    = requests.put(_base_url(ver) + ep, data=json.dumps(data),
                         headers=_headers(ver, os, token, secret, 'PUT', ep), timeout=_TIMEOUT)
    return _safe(r)


def exchangeCards(ver, os, token, secret, card_ids: list):
    """POST /exchange_point_cards — échange des cartes."""
    ep   = '/exchange_point_cards'
    data = {'user_card_ids': card_ids}
    r    = requests.post(_base_url(ver) + ep, data=json.dumps(data),
                         headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def exchangeCardsToBaba(ver, os, token, secret, card_ids: list):
    """POST /baba_shop/exchange_cards — échange des cartes chez Baba."""
    ep   = '/baba_shop/exchange_cards'
    data = {'user_card_ids': card_ids}
    r    = requests.post(_base_url(ver) + ep, data=json.dumps(data),
                         headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def unlockPotential(ver, os, token, secret, user_card_id: int, node_id: int, feed_card_ids: list):
    """POST /user_cards/<id>/unlock_potential — débloque le potentiel."""
    ep   = f'/user_cards/{user_card_id}/unlock_potential'
    data = {'node_id': node_id, 'feed_user_card_ids': feed_card_ids}
    r    = requests.post(_base_url(ver) + ep, data=json.dumps(data),
                         headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ SHOPS

def shopTreasureItems(ver, os, token, secret):
    """GET /treasure_shop_items — articles de la boutique Trésor."""
    ep = '/treasure_shop_items'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def buyTreasureItem(ver, os, token, secret, item_id: int):
    """POST /treasure_shop_items/<id>/buy — achète un article Trésor."""
    ep   = f'/treasure_shop_items/{item_id}/buy'
    r    = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                         headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def shopZeniItems(ver, os, token, secret):
    """GET /zeni_shop_items — articles de la boutique Zeni."""
    ep = '/zeni_shop_items'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def buyZeniItem(ver, os, token, secret, item_id: int):
    """POST /zeni_shop_items/<id>/buy — achète un article Zeni."""
    ep   = f'/zeni_shop_items/{item_id}/buy'
    r    = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                         headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def shopExchangeItems(ver, os, token, secret):
    """GET /exchange_point_shop_items — articles de la boutique Exchange Points."""
    ep = '/exchange_point_shop_items'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def buyExchangeItem(ver, os, token, secret, item_id: int):
    """POST /exchange_point_shop_items/<id>/buy — achète un article Exchange."""
    ep   = f'/exchange_point_shop_items/{item_id}/buy'
    r    = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                         headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def babashopItems(ver, os, token, secret):
    """GET /baba_shop_items — articles de la boutique Baba."""
    ep = '/baba_shop_items'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def buyBabaItem(ver, os, token, secret, item_id: int):
    """POST /baba_shop_items/<id>/buy — achète un article chez Baba."""
    ep   = f'/baba_shop_items/{item_id}/buy'
    r    = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                         headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ MISSIONS

def missionBoard(ver, os, token, secret):
    """GET /missions/mission_board_campaigns — panneau des missions."""
    ep = '/missions/mission_board_campaigns'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ QUEST BRIEFING

def questBriefing(ver, os, token, secret, quest_id: int, stage_id: int, difficulty: int = 3):
    """
    GET /quests/{quest_id}/stages/{stage_id}/briefing — briefing d'un stage.
    CORRECTION : endpoint complet avec quest_id + stage_id (pas /sugoroku_maps/).
    """
    ep  = f'/quests/{quest_id}/stages/{stage_id}/briefing'
    url = _base_url(ver) + ep + f'?difficulty={difficulty}'
    r   = requests.get(url, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def zbattleBriefing(ver, os, token, secret, stage_id: int):
    """
    GET /z_battles/{stage_id}/briefing — briefing d'un Z-Battle.
    CORRECTION : /z_battles/ (pas /eza_battles/).
    """
    ep = f'/z_battles/{stage_id}/briefing'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ RM BATTLES

def rmBattles(ver, os, token, secret):
    """
    GET /rmbattles — RM Battles disponibles.
    CORRECTION : /rmbattles (sans underscore, pas /rm_battles).
    """
    ep = '/rmbattles'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def rmBattleDetails(ver, os, token, secret, battle_id: int):
    """
    GET /rmbattles/{battle_id} — détails d'un RM Battle.
    CORRECTION : /rmbattles/ (pas /rm_battles/).
    """
    ep = f'/rmbattles/{battle_id}'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def rmBattleAvailableCards(ver, os, token, secret):
    """
    GET /rmbattles/available_user_cards — cartes disponibles pour RM Battle.
    CORRECTION : /rmbattles/available_user_cards (pas /rm_battles/available_cards).
    """
    ep = '/rmbattles/available_user_cards'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def rmBattleAvailableCardsForClash(ver, os, token, secret, clash_id: int = 0):
    """
    GET /rmbattles/available_user_cards — même endpoint pour Clash.
    CORRECTION : même endpoint que rmBattleAvailableCards (pas /available_cards_for_clash).
    """
    ep = '/rmbattles/available_user_cards'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def rmBattleTeam(ver, os, token, secret, battle_id: int):
    """
    GET /rmbattles/teams/{battle_id} — équipe d'un RM Battle.
    CORRECTION : /rmbattles/teams/{id} (structure inversée vs /rm_battles/{id}/team).
    """
    ep = f'/rmbattles/teams/{battle_id}'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def setRmBattleTeam(ver, os, token, secret, battle_id: int, team_data: dict):
    """
    PUT /rmbattles/teams/{battle_id} — définit l'équipe d'un RM Battle.
    CORRECTION : méthode PUT (pas POST) + /rmbattles/teams/{id}.
    """
    ep = f'/rmbattles/teams/{battle_id}'
    r  = requests.put(_base_url(ver) + ep, data=json.dumps(team_data),
                      headers=_headers(ver, os, token, secret, 'PUT', ep), timeout=_TIMEOUT)
    return _safe(r)


def setRmBattleTeamForClash(ver, os, token, secret, battle_id: int, team_data: dict):
    """
    PUT /rmbattles/teams/{battle_id} — même endpoint pour Clash.
    CORRECTION : même endpoint que setRmBattleTeam (pas /team_for_clash).
    """
    ep = f'/rmbattles/teams/{battle_id}'
    r  = requests.put(_base_url(ver) + ep, data=json.dumps(team_data),
                      headers=_headers(ver, os, token, secret, 'PUT', ep), timeout=_TIMEOUT)
    return _safe(r)


def startRmBattleStageDetailed(ver, os, token, secret, battle_id: int, stage_id: int):
    """
    POST /rmbattles/{battle_id}/stages/{stage_id}/start — démarre un stage RM.
    CORRECTION : /rmbattles/ (sans underscore).
    """
    ep = f'/rmbattles/{battle_id}/stages/{stage_id}/start'
    r  = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                       headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def finishRmBattleStageDetailed(ver, os, token, secret, battle_id: int, stage_id: int, result: dict):
    """
    POST /rmbattles/{battle_id}/stages/{stage_id}/finish — finit un stage RM.
    CORRECTION : /rmbattles/ (sans underscore).
    """
    ep = f'/rmbattles/{battle_id}/stages/{stage_id}/finish'
    r  = requests.post(_base_url(ver) + ep, data=json.dumps(result),
                       headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def dropoutRmBattle(ver, os, token, secret, battle_id: int):
    """
    POST /rmbattles/{battle_id}/stages/dropout — abandonne un RM Battle.
    CORRECTION : /rmbattles/{id}/stages/dropout (pas /rm_battles/{id}/dropout).
    """
    ep = f'/rmbattles/{battle_id}/stages/dropout'
    r  = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                       headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def resetRmBattle(ver, os, token, secret, battle_id: int):
    """
    POST /rmbattles/{battle_id}/reset — remet à zéro un RM Battle.
    CORRECTION : /rmbattles/ (pas /rm_battles/).
    """
    ep   = f'/rmbattles/{battle_id}/reset'
    r    = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                         headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def getClashTeam(ver, os, token, secret, clash_id: int):
    """GET /clash_battles/<id>/team — équipe d'un Clash Battle."""
    ep = f'/clash_battles/{clash_id}/team'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ GIRU NAV

def giruNavGrowth(ver, os, token, secret):
    """GET /giru_nav/growth_records — progression Giru Nav."""
    ep = '/giru_nav/growth_records'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def giruNavUnacquired(ver, os, token, secret):
    """POST /giru_nav/acquire_unacquired_growth_records — réclame les rewards Giru."""
    ep = '/giru_nav/acquire_unacquired_growth_records'
    r  = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                       headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ MISC

def ping(ver, os, token, secret):
    """GET /ping — ping serveur Dokkan."""
    ep = '/ping'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def databaseStatus(ver, os, token, secret):
    """GET /client_assets/database — version de la base de données."""
    ep = '/client_assets/database'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def cooperationCampaigns(ver, os, token, secret):
    """GET /cooperation_campaigns — campagnes de coopération actives."""
    ep = '/cooperation_campaigns'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def jointCampaigns(ver, os, token, secret):
    """GET /joint_campaigns — campagnes conjointes actives."""
    ep = '/joint_campaigns'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def itemReverseResolutionsAwakening(ver, os, token, secret):
    """GET /item_reverse_resolutions/awakening_items — stages par médaille d'éveil."""
    ep = '/item_reverse_resolutions/awakening_items'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def itemReverseResolutionsQuestLimitation(ver, os, token, secret):
    """GET /item_reverse_resolutions/quest_limitation_items."""
    ep = '/item_reverse_resolutions/quest_limitation_items'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def eventkagi_events(ver, os, token, secret):
    """GET /eventkagi_events — événements kagi actifs."""
    ep = '/eventkagi_events'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


def eventkagi_items(ver, os, token, secret):
    """GET /eventkagi_items — items kagi disponibles."""
    ep = '/eventkagi_items'
    r  = requests.get(_base_url(ver) + ep, headers=_headers(ver, os, token, secret, 'GET', ep), timeout=_TIMEOUT)
    return _safe(r)


# ══════════════════════════════════════════════════════════════ GOOGLE AUTH

def googleLink(ver, os, token, secret, body: dict):
    """POST /user/link/google — lie un compte Google."""
    ep = '/user/link/google'
    r  = requests.post(_base_url(ver) + ep, data=json.dumps(body),
                       headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def googleValidate(ver, os, token, secret, body: dict):
    """POST /user/link/google/validate — valide la liaison Google."""
    ep = '/user/link/google/validate'
    r  = requests.post(_base_url(ver) + ep, data=json.dumps(body),
                       headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def googleSucceedValidate(ver, os, token, secret):
    """POST /user/link/google/succeed_validate."""
    ep = '/user/link/google/succeed_validate'
    r  = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                       headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def googleSucceed(ver, os, token, secret):
    """POST /user/link/google/succeed."""
    ep = '/user/link/google/succeed'
    r  = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                       headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)


def googleUnlink(ver, os, token, secret):
    """DELETE /user/link/google — supprime la liaison Google."""
    ep = '/user/link/google'
    r  = requests.delete(_base_url(ver) + ep,
                         headers=_headers(ver, os, token, secret, 'DELETE', ep), timeout=_TIMEOUT)
    return _safe(r)


def googleUserSucceeds(ver, os, token, secret):
    """POST /user/succeeds — finalise la récupération du compte via Google."""
    ep = '/user/succeeds'
    r  = requests.post(_base_url(ver) + ep, data=json.dumps({}),
                       headers=_headers(ver, os, token, secret, 'POST', ep), timeout=_TIMEOUT)
    return _safe(r)
