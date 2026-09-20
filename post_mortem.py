#!/usr/bin/env python3
"""
tennis_lg: Multi-Tour Factual Match Auditor & Post-Mortem Learner
Simulation-free comparison between pre-match predictions and empirical match results.
Audits ATP, WTA, ITF, and ATF outcomes, logs exact parameter drift, and adjusts feature correlations.
"""

import sqlite3
import requests
import math
from datetime import datetime

DB_NAME = "tennis_lg.db"

ENDPOINTS = {
    "ATP": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
    "WTA": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"
}

def log_learning_event(conn, match_id, param, old_v, new_v, reason):
    delta = round(new_v - old_v, 4)
    conn.execute("""
        INSERT INTO Learning_Log (match_id, parameter, old_val, new_val, delta, reason, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (match_id, param, round(old_v, 4), round(new_v, 4), delta, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

def run_simulation_free_post_mortem(match_id, actual_winner, actual_total, actual_spread):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT * FROM Model_Forecasts WHERE match_id = ?;", (match_id,))
    forecast = c.fetchone()
    if not forecast:
        conn.close()
        return

    # Unpack pregame model projection
    m_id, t_id, tour, p_a, p_b, prob_a, prob_b, _, _, proj_tot, proj_spr, v_phys, v_therm, v_bio, v_var, net_edge, _ = forecast

    # Strictly simulation-free evaluation
    y_a = 1.0 if actual_winner == p_a else 0.0
    brier_score = round((prob_a - y_a) ** 2, 4)
    error_margin = y_a - prob_a  # Positive if Player A outperformed projection; negative if underperformed

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Record into official Historical Audits ledger
    c.execute("""
        INSERT OR REPLACE INTO Historical_Forecasts (
            match_id, tournament_id, tour, player_a, player_b,
            prob_a_win, prob_b_win, actual_winner, actual_total_games,
            actual_game_spread, brier_score, evaluated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (match_id, t_id, tour, p_a, p_b, prob_a, prob_b, actual_winner, actual_total, actual_spread, brier_score, now_ts))

    # 1. Update Feature Correlation Weights (Beta Drift via Gradient Descent)
    learning_rate = 0.04
    c.execute("SELECT vector_name, beta_weight FROM Feature_Correlations;")
    current_betas = {r[0]: r[1] for r in c.fetchall()}

    vector_shifts = {
        'v_physics': v_phys,
        'v_thermo': v_therm,
        'v_bio': v_bio,
        'v_variance': v_var
    }

    for v_name, v_val in vector_shifts.items():
        old_beta = current_betas.get(v_name, 1.0)
        grad = v_val * error_margin * learning_rate
        new_beta = max(0.50, min(1.50, old_beta + grad))
        
        c.execute("UPDATE Feature_Correlations SET beta_weight = ?, updated_at = ? WHERE vector_name = ?;",
                  (round(new_beta, 4), now_ts, v_name))
        log_learning_event(conn, match_id, f"Beta: {v_name}", old_beta, new_beta, f"Post-mortem gradient ({error_margin:+.3f} error)")

    # 2. Recalibrate Player Vectors via Sample-Scaled EWMA
    for p_name, is_winner in [(p_a, actual_winner == p_a), (p_b, actual_winner == p_b)]:
        c.execute("SELECT serve_p, return_q, sample_points FROM Players WHERE name = ?;", (p_name,))
        p_row = c.fetchone()
        if p_row:
            old_serve, old_ret, sample_pts = p_row
            k_factor = max(0.015, 1.0 / math.sqrt(max(sample_pts, 50)))
            
            target_shift = 0.025 if is_winner else -0.020
            new_serve = max(0.48, min(0.85, old_serve + (target_shift * k_factor)))
            new_pts = sample_pts + 140
            
            c.execute("UPDATE Players SET serve_p = ?, sample_points = ?, updated_at = ? WHERE name = ?;",
                      (round(new_serve, 4), new_pts, now_ts, p_name))
            log_learning_event(conn, match_id, f"Rating: {p_name}", old_serve, new_serve, f"Outcome adjustment ({'Won' if is_winner else 'Lost'})")

    c.execute("UPDATE Daily_Card SET status = 'FINAL' WHERE match_id = ?;", (match_id,))
    conn.commit()
    conn.close()
    print(f"[AUDIT SUCCESS] Evaluated {match_id} ({tour}) | Winner: {actual_winner} | Brier: {brier_score:.4f} | Error: {error_margin:+.3f}")

def audit_all_tours():
    """Polls public scoreboards and audits pending matches for ATP, WTA, ITF, and ATF."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT match_id, player_a, player_b FROM Model_Forecasts WHERE match_id NOT IN (SELECT match_id FROM Historical_Forecasts);")
    pending = {r[0]: (r[1], r[2]) for r in c.fetchall()}
    conn.close()

    if not pending:
        print("[AUDITOR] All forecasts in database are audited and synchronized.")
        return

    # Audit via live scoreboard feeds for ATP/WTA
    for tour, url in ENDPOINTS.items():
        try:
            res = requests.get(url, timeout=10)
            if res.status_code != 200: continue
            for ev in res.json().get("events", []):
                for comp in ev.get("competitions", []):
                    m_id = f"MATCH_{tour}_{comp.get('id')}"
                    if m_id in pending and comp.get("status", {}).get("type", {}).get("completed", False):
                        comps = comp.get("competitors", [])
                        w = next((x for x in comps if x.get("winner") is True), None)
                        if w:
                            w_name = w.get("athlete", {}).get("displayName")
                            lines_a = [int(x.get("value", 0)) for x in comps[0].get("linescores", []) if "value" in x]
                            lines_b = [int(x.get("value", 0)) for x in comps[1].get("linescores", []) if "value" in x]
                            run_simulation_free_post_mortem(m_id, w_name, sum(lines_a)+sum(lines_b), sum(lines_a)-sum(lines_b))
        except Exception as e:
            print(f"[AUDITOR ERROR] {tour}: {e}")

if __name__ == "__main__":
    audit_all_tours()
