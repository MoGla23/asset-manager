#!/bin/zsh

# Wechselt in den Ordner, in dem diese Datei liegt (egal von wo sie gestartet wird)
cd "$(dirname "$0")"

# Aktiviert die virtuelle Umgebung
source venv/bin/activate

# Startet die Streamlit-App (öffnet automatisch den Standardbrowser)
streamlit run app.py
