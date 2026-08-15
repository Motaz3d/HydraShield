"""WSGI entry points for gunicorn (production servers).

    gunicorn 'wsgi:api_app'       -> REST API (port 8051)
    gunicorn 'wsgi:dash_server'   -> Dash dashboard (port 8050)
"""

import os

from src.dashboard.api import create_app
from src.dashboard.dashboard import HydraShieldDashboard

api_app = create_app()

_dash = HydraShieldDashboard(
    title="HydraShield Command Center",
    port=int(os.environ.get("PORT", "8050")),
    host="0.0.0.0",
    debug=False,
)
dash_server = _dash.app.server
