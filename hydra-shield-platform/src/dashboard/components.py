"""
Dashboard Components for Talaix Wildfire Protection System.

Interactive components for the dashboard including maps, monitors, simulators,
and explainable AI elements.
"""

from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import json
import warnings

from ..prediction.risk_model import AdvancedWildfireRiskModel
from ..prediction.fire_spread import FireSpreadModel
from ..gis_mapping.data_fusion import DataFusionPipeline
from ..hydration_control.water_optimiser import WaterOptimiser
from ..hydration_control.intervention import InterventionPlanner


class InteractiveMap:
    """Interactive map component for geographic visualization."""
    
    def __init__(self):
        self.map_data = {}
        self.protection_zones = []
        self.assets = []
    
    def create_map(self, data: Dict) -> go.Figure:
        """Create an interactive map visualization."""
        # Create a sample map with risk visualization
        if 'coordinates' in data and 'risk_levels' in data:
            lats = data['coordinates']['lat']
            lons = data['coordinates']['lon']
            risks = data['risk_levels']
            
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
                text=data.get('labels', []),
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
        else:
            # Default empty map
            fig = go.Figure()
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


class RealTimeMonitor:
    """Real-time monitoring component for live data."""
    
    def __init__(self):
        self.current_data = {}
        self.history = []
        self.last_update = datetime.now()
    
    def get_current_status(self) -> Dict:
        """Get current monitoring status."""
        return {
            'timestamp': datetime.now().isoformat(),
            'risk_level': self.current_data.get('risk', 0),
            'wind_speed': self.current_data.get('wind', 0),
            'humidity': self.current_data.get('humidity', 0),
            'fuel_moisture': self.current_data.get('fmc', 0),
            'water_usage': self.current_data.get('water_used', 0),
            'zones_protected': self.current_data.get('zones_protected', 0)
        }
    
    def update_data(self, new_data: Dict):
        """Update monitoring data."""
        self.current_data.update(new_data)
        self.history.append({
            'timestamp': datetime.now(),
            'data': new_data.copy()
        })
        
        # Keep only last 100 records
        if len(self.history) > 100:
            self.history = self.history[-100:]
    
    def get_trend(self, metric: str) -> List[float]:
        """Get trend for a specific metric."""
        if not self.history:
            return []
        
        values = [record['data'].get(metric, 0) for record in self.history]
        return values


class ScenarioSimulator:
    """Interactive scenario modeling component."""
    
    def __init__(self):
        self.scenarios = {}
        self.results = {}
    
    def simulate_scenario(self, scenario_type: str) -> Dict:
        """Run a scenario simulation."""
        # Define base parameters
        base_wind = 20.0
        base_humidity = 30.0
        base_fmc = 12.5
        
        # Adjust parameters based on scenario
        if scenario_type == 'high_wind':
            wind_adjust = 15.0
            humidity_adjust = 0.0
            fmc_adjust = 2.0
        elif scenario_type == 'low_humidity':
            wind_adjust = 0.0
            humidity_adjust = -15.0
            fmc_adjust = 3.0
        elif scenario_type == 'combined':
            wind_adjust = 10.0
            humidity_adjust = -10.0
            fmc_adjust = 5.0
        elif scenario_type == 'mitigation':
            wind_adjust = 0.0
            humidity_adjust = 0.0
            fmc_adjust = -5.0  # Better moisture due to mitigation
        else:  # baseline
            wind_adjust = 0.0
            humidity_adjust = 0.0
            fmc_adjust = 0.0
        
        # Calculate scenario results
        risk_reduction = self._calculate_risk_reduction(base_wind + wind_adjust, base_humidity + humidity_adjust, base_fmc + fmc_adjust)
        water_used = self._calculate_water_usage(scenario_type)
        
        return {
            scenario_type: {
                'risk_reduction': risk_reduction,
                'water_used': water_used,
                'scenario_type': scenario_type
            }
        }
    
    def _calculate_risk_reduction(self, wind_speed: float, humidity: float, fmc: float) -> float:
        """Calculate risk reduction for a scenario."""
        # Simplified calculation - in real implementation would use actual models
        risk = 50 + (wind_speed / 50) * 30 - (humidity / 100) * 20 - (fmc / 50) * 15
        risk = max(0, min(100, risk))
        
        # Risk reduction compared to baseline (50)
        baseline_risk = 50
        risk_reduction = (baseline_risk - risk) / baseline_risk * 100
        
        return max(0, min(100, risk_reduction))
    
    def _calculate_water_usage(self, scenario_type: str) -> float:
        """Calculate water usage for a scenario."""
        if scenario_type == 'mitigation':
            return 450.0  # Higher usage for mitigation
        elif scenario_type == 'combined':
            return 350.0
        else:
            return 250.0


class ExplainableAIComponent:
    """Explainable AI component for decision transparency."""
    
    def __init__(self):
        self.model_explanations = {}
        self.feature_importance = {}
    
    def explain_prediction(self, model_input: Dict, prediction: float) -> Dict:
        """Generate explanation for a prediction."""
        # Fixed placeholder confidence: no calibrated confidence model exists
        # yet, so a constant declared value is used instead of a random one.
        explanation = {
            'prediction': prediction,
            'confidence': 0.8,
            'confidence_note': 'Fixed placeholder; not calibrated',
            'feature_contributions': {
                'wind_speed': model_input.get('wind_speed', 0) * 0.4,
                'humidity': -model_input.get('humidity', 0) * 0.2,
                'fuel_moisture': -model_input.get('fuel_moisture', 0) * 0.3,
                'temperature': model_input.get('temperature', 25) * 0.1
            },
            'reasoning': self._generate_reasoning(model_input, prediction)
        }
        
        return explanation
    
    def _generate_reasoning(self, model_input: Dict, prediction: float) -> str:
        """Generate natural language reasoning."""
        wind = model_input.get('wind_speed', 0)
        humidity = model_input.get('humidity', 0)
        fmc = model_input.get('fuel_moisture', 0)
        
        if wind > 30:
            return f"High wind speeds ({wind} km/h) significantly increase fire spread risk. Wind is the primary driver of fire behavior in this scenario."
        elif humidity < 20:
            return f"Low humidity ({humidity}%) creates extremely dry conditions that accelerate fire spread. Moisture content is critically low."
        elif fmc < 8:
            return f"Very low fuel moisture content ({fmc}%) makes vegetation highly ignitable. Pre-hydration intervention recommended."
        else:
            return f"Moderate conditions detected. Current risk level: {prediction:.1f}% with {self._get_confidence_level(prediction)} confidence."


class DecisionSupportSystem:
    """Decision support system with rule-based recommendations."""
    
    def __init__(self):
        self.rules = self._initialize_rules()
        self.confidence_thresholds = {
            'high': 0.8,
            'medium': 0.6,
            'low': 0.4
        }
    
    def _initialize_rules(self) -> List[Dict]:
        """Initialize decision rules."""
        return [
            {
                'condition': lambda data: data.get('risk_level', 0) > 80,
                'action': 'IMMEDIATE EVACUATION',
                'priority': 'CRITICAL',
                'confidence': 0.95
            },
            {
                'condition': lambda data: data.get('wind_speed', 0) > 35,
                'action': 'ENHANCED MONITORING',
                'priority': 'HIGH',
                'confidence': 0.90
            },
            {
                'condition': lambda data: data.get('humidity', 100) < 15,
                'action': 'INCREASE WATER ALLOCATION',
                'priority': 'HIGH',
                'confidence': 0.85
            },
            {
                'condition': lambda data: data.get('fuel_moisture', 0) < 8,
                'action': 'PRE-HYDRATE FUEL CORRIDORS',
                'priority': 'MEDIUM',
                'confidence': 0.80
            },
            {
                'condition': lambda data: data.get('risk_level', 0) > 60,
                'action': 'ACTIVATE PROTECTION ZONES',
                'priority': 'MEDIUM',
                'confidence': 0.75
            }
        ]
    
    def generate_recommendation(self, input_data: Dict) -> List[Dict]:
        """Generate recommendations based on input data."""
        recommendations = []
        
        for rule in self.rules:
            if rule['condition'](input_data):
                rec = {
                    'action': rule['action'],
                    'priority': rule['priority'],
                    'confidence': rule['confidence'],
                    'triggered_by': self._identify_trigger(input_data, rule['condition'])
                }
                recommendations.append(rec)
        
        # Sort by priority
        priority_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        recommendations.sort(key=lambda x: priority_order.get(x['priority'], 99))
        
        return recommendations
    
    def _identify_trigger(self, input_data: Dict, condition_func) -> str:
        """Identify which condition was triggered."""
        # Simplified trigger identification
        if condition_func(input_data):
            # Return a descriptive trigger
            if input_data.get('risk_level', 0) > 80:
                return "High overall risk level"
            elif input_data.get('wind_speed', 0) > 35:
                return f"High wind speed: {input_data.get('wind_speed')} km/h"
            elif input_data.get('humidity', 100) < 15:
                return f"Low humidity: {input_data.get('humidity')}%"
            elif input_data.get('fuel_moisture', 0) < 8:
                return f"Low fuel moisture: {input_data.get('fuel_moisture')}%"
            else:
                return "General risk threshold exceeded"
        return "No specific trigger"


class AlertManager:
    """Alert and notification management component."""
    
    def __init__(self):
        self.alerts = []
        self.alert_rules = self._initialize_alert_rules()
    
    def _initialize_alert_rules(self) -> List[Dict]:
        """Initialize alert rules."""
        return [
            {
                'condition': lambda data: data.get('risk_level', 0) > 80,
                'level': 'CRITICAL',
                'message': 'EXTREME FIRE RISK DETECTED - IMMEDIATE ACTION REQUIRED',
                'category': 'risk'
            },
            {
                'condition': lambda data: data.get('wind_speed', 0) > 40,
                'level': 'HIGH',
                'message': 'EXCEPTIONALLY HIGH WINDS - INCREASED SPREAD POTENTIAL',
                'category': 'weather'
            },
            {
                'condition': lambda data: data.get('humidity', 100) < 10,
                'level': 'HIGH',
                'message': 'EXTREMELY LOW HUMIDITY - DRY CONDITIONS',
                'category': 'weather'
            },
            {
                'condition': lambda data: data.get('fuel_moisture', 0) < 5,
                'level': 'MEDIUM',
                'message': 'CRITICALLY LOW FUEL MOISTURE - HIGH IGNITION RISK',
                'category': 'fuel'
            },
            {
                'condition': lambda data: data.get('water_available', 0) < 100,
                'level': 'MEDIUM',
                'message': 'LOW WATER RESERVES - ADJUST ALLOCATION STRATEGY',
                'category': 'resources'
            }
        ]
    
    def check_conditions(self, wind_speed: float, humidity: float, fmc: float) -> List[Dict]:
        """Check current conditions against alert rules."""
        current_data = {
            'wind_speed': wind_speed,
            'humidity': humidity,
            'fuel_moisture': fmc,
            'risk_level': self._calculate_risk_level(wind_speed, humidity, fmc)
        }
        
        active_alerts = []
        for rule in self.alert_rules:
            if rule['condition'](current_data):
                alert = {
                    'title': rule['level'],
                    'message': rule['message'],
                    'severity': rule['level'].lower(),
                    'category': rule['category'],
                    'timestamp': datetime.now().isoformat()
                }
                active_alerts.append(alert)
        
        # If no alerts, add a status update
        if not active_alerts:
            active_alerts.append({
                'title': 'ALL CLEAR',
                'message': 'No critical conditions detected at this time',
                'severity': 'low',
                'category': 'status',
                'timestamp': datetime.now().isoformat()
            })
        
        return active_alerts
    
    def _calculate_risk_level(self, wind_speed: float, humidity: float, fmc: float) -> float:
        """Calculate risk level for alert purposes."""
        risk = 50  # baseline
        risk += (wind_speed / 50) * 30
        risk -= (humidity / 100) * 20
        risk -= (fmc / 50) * 15
        return max(0, min(100, risk))


class VisualizationEngine:
    """Advanced visualization engine for dashboard graphics."""
    
    def __init__(self):
        self.charts = {}
    
    def create_risk_heatmap(self, data: np.ndarray, coordinates: Tuple) -> go.Figure:
        """Create a risk heatmap visualization."""
        fig = go.Figure(data=go.Heatmap(
            z=data,
            x=coordinates[0] if len(coordinates) > 0 else [],
            y=coordinates[1] if len(coordinates) > 1 else [],
            colorscale='RdYlGn_r',
            zmid=50
        ))
        
        fig.update_layout(
            title='Risk Heatmap',
            xaxis_title='Longitude',
            yaxis_title='Latitude'
        )
        
        return fig
    
    def create_time_series(self, data: List, labels: List[str], title: str = "Time Series") -> go.Figure:
        """Create a time series visualization."""
        fig = go.Figure()
        
        for i, series in enumerate(data):
            fig.add_trace(go.Scatter(
                x=list(range(len(series))),
                y=series,
                mode='lines+markers',
                name=labels[i] if i < len(labels) else f'Series {i}'
            ))
        
        fig.update_layout(
            title=title,
            xaxis_title='Time',
            yaxis_title='Value'
        )
        
        return fig
    
    def create_comparison_chart(self, scenarios: Dict[str, Dict]) -> go.Figure:
        """Create a comparison chart for multiple scenarios."""
        categories = list(scenarios.keys())
        risk_values = [scenarios[cat]['risk_reduction'] for cat in categories]
        water_values = [scenarios[cat]['water_used'] for cat in categories]
        
        fig = go.Figure(data=[
            go.Bar(name='Risk Reduction (%)', x=categories, y=risk_values),
            go.Bar(name='Water Used (m³)', x=categories, y=water_values)
        ])
        
        fig.update_layout(
            title='Scenario Comparison',
            barmode='group'
        )
        
        return fig