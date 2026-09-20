#!/usr/bin/env python3
"""
tennis_lg: Markov Point Simulation & The Geter Principle Decomposition
Simulates discrete tennis path interactions across ATP, WTA, ITF, and ATF tours.
"""

import sqlite3
import random
import math
from datetime import datetime

DB_NAME = "tennis_lg.db"

def calculate_decomposed_vectors(surface, cpi, temp_c, humidity_pct, p_a, p_b, betas):
    surface_mod = 1.05 if surface == 'Grass' else (0.94 if surface == 'Clay' else 1.0)
    v_phys = (p_a['serve_p'] - p_b['serve_p']) * (cpi / 38.0) * surface_mod
    
    air_density_mod = (temp_c / 25.0) * (1.0 - (humidity_pct / 200.0))
    v_therm = (p_a['topspin_rpm'] - p_b['topspin_rpm']) / 10000.0 * air_density_mod
    
    fatigue_delta = (p_b['fatigue_hours_72h'] - p_a['fatigue_hours_72h']) * 0.04
    rest_delta = (p_a['rest_days'] - p_b['rest_days']) * 0.015
    v_bio = fatigue_delta + rest_delta
    
    sample_weight = math.sqrt(min(p_a['sample_points'], p_b['sample_points'])) / 60.0
    v_var = (p_a['bp_save'] - p_b['bp_convert']) * min(1.0, sample_weight)

    net_edge = (
        (v_phys * betas.get('v_physics', 1.042)) +
        (v_therm * betas.get('v_thermo', 0.985)) +
        (v_bio * betas.get('v_bio', 1.021)) +
        (v_var * betas.get('v_variance', 0.954))
    )
    return v_phys, v_therm, v_bio, v_var, net_edge

def simulate_match_path(prob_a_hold, prob_b_hold, best_of=3):
    sets_to_win = 2 if best_of == 3 else 3
    sets_a, sets_b = 0, 0
    total_games_a, total_games_b = 0, 0

    while sets_a < sets_to_win and sets_b < sets_to_win:
        games_a, games_b = 0, 0
        server = 'A' if (sets_a + sets_b) % 2 == 0 else 'B'

        while True:
            if games_a >= 6 and games_a - games_b >= 2:
                sets_a += 1; break
            if games_b >= 6 and games_b - games_a >= 2:
                sets_b += 1; break
                
            if games_a == 6 and games_b == 6:
                p_tb_a = (prob_a_hold + (1.0 - prob_b_hold)) / 2.0
                tb_pts_a, tb_pts_b = 0, 0
                while True:
                    if random.random() < p_tb_a: tb_pts_a += 1
                    else: tb_pts_b += 1
                    if tb_pts_a >= 7 and tb_pts_a - tb_pts_b >= 2:
                        games_a += 1; sets_a += 1; break
                    if tb_pts_b >= 7 and tb_pts_b - tb_pts_a >= 2:
                        games_b += 1; sets_b += 1; break
                break

            if server == 'A':
                if random.random() < prob_a_hold: games_a += 1
                else: games_b += 1
                server = 'B'
            else:
                if random.random() < prob_b_hold: games_b += 1
                else: games_a += 1
                server = 'A'

        total_games_a += games_a
        total_games_b += games_b

    winner = 'A' if sets_a > sets_b else 'B'
    return winner, total_games_a, total_games_b

def run_monte_carlo(match_fixture, iterations=2500):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Defensive Tournament Resolution
    c.execute("SELECT * FROM Tournaments WHERE id = ?;", (match_fixture['tournament_id'],))
    t_row = c.fetchone()
    if not t_row:
        c.execute("""
            INSERT OR IGNORE INTO Tournaments (id, name, tour, surface, cpi, is_indoor, elevation_m, best_of)
            VALUES (?, ?, ?, 'Hard', 38.0, 0, 15.0, 3);
        """, (match_fixture['tournament_id'], match_fixture['tournament_id'].replace('_', ' '), match_fixture['tour']))
        conn.commit()
        c.execute("SELECT * FROM Tournaments WHERE id = ?;", (match_fixture['tournament_id'],))
        t_row = c.fetchone()
    t = dict(t_row)

    # Defensive Player A Resolution
    c.execute("SELECT * FROM Players WHERE id = ?;", (match_fixture['player_a_id'],))
    pa_row = c.fetchone()
    if not pa_row:
        p_name = match_fixture['player_a_id'].split('_', 1)[-1].replace('_', ' ')
        c.execute("""
            INSERT OR IGNORE INTO Players (id, name, tour, handedness, backhand, serve_p, return_q, bp_save, bp_convert, topspin_rpm, sample_points, fatigue_hours_72h, rest_days, updated_at)
            VALUES (?, ?, ?, 'R', '2H', 0.66, 0.37, 0.65, 0.40, 2800, 200, 0.0, 3, datetime('now'));
        """, (match_fixture['player_a_id'], p_name, match_fixture['tour']))
        conn.commit()
        c.execute("SELECT * FROM Players WHERE id = ?;", (match_fixture['player_a_id'],))
        pa_row = c.fetchone()
    p_a = dict(pa_row)

    # Defensive Player B Resolution
    c.execute("SELECT * FROM Players WHERE id = ?;", (match_fixture['player_b_id'],))
    pb_row = c.fetchone()
    if not pb_row:
        p_name = match_fixture['player_b_id'].split('_', 1)[-1].replace('_', ' ')
        c.execute("""
            INSERT OR IGNORE INTO Players (id, name, tour, handedness, backhand, serve_p, return_q, bp_save, bp_convert, topspin_rpm, sample_points, fatigue_hours_72h, rest_days, updated_at)
            VALUES (?, ?, ?, 'R', '2H', 0.66, 0.37, 0.65, 0.40, 2800, 200, 0.0, 3, datetime('now'));
        """, (match_fixture['player_b_id'], p_name, match_fixture['tour']))
        conn.commit()
        c.execute("SELECT * FROM Players WHERE id = ?;", (match_fixture['player_b_id'],))
        pb_row = c.fetchone()
    p_b = dict(pb_row)

    c.execute("SELECT vector_name, beta_weight FROM Feature_Correlations;")
    betas = {row['vector_name']: row['beta_weight'] for row in c.fetchall()}
    conn.close()

    v_phys, v_therm, v_bio, v_var, net_edge = calculate_decomposed_vectors(
        t['surface'], t['cpi'], match_fixture['temp_c'], match_fixture['humidity_pct'], p_a, p_b, betas
    )

    p_a_hold = max(0.40, min(0.92, p_a['serve_p'] - (p_b['return_q'] - 0.35) + (net_edge * 0.12)))
    p_b_hold = max(0.40, min(0.92, p_b['serve_p'] - (p_a['return_q'] - 0.35) - (net_edge * 0.12)))

    wins_a, wins_b = 0, 0
    tot_games_list = []
    spread_list = []

    for _ in range(iterations):
        winner, g_a, g_b = simulate_match_path(p_a_hold, p_b_hold, best_of=t['best_of'])
        if winner == 'A': wins_a += 1
        else: wins_b += 1
        tot_games_list.append(g_a + g_b)
        spread_list.append(g_a - g_b)

    prob_a = round(wins_a / iterations, 4)
    prob_b = round(wins_b / iterations, 4)
    
    ml_a = int(-100 * (prob_a / (1.0 - prob_a))) if prob_a >= 0.50 else int(100 * ((1.0 - prob_a) / prob_a))
    ml_b = int(-100 * (prob_b / (1.0 - prob_b))) if prob_b >= 0.50 else int(100 * ((1.0 - prob_b) / prob_b))

    median_tot = round(sum(tot_games_list) / len(tot_games_list), 1)
    median_spread = round(sum(spread_list) / len(spread_list), 1)

    return {
        'match_id': match_fixture['match_id'],
        'tournament_id': t['id'],
        'tour': match_fixture['tour'],
        'player_a': p_a['name'],
        'player_b': p_b['name'],
        'prob_a_win': prob_a,
        'prob_b_win': prob_b,
        'american_ml_a': ml_a,
        'american_ml_b': ml_b,
        'proj_total_games': median_tot,
        'proj_game_spread': median_spread,
        'v_physics': round(v_phys, 4),
        'v_thermo': round(v_therm, 4),
        'v_bio': round(v_bio, 4),
        'v_variance': round(v_var, 4),
        'net_edge': round(net_edge, 4),
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
