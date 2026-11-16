from .etihad import EtihadProvider
from .google_flights import GoogleFlightsProvider
from .samokatus import SamokatusProvider
from .self_transfer import SelfTransferProvider
from .travelpayouts import TravelpayoutsProvider

ALL_PROVIDERS = [TravelpayoutsProvider, SelfTransferProvider, GoogleFlightsProvider, EtihadProvider, SamokatusProvider]

__all__ = [
    "ALL_PROVIDERS",
    "EtihadProvider",
    "GoogleFlightsProvider",
    "SamokatusProvider",
    "SelfTransferProvider",
    "TravelpayoutsProvider",
]
