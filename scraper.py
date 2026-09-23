#!/usr/bin/env python3
"""
tennis_lg: High-Fidelity Worldwide Scraper
Strictly extracts verified player entities from /player/ profile links.
Eliminates DOM UI text, doubles, and tournament navigation tags.
"""

import sqlite3
import requests
import re
from datetime import datetime, timezone, timedelta

DB_NAME = "tennis_lg.db"

ESPN_ENDPOINTS = {
    "ATP": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
    "WTA": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

BLACKLIST_TERMS = {
    "click", "detail", "draw", "tournament", "tbd", "bye", "vs", "match",
    "main", "qualification", "qualifying", "order", "schedule"
}

def clean_txt(t):
    if not t:
        return ""
    cleaned = re.sub(r'\b(S|D|\d+|H2H|H|A)\b', '', t)
    return re.sub(r'\s+', ' ', cleaned.replace('\xa0', ' ')).strip()

def classify_circuit(raw_name):
    clean = clean_txt(raw_name)
    nl = clean.lower()

    if any(k in nl for k in ["davis cup", "billie jean", "bjk cup", "hopman", "united cup", "olympic"]):
        tour = "DAVIS_CUP"
    elif "utr" in nl:
        tour = "UTR"
    elif any(k in nl for k in ["challenger", "ch."]):
        tour = "CHALLENGER"
    elif any(k in nl for k in ["wta", "ankara", "porto", "seoul", "sao paulo", "women", "w100", "w75", "w50", "w35", "w15"]):
        tour = "WTA"
    elif any(k in nl for k in ["atp", "grand slam", "masters"]):
        tour = "ATP"
    else:
        tour = "ITF"

    surface = "Clay" if "clay" in nl else ("Grass" if "grass" in nl else "Hard")
    cpi = 28.0 if surface == "Clay" else (45.0 if surface == "Grass" else 38.0)
    return clean, tour, surface, cpi

def extract_player_from_td(td_html):
    """
    Strictly extracts player slug and display name from td.t-name.
    Rejects any non-player anchor tags (e.g., match details or tournament draws).
    """
    if not td_html:
        return None, None

    # Doubles filter
    if "/" in td_html:
        return None, None

    # Must contain a player link: /player/slug/
    m = re.search(r'<a[^>]*href="(/player/([a-z0-9\-]+)/?)"[^>]*>(.*?)</a>', td_html, re.I)
    if not m:
        return None, None

    slug = m.group(2).strip()
    disp = re.sub(r'<[^>]+>', '', m.group(3)).strip()

    # Reject blacklisted UI tokens
    disp_lower = disp.lower()
    if any(b in disp_lower for b in BLACKLIST_TERMS) or len(disp) < 3:
        return None, None

    # Parse full name from URL slug
    parts = slug.split('-')
    if len(parts) >= 2:
        last = parts[0].capitalize()
        first = ' '.join(p.capitalize() for p in parts[1:])
        full_name = f"{first} {last}"
    else:
        full_name = disp

    return disp, full_name

def sync_active_tournaments():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(timezone.utc)
    now_ts = now.strftime("%Y-%m-%d %H:%M:%S")

    # Purge corrupted fixtures
    c.execute("""
        DELETE FROM Daily_Card 
        WHERE status = 'SCHEDULED' 
           OR player_a_id LIKE '%CLICK%' OR player_b_id LIKE '%CLICK%'
           OR player_a_id LIKE '%DRAW%' OR player_b_id LIKE '%DRAW%';
    """)

    tournaments_discovered = {}
    players_discovered = set()
    matches_queued = 0

    # 1. Main-Tour Scoreboards (ESPN API)
    for tour_code, url in ESPN_ENDPOINTS.items():
        try:
            res = requests.get(url, headers=HEADERS, timeout=8)
            if res.status_code == 200:
                for ev in res.json().get("events", []):
                    t_name, tour_type, surface, cpi = classify_circuit(ev.get("name", f"{tour_code} Championship"))
                    t_id = f"{tour_type}_{ev.get('id', 'EV')}"
                    tournaments_discovered[t_id] = (t_id, t_name, tour_type, surface, cpi, 0, 15.0, 3)

                    for comp in ev.get("competitions", []):
                        comps = comp.get("competitors", [])
                        if len(comps) == 2:
                            p_a = clean_txt(comps[0].get("athlete", {}).get("displayName", ""))
                            p_b = clean_txt(comps[1].get("athlete", {}).get("displayName", ""))
                            if not p_a or not p_b or "/" in p_a or "/" in p_b or "TBD" in p_a or len(p_a) < 3 or len(p_b) < 3:
                                continue

                            p_a_id = f"PRO_{p_a.replace(' ', '_').upper()}"
                            p_b_id = f"PRO_{p_b.replace(' ', '_').upper()}"
                            m_id = f"MATCH_{tour_code}_{comp.get('id')}"

                            players_discovered.add((p_a_id, p_a, tour_type))
                            players_discovered.add((p_b_id, p_b, tour_type))

                            c.execute("""
                                INSERT OR REPLACE INTO Daily_Card (match_id, tournament_id, tour, player_a_id, player_b_id, temp_c, humidity_pct, status, created_at)
                                VALUES (?, ?, ?, ?, ?, 24.0, 50.0, 'SCHEDULED', ?);
                            """, (m_id, t_id, tour_type, p_a_id, p_b_id, now_ts))
                            matches_queued += 1
        except Exception as e:
            print(f"[ESPN ERROR] {e}")

    # 2. Multi-Tour Worldwide Feeds (TennisExplorer)
    for day_offset in [0, 1, 2]:
        target_date = now + timedelta(days=day_offset)
        te_url = f"https://www.tennisexplorer.com/matches/?type=all&year={target_date.year}&month={target_date.month}&day={target_date.day}"
        try:
            res = requests.get(te_url, headers=HEADERS, timeout=12)
            if res.status_code == 200:
                html = res.text
                tables = re.findall(r'<table[^>]*class="result"[^>]*>(.*?)</table>', html, re.DOTALL)
                for table in tables:
                    head_match = re.search(r'<tr[^>]*class="head[^"]*"[^>]*>(.*?)</tr>', table, re.DOTALL)
                    if not head_match:
                        continue

                    # Extract title from inner link or header text
                    head_content = head_match.group(1)
                    link_m = re.search(r'<a[^>]*href="[^"]*"[^>]*>(.*?)</a>', head_content)
                    raw_t_name = clean_txt(re.sub(r'<[^>]+>', ' ', link_m.group(1) if link_m else head_content))
                    if not raw_t_name or len(raw_t_name) < 3 or "vs" in raw_t_name.lower():
                        continue

                    t_name, tour_type, surface, cpi = classify_circuit(raw_t_name)
                    t_slug = re.sub(r'[^A-Z0-9_]', '', t_name.upper().replace(' ', '_'))[:30]
                    t_id = f"{tour_type}_{t_slug}"
                    tournaments_discovered[t_id] = (t_id, t_name, tour_type, surface, cpi, 0, 15.0, 3)

                    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL)
                    i = 0
                    while i < len(rows) - 1:
                        r1, r2 = rows[i], rows[i+1]
                        td1_m = re.search(r'<td[^>]*class="t-name"[^>]*>(.*?)</td>', r1, re.DOTALL)
                        td2_m = re.search(r'<td[^>]*class="t-name"[^>]*>(.*?)</td>', r2, re.DOTALL)

                        if td1_m and td2_m:
                            d1, f1 = extract_player_from_td(td1_m.group(1))
                            d2, f2 = extract_player_from_td(td2_m.group(1))

                            if d1 and d2 and f1 and f2 and d1.lower() != d2.lower():
                                p_a_id = f"PRO_{f1.replace(' ', '_').upper()}"
                                p_b_id = f"PRO_{f2.replace(' ', '_').upper()}"
                                m_id = f"MATCH_{t_slug[:6]}_{p_a_id[:6]}_{p_b_id[:6]}"

                                players_discovered.add((p_a_id, f1, tour_type))
                                players_discovered.add((p_b_id, f2, tour_type))

                                c.execute("""
                                    INSERT OR REPLACE INTO Daily_Card (match_id, tournament_id, tour, player_a_id, player_b_id, temp_c, humidity_pct, status, created_at)
                                    VALUES (?, ?, ?, ?, ?, 24.0, 50.0, 'SCHEDULED', ?);
                                """, (m_id, t_id, tour_type, p_a_id, p_b_id, now_ts))
                                matches_queued += 1
                                i += 2
                                continue
                        i += 1
        except Exception as e:
            print(f"[CALENDAR ERROR] {e}")

    # 3. Commit Verified Tournaments and Base Records
    for t_data in tournaments_discovered.values():
        c.execute("""
            INSERT OR REPLACE INTO Tournaments 
            (id, name, tour, surface, cpi, is_indoor, elevation_m, best_of)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, t_data)

    for p_id, p_name, p_tour in players_discovered:
        c.execute("""
            INSERT OR IGNORE INTO Players 
            (id, name, tour, handedness, backhand, serve_p, return_q, bp_save, bp_convert, topspin_rpm, sample_points, fatigue_hours_72h, rest_days, updated_at)
            VALUES (?, ?, ?, 'R', '2H', 0.640, 0.360, 0.600, 0.400, 2700, 100, 0.0, 3, ?);
        """, (p_id, p_name, p_tour, now_ts))

    conn.commit()
    conn.close()
    print(f"[SUCCESS] Scraped {len(tournaments_discovered)} tournaments and {matches_queued} strictly validated matches.")

if __name__ == "__main__":
    sync_active_tournaments()
