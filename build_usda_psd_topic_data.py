#!/usr/bin/env python3

import json
from datetime import datetime, timezone
from pathlib import Path
from re import IGNORECASE, compile


INPUT_DIR = Path("/tmp/psd_topic_data")
OUTPUT_JS = Path("/Users/anders/Documents/Playground/usda-psd-topic-data.js")

METADATA = [
    {"code": "2222000", "group": "oil", "nameZh": "大豆", "nameEn": "Oilseed, Soybean"},
    {"code": "0440000", "group": "gra", "nameZh": "玉米", "nameEn": "Corn"},
    {"code": "0410000", "group": "gra", "nameZh": "小麦", "nameEn": "Wheat"},
    {"code": "4232000", "group": "oil", "nameZh": "豆油", "nameEn": "Oil, Soybean"},
    {"code": "0813100", "group": "oil", "nameZh": "豆粕", "nameEn": "Meal, Soybean"},
    {"code": "2631000", "group": "cot", "nameZh": "棉花", "nameEn": "Cotton"},
    {"code": "0612000", "group": "htp", "nameZh": "原糖", "nameEn": "Sugar, Centrifugal"},
]

SURPLUS_THRESHOLD = 0.02
DEFICIT_THRESHOLD = -0.02


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def parse_value(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def find_header(headers):
    for header in headers:
        if any(ch.isdigit() for ch in header):
            return header
    return None


def pick_by_patterns(attribute_map, patterns):
    for name, value in attribute_map.items():
        for pattern in patterns:
            if pattern.search(name):
                return value
    return None


def derive_supply(attribute_map):
    total_supply = pick_by_patterns(attribute_map, [compile(r"^total\s+supply$", IGNORECASE)])
    if total_supply is not None:
        return total_supply

    production = pick_by_patterns(attribute_map, [compile(r"production", IGNORECASE)])
    imports = pick_by_patterns(attribute_map, [compile(r"imports?", IGNORECASE)])
    beginning = pick_by_patterns(attribute_map, [compile(r"beginning\s+stocks?", IGNORECASE)])
    parts = [v for v in [production, imports, beginning] if v is not None]
    if not parts:
        return None
    return sum(parts)


def derive_use(attribute_map):
    total_use = pick_by_patterns(attribute_map, [compile(r"^total\s+use$", IGNORECASE)])
    if total_use is not None:
        return total_use

    domestic = pick_by_patterns(attribute_map, [compile(r"domestic\s+consumption", IGNORECASE)])
    if domestic is not None:
        return domestic

    domestic_use = pick_by_patterns(attribute_map, [compile(r"domestic\s+use", IGNORECASE)])
    if domestic_use is not None:
        return domestic_use

    disappearance = pick_by_patterns(attribute_map, [compile(r"total\s+disappearance", IGNORECASE)])
    return disappearance


def classify(supply, use):
    if supply is None or use is None or use <= 0:
        return {"code": "unknown", "label": "数据不足", "gap": None, "ratio": None}

    gap = supply - use
    ratio = gap / use
    if ratio > SURPLUS_THRESHOLD:
        code = "surplus"
        label = "供过于求"
    elif ratio < DEFICIT_THRESHOLD:
        code = "deficit"
        label = "供不应求"
    else:
        code = "balanced"
        label = "供需平衡"
    return {"code": code, "label": label, "gap": gap, "ratio": ratio}


def parse_commodity(meta):
    payload = json.loads((INPUT_DIR / f"query_{meta['code']}.json").read_text(encoding="utf-8"))
    value_header = find_header(payload["tableHeaders"])
    if not value_header:
        raise RuntimeError(f"No market year header for {meta['code']}")

    current_commodity = meta["nameEn"]
    current_attribute = ""
    country_attributes = {}

    for row in payload["queryResult"]:
        if row.get("commodity") is not None:
            current_commodity = clean_text(row["commodity"])
        if row.get("attribute") is not None:
            current_attribute = clean_text(row["attribute"])

        country = clean_text(row.get("country"))
        value = parse_value(row.get(value_header))
        if not country or not current_attribute or value is None:
            continue

        country_attributes.setdefault(country, {})[current_attribute] = value

    aggregated = {}
    for attrs in country_attributes.values():
        for attr_name, value in attrs.items():
            aggregated[attr_name] = aggregated.get(attr_name, 0.0) + value

    global_production = pick_by_patterns(aggregated, [compile(r"production", IGNORECASE)])
    global_imports = pick_by_patterns(aggregated, [compile(r"imports?", IGNORECASE)])
    global_exports = pick_by_patterns(aggregated, [compile(r"exports?", IGNORECASE)])
    global_ending_stocks = pick_by_patterns(aggregated, [compile(r"ending\s+stocks?", IGNORECASE)])
    global_use = derive_use(aggregated)
    global_supply = global_production if global_production is not None else derive_supply(aggregated)
    global_status = classify(global_supply, global_use)

    producers = []
    for country, attrs in country_attributes.items():
        production = pick_by_patterns(attrs, [compile(r"production", IGNORECASE)])
        if production is None or production <= 0:
            continue

        imports = pick_by_patterns(attrs, [compile(r"imports?", IGNORECASE)])
        exports = pick_by_patterns(attrs, [compile(r"exports?", IGNORECASE)])
        use = derive_use(attrs)

        if imports is not None and exports is not None:
            supply = production + imports - exports
        else:
            supply = production

        status = classify(supply, use)
        ending_stocks = pick_by_patterns(attrs, [compile(r"ending\s+stocks?", IGNORECASE)])
        producers.append(
            {
                "country": country,
                "production": production,
                "supply": supply,
                "use": use,
                "imports": imports,
                "exports": exports,
                "endingStocks": ending_stocks,
                "statusCode": status["code"],
                "statusLabel": status["label"],
                "gap": status["gap"],
                "balanceRatio": status["ratio"],
            }
        )

    producers.sort(key=lambda item: item["production"], reverse=True)
    top_countries = producers[:10]
    total_top_production = sum(item["production"] for item in top_countries)
    for item in top_countries:
        item["productionShare"] = item["production"] / total_top_production if total_top_production else 0.0

    status_count = {"surplus": 0, "balanced": 0, "deficit": 0, "unknown": 0}
    for item in top_countries:
        status_count[item["statusCode"]] += 1

    market_year_start = int(value_header[:4]) if value_header[:4].isdigit() else None

    return {
        "code": meta["code"],
        "groupCode": meta["group"],
        "nameZh": meta["nameZh"],
        "nameEn": current_commodity or meta["nameEn"],
        "marketYearLabel": value_header,
        "marketYearStart": market_year_start,
        "unit": "(1000 MT)",
        "global": {
            "statusCode": global_status["code"],
            "statusLabel": global_status["label"],
            "supply": global_supply,
            "use": global_use,
            "gap": global_status["gap"],
            "balanceRatio": global_status["ratio"],
            "production": global_production,
            "imports": global_imports,
            "exports": global_exports,
            "endingStocks": global_ending_stocks,
        },
        "topCountries": top_countries,
        "countryStatusCount": status_count,
    }


def main():
    commodities = [parse_commodity(meta) for meta in METADATA]
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "name": "USDA FAS PSD Online",
            "endpoint": "https://apps.fas.usda.gov/PSDOnlineApi/api/query/RunQuery",
            "note": "Commodity-level latest market year from GetAvailabilityByCommodity maxYear.",
        },
        "thresholds": {"balancedBand": "+/-2% (supply-use gap / use)"},
        "commodities": commodities,
    }
    OUTPUT_JS.write_text("window.usdaPsdTopicData = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    print(f"Generated {OUTPUT_JS}")


if __name__ == "__main__":
    main()
