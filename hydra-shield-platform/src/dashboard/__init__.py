"""
HydraShield Interactive Dashboard Module.

Advanced user interface and decision support system with real-time monitoring,
interactive scenario modeling, and explainable AI recommendations.

Imports are lazy: ``plotly``, ``dash``, ``flask`` and friends are only imported
when a heavy symbol is actually requested. This keeps the lightweight data /
analysis modules (``real_data``, ``real_analysis``) importable in environments
that only have ``numpy``/``pandas`` installed.
"""

__version__ = "0.1.0"

__all__ = [
    "HydraShieldDashboard",
    "InteractiveMap",
    "RealTimeMonitor",
    "ScenarioSimulator",
    "ExplainableAIComponent",
    "DecisionSupportSystem",
    "AlertManager",
    "VisualizationEngine",
    "DashboardAPI",
    "StandardFormatsAPI",
    "HydraShieldRealAnalyser",
    "TTLCache",
    "WatchStore",
]

# Mapping of public name -> (module, attribute). ``attribute`` is None when the
# symbol equals the module name (not used here, kept for clarity).
_LAZY_IMPORTS = {
    "HydraShieldDashboard": (".dashboard", "HydraShieldDashboard"),
    "InteractiveMap": (".components", "InteractiveMap"),
    "RealTimeMonitor": (".components", "RealTimeMonitor"),
    "ScenarioSimulator": (".components", "ScenarioSimulator"),
    "ExplainableAIComponent": (".components", "ExplainableAIComponent"),
    "DecisionSupportSystem": (".components", "DecisionSupportSystem"),
    "AlertManager": (".components", "AlertManager"),
    "VisualizationEngine": (".components", "VisualizationEngine"),
    "DashboardAPI": (".api", "DashboardAPI"),
    "StandardFormatsAPI": (".standard_formats_api", "StandardFormatsAPI"),
    "HydraShieldRealAnalyser": (".real_analysis", "HydraShieldRealAnalyser"),
    "TTLCache": (".cache", "TTLCache"),
    "WatchStore": (".monitoring", "WatchStore"),
}


def __getattr__(name):
    import importlib

    entry = _LAZY_IMPORTS.get(name)
    if entry is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute = entry
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(__all__))