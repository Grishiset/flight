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
