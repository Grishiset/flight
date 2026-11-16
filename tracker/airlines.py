"""Названия авиакомпаний по коду IATA (Aviasales отдаёт только коды)."""

AIRLINES = {
    "SU": "Аэрофлот", "U6": "Уральские авиалинии", "S7": "S7", "DP": "Победа", "N4": "Nordwind",
    "ZF": "Azur Air", "UT": "ЮТэйр", "FV": "Россия", "WZ": "Red Wings", "5N": "Smartavia",
    "HY": "Uzbekistan Airways", "KC": "Air Astana", "DV": "SCAT", "J2": "AZAL", "7J": "Tajik Air",
    "KR": "Cambodia Airways", "QH": "Air Kyrgyzstan",
    "TK": "Turkish Airlines", "PC": "Pegasus", "VF": "AJet", "XQ": "SunExpress",
    "EK": "Emirates", "FZ": "flydubai", "EY": "Etihad", "QR": "Qatar Airways", "G9": "Air Arabia",
    "WY": "Oman Air", "GF": "Gulf Air", "SV": "Saudia", "RJ": "Royal Jordanian", "MS": "EgyptAir",
    "AT": "Royal Air Maroc", "JU": "Air Serbia", "LO": "LOT", "A3": "Aegean",
    "CA": "Air China", "MU": "China Eastern", "CZ": "China Southern", "HU": "Hainan Airlines",
    "3U": "Sichuan Airlines", "JD": "Beijing Capital", "FM": "Shanghai Airlines", "MF": "Xiamen Airlines",
    "ZH": "Shenzhen Airlines", "HO": "Juneyao", "9C": "Spring Airlines", "SC": "Shandong Airlines",
    "GS": "Tianjin Airlines", "CX": "Cathay Pacific",
    "KE": "Korean Air", "OZ": "Asiana", "7C": "Jeju Air", "TW": "T'way", "LJ": "Jin Air",
    "JL": "Japan Airlines", "NH": "ANA", "MM": "Peach", "GK": "Jetstar Japan", "ZG": "ZIPAIR",
    "VN": "Vietnam Airlines", "VJ": "VietJet", "SQ": "Singapore Airlines", "TG": "Thai Airways",
    "MH": "Malaysia Airlines", "D7": "AirAsia X", "AI": "Air India",
    "NZ": "Air New Zealand", "QF": "Qantas", "JQ": "Jetstar", "VA": "Virgin Australia",
    "UA": "United", "AA": "American Airlines", "DL": "Delta", "B6": "JetBlue", "AS": "Alaska Airlines",
    "WN": "Southwest", "F9": "Frontier", "NK": "Spirit", "AC": "Air Canada", "BA": "British Airways",
    "AF": "Air France", "KL": "KLM", "LH": "Lufthansa", "LX": "SWISS", "IB": "Iberia",
    "TP": "TAP Air Portugal", "FI": "Icelandair", "UX": "Air Europa", "BT": "airBaltic",
}


def airline_name(code: str | None) -> str | None:
    if not code:
        return None
    return AIRLINES.get(code.upper(), code)


# Официальные сайты авиакомпаний (страницы бронирования). Ключ — название, как в AIRLINES.
AIRLINE_SITES = {
    "Аэрофлот": "https://www.aeroflot.ru/",
    "Uzbekistan Airways": "https://www.uzairways.com/ru",
    "Air Astana": "https://airastana.com/",
    "SCAT": "https://www.scat.kz/",
    "Turkish Airlines": "https://www.turkishairlines.com/ru-ru/",
    "Pegasus": "https://www.flypgs.com/ru",
    "AJet": "https://ajet.com/",
    "Emirates": "https://www.emirates.com/ru/russian/",
    "flydubai": "https://www.flydubai.com/ru/",
    "Etihad": "https://www.etihad.com/ru-ru/",
    "Qatar Airways": "https://www.qatarairways.com/ru-ru/homepage.html",
    "Air Arabia": "https://www.airarabia.com/",
    "Oman Air": "https://www.omanair.com/",
    "Gulf Air": "https://www.gulfair.com/",
    "Saudia": "https://www.saudia.com/",
    "Royal Jordanian": "https://www.rj.com/",
    "EgyptAir": "https://www.egyptair.com/",
    "Royal Air Maroc": "https://www.royalairmaroc.com/",
    "Air Serbia": "https://www.airserbia.com/",
    "Air China": "https://www.airchina.com.cn/",
    "China Eastern": "https://www.ceair.com/",
    "China Southern": "https://www.csair.com/ru/ru/",
    "Hainan Airlines": "https://www.hainanairlines.com/",
    "Sichuan Airlines": "https://www.sichuanair.com/",
    "Cathay Pacific": "https://www.cathaypacific.com/",
    "Korean Air": "https://www.koreanair.com/",
    "Asiana": "https://flyasiana.com/",
    "Japan Airlines": "https://www.jal.co.jp/",
    "ANA": "https://www.ana.co.jp/",
    "Vietnam Airlines": "https://www.vietnamairlines.com/",
    "Singapore Airlines": "https://www.singaporeair.com/",
    "Thai Airways": "https://www.thaiairways.com/",
    "Air New Zealand": "https://www.airnewzealand.com/",
    "Qantas": "https://www.qantas.com/",
    "United": "https://www.united.com/",
    "American Airlines": "https://www.aa.com/",
    "Delta": "https://www.delta.com/",
}


def airline_links(airline_field: str | None) -> list[tuple[str, str]]:
    """Ссылки на сайты авиакомпаний из поля airline («China Southern» или «HY / TK», «A, B»)."""
    if not airline_field:
        return []
    out = []
    for part in airline_field.replace(" / ", ",").split(","):
        name = part.strip()
        url = AIRLINE_SITES.get(name)
        if url and (name, url) not in out:
            out.append((name, url))
    return out


def google_flights_url(origin: str, destination: str, depart, ret, passengers: int = 1) -> str:
    """Google Flights с заполненным маршрутом и датами: у тарифов там есть кнопки покупки на сайте авиакомпании."""
    from urllib.parse import quote

    q = f"Flights to {destination} from {origin} on {depart.isoformat()} through {ret.isoformat()}"
    if passengers > 1:
        q += f" for {passengers} adults"
    return "https://www.google.com/travel/flights?hl=ru&curr=RUB&q=" + quote(q)
