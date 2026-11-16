from .etihad import EtihadProvider
from .google_flights import GoogleFlightsProvider
from .samokatus import SamokatusProvider
from .travelpayouts import TravelpayoutsProvider

ALL_PROVIDERS = [TravelpayoutsProvider, GoogleFlightsProvider, EtihadProvider, SamokatusProvider]

__all__ = [
    "ALL_PROVIDERS",
    "EtihadProvider",
    "GoogleFlightsProvider",
    "SamokatusProvider",
    "TravelpayoutsProvider",
]
