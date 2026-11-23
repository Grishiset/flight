"""Групповые цены с публичной страницы Google Flights."""
from __future__ import annotations

from datetime import date

from fli.models import Airport, FlightSearchFilters, FlightSegment, PassengerInfo, SeatType, TripType
from fli.search import SearchFlights

from ..models import Offer
from .base import Context


class GoogleDirect:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.search = SearchFlights()

    def offers(self, route_id: str, dep: date, ret: date) -> list[Offer]:
        cfg = self.ctx.cfg
        origins = [[Airport[code], 0] for code in cfg.origin_airports]
        destinations = [[Airport[code], 0] for code in cfg.route(route_id).airports]
        party = PassengerInfo(adults=cfg.passengers)
        filters = FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=party,
            seat_type=SeatType.ECONOMY,
            flight_segments=[
                FlightSegment(departure_airport=origins, arrival_airport=destinations, travel_date=dep.isoformat()),
                FlightSegment(departure_airport=destinations, arrival_airport=origins, travel_date=ret.isoformat()),
            ],
        )
        locale = {"currency": "RUB", "language": "ru", "country": "RU"}
        combos = self.search.search(filters, top_n=3, **locale) or []
        offers = []
        for pair in combos:
            if not isinstance(pair, tuple) or len(pair) != 2:
                continue
            outbound, inbound = pair
            # После выбора обратного рейса Google показывает сумму за обе стороны и всю группу.
            if not outbound.legs or not inbound.legs or not inbound.price or not inbound.currency:
                continue
            total = self.ctx.rates.to_rub(inbound.price, inbound.currency)
            if not total:
                continue
            airlines = dict.fromkeys(f.primary_airline_name for f in pair if f.primary_airline_name)
            offers.append(Offer(
                route_id=route_id, source="google_flights", price_rub=round(total / cfg.passengers),
                depart=dep, ret=ret, airline=" / ".join(airlines) or None,
                stops=max(outbound.stops, inbound.stops),
                origin=outbound.legs[0].departure_airport.name,
                destination=outbound.legs[-1].arrival_airport.name,
                link=self.search.build_flight_booking_url(pair, passenger_info=party, **locale),
                price_orig=inbound.price, currency_orig=inbound.currency,
                quoted_passengers=cfg.passengers, total_price_rub=total,
            ))
        return offers
