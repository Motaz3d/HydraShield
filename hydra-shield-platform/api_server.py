"""Production entrypoint for the Talaix REST API (Flask)."""
import os

from src.dashboard.api import DashboardAPI

PORT = int(os.environ.get("PORT", "8051"))

# The primary REST API exposes:
#   GET  /api/status
#   POST /api/risk       (risk + fuel moisture + satellite/weather fusion)
#   POST /api/spread     (fire spread / ROS modelling)
#   POST /api/allocation (water-scarce allocation + WUER)
#   POST /api/simulate   (scenario simulation)
api = DashboardAPI()

if __name__ == "__main__":
    api.app.run(host="0.0.0.0", port=PORT, debug=False)