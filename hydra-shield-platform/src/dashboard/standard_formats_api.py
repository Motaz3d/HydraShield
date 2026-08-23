"""
Standard Formats API for Talaix Dashboard.

Provides standardized API endpoints for integration with civil protection
systems, early warning systems, and standard data formats (GeoJSON, GML, CSV).

NOTE: This module is a scaffold for a future civil-protection integration.
It is NOT part of the deployed stack (not wired into docker-compose) and its
CSV sample endpoint returns illustrative example rows, not real data. It must
be connected to real analysis outputs before any deployment.
"""

from flask import Flask, request, jsonify, Response
from typing import Dict, List, Any
import numpy as np
import pandas as pd
from datetime import datetime
import json
from shapely.geometry import Point, Polygon, mapping
import geopandas as gpd
import xml.etree.ElementTree as ET
from xml.dom import minidom
import csv
import io
from geojson import Feature, FeatureCollection, Point as GeoPoint, Polygon as GeoPolygon
import geojson


class StandardFormatsAPI:
    """API for standardized integration with civil protection systems."""
    
    def __init__(self):
        self.app = Flask(__name__)
        self.setup_standard_routes()
    
    def setup_standard_routes(self):
        """Setup standardized API routes."""
        
        @self.app.route('/api/v1/geojson/fire-risk', methods=['POST'])
        def get_fire_risk_geojson():
            """Get fire risk data in GeoJSON format."""
            data = request.json
            lat = data.get('latitude', 0.0)
            lon = data.get('longitude', 0.0)
            risk_level = data.get('risk_level', 0.5)
            
            # Create a GeoJSON feature for risk area
            point_geom = GeoPoint([lon, lat])
            
            feature = Feature(
                geometry=point_geom,
                properties={
                    'risk_level': risk_level,
                    'timestamp': datetime.now().isoformat(),
                    'threat_category': self._get_threat_category(risk_level)
                }
            )
            
            feature_collection = FeatureCollection([feature])
            
            return Response(
                geojson.dumps(feature_collection),
                mimetype='application/json',
                headers={'Content-Type': 'application/geo+json'}
            )
        
        @self.app.route('/api/v1/gml/protection-zones', methods=['POST'])
        def get_protection_zones_gml():
            """Get protection zones in GML format."""
            data = request.json
            zones = data.get('zones', [])
            
            # Create GML document
            root = ET.Element('gml:FeatureCollection', 
                             attrib={'xmlns:gml': 'http://www.opengis.net/gml'})
            
            for i, zone in enumerate(zones):
                member = ET.SubElement(root, 'gml:member')
                feature = ET.SubElement(member, f'zone_{i}', 
                                       attrib={'gml:id': f'zone_{i}'})
                
                # Add geometry
                geom_container = ET.SubElement(feature, 'gml:geometry')
                polygon = ET.SubElement(geom_container, 'gml:Polygon')
                exterior = ET.SubElement(polygon, 'gml:exterior')
                linear_ring = ET.SubElement(exterior, 'gml:LinearRing')
                
                # Add coordinates (simplified)
                pos_list = ET.SubElement(linear_ring, 'gml:posList')
                # Generate rectangular coordinates for demo
                coords = f"{zone['lon']-0.1} {zone['lat']-0.1} {zone['lon']+0.1} {zone['lat']-0.1} {zone['lon']+0.1} {zone['lat']+0.1} {zone['lon']-0.1} {zone['lat']+0.1} {zone['lon']-0.1} {zone['lat']-0.1}"
                pos_list.text = coords
                
                # Add properties
                risk_elem = ET.SubElement(feature, 'risk_level')
                risk_elem.text = str(zone.get('risk', 0.5))
                
                threat_elem = ET.SubElement(feature, 'threat_category')
                threat_elem.text = self._get_threat_category(zone.get('risk', 0.5))
            
            # Convert to string
            rough_string = ET.tostring(root, encoding='unicode')
            reparsed = minidom.parseString(rough_string)
            gml_string = reparsed.toprettyxml(indent="  ")
            
            return Response(
                gml_string,
                mimetype='application/xml',
                headers={'Content-Type': 'application/gml+xml'}
            )
        
        @self.app.route('/api/v1/csv/historical-data', methods=['GET'])
        def get_historical_data_csv():
            """Get historical fire data in CSV format."""
            # Create sample historical data
            sample_data = {
                'date': ['2023-01-01', '2023-02-01', '2023-03-01'],
                'risk_level': [0.3, 0.7, 0.2],
                'fuel_moisture': [15.0, 8.0, 20.0],
                'wind_speed': [10.0, 25.0, 5.0],
                'temperature': [25.0, 35.0, 20.0],
                'location_lat': [40.0, 40.5, 41.0],
                'location_lon': [-3.0, -3.5, -4.0],
                'area_burned': [10.0, 250.0, 0.0]
            }
            
            df = pd.DataFrame(sample_data)
            
            # Convert to CSV
            output = io.StringIO()
            df.to_csv(output, index=False)
            csv_data = output.getvalue()
            output.close()
            
            return Response(
                csv_data,
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment; filename=historical-fire-data.csv'}
            )
        
        @self.app.route('/api/v1/alerts', methods=['POST'])
        def send_alerts():
            """Send alerts to civil protection systems."""
            data = request.json
            alert_type = data.get('alert_type', 'INFO')
            message = data.get('message', 'No message provided')
            coordinates = data.get('coordinates', [])
            timestamp = datetime.now().isoformat()
            
            # Format alert according to emergency management standards
            alert = {
                'identifier': f"HS-{timestamp.replace(':', '-').replace('.', '-')}",
                'sender': 'Talaix.earth',
                'sent': timestamp,
                'status': 'Actual',
                'msgType': 'Alert',
                'scope': 'Public',
                'info': [
                    {
                        'category': self._get_emergency_category(alert_type),
                        'event': self._get_emergency_event(alert_type),
                        'responseType': 'Monitor',
                        'urgency': 'Immediate' if alert_type == 'EMERGENCY' else 'Expected',
                        'severity': 'Extreme' if alert_type == 'EMERGENCY' else 'Moderate',
                        'certainty': 'Observed',
                        'eventCode': [{'valueName': 'SAME', 'value': 'FLW'}],  # Fire Warning
                        'effective': timestamp,
                        'expires': data.get('expires', ''),
                        'senderName': 'Talaix Earth Systems',
                        'headline': message,
                        'description': data.get('description', message),
                        'instruction': data.get('instruction', 'Monitor updates'),
                        'parameter': [
                            {'valueName': 'Propagation', 'value': data.get('propagation_speed', 'N/A')},
                            {'valueName': 'RiskLevel', 'value': data.get('risk_level', 'N/A')}
                        ]
                    }
                ],
                'area': [
                    {
                        'areaDesc': data.get('area_description', 'Affected region'),
                        'circle': [f"{coord['lat']} {coord['lon']}" for coord in coordinates],
                        'polygon': data.get('polygon', [])
                    }
                ]
            }
            
            return jsonify(alert)
    
    def _get_threat_category(self, risk_level: float) -> str:
        """Convert risk level to threat category."""
        if risk_level > 0.8:
            return "EXTREME"
        elif risk_level > 0.6:
            return "HIGH"
        elif risk_level > 0.4:
            return "MODERATE"
        else:
            return "LOW"
    
    def _get_emergency_category(self, alert_type: str) -> str:
        """Get emergency category based on alert type."""
        if alert_type == 'EMERGENCY':
            return 'Fire'
        else:
            return 'Other'
    
    def _get_emergency_event(self, alert_type: str) -> str:
        """Get emergency event based on alert type."""
        if alert_type == 'EMERGENCY':
            return 'Fire Warning'
        else:
            return 'Forecast'
    
    def run(self, host: str = "0.0.0.0", port: int = 8052, debug: bool = False):
        """Run the standard formats API server."""
        self.app.run(host=host, port=port, debug=debug)