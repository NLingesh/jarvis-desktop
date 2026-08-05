#!/bin/bash

# JARVIS Setup Script
# This script sets up JARVIS on your system

set -e

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║           JARVIS Voice Assistant Setup                        ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Check Python
echo "✓ Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 not found. Please install Python 3.11+"
    exit 1
fi
python_version=$(python3 --version | awk '{print $2}')
echo "  Found Python $python_version"

# Check Node
echo "✓ Checking Node.js..."
if ! command -v node &> /dev/null; then
    echo "✗ Node.js not found. Please install Node.js 18+"
    exit 1
fi
node_version=$(node --version)
echo "  Found $node_version"

# Create .env file
echo ""
echo "✓ Creating .env file..."
if [ ! -f jarvis_backend/.env ]; then
    cp jarvis_backend/.env.example jarvis_backend/.env
    echo "  Created jarvis_backend/.env"
    echo ""
    echo "⚠️  Please edit jarvis_backend/.env and add:"
    echo "  - MISTRAL_API_KEY (primary, get from https://console.mistral.ai/)"
    echo "  - or ANTHROPIC_API_KEY (fallback, from https://console.anthropic.com/)"
    echo "  - ELEVENLABS_API_KEY (optional, from https://elevenlabs.io/)"
    echo ""
    read -p "Continue after adding API keys? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "  .env file already exists"
fi

# Backend setup
echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  Setting up Backend                                           ║"
echo "╚═══════════════════════════════════════════════════════════════╝"

cd jarvis_backend

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "✓ Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "✓ Activating virtual environment..."
source venv/bin/activate || . venv/Scripts/activate

# Install dependencies
echo "✓ Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

cd ..

# Frontend setup
echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  Setting up Frontend                                          ║"
echo "╚═══════════════════════════════════════════════════════════════╝"

cd jarvis_frontend

echo "✓ Installing Node.js dependencies..."
npm install

cd ..

# Create necessary directories
echo ""
echo "✓ Creating directories..."
mkdir -p ~/.jarvis/notes
mkdir -p jarvis_backend/logs

# Success
echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  ✓ JARVIS Setup Complete!                                    ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "🚀 Quick Start:"
echo ""
echo "  Terminal 1 - Backend:"
echo "    cd jarvis_backend"
echo "    source venv/bin/activate  # or: . venv/Scripts/activate (Windows)"
echo "    python main.py"
echo ""
echo "  Terminal 2 - Frontend:"
echo "    cd jarvis_frontend"
echo "    npm run dev"
echo ""
echo "  Then open: http://localhost:5173"
echo ""
echo "📚 For more info, see JARVIS_README.md"
echo ""
