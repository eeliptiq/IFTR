#!/bin/bash
# setup.sh for Stemulsify/IFTR backend

echo "Setting up Python virtual environment..."

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install requirements
pip install -r requirements.txt

# Create necessary directories
mkdir -p sessions uploads logs

echo "Environment setup complete!"
echo "To activate: source venv/bin/activate"
echo "To run: python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"