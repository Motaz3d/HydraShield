"""
Module to run the HydraShield Dashboard.

This module provides a simple way to start the interactive dashboard
with all its components and integrations.
"""

from .dashboard import HydraShieldDashboard


def run_dashboard(
    title: str = "HydraShield Command Center",
    port: int = 8050,
    host: str = "0.0.0.0",
    debug: bool = True
):
    """
    Run the HydraShield Dashboard.
    
    Parameters
    ----------
    title : str
        Title for the dashboard
    port : int
        Port to run the dashboard on
    host : str
        Host to run the dashboard on
    debug : bool
        Enable debug mode
    """
    dashboard = HydraShieldDashboard(title=title, port=port, host=host, debug=debug)
    dashboard.run()


if __name__ == "__main__":
    run_dashboard()