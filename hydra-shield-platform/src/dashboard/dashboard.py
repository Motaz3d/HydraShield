"""
Interactive Dashboard for Talaix Wildfire Protection System.

Advanced user interface and decision support system with real-time monitoring,
interactive scenario modeling, and explainable AI recommendations.
"""

from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from dash import Dash, dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
from datetime import datetime, timedelta

from ..prediction.risk_model import AdvancedWildfireRiskModel
from ..prediction.fire_spread import FireSpreadModel
from ..gis_mapping.data_fusion import DataFusionPipeline
from ..hydration_control.water_optimiser import WaterOptimiser
from ..hydration_control.intervention import InterventionPlanner
from .real_analysis import TalaixRealAnalyser
from .components import (
    InteractiveMap,
    RealTimeMonitor,
    ScenarioSimulator,
    ExplainableAIComponent,
    DecisionSupportSystem,
    AlertManager,
    VisualizationEngine
)


# Run the (expensive, external-data) analysis at most once per location per
# TTL window, shared across all callbacks of a single button click.
_ANALYSIS_CACHE: Dict[str, Tuple[float, Dict]] = {}
_ANALYSIS_TTL_S = 900.0


def _analyse_once(location_query: str) -> Dict:
    import time

    now = time.time()
    hit = _ANALYSIS_CACHE.get(location_query)
    if hit and now - hit[0] < _ANALYSIS_TTL_S:
        return hit[1]
    result = TalaixRealAnalyser().analyse(location_query)
    _ANALYSIS_CACHE[location_query] = (now, result)
    return result


class TalaixDashboard:
    """
    Main dashboard class for Talaix wildfire protection system.
    
    Provides an interactive interface for monitoring, decision support,
    scenario modeling, and real-time wildfire risk assessment.
    """
    
    def __init__(
        self,
        title: str = "Talaix Command Center",
        port: int = 8050,
        host: str = "0.0.0.0",
        debug: bool = True
    ):
        self.title = title
        self.port = port
        self.host = host
        self.debug = debug
        
        # Initialize core Talaix components
        self.risk_model = AdvancedWildfireRiskModel()
        self.spread_model = FireSpreadModel()
        self.fusion_pipeline = DataFusionPipeline()
        self.water_optimiser = WaterOptimiser()
        self.intervention_planner = InterventionPlanner()
        
        # Initialize dashboard components
        self.interactive_map = InteractiveMap()
        self.real_time_monitor = RealTimeMonitor()
        self.scenario_simulator = ScenarioSimulator()
        self.explainable_ai = ExplainableAIComponent()
        self.decision_support = DecisionSupportSystem()
        self.alert_manager = AlertManager()
        self.visualization_engine = VisualizationEngine()
        
        # Create Dash app
        self.app = Dash(
            __name__,
            title=title,
            external_stylesheets=[dbc.themes.BOOTSTRAP],
            suppress_callback_exceptions=True
        )
        
        # Setup dashboard layout
        self.setup_layout()
        self.setup_callbacks()
    
    def setup_layout(self):
        """Initialize the dashboard layout."""
        self.app.layout = dbc.Container([
            dbc.Row([
                dbc.Col(html.H1(self.title, className="text-center mb-4"), width=12)
            ]),
            
            # Location selection section
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Location Selection"),
                        dbc.CardBody([
                            html.P("Enter a location to analyze real Earth Observation data:", className="mb-2"),
                            dcc.Input(
                                id='location-input',
                                type='text',
                                placeholder='Enter location (e.g., Clervaux, Luxembourg)',
                                value='Clervaux, Luxembourg',
                                style={'width': '100%', 'padding': '10px', 'fontSize': '16px'}
                            ),
                            html.Br(),
                            html.Br(),
                            html.Button('Analyze Location', id='analyze-location-btn', n_clicks=0, 
                                       className='btn btn-primary', style={'width': '100%'}),
                            html.Div(id='location-status', className='mt-2')
                        ])
                    ])
                ], width=12)
            ], className="mb-4"),
            
            # Real-time monitoring section
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Real-Time Monitoring"),
                        dbc.CardBody([
                            dcc.Graph(id='real-time-risk-graph'),
                            html.Div(id='current-risk-display', className='mt-3')
                        ])
                    ])
                ], width=4),
                
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Environmental Conditions"),
                        dbc.CardBody([
                            html.Div(id='env-conditions-display'),
                            html.Div(id='real-data-display', className='mt-3')
                        ])
                    ])
                ], width=4),
                
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Resource Allocation"),
                        dbc.CardBody([
                            dcc.Graph(id='water-allocation-graph'),
                            html.Div(id='wuer-display', className='mt-3')
                        ])
                    ])
                ], width=4)
            ], className="mb-4"),
            
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Interactive Map"),
                        dbc.CardBody([
                            dcc.Graph(id='interactive-map', style={'height': '500px'})
                        ])
                    ])
                ], width=8),
                
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("AI Recommendations"),
                        dbc.CardBody([
                            html.Div(id='ai-recommendations-display'),
                            html.Div(id='recommendation-explanation', className='mt-3')
                        ])
                    ])
                ], width=4)
            ], className="mb-4"),
            
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Scenario Simulator"),
                        dbc.CardBody([
                            html.Div(id='scenario-analysis-display', className='mb-3'),
                            dcc.Dropdown(
                                id='scenario-dropdown',
                                options=[
                                    {'label': 'Baseline Conditions', 'value': 'baseline'},
                                    {'label': 'With Talaix Intervention', 'value': 'intervention'}
                                ],
                                value='baseline'
                            ),
                            dcc.Graph(id='scenario-comparison-graph'),
                            html.Button('Compare Scenarios', id='compare-scenarios-btn', className='btn btn-primary mt-3')
                        ])
                    ])
                ], width=12)
            ], className="mb-4"),
            
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Alerts & Notifications"),
                        dbc.CardBody([
                            html.Div(id='alerts-display')
                        ])
                    ])
                ], width=12)
            ])
        ], fluid=True)
    
    def setup_callbacks(self):
        """Setup dashboard callbacks for interactivity."""
        
        @self.app.callback(
            [Output('real-time-risk-graph', 'figure'),
             Output('current-risk-display', 'children')],
            [Input('analyze-location-btn', 'n_clicks')],
            [State('location-input', 'value')]
        )
        def update_main_outputs(n_clicks, location_query):
            # This is the first part of the update - just the main outputs
            # We'll update other parts separately to avoid the long callback issue
            if n_clicks is None or n_clicks == 0:
                # Return initial empty state
                fig = go.Figure(data=[go.Indicator(mode="gauge+number", value=0, 
                                                  title={'text': "Fire Risk Level"},
                                                  gauge={'axis': {'range': [None, 100]},
                                                         'steps': [{'range': [0, 30], 'color': "lightgreen"},
                                                                   {'range': [30, 70], 'color': "yellow"},
                                                                   {'range': [70, 100], 'color': "red"}]})])
                risk_display = dbc.Alert("Enter a location and click 'Analyze Location'", color="info")
                return fig, risk_display
            
            try:
                # Run the analysis once per click (shared, TTL-cached)
                result = _analyse_once(location_query)
                
                if 'error' in result:
                    error_msg = result['error']
                    fig = go.Figure(data=[go.Indicator(mode="gauge+number", value=0, 
                                                      title={'text': "Fire Risk Level"},
                                                      gauge={'axis': {'range': [None, 100]},
                                                             'steps': [{'range': [0, 30], 'color': "lightgreen"},
                                                                       {'range': [30, 70], 'color': "yellow"},
                                                                       {'range': [70, 100], 'color': "red"}]})])
                    risk_display = dbc.Alert(f"Error: {error_msg}", color="danger")
                    return fig, risk_display
                
                # Extract data from analysis
                risk_data = result['analysis']
                location_data = result['location']
                
                # Risk visualization
                risk_value = risk_data['risk']['baseline']
                risk_level = self.get_risk_level(risk_value)
                risk_color = {"green": "success", "yellow": "warning", "red": "danger"}[risk_level]
                
                fig = go.Figure(data=[
                    go.Indicator(
                        mode="gauge+number",
                        value=risk_value,
                        domain={'x': [0, 1], 'y': [0, 1]},
                        title={'text': "Fire Risk Level"},
                        gauge={
                            'axis': {'range': [None, 100]},
                            'bar': {'color': "darkblue"},
                            'steps': [
                                {'range': [0, 30], 'color': "lightgreen"},
                                {'range': [30, 70], 'color': "yellow"},
                                {'range': [70, 100], 'color': "red"}
                            ],
                            'threshold': {
                                'line': {'color': "red", 'width': 4},
                                'thickness': 0.75,
                                'value': risk_value
                            }
                        }
                    )
                ])
                
                risk_display = dbc.Alert(
                    f"Current Risk Level: {risk_value:.1f}% ({risk_level.capitalize()})",
                    color=risk_color
                )
                
                return fig, risk_display
            except Exception as e:
                error_msg = f"Analysis failed: {str(e)}"
                fig = go.Figure(data=[go.Indicator(mode="gauge+number", value=0, 
                                                  title={'text': "Fire Risk Level"},
                                                  gauge={'axis': {'range': [None, 100]},
                                                         'steps': [{'range': [0, 30], 'color': "lightgreen"},
                                                                   {'range': [30, 70], 'color': "yellow"},
                                                                   {'range': [70, 100], 'color': "red"}]})])
                risk_display = dbc.Alert(f"Error: {error_msg}", color="danger")
                return fig, risk_display

        @self.app.callback(
            [Output('env-conditions-display', 'children'),
             Output('real-data-display', 'children')],
            [Input('analyze-location-btn', 'n_clicks')],
            [State('location-input', 'value')]
        )
        def update_environmental_outputs(n_clicks, location_query):
            if n_clicks is None or n_clicks == 0:
                return html.Div("Waiting for location analysis..."), html.Div("Real Earth Observation data will appear here")
            
            try:
                # Run the analysis once per click (shared, TTL-cached)
                result = _analyse_once(location_query)
                
                if 'error' in result:
                    return html.Div("Analysis failed"), html.Div("No data available")
                
                # Extract data from analysis
                risk_data = result['analysis']
                location_data = result['location']
                weather_data = result['weather']
                terrain_data = result['terrain']
                
                # Environmental conditions display
                env_display = html.Div([
                    html.H5("Environmental Conditions", className="card-title"),
                    html.P(f"Temperature: {weather_data.get('temperature_c', 'N/A')}°C", className="card-text"),
                    html.P(f"Humidity: {weather_data.get('relative_humidity_pct', 'N/A')}%", className="card-text"),
                    html.P(f"Wind Speed: {weather_data.get('wind_speed_kmh', 'N/A')} km/h", className="card-text"),
                    html.P(f"Elevation: {terrain_data.get('elevation_m', 'N/A')} m", className="card-text"),
                    html.P(f"Slope: {terrain_data.get('slope_degrees', 'N/A')}°", className="card-text"),
                ])
                
                # Real data display
                real_data_display = html.Div([
                    html.H5("Real Data Sources", className="card-title"),
                    html.P(f"Location: {location_data['name']}", className="card-text"),
                    html.P(f"Fuel Moisture: {risk_data['fuel_moisture_baseline_pct']}% ({risk_data['fuel_moisture_source']})", className="card-text"),
                    html.P(f"Data Quality: {result['data_quality']['components']['weather']}", className="card-text"),
                    html.P(f"Observation Date: {weather_data.get('timestamp', 'N/A')}", className="card-text"),
                ])
                
                return env_display, real_data_display
            except Exception as e:
                return html.Div("Analysis failed"), html.Div("No data available")

        @self.app.callback(
            [Output('water-allocation-graph', 'figure'),
             Output('wuer-display', 'children')],
            [Input('analyze-location-btn', 'n_clicks')],
            [State('location-input', 'value')]
        )
        def update_allocation_outputs(n_clicks, location_query):
            if n_clicks is None or n_clicks == 0:
                return (px.bar(x=['School', 'Hospital', 'Residential', 'Evac Route'], y=[0, 0, 0, 0]),
                        html.Div([html.H5("WUER: 0.0000"), html.P("Risk reduction per m³ of water applied")]))
            
            try:
                # Run the analysis once per click (shared, TTL-cached)
                result = _analyse_once(location_query)
                
                if 'error' in result:
                    return (px.bar(x=['School', 'Hospital', 'Residential', 'Evac Route'], y=[0, 0, 0, 0]),
                            html.Div([html.H5("WUER: 0.0000"), html.P("Risk reduction per m³ of water applied")]))
                
                # Extract data from analysis
                risk_data = result['analysis']
                
                # Risk value for allocation
                risk_value = risk_data['risk']['baseline']
                
                # Create allocation visualization
                base_allocation = 500.0
                risk_factor = risk_value / 100.0
                
                allocations = [
                    base_allocation * 0.3 * risk_factor,    # School
                    base_allocation * 0.4 * risk_factor,    # Hospital (highest priority)
                    base_allocation * 0.2 * risk_factor,    # Residential
                    base_allocation * 0.1 * risk_factor     # Evacuation route
                ]
                
                alloc_fig = px.bar(
                    x=['School', 'Hospital', 'Residential', 'Evac Route'],
                    y=allocations,
                    labels={'x': 'Zone', 'y': 'Water Allocated (m³)'},
                    title='Water Allocation by Zone'
                )
                
                # WUER display
                wuer_value = risk_data['wuer']['wuer'] if risk_data['wuer'] else 0.0
                wuer_display = html.Div([
                    html.H5(f"WUER: {wuer_value:.4f}"),
                    html.P("Risk reduction per m³ of water applied")
                ])
                
                return alloc_fig, wuer_display
            except Exception as e:
                return (px.bar(x=['School', 'Hospital', 'Residential', 'Evac Route'], y=[0, 0, 0, 0]),
                        html.Div([html.H5("WUER: 0.0000"), html.P("Risk reduction per m³ of water applied")]))

        @self.app.callback(
            [Output('ai-recommendations-display', 'children'),
             Output('recommendation-explanation', 'children')],
            [Input('analyze-location-btn', 'n_clicks')],
            [State('location-input', 'value')]
        )
        def update_recommendation_outputs(n_clicks, location_query):
            if n_clicks is None or n_clicks == 0:
                return (dbc.Card([dbc.CardBody([html.H5("Recommendation: WAITING", className="card-title")])], 
                                 color="info", inverse=True),
                        dbc.Card([dbc.CardBody([html.H5("Reasoning:", className="card-title"), 
                                                html.P("Waiting for analysis...", className="card-text")])]))
            
            try:
                # Run the analysis once per click (shared, TTL-cached)
                result = _analyse_once(location_query)
                
                if 'error' in result:
                    error_msg = result['error']
                    return (dbc.Card([dbc.CardBody([html.H5("Recommendation: ERROR", className="card-title")])], 
                                     color="danger", inverse=True),
                            dbc.Card([dbc.CardBody([html.H5("Reasoning:", className="card-title"), 
                                                    html.P(error_msg, className="card-text")])]))
                
                # Generate recommendation based on risk
                recommendation, explanation = self.generate_ai_recommendation_from_analysis(result)
                
                recommendation_card = dbc.Card([
                    dbc.CardBody([
                        html.H5(f"Recommendation: {recommendation}", className="card-title"),
                    ])
                ], color="info", inverse=True)
                
                explanation_card = dbc.Card([
                    dbc.CardBody([
                        html.H5("Reasoning:", className="card-title"),
                        html.P(explanation, className="card-text")
                    ])
                ])
                
                return recommendation_card, explanation_card
            except Exception as e:
                error_msg = f"Analysis failed: {str(e)}"
                return (dbc.Card([dbc.CardBody([html.H5("Recommendation: ERROR", className="card-title")])], 
                                 color="danger", inverse=True),
                        dbc.Card([dbc.CardBody([html.H5("Reasoning:", className="card-title"), 
                                                html.P(error_msg, className="card-text")])]))

        @self.app.callback(
            [Output('interactive-map', 'figure'),
             Output('scenario-analysis-display', 'children')],
            [Input('analyze-location-btn', 'n_clicks')],
            [State('location-input', 'value')]
        )
        def update_map_scenario_outputs(n_clicks, location_query):
            if n_clicks is None or n_clicks == 0:
                return (go.Figure(),
                        html.Div("Analyze a location to see scenario comparisons"))
            
            try:
                # Run the analysis once per click (shared, TTL-cached)
                result = _analyse_once(location_query)
                
                if 'error' in result:
                    return (go.Figure(),
                            html.Div("Analysis failed"))
                
                # Create map visualization
                map_fig = self.create_map_from_analysis(result)
                
                # Extract data for scenario analysis
                risk_data = result['analysis']
                
                # Scenario analysis display
                scenario_display = html.Div([
                    html.H6("Scenario Analysis"),
                    html.P(f"Baseline Risk: {risk_data['risk']['baseline']:.1f}%"),
                    html.P(f"With Talaix: {risk_data['risk']['intervention']:.1f}%" if risk_data['risk']['intervention'] else "Not calculated"),
                    html.P(f"Risk Reduction: {risk_data['risk']['reduction_percent']:.1f}%" if risk_data['risk']['reduction_percent'] else "Not calculated"),
                    html.P(f"Water Savings: {risk_data['water_savings_pct']:.1f}%")
                ])
                
                return map_fig, scenario_display
            except Exception as e:
                return (go.Figure(),
                        html.Div("Analysis failed"))

        @self.app.callback(
            [Output('alerts-display', 'children'),
             Output('location-status', 'children')],
            [Input('analyze-location-btn', 'n_clicks')],
            [State('location-input', 'value')]
        )
        def update_alert_status_outputs(n_clicks, location_query):
            if n_clicks is None or n_clicks == 0:
                return (html.Div("No alerts"),
                        dbc.Alert("Please enter a location and click 'Analyze Location'", color="secondary"))
            
            try:
                # Run the analysis once per click (shared, TTL-cached)
                result = _analyse_once(location_query)
                
                if 'error' in result:
                    error_msg = result['error']
                    return (html.Div("No alerts"),
                            dbc.Alert(f"Error analyzing location: {error_msg}", color="danger"))
                
                # Extract data from analysis
                location_data = result['location']
                
                # Generate alerts
                alerts_display = self.generate_alerts_from_analysis(result)
                
                # Status
                status = dbc.Alert(f"Successfully analyzed: {location_data['name']}", color="success")
                
                return alerts_display, status
            except Exception as e:
                error_msg = f"Analysis failed: {str(e)}"
                return (html.Div("No alerts"),
                        dbc.Alert(error_msg, color="danger"))
    
    def generate_ai_recommendation_from_analysis(self, analysis_result):
        """Generate AI recommendation from the analysis result."""
        risk_value = analysis_result['analysis']['risk']['baseline']
        
        if risk_value > 80:
            recommendation = "EVACUATE IMMEDIATELY"
            explanation = f"Extremely high risk ({risk_value:.1f}%) detected. Immediate evacuation recommended for all zones."
        elif risk_value > 60:
            recommendation = "ACTIVATE PROTECTION ZONES"
            explanation = f"High risk ({risk_value:.1f}%) detected. Activate protection zones with water intervention."
        elif risk_value > 40:
            recommendation = "MONITOR & PREPARE"
            explanation = f"Moderate risk ({risk_value:.1f}%) detected. Continue monitoring and prepare intervention teams."
        else:
            recommendation = "CONTINUE MONITORING"
            explanation = f"Low risk ({risk_value:.1f}%) detected. Standard monitoring procedures adequate."
        
        return recommendation, explanation
    
    def create_map_from_analysis(self, analysis_result):
        """Create map visualization from the analysis result."""
        location_data = analysis_result['location']
        risk_data = analysis_result['analysis']
        
        # Create a simple map centered on the location
        fig = go.Figure(data=go.Scattergeo(
            lon=[location_data['longitude']],
            lat=[location_data['latitude']],
            mode='markers',
            marker=dict(
                size=15,
                color=risk_data['risk']['baseline'],
                colorscale='Viridis',
                colorbar=dict(title="Risk Level"),
                cmin=0,
                cmax=100,
                showscale=True
            ),
            text=[location_data['name']],
            hovertemplate="<b>%{text}</b><br>" +
                         "Risk: %{marker.color:.1f}%<br>" +
                         "Lat: %{lat:.4f}<br>" +
                         "Lon: %{lon:.4f}<br>" +
                         "<extra></extra>"
        ))
        
        fig.update_layout(
            title=f'Risk Assessment for {location_data["name"]}',
            geo=dict(
                projection_type='mercator',
                showland=True,
                landcolor="rgb(212, 212, 212)",
                subunitcolor="rgb(255, 255, 255)",
                countrycolor="rgb(255, 255, 255)",
                center=dict(lat=location_data['latitude'], lon=location_data['longitude']),
                lataxis_range=[location_data['latitude']-1, location_data['latitude']+1],
                lonaxis_range=[location_data['longitude']-1, location_data['longitude']+1]
            )
        )
        
        return fig
    
    def generate_alerts_from_analysis(self, analysis_result):
        """Generate alerts based on the analysis result."""
        risk_value = analysis_result['analysis']['risk']['baseline']
        
        alerts = []
        if risk_value > 80:
            alerts.append({
                'title': 'CRITICAL FIRE RISK',
                'message': f'Risk level at {risk_value:.1f}% - Immediate action required',
                'severity': 'high'
            })
        elif risk_value > 60:
            alerts.append({
                'title': 'HIGH FIRE RISK',
                'message': f'Risk level at {risk_value:.1f}% - Enhanced monitoring needed',
                'severity': 'high'
            })
        elif risk_value > 40:
            alerts.append({
                'title': 'MODERATE FIRE RISK',
                'message': f'Risk level at {risk_value:.1f}% - Standard precautions advised',
                'severity': 'moderate'
            })
        else:
            alerts.append({
                'title': 'LOW FIRE RISK',
                'message': f'Risk level at {risk_value:.1f}% - Normal conditions',
                'severity': 'low'
            })
        
        alert_elements = []
        for alert in alerts:
            alert_type = {"high": "danger", "moderate": "warning", "low": "info"}[alert['severity']]
            alert_element = dbc.Alert(
                f"{alert['title']}: {alert['message']}",
                color=alert_type
            )
            alert_elements.append(alert_element)
        
        return html.Div(alert_elements)
    
    def calculate_current_risk(self, wind_speed: float, humidity: float, fmc: float) -> float:
        """Calculate current fire risk based on environmental conditions."""
        # Simplified risk calculation - in real implementation would use trained models
        risk = 50  # baseline
        
        # Wind effect (higher wind = higher risk)
        risk += (wind_speed / 50) * 30
        
        # Humidity effect (lower humidity = higher risk)
        risk -= (humidity / 100) * 20
        
        # Fuel moisture effect (lower FMC = higher risk)
        risk -= (fmc / 50) * 15
        
        # Clamp to 0-100 range
        risk = max(0, min(100, risk))
        
        return risk
    
    def get_risk_level(self, risk_value: float) -> str:
        """Convert numeric risk to categorical level."""
        if risk_value > 70:
            return "red"
        elif risk_value > 40:
            return "yellow"
        else:
            return "green"
    
    def simulate_water_allocation(self, wind_speed: float, humidity: float, fmc: float) -> List[float]:
        """Simulate water allocation based on current conditions."""
        # Calculate risk-based allocations
        risk = self.calculate_current_risk(wind_speed, humidity, fmc)
        
        # Base allocation of 500m3, adjust based on risk
        base_allocation = 500.0
        risk_factor = risk / 100.0
        
        allocations = [
            base_allocation * 0.3 * risk_factor,    # School
            base_allocation * 0.4 * risk_factor,    # Hospital (highest priority)
            base_allocation * 0.2 * risk_factor,    # Residential
            base_allocation * 0.1 * risk_factor     # Evacuation route
        ]
        
        return allocations
    
    def calculate_wuer(self, wind_speed: float, humidity: float, fmc: float) -> float:
        """Calculate Water-Use Efficiency Ratio."""
        # Simulate WUER calculation
        risk_reduction = 0.8 - (fmc / 50)  # Higher FMC = lower risk
        water_applied = 400.0  # m³
        
        wuer = risk_reduction / water_applied
        return wuer
    
    def create_interactive_map(self, wind_speed: float, fmc: float) -> go.Figure:
        """Create interactive map visualization."""
        # Create sample map data
        lats = [35.0, 35.1, 35.2, 35.15]
        lons = [105.0, 105.1, 105.05, 105.15]
        risks = [self.calculate_current_risk(wind_speed, 30, fmc) for _ in range(4)]  # Simulate risks
        
        fig = go.Figure(data=go.Scattergeo(
            lon=lons,
            lat=lats,
            mode='markers',
            marker=dict(
                size=15,
                color=risks,
                colorscale='Viridis',
                colorbar=dict(title="Risk Level"),
                cmin=0,
                cmax=100,
                showscale=True
            ),
            text=['School', 'Hospital', 'Residential', 'Evac Route'],
            hovertemplate="<b>%{text}</b><br>" +
                         "Risk: %{marker.color:.1f}%<br>" +
                         "<extra></extra>"
        ))
        
        fig.update_layout(
            title='Geographic Risk Distribution',
            geo=dict(
                projection_type='mercator',
                showland=True,
                landcolor="rgb(212, 212, 212)",
                subunitcolor="rgb(255, 255, 255)",
                countrycolor="rgb(255, 255, 255)"
            )
        )
        
        return fig
    
    def generate_ai_recommendation(self, wind_speed: float, humidity: float, fmc: float) -> Tuple[str, str]:
        """Generate AI-based recommendations with explanations."""
        risk = self.calculate_current_risk(wind_speed, humidity, fmc)
        
        if risk > 80:
            recommendation = "EVACUATE IMMEDIATELY"
            explanation = f"Extremely high risk ({risk:.1f}%) due to high wind ({wind_speed} km/h) and low moisture conditions. Immediate evacuation recommended for all zones."
        elif risk > 60:
            recommendation = "REDUCE BY 40%"
            explanation = f"High risk ({risk:.1f}%) - Activate protection zones with 40% risk reduction measures. Focus on critical infrastructure."
        elif risk > 40:
            recommendation = "MONITOR & PREPARE"
            explanation = f"Moderate risk ({risk:.1f}%) - Continue monitoring and prepare intervention teams. Maintain current protection levels."
        else:
            recommendation = "CONTINUE MONITORING"
            explanation = f"Low risk ({risk:.1f}%) - Standard monitoring procedures adequate. No immediate intervention needed."
        
        return recommendation, explanation
    
    def run(self):
        """Start the dashboard server."""
        print(f"Starting Talaix Dashboard on http://{self.host}:{self.port}")
        print("Press Ctrl+C to stop the server")
        self.app.run(host=self.host, port=self.port, debug=self.debug)


# Additional dashboard components
class DashboardComponents:
    """Additional dashboard components for specialized functionality."""
    
    @staticmethod
    def create_decision_tree_visualization(model):
        """Create visualization for decision tree logic."""
        pass
    
    @staticmethod
    def create_uncertainty_visualization(predictions, uncertainties):
        """Visualize prediction uncertainties."""
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=list(range(len(predictions))),
            y=predictions,
            error_y=dict(
                type='data',
                array=uncertainties,
                visible=True
            ),
            mode='markers',
            name='Predictions with Uncertainty'
        ))
        
        fig.update_layout(
            title='Prediction Uncertainty Visualization',
            xaxis_title='Sample Index',
            yaxis_title='Risk Level'
        )
        
        return fig