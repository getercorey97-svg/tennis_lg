#!/usr/bin/env python3
import sqlite3
from datetime import datetime

DB_NAME = "tennis_lg.db"

def execute_factual_post_mortem(match_id, actual_winner, actual_total, actual_spread):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM Model_Forecasts WHERE match_id = ?;", (match_id,))
    f = c.fetchone()
    if not f: return print(f"[ERROR] Forecast missing for {match_id}")

    # Safely Unpack the 17-Column Forecast Schema
    _, _, _, p_a, p_b, prob_a, prob_b, _, _, proj_tot, proj_spr, v_phys, v_therm, v_bio, v_var, _, _ = f
    
    y_a = 1.0 if actual_winner == p_a else 0.0
    brier = round((prob_a - y_a) ** 2, 4)
    error_margin = y_a - prob_a 
    
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT OR REPLACE INTO Historical_Forecasts VALUES (?,?,?,?,?,?,?,?,?,?,?,?);", 
              (match_id, f[1], f[2], p_a, p_b, prob_a, prob_b, actual_winner, actual_total, actual_spread, brier, now_ts))
    
    lr = 0.05
    c.execute("SELECT vector_name, beta_weight FROM Feature_Correlations;")
    current_betas = {row[0]: row[1] for row in c.fetchall()}
    
    new_betas = {
        'v_physics': max(0.5, min(1.5, current_betas['v_physics'] + (v_phys * error_margin * lr))),
        'v_thermo': max(0.5, min(1.5, current_betas['v_thermo'] + (v_therm * error_margin * lr))),
        'v_bio': max(0.5, min(1.5, current_betas['v_bio'] + (v_bio * error_margin * lr))),
        'v_variance': max(0.5, min(1.5, current_betas['v_variance'] + (v_var * error_margin * lr)))
    }
    
    for v_name, n_beta in new_betas.items():
        c.execute("UPDATE Feature_Correlations SET beta_weight = ?, updated_at = ? WHERE vector_name = ?;", (round(n_beta, 4), now_ts, v_name))

    c.execute("UPDATE Daily_Card SET status = 'FINAL' WHERE match_id = ?;", (match_id,))
    conn.commit(); conn.close()

    print(f"\n[POST-MORTEM] {p_a} vs {p_b} | Brier: {brier:.4f} | Error Margin: {error_margin:+.3f}")
    print(f"  -> Updated Beta Weights: Bio({new_betas['v_bio']:.3f}), Thermo({new_betas['v_thermo']:.3f})")

if __name__ == "__main__":
    execute_factual_post_mortem("MATCH_ATF_001", "Yunchaokete Bu", 19, -5)
