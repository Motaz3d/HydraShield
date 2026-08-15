"""Production entrypoint for the HydraShield interactive dashboard (Dash)."""
import os

from src.dashboard.dashboard import HydraShieldDashboard

PORT = int(os.environ.get("PORT", "8050"))

dash = HydraShieldDashboard(
    title="HydraShield Command Center",
    port=PORT,
    host="0.0.0.0",
    debug=False,
)

if __name__ == "__main__":
    dash.run()