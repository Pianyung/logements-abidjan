#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collecteur d'annonces de location d'appartements a Abidjan.

Sources :
  - Jiji.co.ci          (toujours actif, parsing HTML simple via requests)
  - CoinAfrique.com     (optionnel, --with-coinafrique, necessite Playwright)

Filtre selon config.json : loyer, nombre de pieces/chambres, zones.
Sortie : data/listings.json (consomme par le site statique index.html)

Usage :
  python collect.py                 # collecte Jiji -> data/listings.json
  python collect.py --with-coinafrique
  python collect.py --test          # lance les tests internes (sans reseau)
"""

import json
import os
import re
import sys
import html
import datetime
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
DATA_PATH = os.path.join(HERE, "data", "listings.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

JIJI_PAGES = [
    "https://jiji.co.ci/abidjan/houses-apartments-for-rent?price_min={min}&price_max={max}",
    "https://jiji.co.ci/abidjan/houses-apartments-for-rent?price_min={min}&price_max={max}&page=2",
]


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------------
# Helpers de parsing (testables sans reseau)
# ----------------------------------------------------------------------------
PRICE_RE = re.compile(r"CFA\s*([\d.,\s]+)\s*(per month|/month|par mois|per quarter|"
                      r"par trimestre|per week|par semaine|per day|par jour)?\b", re.I)
BEDROOMS_RE = re.compile(r"(\d+)\s*chbre", re.I)
PIECES_RE = re.compile(r"(\d+)\s*pi[eè]ce", re.I)


def parse_price(text):
    """Renvoie (montant:int|None, unite:str|None) a partir d'un libelle Jiji."""
    m = PRICE_RE.search(text)
    if not m:
        return None, None
    raw = re.sub(r"[^\d]", "", m.group(1))
    amount = int(raw) if raw else None
    unit = (m.group(2) or "per month").lower()
    return amount, unit


def parse_bedrooms(text):
    m = BEDROOMS_RE.search(text)
    return int(m.group(1)) if m else None


def parse_pieces(text):
    m = PIECES_RE.search(text)
    return int(m.group(1)) if m else None


def detect_zone(text, zones):
    low = text.lower()
    for z in zones:
        if z in low:
            return z
    return None


def is_furnished(text):
    low = text.lower()
    return any(k in low for k in ("meubl", "furnished"))


def is_studio(text):
    low = text.lower()
    # un studio explicite n'est pas un 2-3 pieces, sauf si "2/3 pieces" est mentionne
    if "studio" not in low:
        return False
    return parse_pieces(text) not in (2, 3)


def matches_criteria(item, cfg):
    """Decide si une annonce correspond aux criteres."""
    if item.get("studio") and not cfg.get("inclure_studios"):
        return False
    # Unite de loyer : on exclut trimestre/semaine/jour
    unit = (item.get("unite") or "per month").lower()
    if any(bad in unit for bad in cfg["exclure_unite_loyer"]):
        return False
    # Loyer dans la fourchette
    price = item.get("loyer")
    if price is None or not (cfg["loyer_min"] <= price <= cfg["loyer_max"]):
        return False
    # Zone ciblee
    if item.get("zone") is None:
        return False
    # Pieces / chambres
    pieces = item.get("pieces")
    chambres = item.get("chambres")
    if pieces is not None:
        if pieces in cfg["pieces_cibles"]:
            return True
        if pieces == 1 and cfg.get("inclure_studios"):
            return True
        return False
    if chambres is not None:
        if chambres in cfg["chambres_equivalentes"]:
            return True
        if chambres == 0 and cfg.get("inclure_studios"):
            return True
        return False
    # Pas d'info pieces/chambres : on accepte prudemment
    return True


def make_id(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def build_item(title, url, raw_text, cfg, source):
    price, unit = parse_price(raw_text)
    item = {
        "id": make_id(url),
        "titre": title.strip(),
        "url": url,
        "loyer": price,
        "unite": unit,
        "chambres": parse_bedrooms(raw_text),
        "pieces": parse_pieces(raw_text),
        "zone": detect_zone(raw_text, cfg["zones_cibles"]),
        "meuble": is_furnished(raw_text),
        "studio": is_studio(raw_text),
        "source": source,
        "resume": clean_summary(raw_text, title),
        "vu_le": datetime.date.today().isoformat(),
    }
    return item


def clean_summary(raw_text, title):
    txt = raw_text.replace(title, " ")
    txt = re.sub(r"CFA[\d.,\s]+(per month|/month|par mois|per quarter|par trimestre)?", " ", txt, flags=re.I)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:180]


# ----------------------------------------------------------------------------
# Source Jiji (requests + BeautifulSoup)
# ----------------------------------------------------------------------------
def collect_jiji(cfg):
    import requests
    from bs4 import BeautifulSoup

    items = []
    seen = set()
    for tmpl in JIJI_PAGES:
        url = tmpl.format(min=cfg["loyer_min"], max=cfg["loyer_max"])
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "fr"}, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"[jiji] echec {url}: {e}", file=sys.stderr)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/houses-apartments-for-rent/" not in href or not href.endswith(".html"):
                continue
            full = href if href.startswith("http") else "https://jiji.co.ci" + href
            base = full.split("?")[0]
            if base in seen:
                continue
            seen.add(base)
            raw = a.get_text(" ", strip=True)
            if not raw:
                continue
            title = raw.split("CFA")[0].strip() or raw[:60]
            item = build_item(title, base, raw, cfg, "Jiji")
            if matches_criteria(item, cfg):
                items.append(item)
    print(f"[jiji] {len(items)} annonces retenues", file=sys.stderr)
    return items


# ----------------------------------------------------------------------------
# Source CoinAfrique (Playwright, optionnelle)
# ----------------------------------------------------------------------------
def collect_coinafrique(cfg):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"[coinafrique] Playwright indisponible: {e}", file=sys.stderr)
        return []
    items = []
    url = (f"https://ci.coinafrique.com/ville/{cfg['ville']}/appartements"
           f"?prix_min={cfg['loyer_min']}&prix_max={cfg['loyer_max']}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=UA)
            page.goto(url, timeout=45000, wait_until="networkidle")
            page.wait_for_timeout(2500)
            cards = page.query_selector_all("div.card.ad__card, a[href*='/annonce/']")
            seen = set()
            for c in cards:
                link = c.query_selector("a[href*='/annonce/']") or c
                href = link.get_attribute("href") if link else None
                if not href:
                    continue
                full = href if href.startswith("http") else "https://ci.coinafrique.com" + href
                if full in seen:
                    continue
                seen.add(full)
                raw = c.inner_text().replace("\n", " ").strip()
                title = raw.split("CFA")[0].split("\n")[0][:60]
                item = build_item(title or "Annonce CoinAfrique", full, raw, cfg, "CoinAfrique")
                if matches_criteria(item, cfg):
                    items.append(item)
            browser.close()
    except Exception as e:
        print(f"[coinafrique] echec: {e}", file=sys.stderr)
    print(f"[coinafrique] {len(items)} annonces retenues", file=sys.stderr)
    return items




# ----------------------------------------------------------------------------
# Gestion du temps : date de publication & fraicheur
# ----------------------------------------------------------------------------
REL_FR = re.compile(r"il y a\s+(\d+)\s*(minute|heure|jour|semaine|mois)", re.I)
REL_EN = re.compile(r"(\d+)\s*(minute|hour|day|week|month)s?\s+ago", re.I)
ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_UNIT_DAYS = {"jour": 1, "day": 1, "semaine": 7, "week": 7, "mois": 30, "month": 30}


def parse_published_date(raw):
    """raw = un item de l'API Google CSE. Renvoie une date ISO (YYYY-MM-DD) ou None."""
    try:
        meta = (raw.get("pagemap", {}).get("metatags") or [{}])[0]
    except Exception:
        meta = {}
    for k in ("article:published_time", "article:modified_time", "og:updated_time",
              "og:article:published_time", "date", "dc.date", "dc.date.issued"):
        v = meta.get(k)
        if v:
            m = ISO_DATE_RE.search(v)
            if m:
                return m.group(1)
    snip = (raw.get("snippet") or "")[:50]
    m = REL_FR.search(snip) or REL_EN.search(snip)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = _UNIT_DAYS.get(unit, 0) * n  # minute/heure -> 0 jour (= aujourd'hui)
        return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    m = ISO_DATE_RE.search(snip)
    if m:
        return m.group(1)
    return None


def age_jours(date_iso):
    if not date_iso:
        return None
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(date_iso)).days
    except Exception:
        return None


# ----------------------------------------------------------------------------
# Source Facebook via Google Custom Search (annonces publiques indexees)
# ----------------------------------------------------------------------------
NIGHTLY_RE = re.compile(r"nuit[ée]?e?|/\s*jour|par\s+jour|la\s+nuit|meubl.{0,15}\bnuit", re.I)
MILLE_RE = re.compile(r"(\d{2,4})\s*mille", re.I)
FCFA_PATS = [
    re.compile(r"(?:CFA|FCFA)\s*([\d][\d .,]{2,})", re.I),
    re.compile(r"([\d][\d .,]{2,})\s*(?:FCFA|CFA|francs?|F)\b", re.I),
]


def parse_price_fb(text):
    """Extrait un loyer mensuel a partir d'un titre/snippet Facebook.
    Gere 130mille, 150.000, 150,000, 80 000 fcfa, CFA150,000. Exclut les nuitees."""
    if NIGHTLY_RE.search(text):
        return None, "nuit"
    m = MILLE_RE.search(text)
    if m:
        return int(m.group(1)) * 1000, "per month"
    for pat in FCFA_PATS:
        m = pat.search(text)
        if m:
            digits = re.sub(r"[^\d]", "", m.group(1))
            if digits:
                val = int(digits)
                if 10000 <= val <= 100000000:
                    return val, "per month"
    return None, None


def build_item_fb(title, snippet, url, cfg):
    text = (title or "") + " . " + (snippet or "")
    price, unit = parse_price_fb(text)
    return {
        "id": make_id(url),
        "titre": (title or "Annonce Facebook").strip()[:120],
        "url": url.replace("//m.facebook.com", "//www.facebook.com"),
        "loyer": price,
        "unite": unit,
        "chambres": None,
        "pieces": parse_pieces(text),
        "zone": detect_zone(text, cfg["zones_cibles"]),
        "meuble": is_furnished(text),
        "studio": is_studio(text),
        "source": "Facebook",
        "resume": re.sub(r"\s+", " ", (snippet or title or "")).strip()[:180],
        "vu_le": datetime.date.today().isoformat(),
        "date_pub": None,
        "age_jours": None,
    }


def matches_criteria_fb(item, cfg):
    """Plus permissif que Jiji : Facebook est prioritaire, on garde meme sans prix,
    mais on rejette hors-zone, hors-budget (si prix connu), nuitees, studios et mauvais nb pieces."""
    if item.get("unite") == "nuit":
        return False
    if item.get("studio") and not cfg.get("inclure_studios"):
        return False
    if item.get("zone") is None:
        return False
    price = item.get("loyer")
    if price is not None and not (cfg["loyer_min"] <= price <= cfg["loyer_max"]):
        return False
    pieces = item.get("pieces")
    if pieces is not None and pieces not in cfg["pieces_cibles"]:
        if not (pieces == 1 and cfg.get("inclure_studios")):
            return False
    return True


def collect_facebook_google(cfg):
    import os
    import requests
    key = os.environ.get("GOOGLE_API_KEY")
    cx = os.environ.get("GOOGLE_CX")
    if not key or not cx:
        print("[facebook] GOOGLE_API_KEY / GOOGLE_CX absents -> source ignoree "
              "(voir README pour la cle gratuite)", file=sys.stderr)
        return []
    fenetre = int(cfg.get("fb_fenetre_jours", 7))
    items, seen = [], set()
    for q in cfg.get("fb_requetes", []):
        for start in (1, 11):  # 2 pages = jusqu'a 20 resultats / requete
            base = {"key": key, "cx": cx, "q": q, "num": 10, "start": start}
            attempts = [
                {**base, "gl": "ci", "lr": "lang_fr",
                 "dateRestrict": cfg.get("fb_fraicheur", "d7")},   # complet
                {**base, "dateRestrict": cfg.get("fb_fraicheur", "d7")},  # sans gl/lr
                base,                                               # minimal
            ]
            r = None
            for ai, params in enumerate(attempts, 1):
                try:
                    r = requests.get("https://www.googleapis.com/customsearch/v1",
                                     params=params, timeout=30)
                except Exception as e:
                    print(f"[facebook] echec reseau: {e}", file=sys.stderr)
                    r = None
                    break
                if r.status_code == 200:
                    break
                try:
                    err = r.json().get("error", {})
                    det = (err.get("errors") or [{}])[0]
                    print(f"[facebook] tentative {ai}/3 HTTP {r.status_code} "
                          f"reason={det.get('reason')} :: MESSAGE: {err.get('message')}",
                          file=sys.stderr)
                except Exception:
                    print(f"[facebook] tentative {ai}/3 HTTP {r.status_code}: {r.text[:400]}",
                          file=sys.stderr)
            if r is None or r.status_code != 200:
                break
            data = r.json()
            results = data.get("items", [])
            if not results:
                break
            for it in results:
                url = (it.get("link") or "").split("?")[0]
                if "facebook.com" not in url or url in seen:
                    continue
                seen.add(url)
                item = build_item_fb(it.get("title", ""), it.get("snippet", ""), url, cfg)
                item["date_pub"] = parse_published_date(it)
                item["age_jours"] = age_jours(item["date_pub"])
                # respecte la fenetre temporelle
                if item["age_jours"] is not None and item["age_jours"] > fenetre:
                    continue
                if item["date_pub"] is None and cfg.get("exiger_date"):
                    continue
                if matches_criteria_fb(item, cfg):
                    items.append(item)
            if len(results) < 10:
                break
    print(f"[facebook] {len(items)} annonces retenues", file=sys.stderr)
    return items


# ----------------------------------------------------------------------------
# Fusion + persistance (conserve l'historique, marque les nouveautes)
# ----------------------------------------------------------------------------
def load_existing():
    if os.path.exists(DATA_PATH):
        try:
            with open(DATA_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"maj": None, "annonces": []}


def merge_and_save(new_items):
    existing = load_existing()
    by_id = {a["id"]: a for a in existing.get("annonces", [])}
    today = datetime.date.today().isoformat()
    nb_new = 0
    for it in new_items:
        if it["id"] in by_id:
            by_id[it["id"]].update({k: it[k] for k in ("loyer", "unite", "resume") if it.get(k)})
            by_id[it["id"]]["nouveau"] = False
        else:
            it["ajoute_le"] = today
            it["nouveau"] = True
            by_id[it["id"]] = it
            nb_new += 1
    annonces = sorted(by_id.values(), key=lambda a: a.get("ajoute_le", ""), reverse=True)
    out = {"maj": datetime.datetime.now().isoformat(timespec="minutes"),
           "nb_total": len(annonces), "nb_nouvelles": nb_new, "annonces": annonces}
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[ok] {len(annonces)} annonces ({nb_new} nouvelles) -> {DATA_PATH}", file=sys.stderr)
    return out


# ----------------------------------------------------------------------------
# Tests internes (sans reseau) — valident parsing + filtrage
# ----------------------------------------------------------------------------
def run_tests():
    cfg = load_config()
    samples = [
        ("Meublé 2chbre Appartement dans Yopougon à Louer CFA 80,000per month "
         "Une maison tres belle et bien situee Yopougon", True),
        ("3chbre Appartement dans Particulier Fiable, Cocody à Louer CFA 100,000per month "
         "studios 70000 2pieces 120000 Cocody", True),
        ("Meublé 3chbre Appartement dans Mt Service Location, Cocody à Louer CFA 75,000per quarter "
         "Résidence meublée 3pièces Cocody", False),   # exclu: trimestre
        ("5chbre Duplex dans Francis Gweh, Cocody à Louer CFA 3,000,000per month "
         "villa duplex Cocody", False),                # exclu: hors budget
        ("2chbre Appartement dans Batoadê Immobilier, Songon à Louer CFA 130,000per month "
         "3 pieces Songon gravier", False),            # exclu: zone hors liste
        ("1chbre Studio dans Cocody à Louer CFA 130,000per month grand studio "
         "deux plateaux vallon Cocody", False),        # exclu: studio (inclure_studios=false)
    ]
    ok = 0
    for text, expected in samples:
        title = text.split("CFA")[0].strip()
        item = build_item(title, "https://x/" + str(hash(text)), text, cfg, "test")
        got = matches_criteria(item, cfg)
        status = "OK " if got == expected else "FAIL"
        if got == expected:
            ok += 1
        print(f"  [{status}] attendu={expected} obtenu={got} | "
              f"loyer={item['loyer']} unite={item['unite']} ch={item['chambres']} "
              f"pieces={item['pieces']} zone={item['zone']}")
    # tests unitaires parsing
    assert parse_price("CFA 80,000per month")[0] == 80000
    assert parse_price("CFA 1,500,000per month")[0] == 1500000
    assert parse_price("CFA 75,000per quarter")[1] == "per quarter"
    assert parse_bedrooms("3chbre Appartement") == 3
    assert parse_pieces("Résidence 3pièces") == 3
    # --- tests parser Facebook (snippets reels) ---
    fb = [
        ("À louer 2 pièces 130mille Cocody Angré Nouveau Chu", 130000, 2, True),
        ("2 pièces a Yopougon cité verte 80 000 fcfa A LOUER", 80000, 2, True),
        ("Un appartement 2 pièces à louer Cocody | CFA150,000", 150000, 2, True),
        ("2 PIECES A COCODY RIVIERA 2 25.000F LA NUITEE meublé", None, 2, False),
        ("Bel appartement 2 pièces Cocody Riviera Loyer 200 milles", 200000, 2, False),
        ("BEL APPARTEMENT 2 PIÈCES A LOUER COCODY RIVIERA ATTOBAN", None, 2, True),
    ]
    fbok = 0
    for text, exp_price, exp_pieces, exp_keep in fb:
        it = build_item_fb(text, "", "https://facebook.com/" + str(hash(text)), cfg)
        keep = matches_criteria_fb(it, cfg)
        good = (it["loyer"] == exp_price) and (it["pieces"] == exp_pieces) and (keep == exp_keep)
        fbok += good
        st = "OK " if good else "FAIL"
        print(f"  [FB {st}] prix={it['loyer']} (att {exp_price}) pieces={it['pieces']} "
              f"zone={it['zone']} garde={keep} (att {exp_keep})")
    print(f"FB parser: {fbok}/{len(fb)} corrects")
    assert parse_price_fb("130mille")[0] == 130000
    assert parse_price_fb("CFA150,000")[0] == 150000
    assert parse_price_fb("80 000 fcfa")[0] == 80000
    assert parse_price_fb("25.000F la nuitée")[1] == "nuit"
    # tests date de publication
    assert parse_published_date({"pagemap": {"metatags": [{"article:published_time": "2026-06-25T10:00:00Z"}]}}) == "2026-06-25"
    assert parse_published_date({"snippet": "il y a 3 jours - Bel appartement 2 pièces"}) == (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    assert parse_published_date({"snippet": "il y a 5 heures - 2 pièces Cocody"}) == datetime.date.today().isoformat()
    assert age_jours((datetime.date.today() - datetime.timedelta(days=2)).isoformat()) == 2
    print(f"\nResultat filtrage Jiji: {ok}/{len(samples)} corrects")
    return ok == len(samples) and fbok == len(fb)


# ----------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    if "--test" in args:
        sys.exit(0 if run_tests() else 1)
    cfg = load_config()
    items = []
    if "--no-facebook" not in args:
        items += collect_facebook_google(cfg)   # source principale
    if "--with-jiji" in args:
        items += collect_jiji(cfg)
    if "--with-coinafrique" in args:
        items += collect_coinafrique(cfg)
    merge_and_save(items)


if __name__ == "__main__":
    main()
