#!/usr/bin/env python3
"""
tennis_lg: Global Ingestion Engine with Tournament Name Sanitization
Strips website navigation tags (S 1 2 3 4 5, H2H, H A) from event titles.
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

def clean_txt(t):
    if not t:
        return ""
    # Strip site navigation tokens: S, D, numbers, H2H, H, A
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
    elif any(k in nl for k in ["itf", "m25", "m15", "futures"]):
        tour = "ITF"
    else:
        tour = "ITF"

    surface = "Clay" if "clay" in nl else ("Grass" if "grass" in nl else "Hard")
    cpi = 28.0 if surface == "Clay" else (45.0 if surface == "Grass" else 38.0)
    return clean, tour, surface, cpi

def sync_worldwide_slate():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(timezone.utc)
    now_ts = now.strftime("%Y-%m-%d %H:%M:%S")

    c.execute("DELETE FROM Daily_Card WHERE status = 'SCHEDULED';")

    tournaments_discovered = {}
    players_discovered = set()
    matches_queued = 0

    # 1. ESPN Scoreboards
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
            print(f"[ESPN API] {e}")

    # 2. TennisExplorer Multi-Day Feed
    for day_offset in [0, 1, 2]:
        target_date = now + timedelta(days=day_offset)
        te_url = f"https://www.tennisexplorer.com/matches/?type=all&year={target_date.year}&month={target_date.month}&day={target_date.day}"
        try:
            res = requests.get(te_url, headers=HEADERS, timeout=12)
            if res.status_code == 200:
                html = res.text
                tables = re.findall(r'<table[^>]*class="result"[^>]*>(.*?)</table>', html, re.DOTALL)
                for table in tables:
                    head_match = re.search(r'<tr[^>]*class="head"[^>]*>(.*?)</tr>', table, re.DOTALL)
                    raw_t_name = clean_txt(re.sub(r'<[^>]+>', ' ', head_match.group(1))) if head_match else "World Tour"
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
                        if 't-name' not in r1 or 't-name' not in r2:
                            i += 1
                            continue

                        p1_m = re.search(r'class="t-name"[^>]*>.*?<a[^>]*>(.*?)</a>', r1, re.DOTALL)
                        p2_m = re.search(r'class="t-name"[^>]*>.*?<a[^>]*>(.*?)</a>', r2, re.DOTALL)
                        if not p1_m or not p2_m:
                            i += 1
                            continue

                        p1_title = re.search(r'title="([^"]+)"', r1)
                        p2_title = re.search(r'title="([^"]+)"', r2)
                        p_a = clean_txt(p1_title.group(1)) if p1_title else clean_txt(re.sub(r'<[^>]+>', '', p1_m.group(1)))
                        p_b = clean_txt(p2_title.group(1)) if p2_title else clean_txt(re.sub(r'<[^>]+>', '', p2_m.group(1)))

                        if not p_a or not p_b or "/" in p_a or "/" in p_b or len(p_a) < 3 or len(p_b) < 3:
                            i += 2
                            continue

                        p_a_id = f"PRO_{p_a.replace(' ', '_').upper()}"
                        p_b_id = f"PRO_{p_b.replace(' ', '_').upper()}"
                        m_id = f"MATCH_{t_slug[:6]}_{p_a_id[:6]}_{p_b_id[:6]}"

                        players_discovered.add((p_a_id, p_a, tour_type))
                        players_discovered.add((p_b_id, p_b, tour_type))

                        c.execute("""
                            INSERT OR REPLACE INTO Daily_Card (match_id, tournament_id, tour, player_a_id, player_b_id, temp_c, humidity_pct, status, created_at)
                            VALUES (?, ?, ?, ?, ?, 24.0, 50.0, 'SCHEDULED', ?);
                        """, (m_id, t_id, tour_type, p_a_id, p_b_id, now_ts))
                        matches_queued += 1
                        i += 2
        except Exception as e:
            print(f"[CALENDAR ERROR] {e}")

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
    print(f"[SUCCESS] Ingested {len(tournaments_discovered)} clean tournaments and {matches_queued} matchups.")

if __name__ == "__main__":
    sync_worldwide_slate()
