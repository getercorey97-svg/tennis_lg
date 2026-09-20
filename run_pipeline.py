#!/usr/bin/env python3
"""
tennis_lg: Pre-Match Execution Pipeline
Pulls active matches from Daily_Card and computes Monte Carlo projections.
"""

import sqlite3
from engine import run_monte_carlo

DB_NAME = "tennis_lg.db"

def execute_daily_card():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT * FROM Daily_Card WHERE status = 'SCHEDULED';")
    scheduled_matches = [dict(row) for row in c.fetchall()]

    if not scheduled_matches:
        print("[PIPELINE] No scheduled fixtures pending simulation.")
        conn.close()
        return

    print(f"[PIPELINE] Processing {len(scheduled_matches)} fixtures across ATP, WTA, ITF, and ATF...")
    
    for fixture in scheduled_matches:
        forecast = run_monte_carlo(fixture, iterations=3000)
        c.execute("""
            INSERT OR REPLACE INTO Model_Forecasts (
                match_id, tournament_id, tour, player_a, player_b,
                prob_a_win, prob_b_win, american_ml_a, american_ml_b,
                proj_total_games, proj_game_spread, v_physics, v_thermo,
                v_bio, v_variance, net_edge, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            forecast['match_id'], forecast['tournament_id'], forecast['tour'],
            forecast['player_a'], forecast['player_b'], forecast['prob_a_win'],
            forecast['prob_b_win'], forecast['american_ml_a'], forecast['american_ml_b'],
            forecast['proj_total_games'], forecast['proj_game_spread'], forecast['v_physics'],
            forecast['v_thermo'], forecast['v_bio'], forecast['v_variance'],
            forecast['net_edge'], forecast['created_at']
        ))
        print(f"  ✓ Model: {forecast['player_a']} ({forecast['prob_a_win']*100:.1f}%) vs {forecast['player_b']} ({forecast['prob_b_win']*100:.1f}%) [{forecast['tour']}]")

    conn.commit()
    conn.close()
    print("[PIPELINE COMPLETE] Generated forecasts saved to database.")

if __name__ == "__main__":
    execute_daily_card()
