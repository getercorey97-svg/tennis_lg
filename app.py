#!/usr/bin/env python3
"""
tennis_lg: Autonomous Operational Hub with On-Launch Live Ingestion
- Automatically checks for new slates, scores, and audits upon app opening
- Synchronizes dual-source FanDuel and player profile feeds
- Real-time learning adaptations, bet settlement, and factual audits
"""

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from contextlib import asynccontextmanager
import asyncio
import subprocess
import sqlite3
import os
import time
import uvicorn
from datetime import datetime

DB_NAME = "tennis_lg.db"
LAST_RUN_TIMESTAMP = 0.0

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def run_full_pipeline_sync():
    """Runs ingestion, pre-match simulations, and simulation-free audits."""
    global LAST_RUN_TIMESTAMP
    now = time.time()
    
    # 60-second debounce to prevent spamming when toggling tabs quickly
    if now - LAST_RUN_TIMESTAMP < 60:
        return {"status": "debounced", "message": "Updated recently"}

    LAST_RUN_TIMESTAMP = now
    try:
        # 1. Pull latest match slates from FanDuel & Stats repos
        subprocess.run(["python3", "scraper.py"], check=False)
        # 2. Compute Monte Carlo predictions for newly scheduled games
        subprocess.run(["python3", "run_pipeline.py"], check=False)
        # 3. Ingest completed match scores & execute simulation-free post-mortems
        subprocess.run(["python3", "post_mortem.py"], check=False)

        # 4. Auto-settle any pending wagers with empirical outcomes
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT b.id, b.selection, b.odds, b.units, h.actual_winner
            FROM Betting_Logs b
            JOIN Historical_Forecasts h ON b.match_id = h.match_id
            WHERE b.status = 'PENDING';
        """)
        for b_id, sel, odds, units, actual_winner in c.fetchall():
            if sel == actual_winner:
                payout = (units * (odds / 100.0)) if odds > 0 else (units * (100.0 / abs(odds)))
                c.execute("UPDATE Betting_Logs SET status = 'WON', actual_winner = ?, payout_units = ? WHERE id = ?;", (actual_winner, round(payout, 2), b_id))
            else:
                c.execute("UPDATE Betting_Logs SET status = 'LOST', actual_winner = ?, payout_units = ? WHERE id = ?;", (actual_winner, -units, b_id))
        conn.commit()
        conn.close()
        return {"status": "success", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    except Exception as e:
        print(f"[PIPELINE SYNC ERROR] {e}")
        return {"status": "error", "detail": str(e)}

async def autonomous_background_daemon(interval_minutes: int = 15):
    """Fallback loop running every 15 minutes when app is closed."""
    await asyncio.sleep(5)
    while True:
        run_full_pipeline_sync()
        await asyncio.sleep(interval_minutes * 60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(autonomous_background_daemon(interval_minutes=15))
    yield
    worker_task.cancel()

app = FastAPI(title="tennis_lg Operations Hub", lifespan=lifespan)

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

@app.post("/api/sync/on_open")
def sync_on_open(background_tasks: BackgroundTasks):
    """Immediate trigger executed whenever you open the dashboard."""
    background_tasks.add_task(run_full_pipeline_sync)
    return JSONResponse({"status": "sync_dispatched", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

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
    
    # 1. Active Slate
    c.execute("SELECT * FROM Model_Forecasts ORDER BY created_at DESC;")
    forecasts = [dict(row) for row in c.fetchall()]
    
    # 2. Betas
    c.execute("SELECT * FROM Feature_Correlations;")
    betas = {row['vector_name']: row['beta_weight'] for row in c.fetchall()}
    
    # 3. Learning Adaptations
    c.execute("SELECT * FROM Learning_Log ORDER BY id DESC LIMIT 50;")
    learning_events = [dict(row) for row in c.fetchall()]
    
    # 4. Factual Audits (Excluding mock dummy labels)
    c.execute("""
        SELECT * FROM Historical_Forecasts 
        WHERE player_a NOT LIKE 'Player_%' AND player_b NOT LIKE 'Player_%'
        ORDER BY evaluated_at DESC;
    """)
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
    
    # 5. Betting Ledger
    c.execute("SELECT * FROM Betting_Logs ORDER BY logged_at DESC;")
    bets = [dict(row) for row in c.fetchall()]
    net_units = round(sum(b['payout_units'] for b in bets if b['status'] in ('WON', 'LOST')), 2)
    won_bets = sum(1 for b in bets if b['status'] == 'WON')
    resolved_bets = sum(1 for b in bets if b['status'] in ('WON', 'LOST'))
    bet_win_rate = round((won_bets / resolved_bets * 100), 1) if resolved_bets > 0 else 0.0
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
            body {{ background: var(--bg); color: var(--text); margin: 0; padding: env(safe-area-inset-top) 16px 80px 16px; }}
            h1 {{ font-size: 1.3rem; margin: 16px 0 4px 0; font-weight: 800; }}
            .sub-status {{ font-size: 0.75rem; color: var(--muted); font-family: monospace; display: flex; align-items: center; gap: 6px; margin-bottom: 16px; }}
            .dot {{ width: 8px; height: 8px; background: var(--green); border-radius: 50%; box-shadow: 0 0 8px var(--green); }}
            .tabs {{ display: flex; gap: 8px; margin-bottom: 16px; overflow-x: auto; }}
            .tab-btn {{
                background: var(--card); border: 1px solid var(--border); color: var(--muted);
                padding: 10px 14px; border-radius: 12px; font-size: 0.85rem; font-weight: 700; white-space: nowrap; cursor: pointer;
            }}
            .tab-btn.active {{ background: var(--blue); color: white; border-color: var(--blue); }}
            .search-box {{
                width: 100%; background: var(--card); border: 1px solid var(--border);
                color: var(--text); padding: 12px 14px; border-radius: 14px; font-size: 0.95rem; margin-bottom: 14px; outline: none;
            }}
            .search-box:focus {{ border-color: var(--blue); }}
            .metrics-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 18px; }}
            .metric-pill {{ background: var(--card); border: 1px solid var(--border); padding: 10px 6px; border-radius: 12px; text-align: center; }}
            .metric-title {{ font-size: 0.65rem; color: var(--muted); font-weight: 700; text-transform: uppercase; }}
            .metric-val {{ font-size: 1rem; font-weight: 800; margin-top: 4px; font-family: monospace; }}
            .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 18px; padding: 14px; margin-bottom: 12px; }}
            .card-header {{ display: flex; justify-content: space-between; align-items: center; font-weight: 700; font-size: 0.95rem; margin-bottom: 10px; }}
            .tour-tag {{ background: var(--purple); color: white; font-size: 0.65rem; font-weight: 800; padding: 3px 6px; border-radius: 4px; }}
            .row {{ display: flex; justify-content: space-between; padding: 7px 0; border-bottom: 1px solid var(--border); font-size: 0.88rem; }}
            .row:last-of-type {{ border-bottom: none; }}
            .lbl {{ color: var(--muted); }}
            .green {{ color: var(--green); font-weight: 700; }}
            .red {{ color: var(--red); font-weight: 700; }}
            .btn-action {{
                width: 100%; background: #1f2937; border: 1px solid #374151; color: var(--text);
                padding: 10px; border-radius: 12px; font-weight: 700; font-size: 0.85rem; margin-top: 10px; cursor: pointer;
            }}
            .badge-won {{ background: rgba(48,209,88,0.2); color: var(--green); padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 800; }}
            .badge-lost {{ background: rgba(255,69,58,0.2); color: var(--red); padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 800; }}
            .badge-pending {{ background: rgba(10,132,255,0.2); color: var(--blue); padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 800; }}
            .delta-up {{ color: var(--green); font-weight: 700; font-family: monospace; }}
            .delta-down {{ color: var(--red); font-weight: 700; font-family: monospace; }}
            #sync-badge {{
                display: inline-block; padding: 2px 8px; border-radius: 6px;
                background: #1c1c1e; font-size: 0.7rem; color: var(--muted); margin-left: auto;
            }}
        </style>
        <script>
            function setTab(name) {{
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-pane').forEach(p => p.style.display = 'none');
                document.getElementById('btn-' + name).classList.add('active');
                document.getElementById('pane-' + name).style.display = 'block';
            }}
            
            function filterMatches() {{
                const q = document.getElementById('search-input').value.toLowerCase();
                document.querySelectorAll('.match-card').forEach(c => {{
                    c.style.display = c.getAttribute('data-search').toLowerCase().includes(q) ? 'block' : 'none';
                }});
            }}

            async function triggerOnOpenSync() {{
                const badge = document.getElementById('sync-badge');
                if (badge) badge.innerText = "Syncing live feeds...";
                try {{
                    const res = await fetch('/api/sync/on_open', {{ method: 'POST' }});
                    if (res.ok) {{
                        setTimeout(() => {{
                            if (badge) badge.innerText = "Slate Updated";
                        }}, 2500);
                    }}
                }} catch (e) {{
                    if (badge) badge.innerText = "Sync Pending";
                }}
            }}

            // Trigger sync when app opens or returns to active view
            document.addEventListener('DOMContentLoaded', triggerOnOpenSync);
            document.addEventListener('visibilitychange', () => {{
                if (document.visibilityState === 'visible') {{
                    triggerOnOpenSync();
                }}
            }});

            async function logWager(matchId, tour, sel, odds) {{
                const units = prompt(`Log Wager on ${{sel}} (${{odds > 0 ? '+' : ''}}${{odds}})\\nEnter stake units:`, "1.0");
                if (!units || isNaN(units)) return;
                await fetch('/api/bet/log', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ match_id: matchId, tour: tour, selection: sel, wager_type: 'Moneyline', odds: odds, units: parseFloat(units) }})
                }});
                window.location.reload();
            }}
        </script>
    </head>
    <body>
        <h1>tennis_lg Operations Hub</h1>
        <div class="sub-status">
            <span class="dot"></span> 
            <span>Live Auto-Sync On Open</span>
            <span id="sync-badge">Checking Slate...</span>
        </div>

        <div class="metrics-grid">
            <div class="metric-pill"><div class="metric-title">Accuracy</div><div class="metric-val green">{accuracy_rate}%</div></div>
            <div class="metric-pill"><div class="metric-title">Audits</div><div class="metric-val">{audit_total}</div></div>
            <div class="metric-pill"><div class="metric-title">Mean Brier</div><div class="metric-val">{mean_brier}</div></div>
            <div class="metric-pill"><div class="metric-title">Net Units</div><div class="metric-val {'green' if net_units >= 0 else 'red'}">{net_units:+.2f}u</div></div>
        </div>

        <div class="tabs">
            <button id="btn-slate" class="tab-btn active" onclick="setTab('slate')">Predictions Slate</button>
            <button id="btn-learning" class="tab-btn" onclick="setTab('learning')">Learning Ledger ({len(learning_events)})</button>
            <button id="btn-audits" class="tab-btn" onclick="setTab('audits')">Factual Audits ({audit_total})</button>
            <button id="btn-bets" class="tab-btn" onclick="setTab('bets')">Betting Log ({len(bets)})</button>
        </div>

        <!-- TAB 1: PREDICTIONS SLATE -->
        <div id="pane-slate" class="tab-pane">
            <input type="text" id="search-input" class="search-box" placeholder="🔍 Search player, tour (ATP, WTA, ITF, ATF), or tournament..." onkeyup="filterMatches()">
    """
    if not forecasts:
        html += "<div class='card'><div class='lbl'>Updating live matchups from FanDuel and official boards...</div></div>"
    for f in forecasts:
        fav = f['player_a'] if f['prob_a_win'] >= 0.5 else f['player_b']
        fav_prob = max(f['prob_a_win'], f['prob_b_win']) * 100
        fav_ml = f['american_ml_a'] if fav == f['player_a'] else f['american_ml_b']
        fav_ml_str = f"+{fav_ml}" if fav_ml > 0 else str(fav_ml)
        html += f"""
        <div class="card match-card" data-search="{f['tour']} {f['player_a']} {f['player_b']} {f['tournament_id']}">
            <div class="card-header"><span>{f['player_a']} vs {f['player_b']}</span><span class="tour-tag">{f['tour']}</span></div>
            <div class="row"><span class="lbl">Predicted Outright</span> <span class="green">{fav} ({fav_prob:.1f}%)</span></div>
            <div class="row"><span class="lbl">Fair FanDuel ML</span> <span>{fav_ml_str}</span></div>
            <div class="row"><span class="lbl">Projected Spread</span> <span>{f['proj_game_spread']:+.1f} Games</span></div>
            <div class="row"><span class="lbl">Total Games Line</span> <span>{f['proj_total_games']}</span></div>
            <button class="btn-action" onclick="logWager('{f['match_id']}', '{f['tour']}', '{fav}', {fav_ml})">+ Log {fav} ({fav_ml_str}) Bet</button>
        </div>
        """
    html += f"""
        </div>

        <!-- TAB 2: LEARNING LEDGER -->
        <div id="pane-learning" class="tab-pane" style="display: none;">
            <div class="card">
                <div class="card-header"><span>Learned Correlation Weights (β)</span></div>
                <div class="row"><span class="lbl">Physics Vector</span> <span style="font-family: monospace;">{betas.get('v_physics', 1.0):.4f}</span></div>
                <div class="row"><span class="lbl">Thermo Vector</span> <span style="font-family: monospace;">{betas.get('v_thermo', 1.0):.4f}</span></div>
                <div class="row"><span class="lbl">Fatigue/Bio Vector</span> <span style="font-family: monospace;">{betas.get('v_bio', 1.0):.4f}</span></div>
                <div class="row"><span class="lbl">Variance Vector</span> <span style="font-family: monospace;">{betas.get('v_variance', 1.0):.4f}</span></div>
            </div>
    """
    if not learning_events:
        html += "<div class='card'><div class='lbl'>Parameter updates record here dynamically upon completed match audits.</div></div>"
    for e in learning_events:
        delta_class = "delta-up" if e['delta'] >= 0 else "delta-down"
        arrow = "▲" if e['delta'] >= 0 else "▼"
        html += f"""
        <div class="card">
            <div class="card-header">
                <span>{e['parameter']}</span>
                <span class="{delta_class}">{arrow} {e['delta']:+.4f}</span>
            </div>
            <div class="row"><span class="lbl">Parameter Shift</span> <span>{e['old_val']:.4f} → {e['new_val']:.4f}</span></div>
            <div class="row"><span class="lbl">Evaluation Context</span> <span style="font-size: 0.8rem;">{e['reason']}</span></div>
            <div class="row"><span class="lbl">Timestamp</span> <span style="font-family: monospace; font-size: 0.75rem;">{e['updated_at']}</span></div>
        </div>
        """
    html += f"""
        </div>

        <!-- TAB 3: FACTUAL AUDITS -->
        <div id="pane-audits" class="tab-pane" style="display: none;">
    """
    if not audits:
        html += "<div class='card'><div class='lbl'>No match outcomes audited yet. Auditing occurs as matches finish.</div></div>"
    for a in audits:
        verdict = "<span class='badge-won'>HIT ✅</span>" if a['hit'] else "<span class='badge-lost'>MISS ❌</span>"
        html += f"""
        <div class="card">
            <div class="card-header"><span>{a['player_a']} vs {a['player_b']}</span>{verdict}</div>
            <div class="row"><span class="lbl">Model Pick</span> <span>{a['predicted_winner']} ({(max(a['prob_a_win'], a['prob_b_win'])*100):.1f}%)</span></div>
            <div class="row"><span class="lbl">Official Winner</span> <span class="green">{a['actual_winner']}</span></div>
            <div class="row"><span class="lbl">Games / Spread</span> <span>{a['actual_total_games']} ({a['actual_game_spread']:+d})</span></div>
            <div class="row"><span class="lbl">Brier Score</span> <span>{a['brier_score']:.4f}</span></div>
            <div class="row"><span class="lbl">Evaluated</span> <span style="font-family: monospace; font-size: 0.75rem;">{a['evaluated_at']}</span></div>
        </div>
        """
    html += f"""
        </div>

        <!-- TAB 4: BETTING LOGS -->
        <div id="pane-bets" class="tab-pane" style="display: none;">
            <div class="card">
                <div class="card-header"><span>Performance</span> <span class="green">{bet_win_rate}% Win Rate</span></div>
                <div class="row"><span class="lbl">Settled</span> <span>{resolved_bets}</span></div>
                <div class="row"><span class="lbl">Pending</span> <span>{len(bets) - resolved_bets}</span></div>
                <div class="row"><span class="lbl">Net Return</span> <span class="{'green' if net_units >= 0 else 'red'}">{net_units:+.2f}u</span></div>
            </div>
    """
    if not bets:
        html += "<div class='card'><div class='lbl'>No bets logged yet. Use '+ Log Bet' on any active prediction.</div></div>"
    for b in bets:
        status_tag = f"<span class='badge-{'won' if b['status'] == 'WON' else ('lost' if b['status'] == 'LOST' else 'pending')}'>{b['status']}</span>"
        payout = f"{b['payout_units']:+.2f}u" if b['status'] in ('WON', 'LOST') else "In Play"
        html += f"""
        <div class="card">
            <div class="card-header"><span>{b['selection']} ({'+' if b['odds'] > 0 else ''}{b['odds']})</span>{status_tag}</div>
            <div class="row"><span class="lbl">Tour / Type</span> <span>{b['tour']} • {b['wager_type']}</span></div>
            <div class="row"><span class="lbl">Stake Risked</span> <span>{b['units']} units</span></div>
            <div class="row"><span class="lbl">Net Result</span> <span class="{'green' if b['payout_units'] > 0 else ('red' if b['payout_units'] < 0 else '')}">{payout}</span></div>
            <div class="row"><span class="lbl">Logged Time</span> <span style="font-family: monospace; font-size: 0.75rem;">{b['logged_at']}</span></div>
        </div>
        """
    html += """
        </div>
    </body>
    </html>
    """
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
