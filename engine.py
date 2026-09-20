#!/usr/bin/env python3
import sqlite3
import random
import argparse
from dataclasses import dataclass
from typing import Dict

DB_NAME = "tennis_lg.db"

@dataclass
class PlayerProfile:
    name: str; tour: str; handedness: str; backhand: str
    serve_p: float; return_q: float; bp_save: float; bp_convert: float
    topspin_rpm: float; sample_points: int; fatigue_hours_72h: float; rest_days: int

@dataclass
class MatchConditions:
    tournament_name: str; tour: str; surface: str; cpi: float
    is_indoor: bool; elevation_m: float; temp_c: float; humidity_pct: float; best_of: int

def fetch_correlation_betas() -> Dict[str, float]:
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT vector_name, beta_weight FROM Feature_Correlations;")
        betas = {row[0]: row[1] for row in c.fetchall()}
        conn.close()
        return betas if betas else {"v_physics": 1.0, "v_thermo": 1.0, "v_bio": 1.0, "v_variance": 1.0}
    except Exception:
        return {"v_physics": 1.0, "v_thermo": 1.0, "v_bio": 1.0, "v_variance": 1.0}

def compute_causal_decomposition(p_a: PlayerProfile, p_b: PlayerProfile, cond: MatchConditions) -> dict:
    betas = fetch_correlation_betas()
    
    # 1. Physics (Kinematics)
    raw_phys = 0.0
    if p_a.handedness == 'L' and p_b.handedness == 'R' and p_b.backhand == '1H':
        raw_phys += 0.015 + (max(0.0, (p_a.topspin_rpm - 2600.0) / 1000.0) * 0.008)
    elif p_b.handedness == 'L' and p_a.handedness == 'R' and p_a.backhand == '1H':
        raw_phys -= 0.015 + (max(0.0, (p_b.topspin_rpm - 2600.0) / 1000.0) * 0.008)
    v_phys = raw_phys * betas.get("v_physics", 1.0)

    # 2. Thermo (Surface & Air Density)
    cpi_delta = (cond.cpi - 35.0) / 100.0
    air_den = (cond.temp_c * 0.08) + (cond.elevation_m / 1000.0) - (cond.humidity_pct * 0.04)
    raw_thermo = (p_a.serve_p - p_b.serve_p) * (cpi_delta + (air_den * 0.008)) * 0.85
    v_therm = raw_thermo * betas.get("v_thermo", 1.0)

    # 3. Bio (Fatigue)
    fatigue_a = max(0.0, p_a.fatigue_hours_72h - 4.5) * 0.012 * (0.35 if p_a.rest_days >= 2 else 1.0)
    fatigue_b = max(0.0, p_b.fatigue_hours_72h - 4.5) * 0.012 * (0.35 if p_b.rest_days >= 2 else 1.0)
    if cond.tour == 'ATF':
        fatigue_a *= 1.4; fatigue_b *= 1.4
    raw_bio = fatigue_b - fatigue_a
    v_bio = raw_bio * betas.get("v_bio", 1.0)

    # 4. Variance (Bayesian Shrinkage)
    raw_var = 0.0
    if cond.tour == 'ITF':
        raw_var = ((60.0 / (p_b.sample_points + 60.0)) * 0.02) - ((60.0 / (p_a.sample_points + 60.0)) * 0.02)
    v_var = raw_var * betas.get("v_variance", 1.0)

    net = v_phys + v_therm + v_bio + v_var
    return {
        "v_physics": round(v_phys, 4), "v_thermo": round(v_therm, 4),
        "v_bio": round(v_bio, 4), "v_variance": round(v_var, 4),
        "net_edge": round(net, 4)
    }

def calculate_point_win_prob(server_p: float, returner_q: float, tour: str, is_bp: bool=False, sv_bps: float=0.65, ret_bpc: float=0.40) -> float:
    num = server_p * (1.0 - returner_q)
    den = num + ((1.0 - server_p) * returner_q)
    base_p = num / den if den > 0 else server_p
    if is_bp:
        if tour == 'ATP': base_p += ((sv_bps - 0.65) - (ret_bpc - 0.40)) * 0.045
        elif tour == 'WTA': base_p -= (ret_bpc - 0.45) * 0.055
    bounds = {'ATP': (0.50, 0.85), 'WTA': (0.42, 0.74), 'ITF': (0.40, 0.78), 'ATF': (0.44, 0.80)}
    low, high = bounds.get(tour, (0.45, 0.80))
    return max(low, min(high, base_p))

def simulate_game(p_s, q_r, tour, s_bps, r_bpc):
    s, r = 0, 0
    while True:
        is_bp = (r >= 3 and (r - s) >= 1) or (r == 3 and s < 3)
        if random.random() < calculate_point_win_prob(p_s, q_r, tour, is_bp, s_bps, r_bpc): s += 1
        else: r += 1
        if s >= 4 and (s - r) >= 2: return 1, (s + r)
        if r >= 4 and (r - s) >= 2: return 0, (s + r)

def simulate_tiebreak(p_sa, p_sb, q_ra, q_rb, tour):
    a, b, pt = 1, 0, 1  
    while True:
        s_is_a = (pt % 4 in (1, 0)) if pt > 1 else True
        if s_is_a:
            if random.random() < calculate_point_win_prob(p_sa, q_rb, tour): a += 1
            else: b += 1
        else:
            if random.random() < calculate_point_win_prob(p_sb, q_ra, tour): b += 1
            else: a += 1
        pt += 1
        if a >= 7 and (a - b) >= 2: return 1, a, b
        if b >= 7 and (b - a) >= 2: return 2, a, b

def simulate_set(p_sa, p_sb, q_ra, q_rb, pa, pb, cond, s_starts_a):
    ga, gb, s_is_a, tb = 0, 0, s_starts_a, False
    while True:
        if s_is_a:
            w, _ = simulate_game(p_sa, q_rb, cond.tour, pa.bp_save, pb.bp_convert)
            if w: ga += 1 
            else: gb += 1
        else:
            w, _ = simulate_game(p_sb, q_ra, cond.tour, pb.bp_save, pa.bp_convert)
            if w: gb += 1 
            else: ga += 1
        s_is_a = not s_is_a
        if ga >= 6 and (ga - gb) >= 2: return 1, ga, gb, tb
        if gb >= 6 and (gb - ga) >= 2: return 2, ga, gb, tb
        if ga == 6 and gb == 6:
            tb = True
            tb_w, _, _ = simulate_tiebreak(p_sa, p_sb, q_ra, q_rb, cond.tour)
            if tb_w == 1: ga += 1; return 1, ga, gb, tb
            else: gb += 1; return 2, ga, gb, tb

def simulate_match_monte_carlo(p_a, p_b, cond, iterations=3500):
    v = compute_causal_decomposition(p_a, p_b, cond)
    epa = p_a.serve_p + (v["net_edge"] * 0.5)
    epb = p_b.serve_p - (v["net_edge"] * 0.5)
    eqa = p_a.return_q + (v["net_edge"] * 0.5)
    eqb = p_b.return_q - (v["net_edge"] * 0.5)

    if cond.tour == 'ITF':
        wa, wb = p_a.sample_points / (p_a.sample_points + 60.0), p_b.sample_points / (p_b.sample_points + 60.0)
        epa = (wa * epa) + ((1.0 - wa) * 0.62)
        epb = (wb * epb) + ((1.0 - wb) * 0.62)

    s2w = 3 if cond.best_of == 5 else 2
    w_a, w_b, tg_list, gd_list = 0, 0, [], []

    for _ in range(iterations):
        sa, sb, mga, mgb, ss_a = 0, 0, 0, 0, bool(random.getrandbits(1))
        while sa < s2w and sb < s2w:
            w, ga, gb, _ = simulate_set(epa, epb, eqa, eqb, p_a, p_b, cond, ss_a)
            mga += ga; mgb += gb; ss_a = not ss_a
            if w == 1: sa += 1 
            else: sb += 1
        if sa == s2w: w_a += 1
        else: w_b += 1
        tg_list.append(mga + mgb)
        gd_list.append(mga - mgb)

    tg_list.sort(); gd_list.sort()
    prob_a = round(w_a / iterations, 4)
    prob_b = round(w_b / iterations, 4)
    
    if prob_a == 0: ml_a = 10000; ml_b = -10000
    elif prob_b == 0: ml_a = -10000; ml_b = 10000
    else:
        ml_a = int((-(prob_a / prob_b) * 100) if prob_a >= 0.50 else ((prob_b / prob_a) * 100))
        ml_b = int((-(prob_b / prob_a) * 100) if prob_b >= 0.50 else ((prob_a / prob_b) * 100))

    return {
        "prob_a_win": prob_a, "prob_b_win": prob_b, "american_ml_a": ml_a, "american_ml_b": ml_b,
        "proj_median_total_games": tg_list[iterations // 2],
        "proj_mean_total_games": round(sum(tg_list) / iterations, 2),
        "proj_median_game_spread": gd_list[iterations // 2],
        "proj_mean_game_spread": round(sum(gd_list) / iterations, 2),
        "causal_vectors": v
    }

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL;")
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS Tournaments (id TEXT PRIMARY KEY, name TEXT, tour TEXT, surface TEXT, cpi REAL, is_indoor INTEGER, elevation_m REAL, best_of INTEGER);
    CREATE TABLE IF NOT EXISTS Players (id TEXT PRIMARY KEY, name TEXT, tour TEXT, handedness TEXT, backhand TEXT, serve_p REAL, return_q REAL, bp_save REAL, bp_convert REAL, topspin_rpm REAL, sample_points INTEGER, fatigue_hours_72h REAL, rest_days INTEGER, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS Daily_Card (match_id TEXT PRIMARY KEY, tournament_id TEXT, tour TEXT, player_a_id TEXT, player_b_id TEXT, temp_c REAL, humidity_pct REAL, status TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS Model_Forecasts (match_id TEXT PRIMARY KEY, tournament_id TEXT, tour TEXT, player_a TEXT, player_b TEXT, prob_a_win REAL, prob_b_win REAL, american_ml_a INTEGER, american_ml_b INTEGER, proj_total_games REAL, proj_game_spread REAL, v_physics REAL, v_thermo REAL, v_bio REAL, v_variance REAL, net_edge REAL, created_at TEXT);
    CREATE TABLE IF NOT EXISTS Historical_Forecasts (match_id TEXT PRIMARY KEY, tournament_id TEXT, tour TEXT, player_a TEXT, player_b TEXT, prob_a_win REAL, prob_b_win REAL, actual_winner TEXT, actual_total_games INTEGER, actual_game_spread INTEGER, brier_score REAL, evaluated_at TEXT);
    CREATE TABLE IF NOT EXISTS Feature_Correlations (vector_name TEXT PRIMARY KEY, beta_weight REAL, updated_at TEXT);
    """)
    
    # Initialize Correlation Betas to 1.00
    c.execute("INSERT OR IGNORE INTO Feature_Correlations VALUES ('v_physics', 1.0, datetime('now')), ('v_thermo', 1.0, datetime('now')), ('v_bio', 1.0, datetime('now')), ('v_variance', 1.0, datetime('now'));")
    conn.commit(); conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--init-db", action="store_true"); args = parser.parse_args()
    if args.init_db: init_db(); print("[DATABASE] Initialized Schema & Correlation Tables.")
