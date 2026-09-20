#!/usr/bin/env python3
"""
tennis_lg: Live Multi-Tour Ingestion Engine
Fetches live and upcoming matches across ATP, WTA, ATP Challenger, Davis Cup, and ITF.
"""

import sqlite3
import requests
from datetime import datetime, timezone

DB_NAME = "tennis_lg.db"

# Open live tennis scoreboard API
LIVE_ENDPOINT = "https://api.sofascore.com/api/v1/sport/tennis/events/live"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def sync_active_slate():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    print("[SCRAPER] Fetching active multi-tour tennis slate...")
    try:
        res = requests.get(LIVE_ENDPOINT, headers=HEADERS, timeout=12)
        if res.status_code != 200:
            print(f"[SCRAPER ERROR] API returned status {res.status_code}")
            return
            
        data = res.json()
        events = data.get("events", [])
        
        # Purge stale scheduled fixtures
        c.execute("DELETE FROM Daily_Card WHERE status = 'SCHEDULED';")
        
        count = 0
        for ev in events:
            # Filter out doubles matches
            if "/" in ev.get("homeTeam", {}).get("name", "") or "/" in ev.get("awayTeam", {}).get("name", ""):
                continue

            player_a = ev.get("homeTeam", {}).get("name", "").strip()
            player_b = ev.get("awayTeam", {}).get("name", "").strip()
            if not player_a or not player_b:
                continue

            tournament_info = ev.get("tournament", {})
            comp_name = tournament_info.get("name", "World Tennis Tour")
            category = tournament_info.get("category", {}).get("name", "")

            # Classify tour
            if "ITF" in comp_name or "ITF" in category:
                tour = "ITF"
            elif "Challenger" in comp_name or "Challenger" in category:
                tour = "ATP"
            elif "WTA" in category or "WTA" in comp_name:
                tour = "WTA"
            elif "Davis" in comp_name or "Davis" in category:
                tour = "DAVIS_CUP"
            else:
                tour = "ATP"

            t_id = f"{tour}_{tournament_info.get('id', 'TOUR')}"
            match_id = f"MATCH_{ev.get('id')}"

            p_a_id = f"{tour}_{player_a.replace(' ', '_').upper()}"
            p_b_id = f"{tour}_{player_b.replace(' ', '_').upper()}"

            # Register tournament
            c.execute("""
                INSERT OR REPLACE INTO Tournaments (id, name, tour, surface, cpi, is_indoor, elevation_m, best_of)
                VALUES (?, ?, ?, 'Hard', 36.0, 0, 15.0, 3);
            """, (t_id, comp_name, tour))

            # Register player baselines if not already tracked
            for pid, pname in [(p_a_id, player_a), (p_b_id, player_b)]:
                c.execute("""
                    INSERT OR IGNORE INTO Players (id, name, tour, handedness, backhand, serve_p, return_q, bp_save, bp_convert, topspin_rpm, sample_points, fatigue_hours_72h, rest_days, updated_at)
                    VALUES (?, ?, ?, 'R', '2H', 0.650, 0.380, 0.620, 0.400, 2800, 120, 0.0, 3, ?);
                """, (pid, pname, tour, now_ts))

            # Queue active match
            c.execute("""
                INSERT OR REPLACE INTO Daily_Card (match_id, tournament_id, tour, player_a_id, player_b_id, temp_c, humidity_pct, status, created_at)
                VALUES (?, ?, ?, ?, ?, 24.0, 50.0, 'SCHEDULED', ?);
            """, (match_id, t_id, tour, p_a_id, p_b_id, now_ts))
            count += 1

        conn.commit()
        print(f"[SCRAPER SUCCESS] Queued {count} live matches across ATP, WTA, Challenger, and ITF.")

    except Exception as e:
        print(f"[SCRAPER FAILURE] {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    sync_active_slate()
