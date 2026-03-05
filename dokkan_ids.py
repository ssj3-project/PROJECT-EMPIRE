'''
dokkan_ids.py — Referentiel d'IDs Dokkan Battle.
Ajoute tes IDs dans les dicts vides au fur et a mesure.
Utilise par commands.py pour afficher des noms lisibles dans Discord.
'''

# =============================================================================
# ACT ITEMS (stamina)
# =============================================================================

ACT_ITEMS = {
    1: "Viande maturee (P)",
    2: "Viande maturee (M)",
    3: "Viande maturee (G)",
}

# =============================================================================
# SUPPORT ITEMS
# =============================================================================

SUPPORT_ITEMS = {
    1:      "Boisson de soin",
    2:      "Super boisson de soin",
    3:      "Ultra boisson de soin",
    4:      "Boisson de soin ultime",
    5:      "Medicament de Karin",
    6:      "Haricot magique",
    1000:   "Dende",
    1002:   "Cargo",
    1100:   "Oolong [AGI]",
    1101:   "Oolong [TEC]",
    1102:   "Plume [INT]",
    1103:   "Plume [PUI]",
    1104:   "Plume [END]",
    1200:   "Shu",
    1201:   "M. Satan",
    1202:   "Roi",
    1203:   "Lunch (normale)",
    1400:   "Presentateur du tournoi [AGI]",
    1401:   "Presentateur du tournoi [TEC]",
    1402:   "Presentateur du tournoi [INT]",
    1403:   "Presentateur du tournoi [PUI]",
    1404:   "Presentateur du tournoi [END]",
    1502:   "Bulma",
    1503:   "Gyumao",
    1505:   "Mamie Voyante",
    1506:   "Videl [AGI]",
    1507:   "Videl [TEC]",
    1508:   "Videl [INT]",
    1509:   "Videl [PUI]",
    1510:   "Videl [END]",
    1600:   "Muri",
    1603:   "Lanfan",
    1700:   "Fantome portier",
    1701:   "Roi Enma",
    1800:   "Ancien detecteur (vert)",
    1801:   "Ancien detecteur (rouge)",
    1900:   "Souris",
    1901:   "Oolong (taureau)",
    1902:   "To le carotteur",
    1903:   "Tenue de combat ancestrale",
    1904:   "Char",
    1905:   "Oolong",
    1906:   "Tenue de combat",
    1907:   "Bouton de Zen-O",
    13001:  "Oolong",
    15201:  "Biscuit Dabra",
    17501:  "Deguisement Monaka",
    21601:  "Queue de dino Paozu",
    30501:  "C-18",
    30502:  "Maron",
    30503:  "Bulma",
    30504:  "Videl",
    30505:  "Whis",
    31401:  "Pilaf",
    31402:  "Soba",
    31403:  "Mai",
    31501:  "Fruit de l'Arbre sacre",
    31502:  "Hire Dragon",
    32101:  "Bulma (futur)",
    32102:  "C-8",
    32301:  "Princesse Hebi",
    32601:  "Shamo",
    32701:  "Brindille",
    32702:  "Brindille",
    33001:  "Chichi (infirmiere)",
    33301:  "Jaga Budder",
    33401:  "Gure",
    33701:  "Roulette Russe de takoyaki",
    33801:  "Flute de Tapion",
    34601:  "Grenouille",
    35501:  "Cheelai",
    35502:  "Lemo",
    36201:  "Kaio du nord",
    39701:  "Robot-guide",
    90001:  "Tenue de combat bien usee",
    130801: "Resurroptere",
}

# =============================================================================
# POTENTIAL ITEMS
# =============================================================================

POTENTIAL_ITEMS = {
    1:  "Sphere potentiel AGI (P)",
    2:  "Sphere potentiel TEC (P)",
    3:  "Sphere potentiel INT (P)",
    4:  "Sphere potentiel PUI (P)",
    5:  "Sphere potentiel END (P)",
    6:  "Sphere potentiel AGI (M)",
    7:  "Sphere potentiel TEC (M)",
    8:  "Sphere potentiel INT (M)",
    9:  "Sphere potentiel PUI (M)",
    10: "Sphere potentiel END (M)",
    11: "Sphere potentiel AGI (G)",
    12: "Sphere potentiel TEC (G)",
    13: "Sphere potentiel INT (G)",
    14: "Sphere potentiel PUI (G)",
    15: "Sphere potentiel END (G)",
    16: "Sphere potentiel (P)",
    17: "Sphere potentiel (M)",
    18: "Sphere potentiel (G)",
    19: "Sphere potentiel Super (P)",
    20: "Sphere potentiel Super (M)",
    21: "Sphere potentiel Super (G)",
    # IDs 22-81 : a completer
}

# =============================================================================
# TREASURE ITEMS
# =============================================================================

TREASURE_ITEMS = {
    1:    "Gemme incroyable (verte)",
    2:    "Fruits en metal",
    3:    "Insigne de M. Satan",
    6:    "Radis genial",
    8:    "Kachikatchin",
    9:    "Eclat des champions",
    10:   "Flan",
    13:   "Pierre de richesse",
    14:   "Dessert apprecie de l'univers",
    16:   "Lan Lan",
    17:   "Cle du sceau de l'eau surhumaine",
    18:   "Princesse endormie",
    19:   "Apogee du combat",
    22:   "Gemme incroyable (bleue)",
    23:   "Peluche Penenko",
    24:   "Peluche Penenko (grande)",
    25:   "Autographe de Satan",
    26:   "L'energie de tous",
    28:   "Minerai Dragon (vert)",
    29:   "Piece du 9e anniversaire",
    35:   "Piece du 10e anniversaire",
    36:   "Preuve de depassement",
    37:   "Coupon d'echange",
    38:   "Coupon d'echange du 10e anniv.",
    47:   "Piece globale 2025",
    48:   "Pilier brise",
    50:   "Majilite",
    51:   "Lait",
    53:   "Piece du 11e anniversaire",
    60:   "Sphere d'opportunite 6",
    61:   "Sphere d'opportunite 7",
    62:   "Coupon d'echange sph. d'aptitude",
    1000: "Super Pierre Dragon",
    1001: "Pierre Dragon divine",
    1006: "Super Pierre Dragon premium",
    1023: "Pierre Dragon memorable",
    1031: "Pierre Dragon divine 14",
    1082: "Pierre Dragon selection 11",
    1083: "Pierre Dragon premium UR 6",
    1084: "Pierre Dragon premium LR 6",
    2000: "Souvenir de combat",
    3518: "Ticket de participation 2",
    4001: "Pierre Kaio Shin",
    5002: "Chocolats extra fins",
    7000: "Piece Festival Dokkan",
    7002: "Piece Invocation",
    7003: "Piece Celebrations",
    7004: "Point d'invocation",
    7203: "Piece Festival Dokkan (11e anniv.)",
    7303: "Piece Celebrations (11e anniv.)",
    9119: "Ticket Envolee de puissance",
    9122: "Ticket Persos SSR en renfort",
}

# =============================================================================
# BABA SHOP TREASURES (subset de TREASURE_ITEMS)
# =============================================================================

BABA_SHOP_TREASURES = {
    1:    "Gemme incroyable (verte)",
    2:    "Fruits en metal",
    3:    "Insigne de M. Satan",
    6:    "Radis genial",
    9:    "Eclat des champions",
    10:   "Flan",
    13:   "Pierre de richesse",
    14:   "Dessert apprecie de l'univers",
    16:   "Lan Lan",
    17:   "Cle du sceau de l'eau surhumaine",
    18:   "Princesse endormie",
    19:   "Apogee du combat",
    22:   "Gemme incroyable (bleue)",
    23:   "Peluche Penenko",
    24:   "Peluche Penenko (grande)",
    25:   "Autographe de Satan",
    28:   "Minerai Dragon (vert)",
    38:   "Coupon d'echange du 10e anniv.",
    50:   "Majilite",
    51:   "Lait",
    53:   "Piece du 11e anniversaire",
    60:   "Sphere d'opportunite 6",
    61:   "Sphere d'opportunite 7",
    62:   "Coupon d'echange sph. d'aptitude",
    1082: "Pierre Dragon selection 11",
    1083: "Pierre Dragon premium UR 6",
    1084: "Pierre Dragon premium LR 6",
    2000: "Souvenir de combat",
    3518: "Ticket de participation 2",
    4001: "Pierre Kaio Shin",
    5002: "Chocolats extra fins",
    7000: "Piece Festival Dokkan",
    7002: "Piece Invocation",
    7003: "Piece Celebrations",
    7004: "Point d'invocation",
    7203: "Piece Festival Dokkan (11e anniv.)",
    7303: "Piece Celebrations (11e anniv.)",
    9119: "Ticket Envolee de puissance",
    9122: "Ticket Persos SSR en renfort",
}

# =============================================================================
# AWAKENING ITEMS (medailles d'eveil)
# =============================================================================

AWAKENING_ITEMS = {
    1:    "Gregory",
    2:    "Bubbles",
    3:    "Dr. Gero",
    4:    "M. Popo",
    5:    "Maitre des Grues",
    6:    "Kamesennin",
    7:    "Mutaito",
    8:    "Son Gohan (grand-pere)",
    9:    "Tout-Puissant",
    10:   "Chef des Nameks",
    11:   "Babidi",
    12:   "Bibidi",
    13:   "Karin",
    14:   "Kibito",
    15:   "Kaio de l'ouest",
    16:   "Kaio du sud",
    17:   "Kaio de l'est",
    18:   "Kaio du nord",
    19:   "Kaio Shin de l'est",
    20:   "Vieux Kaio Shin",
    101:  "Son Goku",
    102:  "Dr. Gero",
    103:  "C-19",
    104:  "C-14",
    105:  "C-15",
    321:  "Trunks (jeune)",
    322:  "Trunks SS (jeune) & Broly SS",
    361:  "Bardock",
    362:  "Freezer (forme finale)",
    363:  "Bardock Super Saiyan",
    1001: "La tortue",
    1002: "Bulma",
    1391: "Yamcha",
    3030: "Bardock",
    3031: "Selipa",
    3032: "Toteppo",
    3033: "Pumbukim",
    3034: "Toma",
    3035: "Freezer",
    3041: "Whis",
    3042: "Bulma",
    3043: "Jaco",
    3044: "Beerus",
    3045: "Vegeta",
    3046: "C-18",
    3047: "Maron",
    3048: "Freezer (1re forme)",
    3049: "Freezer (2e forme)",
    3050: "Freezer (3eme forme)",
    3051: "Freezer (forme finale)",
    3052: "Golden Freezer",
    3061: "Zangya",
    3062: "Gokua",
    3063: "Bido",
    3064: "Bujin",
    3065: "Bojack",
    3066: "Son Gohan (enfant)",
    3071: "Sauzer",
    3072: "Dore",
    3073: "Neizu",
    3074: "Cooler",
    3075: "Son Goku",
    3081: "Videl",
    3082: "Son Gohan (jeune)",
    3083: "M. Satan",
    3084: "Chichi",
    3085: "Bulma",
    3086: "Spopovitch",
    3087: "Yamu",
    3088: "Boo (mal incarne)",
    3089: "Boo (super)",
    3141: "Beerus",
    3142: "Whis",
    3143: "Son Goten (petit)",
    3144: "Trunks (petit)",
    3145: "Videl",
    3146: "Son Gohan ultime",
    3147: "Vegeta",
    3151: "Fruit de l'Arbre sacre",
    3181: "Noyau de Metal Cooler",
    4031: "Pod de sustentation de Freezer",
    5011: "Carot",
    5012: "Broly Super Saiyan",
    5013: "Broly SS Legendaire",
    5021: "Son Goku",
    5022: "Cell (forme parfaite)",
    5023: "Cell (forme parfaite)",
    5031: "Son Goku",
    5032: "Boo (petit)",
    5041: "Boule a 4 etoiles",
    5042: "Son Goku Super Saiyan",
    5043: "Son Goku SS3",
}

# =============================================================================
# SPECIAL ITEMS (tickets, invocations speciales)
# =============================================================================

SPECIAL_ITEMS = {
    # A remplir avec tes IDs
    # ex: 1: "Ticket d'invocation",
}

# =============================================================================
# EVENTKAGI ITEMS (cles pour events/Z-Battles)
# =============================================================================

EVENTKAGI_ITEMS = {
    # A remplir avec tes IDs
    # ex: 1: "Cle Bardock",
}

# =============================================================================
# TRAINING ITEMS
# =============================================================================

TRAINING_ITEMS = {
    # A remplir avec tes IDs
}

# =============================================================================
# TRAINING FIELDS
# =============================================================================

TRAINING_FIELDS = {
    # A remplir avec tes IDs
}

# =============================================================================
# EVENTKAGI — IDs prioritaires pour cmd_keyevents
# =============================================================================

PRIORITY_KAGI_IDS = [
    # Mets ici les IDs des cles kagi a farmer en priorite
    # ex: 1, 2, 3
]

# =============================================================================
# HELPERS utilises par commands.py
# =============================================================================

_TABLE_MAP = None

def _get_table_map():
    global _TABLE_MAP
    if _TABLE_MAP is None:
        _TABLE_MAP = {
            'act_items':           ACT_ITEMS,
            'support_items':       SUPPORT_ITEMS,
            'potential_items':     POTENTIAL_ITEMS,
            'treasure_items':      TREASURE_ITEMS,
            'baba_shop_treasures': BABA_SHOP_TREASURES,
            'awakening_items':     AWAKENING_ITEMS,
            'special_items':       SPECIAL_ITEMS,
            'eventkagi_items':     EVENTKAGI_ITEMS,
            'training_items':      TRAINING_ITEMS,
            'training_fields':     TRAINING_FIELDS,
        }
    return _TABLE_MAP


def resolve_items(items, table='treasure_items'):
    """
    Enrichit une liste d'items avec leurs noms depuis le referentiel.
    Accepte une liste de dicts ou d'ints.
    """
    tbl = _get_table_map().get(table, TREASURE_ITEMS)
    result = []
    for item in items:
        if isinstance(item, dict):
            iid  = (item.get('item_id') or item.get('id')
                    or item.get('treasure_id') or item.get('awakening_item_id'))
            name = tbl.get(iid, f'Item #{iid}') if iid else '?'
            result.append({**item, 'name': name})
        else:
            result.append({'id': item, 'name': tbl.get(item, f'Item #{item}')})
    return result


def awakening_medal_name(medal_id):
    """Retourne le nom d'une medaille d'eveil par son ID."""
    return AWAKENING_ITEMS.get(medal_id, f'Medaille #{medal_id}')


def kagi_name(kagi_id):
    """Retourne le nom d'une cle kagi par son ID."""
    return EVENTKAGI_ITEMS.get(kagi_id, f'Cle #{kagi_id}')


def lookup(category, item_id):
    """Lookup generique : lookup('support_items', 1907) -> 'Bouton de Zen-O'"""
    tbl = _get_table_map().get(category, {})
    return tbl.get(item_id, f'#{item_id}')
