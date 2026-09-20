#!/usr/bin/env python3
"""
tennis_lg: Automated Factual Post-Mortem Auditor & Parameter Learner
Scrapes completed matches, computes Brier scores, updates beta weights,
and logs every parameter adaptation to the Learning_Log ledger.
"""

import sqlite3
import requests
from datetime import datetime

DB_NAME = "tennis_lg.db"
ENDPOINTS = {
    "ATP": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
    "WTA": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"
}

def init_learning_schema():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS Learning_Log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT,
        parameter TEXT,
        old_val REAL,
        new_val REAL,
        delta REAL,
        reason TEXT,
        updated_at TEXT
    );
    """)
    conn.commit()
    conn.close()

def log_adaptation(conn, match_id, param, old_val, new_val, reason):
    delta = round(new_val - old_val, 4)
    conn.execute("""
        INSERT INTO Learning_Log (match_id, parameter, old_val, new_val, delta, reason, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (match_id, param, round(old_val, 4), round(new_val, 4), delta, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

def execute_factual_post_mortem(match_id, actual_winner, actual_total, actual_spread):
    init_learning_schema()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM Model_Forecasts WHERE match_id = ?;", (match_id,))
    f = c.fetchone()
    if not f:
        conn.close()
        return

    _, tour_id, tour, p_a, p_b, prob_a, prob_b, _, _, proj_tot, proj_spr, v_phys, v_therm, v_bio, v_var, _, _ = f
    
    # Simulation-free arithmetic audit
    y_a = 1.0 if actual_winner == p_a else 0.0
    brier = round((prob_a - y_a) ** 2, 4)
    error_margin = y_a - prob_a 
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Archive forecast audit
    c.execute("""
        INSERT OR REPLACE INTO Historical_Forecasts VALUES (?,?,?,?,?,?,?,?,?,?,?,?);
    """, (match_id, tour_id, tour, p_a, p_b, prob_a, prob_b, actual_winner, actual_total, actual_spread, brier, now_ts))
    
    # 1. Learn & Adjust Feature Betas via Gradient Descent
    lr = 0.05
    c.execute("SELECT vector_name, beta_weight FROM Feature_Correlations;")
    current_betas = {row[0]: row[1] for row in c.fetchall()}
    
    vector_map = {
        'v_physics': v_phys,
        'v_thermo': v_therm,
        'v_bio': v_bio,
        'v_variance': v_var
    }
    
    for v_name, v_val in vector_map.items():
        old_b = current_betas.get(v_name, 1.0)
        grad = v_val * error_margin * lr
        new_b = max(0.5, min(1.5, old_b + grad))
        
        c.execute("UPDATE Feature_Correlations SET beta_weight = ?, updated_at = ? WHERE vector_name = ?;", 
                  (round(new_b, 4), now_ts, v_name))
        log_adaptation(conn, match_id, f"Beta: {v_name}", old_b, new_b, f"Audit error {error_margin:+.3f} on {match_id}")

    # 2. Learn & Adjust Individual Player Ratings via EWMA
    # Retrieve player A & B current profiles
    for p_name, is_winner in [(p_a, actual_winner == p_a), (p_b, actual_winner == p_b)]:
        c.execute("SELECT serve_p, return_q, sample_points FROM Players WHERE name = ?;", (p_name,))
        p_row = c.fetchone()
        if p_row:
            old_serve, old_ret, samples = p_row
            # Dynamic learning rate shrinks as historical match samples increase
            alpha = max(0.02, 1.0 / (math.sqrt(samples) if 'math' in globals() else 5.0))
            
            # Winner adjusted upward; loser adjusted downward
            target_serve_shift = (0.02 if is_winner else -0.015)
            new_serve = max(0.45, min(0.85, old_serve + (target_serve_shift * alpha)))
            new_samples = samples + 120
            
            c.execute("UPDATE Players SET serve_p = ?, sample_points = ?, updated_at = ? WHERE name = ?;",
                      (round(new_serve, 4), new_samples, now_ts, p_name))
            log_adaptation(conn, match_id, f"Rating: {p_name} (Serve)", old_serve, new_serve, f"Outcome shift ({'Won' if is_winner else 'Lost'})")

    c.execute("UPDATE Daily_Card SET status = 'FINAL' WHERE match_id = ?;", (match_id,))
    conn.commit()
    conn.close()
    print(f"[LEARNING ENGINE] Audited {match_id} | Winner: {actual_winner} | Parameter drift recorded.")

def audit_completed_matches():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT match_id, player_a, player_b FROM Model_Forecasts;")
    active_forecasts = {row[0]: (row[1], row[2]) for row in c.fetchall()}
    conn.close()

    if not active_forecasts:
        return

    for tour, url in ENDPOINTS.items():
        try:
            res = requests.get(url, timeout=10)
            if res.status_code != 200:
                continue
            for event in res.json().get("events", []):
                for comp in event.get("competitions", []):
                    m_id = f"MATCH_{comp.get('id')}"
                    if comp.get("status", {}).get("type", {}).get("completed", False) and m_id in active_forecasts:
                        competitors = comp.get("competitors", [])
                        if len(competitors) == 2:
                            w_data = next((c for c in competitors if c.get("winner") is True), None)
                            if not w_data:
                                continue
                            winner_name = w_data.get("athlete", {}).get("displayName")
                            lines_a = [int(x.get("value", 0)) for x in competitors[0].get("linescores", []) if "value" in x]
                            lines_b = [int(x.get("value", 0)) for x in competitors[1].get("linescores", []) if "value" in x]
                            tot_games = sum(lines_a) + sum(lines_b)
                            game_spread = sum(lines_a) - sum(lines_b)
                            execute_factual_post_mortem(m_id, winner_name, tot_games, game_spread)
        except Exception as e:
            print(f"[AUDITOR ERROR] {tour}: {e}")

if __name__ == "__main__":
    audit_completed_matches()
