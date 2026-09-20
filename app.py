#!/usr/bin/env python3
"""
tennis_lg: Mobile Web Dashboard (Optimized for Samsung Galaxy S26 Ultra)
Serves active projections, causal vector weights, and post-mortem audits.
"""
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
    
    # 1. Fetch Active Predictions
    c.execute("SELECT * FROM Model_Forecasts ORDER BY created_at DESC LIMIT 15;")
    forecasts = [dict(row) for row in c.fetchall()]
    
    # 2. Fetch Active Correlation Beta Weights
    c.execute("SELECT * FROM Feature_Correlations;")
    betas = {row['vector_name']: row['beta_weight'] for row in c.fetchall()}
    
    # 3. Fetch Simulation-Free Factual Post-Mortem Logs
    c.execute("SELECT * FROM Historical_Forecasts ORDER BY evaluated_at DESC LIMIT 10;")
    audits = [dict(row) for row in c.fetchall()]
    
    conn.close()
    return {"forecasts": forecasts, "betas": betas, "audits": audits}

@app.get("/", response_class=HTMLResponse)
def render_dashboard():
    data = fetch_dashboard_data()
    if "error" in data:
        return f"<html><body><h2 style='color:red; font-family:sans-serif;'>{data['error']}</h2></body></html>"
        
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0">
        <title>tennis_lg | S26 Ultra Engine</title>
        <style>
            :root {{
                --bg-main: #0d0d0f;
                --bg-card: #1c1c1e;
                --text-main: #f5f5f7;
                --text-muted: #98989d;
                --accent-primary: #0a84ff;
                --accent-success: #32d74b;
                --accent-danger: #ff453a;
                --accent-purple: #bf5af2;
            }}
            body {{
                background-color: var(--bg-main);
                color: var(--text-main);
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                margin: 0;
                padding: 16px;
                -webkit-font-smoothing: antialiased;
            }}
            h1 {{ font-size: 1.5rem; margin-top: 8px; color: var(--accent-primary); }}
            h2 {{ font-size: 1.2rem; margin-top: 24px; margin-bottom: 12px; color: var(--text-main); border-bottom: 1px solid #333; padding-bottom: 4px; }}
            .card {{
                background: var(--bg-card);
                border-radius: 16px;
                padding: 16px;
                margin-bottom: 16px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            }}
            .card-header {{
                font-size: 1.1rem;
                font-weight: bold;
                margin-bottom: 12px;
                color: var(--text-main);
            }}
            .tour-badge {{
                display: inline-block;
                background: var(--accent-purple);
                color: white;
                font-size: 0.75rem;
                padding: 2px 8px;
                border-radius: 8px;
                vertical-align: middle;
                margin-right: 8px;
            }}
            .stat-row {{
                display: flex;
                justify-content: space-between;
                padding: 8px 0;
                border-bottom: 1px solid #2c2c2e;
                font-size: 0.95rem;
            }}
            .stat-row:last-child {{ border-bottom: none; }}
            .stat-label {{ color: var(--text-muted); }}
            .val-pos {{ color: var(--accent-success); font-weight: bold; }}
            .val-neg {{ color: var(--accent-danger); font-weight: bold; }}
            .beta-grid {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 10px;
            }}
            .beta-pill {{
                background: #2c2c2e;
                padding: 10px;
                border-radius: 10px;
                text-align: center;
                font-size: 0.9rem;
                font-weight: 600;
            }}
            .beta-val {{ color: var(--accent-primary); display: block; margin-top: 4px; font-size: 1.1rem; }}
        </style>
    </head>
    <body>
        <h1>tennis_lg Forecast Terminal</h1>
        
        <h2>Active Vector Correlations (β)</h2>
        <div class="card">
            <div class="beta-grid">
                <div class="beta-pill">Physics <span class="beta-val">{data['betas'].get('v_physics', 1.0):.4f}</span></div>
                <div class="beta-pill">Thermo <span class="beta-val">{data['betas'].get('v_thermo', 1.0):.4f}</span></div>
                <div class="beta-pill">Bio (Fatigue) <span class="beta-val">{data['betas'].get('v_bio', 1.0):.4f}</span></div>
                <div class="beta-pill">Variance <span class="beta-val">{data['betas'].get('v_variance', 1.0):.4f}</span></div>
            </div>
        </div>
        
        <h2>FanDuel Live Slate Projections</h2>
    """
    for f in data['forecasts']:
        fav = f['player_a'] if f['prob_a_win'] >= 0.5 else f['player_b']
        fav_prob = max(f['prob_a_win'], f['prob_b_win']) * 100
        ml = f['american_ml_a'] if fav == f['player_a'] else f['american_ml_b']
        ml_str = f"+{ml}" if ml > 0 else str(ml)
        
        html += f"""
        <div class="card">
            <div class="card-header"><span class="tour-badge">{f['tour']}</span> {f['player_a']} vs {f['player_b']}</div>
            <div class="stat-row"><span class="stat-label">Projected Winner</span> <span class="val-pos">{fav} ({fav_prob:.1f}%)</span></div>
            <div class="stat-row"><span class="stat-label">Fair Moneyline</span> <span>{ml_str}</span></div>
            <div class="stat-row"><span class="stat-label">Game Spread (EV)</span> <span>{f['proj_game_spread']:+.1f} Games</span></div>
            <div class="stat-row"><span class="stat-label">Total Games (O/U)</span> <span>{f['proj_total_games']}</span></div>
            <div class="stat-row"><span class="stat-label">Net Causal Edge</span> <span>{f['net_edge']:+.4f}</span></div>
        </div>
        """
        
    html += "<h2>Factual Post-Mortem Audit</h2>"
    if not data['audits']:
         html += "<div class='card'><div class='stat-label'>No final matches audited yet.</div></div>"
    for a in data['audits']:
        html += f"""
        <div class="card">
            <div class="card-header" style="font-size: 1rem;">{a['player_a']} vs {a['player_b']}</div>
            <div class="stat-row"><span class="stat-label">Official Winner</span> <span class="val-pos">{a['actual_winner']}</span></div>
            <div class="stat-row"><span class="stat-label">Total / Spread</span> <span>{a['actual_total_games']} / {a['actual_game_spread']:+.1f}</span></div>
            <div class="stat-row"><span class="stat-label">Brier Score</span> <span>{a['brier_score']:.4f}</span></div>
            <div class="stat-row"><span class="stat-label">Audited At</span> <span style="font-size: 0.8em; color: var(--text-muted);">{a['evaluated_at']}</span></div>
        </div>
        """
        
    html += """
    </body>
    </html>
    """
    return html

if __name__ == "__main__":
    # Bound to 0.0.0.0 so Codespaces forwards the port to your browser seamlessly
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
