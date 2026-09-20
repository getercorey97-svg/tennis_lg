#!/usr/bin/env python3
"""
tennis_lg: Live Slate Data Ingestion Utility
Use this to add real players, tournaments, and daily matches to the operational database.
"""
import sqlite3
import argparse
from datetime import datetime

DB_NAME = "tennis_lg.db"

def add_tournament(conn):
    print("\n--- Add New Tournament ---")
    t_id = input("Tournament ID (e.g., ATP_CINCINNATI): ").strip().upper()
    name = input("Tournament Name (e.g., Cincinnati Masters): ").strip()
    tour = input("Tour (ATP/WTA/ITF/ATF): ").strip().upper()
    surface = input("Surface (Hard/Clay/Grass): ").strip().capitalize()
    cpi = float(input("Court Pace Index (e.g., 42.0 for fast hard, 28.0 for clay): "))
    elevation = float(input("Elevation in meters (e.g., 200): "))
    best_of = int(input("Best of (3 or 5): "))
    
    conn.execute("INSERT OR REPLACE INTO Tournaments VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                 (t_id, name, tour, surface, cpi, elevation, best_of))
    conn.commit()
    print(f"Tournament {name} added.")

def add_player(conn):
    print("\n--- Add New Player ---")
    p_id = input("Player ID (e.g., ATP_DJOKOVIC): ").strip().upper()
    name = input("Player Name: ").strip()
    tour = input("Tour (ATP/WTA/ITF/ATF): ").strip().upper()
    hand = input("Handedness (R/L): ").strip().upper()
    bh = input("Backhand (1H/2H): ").strip().upper()
    serve_p = float(input("True Serve Win % (e.g., 0.685): "))
    ret_q = float(input("True Return Win % (e.g., 0.415): "))
    rpm = float(input("Topspin RPM (e.g., 3100): "))
    sample = int(input("Historical Sample Points (e.g., 15000): "))
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT OR REPLACE INTO Players VALUES (?, ?, ?, ?, ?, ?, ?, 0.65, 0.40, ?, ?, 0.0, 3, ?)",
                 (p_id, name, tour, hand, bh, serve_p, ret_q, rpm, sample, now))
    conn.commit()
    print(f"Player {name} added.")

def schedule_match(conn):
    print("\n--- Schedule Match for Today's Slate ---")
    m_id = input("Unique Match ID (e.g., MATCH_005): ").strip().upper()
    t_id = input("Tournament ID (must exist in DB): ").strip().upper()
    tour = input("Tour (ATP/WTA/ITF/ATF): ").strip().upper()
    p_a = input("Player A ID (must exist in DB): ").strip().upper()
    p_b = input("Player B ID (must exist in DB): ").strip().upper()
    temp = float(input("Forecasted Temp in Celsius (e.g., 28.5): "))
    hum = float(input("Forecasted Humidity % (e.g., 60.0): "))
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT OR REPLACE INTO Daily_Card VALUES (?, ?, ?, ?, ?, ?, ?, 'SCHEDULED', ?)",
                 (m_id, t_id, tour, p_a, p_b, temp, hum, now))
    conn.commit()
    print(f"Match {m_id} scheduled. Run 'python3 run_pipeline.py' to generate predictions.")

if __name__ == "__main__":
    conn = sqlite3.connect(DB_NAME)
    while True:
        print("\n=== tennis_lg Data Ingestion ===")
        print("1. Add Tournament")
        print("2. Add Player Profile")
        print("3. Schedule Match")
        print("4. Exit")
        choice = input("Select operation (1-4): ").strip()
        
        if choice == '1': add_tournament(conn)
        elif choice == '2': add_player(conn)
        elif choice == '3': schedule_match(conn)
        elif choice == '4': break
        else: print("Invalid selection.")
    
    conn.close()
