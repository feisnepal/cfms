"""The "I am here" check of an NTFP sample plot (pure maths).

A phone's position is a circle, not a point: it comes with an accuracy radius. The plot is at most 500 m2 (about 22 m across), so a person at the plot is within
``NEAR_M`` of its marker plus the phone's own error. Three answers, never a refusal (a GPS under a closed canopy can be 50 m out and the survey must go on):

* ``at``        -- the distance is within NEAR_M plus the accuracy, and the accuracy is good enough to mean something (<= MAX_USABLE_ACCURACY_M);
* ``far``       -- even allowing for the accuracy, the person is more than NEAR_M away;
* ``uncertain`` -- the accuracy is too poor (over MAX_USABLE_ACCURACY_M) to say, and not even clearly far.
"""
from __future__ import annotations

import math
from typing import Optional

NEAR_M = 40.0
MAX_USABLE_ACCURACY_M = 100.0
EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def verdict(distance_m: float, accuracy_m: Optional[float]) -> str:
    acc = max(0.0, accuracy_m or 0.0)
    if acc <= MAX_USABLE_ACCURACY_M and distance_m <= NEAR_M + acc:
        return "at"
    if distance_m - acc > NEAR_M:
        return "far"
    return "uncertain"
