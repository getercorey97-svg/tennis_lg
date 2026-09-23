#!/usr/bin/env python3
"""
tennis_lg: Simulation-Free Factual Auditor & Parameter Learning Engine
- Scrapes official completed linescores across all circuits (Davis Cup, Challenger, ITF, ATP, WTA)
- Strictly compares pre-match model forecasts against empirical outcomes with zero simulations
- Calculates factual Brier scores, auto-settles wagers, and executes gradient descent on correlation weights (beta)
"""

import sqlite3
import requests
import re
from datetime import datetime, timezone
import math

DB_NAME = "tennis_lg.db"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def normalize_name(name: str) -> str:
    """Normalizes player names for fuzzy comparison across data feeds."""
    return re.sub(r'[^a-z0-9]', '', name.lower().replace(' ', ''))

def audit_completed_slate():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # 1. Fetch pending forecasts
    c.execute("SELECT * FROM Model_Forecasts;")
    active_forecasts = [dict(r) for r in c.fetchall()]
    if not active_forecasts:
        print("[POST-MORTEM] No active forecasts queued for auditing.")
        conn.close()
        return

    print(f"[POST-MORTEM] Checking completed outcomes for {len(active_forecasts)} queued fixtures...")

    # 2. Scrape live completed matches from TennisExplorer
    completed_results = []
    try:
        url = "https://www.tennisexplorer.com/matches/?type=all"
        res = requests.get(url, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            html = res.text
            tables = re.findall(r'<table[^>]*class="result"[^>]*>(.*?)</table>', html, re.DOTALL)
            for t in tables:
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.DOTALL)
                i = 0
                while i < len(rows):
                    r1 = rows[i]
                    if "t-name" not in r1:
                        i += 1
                        continue
                    if i + 1 >= len(rows):
                        break
                    r2 = rows[i+1]

                    p1_match = re.search(r'<td[^>]*class="t-name"[^>]*>.*?<a[^>]*>(.*?)</a>', r1, re.DOTALL)
                    p2_match = re.search(r'<td[^>]*class="t-name"[^>]*>.*?<a[^>]*>(.*?)</a>', r2, re.DOTALL)

                    res1 = re.search(r'<td[^>]*class="result"[^>]*>(.*?)</td>', r1, re.DOTALL)
                    res2 = re.search(r'<td[^>]*class="result"[^>]*>(.*?)</td>', r2, re.DOTALL)

                    sc1 = re.findall(r'<td[^>]*class="score"[^>]*>(.*?)</td>', r1, re.DOTALL)
                    sc2 = re.findall(r'<td[^>]*class="score"[^>]*>(.*?)</td>', r2, re.DOTALL)

                    if p1_match and p2_match and res1 and res2:
                        name1 = re.sub(r'<[^>]+>', '', p1_match.group(1)).strip()
                        name2 = re.sub(r'<[^>]+>', '', p2_match.group(1)).strip()
                        v1, v2 = res1.group(1).strip(), res2.group(1).strip()

                        if v1.isdigit() and v2.isdigit():
                            s1, s2 = int(v1), int(v2)
                            if s1 >= 2 or s2 >= 2:
                                winner = name1 if s1 > s2 else name2
                                loser = name2 if s1 > s2 else name1
                                games1 = sum(int(x.strip()) for x in sc1 if x.strip().isdigit())
                                games2 = sum(int(x.strip()) for x in sc2 if x.strip().isdigit())
                                total_games = games1 + games2
                                spread = (games1 - games2) if winner == name1 else (games2 - games1)

                                completed_results.append({
                                    "p1": name1,
                                    "p2": name2,
                                    "winner": winner,
                                    "loser": loser,
                                    "total_games": total_games if total_games > 0 else 20,
                                    "spread": spread
                                })
                    i += 2
    except Exception as e:
        print(f"[POST-MORTEM ERROR] TennisExplorer scraper failure: {e}")

    print(f"[POST-MORTEM] Scraped {len(completed_results)} completed matches from live boards.")

    # 3. Simulation-Free Comparison & Learning
    audited_count = 0
    c.execute("SELECT vector_name, beta_weight FROM Feature_Correlations;")
    betas = {r[0]: r[1] for r in c.fetchall()}

    for f in active_forecasts:
        f_p1_norm = normalize_name(f['player_a'])
        f_p2_norm = normalize_name(f['player_b'])

        for res in completed_results:
            r_p1_norm = normalize_name(res['p1'])
            r_p2_norm = normalize_name(res['p2'])

            # Verify matchup match
            if (f_p1_norm in r_p1_norm or r_p1_norm in f_p1_norm) and (f_p2_norm in r_p2_norm or r_p2_norm in f_p2_norm):
                actual_winner = f['player_a'] if normalize_name(res['winner']) == r_p1_norm else f['player_b']
                
                # Factual Brier Score calculation (zero simulation)
                y_a = 1.0 if actual_winner == f['player_a'] else 0.0
                brier = round((f['prob_a_win'] - y_a) ** 2, 4)

                # Record in Historical_Forecasts
                c.execute("""
                    INSERT OR REPLACE INTO Historical_Forecasts (
                        match_id, tournament_id, tour, player_a, player_b,
                        prob_a_win, prob_b_win, actual_winner, actual_total_games,
                        actual_game_spread, brier_score, evaluated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    f['match_id'], f['tournament_id'], f['tour'], f['player_a'], f['player_b'],
                    f['prob_a_win'], f['prob_b_win'], actual_winner, res['total_games'],
                    res['spread'], brier, now_ts
                ))

                # Auto-Settle pending wagers
                c.execute("""
                    SELECT id, selection, odds, units FROM Betting_Logs
                    WHERE match_id = ? AND status = 'PENDING';
                """, (f['match_id'],))
                for b_id, sel, odds, units in c.fetchall():
                    if sel == actual_winner:
                        payout = (units * (odds / 100.0)) if odds > 0 else (units * (100.0 / abs(odds)))
                        c.execute("UPDATE Betting_Logs SET status = 'WON', actual_winner = ?, payout_units = ? WHERE id = ?;", (actual_winner, round(payout, 2), b_id))
                    else:
                        c.execute("UPDATE Betting_Logs SET status = 'LOST', actual_winner = ?, payout_units = ? WHERE id = ?;", (actual_winner, -units, b_id))

                # Gradient Descent Parameter Update on Betas (Learning Ledger)
                # Error gradient: e = actual (y_a) - predicted (prob_a_win)
                err = y_a - f['prob_a_win']
                learning_rate = 0.005

                vectors = [
                    ('v_physics', f['v_physics']),
                    ('v_thermo', f['v_thermo']),
                    ('v_bio', f['v_bio']),
                    ('v_variance', f['v_variance'])
                ]

                for v_name, v_val in vectors:
                    old_beta = betas.get(v_name, 1.0)
                    delta = learning_rate * err * (v_val if v_val != 0 else 0.5)
                    new_beta = round(max(0.5, min(2.0, old_beta + delta)), 4)
                    betas[v_name] = new_beta

                    c.execute("UPDATE Feature_Correlations SET beta_weight = ?, updated_at = ? WHERE vector_name = ?;", (new_beta, now_ts, v_name))
                    c.execute("""
                        INSERT INTO Learning_Log (parameter, old_val, new_val, delta, reason, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?);
                    """, (v_name, old_beta, new_beta, round(delta, 4), f"Factual audit error ({err:+.3f}) on {f['player_a']} vs {f['player_b']}", now_ts))

                # Remove completed match from Daily_Card and Model_Forecasts
                c.execute("DELETE FROM Daily_Card WHERE match_id = ?;", (f['match_id'],))
                c.execute("DELETE FROM Model_Forecasts WHERE match_id = ?;", (f['match_id'],))
                audited_count += 1
                break

    conn.commit()
    conn.close()
    print(f"[POST-MORTEM SUCCESS] Audited {audited_count} finished matches, updated betas, and resolved pending bets.")

if __name__ == "__main__":
    audit_completed_slate()
