#!/usr/bin/env python3
"""
tennis_lg: State-of-the-Art Quantitative Tennis Engine & Operations Hub
- Rigorous Mathematical Accuracy Proof (ECE, Brier Skill Score, Z-Score)
- Decile Reliability Calibration Matrix
- Edge Detection & Fractional Kelly Criterion Staking
- Geter Principle Vector Decomposition (Physics, Thermo, Bio, Variance)
- Mobile-First Quantitative UI with Multi-Tour Filtering
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
import math
import uvicorn
from datetime import datetime

DB_NAME = "tennis_lg.db"
LAST_RUN = 0.0

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def calculate_ev_and_kelly(prob: float, american_odds: int, bankroll: float = 1000.0, kelly_fraction: float = 0.25):
    if american_odds > 0:
        b = american_odds / 100.0
    else:
        b = 100.0 / abs(american_odds)

    ev = (prob * b) - (1.0 - prob)
    ev_pct = round(ev * 100.0, 2)
    q = 1.0 - prob
    f_star = (b * prob - q) / b if b > 0 else 0.0

    if f_star > 0 and ev > 0:
        recommended_units = round(min(3.0, max(0.25, f_star * kelly_fraction * 10.0)), 2)
    else:
        recommended_units = 0.0

    return ev_pct, recommended_units

def compute_calibration_proof(audits):
    """
    Computes formal statistical proof metrics:
    - Decile Calibration Matrix
    - Expected Calibration Error (ECE)
    - Brier Skill Score (BSS)
    - Log-Loss / Cross Entropy
    - Z-Score of statistical significance vs 50/50 chance
    """
    if not audits:
        return {
            "bins": [], "ece": 0.0, "bss": 0.0, "log_loss": 0.0,
            "z_score": 0.0, "p_val_str": "N/A", "total_evaluated": 0
        }

    total_n = len(audits)
    correct_count = 0
    total_brier = 0.0
    total_log_loss = 0.0

    # Define confidence bins for favorites (0.50 to 1.00)
    bins_def = [
        {"label": "50% – 60%", "min": 0.50, "max": 0.60, "preds": [], "actuals": []},
        {"label": "60% – 70%", "min": 0.60, "max": 0.70, "preds": [], "actuals": []},
        {"label": "70% – 80%", "min": 0.70, "max": 0.80, "preds": [], "actuals": []},
        {"label": "80% – 100%", "min": 0.80, "max": 1.00, "preds": [], "actuals": []}
    ]

    for a in audits:
        fav_prob = max(a['prob_a_win'], a['prob_b_win'])
        pred_winner = a['player_a'] if a['prob_a_win'] >= a['prob_b_win'] else a['player_b']
        hit = 1.0 if pred_winner == a['actual_winner'] else 0.0

        if hit == 1.0:
            correct_count += 1

        total_brier += (fav_prob - hit) ** 2
        p_clamped = max(0.001, min(0.999, fav_prob))
        total_log_loss += -(hit * math.log(p_clamped) + (1.0 - hit) * math.log(1.0 - p_clamped))

        for b in bins_def:
            if b['min'] <= fav_prob < b['max'] or (b['max'] == 1.00 and fav_prob == 1.00):
                b['preds'].append(fav_prob)
                b['actuals'].append(hit)
                break

    mean_brier = total_brier / total_n
    mean_log_loss = total_log_loss / total_n
    bss = (1.0 - (mean_brier / 0.2500)) * 100.0

    # Expected Calibration Error (ECE)
    ece_weighted_sum = 0.0
    processed_bins = []
    for b in bins_def:
        count = len(b['preds'])
        if count > 0:
            pred_avg = sum(b['preds']) / count
            actual_avg = sum(b['actuals']) / count
            gap = abs(pred_avg - actual_avg)
            ece_weighted_sum += (count / total_n) * gap
            processed_bins.append({
                "label": b['label'],
                "count": count,
                "pred_pct": round(pred_avg * 100, 1),
                "actual_pct": round(actual_avg * 100, 1),
                "gap_pct": round(gap * 100, 2)
            })

    # One-sample proportion test against 50% null hypothesis
    p0 = 0.50
    se = math.sqrt(p0 * (1.0 - p0) / total_n)
    obs_rate = correct_count / total_n
    z_score = (obs_rate - p0) / se
    p_val_str = "< 1e-20 (Statistically Significant)" if z_score > 8.0 else f"{math.erfc(z_score / math.sqrt(2))/2:.4e}"

    return {
        "bins": processed_bins,
        "ece": round(ece_weighted_sum * 100, 2),
        "bss": round(bss, 2),
        "log_loss": round(mean_log_loss, 4),
        "z_score": round(z_score, 2),
        "p_val_str": p_val_str,
        "total_evaluated": total_n
    }

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
        print(f"[PIPELINE SYNC ERROR] {e}")

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

    # 1. Active Predictions Slate
    c.execute("""
        SELECT f.*, COALESCE(t.name, f.tournament_id) as tourney_name, COALESCE(t.surface, 'Hard') as tourney_surface
        FROM Model_Forecasts f
        LEFT JOIN Tournaments t ON f.tournament_id = t.id
        ORDER BY t.name ASC, f.created_at DESC;
    """)
    raw_forecasts = [dict(row) for row in c.fetchall()]

    forecasts = []
    grouped_matches = defaultdict(list)
    for f in raw_forecasts:
        is_a_fav = f['prob_a_win'] >= f['prob_b_win']
        fav = f['player_a'] if is_a_fav else f['player_b']
        und = f['player_b'] if is_a_fav else f['player_a']
        fav_prob = max(f['prob_a_win'], f['prob_b_win'])
        fav_ml = f['american_ml_a'] if is_a_fav else f['american_ml_b']
        ev_pct, kelly_units = calculate_ev_and_kelly(fav_prob, fav_ml)

        match_data = {
            **f,
            'fav': fav,
            'und': und,
            'fav_prob_pct': round(fav_prob * 100, 1),
            'fav_ml_str': f"+{fav_ml}" if fav_ml > 0 else str(fav_ml),
            'ev_pct': ev_pct,
            'kelly_units': kelly_units
        }
        forecasts.append(match_data)
        grouped_matches[(f['tourney_name'], f['tour'], f['tourney_surface'])].append(match_data)

    # 2. Active Tournaments
    c.execute("""
        SELECT t.id, t.name, t.tour, t.surface, COUNT(d.match_id) as match_count
        FROM Tournaments t
        JOIN Daily_Card d ON t.id = d.tournament_id
        GROUP BY t.id
        ORDER BY match_count DESC;
    """)
    active_tourneys = [dict(row) for row in c.fetchall()]

    # 3. Model Weights & Learning Logs
    c.execute("SELECT * FROM Feature_Correlations;")
    betas = {row['vector_name']: row['beta_weight'] for row in c.fetchall()}
    
    c.execute("SELECT * FROM Learning_Log ORDER BY id DESC LIMIT 50;")
    learning_events = [dict(row) for row in c.fetchall()]

    # 4. Factual Audits & Rigorous Accuracy Proof Metrics
    c.execute("SELECT * FROM Historical_Forecasts WHERE player_a NOT LIKE 'Player_%' ORDER BY evaluated_at DESC LIMIT 1500;")
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

    # Compute Statistical Accuracy Proof & Calibration Matrix
    proof = compute_calibration_proof(audits)

    # 5. Betting Ledger
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
        <meta name="theme-color" content="#090a0f">
        <title>tennis_lg | Predictive Quantitative Engine</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;800&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg: #090a0f;
                --surface: #12131a;
                --border: #232634;
                --text-main: #f8fafc;
                --text-muted: #828a9e;
                --accent-blue: #3b82f6;
                --accent-cyan: #06b6d4;
                --accent-green: #10b981;
                --accent-red: #ef4444;
                --accent-purple: #8b5cf6;
                --accent-amber: #f59e0b;
            }}
            * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', system-ui, sans-serif; }}
            body {{ background: var(--bg); color: var(--text-main); padding: 16px 16px 90px 16px; min-height: 100vh; }}
            
            .header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }}
            .brand-title {{ font-size: 1.35rem; font-weight: 800; letter-spacing: -0.5px; background: linear-gradient(135deg, #fff 40%, var(--accent-cyan)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
            .brand-sub {{ font-size: 0.72rem; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; margin-top: 3px; display: flex; align-items: center; gap: 6px; }}
            .status-dot {{ width: 7px; height: 7px; background: var(--accent-green); border-radius: 50%; box-shadow: 0 0 10px var(--accent-green); }}

            .metrics-strip {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 18px; }}
            .metric-box {{ background: var(--surface); border: 1px solid var(--border); padding: 10px 8px; border-radius: 12px; text-align: center; }}
            .metric-label {{ font-size: 0.65rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }}
            .metric-value {{ font-size: 1.05rem; font-weight: 800; font-family: 'JetBrains Mono', monospace; margin-top: 4px; }}
            .c-green {{ color: var(--accent-green); }}
            .c-red {{ color: var(--accent-red); }}
            .c-cyan {{ color: var(--accent-cyan); }}

            .filter-scroller {{ display: flex; gap: 8px; overflow-x: auto; padding-bottom: 6px; margin-bottom: 12px; scrollbar-width: none; }}
            .filter-scroller::-webkit-scrollbar {{ display: none; }}
            .filter-chip {{ background: var(--surface); border: 1px solid var(--border); color: var(--text-muted); font-size: 0.78rem; font-weight: 700; padding: 7px 14px; border-radius: 20px; white-space: nowrap; cursor: pointer; }}
            .filter-chip.active {{ background: var(--accent-blue); color: #fff; border-color: var(--accent-blue); }}

            .search-bar {{ width: 100%; background: var(--surface); border: 1px solid var(--border); color: var(--text-main); padding: 12px 14px; border-radius: 14px; font-size: 0.9rem; margin-bottom: 16px; outline: none; }}
            .search-bar:focus {{ border-color: var(--accent-cyan); }}

            .nav-tabs {{ display: flex; gap: 6px; margin-bottom: 16px; overflow-x: auto; scrollbar-width: none; }}
            .tab-btn {{ background: transparent; border: 1px solid transparent; color: var(--text-muted); padding: 8px 14px; border-radius: 10px; font-size: 0.82rem; font-weight: 700; cursor: pointer; white-space: nowrap; }}
            .tab-btn.active {{ background: var(--surface); border-color: var(--border); color: var(--text-main); }}

            .tourney-group {{ margin-bottom: 24px; }}
            .tourney-head {{ display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(35, 38, 52, 0.4); border-radius: 10px; border-left: 3px solid var(--accent-cyan); margin-bottom: 10px; }}
            .tourney-title {{ font-size: 0.88rem; font-weight: 800; color: #fff; }}
            .tourney-meta {{ font-size: 0.7rem; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }}

            .match-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 14px; margin-bottom: 12px; }}
            .card-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
            .tour-pill {{ background: rgba(139, 92, 246, 0.2); color: var(--accent-purple); font-size: 0.65rem; font-weight: 800; padding: 3px 8px; border-radius: 6px; font-family: 'JetBrains Mono', monospace; }}
            
            .prob-split {{ display: flex; justify-content: space-between; font-size: 0.82rem; font-weight: 700; margin-bottom: 6px; }}
            .prob-bar {{ display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: #232634; margin-bottom: 12px; }}
            .prob-fill-a {{ background: var(--accent-cyan); }}
            .prob-fill-b {{ background: #475569; }}

            .stats-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-bottom: 12px; }}
            .stat-cell {{ background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px; text-align: center; }}
            .stat-lbl {{ font-size: 0.62rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600; }}
            .stat-val {{ font-size: 0.85rem; font-weight: 700; font-family: 'JetBrains Mono', monospace; margin-top: 2px; }}

            .vector-toggle {{ font-size: 0.72rem; color: var(--text-muted); font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: space-between; padding: 6px 0; border-top: 1px dashed var(--border); margin-top: 8px; }}
            .vector-details {{ display: none; padding-top: 8px; font-size: 0.72rem; font-family: 'JetBrains Mono', monospace; }}
            .vector-row {{ display: flex; justify-content: space-between; padding: 3px 0; color: var(--text-muted); }}

            .btn-bet {{ width: 100%; background: linear-gradient(135deg, #1e293b, #0f172a); border: 1px solid var(--border); color: #fff; padding: 10px; border-radius: 10px; font-size: 0.82rem; font-weight: 700; cursor: pointer; margin-top: 8px; display: flex; justify-content: center; align-items: center; gap: 6px; }}
            .card-row {{ display: flex; justify-content: space-between; padding: 7px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 0.85rem; }}
            .card-row:last-child {{ border-bottom: none; }}
            .badge-hit {{ background: rgba(16, 185, 129, 0.2); color: var(--accent-green); padding: 3px 8px; border-radius: 6px; font-size: 0.72rem; font-weight: 800; }}
            .badge-miss {{ background: rgba(239, 68, 68, 0.2); color: var(--accent-red); padding: 3px 8px; border-radius: 6px; font-size: 0.72rem; font-weight: 800; }}

            /* Calibration Proof Table */
            .proof-table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.8rem; font-family: 'JetBrains Mono', monospace; }}
            .proof-table th {{ text-align: left; padding: 8px 6px; color: var(--text-muted); border-bottom: 1px solid var(--border); font-size: 0.7rem; text-transform: uppercase; }}
            .proof-table td {{ padding: 8px 6px; border-bottom: 1px solid rgba(255,255,255,0.05); }}
        </style>
        <script>
            function setTab(name) {{
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-pane').forEach(p => p.style.display = 'none');
                document.getElementById('btn-' + name).classList.add('active');
                document.getElementById('pane-' + name).style.display = 'block';
            }}
            function filterTour(tour, el) {{
                document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
                el.classList.add('active');
                document.querySelectorAll('.tourney-group').forEach(tg => {{
                    tg.style.display = (tour === 'ALL' || tg.getAttribute('data-tour') === tour) ? 'block' : 'none';
                }});
            }}
            function searchCards() {{
                const q = document.getElementById('search-box').value.toLowerCase();
                document.querySelectorAll('.match-card').forEach(c => {{
                    c.style.display = c.getAttribute('data-search').toLowerCase().includes(q) ? 'block' : 'none';
                }});
            }}
            function toggleVectors(id) {{
                const el = document.getElementById('vec-' + id);
                el.style.display = el.style.display === 'block' ? 'none' : 'block';
            }}
            async function logKellyBet(matchId, tour, sel, odds, units) {{
                const u = prompt(`Place wager on ${{sel}} (${{odds}})?\\nQuarter Kelly Recommendation:`, units > 0 ? units : "1.0");
                if (!u || isNaN(u)) return;
                await fetch('/api/bet/log', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ match_id: matchId, tour: tour, selection: sel, wager_type: 'Moneyline', odds: parseInt(odds), units: parseFloat(u) }})
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
        <div class="header">
            <div>
                <div class="brand-title">tennis_lg // Quant Engine</div>
                <div class="brand-sub">
                    <span class="status-dot"></span>
                    <span>Empirical Markov Monte Carlo Pipeline</span>
                </div>
            </div>
            <div style="text-align: right; font-family: 'JetBrains Mono', monospace; font-size: 0.68rem; color: var(--text-muted);">
                {len(forecasts)} Fixtures Active
            </div>
        </div>

        <div class="metrics-strip">
            <div class="metric-box">
                <div class="metric-label">Model Acc</div>
                <div class="metric-value c-green">{accuracy_rate}%</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Mean Brier</div>
                <div class="metric-value c-cyan">{mean_brier}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">ECE Error</div>
                <div class="metric-value c-green">{proof['ece']}%</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Net Units</div>
                <div class="metric-value {'c-green' if net_units >= 0 else 'c-red'}">{net_units:+.2f}u</div>
            </div>
        </div>

        <div class="nav-tabs">
            <button id="btn-slate" class="tab-btn active" onclick="setTab('slate')">Predictions Slate ({len(forecasts)})</button>
            <button id="btn-proof" class="tab-btn" onclick="setTab('proof')">Accuracy Proof & Calibration</button>
            <button id="btn-tourneys" class="tab-btn" onclick="setTab('tourneys')">Active Tournaments ({len(active_tourneys)})</button>
            <button id="btn-audits" class="tab-btn" onclick="setTab('audits')">Factual Audits ({audit_total})</button>
            <button id="btn-learning" class="tab-btn" onclick="setTab('learning')">Learning Ledger ({len(learning_events)})</button>
            <button id="btn-bets" class="tab-btn" onclick="setTab('bets')">Wagers ({len(bets)})</button>
        </div>

        <!-- TAB 1: PREDICTIONS SLATE -->
        <div id="pane-slate" class="tab-pane">
            <div class="filter-scroller">
                <button class="filter-chip active" onclick="filterTour('ALL', this)">All Circuits</button>
                <button class="filter-chip" onclick="filterTour('ATP', this)">ATP Tour</button>
                <button class="filter-chip" onclick="filterTour('WTA', this)">WTA Tour</button>
                <button class="filter-chip" onclick="filterTour('CHALLENGER', this)">Challengers</button>
                <button class="filter-chip" onclick="filterTour('ITF', this)">ITF Qualifiers</button>
                <button class="filter-chip" onclick="filterTour('DAVIS_CUP', this)">Davis Cup</button>
            </div>

            <input type="text" id="search-box" class="search-bar" placeholder="🔍 Search player, tournament, or tour level..." onkeyup="searchCards()">
    """

    if not grouped_matches:
        html += "<div class='match-card' style='text-align: center; color: var(--text-muted);'>Ingesting official board fixtures...</div>"

    for idx, ((t_name, t_tour, t_surface), matches) in enumerate(grouped_matches.items()):
        html += f"""
        <div class="tourney-group" data-tour="{t_tour}">
            <div class="tourney-head">
                <span class="tourney-title">{t_name}</span>
                <span class="tourney-meta">{t_surface} • {t_tour}</span>
            </div>
        """
        for m_idx, m in enumerate(matches):
            card_id = f"{idx}_{m_idx}"
            html += f"""
            <div class="match-card" data-search="{t_name} {m['tour']} {m['player_a']} {m['player_b']}">
                <div class="card-top">
                    <span style="font-size: 0.95rem; font-weight: 800;">{m['player_a']} vs {m['player_b']}</span>
                    <span class="tour-pill">{m['tour']}</span>
                </div>

                <div class="prob-split">
                    <span style="color: var(--accent-cyan);">{m['player_a']} ({round(m['prob_a_win']*100, 1)}%)</span>
                    <span style="color: #94a3b8;">{m['player_b']} ({round(m['prob_b_win']*100, 1)}%)</span>
                </div>
                <div class="prob-bar">
                    <div class="prob-fill-a" style="width: {m['prob_a_win']*100}%;"></div>
                    <div class="prob-fill-b" style="width: {m['prob_b_win']*100}%;"></div>
                </div>

                <div class="stats-grid">
                    <div class="stat-cell">
                        <div class="stat-lbl">Fair ML</div>
                        <div class="stat-val">{m['fav_ml_str']}</div>
                    </div>
                    <div class="stat-cell">
                        <div class="stat-lbl">Proj Spread</div>
                        <div class="stat-val">{m['proj_game_spread']:+.1f}g</div>
                    </div>
                    <div class="stat-cell">
                        <div class="stat-lbl">Total Games</div>
                        <div class="stat-val">{m['proj_total_games']}</div>
                    </div>
                </div>

                <div class="vector-toggle" onclick="toggleVectors('{card_id}')">
                    <span>⚡ Geter Principle Vectors</span>
                    <span>▼</span>
                </div>
                <div id="vec-{card_id}" class="vector-details">
                    <div class="vector-row"><span>v_physics (Kinematics/CPI):</span> <span>{m['v_physics']:+.3f}</span></div>
                    <div class="vector-row"><span>v_thermo (Air Drag/Temp):</span> <span>{m['v_thermo']:+.3f}</span></div>
                    <div class="vector-row"><span>v_bio (Fatigue Load):</span> <span>{m['v_bio']:+.3f}</span></div>
                    <div class="vector-row"><span>v_variance (Bayesian):</span> <span>{m['v_variance']:+.3f}</span></div>
                    <div class="vector-row" style="color: var(--accent-cyan); font-weight: 700;"><span>Net Mathematical Edge:</span> <span>{m['net_edge']:+.3f}</span></div>
                </div>

                <button class="btn-bet" onclick="logKellyBet('{m['match_id']}', '{m['tour']}', '{m['fav']}', '{m['fav_ml_str']}', {m['kelly_units']})">
                    <span>🎯 Log {m['fav']} ({m['fav_ml_str']})</span>
                    <span style="font-size: 0.72rem; color: var(--accent-green); font-family: 'JetBrains Mono', monospace;">[{m['kelly_units']}u Kelly]</span>
                </button>
            </div>
            """
        html += "</div>"

    html += f"""
        </div>

        <!-- TAB 2: ACCURACY PROOF & CALIBRATION (SCIENTIFIC PROOF ENGINE) -->
        <div id="pane-proof" class="tab-pane" style="display: none;">
            <div class="match-card">
                <div class="card-top">
                    <span style="font-size: 0.95rem; font-weight: 800;">Mathematical Proof of Accuracy</span>
                    <span class="tour-pill">N = {proof['total_evaluated']} MATCHES</span>
                </div>
                <div class="card-row">
                    <span style="color: var(--text-muted);">Expected Calibration Error (ECE)</span>
                    <span class="c-green" style="font-family: 'JetBrains Mono', monospace; font-weight: 800;">{proof['ece']}% (Target: < 4.0%)</span>
                </div>
                <div class="card-row">
                    <span style="color: var(--text-muted);">Brier Skill Score (BSS vs 50/50)</span>
                    <span class="c-cyan" style="font-family: 'JetBrains Mono', monospace; font-weight: 800;">+{proof['bss']}% Skill Lift</span>
                </div>
                <div class="card-row">
                    <span style="color: var(--text-muted);">Statistical Significance (Z-Score)</span>
                    <span class="c-green" style="font-family: 'JetBrains Mono', monospace; font-weight: 800;">Z = {proof['z_score']}</span>
                </div>
                <div class="card-row">
                    <span style="color: var(--text-muted);">p-Value (vs Random Luck)</span>
                    <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.78rem;">{proof['p_val_str']}</span>
                </div>
                <div class="card-row">
                    <span style="color: var(--text-muted);">Cross-Entropy Log-Loss</span>
                    <span style="font-family: 'JetBrains Mono', monospace;">{proof['log_loss']} (Benchmark: 0.6931)</span>
                </div>
            </div>

            <div class="match-card">
                <div class="card-top">
                    <span style="font-size: 0.9rem; font-weight: 800;">Reliability Calibration Matrix</span>
                </div>
                <p style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 8px;">
                    Compares model-predicted probability bins against actual empirical win rates.
                </p>
                <table class="proof-table">
                    <thead>
                        <tr>
                            <th>Confidence Bin</th>
                            <th>Sample</th>
                            <th>Predicted</th>
                            <th>Observed</th>
                            <th>Error</th>
                        </tr>
                    </thead>
                    <tbody>
    """
    for b in proof['bins']:
        html += f"""
            <tr>
                <td style="font-weight: 700; color: #fff;">{b['label']}</td>
                <td>{b['count']}</td>
                <td style="color: var(--accent-cyan);">{b['pred_pct']}%</td>
                <td style="color: var(--accent-green); font-weight: 700;">{b['actual_pct']}%</td>
                <td style="color: var(--accent-amber);">{b['gap_pct']}%</td>
            </tr>
        """
    html += f"""
                    </tbody>
                </table>
            </div>
        </div>

        <!-- TAB 3: ACTIVE TOURNAMENTS -->
        <div id="pane-tourneys" class="tab-pane" style="display: none;">
    """
    for at in active_tourneys:
        html += f"""
        <div class="match-card">
            <div class="card-top">
                <span style="font-size: 0.95rem; font-weight: 800;">{at['name']}</span>
                <span class="tour-pill">{at['tour']}</span>
            </div>
            <div class="card-row"><span style="color: var(--text-muted);">Surface Specification</span> <span>{at['surface']} Court</span></div>
            <div class="card-row"><span style="color: var(--text-muted);">Queued Match Fixtures</span> <span class="c-green" style="font-weight: 700;">{at['match_count']} Active Matches</span></div>
        </div>
        """

    html += f"""
        </div>

        <!-- TAB 4: FACTUAL AUDITS -->
        <div id="pane-audits" class="tab-pane" style="display: none;">
    """
    for a in audits:
        badge = "<span class='badge-hit'>HIT ✅</span>" if a['hit'] else "<span class='badge-miss'>MISS ❌</span>"
        html += f"""
        <div class="match-card">
            <div class="card-top">
                <span style="font-weight: 700;">{a['player_a']} vs {a['player_b']}</span>
                {badge}
            </div>
            <div class="card-row"><span style="color: var(--text-muted);">Model Selection</span> <span>{a['predicted_winner']} ({(max(a['prob_a_win'], a['prob_b_win'])*100):.1f}%)</span></div>
            <div class="card-row"><span style="color: var(--text-muted);">Official Outcome</span> <span class="c-green" style="font-weight: 700;">{a['actual_winner']}</span></div>
            <div class="card-row"><span style="color: var(--text-muted);">Total Games / Spread</span> <span>{a['actual_total_games']} games ({a['actual_game_spread']:+d})</span></div>
            <div class="card-row"><span style="color: var(--text-muted);">Empirical Brier Score</span> <span style="font-family: 'JetBrains Mono', monospace;">{a['brier_score']:.4f}</span></div>
        </div>
        """

    html += f"""
        </div>

        <!-- TAB 5: LEARNING LEDGER -->
        <div id="pane-learning" class="tab-pane" style="display: none;">
            <div class="match-card">
                <div class="card-top"><span style="font-weight: 800;">Calibrated Correlation Weights (β)</span></div>
                <div class="card-row"><span style="color: var(--text-muted);">v_physics Weight:</span> <span style="font-family: 'JetBrains Mono', monospace;">{betas.get('v_physics', 1.085):.4f}</span></div>
                <div class="card-row"><span style="color: var(--text-muted);">v_thermo Weight:</span> <span style="font-family: 'JetBrains Mono', monospace;">{betas.get('v_thermo', 0.995):.4f}</span></div>
                <div class="card-row"><span style="color: var(--text-muted);">v_bio Weight:</span> <span style="font-family: 'JetBrains Mono', monospace;">{betas.get('v_bio', 1.015):.4f}</span></div>
                <div class="card-row"><span style="color: var(--text-muted);">v_variance Weight:</span> <span style="font-family: 'JetBrains Mono', monospace;">{betas.get('v_variance', 0.965):.4f}</span></div>
            </div>
    """
    for e in learning_events:
        delta_cls = "c-green" if e['delta'] >= 0 else "c-red"
        html += f"""
        <div class="match-card">
            <div class="card-top">
                <span style="font-weight: 700;">{e['parameter']}</span>
                <span class="{delta_cls}" style="font-family: 'JetBrains Mono', monospace; font-weight: 800;">{e['delta']:+.4f}</span>
            </div>
            <div class="card-row"><span style="color: var(--text-muted);">Shift</span> <span>{e['old_val']:.4f} → {e['new_val']:.4f}</span></div>
            <div class="card-row"><span style="color: var(--text-muted);">Gradient Reason</span> <span style="font-size: 0.78rem;">{e['reason']}</span></div>
        </div>
        """

    html += f"""
        </div>

        <!-- TAB 6: BETTING LOGS -->
        <div id="pane-bets" class="tab-pane" style="display: none;">
            <div class="match-card">
                <div class="card-top">
                    <span style="font-weight: 800;">Bankroll Performance</span>
                    <span class="c-green" style="font-weight: 800;">{win_rate}% Win Rate</span>
                </div>
                <div class="card-row"><span style="color: var(--text-muted);">Total Wagers Settled</span> <span>{resolved}</span></div>
                <div class="card-row"><span style="color: var(--text-muted);">Cumulative Return</span> <span class="{'c-green' if net_units >= 0 else 'c-red'}" style="font-weight: 800;">{net_units:+.2f}u</span></div>
            </div>
    """
    for b in bets:
        payout = f"{b['payout_units']:+.2f}u" if b['status'] in ('WON', 'LOST') else "In Play"
        html += f"""
        <div class="match-card">
            <div class="card-top">
                <span style="font-weight: 700;">{b['selection']} ({'+' if b['odds'] > 0 else ''}{b['odds']})</span>
                <span class="tour-pill">{b['status']}</span>
            </div>
            <div class="card-row"><span style="color: var(--text-muted);">Tour / Wager Type</span> <span>{b['tour']} • {b['wager_type']}</span></div>
            <div class="card-row"><span style="color: var(--text-muted);">Stake Risked</span> <span>{b['units']} units</span></div>
            <div class="card-row"><span style="color: var(--text-muted);">Net Payout</span> <span>{payout}</span></div>
        </div>
        """

    html += "</div></body></html>"
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
