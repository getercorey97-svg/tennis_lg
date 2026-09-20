#!/usr/bin/env python3
"""
tennis_lg: Multi-Tour Operations Hub
- Groups matches cleanly by active tournament
- Provides dedicated 'Active Tournaments' view with participant rosters
- Dynamic auto-sync and wager settlement
"""

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from contextlib import asynccontextmanager
from collections import defaultdict
import asyncio
import subprocess
import sqlite3
import os
import time
import uvicorn
from datetime import datetime

DB_NAME = "tennis_lg.db"
LAST_RUN = 0.0

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def execute_pipeline_refresh():
    global LAST_RUN
    now = time.time()
    if now - LAST_RUN < 45:
        return
    LAST_RUN = now
    try:
        subprocess.run(["python3", "scraper.py"], check=False)
        subprocess.run(["python3", "run_pipeline.py"], check=False)
        subprocess.run(["python3", "post_mortem.py"], check=False)
    except Exception as e:
        print(f"[SYNC ERROR] {e}")

async def background_loop():
    await asyncio.sleep(5)
    while True:
        execute_pipeline_refresh()
        await asyncio.sleep(900)

@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = asyncio.create_task(background_loop())
    yield
    worker.cancel()

app = FastAPI(title="tennis_lg Operations Hub", lifespan=lifespan)

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

@app.post("/api/sync/on_open")
def sync_on_open(background_tasks: BackgroundTasks):
    execute_pipeline_refresh()
    return JSONResponse({"status": "synced"})

@app.post("/api/bet/log")
async def log_bet(request: Request):
    data = await request.json()
    conn = get_db()
    conn.execute("""
        INSERT INTO Betting_Logs (match_id, tour, selection, wager_type, odds, units, logged_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (data['match_id'], data['tour'], data['selection'], data.get('wager_type', 'Moneyline'), 
          int(data['odds']), float(data['units']), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return JSONResponse({"status": "logged"})

@app.get("/", response_class=HTMLResponse)
def dashboard():
    conn = get_db()
    c = conn.cursor()

    # 1. Matches with Tournament Metadata
    c.execute("""
        SELECT f.*, COALESCE(t.name, f.tournament_id) as tourney_name, COALESCE(t.surface, 'Hard') as tourney_surface
        FROM Model_Forecasts f
        LEFT JOIN Tournaments t ON f.tournament_id = t.id
        ORDER BY t.name ASC, f.created_at DESC;
    """)
    forecasts = [dict(row) for row in c.fetchall()]

    # Group matches by tournament
    grouped_matches = defaultdict(list)
    for f in forecasts:
        grouped_matches[(f['tourney_name'], f['tour'], f['tourney_surface'])].append(f)

    # 2. Active Tournaments List with Active Player Counts
    c.execute("""
        SELECT t.id, t.name, t.tour, t.surface, COUNT(d.match_id) as match_count
        FROM Tournaments t
        JOIN Daily_Card d ON t.id = d.tournament_id
        GROUP BY t.id
        ORDER BY t.name ASC;
    """)
    active_tourneys = [dict(row) for row in c.fetchall()]

    # 3. Model Weights & Learning Logs
    c.execute("SELECT * FROM Feature_Correlations;")
    betas = {row['vector_name']: row['beta_weight'] for row in c.fetchall()}
    
    c.execute("SELECT * FROM Learning_Log ORDER BY id DESC LIMIT 50;")
    learning_events = [dict(row) for row in c.fetchall()]

    # 4. Factual Audits (Excluding mock dummy records)
    c.execute("SELECT * FROM Historical_Forecasts WHERE player_a NOT LIKE 'Player_%' ORDER BY evaluated_at DESC LIMIT 500;")
    raw_audits = [dict(row) for row in c.fetchall()]
    audits = []
    correct_count = 0
    total_brier = 0.0
    for a in raw_audits:
        pred = a['player_a'] if a['prob_a_win'] >= a['prob_b_win'] else a['player_b']
        hit = (pred == a['actual_winner'])
        if hit: correct_count += 1
        total_brier += a['brier_score']
        audits.append({**a, "predicted_winner": pred, "hit": hit})

    audit_total = len(audits)
    accuracy_rate = round((correct_count / audit_total * 100), 1) if audit_total > 0 else 0.0
    mean_brier = round(total_brier / audit_total, 4) if audit_total > 0 else 0.0

    # 5. Betting Performance
    c.execute("SELECT * FROM Betting_Logs ORDER BY logged_at DESC;")
    bets = [dict(row) for row in c.fetchall()]
    net_units = round(sum(b['payout_units'] for b in bets if b['status'] in ('WON', 'LOST')), 2)
    resolved = sum(1 for b in bets if b['status'] in ('WON', 'LOST'))
    won = sum(1 for b in bets if b['status'] == 'WON')
    win_rate = round((won / resolved * 100), 1) if resolved > 0 else 0.0
    conn.close()

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0, viewport-fit=cover">
        <meta name="theme-color" content="#000000">
        <title>tennis_lg | Operations Hub</title>
        <style>
            :root {{
                --bg: #000000;
                --card: #121212;
                --text: #f5f5f7;
                --muted: #8e8e93;
                --blue: #0a84ff;
                --green: #30d158;
                --red: #ff453a;
                --purple: #bf5af2;
                --border: #2c2c2e;
            }}
            * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; font-family: system-ui, -apple-system, sans-serif; }}
            body {{ background: var(--bg); color: var(--text); margin: 0; padding: 16px 16px 80px 16px; }}
            h1 {{ font-size: 1.3rem; margin: 16px 0 4px 0; font-weight: 800; }}
            .sub-status {{ font-size: 0.75rem; color: var(--muted); font-family: monospace; display: flex; align-items: center; gap: 6px; margin-bottom: 16px; }}
            .dot {{ width: 8px; height: 8px; background: var(--green); border-radius: 50%; }}
            .tabs {{ display: flex; gap: 8px; margin-bottom: 16px; overflow-x: auto; }}
            .tab-btn {{ background: var(--card); border: 1px solid var(--border); color: var(--muted); padding: 10px 14px; border-radius: 12px; font-size: 0.85rem; font-weight: 700; cursor: pointer; white-space: nowrap; }}
            .tab-btn.active {{ background: var(--blue); color: white; border-color: var(--blue); }}
            .search-box {{ width: 100%; background: var(--card); border: 1px solid var(--border); color: var(--text); padding: 12px 14px; border-radius: 14px; font-size: 0.95rem; margin-bottom: 14px; outline: none; }}
            .metrics-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 18px; }}
            .metric-pill {{ background: var(--card); border: 1px solid var(--border); padding: 10px 6px; border-radius: 12px; text-align: center; }}
            .metric-title {{ font-size: 0.65rem; color: var(--muted); font-weight: 700; text-transform: uppercase; }}
            .metric-val {{ font-size: 1rem; font-weight: 800; margin-top: 4px; font-family: monospace; }}
            
            .tourney-banner {{
                background: #1c1c1e; border: 1px solid var(--border); border-left: 4px solid var(--blue);
                padding: 10px 14px; border-radius: 12px; margin: 20px 0 10px 0; display: flex; justify-content: space-between; align-items: center;
            }}
            .tourney-title {{ font-size: 0.95rem; font-weight: 800; color: var(--text); }}
            .tourney-badge {{ font-size: 0.65rem; font-weight: 800; padding: 3px 8px; border-radius: 6px; background: var(--purple); color: white; }}
            .surface-tag {{ font-size: 0.7rem; color: var(--muted); margin-left: 6px; }}

            .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 14px; margin-bottom: 10px; }}
            .card-header {{ display: flex; justify-content: space-between; align-items: center; font-weight: 700; font-size: 0.95rem; margin-bottom: 8px; }}
            .row {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 0.88rem; }}
            .row:last-of-type {{ border-bottom: none; }}
            .lbl {{ color: var(--muted); }}
            .green {{ color: var(--green); font-weight: 700; }}
            .red {{ color: var(--red); font-weight: 700; }}
            .btn-action {{ width: 100%; background: #1f2937; border: 1px solid #374151; color: var(--text); padding: 10px; border-radius: 12px; font-weight: 700; font-size: 0.85rem; margin-top: 10px; cursor: pointer; }}
        </style>
        <script>
            function setTab(name) {{
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-pane').forEach(p => p.style.display = 'none');
                document.getElementById('btn-' + name).classList.add('active');
                document.getElementById('pane-' + name).style.display = 'block';
            }}
            function filterAll() {{
                const q = document.getElementById('search-input').value.toLowerCase();
                document.querySelectorAll('.match-card').forEach(c => {{
                    c.style.display = c.getAttribute('data-search').toLowerCase().includes(q) ? 'block' : 'none';
                }});
            }}
            async function logWager(matchId, tour, sel, odds) {{
                const units = prompt(`Log Wager on ${{sel}} (${{odds > 0 ? '+' : ''}}${{odds}}):`, "1.0");
                if (!units || isNaN(units)) return;
                await fetch('/api/bet/log', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ match_id: matchId, tour: tour, selection: sel, wager_type: 'Moneyline', odds: odds, units: parseFloat(units) }})
                }});
                window.location.reload();
            }}
            document.addEventListener('visibilitychange', async () => {{
                if (document.visibilityState === 'visible') {{
                    const res = await fetch('/api/sync/on_open', {{ method: 'POST' }});
                    if (res.ok) window.location.reload();
                }}
            }});
        </script>
    </head>
    <body>
        <h1>tennis_lg Operations Hub</h1>
        <div class="sub-status"><span class="dot"></span> Live Tournament Calendar Online</div>

        <div class="metrics-grid">
            <div class="metric-pill"><div class="metric-title">Accuracy</div><div class="metric-val green">{accuracy_rate}%</div></div>
            <div class="metric-pill"><div class="metric-title">Audits</div><div class="metric-val">{audit_total}</div></div>
            <div class="metric-pill"><div class="metric-title">Mean Brier</div><div class="metric-val">{mean_brier}</div></div>
            <div class="metric-pill"><div class="metric-title">Net Units</div><div class="metric-val {'green' if net_units >= 0 else 'red'}">{net_units:+.2f}u</div></div>
        </div>

        <div class="tabs">
            <button id="btn-slate" class="tab-btn active" onclick="setTab('slate')">Predictions Slate ({len(forecasts)})</button>
            <button id="btn-tourneys" class="tab-btn" onclick="setTab('tourneys')">Active Tournaments ({len(active_tourneys)})</button>
            <button id="btn-learning" class="tab-btn" onclick="setTab('learning')">Learning Ledger ({len(learning_events)})</button>
            <button id="btn-audits" class="tab-btn" onclick="setTab('audits')">Factual Audits ({audit_total})</button>
            <button id="btn-bets" class="tab-btn" onclick="setTab('bets')">Betting Log ({len(bets)})</button>
        </div>

        <!-- TAB 1: PREDICTIONS GROUPED BY TOURNAMENT -->
        <div id="pane-slate" class="tab-pane">
            <input type="text" id="search-input" class="search-box" placeholder="🔍 Search tournament, player, or tour level..." onkeyup="filterAll()">
    """
    if not grouped_matches:
        html += "<div class='card'><div class='lbl'>Scanning official scoreboards for active tournament fixtures...</div></div>"

    for (t_name, t_tour, t_surface), matches in grouped_matches.items():
        html += f"""
        <div class="tourney-banner">
            <div>
                <span class="tourney-title">{t_name}</span>
                <span class="surface-tag">• {t_surface} Court</span>
            </div>
            <span class="tourney-badge">{t_tour}</span>
        </div>
        """
        for f in matches:
            fav = f['player_a'] if f['prob_a_win'] >= 0.5 else f['player_b']
            fav_prob = max(f['prob_a_win'], f['prob_b_win']) * 100
            fav_ml = f['american_ml_a'] if fav == f['player_a'] else f['american_ml_b']
            fav_ml_str = f"+{fav_ml}" if fav_ml > 0 else str(fav_ml)
            html += f"""
            <div class="card match-card" data-search="{t_name} {f['tour']} {f['player_a']} {f['player_b']}">
                <div class="card-header"><span>{f['player_a']} vs {f['player_b']}</span></div>
                <div class="row"><span class="lbl">Predicted Outright</span> <span class="green">{fav} ({fav_prob:.1f}%)</span></div>
                <div class="row"><span class="lbl">Fair FanDuel ML</span> <span>{fav_ml_str}</span></div>
                <div class="row"><span class="lbl">Projected Spread</span> <span>{f['proj_game_spread']:+.1f} Games</span></div>
                <div class="row"><span class="lbl">Total Games Line</span> <span>{f['proj_total_games']}</span></div>
                <button class="btn-action" onclick="logWager('{f['match_id']}', '{f['tour']}', '{fav}', {fav_ml})">+ Log {fav} ({fav_ml_str}) Bet</button>
            </div>
            """

    html += f"""
        </div>

        <!-- TAB 2: ACTIVE TOURNAMENTS HUB -->
        <div id="pane-tourneys" class="tab-pane" style="display: none;">
    """
    if not active_tourneys:
        html += "<div class='card'><div class='lbl'>No active tournaments currently populated.</div></div>"
    for at in active_tourneys:
        html += f"""
        <div class="card">
            <div class="card-header">
                <span>{at['name']}</span>
                <span class="tourney-badge">{at['tour']}</span>
            </div>
            <div class="row"><span class="lbl">Court Surface</span> <span>{at['surface']}</span></div>
            <div class="row"><span class="lbl">Active Scheduled Matches</span> <span class="green">{at['match_count']} Fixtures</span></div>
        </div>
        """

    html += f"""
        </div>

        <!-- TAB 3: LEARNING LEDGER -->
        <div id="pane-learning" class="tab-pane" style="display: none;">
            <div class="card">
                <div class="card-header"><span>Learned Correlation Weights (β)</span></div>
                <div class="row"><span class="lbl">Physics Vector</span> <span style="font-family: monospace;">{betas.get('v_physics', 1.085):.4f}</span></div>
                <div class="row"><span class="lbl">Thermo Vector</span> <span style="font-family: monospace;">{betas.get('v_thermo', 0.995):.4f}</span></div>
                <div class="row"><span class="lbl">Fatigue Vector</span> <span style="font-family: monospace;">{betas.get('v_bio', 1.015):.4f}</span></div>
                <div class="row"><span class="lbl">Variance Vector</span> <span style="font-family: monospace;">{betas.get('v_variance', 0.965):.4f}</span></div>
            </div>
    """
    for e in learning_events:
        delta_cls = "green" if e['delta'] >= 0 else "red"
        html += f"""
        <div class="card">
            <div class="card-header"><span>{e['parameter']}</span><span class="{delta_cls}">{e['delta']:+.4f}</span></div>
            <div class="row"><span class="lbl">Shift</span> <span>{e['old_val']:.4f} → {e['new_val']:.4f}</span></div>
            <div class="row"><span class="lbl">Context</span> <span style="font-size: 0.8rem;">{e['reason']}</span></div>
        </div>
        """

    html += f"""
        </div>

        <!-- TAB 4: FACTUAL AUDITS -->
        <div id="pane-audits" class="tab-pane" style="display: none;">
    """
    for a in audits:
        verdict = "<span style='color: var(--green); font-weight: 800;'>HIT ✅</span>" if a['hit'] else "<span style='color: var(--red); font-weight: 800;'>MISS ❌</span>"
        html += f"""
        <div class="card">
            <div class="card-header"><span>{a['player_a']} vs {a['player_b']}</span>{verdict}</div>
            <div class="row"><span class="lbl">Model Pick</span> <span>{a['predicted_winner']} ({(max(a['prob_a_win'], a['prob_b_win'])*100):.1f}%)</span></div>
            <div class="row"><span class="lbl">Official Winner</span> <span class="green">{a['actual_winner']}</span></div>
            <div class="row"><span class="lbl">Actual Games / Spread</span> <span>{a['actual_total_games']} ({a['actual_game_spread']:+d})</span></div>
            <div class="row"><span class="lbl">Brier Score</span> <span>{a['brier_score']:.4f}</span></div>
        </div>
        """

    html += f"""
        </div>

        <!-- TAB 5: BETTING LOGS -->
        <div id="pane-bets" class="tab-pane" style="display: none;">
            <div class="card">
                <div class="card-header"><span>Performance</span> <span class="green">{win_rate}% Win Rate</span></div>
                <div class="row"><span class="lbl">Settled</span> <span>{resolved}</span></div>
                <div class="row"><span class="lbl">Net Return</span> <span class="{'green' if net_units >= 0 else 'red'}">{net_units:+.2f}u</span></div>
            </div>
    """
    for b in bets:
        payout = f"{b['payout_units']:+.2f}u" if b['status'] in ('WON', 'LOST') else "Pending"
        html += f"""
        <div class="card">
            <div class="card-header"><span>{b['selection']} ({'+' if b['odds'] > 0 else ''}{b['odds']})</span><span>{b['status']}</span></div>
            <div class="row"><span class="lbl">Tour / Type</span> <span>{b['tour']} • {b['wager_type']}</span></div>
            <div class="row"><span class="lbl">Stake</span> <span>{b['units']} units</span></div>
            <div class="row"><span class="lbl">Result</span> <span>{payout}</span></div>
        </div>
        """

    html += "</div></body></html>"
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
