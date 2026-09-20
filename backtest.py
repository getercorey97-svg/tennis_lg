#!/usr/bin/env python3
"""
tennis_lg: Walk-Forward Multi-Tour Backtest Engine
Evaluates factual historical records across ATP, WTA, ITF, and ATF without mock dummy labels.
"""

import sqlite3

DB_NAME = "tennis_lg.db"

def run_walk_forward_backtest():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute("""
        SELECT match_id, tour, player_a, player_b, prob_a_win, prob_b_win, 
               actual_winner, actual_total_games, actual_game_spread, brier_score 
        FROM Historical_Forecasts
        WHERE player_a NOT LIKE 'Player_A%' AND player_b NOT LIKE 'Player_B%'
        ORDER BY evaluated_at ASC;
    """)
    records = c.fetchall()
    conn.close()

    total = len(records)
    if total == 0:
        print("[BACKTEST] No factual historical records found. Run migrate_and_seed.py first.")
        return

    correct = 0
    cumulative_brier = 0.0

    print(f"\n[BACKTEST] Replaying {total} factual multi-tour matches (Walk-Forward OOS)...")
    
    tour_stats = {}

    for row in records:
        match_id, tour, p_a, p_b, prob_a, prob_b, actual_winner, act_tot, act_spr, brier = row
        pred_winner = p_a if prob_a >= prob_b else p_b
        hit = (pred_winner == actual_winner)
        if hit: correct += 1
        cumulative_brier += brier

        if tour not in tour_stats: tour_stats[tour] = {"total": 0, "correct": 0}
        tour_stats[tour]["total"] += 1
        if hit: tour_stats[tour]["correct"] += 1

    accuracy = (correct / total) * 100
    mean_brier = cumulative_brier / total

    print("=======================================================")
    print("  TENNIS_LG: MULTI-TOUR BACKTEST SCORECARD (ATP/WTA/ITF/ATF)")
    print("=======================================================")
    print(f"  Total Matches Evaluated : {total}")
    print(f"  Outright Model Accuracy : {accuracy:.1f}%")
    print(f"  Mean Out-of-Sample Brier : {mean_brier:.4f}")
    print("-------------------------------------------------------")
    for t_name, s in tour_stats.items():
        t_acc = (s['correct'] / s['total']) * 100
        print(f"  {t_name.ljust(6)} Accuracy : {t_acc:.1f}% ({s['correct']}/{s['total']})")
    print("=======================================================\n")

if __name__ == "__main__":
    run_walk_forward_backtest()
