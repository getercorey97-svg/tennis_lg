#!/usr/bin/env python3
"""
tennis_lg: Unified Daily Operational Controller
Executes the live scraper, runs Monte Carlo simulations, updates predictions, 
and launches the S26 Ultra web dashboard.
"""

import subprocess
import sys
import os

def run_command(command, description):
    print(f"\n[DAILY PIPELINE] {description}...")
    result = subprocess.run(command, shell=True)
    if result.returncode != 0:
        print(f"[ERROR] Failed during: {description}")
        sys.exit(1)
    print(f"[SUCCESS] {description} complete.")

if __name__ == "__main__":
    print("=======================================================")
    print("  TENNIS_LG: DAILY LIVE AUTOMATION PIPELINE")
    print("=======================================================\n")
    
    # 1. Scrape today's live ESPN tennis schedule and update player vectors
    run_command("python3 scraper.py", "Fetching live ATP/WTA slate")
    
    # 2. Run discrete Markov Monte Carlo simulations for active matches
    run_command("python3 run_pipeline.py", "Generating pre-match Monte Carlo forecasts")
    
    # 3. Run walk-forward backtest audit check
    run_command("python3 backtest.py", "Executing backtest evaluation")
    
    # 4. Stage and push all updated predictions to GitHub
    run_command("git add -A && git commit -m 'Automated daily pipeline sync' || true", "Committing state to Git")
    run_command("git push origin main || true", "Pushing updates to GitHub repository")
    
    print("\n=======================================================")
    print("  PIPELINE FINISHED SUCCESSFULLY")
    print("  Starting S26 Ultra FastAPI Dashboard on Port 8000...")
    print("=======================================================\n")
    
    # 5. Launch FastAPI Web Dashboard
    os.execvp("python3", ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"])
