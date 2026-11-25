from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    low_impressions_max: int = 50  # "zero ou tres faible" : au plus ce nombre
    ctr_min: float = 0.01  # fraction : 0.01 = 1 %
    ctr_min_impressions: int = 500
    no_sale_views_over: int = 50  # strictement plus
