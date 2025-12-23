# Raspberry Pi Trading Bot Setup Guide

Complete guide to running CryptoVerge Bot 24/7 on a Raspberry Pi with remote access via Tailscale.

---

## What You Need

| Item | Cost | Notes |
|------|------|-------|
| Raspberry Pi 4 (2GB+ RAM) | ~$45-60 | 4GB recommended |
| MicroSD card (32GB+) | ~$10 | Class 10 or better |
| Power supply (USB-C 5V/3A) | ~$15 | Official Pi supply recommended |
| Ethernet cable | ~$5 | Recommended over WiFi |
| Case with fan (optional) | ~$15 | Helps with cooling |

**Total: ~$75-100 one-time cost**

---

## Part 1: Raspberry Pi Initial Setup

### Step 1: Install Raspberry Pi OS

1. Download Raspberry Pi Imager from https://www.raspberrypi.com/software/
2. Insert SD card into your laptop
3. Open Imager:
   - Choose OS → Raspberry Pi OS Lite (64-bit)
   - Choose Storage → Your SD card
4. Click gear icon ⚙️ and configure:
   - Enable SSH: Yes
   - Set username: `pi`
   - Set password: (choose a strong one - write it down!)
   - Configure WiFi (if not using ethernet)
   - Set locale/timezone
5. Click Write and wait for completion

### Step 2: Boot & Connect

```bash
# Insert SD card into Pi
# Connect ethernet cable (recommended)
# Plug in power supply

# Wait 1-2 minutes for boot, then from your laptop:
ssh pi@raspberrypi.local
# Enter your password when prompted

# If raspberrypi.local doesn't work, find IP in your router admin page
# Then use: ssh pi@192.168.x.x
```

---

## Part 2: Install Dependencies on Pi

```bash
# Update system (this takes a few minutes)
sudo apt update && sudo apt upgrade -y

# Install Python and required tools
sudo apt install -y python3 python3-pip python3-venv git

# Install build dependencies (needed for some Python packages)
sudo apt install -y build-essential libffi-dev libssl-dev

# Verify Python version (should be 3.9+)
python3 --version
```

### Add Swap Space (Prevents Memory Errors)

```bash
# Increase swap for package installation
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile

# Find the line CONF_SWAPSIZE=100
# Change it to CONF_SWAPSIZE=2048
# Press Ctrl+X, then Y, then Enter to save

sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

---

## Part 3: Copy Your Bot to the Pi

### Option A: Using SCP (Recommended)

From your **laptop terminal** (not SSH):

```bash
# Copy entire bot folder to Pi
scp -r "/Users/Andrew/Desktop/Claude Projects/Trading Bot" pi@raspberrypi.local:/home/pi/trading-bot
```

### Option B: Using USB Drive

1. Copy `Trading Bot` folder to USB drive on laptop
2. Plug USB into Pi
3. On Pi via SSH:

```bash
# Find USB device
lsblk

# Mount USB (usually /dev/sda1)
sudo mkdir -p /mnt/usb
sudo mount /dev/sda1 /mnt/usb

# Copy files
cp -r "/mnt/usb/Trading Bot" /home/pi/trading-bot

# Unmount
sudo umount /mnt/usb
```

### Option C: Using Git

If your bot is in a Git repository:

```bash
cd /home/pi
git clone https://github.com/yourusername/your-repo.git trading-bot
```

---

## Part 4: Setup Bot Environment on Pi

```bash
# SSH into Pi (if not already connected)
ssh pi@raspberrypi.local

# Navigate to bot folder
cd /home/pi/trading-bot

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install requirements (takes 10-15 minutes on Pi)
pip install -r requirements.txt
```

**If installation fails with memory errors:**
- Make sure you added swap space (Part 2)
- Try installing packages one at a time:
```bash
pip install hyperliquid-python-sdk
pip install pandas
pip install numpy
# etc.
```

---

## Part 5: Configure Environment Variables

```bash
# Create/edit .env file
nano /home/pi/trading-bot/.env
```

Copy all contents from your laptop's `.env` file and paste into nano.

**Important keys to include:**
```
HYPER_LIQUID_ETH_PRIVATE_KEY=your_key_here
GROK_API_KEY=your_key_here
# ... all other keys from your laptop .env
```

Press `Ctrl+X`, then `Y`, then `Enter` to save.

**Security tip:** Make sure .env permissions are restricted:
```bash
chmod 600 /home/pi/trading-bot/.env
```

---

## Part 6: Test the Bot

```bash
cd /home/pi/trading-bot
source venv/bin/activate

# Run bot manually to test
python src/main.py
```

Watch for:
- ✅ "HyperLiquid account initialized"
- ✅ "Trading symbols: ['BTC', 'ETH', ...]"
- ✅ "AI Agent Analyzing Token: ..."

If working, press `Ctrl+C` to stop.

---

## Part 7: Install Tailscale (Remote Access)

Tailscale lets you access your Pi from anywhere securely.

### On Raspberry Pi:

```bash
# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Start Tailscale (will show authentication URL)
sudo tailscale up

# Open the URL in your browser and sign in
# Use Google, Microsoft, or GitHub account

# After authenticating, get your Pi's Tailscale IP
tailscale ip -4
# Example output: 100.84.52.123
# WRITE THIS DOWN - you'll use it to connect remotely
```

### On Your Laptop/Phone:

1. Go to https://tailscale.com/download
2. Download and install Tailscale for your device
3. Sign in with the **SAME account** you used on the Pi
4. Your devices are now on the same private network!

### Enable Tailscale at Boot:

```bash
sudo systemctl enable tailscaled
```

---

## Part 8: Auto-Start Bot on Boot

### Create Bot Service

```bash
sudo nano /etc/systemd/system/tradingbot.service
```

Paste this content:

```ini
[Unit]
Description=CryptoVerge Trading Bot
After=network.target tailscaled.service
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/trading-bot
ExecStart=/home/pi/trading-bot/venv/bin/python src/main.py
Restart=always
RestartSec=30
StandardOutput=append:/home/pi/trading-bot/logs/bot.log
StandardError=append:/home/pi/trading-bot/logs/bot.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Press `Ctrl+X`, `Y`, `Enter` to save.

### Enable Bot Service

```bash
# Create logs directory
mkdir -p /home/pi/trading-bot/logs

# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable tradingbot

# Start the bot now
sudo systemctl start tradingbot

# Check status
sudo systemctl status tradingbot
```

---

## Part 9: Auto-Start Dashboard

### Create Dashboard Service

```bash
sudo nano /etc/systemd/system/dashboard.service
```

Paste this content:

```ini
[Unit]
Description=CryptoVerge Dashboard
After=network.target tailscaled.service
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/trading-bot
ExecStart=/home/pi/trading-bot/venv/bin/python src/scripts/live_dashboard.py
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### Enable Dashboard Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable dashboard
sudo systemctl start dashboard
sudo systemctl status dashboard
```

---

## Part 10: Access From Anywhere

### Get Your Tailscale IP

```bash
tailscale ip -4
# Example: 100.84.52.123
```

### Connect Remotely

**Make sure Tailscale is running on your laptop/phone!**

| Access | URL/Command |
|--------|-------------|
| Dashboard | `http://100.84.52.123:8081` |
| SSH | `ssh pi@100.84.52.123` |
| View Logs | `ssh pi@100.84.52.123 "tail -f /home/pi/trading-bot/logs/bot.log"` |

---

## Quick Reference Commands

### Bot Management

```bash
# Check bot status
sudo systemctl status tradingbot

# Start bot
sudo systemctl start tradingbot

# Stop bot
sudo systemctl stop tradingbot

# Restart bot
sudo systemctl restart tradingbot

# View live logs
tail -f /home/pi/trading-bot/logs/bot.log

# View last 100 log lines
tail -100 /home/pi/trading-bot/logs/bot.log
```

### Dashboard Management

```bash
# Check dashboard status
sudo systemctl status dashboard

# Restart dashboard
sudo systemctl restart dashboard

# Stop dashboard
sudo systemctl stop dashboard
```

### System Commands

```bash
# Reboot Pi
sudo reboot

# Shutdown Pi
sudo shutdown -h now

# Check CPU temperature
vcgencmd measure_temp

# Check disk space
df -h

# Check memory usage
free -h

# Check Tailscale status
tailscale status
```

### Updating the Bot

```bash
# Stop services
sudo systemctl stop tradingbot
sudo systemctl stop dashboard

# Navigate to bot folder
cd /home/pi/trading-bot

# If using Git:
git pull

# If manually copying, use scp from laptop:
# scp -r "/Users/Andrew/Desktop/Claude Projects/Trading Bot/src" pi@raspberrypi.local:/home/pi/trading-bot/

# Restart services
sudo systemctl start tradingbot
sudo systemctl start dashboard
```

---

## Troubleshooting

### Bot won't start

```bash
# Check logs for errors
sudo journalctl -u tradingbot -n 50

# Try running manually
cd /home/pi/trading-bot
source venv/bin/activate
python src/main.py
```

### Can't connect via Tailscale

1. Make sure Tailscale is running on BOTH devices
2. Check if Pi is online: `tailscale status`
3. Try: `sudo tailscale down && sudo tailscale up`

### High CPU/Temperature

```bash
# Check temperature (should be under 80°C)
vcgencmd measure_temp

# If too hot, add a fan or heatsink
# Or reduce analysis frequency in trading_agent.py:
# SLEEP_BETWEEN_RUNS_MINUTES = 30
```

### Out of disk space

```bash
# Check disk usage
df -h

# Clear old logs
rm /home/pi/trading-bot/logs/*.log

# Clear pip cache
pip cache purge
```

---

## Security Checklist

- [ ] Changed default Pi password
- [ ] .env file has restricted permissions (chmod 600)
- [ ] Tailscale 2FA enabled (https://tailscale.com → Settings)
- [ ] No ports forwarded on router (Tailscale handles access)
- [ ] Regular system updates (`sudo apt update && sudo apt upgrade`)

---

## Setup Checklist

- [ ] Raspberry Pi OS installed on SD card
- [ ] SSH access working
- [ ] System updated (`apt update && upgrade`)
- [ ] Python 3.9+ installed
- [ ] Swap space increased to 2GB
- [ ] Bot folder copied to `/home/pi/trading-bot`
- [ ] Virtual environment created and activated
- [ ] Requirements installed (`pip install -r requirements.txt`)
- [ ] `.env` file configured with API keys
- [ ] Bot tested manually (`python src/main.py`)
- [ ] Tailscale installed and authenticated on Pi
- [ ] Tailscale installed on laptop/phone
- [ ] Bot systemd service created and enabled
- [ ] Dashboard systemd service created and enabled
- [ ] Can access dashboard via Tailscale IP
- [ ] Both services start automatically on reboot

---

## Support

If you run into issues:
1. Check the logs: `tail -f /home/pi/trading-bot/logs/bot.log`
2. Check service status: `sudo systemctl status tradingbot`
3. Try running manually to see errors: `python src/main.py`

---

*Last updated: December 2024*
