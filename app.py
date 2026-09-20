#!/usr/bin/env python3
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import sqlite3
import os
import uvicorn

app = FastAPI(title="tennis_lg Operational Dashboard")
DB_NAME = "tennis_lg.db"

def fetch_dashboard_data():
    if not os.path.exists(DB_NAME):
        return {"error": "Database not initialized. Run engine.py --init-db first."}
    
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM Model_Forecasts ORDER BY created_at DESC LIMIT 15;")
    forecasts = [dict(row) for row in c.fetchall()]
    
    c.execute("SELECT * FROM Feature_Correlations;")
    betas = {row['vector_name']: row['beta_weight'] for row in c.fetchall()}
    
    c.execute("SELECT * FROM Historical_Forecasts ORDER BY evaluated_at DESC LIMIT 10;")
    audits = [dict(row) for row in c.fetchall()]
    conn.close()
    return {"forecasts": forecasts, "betas": betas, "audits": audits}

@app.get("/", response_class=HTMLResponse)
def render_dashboard():
    data = fetch_dashboard_data()
    if "error" in data:
        return f"<html><body><h2 style='color:red;'>{data['error']}</h2></body></html>"
        
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0, viewport-fit=cover">
        <meta name="theme-color" content="#000000">
        <title>tennis_lg | Neural Dashboard</title>
        <style>
            :root {{
                --bg-main: #000000;
                --bg-card: #121212;
                --bg-card-hover: #1c1c1e;
                --text-main: #f5f5f7;
                --text-muted: #8e8e93;
                --accent-primary: #0a84ff;
                --accent-success: #30d158;
                --border-color: #2c2c2e;
            }}
            * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
            body {{
                background-color: var(--bg-main); color: var(--text-main);
                font-family: system-ui, -apple-system, sans-serif; margin: 0;
                padding: env(safe-area-inset-top) 16px env(safe-area-inset-bottom) 16px;
                -webkit-font-smoothing: antialiased;
            }}
            h1 {{ font-size: 1.4rem; margin-top: 16px; margin-bottom: 8px; font-weight: 700; }}
            .status-dot {{ height: 8px; width: 8px; background-color: var(--accent-success); border-radius: 50%; display: inline-block; margin-right: 8px; box-shadow: 0 0 8px var(--accent-success); }}
            h2 {{ font-size: 1.1rem; margin-top: 24px; margin-bottom: 12px; color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
            .card {{ background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 20px; padding: 16px; margin-bottom: 14px; transition: background 0.2s ease; }}
            .card-header {{ font-size: 1.05rem; font-weight: 700; margin-bottom: 16px; display: flex; align-items: center; }}
            .tour-badge {{ background: #bf5af2; color: white; font-size: 0.7rem; font-weight: 800; padding: 4px 8px; border-radius: 6px; margin-right: 10px; text-transform: uppercase; }}
            .stat-row {{ display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid var(--border-color); font-size: 0.95rem; }}
            .stat-row:last-child {{ border-bottom: none; padding-bottom: 0; }}
            .stat-label {{ color: var(--text-muted); font-weight: 500; }}
            .val-pos {{ color: var(--accent-success); font-weight: 700; }}
            .val-neutral {{ color: var(--text-main); font-weight: 600; }}
            .beta-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
            .beta-pill {{ background: var(--bg-card); border: 1px solid var(--border-color); padding: 14px; border-radius: 16px; text-align: center; }}
            .beta-label {{ font-size: 0.8rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase; }}
            .beta-val {{ color: var(--accent-primary); display: block; margin-top: 6px; font-size: 1.25rem; font-weight: 700; font-family: monospace; }}
            .refresh-bar {{ height: 2px; background: var(--accent-primary); width: 100%; position: fixed; top: 0; left: 0; animation: loading 60s linear infinite; }}
            @keyframes loading {{ 0% {{ width: 0; }} 100% {{ width: 100%; }} }}
        </style>
        <script>setTimeout(function(){{ window.location.reload(1); }}, 60000);</script>
    </head>
    <body>
        <div class="refresh-bar"></div>
        <h1><span class="status-dot"></span>tennis_lg Live Engine</h1>
        
        <h2>Learned Correlations (β)</h2>
        <div class="beta-grid">
            <div class="beta-pill"><span class="beta-label">Physics</span><span class="beta-val">{data['betas'].get('v_physics', 1.0):.4f}</span></div>
            <div class="beta-pill"><span class="beta-label">Thermo</span><span class="beta-val">{data['betas'].get('v_thermo', 1.0):.4f}</span></div>
            <div class="beta-pill"><span class="beta-label">Fatigue</span><span class="beta-val">{data['betas'].get('v_bio', 1.0):.4f}</span></div>
            <div class="beta-pill"><span class="beta-label">Variance</span><span class="beta-val">{data['betas'].get('v_variance', 1.0):.4f}</span></div>
        </div>
        
        <h2>FanDuel Active Slate</h2>
    """
    for f in data['forecasts']:
        fav = f['player_a'] if f['prob_a_win'] >= 0.5 else f['player_b']
        fav_prob = max(f['prob_a_win'], f['prob_b_win']) * 100
        ml = f['american_ml_a'] if fav == f['player_a'] else f['american_ml_b']
        ml_str = f"+{ml}" if ml > 0 else str(ml)
        
        html += f"""
        <div class="card">
            <div class="card-header"><span class="tour-badge">{f['tour']}</span> {f['player_a']} vs {f['player_b']}</div>
            <div class="stat-row"><span class="stat-label">Projected Outright</span> <span class="val-pos">{fav} ({fav_prob:.1f}%)</span></div>
            <div class="stat-row"><span class="stat-label">Fair Moneyline</span> <span class="val-neutral">{ml_str}</span></div>
            <div class="stat-row"><span class="stat-label">Game Spread (EV)</span> <span class="val-neutral">{f['proj_game_spread']:+.1f} Games</span></div>
            <div class="stat-row"><span class="stat-label">Total Games (O/U)</span> <span class="val-neutral">{f['proj_total_games']}</span></div>
            <div class="stat-row"><span class="stat-label">Net Causal Edge</span> <span class="val-neutral">{f['net_edge']:+.4f}</span></div>
        </div>
        """
        
    html += "<h2>Post-Mortem Audits</h2>"
    if not data['audits']: html += "<div class='card'><div class='stat-label'>Awaiting final match results.</div></div>"
    for a in data['audits']:
        html += f"""
        <div class="card">
            <div class="card-header" style="font-size: 0.95rem; margin-bottom: 12px;">{a['player_a']} vs {a['player_b']}</div>
            <div class="stat-row"><span class="stat-label">Official Winner</span> <span class="val-pos">{a['actual_winner']}</span></div>
            <div class="stat-row"><span class="stat-label">Total / Spread</span> <span class="val-neutral">{a['actual_total_games']} / {a['actual_game_spread']:+.1f}</span></div>
            <div class="stat-row"><span class="stat-label">Brier Score</span> <span class="val-neutral">{a['brier_score']:.4f}</span></div>
        </div>
        """
        
    html += "</body></html>"
    return html

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
