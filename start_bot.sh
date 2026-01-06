#!/bin/bash
# Trading Bot Startup Script for Raspberry Pi
# Run with: pm2 start start_bot.sh --name "trading-bot"

cd ~/projects/Trading-Bot

# Activate virtual environment
source venv/bin/activate

# Run the trading agent
python src/agents/trading_agent.py
