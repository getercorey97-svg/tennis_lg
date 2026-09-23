#!/usr/bin/env python3
"""
tennis_lg: Live Factual Auditor & Learning Loop
Parses completed scores across Davis Cup, Challenger, ITF, ATP, and WTA circuits,
computes simulation-free Brier scores, triggers gradient descent (beta shifts),
and settles active wagers.
"""

import sqlite3
import requests
import re
from datetime import datetime, timezone

DB_NAME = "tennis_lg.db"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def normalize(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', name.lower().replace(' ', ''))

def audit_live_outcomes():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    c.execute("SELECT * FROM Model_Forecasts;")
    active_forecasts = [dict(r) for r in c.fetchall()]
    if not active_forecasts:
        print("[POST-MORTEM] No active forecasts queued.")
        conn.close()
        return

    print(f"[POST-MORTEM] Scanning live scoreboards for {len(active_forecasts)} fixtures...")

    completed_matches = []
    try:
        url = "https://www.tennisexplorer.com/matches/?type=all"
        res = requests.get(url, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            html = res.text
            # Extract row pairs
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
            i = 0
            while i < len(rows) - 1:
                r1, r2 = rows[i], rows[i+1]
                if 't-name' not in r1 or 't-name' not in r2:
                    i += 1
                    continue

                p1_match = re.search(r'class="t-name"[^>]*>.*?<a[^>]*>(.*?)</a>', r1, re.DOTALL)
                p2_match = re.search(r'class="t-name"[^>]*>.*?<a[^>]*>(.*?)</a>', r2, re.DOTALL)
                if not p1_match or not p2_match:
                    i += 1
                    continue

                p1_name = re.sub(r'<[^>]+>', '', p1_match.group(1)).strip()
                p2_name = re.sub(r'<[^>]+>', '', p2_match.group(1)).strip()

                # Extract numeric game scores per set
                sc1 = [int(s) for s in re.findall(r'<td[^>]*class="score[^"]*"[^>]*>\s*(\d+)\s*</td>', r1)]
                sc2 = [int(s) for s in re.findall(r'<td[^>]*class="score[^"]*"[^>]*>\s*(\d+)\s*</td>', r2)]

                if len(sc1) >= 2 and len(sc2) >= 2:
                    s1_won = sum(1 for a, b in zip(sc1, sc2) if a > b)
                    s2_won = sum(1 for a, b in zip(sc1, sc2) if b > a)

                    # Finished match (best-of-3 standard)
                    if s1_won >= 2 or s2_won >= 2:
                        winner = p1_name if s1_won > s2_won else p2_name
                        loser = p2_name if s1_won > s2_won else p1_name
                        tot_games = sum(sc1) + sum(sc2)
                        spread = abs(sum(sc1) - sum(sc2))

                        completed_matches.append({
                            "p1": p1_name,
                            "p2": p2_name,
                            "winner": winner,
                            "loser": loser,
                            "total_games": tot_games if tot_games > 0 else 22,
                            "spread": spread
                        })
                i += 2
    except Exception as e:
        print(f"[POST-MORTEM ERROR] Scraper exception: {e}")

    print(f"[POST-MORTEM] Scraped {len(completed_matches)} verified finished matches.")

    c.execute("SELECT vector_name, beta_weight FROM Feature_Correlations;")
    betas = {r[0]: r[1] for r in c.fetchall()}
    audited = 0

    for f in active_forecasts:
        f1_norm = normalize(f['player_a'])
        f2_norm = normalize(f['player_b'])

        for m in completed_matches:
            m1_norm = normalize(m['p1'])
            m2_norm = normalize(m['p2'])

            if (f1_norm in m1_norm or m1_norm in f1_norm) and (f2_norm in m2_norm or m2_norm in f2_norm):
                actual_winner = f['player_a'] if normalize(m['winner']) == f1_norm else f['player_b']
                y_a = 1.0 if actual_winner == f['player_a'] else 0.0
                brier = round((f['prob_a_win'] - y_a) ** 2, 4)

                # 1. Record in Historical Forecasts ledger
                c.execute("""
                    INSERT OR REPLACE INTO Historical_Forecasts (
                        match_id, tournament_id, tour, player_a, player_b,
                        prob_a_win, prob_b_win, actual_winner, actual_total_games,
                        actual_game_spread, brier_score, evaluated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    f['match_id'], f['tournament_id'], f['tour'], f['player_a'], f['player_b'],
                    f['prob_a_win'], f['prob_b_win'], actual_winner, m['total_games'],
                    m['spread'], brier, now_ts
                ))

                # 2. Auto-Settle pending wagers
                c.execute("SELECT id, selection, odds, units FROM Betting_Logs WHERE match_id = ? AND status = 'PENDING';", (f['match_id'],))
                for b_id, sel, odds, units in c.fetchall():
                    if sel == actual_winner:
                        payout = (units * (odds / 100.0)) if odds > 0 else (units * (100.0 / abs(odds)))
                        c.execute("UPDATE Betting_Logs SET status = 'WON', actual_winner = ?, payout_units = ? WHERE id = ?;", (actual_winner, round(payout, 2), b_id))
                    else:
                        c.execute("UPDATE Betting_Logs SET status = 'LOST', actual_winner = ?, payout_units = ? WHERE id = ?;", (actual_winner, -units, b_id))

                # 3. Gradient Descent on Geter Principle Correlation Weights
                err = y_a - f['prob_a_win']
                lr = 0.005
                vectors = [('v_physics', f['v_physics']), ('v_thermo', f['v_thermo']), ('v_bio', f['v_bio']), ('v_variance', f['v_variance'])]
                for v_name, v_val in vectors:
                    old_b = betas.get(v_name, 1.0)
                    delta = lr * err * (v_val if v_val != 0 else 0.5)
                    new_b = round(max(0.5, min(2.0, old_b + delta)), 4)
                    betas[v_name] = new_b
                    c.execute("UPDATE Feature_Correlations SET beta_weight = ?, updated_at = ? WHERE vector_name = ?;", (new_b, now_ts, v_name))
                    c.execute("INSERT INTO Learning_Log (parameter, old_val, new_val, delta, reason, updated_at) VALUES (?, ?, ?, ?, ?, ?);",
                              (v_name, old_b, new_b, round(delta, 4), f"Audit error ({err:+.3f}) on {f['player_a']} vs {f['player_b']}", now_ts))

                # 4. Remove finished match from active board
                c.execute("DELETE FROM Daily_Card WHERE match_id = ?;", (f['match_id'],))
                c.execute("DELETE FROM Model_Forecasts WHERE match_id = ?;", (f['match_id'],))
                audited += 1
                break

    conn.commit()
    conn.close()
    print(f"[POST-MORTEM COMPLETE] Audited {audited} finished matches. Learning Ledger updated.")

if __name__ == "__main__":
    audit_live_outcomes()
