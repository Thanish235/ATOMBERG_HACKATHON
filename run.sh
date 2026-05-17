#!/usr/bin/env bash
# AtomQuest Goal Portal — quick-start script
set -e

echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Remove stale DB so new schema + seed always loads cleanly
if [ -f atomquest.db ]; then
  echo "🗑️  Removing old database (schema may have changed)..."
  rm atomquest.db
fi

echo ""
echo "🚀 Starting AtomQuest Goal Portal..."
echo "   Open http://localhost:8000 in your browser"
echo "   API docs at http://localhost:8000/docs"
echo ""
echo "   Credentials:"
echo "   Admin:    admin@atomquest.com / admin123"
echo "   Manager:  manager@atomquest.com / manager123"
echo "   Employee: employee@atomquest.com / employee123"
echo ""

uvicorn main:app --reload --host 0.0.0.0 --port 8000
