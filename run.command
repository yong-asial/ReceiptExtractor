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

# Use the project's virtual environment if there is one, otherwise whatever
# Python is on the PATH. Either way it is Streamlit that starts the app.
if [ -x ".venv/bin/streamlit" ]; then
    STREAMLIT=".venv/bin/streamlit"
elif command -v streamlit >/dev/null 2>&1; then
    STREAMLIT="streamlit"
else
    echo "Streamlit is not installed. Run:  pip install -r app/requirements.txt"
    exit 1
fi

echo "Opening the Receipt Extractor in your browser…"
echo "Press Ctrl+C in this window when you are done."
exec "$STREAMLIT" run app/app.py
