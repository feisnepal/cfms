"""
Detect if measurements are diameter or girth (circumference)
Auto-detects and converts girth to diameter
"""
import numpy as np
import pandas as pd
from typing import Dict


class DiameterDetector:
    """Detects whether measurements are diameter or girth"""

    # Thresholds for detection
    GIRTH_MEAN_THRESHOLD = 100  # cm
    GIRTH_MEDIAN_THRESHOLD = 80  # cm
    PI = 3.14159265359

    def detect_measurement_type(
        self,
        values: np.ndarray,
        column_name: str = None
    ) -> Dict:
        """
        Detect if measurements are diameter or girth

        Args:
            values: Array of measurements
            column_name: Name of the column (optional)

        Returns:
            Dict with 'type', 'confidence', 'method'
        """
        # Method 1: Check column name
        if column_name:
            col_lower = column_name.lower()
            girth_keywords = ['girth', 'gbh', 'circumference', 'cbh']
            diameter_keywords = ['diameter', 'dbh', 'dia']

            if any(kw in col_lower for kw in girth_keywords):
                return {
                    'type': 'girth',
                    'confidence': 'high',
                    'method': 'column_name',
                    'column_name': column_name
                }

            if any(kw in col_lower for kw in diameter_keywords):
                return {
                    'type': 'diameter',
                    'confidence': 'high',
                    'method': 'column_name',
                    'column_name': column_name
                }

        # Method 2: Statistical analysis
        mean_val = np.mean(values)
        median_val = np.median(values)
        q75_val = np.percentile(values, 75)

        # Strong indicators for GIRTH
        if mean_val > self.GIRTH_MEAN_THRESHOLD:
            return {
                'type': 'girth',
                'confidence': 'high',
                'method': 'statistical',
                'statistics': {
                    'mean': round(float(mean_val), 2),
                    'median': round(float(median_val), 2),
                    'threshold': self.GIRTH_MEAN_THRESHOLD
                }
            }

        # Strong indicators for DIAMETER
        if mean_val < 50:
            return {
                'type': 'diameter',
                'confidence': 'high',
                'method': 'statistical',
                'statistics': {
                    'mean': round(float(mean_val), 2),
                    'median': round(float(median_val), 2)
                }
            }

        # Uncertain range (50-100 cm mean)
        if 50 <= mean_val <= self.GIRTH_MEAN_THRESHOLD:
            # Check 75th percentile
            if q75_val > self.GIRTH_MEDIAN_THRESHOLD:
                return {
                    'type': 'girth',
                    'confidence': 'medium',
                    'method': 'statistical',
                    'statistics': {
                        'mean': round(float(mean_val), 2),
                        'median': round(float(median_val), 2),
                        'q75': round(float(q75_val), 2)
                    },
                    'requires_confirmation': True
                }
            else:
                return {
                    'type': 'diameter',
                    'confidence': 'medium',
                    'method': 'statistical',
                    'statistics': {
                        'mean': round(float(mean_val), 2),
                        'median': round(float(median_val), 2),
                        'q75': round(float(q75_val), 2)
                    },
                    'requires_confirmation': True
                }

        # Default to diameter
        return {
            'type': 'diameter',
            'confidence': 'low',
            'method': 'default',
            'message': 'Ambiguous measurements - assuming diameter'
        }

    def convert_girth_to_diameter(self, girth_values: np.ndarray) -> np.ndarray:
        """
        Convert girth (circumference) to diameter

        Args:
            girth_values: Array of girth measurements

        Returns:
            Array of diameter measurements
        """
        return girth_values / self.PI

    def get_conversion_samples(
        self,
        girth_values: np.ndarray,
        num_samples: int = 5
    ) -> list:
        """
        Get sample conversions for user confirmation

        Args:
            girth_values: Array of girth measurements
            num_samples: Number of samples to return

        Returns:
            List of sample conversion dicts
        """
        diameter_values = self.convert_girth_to_diameter(girth_values)
        num_samples = min(num_samples, len(girth_values))

        samples = []
        for i in range(num_samples):
            samples.append({
                'original_girth': round(float(girth_values[i]), 2),
                'converted_diameter': round(float(diameter_values[i]), 2)
            })

        return samples
