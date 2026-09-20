#!/usr/bin/env python3
import sqlite3
from datetime import datetime
from engine import simulate_match_monte_carlo, PlayerProfile, MatchConditions, fetch_correlation_betas, DB_NAME

def run_slate_forecasts(iterations=3500):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL;")
    c = conn.cursor()

    query = """
    SELECT 
        d.match_id, d.tournament_id, d.tour, t.name, t.surface, t.cpi, t.is_indoor, t.elevation_m, t.best_of, d.temp_c, d.humidity_pct,
        pa.id, pa.name, pa.tour, pa.handedness, pa.backhand, pa.serve_p, pa.return_q, pa.bp_save, pa.bp_convert, pa.topspin_rpm, pa.sample_points, pa.fatigue_hours_72h, pa.rest_days,
        pb.id, pb.name, pb.tour, pb.handedness, pb.backhand, pb.serve_p, pb.return_q, pb.bp_save, pb.bp_convert, pb.topspin_rpm, pb.sample_points, pb.fatigue_hours_72h, pb.rest_days
    FROM Daily_Card d
    JOIN Tournaments t ON d.tournament_id = t.id
    JOIN Players pa ON d.player_a_id = pa.id
    JOIN Players pb ON d.player_b_id = pb.id
    WHERE d.status = 'SCHEDULED';
    """
    c.execute(query)
    fixtures = c.fetchall()

    if not fixtures: return print("[PIPELINE INFO] No scheduled fixtures pending.")

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    betas = fetch_correlation_betas()
    
    report_lines = [
        "# tennis_lg: FanDuel Operational Slate Projections",
        f"**Generated:** {now_ts} | **Simulation Depth:** N={iterations} Paths",
        f"**Active Correlation Multipliers ($\beta$):** Physics: {betas['v_physics']:.3f} | Thermo: {betas['v_thermo']:.3f} | Bio: {betas['v_bio']:.3f} | Var: {betas['v_variance']:.3f}\n",
        "| Tour | Matchup | Outright ML (+EV Edge) | Spread Line | Total Games | Causal Key Vectors |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    print(f"\n[PIPELINE] Launching discrete Markov state machine across {len(fixtures)} fixtures...\n")

    for fix in fixtures:
        match_id, t_id, tour = fix[0], fix[1], fix[2]
        cond = MatchConditions(fix[3], tour, fix[4], fix[5], bool(fix[6]), fix[7], fix[9], fix[10], fix[8])
        p1 = PlayerProfile(fix[12], fix[13], fix[14], fix[15], fix[16], fix[17], fix[18], fix[19], fix[20], fix[21], fix[22], fix[23])
        p2 = PlayerProfile(fix[25], fix[26], fix[27], fix[28], fix[29], fix[30], fix[31], fix[32], fix[33], fix[34], fix[35], fix[36])

        res = simulate_match_monte_carlo(p1, p2, cond, iterations=iterations)
        v = res["causal_vectors"]

        # Insert exact 17 values matching the schema
        c.execute("INSERT OR REPLACE INTO Model_Forecasts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);", (
            match_id, t_id, tour, p1.name, p2.name, res["prob_a_win"], res["prob_b_win"],
            res["american_ml_a"], res["american_ml_b"], res["proj_mean_total_games"], res["proj_median_game_spread"],
            v["v_physics"], v["v_thermo"], v["v_bio"], v["v_variance"], v["net_edge"], now_ts
        ))

        fav = p1.name if res["prob_a_win"] >= 0.50 else p2.name
        fav_prob = max(res["prob_a_win"], res["prob_b_win"]) * 100
        fav_ml = res["american_ml_a"] if fav == p1.name else res["american_ml_b"]

        print(f"[{tour}] {p1.name} vs. {p2.name} -> {fav} ({fav_prob:.1f}%, ML: {fav_ml:+d})")
        
        row = (f"| **{tour}** | {p1.name} vs {p2.name} | **{fav}** ({fav_prob:.1f}%, {fav_ml:+d}) | "
               f"{res['proj_median_game_spread']:+.1f} Games | O/U {res['proj_median_total_games']:.1f} | "
               f"Bio: {v['v_bio']:+.3f}, Th: {v['v_thermo']:+.3f} |")
        report_lines.append(row)

    conn.commit(); conn.close()
    with open("PREDICTIONS_TODAY.md", "w") as f: f.write("\n".join(report_lines) + "\n")
    print("\n[SUCCESS] Pipeline completed. Active projections persisted to Model_Forecasts and PREDICTIONS_TODAY.md.")

if __name__ == "__main__":
    run_slate_forecasts(iterations=3500)
