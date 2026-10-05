#!/bin/bash
# JC SMART Brain — Deploy Script
# Usage: ./deploy.sh [local|render]

set -e

REPO_URL="https://github.com/arsahatchaleelaha-sudo/jc-smart-brain"
RENDER_DEPLOY_URL="https://render.com/deploy?repo=${REPO_URL}"

case "${1:-local}" in
  local)
    echo "🚀 Starting JC SMART Brain locally on port 8765..."
    PYTHONPATH=src .venv/bin/uvicorn brain.main:app --host 0.0.0.0 --port 8765
    ;;
  tunnel)
    echo "🌐 Starting local server + public tunnel..."
    PYTHONPATH=src .venv/bin/uvicorn brain.main:app --host 127.0.0.1 --port 8765 &
    sleep 4
    npx localtunnel --port 8765 --subdomain jc-smart-brain
    ;;
  render)
    echo "📦 Opening Render deploy page..."
    open "${RENDER_DEPLOY_URL}"
    echo ""
    echo "Steps:"
    echo "  1. Sign in to Render with GitHub"
    echo "  2. Click 'Apply' to create the web service"
    echo "  3. Wait ~2 min for build + deploy"
    echo "  4. Your app will be live at https://jc-smart-brain.onrender.com"
    ;;
  *)
    echo "Usage: ./deploy.sh [local|tunnel|render]"
    echo "  local  — run locally on port 8765 (default)"
    echo "  tunnel  — local + public localtunnel URL"
    echo "  render — open Render.com deploy page"
    ;;
esac
