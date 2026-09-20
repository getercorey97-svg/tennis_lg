#!/usr/bin/env python3
"""
tennis_lg: Live Slate Data Ingestion Pipeline
Fetches today's live ATP and WTA schedule from ESPN's public endpoints.
"""

import sqlite3
import requests
from datetime import datetime

DB_NAME = "tennis_lg.db"

ENDPOINTS = {
    "ATP": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
    "WTA": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"
}

def fetch_espn_slate():
    matches = []
    players = {}
    tournaments = {}

    for tour, url in ENDPOINTS.items():
        try:
            print(f"[SCRAPER] Fetching live {tour} slate from ESPN...")
            res = requests.get(url, timeout=10)
            if res.status_code != 200:
                continue
                
            data = res.json()
            events = data.get("events", [])
            
            for event in events:
                # Extract Tournament Info
                season = event.get("season", {})
                t_name = event.get("name", "Unknown Tournament")
                t_id = f"{tour}_{season.get('year', '2026')}_{event.get('id')}"
                
                # Default surface to Hard if not specified, 3-set matches
                tournaments[t_id] = (t_id, t_name, tour, "Hard", 35.0, 0, 10.0, 3)

                competitions = event.get("competitions", [])
                for comp in competitions:
                    match_id = f"MATCH_{comp.get('id')}"
                    competitors = comp.get("competitors", [])
                    
                    if len(competitors) == 2:
                        p_a_data = competitors[0]
                        p_b_data = competitors[1]
                        
                        p_a_name = p_a_data.get("athlete", {}).get("displayName", "TBD")
                        p_b_name = p_b_data.get("athlete", {}).get("displayName", "TBD")
                        
                        # Skip doubles or incomplete data
                        if "/" in p_a_name or "TBD" in p_a_name:
                            continue
                            
                        p_a_id = f"{tour}_{p_a_name.replace(' ', '').upper()}"
                        p_b_id = f"{tour}_{p_b_name.replace(' ', '').upper()}"
                        
                        # Generate baseline player stats (will be calibrated by post-mortem EWMA)
                        serve_baseline = 0.65 if tour == "ATP" else 0.58
                        ret_baseline = 0.35 if tour == "ATP" else 0.42
                        
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        if p_a_id not in players:
                            players[p_a_id] = (p_a_id, p_a_name, tour, "R", "2H", serve_baseline, ret_baseline, 0.65, 0.40, 2700, 10, 0.0, 3, now)
                        if p_b_id not in players:
                            players[p_b_id] = (p_b_id, p_b_name, tour, "R", "2H", serve_baseline, ret_baseline, 0.65, 0.40, 2700, 10, 0.0, 3, now)
                        
                        # Estimate temp/humidity baselines
                        matches.append((match_id, t_id, tour, p_a_id, p_b_id, 25.0, 50.0, "SCHEDULED", now))
                        
        except Exception as e:
            print(f"[SCRAPER ERROR] Failed to parse {tour} feed: {e}")
            
    return tournaments, players, matches

def inject_to_database(tournaments, players, matches):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL;")
    c = conn.cursor()

    # 1. Update Tournaments
    for t_id, t_data in tournaments.items():
        c.execute("""
            INSERT OR IGNORE INTO Tournaments 
            (id, name, tour, surface, cpi, is_indoor, elevation_m, best_of)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, t_data)

    # 2. Update Players (Only insert if they don't exist to prevent overwriting learned EWMA ratings)
    for p_id, p_data in players.items():
        c.execute("""
            INSERT OR IGNORE INTO Players 
            (id, name, tour, handedness, backhand, serve_p, return_q, bp_save, bp_convert, topspin_rpm, sample_points, fatigue_hours_72h, rest_days, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, p_data)

    # 3. Queue Daily Card
    # First, clear old scheduled matches from previous days
    c.execute("DELETE FROM Daily_Card WHERE status = 'SCHEDULED'")
    
    match_count = 0
    for m in matches:
        c.execute("""
            INSERT OR REPLACE INTO Daily_Card 
            (match_id, tournament_id, tour, player_a_id, player_b_id, temp_c, humidity_pct, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, m)
        match_count += 1

    conn.commit()
    conn.close()
    print(f"[SUCCESS] Scraped and ingested {match_count} real live matches into {DB_NAME}.")

if __name__ == "__main__":
    t_dict, p_dict, m_list = fetch_espn_slate()
    if m_list:
        inject_to_database(t_dict, p_dict, m_list)
    else:
        print("[SCRAPER] No live matches found on the ESPN slate today.")
