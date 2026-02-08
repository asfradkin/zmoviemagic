#!/bin/bash
set -e

# Configuration (update these paths for your server)
APP_DIR="/home/ubuntu/zmoviemagic"
VENV_DIR="$APP_DIR/venv"
SERVICE_NAME="zmoviemagic"

echo "Deploying zmoviemagic..."

# Navigate to app directory
if [ ! -d "$APP_DIR" ]; then
    echo "Error: Directory $APP_DIR does not exist."
    exit 1
fi
cd "$APP_DIR"

# Pull latest changes
echo "Pulling latest code..."
git pull origin main

# Update dependencies
if [ -d "$VENV_DIR" ]; then
    echo "Updating dependencies..."
    source "$VENV_DIR/bin/activate"
    pip install -r requirements.txt
else
    echo "Warning: Virtualenv not found at $VENV_DIR. Skipping pip install. Please create venv."
fi

# Restart Service
echo "Restarting $SERVICE_NAME..."
sudo systemctl restart "$SERVICE_NAME"

echo "Deployment complete!"
