#!/usr/bin/env python3
"""
tennis_lg: Unblocked Live Multi-Tour Ingestion Engine
Ingests ATP, WTA, ATP Challenger, and ITF matches without getting blocked by sportsbook WAFs.
- Source 1: ESPN Scoreboard API (ATP & WTA)
- Source 2: TennisExplorer Live Schedule (ATP Challengers, ITF M15/M25/W50/W75, Davis Cup)
"""

import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

DB_NAME = "tennis_lg.db"

ESPN_ENDPOINTS = {
    "ATP": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
    "WTA": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def sync_live_slate():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # 1. Purge previous scheduled queue
    c.execute("DELETE FROM Daily_Card WHERE status = 'SCHEDULED';")
    
    matches_queued = 0

    # 2. Ingest ATP & WTA from ESPN API
    for tour, url in ESPN_ENDPOINTS.items():
        try:
            print(f"[SCRAPER] Querying official {tour} scoreboard...")
            res = requests.get(url, headers=HEADERS, timeout=8)
            if res.status_code == 200:
                events = res.json().get("events", [])
                for ev in events:
                    t_name = ev.get("name", f"{tour} Tour")
                    t_id = f"{tour}_{ev.get('id', 'EVENT')}"
                    
                    c.execute("""
                        INSERT OR REPLACE INTO Tournaments (id, name, tour, surface, cpi, is_indoor, elevation_m, best_of)
                        VALUES (?, ?, ?, 'Hard', 38.0, 0, 15.0, 3);
                    """, (t_id, t_name, tour))

                    for comp in ev.get("competitions", []):
                        comps = comp.get("competitors", [])
                        if len(comps) == 2:
                            p_a = comps[0].get("athlete", {}).get("displayName", "").strip()
                            p_b = comps[1].get("athlete", {}).get("displayName", "").strip()
                            if "/" in p_a or "TBD" in p_a or not p_a or not p_b:
                                continue
                            
                            p_a_id = f"{tour}_{p_a.replace(' ', '_').upper()}"
                            p_b_id = f"{tour}_{p_b.replace(' ', '_').upper()}"
                            m_id = f"MATCH_{tour}_{comp.get('id')}"

                            for pid, pname in [(p_a_id, p_a), (p_b_id, p_b)]:
                                c.execute("""
                                    INSERT OR IGNORE INTO Players (id, name, tour, handedness, backhand, serve_p, return_q, bp_save, bp_convert, topspin_rpm, sample_points, fatigue_hours_72h, rest_days, updated_at)
                                    VALUES (?, ?, ?, 'R', '2H', 0.67, 0.38, 0.65, 0.40, 2800, 150, 0.0, 3, ?);
                                """, (pid, pname, tour, now_ts))

                            c.execute("""
                                INSERT OR REPLACE INTO Daily_Card (match_id, tournament_id, tour, player_a_id, player_b_id, temp_c, humidity_pct, status, created_at)
                                VALUES (?, ?, ?, ?, ?, 24.0, 50.0, 'SCHEDULED', ?);
                            """, (m_id, t_id, tour, p_a_id, p_b_id, now_ts))
                            matches_queued += 1
        except Exception as e:
            print(f"[SCRAPER ERROR] {tour} ingestion failure: {e}")

    # 3. Ingest ATP Challengers & ITF Circuits from TennisExplorer
    try:
        print("[SCRAPER] Ingesting Challenger & ITF circuit schedules from TennisExplorer...")
        te_url = "https://www.tennisexplorer.com/matches/"
        res = requests.get(te_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            tables = soup.find_all("table", class_="result")
            for table in tables:
                current_tour_name = "World Tennis Tour"
                tour_type = "ITF"

                # Check tournament header
                header = table.find("tr", class_="head")
                if header:
                    current_tour_name = header.get_text(strip=True)
                    if "challenger" in current_tour_name.lower():
                        tour_type = "ATP"
                    elif "wta" in current_tour_name.lower():
                        tour_type = "WTA"
                    else:
                        tour_type = "ITF"

                t_id = f"{tour_type}_{current_tour_name[:20].replace(' ', '_').upper()}"
                c.execute("""
                    INSERT OR REPLACE INTO Tournaments (id, name, tour, surface, cpi, is_indoor, elevation_m, best_of)
                    VALUES (?, ?, ?, 'Hard', 36.0, 0, 15.0, 3);
                """, (t_id, current_tour_name, tour_type))

                # Extract player names from rows
                player_links = table.find_all("td", class_="t-name")
                for i in range(0, len(player_links) - 1, 2):
                    p_a_name = player_links[i].get_text(strip=True)
                    p_b_name = player_links[i+1].get_text(strip=True)
                    
                    if not p_a_name or not p_b_name or "/" in p_a_name:
                        continue

                    p_a_id = f"{tour_type}_{p_a_name.replace(' ', '_').upper()}"
                    p_b_id = f"{tour_type}_{p_b_name.replace(' ', '_').upper()}"
                    m_id = f"MATCH_TE_{p_a_id[:8]}_{p_b_id[:8]}"

                    for pid, pname in [(p_a_id, p_a_name), (p_b_id, p_b_name)]:
                        c.execute("""
                            INSERT OR IGNORE INTO Players (id, name, tour, handedness, backhand, serve_p, return_q, bp_save, bp_convert, topspin_rpm, sample_points, fatigue_hours_72h, rest_days, updated_at)
                            VALUES (?, ?, ?, 'R', '2H', 0.64, 0.37, 0.61, 0.39, 2600, 100, 0.0, 3, ?);
                        """, (pid, pname, tour_type, now_ts))

                    c.execute("""
                        INSERT OR REPLACE INTO Daily_Card (match_id, tournament_id, tour, player_a_id, player_b_id, temp_c, humidity_pct, status, created_at)
                        VALUES (?, ?, ?, ?, ?, 24.0, 50.0, 'SCHEDULED', ?);
                    """, (m_id, t_id, tour_type, p_a_id, p_b_id, now_ts))
                    matches_queued += 1

    except Exception as e:
        print(f"[SCRAPER ERROR] TennisExplorer ingestion failure: {e}")

    conn.commit()
    conn.close()
    print(f"[SCRAPER SUCCESS] Queued {matches_queued} active matches across circuits.")

if __name__ == "__main__":
    sync_live_slate()
