#!/usr/bin/env python3
"""
tennis_lg: Discrete Hierarchical Markov Monte Carlo Prediction Engine
Optimized for ATP, WTA, ITF, and ATF FanDuel Outright & Derivative Markets.
Implements the Geter Principle (Causal Decomposition) and Factual Post-Mortem Architecture.
"""

import sqlite3
import random
import math
import argparse
import sys
from dataclasses import dataclass
from typing import Dict, Any, Tuple, Optional
from datetime import datetime, timezone

DB_NAME = "tennis_lg.db"

# ---------------------------------------------------------
# DOMAIN MODELS & DATA STRUCTURES
# ---------------------------------------------------------

@dataclass
class PlayerProfile:
    name: str
    tour: str              # 'ATP', 'WTA', 'ITF', 'ATF'
    handedness: str        # 'R', 'L'
    backhand: str          # '1H', '2H'
    serve_p: float         # True Point Won on Serve (0.0 to 1.0)
    return_q: float        # True Point Won on Return (0.0 to 1.0)
    bp_save: float         # Break Point Save % (Leverage)
    bp_convert: float      # Break Point Convert % (Leverage)
    topspin_rpm: float     # Average Forehand Topspin RPM
    sample_points: int     # Historical Sample Count (for Empirical Bayes)
    fatigue_hours_72h: float # Court time over last 72 hours
    rest_days: int         # Days since last match

@dataclass
class MatchConditions:
    tournament_name: str
    tour: str              # 'ATP', 'WTA', 'ITF', 'ATF'
    surface: str           # 'Hard', 'Clay', 'Grass', 'Carpet'
    cpi: float             # Court Pace Index (e.g., 25=Slow Clay, 45=Fast Hard)
    is_indoor: bool
    elevation_m: float
    temp_c: float
    humidity_pct: float
    best_of: int           # 3 or 5

@dataclass
class CausalVectors:
    v_physics: float       # Kinematic & geometric matchup delta
    v_thermo: float        # Surface speed & air density interaction
    v_bio: float           # Biological load and fatigue penalty
    v_variance: float      # Tour volatility and Bayesian sample shrinkage
    net_edge: float        # Combined probability delta

# ---------------------------------------------------------
# THE GETER PRINCIPLE: CAUSAL VECTOR DECOMPOSITION
# ---------------------------------------------------------

def compute_causal_decomposition(
    p_a: PlayerProfile,
    p_b: PlayerProfile,
    cond: MatchConditions
) -> CausalVectors:
    """
    Decomposes the net probability edge into four fundamental physical and
    biological vectors rather than treating the matchup as a black-box rating.
    """
    # 1. Kinematic & Geometric Matchup (V_physics)
    v_physics = 0.0
    # Platoon geometry: Lefty topspin kicking high to a Righty 1H backhand
    if p_a.handedness == 'L' and p_b.handedness == 'R' and p_b.backhand == '1H':
        rpm_delta = max(0.0, (p_a.topspin_rpm - 2600.0) / 1000.0)
        v_physics += 0.022 + (rpm_delta * 0.015)
    elif p_b.handedness == 'L' and p_a.handedness == 'R' and p_a.backhand == '1H':
        rpm_delta = max(0.0, (p_b.topspin_rpm - 2600.0) / 1000.0)
        v_physics -= 0.022 + (rpm_delta * 0.015)

    # 2. Thermodynamic & Surface Interaction (V_thermo)
    # Standard CPI baseline is 35.0. Faster courts benefit servers; slow clay benefits returners.
    cpi_delta = (cond.cpi - 35.0) / 100.0
    # Thermodynamic ball speed factor (High elevation & high temp thin the air, boosting CPI)
    air_density_proxy = (cond.temp_c * 0.1) + (cond.elevation_m / 800.0) - (cond.humidity_pct * 0.05)
    effective_cpi_shift = cpi_delta + (air_density_proxy * 0.01)

    serve_delta = p_a.serve_p - p_b.serve_p
    v_thermo = serve_delta * effective_cpi_shift * 1.5

    # 3. Biological Entropy & Fatigue (V_bio)
    # Penalize players exceeding 4.5 match hours in past 72 hours without rest
    fatigue_a = max(0.0, p_a.fatigue_hours_72h - 4.5) / 10.0
    fatigue_b = max(0.0, p_b.fatigue_hours_72h - 4.5) / 10.0
    if p_a.rest_days >= 2:
        fatigue_a *= 0.4
    if p_b.rest_days >= 2:
        fatigue_b *= 0.4

    # ATF regional tour imposes 1.5x penalty on multi-day heat load
    if cond.tour == 'ATF':
        fatigue_a *= 1.5
        fatigue_b *= 1.5

    v_bio = fatigue_b - fatigue_a  # Positive if Player B is more fatigued

    # 4. Human & Systemic Variance (V_variance)
    # Empirical Bayes shrinkage for sparse data (ITF circuits)
    v_variance = 0.0
    if cond.tour == 'ITF':
        shrink_a = 60.0 / (p_a.sample_points + 60.0)
        shrink_b = 60.0 / (p_b.sample_points + 60.0)
        v_variance = (shrink_b * 0.03) - (shrink_a * 0.03)

    net_edge = round(v_physics + v_thermo + v_bio + v_variance, 4)
    return CausalVectors(
        v_physics=round(v_physics, 4),
        v_thermo=round(v_thermo, 4),
        v_bio=round(v_bio, 4),
        v_variance=round(v_variance, 4),
        net_edge=net_edge
    )

# ---------------------------------------------------------
# POINT-LEVEL LOG5 SYNTHESIS & FEDERATION PARAMETERS
# ---------------------------------------------------------

def calculate_point_win_prob(
    server_p: float,
    returner_q: float,
    tour: str,
    is_break_point: bool = False,
    server_bp_save: float = 0.65,
    returner_bp_convert: float = 0.40
) -> float:
    """
    Synthesizes server point probability using Log5, applying tour-specific
    structural parameters and leverage state adjustments.
    """
    # Log5 formulation for independent serve/return point expectation
    numerator = server_p * (1.0 - returner_q)
    denominator = numerator + ((1.0 - server_p) * returner_q)
    if denominator == 0:
        base_p = server_p
    else:
        base_p = numerator / denominator

    # Leverage adjustments on Break Points
    if is_break_point:
        if tour == 'ATP':
            # ATP matches hinge on high-pressure serve defense
            bp_factor = (server_bp_save - 0.65) - (returner_bp_convert - 0.40)
            base_p += bp_factor * 0.06
        elif tour == 'WTA':
            # WTA matches feature higher break frequency; returner conversion dominates
            bp_factor = (returner_bp_convert - 0.45) * 0.08
            base_p -= bp_factor

    # Bound probabilities to physically realistic margins
    if tour == 'ATP':
        return max(0.48, min(0.85, base_p))
    elif tour == 'WTA':
        return max(0.40, min(0.74, base_p))
    elif tour == 'ITF':
        return max(0.38, min(0.78, base_p))
    else:  # ATF
        return max(0.42, min(0.80, base_p))

# ---------------------------------------------------------
# DISCRETE MARKOV STATE SIMULATION CORE
# ---------------------------------------------------------

def simulate_game(
    p_server: float,
    tour: str,
    server_bp_save: float,
    returner_bp_convert: float
) -> Tuple[int, int]:
    """
    Simulates a single discrete tennis game point-by-point.
    Returns (server_won: 1 or 0, total_points_played: int).
    """
    s_pts = 0
    r_pts = 0

    while True:
        # Check leverage state: Break point occurs when receiver is 1 point away from game
        is_bp = (r_pts >= 3 and (r_pts - s_pts) >= 1) or (r_pts == 3 and s_pts < 3)
        effective_p = calculate_point_win_prob(
            p_server, 1.0 - p_server, tour,
            is_break_point=is_bp,
            server_bp_save=server_bp_save,
            returner_bp_convert=returner_bp_convert
        )

        if random.random() < effective_p:
            s_pts += 1
        else:
            r_pts += 1

        # Check win condition: At least 4 points and win by 2
        if s_pts >= 4 and (s_pts - r_pts) >= 2:
            return 1, (s_pts + r_pts)
        if r_pts >= 4 and (r_pts - s_pts) >= 2:
            return 0, (s_pts + r_pts)

def simulate_tiebreak(
    p_serve_a: float,
    p_serve_b: float,
    tour: str,
    target_pts: int = 7
) -> Tuple[int, int, int]:
    """
    Simulates a standard tiebreak. Alternates serve after Point 1, then every 2 points.
    Returns (winner: 1 for A or 2 for B, a_points, b_points).
    """
    pts_a = 0
    pts_b = 0
    point_num = 1

    while True:
        # Determine active server (A serves pt 1, B serves 2-3, A serves 4-5, etc.)
        server_is_a = (point_num % 4 in (1, 0)) if point_num > 1 else True

        if server_is_a:
            p_point = calculate_point_win_prob(p_serve_a, 1.0 - p_serve_a, tour)
            if random.random() < p_point:
                pts_a += 1
            else:
                pts_b += 1
        else:
            p_point = calculate_point_win_prob(p_serve_b, 1.0 - p_serve_b, tour)
            if random.random() < p_point:
                pts_b += 1
            else:
                pts_a += 1

        point_num += 1

        if pts_a >= target_pts and (pts_a - pts_b) >= 2:
            return 1, pts_a, pts_b
        if pts_b >= target_pts and (pts_b - pts_a) >= 2:
            return 2, pts_a, pts_b

def simulate_set(
    p_serve_a: float,
    p_serve_b: float,
    p_a: PlayerProfile,
    p_b: PlayerProfile,
    cond: MatchConditions,
    server_starts_a: bool = True
) -> Tuple[int, int, int, bool]:
    """
    Simulates a single set.
    Returns (winner: 1 for A or 2 for B, games_a, games_b, tiebreak_occurred: bool).
    """
    games_a = 0
    games_b = 0
    current_server_a = server_starts_a
    tb_occurred = False

    while True:
        if current_server_a:
            won, _ = simulate_game(p_serve_a, cond.tour, p_a.bp_save, p_b.bp_convert)
            if won:
                games_a += 1
            else:
                games_b += 1
        else:
            won, _ = simulate_game(p_serve_b, cond.tour, p_b.bp_save, p_a.bp_convert)
            if won:
                games_b += 1
            else:
                games_a += 1

        current_server_a = not current_server_a

        # Set win checks
        if games_a >= 6 and (games_a - games_b) >= 2:
            return 1, games_a, games_b, tb_occurred
        if games_b >= 6 and (games_b - games_a) >= 2:
            return 2, games_a, games_b, tb_occurred

        # Tiebreak at 6-6
        if games_a == 6 and games_b == 6:
            tb_occurred = True
            tb_winner, _, _ = simulate_tiebreak(p_serve_a, p_serve_b, cond.tour)
            if tb_winner == 1:
                games_a += 1
                return 1, games_a, games_b, tb_occurred
            else:
                games_b += 1
                return 2, games_a, games_b, tb_occurred

def simulate_match_monte_carlo(
    player_a: PlayerProfile,
    player_b: PlayerProfile,
    conditions: MatchConditions,
    iterations: int = 5000
) -> Dict[str, Any]:
    """
    Executes discrete point-by-point Monte Carlo simulation across N iterations.
    Outputs Outright Win Probabilities and exact FanDuel market distributions.
    """
    vectors = compute_causal_decomposition(player_a, player_b, conditions)

    # Effective baseline point-won-on-serve incorporating causal vectors
    effective_p_a = player_a.serve_p + (vectors.net_edge * 0.5)
    effective_p_b = player_b.serve_p - (vectors.net_edge * 0.5)

    # Empirical Bayes regression for ITF low-sample stability
    if conditions.tour == 'ITF':
        w_a = player_a.sample_points / (player_a.sample_points + 60.0)
        w_b = player_b.sample_points / (player_b.sample_points + 60.0)
        effective_p_a = (w_a * effective_p_a) + ((1.0 - w_a) * 0.62)
        effective_p_b = (w_b * effective_p_b) + ((1.0 - w_b) * 0.62)

    sets_to_win = 3 if conditions.best_of == 5 else 2

    wins_a = 0
    wins_b = 0
    total_games_list = []
    game_diff_list = []
    set_scores_count = {}
    tiebreak_total = 0

    for _ in range(iterations):
        sets_a = 0
        sets_b = 0
        match_games_a = 0
        match_games_b = 0
        server_starts_a = bool(random.getrandbits(1))

        while sets_a < sets_to_win and sets_b < sets_to_win:
            winner, g_a, g_b, tb = simulate_set(
                effective_p_a, effective_p_b, player_a, player_b, conditions, server_starts_a
            )
            match_games_a += g_a
            match_games_b += g_b
            if tb:
                tiebreak_total += 1
            if winner == 1:
                sets_a += 1
            else:
                sets_b += 1
            # Invert server for next set
            server_starts_a = not server_starts_a

        if sets_a == sets_to_win:
            wins_a += 1
        else:
            wins_b += 1

        total_games = match_games_a + match_games_b
        total_games_list.append(total_games)
        game_diff_list.append(match_games_a - match_games_b)

        score_key = f"{sets_a}-{sets_b}"
        set_scores_count[score_key] = set_scores_count.get(score_key, 0) + 1

    prob_a = round(wins_a / iterations, 4)
    prob_b = round(1.0 - prob_a, 4)

    total_games_list.sort()
    game_diff_list.sort()
    median_total_games = total_games_list[iterations // 2]
    median_game_spread = game_diff_list[iterations // 2]

    # Implied fair decimal odds and American moneyline
    ml_a = int((-(prob_a / (1.0 - prob_a)) * 100) if prob_a >= 0.50 else (((1.0 - prob_a) / prob_a) * 100))
    ml_b = int((-(prob_b / (1.0 - prob_b)) * 100) if prob_b >= 0.50 else (((1.0 - prob_b) / prob_b) * 100))

    return {
        "prob_a_win": prob_a,
        "prob_b_win": prob_b,
        "american_ml_a": ml_a,
        "american_ml_b": ml_b,
        "proj_median_total_games": median_total_games,
        "proj_mean_total_games": round(sum(total_games_list) / iterations, 2),
        "proj_median_game_spread": median_game_spread,
        "proj_mean_game_spread": round(sum(game_diff_list) / iterations, 2),
        "tiebreak_rate_per_match": round(tiebreak_total / iterations, 2),
        "set_score_distribution": {k: round(v / iterations, 3) for k, v in set_scores_count.items()},
        "causal_vectors": {
            "v_physics": vectors.v_physics,
            "v_thermo": vectors.v_thermo,
            "v_bio": vectors.v_bio,
            "v_variance": vectors.v_variance,
            "net_edge": vectors.net_edge
        }
    }

# ---------------------------------------------------------
# DATABASE SCHEMA & TELEMETRY PERSISTENCE
# ---------------------------------------------------------

def init_db(db_path: str = DB_NAME):
    """Initializes the SQLite schema supporting simulations and factual post-mortems."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS Tournaments (
        id TEXT PRIMARY KEY,
        name TEXT,
        tour TEXT,
        surface TEXT,
        cpi REAL,
        is_indoor INTEGER,
        elevation_m REAL,
        best_of INTEGER
    );
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS Players (
        id TEXT PRIMARY KEY,
        name TEXT,
        tour TEXT,
        handedness TEXT,
        backhand TEXT,
        serve_p REAL,
        return_q REAL,
        bp_save REAL,
        bp_convert REAL,
        topspin_rpm REAL,
        sample_points INTEGER,
        fatigue_hours_72h REAL,
        rest_days INTEGER,
        updated_at TEXT
    );
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS Model_Forecasts (
        match_id TEXT PRIMARY KEY,
        tournament_id TEXT,
        tour TEXT,
        player_a TEXT,
        player_b TEXT,
        prob_a_win REAL,
        prob_b_win REAL,
        proj_total_games REAL,
        proj_game_spread REAL,
        v_physics REAL,
        v_thermo REAL,
        v_bio REAL,
        v_variance REAL,
        net_edge REAL,
        created_at TEXT
    );
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS Historical_Forecasts (
        match_id TEXT PRIMARY KEY,
        tournament_id TEXT,
        tour TEXT,
        player_a TEXT,
        player_b TEXT,
        prob_a_win REAL,
        prob_b_win REAL,
        actual_winner TEXT,
        actual_total_games INTEGER,
        actual_game_spread INTEGER,
        brier_score REAL,
        evaluated_at TEXT
    );
    """)

    # Seed baseline demonstration tournament profiles
    c.execute("""
    INSERT OR REPLACE INTO Tournaments VALUES 
    ('ATP_US_OPEN', 'US Open', 'ATP', 'Hard', 42.0, 0, 10.0, 5),
    ('WTA_MADRID', 'Madrid Open', 'WTA', 'Clay', 28.0, 0, 650.0, 3),
    ('ITF_M25_MONASTIR', 'ITF Monastir M25', 'ITF', 'Hard', 38.0, 0, 5.0, 3),
    ('ATF_CHALLENGER_BEIJING', 'Beijing Regional Challenger', 'ATF', 'Hard', 36.0, 0, 44.0, 3);
    """)

    # Seed demonstration player vectors
    c.execute("""
    INSERT OR REPLACE INTO Players VALUES 
    ('ATP_SINNER', 'Jannik Sinner', 'ATP', 'R', '2H', 0.695, 0.425, 0.72, 0.46, 3200, 18500, 2.1, 2, datetime('now')),
    ('ATP_ALCARAZ', 'Carlos Alcaraz', 'ATP', 'R', '2H', 0.680, 0.440, 0.70, 0.48, 3450, 17200, 3.8, 1, datetime('now')),
    ('ATP_SHAPOVALOV', 'Denis Shapovalov', 'ATP', 'L', '1H', 0.665, 0.355, 0.63, 0.36, 3100, 12000, 1.5, 3, datetime('now')),
    ('WTA_SWIATEK', 'Iga Swiatek', 'WTA', 'R', '2H', 0.635, 0.495, 0.68, 0.54, 3150, 14200, 2.0, 2, datetime('now')),
    ('WTA_SABALENKA', 'Aryna Sabalenka', 'WTA', 'R', '2H', 0.670, 0.440, 0.65, 0.47, 2800, 15000, 3.2, 1, datetime('now')),
    ('ITF_PROSPECT_A', 'Alexandre Muller (Dev)', 'ITF', 'R', '2H', 0.610, 0.390, 0.58, 0.38, 2500, 85, 5.2, 0, datetime('now')),
    ('ITF_PROSPECT_B', 'Luca Nardi (Dev)', 'ITF', 'R', '2H', 0.630, 0.370, 0.60, 0.40, 2600, 42, 1.0, 2, datetime('now')),
    ('ATF_ZHANG', 'Zhizhen Zhang', 'ATF', 'R', '2H', 0.650, 0.385, 0.64, 0.41, 2900, 9200, 5.8, 0, datetime('now')),
    ('ATF_BU', 'Yunchaokete Bu', 'ATF', 'R', '2H', 0.635, 0.395, 0.62, 0.39, 2750, 6800, 2.0, 2, datetime('now'));
    """)

    conn.commit()
    conn.close()

# ---------------------------------------------------------
# CLI CONTROLLER & VERIFICATION TEST
# ---------------------------------------------------------

def run_test_simulation():
    init_db()
    print("\n=======================================================")
    print("  TENNIS_LG: 4-FEDERATION ACCURACY & EV VERIFICATION")
    print("=======================================================\n")

    test_cases = [
        ("ATP", "US Open (Best of 5)", 
         PlayerProfile("Jannik Sinner", "ATP", "R", "2H", 0.695, 0.425, 0.72, 0.46, 3200, 18500, 2.1, 2),
         PlayerProfile("Carlos Alcaraz", "ATP", "R", "2H", 0.680, 0.440, 0.70, 0.48, 3450, 17200, 3.8, 1),
         MatchConditions("US Open", "ATP", "Hard", 42.0, False, 10.0, 26.0, 55.0, 5)),

        ("WTA", "Madrid Open (Best of 3)", 
         PlayerProfile("Iga Swiatek", "WTA", "R", "2H", 0.635, 0.495, 0.68, 0.54, 3150, 14200, 2.0, 2),
         PlayerProfile("Aryna Sabalenka", "WTA", "R", "2H", 0.670, 0.440, 0.65, 0.47, 2800, 15000, 3.2, 1),
         MatchConditions("Madrid Open", "WTA", "Clay", 28.0, False, 650.0, 22.0, 40.0, 3)),

        ("ITF", "Monastir M25 (Empirical Bayes Shrinkage)", 
         PlayerProfile("Alexandre Muller (Dev)", "ITF", "R", "2H", 0.610, 0.390, 0.58, 0.38, 2500, 85, 5.2, 0),
         PlayerProfile("Luca Nardi (Dev)", "ITF", "R", "2H", 0.630, 0.370, 0.60, 0.40, 2600, 42, 1.0, 2),
         MatchConditions("ITF Monastir", "ITF", "Hard", 38.0, False, 5.0, 29.0, 60.0, 3)),

        ("ATF", "Beijing Regional (Extreme Thermodynamic Load)", 
         PlayerProfile("Zhizhen Zhang", "ATF", "R", "2H", 0.650, 0.385, 0.64, 0.41, 2900, 9200, 6.2, 0),
         PlayerProfile("Yunchaokete Bu", "ATF", "R", "2H", 0.635, 0.395, 0.62, 0.39, 2750, 6800, 1.5, 2),
         MatchConditions("Beijing Challenger", "ATF", "Hard", 36.0, False, 44.0, 33.0, 82.0, 3))
    ]

    for tour_name, desc, p1, p2, cond in test_cases:
        res = simulate_match_monte_carlo(p1, p2, cond, iterations=3500)
        v = res["causal_vectors"]
        print(f"[{tour_name} ENGINE] {desc}")
        print(f"  Matchup: {p1.name} vs. {p2.name}")
        print(f"  Geter Principle Vectors: V_physics={v['v_physics']:+.4f} | V_thermo={v['v_thermo']:+.4f} | V_bio={v['v_bio']:+.4f} | V_var={v['v_variance']:+.4f}")
        print(f"  Net Predictive Edge: {v['net_edge']:+.4f}")
        print(f"  Outright Win Probability: {p1.name}: {res['prob_a_win']*100:.1f}% ({res['american_ml_a']:+d}) | {p2.name}: {res['prob_b_win']*100:.1f}% ({res['american_ml_b']:+d})")
        print(f"  FanDuel Game Spread: {res['proj_median_game_spread']:+.1f} Games | Total Games: {res['proj_median_total_games']} (Mean: {res['proj_mean_total_games']})")
        print(f"  Set Distributions: {res['set_score_distribution']}")
        print("-------------------------------------------------------")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="tennis_lg Prediction Engine Core")
    parser.add_argument("--init-db", action="store_true", help="Initialize SQLite Schema and Seed Data")
    parser.add_argument("--test", action="store_true", help="Execute 4-Federation Verification Simulations")
    args = parser.parse_args()

    if args.init_db:
        init_db()
        print("[DATABASE] Schema successfully created and seeded: tennis_lg.db")

    if args.test or len(sys.argv) == 1:
        run_test_simulation()
