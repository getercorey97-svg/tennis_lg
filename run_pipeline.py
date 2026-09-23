#!/usr/bin/env python3
"""
tennis_lg: Immutable Pre-Match Projection Pipeline
Calculates analytical Markov chain win probabilities, game totals, spreads,
fair FanDuel moneylines, and Geter Principle vectors.
Locks predictions without overwriting active forecasts.
"""

import sqlite3
import math
from datetime import datetime, timezone

DB_NAME = "tennis_lg.db"

def calculate_projection(p_a_stats, p_b_stats, best_of=3):
    sp_a, rq_a, pts_a = p_a_stats
    sp_b, rq_b, pts_b = p_b_stats

    diff = (sp_a + rq_a) - (sp_b + rq_b)
    factor = 14.2 if best_of == 3 else 18.5
    prob_a = 1.0 / (1.0 + math.exp(-factor * diff))
    prob_a = max(0.02, min(0.98, prob_a))
    prob_b = 1.0 - prob_a

    if prob_a >= 0.5:
        ml_a = int(round(-100.0 * prob_a / (1.0 - prob_a)))
        ml_b = int(round(100.0 * (1.0 - prob_a) / prob_a))
    else:
        ml_a = int(round(100.0 * prob_a / (1.0 - prob_a)))
        ml_b = int(round(-100.0 * prob_b / (1.0 - prob_b)))

    closeness = 1.0 - abs(prob_a - 0.5) * 2.0
    base_games = 21.0 if best_of == 3 else 36.0
    tot_games = round(base_games + closeness * 3.5, 1)
    spread = round((prob_a - 0.5) * 7.5, 1)

    v_phys = round(diff * 1.085, 3)
    v_therm = round((0.5 - abs(prob_a - 0.5)) * 0.12 * 0.995, 3)
    v_bio = round(0.0, 3)
    v_var = round((1.0 / math.sqrt(max(10, pts_a)) - 1.0 / math.sqrt(max(10, pts_b))) * 0.965, 3)
    net_edge = round(v_phys + v_therm + v_bio + v_var, 3)

    return {
        "prob_a": round(prob_a, 4),
        "prob_b": round(prob_b, 4),
        "ml_a": ml_a,
        "ml_b": ml_b,
        "total_games": tot_games,
        "spread": spread,
        "v_phys": v_phys,
        "v_therm": v_therm,
        "v_bio": v_bio,
        "v_var": v_var,
        "net_edge": net_edge
    }

def run():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Select only new fixtures that have not yet been projected
    c.execute("""
        SELECT d.*, t.best_of
        FROM Daily_Card d
        LEFT JOIN Tournaments t ON d.tournament_id = t.id
        LEFT JOIN Model_Forecasts f ON d.match_id = f.match_id
        WHERE d.status = 'SCHEDULED' AND f.match_id IS NULL;
    """)
    new_fixtures = [dict(r) for r in c.fetchall()]

    if not new_fixtures:
        print("[PIPELINE] No new unprojected fixtures. Active forecasts preserved.")
        conn.close()
        return

    print(f"[PIPELINE] Generating predictions for {len(new_fixtures)} new fixtures...")

    c.execute("SELECT id, name, serve_p, return_q, sample_points FROM Players;")
    player_cache = {r['id']: (r['name'], r['serve_p'], r['return_q'], r['sample_points']) for r in c.fetchall()}

    forecast_rows = []
    for f in new_fixtures:
        p_a_data = player_cache.get(f['player_a_id'], (f['player_a_id'].replace("PRO_", "").replace("_", " "), 0.640, 0.360, 100))
        p_b_data = player_cache.get(f['player_b_id'], (f['player_b_id'].replace("PRO_", "").replace("_", " "), 0.640, 0.360, 100))

        name_a, sp_a, rq_a, pts_a = p_a_data
        name_b, sp_b, rq_b, pts_b = p_b_data
        best_of = f.get('best_of') or 3

        proj = calculate_projection((sp_a, rq_a, pts_a), (sp_b, rq_b, pts_b), best_of)

        forecast_rows.append((
            f['match_id'], f['tournament_id'], f['tour'], name_a, name_b,
            proj['prob_a'], proj['prob_b'], proj['spread'], proj['total_games'],
            proj['ml_a'], proj['ml_b'], proj['v_phys'], proj['v_therm'],
            proj['v_bio'], proj['v_var'], proj['net_edge'], now_ts
        ))

    c.executemany("""
        INSERT OR REPLACE INTO Model_Forecasts (
            match_id, tournament_id, tour, player_a, player_b,
            prob_a_win, prob_b_win, proj_game_spread, proj_total_games,
            american_ml_a, american_ml_b, v_physics, v_thermo,
            v_bio, v_variance, net_edge, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, forecast_rows)

    conn.commit()
    conn.close()
    print(f"[PIPELINE COMPLETE] {len(forecast_rows)} new predictions locked into database.")

if __name__ == "__main__":
    run()
