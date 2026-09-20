#!/usr/bin/env python3
"""
tennis_lg: Simulation-Free Factual Post-Mortem Auditor
Audits completed matches against actual official linescores,
computes empirical Brier scores, updates beta correlation weights,
and recalibrates real player performance ratings.
"""

import sqlite3
import requests
import math
from datetime import datetime, timezone

DB_NAME = "tennis_lg.db"

ENDPOINTS = {
    "ATP": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
    "WTA": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"
}

def log_learning_drift(conn, match_id, param, old_val, new_val, reason):
    delta = round(new_val - old_val, 4)
    conn.execute("""
        INSERT INTO Learning_Log (match_id, parameter, old_val, new_val, delta, reason, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (match_id, param, round(old_val, 4), round(new_val, 4), delta, reason, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")))

def audit_match_outcome(match_id, actual_winner, actual_total, actual_spread):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT * FROM Model_Forecasts WHERE match_id = ?;", (match_id,))
    forecast = c.fetchone()
    if not forecast:
        conn.close()
        return

    m_id, t_id, tour, p_a, p_b, prob_a, prob_b, _, _, proj_tot, proj_spr, v_phys, v_therm, v_bio, v_var, net_edge, _ = forecast

    # Empirical mathematical comparison (Simulation-Free)
    y_a = 1.0 if actual_winner == p_a else 0.0
    brier = round((prob_a - y_a) ** 2, 4)
    error_margin = y_a - prob_a
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    c.execute("""
        INSERT OR REPLACE INTO Historical_Forecasts (
            match_id, tournament_id, tour, player_a, player_b,
            prob_a_win, prob_b_win, actual_winner, actual_total_games,
            actual_game_spread, brier_score, evaluated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (match_id, t_id, tour, p_a, p_b, prob_a, prob_b, actual_winner, actual_total, actual_spread, brier, now_ts))

    # Gradient descent update on correlation weights
    lr = 0.04
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
        new_b = max(0.50, min(1.50, old_b + grad))
        c.execute("UPDATE Feature_Correlations SET beta_weight = ?, updated_at = ? WHERE vector_name = ?;",
                  (round(new_b, 4), now_ts, v_name))
        log_learning_drift(conn, match_id, f"Beta: {v_name}", old_b, new_b, f"Error {error_margin:+.3f} on {p_a} vs {p_b}")

    # Player vector update via sample-weighted EWMA
    for p_name, is_winner in [(p_a, actual_winner == p_a), (p_b, actual_winner == p_b)]:
        c.execute("SELECT serve_p, return_q, sample_points FROM Players WHERE name = ?;", (p_name,))
        p_row = c.fetchone()
        if p_row:
            old_serve, old_ret, sample_pts = p_row
            k_factor = max(0.015, 1.0 / math.sqrt(max(sample_pts, 50)))
            shift = 0.025 if is_winner else -0.020
            new_serve = max(0.45, min(0.85, old_serve + (shift * k_factor)))
            c.execute("UPDATE Players SET serve_p = ?, sample_points = ?, updated_at = ? WHERE name = ?;",
                      (round(new_serve, 4), sample_pts + 120, now_ts, p_name))
            log_learning_drift(conn, match_id, f"Rating: {p_name}", old_serve, new_serve, f"Outcome: {'Win' if is_winner else 'Loss'}")

    c.execute("UPDATE Daily_Card SET status = 'FINAL' WHERE match_id = ?;", (match_id,))
    conn.commit()
    conn.close()
    print(f"[AUDIT] Match {match_id} | Official Winner: {actual_winner} | Games: {actual_total} | Brier: {brier:.4f}")

def poll_and_audit():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT match_id FROM Model_Forecasts WHERE match_id NOT IN (SELECT match_id FROM Historical_Forecasts);")
    pending_ids = set(r[0] for r in c.fetchall())
    conn.close()

    if not pending_ids:
        print("[AUDITOR] No pending unaudited matches in database.")
        return

    for tour, url in ENDPOINTS.items():
        try:
            res = requests.get(url, timeout=10)
            if res.status_code != 200:
                continue
            data = res.json()
            for ev in data.get("events", []):
                for comp in ev.get("competitions", []):
                    m_id = f"MATCH_{tour}_{comp.get('id')}"
                    if m_id in pending_ids and comp.get("status", {}).get("type", {}).get("completed", False):
                        competitors = comp.get("competitors", [])
                        winner_comp = next((x for x in competitors if x.get("winner") is True), None)
                        if not winner_comp:
                            continue
                        winner_name = winner_comp.get("athlete", {}).get("displayName")
                        lines_a = [int(x.get("value", 0)) for x in competitors[0].get("linescores", []) if "value" in x]
                        lines_b = [int(x.get("value", 0)) for x in competitors[1].get("linescores", []) if "value" in x]
                        total_g = sum(lines_a) + sum(lines_b)
                        spread_g = sum(lines_a) - sum(lines_b)
                        audit_match_outcome(m_id, winner_name, total_g, spread_g)
        except Exception as e:
            print(f"[AUDITOR ERROR] Failed parsing {tour} results: {e}")

if __name__ == "__main__":
    poll_and_audit()
