#!/bin/bash
# Double-click this file to start the Receipt Extractor.
cd "$(dirname "$0")"

# Make sure the local AI engine is running before we open the page.
if ! curl -s --max-time 2 http://127.0.0.1:11434/api/version >/dev/null; then
    echo "Starting Ollama…"
    open -a Ollama
    for i in $(seq 1 30); do
        curl -s --max-time 2 http://127.0.0.1:11434/api/version >/dev/null && break
        sleep 1
    done
fi

echo "Opening the Receipt Extractor in your browser…"
echo "Press Ctrl+C in this window when you are done."
exec app/.venv/bin/streamlit run app/app.py
