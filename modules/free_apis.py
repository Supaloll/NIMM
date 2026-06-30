# -*- coding: utf-8 -*-
"""
modules/free_apis.py — Services gratuits sans clé (ou avec clé déjà présente)

Outils disponibles :
  get_weather(city)                  — Météo (Open-Meteo + Nominatim)
  get_jours_feries(year)             — Jours fériés français (calendrier.api.gouv.fr)
  get_exchange_rate(from_, to, amt)  — Taux de change (Frankfurter / BCE)
  geocode_address(address)           — Géocodage adresse française (BAN)
  extract_url_content(url, api_key)  — Contenu d'une URL (Tavily Extract)
  lookup_book(query)                 — Recherche livre (Open Library)
  get_country_info(country)          — Infos pays (REST Countries)
  search_commune(query)              — Commune / département (Géo API France)

Légifrance PISTE (nécessite inscription) : https://piste.gouv.fr/
"""

import httpx
import json
from datetime import datetime


_HEADERS = {
    'User-Agent': 'NIMM-assistant/1.0 (contact: nimm@local)',
    'Accept': 'application/json',
}

_TIMEOUT = 15


# ══════════════════════════════════════════════════════════════════════════════
# 1. MÉTÉO — Open-Meteo + Nominatim
# ══════════════════════════════════════════════════════════════════════════════

_WMO_CODES = {
    0: 'ciel dégagé', 1: 'principalement dégagé', 2: 'partiellement nuageux',
    3: 'couvert', 45: 'brouillard', 48: 'brouillard givrant',
    51: 'bruine légère', 53: 'bruine modérée', 55: 'bruine dense',
    61: 'pluie légère', 63: 'pluie modérée', 65: 'pluie forte',
    71: 'neige légère', 73: 'neige modérée', 75: 'neige forte',
    77: 'grains de neige', 80: 'averses légères', 81: 'averses modérées',
    82: 'averses violentes', 85: 'averses de neige légères',
    86: 'averses de neige fortes', 95: 'orage', 96: 'orage avec grêle',
    99: 'orage violent avec grêle',
}


async def get_weather(city: str) -> str:
    """Météo actuelle + prévisions 3 jours pour une ville."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        # 1. Géocodage via Nominatim
        geo = await client.get(
            'https://nominatim.openstreetmap.org/search',
            params={'q': city, 'format': 'json', 'limit': 1},
        )
        geo.raise_for_status()
        places = geo.json()
        if not places:
            return f"Ville introuvable : {city}"
        place = places[0]
        lat = float(place['lat'])
        lon = float(place['lon'])
        display_name = place.get('display_name', city).split(',')[0]

        # 2. Météo via Open-Meteo
        params = {
            'latitude': lat, 'longitude': lon,
            'current': 'temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m',
            'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum',
            'timezone': 'Europe/Paris',
            'forecast_days': 4,
        }
        meteo = await client.get('https://api.open-meteo.com/v1/forecast', params=params)
        meteo.raise_for_status()
        data = meteo.json()

    cur = data.get('current', {})
    daily = data.get('daily', {})

    # Météo actuelle
    code = cur.get('weather_code', 0)
    desc = _WMO_CODES.get(code, f'code {code}')
    lines = [
        f"Météo à {display_name} :",
        f"  Actuellement : {desc}, {cur.get('temperature_2m', '?')}°C "
        f"(ressenti {cur.get('apparent_temperature', '?')}°C)",
        f"  Vent : {cur.get('wind_speed_10m', '?')} km/h  •  Humidité : {cur.get('relative_humidity_2m', '?')}%",
        "",
        "Prévisions :",
    ]

    dates = daily.get('time', [])
    codes_d = daily.get('weather_code', [])
    tmax = daily.get('temperature_2m_max', [])
    tmin = daily.get('temperature_2m_min', [])
    precip = daily.get('precipitation_sum', [])
    jours_fr = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']
    today = datetime.today().date()

    for i, d in enumerate(dates[1:4], 1):
        try:
            dt = datetime.strptime(d, '%Y-%m-%d').date()
            if dt == today:
                label = "Aujourd'hui"
            else:
                label = jours_fr[dt.weekday()] + f" {dt.day}/{dt.month}"
            wdesc = _WMO_CODES.get(codes_d[i] if i < len(codes_d) else 0, '')
            pluie = f", {precip[i]:.1f} mm" if i < len(precip) and precip[i] else ''
            lines.append(
                f"  {label} : {wdesc}, {tmin[i] if i<len(tmin) else '?'}–{tmax[i] if i<len(tmax) else '?'}°C{pluie}"
            )
        except Exception:
            pass

    return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 2. JOURS FÉRIÉS — calendrier.api.gouv.fr
# ══════════════════════════════════════════════════════════════════════════════

async def get_jours_feries(year: int = None, zone: str = 'metropole') -> str:
    """Jours fériés français pour une année (défaut : année courante)."""
    if not year:
        year = datetime.today().year
    url = f'https://calendrier.api.gouv.fr/jours-feries/{zone}/{year}.json'
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()

    today = datetime.today().date()
    lines = [f"Jours fériés {year} ({zone.replace('-', ' ')}) :"]
    for date_str, nom in sorted(data.items()):
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d').date()
            jour_fr = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'][dt.weekday()]
            passé = ' ✓' if dt < today else (' ← aujourd\'hui' if dt == today else '')
            lines.append(f"  {date_str} ({jour_fr}) — {nom}{passé}")
        except Exception:
            lines.append(f"  {date_str} — {nom}")
    return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 3. TAUX DE CHANGE — Frankfurter (BCE)
# ══════════════════════════════════════════════════════════════════════════════

async def get_exchange_rate(amount: float = 1.0, from_currency: str = 'EUR',
                             to_currencies: str = '') -> str:
    """Taux de change en temps réel via la Banque Centrale Européenne."""
    from_c = from_currency.upper().strip()
    params: dict = {'from': from_c, 'amount': amount}
    if to_currencies:
        targets = ','.join(c.strip().upper() for c in to_currencies.replace(' ', ',').split(',') if c.strip())
        if targets:
            params['to'] = targets

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        r = await client.get('https://api.frankfurter.app/latest', params=params)
        r.raise_for_status()
        data = r.json()

    base = data.get('base', from_c)
    date = data.get('date', '?')
    rates = data.get('rates', {})
    lines = [f"Taux de change au {date} (source : BCE) — {amount} {base} ="]
    for cur, val in sorted(rates.items()):
        lines.append(f"  {val:.4f} {cur}")
    if not rates:
        lines.append("  Aucun taux disponible pour ces devises.")
    return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 4. GÉOCODAGE — Base Adresse Nationale (France) + Nominatim (monde)
# ══════════════════════════════════════════════════════════════════════════════

async def geocode_address(address: str) -> str:
    """Géocode une adresse française (BAN) ou mondiale (Nominatim)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        # Essai BAN pour les adresses françaises
        try:
            r = await client.get(
                'https://api-adresse.data.gouv.fr/search/',
                params={'q': address, 'limit': 5},
            )
            r.raise_for_status()
            feats = r.json().get('features', [])
        except Exception:
            feats = []

        if feats:
            lines = [f"Résultats pour « {address} » (Base Adresse Nationale) :"]
            for f in feats:
                props = f.get('properties', {})
                coords = f.get('geometry', {}).get('coordinates', [None, None])
                score = props.get('score', 0)
                lines.append(
                    f"  {props.get('label', '?')} "
                    f"[{coords[1]:.5f}, {coords[0]:.5f}] "
                    f"— score {score:.0%}"
                )
            return '\n'.join(lines)

        # Fallback Nominatim (monde entier)
        r2 = await client.get(
            'https://nominatim.openstreetmap.org/search',
            params={'q': address, 'format': 'json', 'addressdetails': 1, 'limit': 5},
        )
        r2.raise_for_status()
        places = r2.json()
        if not places:
            return f"Adresse introuvable : {address}"
        lines = [f"Résultats pour « {address} » (OpenStreetMap) :"]
        for p in places:
            lines.append(
                f"  {p.get('display_name', '?')} "
                f"[{float(p['lat']):.5f}, {float(p['lon']):.5f}]"
            )
        return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 5. CONTENU D'UNE URL — Tavily Extract
# ══════════════════════════════════════════════════════════════════════════════

async def extract_url_content(url: str, tavily_api_key: str) -> str:
    """Extrait le contenu textuel complet d'une URL via Tavily Extract."""
    if not tavily_api_key:
        return "[Clé Tavily manquante — configurez-la dans les paramètres NIMM]"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            'https://api.tavily.com/extract',
            headers={'Content-Type': 'application/json'},
            json={'api_key': tavily_api_key, 'urls': [url]},
        )
        r.raise_for_status()
        data = r.json()

    results = data.get('results', [])
    if not results:
        return f"Impossible d'extraire le contenu de : {url}"
    item = results[0]
    title = item.get('title', url)
    content = item.get('raw_content') or item.get('content') or ''
    # Tronquer si trop long
    if len(content) > 6000:
        content = content[:6000] + '\n\n[…contenu tronqué à 6000 caractères]'
    return f"**{title}**\n{url}\n\n{content}"


# ══════════════════════════════════════════════════════════════════════════════
# 6. LIVRE — Open Library
# ══════════════════════════════════════════════════════════════════════════════

async def lookup_book(query: str) -> str:
    """Recherche un livre par titre, auteur ou ISBN (Open Library)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        # Détection ISBN (10 ou 13 chiffres)
        isbn_clean = query.replace('-', '').replace(' ', '')
        if isbn_clean.isdigit() and len(isbn_clean) in (10, 13):
            r = await client.get(f'https://openlibrary.org/isbn/{isbn_clean}.json')
            if r.status_code == 200:
                book = r.json()
                title = book.get('title', '?')
                authors_keys = [a.get('key', '') for a in book.get('authors', [])]
                authors = []
                for k in authors_keys[:3]:
                    try:
                        ar = await client.get(f'https://openlibrary.org{k}.json')
                        authors.append(ar.json().get('name', k))
                    except Exception:
                        pass
                pages = book.get('number_of_pages', '?')
                publish = book.get('publish_date', '?')
                desc = book.get('description', '')
                if isinstance(desc, dict):
                    desc = desc.get('value', '')
                lines = [
                    f"Livre : {title}",
                    f"  Auteur(s) : {', '.join(authors) or '?'}",
                    f"  Pages : {pages}  •  Publication : {publish}",
                    f"  ISBN : {isbn_clean}",
                ]
                if desc:
                    lines.append(f"  Description : {desc[:400]}{'…' if len(desc)>400 else ''}")
                return '\n'.join(lines)

        # Recherche par titre/auteur
        r = await client.get(
            'https://openlibrary.org/search.json',
            params={'q': query, 'limit': 5, 'fields': 'title,author_name,first_publish_year,isbn,number_of_pages_median,subject'},
        )
        r.raise_for_status()
        docs = r.json().get('docs', [])
        if not docs:
            return f"Aucun livre trouvé pour : {query}"
        lines = [f"Livres pour « {query} » (Open Library) :"]
        for d in docs[:5]:
            authors = ', '.join((d.get('author_name') or [])[:2])
            year = d.get('first_publish_year', '?')
            isbn = (d.get('isbn') or ['?'])[0]
            pages = d.get('number_of_pages_median', '?')
            lines.append(
                f"\n  {d.get('title', '?')} ({year})"
                f"\n  Auteur(s) : {authors or '?'}  •  Pages : {pages}  •  ISBN : {isbn}"
            )
        return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 7. INFOS PAYS — REST Countries
# ══════════════════════════════════════════════════════════════════════════════

async def get_country_info(country: str) -> str:
    """Informations sur un pays (capitale, population, langues, monnaie…)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        # Essai par nom
        r = await client.get(
            f'https://restcountries.com/v3.1/name/{country}',
            params={'fields': 'name,capital,population,languages,currencies,region,subregion,area,flag,borders,timezones,tld'},
        )
        if r.status_code == 404:
            return f"Pays introuvable : {country}"
        r.raise_for_status()
        data = r.json()

    c = data[0]
    name_fr = c.get('translations', {}).get('fra', {}).get('common') or c.get('name', {}).get('common', '?')
    capital = ', '.join(c.get('capital') or ['?'])
    pop = c.get('population', 0)
    pop_str = f"{pop:,}".replace(',', ' ')
    region = c.get('region', '?')
    subregion = c.get('subregion', '')
    area = c.get('area', 0)
    area_str = f"{area:,.0f}".replace(',', ' ') + ' km²' if area else '?'
    flag = c.get('flag', '')
    tlds = ', '.join(c.get('tld') or ['?'])
    tz = ', '.join((c.get('timezones') or ['?'])[:3])

    langs = ', '.join(c.get('languages', {}).values()) or '?'
    currencies = '; '.join(
        f"{v.get('name','?')} ({v.get('symbol','')})" for v in c.get('currencies', {}).values()
    ) or '?'

    return (
        f"{flag} {name_fr}\n"
        f"  Région : {region}{(' / ' + subregion) if subregion else ''}\n"
        f"  Capitale : {capital}\n"
        f"  Population : {pop_str}\n"
        f"  Superficie : {area_str}\n"
        f"  Langue(s) : {langs}\n"
        f"  Monnaie : {currencies}\n"
        f"  Domaine internet : {tlds}\n"
        f"  Fuseau(x) horaire(s) : {tz}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 8. COMMUNE / DÉPARTEMENT — Géo API France
# ══════════════════════════════════════════════════════════════════════════════

async def search_commune(query: str) -> str:
    """Recherche une commune, un département ou une région française."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        # Détection code postal (5 chiffres)
        if query.strip().isdigit() and len(query.strip()) == 5:
            r = await client.get(
                'https://geo.api.gouv.fr/communes',
                params={'codePostal': query.strip(), 'fields': 'nom,code,codesPostaux,codeDepartement,codeRegion,population', 'limit': 10},
            )
        else:
            r = await client.get(
                'https://geo.api.gouv.fr/communes',
                params={'nom': query, 'fields': 'nom,code,codesPostaux,codeDepartement,codeRegion,population', 'boost': 'population', 'limit': 10},
            )
        r.raise_for_status()
        communes = r.json()

        # Recherche département si pas de commune trouvée
        if not communes:
            r2 = await client.get(
                'https://geo.api.gouv.fr/departements',
                params={'nom': query, 'fields': 'nom,code,codeRegion', 'limit': 5},
            )
            r2.raise_for_status()
            deps = r2.json()
            if deps:
                lines = [f"Département(s) pour « {query} » :"]
                for d in deps:
                    lines.append(f"  {d.get('nom','?')} (code {d.get('code','?')}, région {d.get('codeRegion','?')})")
                return '\n'.join(lines)
            return f"Aucune commune ni département trouvé pour : {query}"

    lines = [f"Commune(s) pour « {query} » :"]
    for c in communes[:8]:
        pop = c.get('population', 0)
        pop_str = f"{pop:,}".replace(',', ' ') if pop else '?'
        cp = ', '.join((c.get('codesPostaux') or [])[:2])
        lines.append(
            f"  {c.get('nom','?')} ({cp}) — dép. {c.get('codeDepartement','?')} — {pop_str} hab."
        )
    return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 9. ACCESSIBILITÉ DES LIEUX — Acceslibre (beta.gouv.fr)
# ══════════════════════════════════════════════════════════════════════════════

_ACCESLIBRE_BOOL = {
    True:  'oui',
    False: 'non',
    None:  'non renseigné',
}

def _fmt_bool(val):
    return _ACCESLIBRE_BOOL.get(val, 'non renseigné' if val is None else str(val))


async def search_acceslibre(name: str = '', city: str = '', activity: str = '') -> str:
    """Recherche l'accessibilité d'un lieu (ERP) via Acceslibre."""
    params = {'limit': 8, 'page_size': 8}
    if name:     params['nom']      = name
    if city:     params['commune']  = city
    if activity: params['activite'] = activity

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        r = await client.get('https://acceslibre.beta.gouv.fr/api/erps/', params=params)
        r.raise_for_status()
        data = r.json()

    results = data.get('results', [])
    count   = data.get('count', 0)
    if not results:
        return f"Aucun établissement trouvé (nom={name!r}, ville={city!r}, activité={activity!r})."

    lines = [f"Accessibilité — {count} résultat(s) (affichage des {len(results)} premiers) :"]
    for e in results:
        acc  = e.get('accessibilite', {}) or {}
        nom  = e.get('nom', '?')
        adr  = ', '.join(filter(None, [
            e.get('adresse', ''),
            e.get('code_postal', ''),
            e.get('commune', ''),
        ]))
        act  = e.get('activite', {})
        act_nom = act.get('nom', '') if isinstance(act, dict) else str(act)

        # Entrée
        entree = acc.get('entree', {}) or {}
        plain_pied   = _fmt_bool(entree.get('plain_pied'))
        largeur_mini = entree.get('largeur_mini')
        rampe        = _fmt_bool(entree.get('rampe'))
        audio        = _fmt_bool(entree.get('dispositif_appel_type') or entree.get('interphone'))

        # Stationnement
        stat = acc.get('stationnement', {}) or {}
        pmr_parking = _fmt_bool(stat.get('stationnement_pmr') or stat.get('presence'))

        # Cheminement intérieur
        chemin = acc.get('cheminement_ext', {}) or {}
        guidage = _fmt_bool(chemin.get('bande_guidage'))

        # Personnel
        perso = acc.get('personnel', {}) or {}
        formation = _fmt_bool(perso.get('personnels_formes'))

        lines += [
            f"\n  {nom} ({act_nom})",
            f"  {adr}",
            f"  Entrée plain-pied : {plain_pied}"
            + (f"  •  Largeur min. : {largeur_mini} cm" if largeur_mini else ''),
            f"  Rampe : {rampe}  •  Interphone/appel : {audio}",
            f"  Parking PMR : {pmr_parking}  •  Bande de guidage : {guidage}",
            f"  Personnel formé accessibilité : {formation}",
        ]
        url_slug = e.get('slug') or e.get('uuid') or ''
        if url_slug:
            lines.append(f"  Fiche complète : https://acceslibre.beta.gouv.fr/app/{url_slug}/")

    return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 10. PRODUIT ALIMENTAIRE — OpenFoodFacts
# ══════════════════════════════════════════════════════════════════════════════

_NUTRISCORE_LABEL = {'a': 'A (excellent)', 'b': 'B (bon)', 'c': 'C (moyen)',
                     'd': 'D (médiocre)', 'e': 'E (mauvais)'}
_NOVA_LABEL = {1: '1 — aliments non transformés', 2: '2 — ingrédients culinaires',
               3: '3 — aliments transformés', 4: '4 — ultra-transformés'}


async def search_food_product(query: str) -> str:
    """Recherche un produit alimentaire par nom ou code-barres (OpenFoodFacts)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={
        **_HEADERS, 'User-Agent': 'NIMM-assistant/1.0 (contact: nimm@local) - OpenFoodFacts'
    }) as client:
        # Détection code-barres (8 à 14 chiffres)
        barcode = query.strip().replace(' ', '')
        if barcode.isdigit() and 8 <= len(barcode) <= 14:
            r = await client.get(
                f'https://world.openfoodfacts.org/api/v2/product/{barcode}.json',
                params={'fields': 'product_name,brands,quantity,nutriscore_grade,nova_group,nutriments,allergens_tags,ingredients_text,categories_tags,labels_tags,stores_tags'},
            )
            r.raise_for_status()
            data = r.json()
            if data.get('status') == 0:
                return f"Produit introuvable pour le code-barres {barcode}."
            return _format_food_product(data.get('product', {}), barcode)

        # Recherche par nom
        r = await client.get(
            'https://world.openfoodfacts.org/cgi/search.pl',
            params={
                'search_terms': query, 'json': 1, 'page_size': 5,
                'fields': 'product_name,brands,quantity,nutriscore_grade,nova_group,nutriments,allergens_tags,code',
                'sort_by': 'unique_scans_n',
            },
        )
        r.raise_for_status()
        products = r.json().get('products', [])

    if not products:
        return f"Aucun produit trouvé pour : {query}"

    lines = [f"Produits alimentaires pour « {query} » :"]
    for p in products[:5]:
        ns  = _NUTRISCORE_LABEL.get((p.get('nutriscore_grade') or '').lower(), '?')
        nova = _NOVA_LABEL.get(p.get('nova_group'), '?')
        lines.append(
            f"\n  {p.get('product_name', '?')} — {p.get('brands', '?')} ({p.get('quantity', '?')})"
            f"\n  Nutri-Score : {ns}  •  NOVA : {nova}"
            f"\n  Code-barres : {p.get('code', '?')}"
        )
    return '\n'.join(lines)


def _format_food_product(p: dict, barcode: str = '') -> str:
    """Formate les détails d'un produit OpenFoodFacts."""
    name   = p.get('product_name') or '?'
    brand  = p.get('brands', '?')
    qty    = p.get('quantity', '?')
    ns     = _NUTRISCORE_LABEL.get((p.get('nutriscore_grade') or '').lower(), 'non renseigné')
    nova   = _NOVA_LABEL.get(p.get('nova_group'), 'non renseigné')
    ingr   = (p.get('ingredients_text') or '').strip()
    allergens = ', '.join(
        a.replace('en:', '').replace('fr:', '') for a in (p.get('allergens_tags') or [])
    ) or 'non renseignés'
    labels = ', '.join(
        lb.replace('en:', '').replace('fr:', '') for lb in (p.get('labels_tags') or [])[:6]
    ) or ''

    nut = p.get('nutriments', {}) or {}
    lines = [
        f"{name} — {brand} ({qty})",
        f"  Code-barres : {barcode}" if barcode else '',
        f"  Nutri-Score : {ns}",
        f"  Groupe NOVA : {nova}",
        f"  Allergènes : {allergens}",
    ]
    if labels:
        lines.append(f"  Labels : {labels}")
    if ingr:
        lines.append(f"  Ingrédients : {ingr[:500]}{'…' if len(ingr) > 500 else ''}")

    # Valeurs nutritionnelles pour 100 g
    n100 = [
        ('Énergie', f"{nut.get('energy-kcal_100g', '?')} kcal"),
        ('Graisses', f"{nut.get('fat_100g', '?')} g"),
        ('  dont saturées', f"{nut.get('saturated-fat_100g', '?')} g"),
        ('Glucides', f"{nut.get('carbohydrates_100g', '?')} g"),
        ('  dont sucres', f"{nut.get('sugars_100g', '?')} g"),
        ('Fibres', f"{nut.get('fiber_100g', '?')} g"),
        ('Protéines', f"{nut.get('proteins_100g', '?')} g"),
        ('Sel', f"{nut.get('salt_100g', '?')} g"),
    ]
    lines.append("  Valeurs nutritionnelles (pour 100 g) :")
    for label, val in n100:
        if val != '? g' and val != '? kcal':
            lines.append(f"    {label} : {val}")
    return '\n'.join(l for l in lines if l)


# ══════════════════════════════════════════════════════════════════════════════
# 11. RECETTES — TheMealDB (free tier, no key)
# ══════════════════════════════════════════════════════════════════════════════

_MEALDB_BASE = 'https://www.themealdb.com/api/json/v1/1'


async def search_recipe(query: str = '', ingredient: str = '',
                        category: str = '', area: str = '',
                        random: bool = False) -> str:
    """Recherche une recette de cuisine (TheMealDB)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        if random:
            r = await client.get(f'{_MEALDB_BASE}/random.php')
            r.raise_for_status()
            meals = r.json().get('meals') or []
            if not meals:
                return 'Aucune recette trouvée.'
            return _format_meal(meals[0])

        if ingredient:
            r = await client.get(f'{_MEALDB_BASE}/filter.php', params={'i': ingredient})
            r.raise_for_status()
            meals = r.json().get('meals') or []
            if not meals:
                return f"Aucune recette avec l'ingrédient : {ingredient}"
            lines = [f"Recettes avec « {ingredient} » ({len(meals)} résultat(s)) :"]
            for m in meals[:8]:
                lines.append(f"  • {m.get('strMeal', '?')} (id: {m.get('idMeal', '?')})")
            lines.append("\nDemande les détails d'une recette par son nom pour voir la recette complète.")
            return '\n'.join(lines)

        if category:
            r = await client.get(f'{_MEALDB_BASE}/filter.php', params={'c': category})
            r.raise_for_status()
            meals = r.json().get('meals') or []
            if not meals:
                return f"Aucune recette dans la catégorie : {category}"
            lines = [f"Recettes — catégorie « {category} » ({len(meals)} résultat(s)) :"]
            for m in meals[:8]:
                lines.append(f"  • {m.get('strMeal', '?')}")
            return '\n'.join(lines)

        if area:
            r = await client.get(f'{_MEALDB_BASE}/filter.php', params={'a': area})
            r.raise_for_status()
            meals = r.json().get('meals') or []
            if not meals:
                return f"Aucune recette de cuisine {area}"
            lines = [f"Recettes — cuisine « {area} » ({len(meals)} résultat(s)) :"]
            for m in meals[:8]:
                lines.append(f"  • {m.get('strMeal', '?')}")
            return '\n'.join(lines)

        # Recherche par nom (défaut)
        r = await client.get(f'{_MEALDB_BASE}/search.php', params={'s': query or ''})
        r.raise_for_status()
        meals = r.json().get('meals') or []
        if not meals:
            return f"Aucune recette trouvée pour : {query}"
        if len(meals) == 1:
            return _format_meal(meals[0])
        lines = [f"Recettes pour « {query} » ({len(meals)} résultat(s)) :"]
        for m in meals[:6]:
            lines.append(f"  • {m.get('strMeal', '?')} ({m.get('strArea', '?')} — {m.get('strCategory', '?')})")
        lines.append("\nDemande la recette complète par son nom exact pour voir les détails.")
        return '\n'.join(lines)


def _format_meal(m: dict) -> str:
    """Formate une recette TheMealDB de façon accessible."""
    name     = m.get('strMeal', '?')
    category = m.get('strCategory', '?')
    area     = m.get('strArea', '?')
    instructions = (m.get('strInstructions') or '').strip()
    youtube  = m.get('strYoutube', '')
    source   = m.get('strSource', '')

    # Ingrédients + mesures (jusqu'à 20)
    ingredients = []
    for i in range(1, 21):
        ing = (m.get(f'strIngredient{i}') or '').strip()
        msr = (m.get(f'strMeasure{i}') or '').strip()
        if ing:
            ingredients.append(f"{msr} {ing}".strip() if msr else ing)

    lines = [
        f"Recette : {name}",
        f"  Catégorie : {category}  •  Cuisine : {area}",
        "",
        "Ingrédients :",
    ] + [f"  • {ing}" for ing in ingredients] + [
        "",
        "Préparation :",
        instructions[:3000] + ('…' if len(instructions) > 3000 else ''),
    ]
    if youtube:
        lines += ["", f"Vidéo YouTube : {youtube}"]
    if source:
        lines += [f"Source : {source}"]
    return '\n'.join(lines)
