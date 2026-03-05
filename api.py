'''
api.py — DokkanClient : interface haut niveau pour discord_bot.py.
Délègue l'auth à auth.py (DokkanAuth) et les appels API à ingame.py.
'''
import json
import time
import random
import requests
from typing import Optional, Dict, List

import config
import ingame
import crypto
from auth import DokkanAuth

RARITY_MAP = {1: 'N', 2: 'R', 3: 'SR', 4: 'SSR', 5: 'UR', 6: 'LR'}
TYPE_MAP   = {1: 'AGL', 2: 'TEQ', 3: 'INT', 4: 'STR', 5: 'PHY',
              6: 'S.AGL', 7: 'S.TEQ', 8: 'S.INT', 9: 'S.STR', 10: 'S.PHY'}


def _extract_secret_from_identifier(identifier: str) -> str:
    '''Extrait le secret MAC depuis l'identifier Dokkan (base64(secret:username)).'''
    if not identifier:
        return ''
    try:
        import base64 as _b64
        decoded = _b64.b64decode(identifier).decode('utf-8', errors='replace')
        parts = decoded.split(':')
        if len(parts) >= 2 and len(parts[0]) > 20:
            return parts[0].strip()
    except Exception:
        pass
    return ''


class DokkanClient:
    '''
    Client haut niveau Dokkan Battle.
    Auth  → auth.py (DokkanAuth)
    Appels → ingame.py (fonctions pures)
    '''

    def __init__(self, region: str = 'GLOBAL', os_type: str = 'android'):
        ver        = 'gb' if region.upper() == 'GLOBAL' else 'jp'
        self._auth = DokkanAuth(ver=ver, os_type=os_type)
        self.region   = self._auth.region
        self.ver      = self._auth.ver
        self.os_type  = os_type.lower()
        self.base_url = self._auth.base_url
        self.os       = 'ANDROID' if os_type.lower() == 'android' else 'IOS'
        self._cards_cache: Optional[List[Dict]] = None

    # ── Raccourcis vers les credentials ──────────────────────────────────────
    @property
    def user_id(self)    -> Optional[str]: return self._auth.user_id
    @property
    def token(self)      -> Optional[str]: return self._auth.token
    @property
    def secret(self)     -> Optional[str]: return self._auth.secret
    @property
    def identifier(self) -> Optional[str]: return self._auth.identifier
    @property
    def ad_id(self)      -> Optional[str]: return self._auth.ad_id
    @property
    def unique_id(self)  -> Optional[str]: return self._auth.unique_id

    # ── AUTH ──────────────────────────────────────────────────────────────────

    def create_account(self) -> Dict:
        return self._auth.sign_up()

    def login_with_token(self, user_id: str, token: str,
                         secret: str = '', identifier: str = '',
                         ad_id: str = '', unique_id: str = '') -> bool:
        # FIX : si secret vide, l'extraire depuis l'identifier avant de charger
        if not secret and identifier:
            secret = _extract_secret_from_identifier(identifier) or identifier
        self._auth.load_credentials(
            user_id=user_id, token=token, secret=secret,
            identifier=identifier, ad_id=ad_id, unique_id=unique_id,
        )
        return self._auth.verify()

    def refresh_token(self) -> Dict:
        return self._auth.refresh()

    # ── INFO ──────────────────────────────────────────────────────────────────

    def get_info(self) -> Optional[Dict]:
        return self._call(ingame.user)

    def get_account_summary(self) -> Dict:
        data = self.get_info()
        if not data:
            return {'error': 'Could not reach Dokkan servers'}
        if 'error' in data:
            return data
        u = data.get('user', {})
        max_act = u.get('max_act') or u.get('act_max') or u.get('max_stamina') or 0
        return {
            'Region':              self.region,
            'Account OS':          self.os,
            'User ID':             u.get('id'),
            'Stones':              u.get('stone', 0),
            'Zeni':                u.get('zeni', 0),
            'Rank':                u.get('rank', 0),
            'Stamina':             f"{u.get('act', 0)}/{max_act}",
            'Name':                u.get('name', '???'),
            'Total Card Capacity': u.get('card_capacity', 0),
        }

    # ── CARTES ────────────────────────────────────────────────────────────────

    def get_user_cards(self, force_refresh: bool = False) -> List[Dict]:
        if self._cards_cache and not force_refresh:
            return self._cards_cache
        data = self._call(ingame.cards)
        if data:
            self._cards_cache = data.get('cards', [])
            return self._cards_cache
        return []

    def sell_cards(self, card_ids: List[int]) -> Dict:
        return self._call(ingame.sell, card_ids) or {}

    def get_teams(self) -> Dict:
        return self._call(ingame.getTeams) or {}

    def increase_card_capacity(self) -> Dict:
        return self._call(ingame.capacity) or {}

    # ── STAGES ────────────────────────────────────────────────────────────────

    # ── Constantes de décodage sugoroku_map_id ───────────────────────────────
    # sugoroku_map_id = quest_id * 10 + difficulty
    # difficulty : 0=Normal, 1=Hard, 2=Very Hard
    # area_id est encodé dans quest_id // 1000
    # Plages d'area_id par type :
    #   1-39    → Quêtes histoire (story)
    #   100-899 → Événements (events)
    #   900-999 → Z-Battles (old)
    #   1000+   → DB Stories
    DIFF_VH     = 2   # Very Hard — le plus rentable
    DIFF_NORMAL = 0

    def _get_user_areas_raw(self) -> List[Dict]:
        '''
        GET /user_areas — retourne les zones brutes.
        Fallback sur /resources/login si vide.
        '''
        import logging as _log
        log = _log.getLogger('DokkanBot')

        data = self._call(ingame.quests)
        http = data.get('_http_status', 200) if isinstance(data, dict) else '?'
        err  = data.get('error') if isinstance(data, dict) else None
        areas = data.get('user_areas', []) if isinstance(data, dict) else []
        log.info('[user_areas] http=%s err=%s areas=%d', http, err, len(areas))

        if areas:
            return areas

        # Fallback /resources/login
        log.info('[user_areas] fallback → resourcesLogin')
        res = self._call(ingame.resourcesLogin)
        http2 = res.get('_http_status', 200) if isinstance(res, dict) else '?'
        areas2 = res.get('user_areas', []) if isinstance(res, dict) else []
        log.info('[user_areas] resourcesLogin http=%s areas=%d', http2, len(areas2))
        return areas2

    def get_stages(self, area_id: Optional[int] = None) -> List[Dict]:
        '''
        CORRIGÉ : retourne les stages avec les vrais champs de l'API.
        Chaque stage a : sugoroku_map_id, visited_count, cleared_count, area_id
        '''
        areas = self._get_user_areas_raw()
        stages = []
        for area in areas:
            aid = area['area_id']
            if area_id is not None and aid != area_id:
                continue
            for s in area.get('user_sugoroku_maps', []):
                s['area_id'] = aid
                stages.append(s)
        return stages

    def get_story_stages(self, only_uncleared: bool = True, difficulty: int = None) -> List[int]:
        '''
        Retourne les sugoroku_map_ids des quêtes histoire (areas 1-39).
        Si difficulty=None, prend toutes les difficultés disponibles (Normal+Hard+VH).
        Un compte rang 1 n'a que Normal, un compte avancé a VH.
        '''
        areas = self._get_user_areas_raw()
        ids = []
        for area in areas:
            if not (1 <= area['area_id'] <= 39):
                continue
            for m in area.get('user_sugoroku_maps', []):
                if difficulty is not None and m['sugoroku_map_id'] % 10 != difficulty:
                    continue
                if only_uncleared and m.get('cleared_count', 0) > 0:
                    continue
                ids.append(m['sugoroku_map_id'])
        return ids

    def get_event_stage_ids(self, only_unvisited: bool = False) -> List[int]:
        '''
        Retourne les sugoroku_map_ids des events.
        Sources : /events → /user_areas 100-899 → /resources/login inline
        '''
        import logging as _log
        log = _log.getLogger('DokkanBot')

        ids = []

        # Source 1 : /events
        data = self._call(ingame.events)
        http = data.get('_http_status', 200) if isinstance(data, dict) else '?'
        err  = data.get('error') if isinstance(data, dict) else None
        log.info('[get_events] /events http=%s err=%s', http, err)

        if isinstance(data, dict) and not err and http == 200:
            event_list = data.get('events') or data.get('user_events') or (data if isinstance(data, list) else [])
            if isinstance(event_list, dict):
                event_list = list(event_list.values())
            log.info('[get_events] events_count=%d', len(event_list))
            for event in event_list:
                if not isinstance(event, dict):
                    continue
                quests = event.get('quests') or event.get('stages') or event.get('event_stages') or []
                for quest in quests:
                    if not isinstance(quest, dict):
                        continue
                    uq = quest.get('user_quest') or quest.get('user_stage') or {}
                    if only_unvisited and uq.get('visited_count', 0) > 0:
                        continue
                    visit_max = quest.get('visit_count_max') or quest.get('max_visit_count')
                    if visit_max and uq.get('visited_count', 0) >= visit_max:
                        continue
                    qid  = quest.get('id') or quest.get('quest_id') or quest.get('stage_id')
                    diff = quest.get('max_difficulty') or quest.get('difficulty_max') or 2
                    if qid:
                        try:
                            ids.append(int(qid) * 10 + int(diff))
                        except (TypeError, ValueError):
                            ids.append(int(qid) * 10 + 2)

        # Source 2 : /user_areas 100-899
        if not ids:
            log.info('[get_events] fallback → user_areas 100-899')
            for area in self._get_user_areas_raw():
                if 100 <= area.get('area_id', 0) <= 899:
                    for m in area.get('user_sugoroku_maps', []):
                        sid = m.get('sugoroku_map_id')
                        if sid:
                            ids.append(sid)
            log.info('[get_events] user_areas fallback → %d ids', len(ids))

        # Source 3 : /resources/login inline
        if not ids:
            log.info('[get_events] fallback → resourcesLogin inline')
            res = self._call(ingame.resourcesLogin)
            if isinstance(res, dict) and not res.get('error'):
                event_list = res.get('events', [])
                if isinstance(event_list, dict):
                    event_list = list(event_list.values())
                for event in event_list:
                    if not isinstance(event, dict):
                        continue
                    for quest in event.get('quests', event.get('stages', [])):
                        qid  = quest.get('id') or quest.get('quest_id')
                        diff = quest.get('max_difficulty', 2)
                        if qid:
                            try:
                                ids.append(int(qid) * 10 + int(diff))
                            except (TypeError, ValueError):
                                ids.append(int(qid) * 10 + 2)
            log.info('[get_events] resourcesLogin fallback → %d ids', len(ids))

        # Déduplique
        seen = set()
        ids  = [x for x in ids if not (x in seen or seen.add(x))]
        log.info('[get_events] total unique ids: %d', len(ids))
        return ids

    def get_zbattle_stage_ids(self, only_uncleared: bool = True) -> List[int]:
        '''Retourne les sugoroku_map_ids des Z-Battles (areas 900-999), toutes difficultés.'''
        areas = self._get_user_areas_raw()
        ids = []
        for area in areas:
            if not (900 <= area['area_id'] <= 999):
                continue
            for m in area.get('user_sugoroku_maps', []):
                if only_uncleared and m.get('cleared_count', 0) > 0:
                    continue
                ids.append(m['sugoroku_map_id'])
        return ids

    def get_dbstory_stage_ids(self, only_uncleared: bool = True) -> List[int]:
        '''Retourne les sugoroku_map_ids des DB Stories (areas 1000-1999), toutes difficultés.'''
        areas = self._get_user_areas_raw()
        ids = []
        for area in areas:
            if not (1000 <= area['area_id'] <= 1999):
                continue
            for m in area.get('user_sugoroku_maps', []):
                if only_uncleared and m.get('cleared_count', 0) > 0:
                    continue
                ids.append(m['sugoroku_map_id'])
        return ids

    def _get_kagi_data(self) -> Dict:
        '''GET /events/eventkagi_events — events et z-battles avec clé.'''
        return self._call(ingame.eventkagi_events) or {}

    def get_kagi_event_ids(self) -> List[int]:
        '''Retourne les stage IDs des events kagi disponibles (/eventkagi).''' 
        data = self._get_kagi_data()
        if not data:
            return []
        ids = []
        for event in data.get('eventkagi_events', []):
            if event.get('open_status') != 'available':
                continue
            for quest in event.get('quests', []):
                ids.append(quest['id'] * 10 + 2)
        return ids

    def get_kagi_zbattle_ids(self) -> List[int]:
        '''Retourne les IDs des Z-Battles kagi disponibles (/eventkagi).''' 
        data = self._get_kagi_data()
        return [
            zb['id'] for zb in data.get('eventkagi_z_battle_stages', [])
            if zb.get('open_status') == 'available'
        ]

    def get_events(self) -> Dict:
        '''GET /events — retourne la liste brute des événements.''' 
        return self._call(ingame.events) or {}

    def quick_finish_stage(self, stage_id: int, difficulty: int = None,
                           deck_id: int = 1, use_key: bool = False) -> Dict:
        '''
        Enchaîne getSupports → startStage → finishStage avec sign chiffré.
        difficulty=None → déduit depuis stage_id % 10 (encodé dans sugoroku_map_id).
        0=Normal, 1=Hard, 2=VeryHard, 3=SuperHard (certains events)

        CORRECTION CRITIQUE :
          sugoroku_map_id = quest_id * 10 + difficulty
          → quest_id = stage_id // 10
          → getSupports / startStage / finishStage prennent DEUX IDs distincts
        '''
        # Déduit la difficulté depuis l'ID si non fournie
        if difficulty is None:
            difficulty = stage_id % 10  # ex: 1234562 → diff=2 (VH)

        # CORRECTION : dériver quest_id depuis sugoroku_map_id
        quest_id = stage_id // 10

        # Support units - CORRECTION : 3 args (quest_id, stage_id, difficulty)
        store = self._call(ingame.getSupports, quest_id, stage_id, difficulty)
        if not store or 'error' in store:
            # Fallback diff=0 (Normal) si la difficulté déduite échoue
            if difficulty != 0:
                store = self._call(ingame.getSupports, quest_id, stage_id, 0)
                if not store or 'error' in store:
                    return store or {'error': f'getSupports failed (stage={stage_id} diff={difficulty})'}
                difficulty = 0
            else:
                return store or {'error': f'getSupports failed (stage={stage_id})'}

        # Choisit l'ami (CPU ou friend)
        difficulties = ['normal', 'hard', 'very_hard', 'super_hard1', 'super_hard2', 'super_hard3']
        diff_name    = difficulties[int(difficulty)] if int(difficulty) < len(difficulties) else 'normal'
        friend       = None
        friend_card  = None

        cpu = store.get('cpu_supporters', {})
        if cpu and diff_name in cpu and cpu[diff_name].get('is_cpu_only') and cpu[diff_name].get('cpu_friends'):
            friend      = cpu[diff_name]['cpu_friends'][0]['id']
            friend_card = cpu[diff_name]['cpu_friends'][0]['card_id']
        elif store.get('supporters'):
            friend      = store['supporters'][0]['id']
            friend_card = store['supporters'][0]['leader']['card_id']
        elif store.get('cpu_supporters'):
            # Fallback : premier CPU disponible toutes difficultés
            for dname, ddata in store['cpu_supporters'].items():
                if ddata.get('cpu_friends'):
                    friend      = ddata['cpu_friends'][0]['id']
                    friend_card = ddata['cpu_friends'][0]['card_id']
                    break

        if friend is None:
            return {'error': f'Aucun supporter (stage={stage_id} diff={difficulty})'}

        # Start - CORRECTION : 3 args (quest_id, stage_id, difficulty, ...)
        start = self._call(ingame.startStage, quest_id, stage_id, difficulty, friend, friend_card)
        if not start or 'error' in start:
            return start or {'error': f'startStage failed (stage={stage_id})'}

        try:
            data    = crypto.decrypt_sign(start['sign'])
            stoken  = data['token']
            paces   = [int(i) for i in data['sugoroku']['events']]
            defeated = []
            for i in data['sugoroku']['events']:
                ev = data['sugoroku']['events'][i]
                if isinstance(ev, dict) and 'battle_info' in ev.get('content', {}):
                    for j in ev['content']['battle_info']:
                        defeated.append(j['round_id'])
        except Exception as e:
            return {'error': f'decrypt_sign failed: {e}'}

        # Finish - CORRECTION : 3 args (quest_id, stage_id, difficulty, ...)
        finish = self._call(ingame.finishStage, quest_id, stage_id, difficulty, paces, defeated, stoken)
        return finish or {'error': 'finishStage failed'}

    def farm_stage_n_times(self, stage_id: int, count: int,
                           difficulty: int = 3) -> List[Dict]:
        results = []
        for i in range(count):
            r = self.quick_finish_stage(stage_id, difficulty)
            r['attempt'] = i + 1
            results.append(r)
            time.sleep(random.uniform(0.8, 1.6))
        return results

    # ── Z-Battles (EZA) ───────────────────────────────────────────────────────

    def quick_finish_zbattle(self, eza_id: int, level: int = 1) -> Dict:
        store = self._call(ingame.zSupports, eza_id)
        if not store or 'error' in store:
            return store or {'error': 'zSupports failed'}

        friend      = store['supporters'][0]['id']
        friend_card = store['supporters'][0]['leader']['card_id']

        start = self._call(ingame.zStart, eza_id, level, friend, friend_card)
        if not start or 'error' in start:
            return start or {'error': 'zStart failed'}

        try:
            dec    = crypto.decrypt_sign(start['sign'])
            em_hp  = [i['hp'] for i in dec['enemies'][0]]
            em_atk = sum(i['attack'] for i in dec['enemies'][0])
            stoken = dec['token']
        except Exception as e:
            return {'error': f'decrypt_sign failed: {e}'}

        finish = self._call(ingame.zFinish, eza_id, level, stoken, em_atk, em_hp)
        return finish or {'error': 'zFinish failed'}

    # ── Cadeaux / Missions ────────────────────────────────────────────────────

    def accept_gifts(self) -> Dict:
        store = self._call(ingame.gifts)
        if not store or 'error' in store:
            return store or {}
        presents = [i['id'] for i in store.get('gifts', [])]
        if not presents:
            return {'accepted': 0}
        return self._call(ingame.acceptGifts, presents) or {}

    def accept_missions(self) -> Dict:
        store = self._call(ingame.missions)
        if not store or 'error' in store:
            return store or {}
        ids = [i['id'] for i in store.get('missions', []) if i.get('completed_at')]
        if not ids:
            return {'claimed': 0}
        return self._call(ingame.acceptMissions, ids) or {}

    # ── Stamina ───────────────────────────────────────────────────────────────

    def refill_stamina(self, use_stone: bool = True) -> Dict:
        return self._call(ingame.actRefill) or {}

    # ── Google Auth ───────────────────────────────────────────────────────────

    def google_login(self, google_id_token: str) -> Dict:
        link = self._call(ingame.googleLink, google_id_token)
        if not link or link.get('_http_status', 200) not in (200, 201):
            return {'error': f'google_link failed: {link}'}
        validate = self._call(ingame.googleValidate, google_id_token)
        if not validate or validate.get('_http_status', 200) not in (200, 201):
            return {'error': f'google_validate failed: {validate}'}
        succeed = self._call(ingame.googleSucceedValidate, google_id_token)
        if not succeed or succeed.get('_http_status', 200) not in (200, 201):
            return {'error': f'google_succeed_validate failed: {succeed}'}
        final = self._call(ingame.googleUserSucceeds)
        return {
            'ok': True,
            'google_link': link,
            'validate': validate,
            'succeed': succeed,
            'final': final,
        }

    def google_transfer(self, google_id_token: str) -> Dict:
        succeed = self._call(ingame.googleSucceed, google_id_token)
        if not succeed or succeed.get('_http_status', 200) not in (200, 201):
            return {'error': f'google_succeed failed: {succeed}'}
        validate = self._call(ingame.googleSucceedValidate, google_id_token)
        if not validate or validate.get('_http_status', 200) not in (200, 201):
            return {'error': f'google_succeed_validate failed: {validate}'}
        final = self._call(ingame.googleUserSucceeds)
        user = (final or {}).get('user') or (validate or {}).get('user')
        if user:
            self._auth.user_id  = str(user.get('id', self._auth.user_id or ''))
            if final and final.get('access_token'):
                self._auth.token = final['access_token']
        return {
            'ok':      True,
            'succeed': succeed,
            'validate': validate,
            'final':   final,
            'user_id': self._auth.user_id,
            'token':   self._auth.token,
        }

    def google_unlink(self) -> Dict:
        return self._call(ingame.googleUnlink) or {}

    # ── Bulk Resources ────────────────────────────────────────────────────────

    def get_resources_login(self) -> Optional[Dict]:
        return self._call(ingame.resourcesLogin)

    def get_resources_home(self) -> Optional[Dict]:
        return self._call(ingame.resourcesHome)

    def get_resources_items(self) -> Optional[Dict]:
        return self._call(ingame.resourcesItems)

    # ── Éveils ────────────────────────────────────────────────────────────────

    def awaken_card(self, user_card_id: int) -> Dict:
        return self._call(ingame.awakenCard, user_card_id) or {}

    def bulk_optimal_awake(self, user_card_id: int) -> Dict:
        return self._call(ingame.bulkOptimalAwake, user_card_id) or {}

    def train_card(self, user_card_id: int, feed_card_ids: List[int]) -> Dict:
        return self._call(ingame.trainCard, user_card_id, feed_card_ids) or {}

    def exchange_cards(self, card_ids: List[int]) -> Dict:
        return self._call(ingame.exchangeCards, card_ids) or {}

    def unlock_potential(self, user_card_id: int, node_id: int, feed_card_ids: List[int]) -> Dict:
        return self._call(ingame.unlockPotential, user_card_id, node_id, feed_card_ids) or {}

    def get_cards_for_awaken(self) -> List[Dict]:
        cards = self.get_user_cards()
        return [c for c in cards if c.get('can_awaken') or c.get('awakening_id')]

    def full_awaken_sequence(self, user_card_id: int) -> Dict:
        result = self.bulk_optimal_awake(user_card_id)
        if result.get('error') or result.get('_http_status', 200) != 200:
            result = self.awaken_card(user_card_id)
        return result

    # ── Briefings stages ──────────────────────────────────────────────────────

    def get_quest_briefing(self, stage_id: int, difficulty: int = 3) -> Dict:
        quest_id = stage_id // 10
        return self._call(ingame.questBriefing, quest_id, stage_id, difficulty) or {}

    def get_zbattle_briefing(self, stage_id: int) -> Dict:
        return self._call(ingame.zbattleBriefing, stage_id) or {}

    # ── Login Bonuses ─────────────────────────────────────────────────────────

    def get_login_bonuses(self) -> Dict:
        return self._call(ingame.loginBonuses) or {}

    def accept_login_bonuses(self) -> Dict:
        return self._call(ingame.acceptLoginBonus) or {}

    # ── Missions avancées ─────────────────────────────────────────────────────

    def get_mission_board(self) -> Dict:
        return self._call(ingame.missionBoard) or {}

    # ── Boutiques ─────────────────────────────────────────────────────────────

    def get_shop_treasure(self) -> Dict:
        return self._call(ingame.shopTreasureItems) or {}

    def buy_treasure_item(self, item_id: int) -> Dict:
        return self._call(ingame.buyTreasureItem, item_id) or {}

    def get_shop_zeni(self) -> Dict:
        return self._call(ingame.shopZeniItems) or {}

    def buy_zeni_item(self, item_id: int) -> Dict:
        return self._call(ingame.buyZeniItem, item_id) or {}

    def get_shop_exchange(self) -> Dict:
        return self._call(ingame.shopExchangeItems) or {}

    def buy_exchange_item(self, item_id: int) -> Dict:
        return self._call(ingame.buyExchangeItem, item_id) or {}

    # ── DB Stories ────────────────────────────────────────────────────────────

    def get_db_stories(self) -> Dict:
        return self._call(ingame.dbStories) or {}

    # ── Wishes (Dragon Balls) ─────────────────────────────────────────────────

    def get_wishes(self) -> Dict:
        return self._call(ingame.wishes) or {}

    def collect_and_wish(self, wish_type: int = 1) -> Dict:
        data = self.get_wishes()
        if not data or 'error' in data:
            return data or {'error': 'Cannot reach wishes endpoint'}
        collected = data.get('dragon_balls', 0)
        if collected >= 7:
            sets_data = self._call(ingame.dragonballs)
            return {
                'dragon_balls_collected': collected,
                'dragonball_sets': sets_data,
                'note': 'Wish logic requires dragonball_set_id — use get_wishes() + buy_exchange_item()'
            }
        return {'dragon_balls_collected': collected, 'wish_ready': False}

    # ── Compensations ─────────────────────────────────────────────────────────

    def get_apologies(self) -> Dict:
        return self._call(ingame.apologies) or {}

    def accept_apologies(self) -> Dict:
        return self._call(ingame.acceptApologies) or {}

    # ── Stamina (viande) ──────────────────────────────────────────────────────

    def refill_stamina_items(self) -> Dict:
        return self._call(ingame.actRefillWithItems) or {}

    # ── Tutorial ──────────────────────────────────────────────────────────────

    def finish_tutorial(self) -> Dict:
        return self._call(ingame.tutorialFinish) or {}

    def tutorial_gasha(self) -> Dict:
        return self._call(ingame.tutorialGasha) or {}

    # ── RM Battles ───────────────────────────────────────────────────────────

    def get_rm_battles(self) -> Dict:
        return self._call(ingame.rmBattles) or {}

    def get_rm_battle_cards(self) -> Dict:
        return self._call(ingame.rmBattleAvailableCards) or {}

    def get_rm_battle_team(self, battle_id: int) -> Dict:
        return self._call(ingame.rmBattleTeam, battle_id) or {}

    def set_rm_battle_team(self, battle_id: int, team_data: dict) -> Dict:
        return self._call(ingame.setRmBattleTeam, battle_id, team_data) or {}

    def dropout_rm_battle(self, battle_id: int) -> Dict:
        return self._call(ingame.dropoutRmBattle, battle_id) or {}

    # ── Invocations ───────────────────────────────────────────────────────────

    def get_banners(self) -> List[Dict]:
        data = self._call(ingame.banners)
        return data.get('gashas', []) if data else []

    def summon(self, gacha_id: int, course: int = 2) -> Dict:
        return self._call(ingame.summon, gacha_id, course) or {}

    def summon_until_card(self, gacha_id: int, target_card_id: int,
                          max_pulls: int = 500, course: int = 2) -> Dict:
        stones_spent = 0
        for i in range(max_pulls):
            r = self.summon(gacha_id, course)
            stones_spent += 50
            if any(c.get('item_id') == target_card_id for c in r.get('gasha_items', [])):
                return {'found': True, 'pulls': i + 1, 'stones_spent': stones_spent}
            time.sleep(random.uniform(0.5, 1.0))
        return {'found': False, 'pulls': max_pulls, 'stones_spent': stones_spent}

    # ── Eventkagi (clés events) ───────────────────────────────────────────────

    def get_eventkagi_events(self) -> Dict:
        return self._call(ingame.eventkagi_events) or {}

    def get_eventkagi_items(self) -> Dict:
        return self._call(ingame.eventkagi_items) or {}

    def get_kagi_event_ids_from_dedicated(self) -> List[int]:
        data = self.get_eventkagi_events()
        if not data or 'error' in data:
            return []
        ids = []
        for event in data.get('eventkagi_events', []):
            if event.get('open_status') != 'available':
                continue
            for quest in event.get('quests', []):
                ids.append(quest['id'] * 10 + 2)
        return ids

    def get_kagi_zbattle_ids_from_dedicated(self) -> List[int]:
        data = self.get_eventkagi_events()
        return [
            zb['id'] for zb in data.get('eventkagi_z_battle_stages', [])
            if zb.get('open_status') == 'available'
        ]

    # ── Giru Nav ──────────────────────────────────────────────────────────────

    def get_giru_growth(self) -> Dict:
        return self._call(ingame.giruNavGrowth) or {}

    def get_giru_unacquired(self) -> Dict:
        return self._call(ingame.giruNavUnacquired) or {}

    # ── Database / Ping ───────────────────────────────────────────────────────

    def get_database_status(self) -> Dict:
        return self._call(ingame.databaseStatus) or {}

    def ping_server(self) -> Dict:
        return self._call(ingame.ping) or {}

    # ── Item Reverse Resolutions ──────────────────────────────────────────────

    def get_item_reverse_resolutions(self, resolution_type: str = 'awakening_items') -> Dict:
        if resolution_type == 'quest_limitation_cards':
            return self._call(ingame.itemReverseResolutionsQuestLimitation) or {}
        return self._call(ingame.itemReverseResolutionsAwakening) or {}

    def find_farmable_stages_for_medal(self, awakening_item_id: int) -> List[Dict]:
        data = self.get_item_reverse_resolutions('awakening_items')
        if not data or 'error' in data:
            return []
        resolutions = data.get('item_reverse_resolutions', data) if isinstance(data, dict) else []
        if isinstance(resolutions, dict):
            resolutions = [resolutions]
        return [r for r in resolutions if r.get('awakening_item_id') == awakening_item_id]

    # ── Campaigns ─────────────────────────────────────────────────────────────

    def get_cooperation_campaigns(self) -> Dict:
        return self._call(ingame.cooperationCampaigns) or {}

    def get_joint_campaigns(self) -> Dict:
        return self._call(ingame.jointCampaigns) or {}

    # ── Baba Shop ─────────────────────────────────────────────────────────────

    def get_baba_shop(self) -> Dict:
        return self._call(ingame.babashopItems) or {}

    def buy_baba_item(self, item_id: int) -> Dict:
        return self._call(ingame.buyBabaItem, item_id) or {}

    def exchange_cards_to_baba(self, card_ids: List[int]) -> Dict:
        return self._call(ingame.exchangeCardsToBaba, card_ids) or {}

    def autosell_to_baba(self, rarity_threshold: int = 3) -> Dict:
        cards = self.get_user_cards()
        to_exchange = [c['id'] for c in cards if c.get('rarity', 0) <= rarity_threshold]
        if not to_exchange:
            return {'exchanged': 0, 'message': 'No cards below that rarity'}
        results = []
        for i in range(0, len(to_exchange), 100):
            batch = to_exchange[i:i+100]
            r = self.exchange_cards_to_baba(batch)
            results.append(r)
        return {'exchanged': len(to_exchange), 'batches': len(results)}

    # ── Dragon Balls / Wishes ─────────────────────────────────────────────────

    def get_dragonball_sets(self) -> Dict:
        return self._call(ingame.dragonballs) or {}

    def get_dragonball_wishes_for_set(self, dragonball_set_id: int) -> Dict:
        return self._call(ingame.dragonballWishes, dragonball_set_id) or {}

    def make_dragonball_wish(self, dragonball_set_id: int, wish_ids: List[int]) -> Dict:
        return self._call(ingame.makeWish, dragonball_set_id, wish_ids) or {}

    def collect_and_wish_smart(self) -> Dict:
        sets_data = self.get_dragonball_sets()
        if not sets_data or 'error' in sets_data:
            return sets_data or {'error': 'Cannot reach dragonball endpoint'}
        db_sets = sets_data.get('dragonball_sets', [])
        if not db_sets:
            return {'dragon_balls': 0, 'wish_made': False, 'message': 'No dragonball sets found'}
        results = []
        for db_set in db_sets:
            set_id    = db_set.get('id')
            collected = db_set.get('dragonball_count', 0) or len([b for b in db_set.get('dragonballs', []) if b.get('collected')])
            if collected < 7:
                results.append({'set_id': set_id, 'collected': collected, 'wish_made': False})
                continue
            wishes = self.get_dragonball_wishes_for_set(set_id)
            available = wishes.get('dragonball_wishes', wishes.get('wishes', []))
            if not available:
                results.append({'set_id': set_id, 'collected': collected, 'wish_made': False, 'reason': 'no wishes available'})
                continue
            wish = next((w for w in available if w.get('is_wishable') or w.get('wishable')), available[0])
            wish_result = self.make_dragonball_wish(set_id, [wish['id']])
            results.append({'set_id': set_id, 'collected': collected, 'wish_made': True, 'wish': wish.get('name', wish['id']), 'result': wish_result})
        return {'sets': results, 'wishes_made': sum(1 for r in results if r.get('wish_made'))}

    # ── Ultimate Clash ────────────────────────────────────────────────────────

    def get_clash_details(self, clash_id: int) -> Dict:
        return self._call(ingame.rmBattleDetails, clash_id) or {}

    def get_clash_available_cards(self, clash_id: int = 0) -> Dict:
        return self._call(ingame.rmBattleAvailableCardsForClash, clash_id) or {}

    def get_clash_team(self, clash_id: int) -> Dict:
        return self._call(ingame.getClashTeam, clash_id) or {}

    def set_clash_team(self, clash_id: int, team_data: dict) -> Dict:
        return self._call(ingame.setRmBattleTeamForClash, clash_id, team_data) or {}

    def start_clash_stage(self, clash_id: int, stage_id: int) -> Dict:
        return self._call(ingame.startRmBattleStageDetailed, clash_id, stage_id) or {}

    def finish_clash_stage(self, clash_id: int, stage_id: int, result: dict) -> Dict:
        return self._call(ingame.finishRmBattleStageDetailed, clash_id, stage_id, result) or {}

    def reset_clash(self, clash_id: int) -> Dict:
        return self._call(ingame.resetRmBattle, clash_id) or {}

    def complete_clash(self) -> Dict:
        data = self.get_rm_battles()
        if not data or 'error' in data:
            return data or {'error': 'No RM Battles found'}
        battles = data.get('rmbattles', [])
        if not battles:
            return {'cleared': 0, 'message': 'No active RM Battles'}
        cleared = 0
        errors  = []
        for battle in battles:
            bid    = battle.get('id')
            stages = battle.get('stages') or battle.get('rmbattle_stages', [])
            for stage in stages:
                sid = stage.get('id')
                if stage.get('cleared') or stage.get('status') == 'cleared':
                    continue
                start = self.start_clash_stage(bid, sid)
                if start.get('error') or start.get('_http_status', 200) >= 400:
                    errors.append({'clash': bid, 'stage': sid, 'error': start})
                    continue
                result = {
                    'is_cleared':  True,
                    'elapsed_time': random.randint(60000, 120000),
                }
                finish = self.finish_clash_stage(bid, sid, result)
                if finish.get('error') or finish.get('_http_status', 200) >= 400:
                    errors.append({'clash': bid, 'stage': sid, 'error': finish})
                else:
                    cleared += 1
                time.sleep(random.uniform(0.5, 1.0))
        return {'cleared': cleared, 'errors': errors}

    # ── Helper interne ────────────────────────────────────────────────────────

    _TOKEN_EXPIRED_CODES = {
        'invalid_token',
        'oauth2_bearer_rails/access_token_required',
        'oauth2_bearer_rails/expired_token',
        'access_token_required',
        'expired_token',
    }

    def _call(self, fn, *args):
        '''Appelle fn(ver, os, token, secret, *args). Auto-refresh sur 400/401/403.'''
        import logging as _log
        log = _log.getLogger('DokkanBot')

        if not self.token:
            return {'error': 'Non authentifié — token manquant'}

        # FIX : extraire le secret depuis l'identifier si manquant
        if not self._auth.secret and self._auth.identifier:
            extracted = _extract_secret_from_identifier(self._auth.identifier)
            if extracted:
                self._auth.secret = extracted
                log.info('[_call] Secret extrait depuis identifier (%d chars)', len(extracted))

        try:
            result = fn(self.ver, self.os_type, self.token, self.secret, *args)

            http = result.get('_http_status', 200) if isinstance(result, dict) else 200
            err_code = ''
            if isinstance(result, dict):
                err = result.get('error', {})
                err_code = err.get('code', '') if isinstance(err, dict) else str(err)

            needs_refresh = (
                http in (401, 403)
                or err_code in self._TOKEN_EXPIRED_CODES
                or (http == 400 and 'access_token' in err_code)
            )

            if needs_refresh:
                log.warning('[_call] %s → HTTP %d err=%s → refresh token',
                            getattr(fn, '__name__', '?'), http, err_code)
                if self._auth.identifier:
                    try:
                        self._auth.sign_in()
                        # Après sign_in, s'assurer que le secret est bien présent
                        if not self._auth.secret and self._auth.identifier:
                            extracted = _extract_secret_from_identifier(self._auth.identifier)
                            if extracted:
                                self._auth.secret = extracted
                        result = fn(self.ver, self.os_type, self.token, self.secret, *args)
                    except Exception as re:
                        log.warning('[_call] refresh échoué: %s', re)

            return result
        except Exception as e:
            return {'error': str(e)}
