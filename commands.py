import time
import random
import logging
from typing import Dict, List, Optional
from api import DokkanClient

log = logging.getLogger('DokkanBot')


# ═══════════════════════════════════════════════════════════ INIT HELPER

def _ensure_ready(client: DokkanClient) -> dict:
    """
    Vérifie et corrige l'état du compte avant tout farm.
    Retourne un dict de diagnostic {'secret_ok', 'rank', 'tutorial_done'}.
    
    Problèmes gérés :
    1. secret="" → l'extraire depuis l'identifier (il y est toujours)
    2. rank=1 (tutoriel pas fini) → tutorialFinish + tutorialGasha + resourcesLogin
    """
    import ingame as _ig

    diag = {'secret_ok': False, 'rank': 0, 'tutorial_done': False}

    # ── 1. Secret manquant ────────────────────────────────────────────────────
    if not client._auth.secret:
        identifier = client._auth.identifier or ''
        if identifier:
            try:
                import base64 as _b64
                temp = identifier.replace('\n', '').strip()
                while len(temp) < 159:
                    temp = temp.ljust(159, '\x08')
                decoded = _b64.b64decode(temp).decode('utf-8', errors='replace')
                parts   = decoded.split(':')
                if len(parts) >= 2 and len(parts[0]) > 20:
                    client._auth.secret = parts[0]
                    log.info('[ensure_ready] Secret extrait depuis identifier (%d chars)', len(parts[0]))
            except Exception as e:
                log.warning('[ensure_ready] Extraction secret échouée: %s', e)
        if not client._auth.secret:
            # Dernier recours : sign_in
            try:
                client._auth.sign_in()
                log.info('[ensure_ready] Secret obtenu via sign_in: %s', 'OK' if client._auth.secret else 'VIDE')
            except Exception as e:
                log.warning('[ensure_ready] sign_in échoué: %s', e)

    diag['secret_ok'] = bool(client._auth.secret)
    log.info('[ensure_ready] secret=%s', '✓' if diag['secret_ok'] else '✗ VIDE')

    # ── 2. Rang du compte ─────────────────────────────────────────────────────
    info = client.get_info()
    if not info or info.get('error') or info.get('_http_status'):
        log.warning('[ensure_ready] get_info() échoué: %s', info)
        return diag

    rank = info.get('user', {}).get('rank', 0)
    diag['rank'] = rank
    log.info('[ensure_ready] rank=%d stones=%d', rank, info.get('user', {}).get('stone', 0))

    # ── 3. Tutoriel (rang 1 = bloqué) ────────────────────────────────────────
    # rank=1 NE signifie PAS que le tuto n'est pas fait.
    # Vérifier d'abord avec GET /user_areas (MAC — fiable).
    if rank <= 1:
        areas_resp  = client._call(_ig.quests)  # GET /user_areas
        areas_count = len((areas_resp or {}).get('user_areas', []))
        log.info('[ensure_ready] rank=1 → /user_areas: areas=%d', areas_count)

        if areas_count > 0:
            # Compte opérationnel : tuto déjà fait dans auth._finalize()
            log.info('[ensure_ready] areas=%d → tuto déjà fait, skip', areas_count)
            diag['tutorial_done'] = True
        else:
            # Vrai compte bloqué : relancer la séquence complète en Bearer
            log.info('[ensure_ready] areas=0 → relance séquence tutoriel Bearer...')
            from auth import tutorial_full_sequence, resources_login_request
            bearer = client._auth.token  # Bearer (auth.py self.token après sign_in)

            try:
                # PUT /tutorial 50101 → POST /tutorial/gasha → PUT /tutorial 60101..150101
                tuto = tutorial_full_sequence(client.ver, client.os_type, bearer)
                log.info('[ensure_ready] tutorialSequence → %s', tuto)

                # resources/login final pour charger les areas
                r = resources_login_request(client.ver, client.os_type, bearer,
                                            user_card_updated_at=0)
                n = len(r.get('user_areas', [])) if isinstance(r, dict) else 0
                log.info('[ensure_ready] resourcesLogin post-tuto → http=%s areas=%d',
                         r.get('_http_status', '?') if isinstance(r, dict) else '?', n)
            except Exception as e:
                log.error('[ensure_ready] Séquence tutoriel échouée: %s', e)

            diag['tutorial_done'] = True
    else:
        diag['tutorial_done'] = True

    return diag



def cmd_info(client: DokkanClient) -> Dict:
    return client.get_account_summary()


def cmd_omegafarm(client: DokkanClient) -> Dict:
    results = {}
    results["quests"]    = cmd_quests(client)
    results["events"]    = cmd_events(client)
    results["zbattles"]  = cmd_zbattles(client)
    results["dbstories"] = cmd_dbstories(client)
    total = sum(r.get("cleared", 0) for r in results.values())
    results["total_cleared"] = total
    return results


def cmd_dailyfarm(client: DokkanClient) -> Dict:
    """Farm complet journalier avec init automatique du compte."""
    results = {}

    # ── 0. Init : secret + tutoriel ──────────────────────────────────────────
    diag = _ensure_ready(client)
    if not diag['secret_ok']:
        return {'error': 'Secret manquant — impossible de faire des requêtes MAC. Recréez le compte avec !create.'}

    stones_before = None
    try:
        info = client.get_info()
        if info and not info.get('error'):
            stones_before = info.get('user', {}).get('stone', 0)
    except Exception:
        pass

    # ── 1. Récompenses passives ───────────────────────────────────────────────
    for key, fn in [
        ('loginbonus', client.accept_login_bonuses),
        ('apologies',  client.accept_apologies),
        ('gift',       client.accept_gifts),
        ('missions',   client.accept_missions),
    ]:
        try:
            results[key] = fn()
        except Exception as e:
            results[key] = {'error': str(e), 'claimed': 0}
        time.sleep(random.uniform(0.3, 0.6))

    # ── 2. Farm des stages ────────────────────────────────────────────────────
    for key, fn in [
        ('quests',       cmd_quests),
        ('events',       cmd_events),
        ('zbattles',     cmd_zbattles),
        ('dbstories',    cmd_dbstories),
        ('keyevents',    cmd_keyevents),
        ('superzbattles',cmd_superzbattles),
    ]:
        try:
            results[key] = fn(client)
        except Exception as e:
            results[key] = {'cleared': 0, 'error': str(e)}

    # ── 3. Dragon Balls ───────────────────────────────────────────────────────
    try:
        results['wishes'] = cmd_wishes(client)
    except Exception as e:
        results['wishes'] = {'error': str(e)}
    time.sleep(random.uniform(0.5, 1.0))

    # ── 4. Ultimate Clash ─────────────────────────────────────────────────────
    try:
        results['clash'] = cmd_clash(client)
    except Exception as e:
        results['clash'] = {'cleared': 0, 'error': str(e)}
    time.sleep(random.uniform(0.5, 1.0))

    # ── 5. Éveils ─────────────────────────────────────────────────────────────
    try:
        results['awakenall'] = cmd_awakenall(client)
    except Exception as e:
        results['awakenall'] = {'processed': 0, 'error': str(e)}
    time.sleep(random.uniform(0.5, 1.0))

    # ── 6. Nettoyage cartes ───────────────────────────────────────────────────
    try:
        results['autosell'] = cmd_autosell(client, rarity_threshold=3)
    except Exception as e:
        results['autosell'] = {'sold': 0, 'exchanged': 0, 'error': str(e)}

    # ── 7. Missions post-farm ─────────────────────────────────────────────────
    try:
        results['missions_post'] = client.accept_missions()
    except Exception as e:
        results['missions_post'] = {'error': str(e)}

    # ── Résumé ────────────────────────────────────────────────────────────────
    total_cleared = sum(
        r.get('cleared', 0) for k, r in results.items()
        if isinstance(r, dict) and k in ('quests','events','zbattles','dbstories',
                                          'keyevents','superzbattles','clash')
    )
    results['total_stages_cleared'] = total_cleared

    # Pierres gagnées
    try:
        info_after = client.get_info()
        if info_after and stones_before is not None:
            u2 = info_after.get('user', {})
            stones_after  = u2.get('stone', 0)
            results['stones_gained'] = stones_after - stones_before
            results['stones_total']  = stones_after
    except Exception:
        pass

    return results


def cmd_quests(client: DokkanClient) -> Dict:
    _ensure_ready(client)
    stage_ids = []
    for diff in (2, 1, 0, None):
        stage_ids = client.get_story_stages(only_uncleared=True, difficulty=diff)
        if stage_ids:
            break
    log.info('[cmd_quests] stage_ids trouvés: %d', len(stage_ids))
    if not stage_ids:
        return {"cleared": 0, "message": "No uncleared story stages found"}
    return _clear_stage_ids(client, stage_ids)


def cmd_events(client: DokkanClient) -> Dict:
    _ensure_ready(client)
    stage_ids = client.get_event_stage_ids(only_unvisited=False)
    log.info('[cmd_events] stage_ids trouvés: %d', len(stage_ids))
    if not stage_ids:
        return {"cleared": 0, "message": "No event stages found"}
    return _clear_stage_ids(client, stage_ids)


def cmd_zbattles(client: DokkanClient, max_stage: int = 31) -> Dict:
    _ensure_ready(client)
    stage_ids = client.get_zbattle_stage_ids(only_uncleared=True)
    if max_stage:
        stage_ids = [sid for sid in stage_ids if ((sid // 10) % 1000) <= max_stage]
    log.info('[cmd_zbattles] stage_ids trouvés: %d', len(stage_ids))
    if not stage_ids:
        return {"cleared": 0, "message": "No uncleared Z-Battle stages found"}
    return _clear_stage_ids(client, stage_ids)


def cmd_dbstories(client: DokkanClient) -> Dict:
    _ensure_ready(client)
    stage_ids = client.get_dbstory_stage_ids(only_uncleared=True)
    log.info('[cmd_dbstories] stage_ids trouvés: %d', len(stage_ids))
    if not stage_ids:
        return {"cleared": 0, "message": "No uncleared DB Story stages found"}
    return _clear_stage_ids(client, stage_ids)



def cmd_stage(client: DokkanClient, stage_id: int,
              deck_id: int = 1, use_key: bool = False) -> Dict:
    r = client.quick_finish_stage(stage_id, deck_id, use_key)
    return {"stage_id": stage_id, "result": r}


def cmd_keyevents(client: DokkanClient) -> Dict:
    # CORRIGÉ : utilise /eventkagi endpoint, events avec open_status=available
    stage_ids = client.get_kagi_event_ids()
    if not stage_ids:
        return {"cleared": 0, "message": "No available key event stages found"}
    return _clear_stage_ids(client, stage_ids, use_key=True)


def cmd_keyzbattles(client: DokkanClient, max_stage: int = 30) -> Dict:
    # CORRIGÉ : utilise /eventkagi z_battle_stages avec open_status=available
    zb_ids = client.get_kagi_zbattle_ids()
    cleared = 0
    errors = []
    for zb_id in zb_ids:
        r = client.quick_finish_zbattle(zb_id)
        if r.get('error'):
            errors.append({'zb_id': zb_id, 'error': r['error']})
        else:
            cleared += 1
        import time, random
        time.sleep(random.uniform(0.5, 1.0))
    return {"cleared": cleared, "errors": errors}


def cmd_area(client: DokkanClient, area_id: int) -> Dict:
    stages = [s for s in client.get_stages(area_id=area_id) if not s.get("cleared")]
    return _clear_stages(client, stages)


def cmd_clash(client: DokkanClient) -> Dict:
    # complete_clash() utilise /rm_battles (bon endpoint)
    # get_stages() ne retourne pas type='clash' donc toujours 0
    return client.complete_clash()


def cmd_sbr(client: DokkanClient) -> Dict:
    stages = [s for s in client.get_stages()
              if s.get("type") in ("sbr", "esbr") and not s.get("cleared")]
    return _clear_stages(client, stages)


def cmd_zstars(client: DokkanClient) -> Dict:
    stages = [s for s in client.get_stages() if s.get("type") == "zstars"]
    cleared = 0
    for stage in stages:
        for _ in range(999):
            r = client.quick_finish_stage(stage["id"])
            if r.get("error"):
                break
            cleared += 1
            time.sleep(random.uniform(0.3, 0.7))
    return {"cleared": cleared}


def cmd_medals(client: DokkanClient, medal_id: int, count: int = 1) -> Dict:
    stages = client.get_stages()
    target = next((s for s in stages if medal_id in s.get("medal_drops", [])), None)
    if not target:
        return {"error": f"No stage found for medal {medal_id}. Use !stage <id> manually."}
    results = client.farm_stage_n_times(target["id"], count)
    return {"medal_id": medal_id, "runs": len(results)}


def cmd_missions(client: DokkanClient) -> Dict:
    return client.accept_missions()


def cmd_zeni(client: DokkanClient) -> Dict:
    stages = [s for s in client.get_stages() if s.get("type") == "zbattle"]
    total = 0
    for stage in stages[:5]:
        results = client.farm_stage_n_times(stage["id"], 10)
        total += len(results)
    return {"runs": total}


def cmd_f2p(client: DokkanClient) -> Dict:
    stages = [s for s in client.get_stages() if s.get("f2p_card_drop")]
    return _clear_stages(client, stages)


def cmd_blue_gems(client: DokkanClient) -> Dict:
    stages = [s for s in client.get_stages() if s.get("gem_drop") == "blue"]
    return _clear_stages(client, stages)


def cmd_green_gems(client: DokkanClient) -> Dict:
    stages = [s for s in client.get_stages() if s.get("gem_drop") == "green"]
    return _clear_stages(client, stages)


def cmd_wishes(client: DokkanClient) -> Dict:
    return client.collect_and_wish()


def cmd_eza(client: DokkanClient, stage_id: int) -> Dict:
    return cmd_stage(client, stage_id)


def cmd_supereza(client: DokkanClient) -> Dict:
    stages = [s for s in client.get_stages() if s.get("type") == "supereza"]
    return _clear_stages(client, stages)


def cmd_rank(client: DokkanClient, target_rank: int) -> Dict:
    info = client.get_info()
    current = (info.get("user", {}) if info else {}).get("rank", 0)
    runs = 0
    stages = client.get_stages()
    while current < target_rank and stages:
        client.quick_finish_stage(random.choice(stages[:10])["id"])
        runs += 1
        info = client.get_info()
        current = (info.get("user", {}) if info else {}).get("rank", current)
        time.sleep(random.uniform(0.5, 1.0))
    return {"target_rank": target_rank, "current_rank": current, "runs": runs}


def cmd_farm_link(client: DokkanClient) -> Dict:
    stages = [s for s in client.get_stages() if s.get("link_skill_stage")]
    return _clear_stages(client, stages)


# ═══════════════════════════════════════════════════════════ TEAM / CARDS

def cmd_awaken(client: DokkanClient, card_id: int) -> Dict:
    cards = client.get_user_cards()
    uc = next((c for c in cards if c["card_id"] == card_id), None)
    if not uc:
        return {"error": f"Card {card_id} not found in your box"}
    return client.full_awaken_sequence(uc["id"])


def cmd_awakenall(client: DokkanClient) -> Dict:
    cards = client.get_cards_for_awaken()
    if not cards:
        return {"processed": 0, "message": "No awakeable cards found"}
    results = []
    for uc in cards:
        r = client.full_awaken_sequence(uc["id"])
        results.append({"card_id": uc.get("card_id"), "uid": uc["id"], "result": r})
        time.sleep(random.uniform(0.3, 0.8))
    return {"processed": len(results), "results": results}


def cmd_sell(client: DokkanClient, rarity_threshold: int = 2) -> Dict:
    cards = client.get_user_cards()
    to_sell = [c["id"] for c in cards if c.get("rarity", 0) <= rarity_threshold]
    if not to_sell:
        return {"sold": 0, "message": "Nothing to sell below that rarity"}
    r = client.sell_cards(to_sell)
    return {"sold": len(to_sell), "result": r}


def cmd_team(client: DokkanClient, card_ids: List[int]) -> Dict:
    teams = client.get_teams()
    team_num = teams.get('selected_team_num', 1)
    cards_data = [{'user_card_id': cid, 'position': i + 1} for i, cid in enumerate(card_ids)]
    import ingame
    return client._call(ingame.setTeam, team_num, cards_data) or {}


def cmd_deck(client: DokkanClient, deck_id: int) -> Dict:
    import ingame
    teams = client.get_teams()
    cards_data = []
    for t in teams.get('user_card_teams', []):
        if t.get('team_num') == deck_id:
            cards_data = t.get('user_cards', [])
            break
    return client._call(ingame.setTeam, deck_id, cards_data) or {}


def cmd_copyteam(client: DokkanClient, stage_id: int) -> Dict:
    """Récupère le briefing du stage et retourne l'équipe recommandée."""
    return client.get_quest_briefing(stage_id)


# ═══════════════════════════════════════════════════════════ STAMINA / SHOP

def cmd_gift(client: DokkanClient) -> Dict:
    return client.accept_gifts()


def cmd_refill(client: DokkanClient) -> Dict:
    return client.refill_stamina(use_stone=True)


def cmd_meat(client: DokkanClient) -> Dict:
    return client.refill_stamina(use_stone=False)


def cmd_capacity(client: DokkanClient) -> Dict:
    return client.increase_card_capacity()


# ═══════════════════════════════════════════════════════════ SUMMON

def cmd_summon(client: DokkanClient, gacha_id: int) -> Dict:
    return client.summon(gacha_id, 10)


def cmd_summon_card(client: DokkanClient, gacha_id: int,
                    card_id: int, max_pulls: int = 500) -> Dict:
    return client.summon_until_card(gacha_id, card_id, max_pulls)


def cmd_superzbattles(client: DokkanClient, use_kagi: bool = True) -> Dict:
    '''Farm les Super Z-Battle stages (kagi) via /events/eventkagi_events.
    Source : command_definitions → _farm_super_zbattle_stage / kagi_super_z_battle_stages'''
    zb_ids = client.get_kagi_zbattle_ids_from_dedicated()
    if not zb_ids:
        # Fallback sur l'ancienne méthode
        zb_ids = client.get_kagi_zbattle_ids()
    if not zb_ids:
        return {'cleared': 0, 'message': 'No Super Z-Battle stages available (kagi required)'}
    cleared = 0
    errors  = []
    for zb_id in zb_ids:
        r = client.quick_finish_zbattle(zb_id)
        if r.get('error'):
            errors.append({'zb_id': zb_id, 'error': r['error']})
        else:
            cleared += 1
        time.sleep(random.uniform(0.5, 1.0))
    return {'cleared': cleared, 'errors': errors}


def cmd_clash(client: DokkanClient) -> Dict:
    '''Flow complet du RM Battle / Ultimate Clash — joue tous les stages disponibles.
    Source : command_definitions → complete_clash / "Run the latest Ultimate Clash."'''
    return client.complete_clash()


def cmd_baba(client: DokkanClient) -> Dict:
    '''Affiche les articles de la boutique Baba.
    Source : dokkan_client → get_baba_shop_items'''
    return client.get_baba_shop() or {}


def cmd_buy_baba(client: DokkanClient, item_id: int) -> Dict:
    '''Achète un article dans la boutique Baba.
    Source : dokkan_client → buy_baba_shop_item'''
    return client.buy_baba_item(item_id)


def cmd_autosell(client: DokkanClient, rarity_threshold: int = 3) -> Dict:
    '''Vend les cartes inutiles + échange SR/R à la boutique Baba.
    Source : command_definitions → "Automatically sell useless cards and trade SR/R cards to baba shop."
    rarity_threshold : 1=N, 2=R, 3=SR (défaut)'''
    result = {'sold': 0, 'exchanged': 0}
    # Vente des N/R
    cards    = client.get_user_cards()
    to_sell  = [c['id'] for c in cards if c.get('rarity', 0) <= 2]
    if to_sell:
        client.sell_cards(to_sell)
        result['sold'] = len(to_sell)
        time.sleep(0.5)
    # Échange des SR à Baba
    cards    = client.get_user_cards(force_refresh=True)
    to_baba  = [c['id'] for c in cards if c.get('rarity', 0) == rarity_threshold and not c.get('favorite')]
    if to_baba:
        baba_r   = client.autosell_to_baba(rarity_threshold)
        result['exchanged'] = baba_r.get('exchanged', 0)
    return result


def cmd_wishes(client: DokkanClient) -> Dict:
    '''Flow complet Dragon Balls : vérifie les sets, exauce les vœux disponibles.
    Source : command_definitions → make_dragonball_wish / get_dragonball_wishes'''
    return client.collect_and_wish_smart()


def cmd_giru(client: DokkanClient) -> Dict:
    '''Récupère la progression des missions Giru Nav (growth + unacquired).
    Source : endpoints.pyd → GIRU_NAV_GROWTH / GIRU_NAV_UNACQUIRED'''
    growth      = client.get_giru_growth()
    unacquired  = client.get_giru_unacquired()
    return {'growth': growth, 'unacquired': unacquired}


def cmd_farmcards(client: DokkanClient, awakening_item_id: int = 0) -> Dict:
    '''Trouve les stages qui droppent une médaille spécifique via item_reverse_resolutions.
    Source : dokkan_client → get_item_reverse_resolutions / command_definitions → find_farmable_stage_for_card'''
    if awakening_item_id:
        stages = client.find_farmable_stages_for_medal(awakening_item_id)
        return {'medal_id': awakening_item_id, 'farmable_stages': stages, 'count': len(stages)}
    # Sans ID : retourne toute la table
    data = client.get_item_reverse_resolutions()
    return data or {'error': 'item_reverse_resolutions failed'}


def cmd_database(client: DokkanClient) -> Dict:
    '''Vérifie l'état de la base de données in-game.
    Source : dokkan_client → get_database_status / update_database'''
    return client.get_database_status()


def cmd_ping(client: DokkanClient) -> Dict:
    '''Ping le serveur Dokkan pour vérifier la connectivité.
    Source : endpoints.pyd → PING'''
    return client.ping_server()


def cmd_cooperation(client: DokkanClient) -> Dict:
    '''GET /cooperation_campaigns — campagnes de coopération actives.
    Source : endpoints.pyd → COOPERATION_CAMPAIGNS'''
    return client.get_cooperation_campaigns()


def cmd_joint(client: DokkanClient) -> Dict:
    '''GET /joint_campaigns — campagnes conjointes actives.
    Source : endpoints.pyd → JOINT_CAMPAIGNS'''
    return client.get_joint_campaigns()


def cmd_shopbaba(client: DokkanClient) -> Dict:
    '''Affiche les articles de la boutique Baba.
    Source : endpoints.pyd → SHOPS_BABA_ITEMS'''
    return client.get_baba_shop()


# ═══════════════════════════════════════════════════════════ HELPER

def _clear_stages(client: DokkanClient, stages: list,
                  use_key: bool = False) -> Dict:
    # Ancien helper — conservé pour compatibilité
    cleared = []
    for stage in stages:
        sid = stage.get('sugoroku_map_id') or stage.get('id')
        if not sid:
            continue
        r = client.quick_finish_stage(sid, use_key=use_key)
        cleared.append({"stage_id": sid, "result": r})
        time.sleep(random.uniform(0.5, 1.2))
    return {"cleared": len(cleared)}


def _clear_stage_ids(client: DokkanClient, stage_ids: list,
                     use_key: bool = False) -> Dict:
    # NOUVEAU helper — prend directement une liste de sugoroku_map_ids
    cleared = 0
    errors  = []
    for sid in stage_ids:
        r = client.quick_finish_stage(sid, use_key=use_key)
        if r.get('error'):
            errors.append({'stage_id': sid, 'error': r['error']})
        else:
            cleared += 1
        time.sleep(random.uniform(0.5, 1.2))
    return {"cleared": cleared, "errors": errors if errors else []}


# ═══════════════════════════════════════════════════════════ ÉVEILS AVANCÉS

def cmd_awaken_uid(client: DokkanClient, user_card_id: int) -> Dict:
    """Éveille une carte directement par son UID (user card ID unique)."""
    return client.full_awaken_sequence(user_card_id)


def cmd_train(client: DokkanClient, user_card_id: int, feed_ids: List[int]) -> Dict:
    """Monte le SA d'une carte en lui sacrifiant d'autres cartes."""
    return client.train_card(user_card_id, feed_ids)


def cmd_exchange(client: DokkanClient, card_ids: List[int]) -> Dict:
    """Échange des cartes (trade-in LR, etc.)."""
    return client.exchange_cards(card_ids)


# ═══════════════════════════════════════════════════════════ BOUTIQUES

def cmd_shop_treasure(client: DokkanClient) -> Dict:
    return client.get_shop_treasure()


def cmd_shop_zeni(client: DokkanClient) -> Dict:
    return client.get_shop_zeni()


def cmd_shop_exchange(client: DokkanClient) -> Dict:
    return client.get_shop_exchange()


def cmd_buy(client: DokkanClient, shop: str, item_id: int) -> Dict:
    shop = shop.lower()
    if shop == 'treasure':
        return client.buy_treasure_item(item_id)
    elif shop == 'zeni':
        return client.buy_zeni_item(item_id)
    elif shop in ('exchange', 'ep'):
        return client.buy_exchange_item(item_id)
    return {'error': f'Boutique inconnue : {shop}. Options : treasure, zeni, exchange'}


# ═══════════════════════════════════════════════════════════ LOGIN BONUSES

def cmd_loginbonus(client: DokkanClient) -> Dict:
    return client.accept_login_bonuses()


# ═══════════════════════════════════════════════════════════ COMPENSATIONS

def cmd_apologies(client: DokkanClient) -> Dict:
    return client.accept_apologies()


# ═══════════════════════════════════════════════════════════ RM BATTLES

def cmd_rmbattles(client: DokkanClient) -> Dict:
    return client.get_rm_battles()


# ═══════════════════════════════════════════════════════════ RESSOURCES BULK

def cmd_resources(client: DokkanClient) -> Dict:
    """Charge toutes les données de session en une requête (bulk login resource)."""
    data = client.get_resources_login()
    if not data:
        return {'error': 'Impossible de contacter les serveurs Dokkan'}
    return {
        'cards':         len(data.get('cards', [])),
        'missions':      len(data.get('missions', [])),
        'gifts':         len(data.get('gifts', [])),
        'gashas':        len(data.get('gashas', [])),
        'user_areas':    len(data.get('user_areas', [])),
        'login_bonuses': len(data.get('login_bonuses', [])),
        'db_stories':    len(data.get('db_stories', [])),
    }


def cmd_awakenall_auto(client: DokkanClient) -> Dict:
    """Éveille toutes les cartes éveillables automatiquement."""
    return cmd_awakenall(client)


def cmd_trainall(client: DokkanClient) -> Dict:
    """
    Monte le SA de toutes les cartes entraînables automatiquement.
    Utilise les doublons (même card_id) comme nourriture.
    """
    cards = client.get_user_cards()
    if not cards:
        return {'trained': 0, 'message': 'Aucune carte'}

    # Groupe par card_id
    from collections import defaultdict
    groups = defaultdict(list)
    for c in cards:
        groups[c['card_id']].append(c['id'])

    trained = 0
    errors  = []
    for card_id, uids in groups.items():
        if len(uids) < 2:
            continue  # pas de doublon à sacrifier
        base     = uids[0]
        feeders  = uids[1:]
        r = client.train_card(base, feeders)
        if r.get('error') or r.get('_http_status', 200) >= 400:
            errors.append({'card_id': card_id, 'error': r})
        else:
            trained += 1
        time.sleep(random.uniform(0.3, 0.6))
    return {'trained': trained, 'errors': errors}


def cmd_sellall(client: DokkanClient) -> Dict:
    """Vend TOUTES les cartes N et R automatiquement."""
    return cmd_sell(client, rarity_threshold=2)


def cmd_exchangeall(client: DokkanClient) -> Dict:
    """Échange toutes les cartes éligibles (SR+) vers la boutique Baba automatiquement."""
    return cmd_autosell(client, rarity_threshold=3)


def cmd_rankall(client: DokkanClient, target_rank: int = 500) -> Dict:
    """Farm de rang automatique jusqu'au rang cible (défaut 500)."""
    return cmd_rank(client, target_rank)


def cmd_summonall_card(client: DokkanClient, card_id: int, max_pulls: int = 9999) -> Dict:
    """
    Invoque en boucle sur TOUTES les bannières actives jusqu'à obtenir card_id.
    S'arrête dès que la carte est trouvée sur n'importe quelle bannière.
    """
    banners = client.get_banners()
    if not banners:
        return {'error': 'Aucune bannière disponible', 'found': False}

    total_pulls  = 0
    stones_used  = 0
    found_banner = None

    for banner in banners:
        gacha_id = banner.get('id')
        name     = banner.get('name', f'Bannière {gacha_id}')
        if not gacha_id:
            continue

        courses = banner.get('courses', [])
        course  = next((c['id'] for c in courses if c.get('count', 0) >= 10), 2)

        pulls_this_banner = 0
        while pulls_this_banner < max_pulls:
            r = client.summon(gacha_id, course)
            if r.get('error') or r.get('_http_status', 200) >= 400:
                break
            items = r.get('gasha_items', [])
            total_pulls  += 10
            pulls_this_banner += 10
            stones_used  += 50

            # Vérifie si la carte est dans les résultats
            if any(i.get('item_id') == card_id or i.get('card_id') == card_id for i in items):
                found_banner = name
                return {
                    'found':        True,
                    'card_id':      card_id,
                    'banner':       found_banner,
                    'total_pulls':  total_pulls,
                    'stones_used':  stones_used,
                }
            time.sleep(random.uniform(0.5, 1.0))

    return {
        'found':       False,
        'card_id':     card_id,
        'total_pulls': total_pulls,
        'stones_used': stones_used,
        'message':     f'Carte {card_id} non trouvée après {total_pulls} invocations',
    }


def cmd_sbr_auto(client: DokkanClient) -> Dict:
    return cmd_sbr(client)

def cmd_zstars_auto(client: DokkanClient) -> Dict:
    return cmd_zstars(client)

def cmd_keyzbattles_auto(client: DokkanClient) -> Dict:
    return cmd_keyzbattles(client)

def cmd_rmbattles_auto(client: DokkanClient) -> Dict:
    return cmd_clash(client)

def cmd_zeni_auto(client: DokkanClient) -> Dict:
    return cmd_zeni(client)

def cmd_f2p_auto(client: DokkanClient) -> Dict:
    return cmd_f2p(client)

def cmd_wishes_auto(client: DokkanClient) -> Dict:
    return cmd_wishes(client)

def cmd_supereza_auto(client: DokkanClient) -> Dict:
    return cmd_supereza(client)

def cmd_bluegems_auto(client: DokkanClient) -> Dict:
    return cmd_blue_gems(client)

def cmd_greengems_auto(client: DokkanClient) -> Dict:
    return cmd_green_gems(client)

def cmd_farmlink_auto(client: DokkanClient) -> Dict:
    return cmd_farm_link(client)

def cmd_giru_auto(client: DokkanClient) -> Dict:
    return cmd_giru(client)

def cmd_cooperation_auto(client: DokkanClient) -> Dict:
    return cmd_cooperation(client)

def cmd_joint_auto(client: DokkanClient) -> Dict:
    return cmd_joint(client)

def cmd_farmcards_auto(client: DokkanClient) -> Dict:
    """Farm toutes les médailles d'éveil (toutes IDs) via item_reverse_resolutions."""
    data = client.get_item_reverse_resolutions('awakening_items')
    if not data or 'error' in data:
        return {'cleared': 0, 'error': 'item_reverse_resolutions inaccessible'}
    resolutions = data.get('item_reverse_resolutions', [])
    if isinstance(resolutions, dict):
        resolutions = list(resolutions.values())
    seen, stage_ids = set(), []
    for r in resolutions:
        sid = r.get('sugoroku_map_id') or r.get('stage_id')
        if sid and sid not in seen:
            seen.add(sid)
            stage_ids.append(sid)
    if not stage_ids:
        return {'cleared': 0, 'message': 'Aucun stage de médaille trouvé'}
    return _clear_stage_ids(client, stage_ids)

def cmd_area_auto(client: DokkanClient) -> Dict:
    """Farm toutes les areas non complétées sans area_id."""
    stages = client.get_stages()
    todo   = [s for s in stages if not s.get('cleared') and s.get('sugoroku_map_id')]
    if not todo:
        return {'cleared': 0, 'message': 'Toutes les areas complétées'}
    return _clear_stage_ids(client, [s['sugoroku_map_id'] for s in todo])

def cmd_rank_auto(client: DokkanClient, target_rank: int = 500) -> Dict:
    return cmd_rank(client, target_rank)

def cmd_summonall_card(client: DokkanClient, card_id: int, max_pulls: int = 9999) -> Dict:
    """Invoque sur toutes les bannières jusqu'à obtenir card_id."""
    banners = client.get_banners()
    if not banners:
        return {'error': 'Aucune bannière disponible', 'found': False}
    total_pulls = 0
    stones_used = 0
    for banner in banners:
        gacha_id = banner.get('id')
        name     = banner.get('name', f'Bannière {gacha_id}')
        if not gacha_id:
            continue
        courses = banner.get('courses', [])
        course  = next((c['id'] for c in courses if c.get('count', 0) >= 10), 2)
        while total_pulls < max_pulls:
            r = client.summon(gacha_id, course)
            if r.get('error') or r.get('_http_status', 200) >= 400:
                break
            items        = r.get('gasha_items', [])
            total_pulls += 10
            stones_used += 50
            if any(i.get('item_id') == card_id or i.get('card_id') == card_id for i in items):
                return {'found': True, 'card_id': card_id, 'banner': name,
                        'total_pulls': total_pulls, 'stones_used': stones_used}
            time.sleep(random.uniform(0.5, 1.0))
    return {'found': False, 'card_id': card_id, 'total_pulls': total_pulls,
            'stones_used': stones_used, 'message': f'Carte {card_id} introuvable après {total_pulls} pulls'}


def cmd_stageall(client: DokkanClient) -> Dict:
    """
    Farm automatique : trouve les stages non complétés, les classe par
    ratio récompenses/stamina et les clear tous sans avoir à donner d'ID.
    """
    stages = client.get_stages()
    if not stages:
        return {'cleared': 0, 'message': 'Aucun stage trouvé'}
    # Priorité : stages non visités > non complétés > visitables encore
    todo = [s for s in stages if not s.get('cleared') and not s.get('visited_count', 0)]
    if not todo:
        todo = [s for s in stages if not s.get('cleared')]
    if not todo:
        return {'cleared': 0, 'message': 'Tous les stages sont déjà complétés'}
    return _clear_stage_ids(client, [s['sugoroku_map_id'] for s in todo if s.get('sugoroku_map_id')])


def cmd_ezaall(client: DokkanClient) -> Dict:
    """
    Fait tous les EZA / Z-Battles disponibles automatiquement sans ID.
    Récupère la liste depuis l'API et les clear tous.
    """
    # Via les areas Z-Battle (900-999) — tous niveaux
    ids = client.get_zbattle_stage_ids(only_uncleared=True)
    if not ids:
        return {'cleared': 0, 'message': 'Aucun EZA/Z-Battle disponible'}
    cleared = 0
    errors  = []
    for zb_id in ids:
        r = client.quick_finish_zbattle(zb_id)
        if r.get('error'):
            errors.append({'id': zb_id, 'error': r['error']})
        else:
            cleared += 1
        time.sleep(random.uniform(0.5, 1.0))
    return {'cleared': cleared, 'total': len(ids), 'errors': errors}


def cmd_medalsall(client: DokkanClient) -> Dict:
    """
    Farm toutes les médailles d'éveil disponibles automatiquement.
    Utilise item_reverse_resolutions pour trouver les meilleurs stages par médaille,
    puis les clear.
    """
    data = client.get_item_reverse_resolutions('awakening_items')
    if not data or 'error' in data:
        return {'error': 'Impossible de récupérer les médailles disponibles'}

    resolutions = data.get('item_reverse_resolutions', [])
    if isinstance(resolutions, dict):
        resolutions = [resolutions]

    # Déduplique les stage_ids
    seen     = set()
    stage_ids = []
    for r in resolutions:
        sid = r.get('sugoroku_map_id') or r.get('stage_id')
        if sid and sid not in seen:
            seen.add(sid)
            stage_ids.append(sid)

    if not stage_ids:
        return {'cleared': 0, 'message': 'Aucun stage de médaille trouvé'}

    result = _clear_stage_ids(client, stage_ids)
    result['medals_targeted'] = len(resolutions)
    result['stages_unique']   = len(stage_ids)
    return result


def cmd_summonall(client: DokkanClient) -> Dict:
    """
    Fait 1 multi (10 invocations) sur TOUTES les bannières actives automatiquement.
    Récupère les gashas depuis l'API et invoque sur chacun.
    """
    banners = client.get_banners()
    if not banners:
        return {'error': 'Aucune bannière disponible'}

    results   = []
    total_got = 0
    stones_used = 0

    for banner in banners:
        gacha_id = banner.get('id')
        name     = banner.get('name', f'Bannière {gacha_id}')
        if not gacha_id:
            continue
        # Trouve le course multi (course 2 = 10x en général)
        courses  = banner.get('courses', [])
        course   = next((c['id'] for c in courses if c.get('count', 0) >= 10), 2)
        r = client.summon(gacha_id, course)
        items = r.get('gasha_items', [])
        total_got += len(items)
        stones_used += 50  # approximatif
        results.append({
            'banner':    name,
            'gacha_id':  gacha_id,
            'obtained':  len(items),
            'ur_cards':  [i for i in items if i.get('rarity', 0) >= 5],
        })
        time.sleep(random.uniform(0.8, 1.5))

    ur_total = sum(len(r['ur_cards']) for r in results)
    return {
        'banners_done':  len(results),
        'cards_obtained': total_got,
        'ur_obtained':   ur_total,
        'stones_used':   stones_used,
        'details':       results,
    }


def cmd_areaall(client: DokkanClient) -> Dict:
    """
    Farm toutes les areas non complétées automatiquement (sans donner d'area_id).
    """
    stages = client.get_stages()
    todo   = [s for s in stages if not s.get('cleared')]
    if not todo:
        return {'cleared': 0, 'message': 'Toutes les areas sont déjà complétées'}
    ids = [s['sugoroku_map_id'] for s in todo if s.get('sugoroku_map_id')]
    return _clear_stage_ids(client, ids)


def cmd_superezaall(client: DokkanClient) -> Dict:
    """
    Fait tous les Super EZA disponibles sans ID.
    """
    stages = [s for s in client.get_stages() if s.get('type') in ('supereza', 'eza')]
    if not stages:
        return {'cleared': 0, 'message': 'Aucun Super EZA disponible'}
    ids = [s['sugoroku_map_id'] for s in stages if s.get('sugoroku_map_id')]
    return _clear_stage_ids(client, ids)


def cmd_buyall_treasure(client: DokkanClient) -> Dict:
    """Achète tous les articles disponibles dans la boutique Trésor."""
    shop = client.get_shop_treasure()
    items = shop.get('treasure_shop_items', shop.get('items', []))
    if not items:
        return {'bought': 0, 'message': 'Boutique Trésor vide'}
    bought = 0
    errors = []
    for item in items:
        iid   = item.get('id')
        limit = item.get('purchase_limit', 1)
        owned = item.get('purchased_count', 0)
        if not iid or owned >= limit:
            continue
        for _ in range(limit - owned):
            r = client.buy_treasure_item(iid)
            if r.get('error') or r.get('_http_status', 200) >= 400:
                errors.append({'id': iid, 'error': r})
                break
            bought += 1
            time.sleep(random.uniform(0.3, 0.6))
    return {'bought': bought, 'errors': errors}


def cmd_buyall_baba(client: DokkanClient) -> Dict:
    """Achète tous les articles disponibles dans la boutique Baba."""
    shop  = client.get_baba_shop()
    items = shop.get('baba_shop_items', shop.get('items', []))
    if not items:
        return {'bought': 0, 'message': 'Boutique Baba vide'}
    bought = 0
    errors = []
    for item in items:
        iid   = item.get('id')
        limit = item.get('purchase_limit', 1)
        owned = item.get('purchased_count', 0)
        if not iid or owned >= limit:
            continue
        r = client.buy_baba_item(iid)
        if r.get('error') or r.get('_http_status', 200) >= 400:
            errors.append({'id': iid, 'error': r})
        else:
            bought += 1
        time.sleep(random.uniform(0.3, 0.5))
    return {'bought': bought, 'errors': errors}


# ═══════════════════════════════════════════════════════════ REGISTRY

COMMAND_REGISTRY = {
    # ── Farm principal ────────────────────────────────────────────────────────
    "dailyfarm":        lambda c, **k: cmd_dailyfarm(c),
    "omegafarm":        lambda c, **k: cmd_omegafarm(c),
    # ── AUTO : toutes les commandes farm sans ID ───────────────────────────────
    "stageall":         lambda c, **k: cmd_stageall(c),
    "areaall":          lambda c, **k: cmd_area_auto(c),
    "ezaall":           lambda c, **k: cmd_ezaall(c),
    "superezaall":      lambda c, **k: cmd_supereza_auto(c),
    "medalsall":        lambda c, **k: cmd_farmcards_auto(c),
    "farmcardsall":     lambda c, **k: cmd_farmcards_auto(c),
    "sbr":              lambda c, **k: cmd_sbr_auto(c),
    "zstars":           lambda c, **k: cmd_zstars_auto(c),
    "keyzbattlesall":   lambda c, **k: cmd_keyzbattles_auto(c),
    "rmbattlesall":     lambda c, **k: cmd_rmbattles_auto(c),
    "zeniall":          lambda c, **k: cmd_zeni_auto(c),
    "f2pall":           lambda c, **k: cmd_f2p_auto(c),
    "wishesall":        lambda c, **k: cmd_wishes_auto(c),
    "bluegemsall":      lambda c, **k: cmd_bluegems_auto(c),
    "greengemsall":     lambda c, **k: cmd_greengems_auto(c),
    "farmlinkall":      lambda c, **k: cmd_farmlink_auto(c),
    "giruall":          lambda c, **k: cmd_giru_auto(c),
    "cooperationall":   lambda c, **k: cmd_cooperation_auto(c),
    "jointall":         lambda c, **k: cmd_joint_auto(c),
    "rankall":          lambda c, **k: cmd_rank_auto(c, k.get('target_rank', 500)),
    "summonall":        lambda c, **k: cmd_summonall_card(c, k['card_id'], k.get('max_pulls', 9999)),
    "awakenall":        lambda c, **k: cmd_awakenall(c),
    "trainall":         lambda c, **k: cmd_trainall(c),
    "sellall":          lambda c, **k: cmd_sellall(c),
    "exchangeall":      lambda c, **k: cmd_exchangeall(c),
    "buyall treasure":  lambda c, **k: cmd_buyall_treasure(c),
    "buyall baba":      lambda c, **k: cmd_buyall_baba(c),
    "quests":      lambda c, **k: cmd_quests(c),
    "events":      lambda c, **k: cmd_events(c),
    "zbattles":    lambda c, **k: cmd_zbattles(c, k.get("max_stage", 31)),
    "dbstories":   lambda c, **k: cmd_dbstories(c),
    "clash":       lambda c, **k: cmd_clash(c),
    "stage":       lambda c, **k: cmd_stage(c, k["stage_id"], k.get("deck_id", 1), k.get("use_key", False)),
    "keyevents":   lambda c, **k: cmd_keyevents(c),
    "keyzbattles": lambda c, **k: cmd_keyzbattles(c, k.get("max_stage", 30)),
    "area":        lambda c, **k: cmd_area(c, k["area_id"]),
    "farm link":   lambda c, **k: cmd_farm_link(c),
    "blue gems":   lambda c, **k: cmd_blue_gems(c),
    "green gems":  lambda c, **k: cmd_green_gems(c),
    "rank":        lambda c, **k: cmd_rank(c, k["target_rank"]),
    "sbr":         lambda c, **k: cmd_sbr(c),
    "zstars":      lambda c, **k: cmd_zstars(c),
    "medals":      lambda c, **k: cmd_medals(c, k["medal_id"], k.get("count", 1)),
    "missions":    lambda c, **k: cmd_missions(c),
    "zeni":        lambda c, **k: cmd_zeni(c),
    "f2p":         lambda c, **k: cmd_f2p(c),
    "wishes":      lambda c, **k: cmd_wishes(c),
    "eza":         lambda c, **k: cmd_eza(c, k["stage_id"]),
    "supereza":    lambda c, **k: cmd_supereza(c),
    "awaken":      lambda c, **k: cmd_awaken(c, k["card_id"]),
    "awakenall":   lambda c, **k: cmd_awakenall(c),
    "awaken uid":  lambda c, **k: cmd_awaken_uid(c, k["user_card_id"]),
    "train":       lambda c, **k: cmd_train(c, k["user_card_id"], k.get("feed_ids", [])),
    "exchange":    lambda c, **k: cmd_exchange(c, k["card_ids"]),
    "team":        lambda c, **k: cmd_team(c, k["card_ids"]),
    "deck":        lambda c, **k: cmd_deck(c, k["deck_id"]),
    "sell":        lambda c, **k: cmd_sell(c, k.get("rarity_threshold", 2)),
    "copyteam":    lambda c, **k: cmd_copyteam(c, k["stage_id"]),
    "gift":        lambda c, **k: cmd_gift(c),
    "refill":      lambda c, **k: cmd_refill(c),
    "capacity":    lambda c, **k: cmd_capacity(c),
    "meat":        lambda c, **k: cmd_meat(c),
    "summon":      lambda c, **k: cmd_summon(c, k["gacha_id"]),
    "summon card": lambda c, **k: cmd_summon_card(c, k["gacha_id"], k["card_id"], k.get("max_pulls", 500)),
    "info":        lambda c, **k: cmd_info(c),
    # ── Nouveaux (extraits des .pyd) ──
    "loginbonus":       lambda c, **k: cmd_loginbonus(c),
    "apologies":        lambda c, **k: cmd_apologies(c),
    "shop treasure":    lambda c, **k: cmd_shop_treasure(c),
    "shop zeni":        lambda c, **k: cmd_shop_zeni(c),
    "shop exchange":    lambda c, **k: cmd_shop_exchange(c),
    "buy":              lambda c, **k: cmd_buy(c, k["shop"], k["item_id"]),
    "rmbattles":        lambda c, **k: cmd_rmbattles(c),
    "resources":        lambda c, **k: cmd_resources(c),
    # ── Endpoints .pyd — nouveaux ──────────────────────────────────────────
    "clash":            lambda c, **k: cmd_clash(c),
    "superzbattles":    lambda c, **k: cmd_superzbattles(c),
    "autosell":         lambda c, **k: cmd_autosell(c, k.get("rarity_threshold", 3)),
    "wishes":           lambda c, **k: cmd_wishes(c),
    "giru":             lambda c, **k: cmd_giru(c),
    "farmcards":        lambda c, **k: cmd_farmcards(c, k.get("awakening_item_id", 0)),
    "database":         lambda c, **k: cmd_database(c),
    "ping":             lambda c, **k: cmd_ping(c),
    "cooperation":      lambda c, **k: cmd_cooperation(c),
    "joint":            lambda c, **k: cmd_joint(c),
    "shopbaba":         lambda c, **k: cmd_shopbaba(c),
    "buybaba":          lambda c, **k: cmd_buy_baba(c, k["item_id"]),
}


def dispatch(command: str, client: DokkanClient, **kwargs) -> Dict:
    handler = COMMAND_REGISTRY.get(command.lower())
    if not handler:
        return {"error": f"Unknown command: '{command}'. Type !dokkanhelp for the list."}
    try:
        return handler(client, **kwargs)
    except Exception as e:
        return {"error": str(e)}
