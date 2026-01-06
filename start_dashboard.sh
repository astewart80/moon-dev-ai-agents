#!/bin/bash
# Dashboard Startup Script for Raspberry Pi
# Run with: pm2 start start_dashboard.sh --name "dashboard"

cd ~/projects/Trading-Bot

# Activate virtual environment
source venv/bin/activate

# Run the dashboard
python src/scripts/live_dashboard.py
