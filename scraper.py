#!/usr/bin/env python3
"""
tennis_lg: Real-Time Tournament & Player Roster Ingestion Engine
Discovers all ongoing tournaments (ATP, WTA, Challenger, ITF, Davis Cup)
and retrieves every player competing in active draws.
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

def clean_name(name: str) -> str:
    return re.sub(r'\s+', ' ', name.replace('\xa0', ' ')).strip()

def sync_active_tournaments_and_rosters():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Clear out previous scheduled fixtures
    c.execute("DELETE FROM Daily_Card WHERE status = 'SCHEDULED';")

    tournaments_discovered = {}
    players_discovered = set()
    matches_queued = 0

    # 1. Ingest Main-Tour Tournaments & Players (ESPN API)
    for tour, url in ESPN_ENDPOINTS.items():
        try:
            print(f"[SCRAPER] Scanning active {tour} tournaments on ESPN...")
            res = requests.get(url, headers=HEADERS, timeout=8)
            if res.status_code == 200:
                events = res.json().get("events", [])
                for ev in events:
                    t_name = clean_name(ev.get("name", f"{tour} Championship"))
                    t_id = f"{tour}_{ev.get('id', 'EVENT')}"
                    
                    surface = "Clay" if "clay" in t_name.lower() else ("Grass" if "grass" in t_name.lower() else "Hard")
                    cpi = 28.0 if surface == "Clay" else (45.0 if surface == "Grass" else 38.0)

                    tournaments_discovered[t_id] = (t_id, t_name, tour, surface, cpi, 0, 15.0, 3)

                    for comp in ev.get("competitions", []):
                        comps = comp.get("competitors", [])
                        if len(comps) == 2:
                            p_a = clean_name(comps[0].get("athlete", {}).get("displayName", ""))
                            p_b = clean_name(comps[1].get("athlete", {}).get("displayName", ""))
                            
                            if "/" in p_a or "/" in p_b or "TBD" in p_a or not p_a or not p_b:
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
            print(f"[SCRAPER ERROR] {tour} ingestion failure: {e}")

    # 2. Ingest Ongoing ATP Challengers, ITF Circuits, and Davis Cup (TennisExplorer)
    try:
        print("[SCRAPER] Scanning ongoing Challengers and ITF circuit tournaments...")
        te_url = "https://www.tennisexplorer.com/matches/"
        res = requests.get(te_url, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            tables = soup.find_all("table", class_="result")

            for table in tables:
                header = table.find("tr", class_="head")
                if not header:
                    continue

                raw_t_name = clean_name(header.get_text(" ", strip=True))
                if not raw_t_name:
                    continue

                # Classify tour level
                name_lower = raw_t_name.lower()
                if "challenger" in name_lower:
                    tour_type = "CHALLENGER"
                elif "itf" in name_lower or "futures" in name_lower or "m15" in name_lower or "w50" in name_lower or "w75" in name_lower:
                    tour_type = "ITF"
                elif "wta" in name_lower:
                    tour_type = "WTA"
                elif "davis" in name_lower:
                    tour_type = "DAVIS_CUP"
                else:
                    tour_type = "ATP"

                surface = "Clay" if "clay" in name_lower else ("Grass" if "grass" in name_lower else "Hard")
                cpi = 28.0 if surface == "Clay" else (45.0 if surface == "Grass" else 36.0)

                t_slug = re.sub(r'[^A-Z0-9_]', '', raw_t_name.upper().replace(' ', '_'))[:25]
                t_id = f"{tour_type}_{t_slug}"

                tournaments_discovered[t_id] = (t_id, raw_t_name, tour_type, surface, cpi, 0, 15.0, 3)

                player_tds = table.find_all("td", class_="t-name")
                for i in range(0, len(player_tds) - 1, 2):
                    p_a = clean_name(player_tds[i].get_text(strip=True))
                    p_b = clean_name(player_tds[i+1].get_text(strip=True))

                    if not p_a or not p_b or "/" in p_a or "/" in p_b:
                        continue

                    p_a_id = f"PRO_{p_a.replace(' ', '_').upper()}"
                    p_b_id = f"PRO_{p_b.replace(' ', '_').upper()}"
                    m_id = f"MATCH_{t_slug[:6]}_{p_a_id[:8]}_{p_b_id[:8]}"

                    players_discovered.add((p_a_id, p_a, tour_type))
                    players_discovered.add((p_b_id, p_b, tour_type))

                    c.execute("""
                        INSERT OR REPLACE INTO Daily_Card (match_id, tournament_id, tour, player_a_id, player_b_id, temp_c, humidity_pct, status, created_at)
                        VALUES (?, ?, ?, ?, ?, 24.0, 50.0, 'SCHEDULED', ?);
                    """, (m_id, t_id, tour_type, p_a_id, p_b_id, now_ts))
                    matches_queued += 1

    except Exception as e:
        print(f"[SCRAPER ERROR] Challenger/ITF retrieval failure: {e}")

    # 3. Commit Tournaments and Players
    for t_data in tournaments_discovered.values():
        c.execute("""
            INSERT OR REPLACE INTO Tournaments 
            (id, name, tour, surface, cpi, is_indoor, elevation_m, best_of)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, t_data)

    # Insert new players; existing calibrated players will not be overwritten
    for p_id, p_name, p_tour in players_discovered:
        c.execute("""
            INSERT OR IGNORE INTO Players 
            (id, name, tour, handedness, backhand, serve_p, return_q, bp_save, bp_convert, topspin_rpm, sample_points, fatigue_hours_72h, rest_days, updated_at)
            VALUES (?, ?, ?, 'R', '2H', 0.640, 0.360, 0.600, 0.400, 2700, 100, 0.0, 3, ?);
        """, (p_id, p_name, p_tour, now_ts))

    conn.commit()
    conn.close()

    print("=======================================================")
    print(f"  [DISCOVERY COMPLETE]")
    print(f"  • Ongoing Tournaments Found : {len(tournaments_discovered)}")
    print(f"  • Competing Players Found   : {len(players_discovered)}")
    print(f"  • Scheduled Matchups Queued : {matches_queued}")
    print("=======================================================")

if __name__ == "__main__":
    sync_active_tournaments_and_rosters()
