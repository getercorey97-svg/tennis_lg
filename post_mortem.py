#!/usr/bin/env python3
"""
tennis_lg: Automated Factual Post-Mortem Auditor
Scrapes completed match results from ESPN, performs simulation-free arithmetic audits,
calculates Brier scores, and adjusts feature correlation weights (beta).
"""

import sqlite3
import requests
from datetime import datetime

DB_NAME = "tennis_lg.db"
ENDPOINTS = {
    "ATP": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
    "WTA": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"
}

def execute_factual_post_mortem(match_id, actual_winner, actual_total, actual_spread):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM Model_Forecasts WHERE match_id = ?;", (match_id,))
    f = c.fetchone()
    if not f:
        conn.close()
        return

    _, _, _, p_a, p_b, prob_a, prob_b, _, _, proj_tot, proj_spr, v_phys, v_therm, v_bio, v_var, _, _ = f
    
    # Strictly simulation-free arithmetic comparison
    y_a = 1.0 if actual_winner == p_a else 0.0
    brier = round((prob_a - y_a) ** 2, 4)
    error_margin = y_a - prob_a 
    
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        INSERT OR REPLACE INTO Historical_Forecasts VALUES (?,?,?,?,?,?,?,?,?,?,?,?);
    """, (match_id, f[1], f[2], p_a, p_b, prob_a, prob_b, actual_winner, actual_total, actual_spread, brier, now_ts))
    
    # Gradient adjustment of feature betas
    lr = 0.05
    c.execute("SELECT vector_name, beta_weight FROM Feature_Correlations;")
    current_betas = {row[0]: row[1] for row in c.fetchall()}
    
    new_betas = {
        'v_physics': max(0.5, min(1.5, current_betas.get('v_physics', 1.0) + (v_phys * error_margin * lr))),
        'v_thermo': max(0.5, min(1.5, current_betas.get('v_thermo', 1.0) + (v_therm * error_margin * lr))),
        'v_bio': max(0.5, min(1.5, current_betas.get('v_bio', 1.0) + (v_bio * error_margin * lr))),
        'v_variance': max(0.5, min(1.5, current_betas.get('v_variance', 1.0) + (v_var * error_margin * lr)))
    }
    
    for v_name, n_beta in new_betas.items():
        c.execute("UPDATE Feature_Correlations SET beta_weight = ?, updated_at = ? WHERE vector_name = ?;", 
                  (round(n_beta, 4), now_ts, v_name))

    c.execute("UPDATE Daily_Card SET status = 'FINAL' WHERE match_id = ?;", (match_id,))
    conn.commit()
    conn.close()
    print(f"[AUDIT COMPLETE] {match_id} | Winner: {actual_winner} | Brier: {brier} | Err: {error_margin:+.3f}")

def audit_completed_matches():
    """Polls public scoreboard for finished matches and triggers audits."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT match_id, player_a, player_b FROM Model_Forecasts;")
    active_forecasts = {row[0]: (row[1], row[2]) for row in c.fetchall()}
    conn.close()

    if not active_forecasts:
        return

    print("[AUDITOR] Checking public scoreboards for completed matches...")
    for tour, url in ENDPOINTS.items():
        try:
            res = requests.get(url, timeout=10)
            if res.status_code != 200:
                continue
            events = res.json().get("events", [])
            for event in events:
                for comp in event.get("competitions", []):
                    m_id = f"MATCH_{comp.get('id')}"
                    status_type = comp.get("status", {}).get("type", {})
                    if not status_type.get("completed", False):
                        continue
                    
                    if m_id in active_forecasts:
                        competitors = comp.get("competitors", [])
                        if len(competitors) == 2:
                            w_data = next((c for c in competitors if c.get("winner") is True), None)
                            if not w_data:
                                continue
                            winner_name = w_data.get("athlete", {}).get("displayName")
                            
                            # Parse games won from linescores
                            lines_a = [int(x.get("value", 0)) for x in competitors[0].get("linescores", []) if "value" in x]
                            lines_b = [int(x.get("value", 0)) for x in competitors[1].get("linescores", []) if "value" in x]
                            
                            tot_games = sum(lines_a) + sum(lines_b)
                            game_spread = sum(lines_a) - sum(lines_b)
                            
                            execute_factual_post_mortem(m_id, winner_name, tot_games, game_spread)
        except Exception as e:
            print(f"[AUDITOR ERROR] {tour}: {e}")

if __name__ == "__main__":
    audit_completed_matches()
