#!/usr/bin/env python3
"""
tennis_lg: Precise Multi-Tour Ingestion Engine
Strictly validates player profiles against /player/ links.
Completely isolates tournament headers and filters doubles.
"""

import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import re

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
    return re.sub(r'\s+', ' ', t.replace('\xa0', ' ')).strip()

def sync_active_tournaments():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Clear outdated fixtures and faulty predictions
    c.execute("DELETE FROM Daily_Card WHERE status = 'SCHEDULED';")
    c.execute("DELETE FROM Model_Forecasts;")

    tournaments_discovered = {}
    players_discovered = set()
    matches_queued = 0

    # 1. ESPN API (ATP & WTA Main Draws)
    for tour, url in ESPN_ENDPOINTS.items():
        try:
            res = requests.get(url, headers=HEADERS, timeout=8)
            if res.status_code == 200:
                for ev in res.json().get("events", []):
                    t_name = clean_txt(ev.get("name", f"{tour} Championship"))
                    t_id = f"{tour}_{ev.get('id', 'EV')}"
                    surface = "Clay" if "clay" in t_name.lower() else ("Grass" if "grass" in t_name.lower() else "Hard")
                    cpi = 28.0 if surface == "Clay" else 38.0
                    tournaments_discovered[t_id] = (t_id, t_name, tour, surface, cpi, 0, 15.0, 3)

                    for comp in ev.get("competitions", []):
                        comps = comp.get("competitors", [])
                        if len(comps) == 2:
                            p_a = clean_txt(comps[0].get("athlete", {}).get("displayName", ""))
                            p_b = clean_txt(comps[1].get("athlete", {}).get("displayName", ""))
                            if not p_a or not p_b or "/" in p_a or "/" in p_b or "TBD" in p_a or len(p_a) < 3 or len(p_b) < 3:
                                continue

                            p_a_id = f"PRO_{p_a.replace(' ', '_').upper()}"
                            p_b_id = f"PRO_{p_b.replace(' ', '_').upper()}"
                            m_id = f"MATCH_{tour}_{comp.get('id')}"

                            players_discovered.add((p_a_id, p_a, tour))
                            players_discovered.add((p_b_id, p_b, tour))

                            c.execute("""
                                INSERT OR REPLACE INTO Daily_Card (match_id, tournament_id, tour, player_a_id, player_b_id, temp_c, humidity_pct, status, created_at)
                                VALUES (?, ?, ?, ?, ?, 24.0, 50.0, 'SCHEDULED', ?);
                            """, (m_id, t_id, tour, p_a_id, p_b_id, now_ts))
                            matches_queued += 1
        except Exception as e:
            print(f"[ESPN ERROR] {e}")

    # 2. TennisExplorer (Challengers, Davis Cup, ITF Qualifiers)
    try:
        res = requests.get("https://www.tennisexplorer.com/matches/", headers=HEADERS, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for table in soup.find_all("table", class_="result"):
                head = table.find("tr", class_="head")
                if not head:
                    continue

                raw_t_name = clean_txt(head.get_text(" ", strip=True))
                if not raw_t_name or len(raw_t_name) < 3:
                    continue

                nl = raw_t_name.lower()
                tour_type = "CHALLENGER" if "challenger" in nl else ("DAVIS_CUP" if "davis" in nl else ("WTA" if "wta" in nl else "ITF"))
                surface = "Clay" if "clay" in nl else ("Grass" if "grass" in nl else "Hard")
                cpi = 28.0 if surface == "Clay" else 38.0

                t_slug = re.sub(r'[^A-Z0-9_]', '', raw_t_name.upper().replace(' ', '_'))[:30]
                t_id = f"{tour_type}_{t_slug}"
                tournaments_discovered[t_id] = (t_id, raw_t_name, tour_type, surface, cpi, 0, 15.0, 3)

                current_pair = []
                for row in table.find_all("tr"):
                    if "head" in row.get("class", []):
                        continue

                    # Strictly match athlete profile links; ignore tournament and doubles rows
                    p_link = row.find("a", href=re.compile(r"^/player/[^/]+/?$"))
                    if p_link:
                        td_tname = row.find("td", class_="t-name")
                        if td_tname and "/" in td_tname.get_text():
                            current_pair = []  # Drop doubles
                            continue

                        p_name = clean_txt(p_link.get_text(strip=True))
                        if p_name and len(p_name) >= 3:
                            current_pair.append(p_name)
                            if len(current_pair) == 2:
                                p_a, p_b = current_pair
                                current_pair = []

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
    except Exception as e:
        print(f"[TE ERROR] {e}")

    for t_data in tournaments_discovered.values():
        c.execute("""
            INSERT OR REPLACE INTO Tournaments (id, name, tour, surface, cpi, is_indoor, elevation_m, best_of)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, t_data)

    for p_id, p_name, p_tour in players_discovered:
        c.execute("""
            INSERT OR IGNORE INTO Players (id, name, tour, handedness, backhand, serve_p, return_q, bp_save, bp_convert, topspin_rpm, sample_points, fatigue_hours_72h, rest_days, updated_at)
            VALUES (?, ?, ?, 'R', '2H', 0.640, 0.360, 0.600, 0.400, 2700, 100, 0.0, 3, ?);
        """, (p_id, p_name, p_tour, now_ts))

    conn.commit()
    conn.close()
    print(f"[SUCCESS] Cataloged {len(tournaments_discovered)} tournaments and queued {matches_queued} clean singles matches.")

if __name__ == "__main__":
    sync_active_tournaments()
