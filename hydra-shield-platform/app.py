"""Production entrypoint for the Talaix interactive dashboard (Dash)."""
import os

from src.dashboard.dashboard import TalaixDashboard

PORT = int(os.environ.get("PORT", "8050"))

dash = TalaixDashboard(
    title="Talaix Command Center",
    port=PORT,
    host="0.0.0.0",
    debug=False,
)

if __name__ == "__main__":
    dash.run()