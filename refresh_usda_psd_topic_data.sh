#!/usr/bin/env bash
set -euo pipefail

WORKDIR="/tmp/psd_topic_data"
mkdir -p "$WORKDIR"

cat > "$WORKDIR/commodities.tsv" <<'EOF'
2222000	oil	大豆	Oilseed, Soybean
0440000	gra	玉米	Corn
0410000	gra	小麦	Wheat
4232000	oil	豆油	Oil, Soybean
0813100	oil	豆粕	Meal, Soybean
2631000	cot	棉花	Cotton
0612000	htp	原糖	Sugar, Centrifugal
EOF

> "$WORKDIR/fetch_log.tsv"

while IFS=$'\t' read -r code group _ _; do
  year=$(
    curl -sL --max-time 60 \
      "https://apps.fas.usda.gov/PSDOnlineApi/api/downloadableData/GetAvailabilityByCommodity?commodityCode=$code" \
      | jq 'map(.maxYear) | max'
  )

  payload=$(
    jq -cn \
      --arg group "$group" \
      --arg comm "$code" \
      --argjson year "$year" \
      '{
        queryId: 0,
        commodityGroupCode: $group,
        commodities: [$comm],
        attributes: [20, 28, 57, 88, 86, 125, 126, 142, 174, 176],
        countries: ["ALL"],
        marketYears: [$year],
        chkCommoditySummary: false,
        chkAttribSummary: false,
        chkCountrySummary: false,
        commoditySummaryText: "",
        attribSummaryText: "",
        countrySummaryText: "",
        optionColumn: "year",
        chkTopCountry: false,
        topCountryCount: "",
        chkfileFormat: false,
        chkPrevMonth: false,
        chkMonthChange: false,
        chkCodes: false,
        chkYearChange: false,
        queryName: "",
        sortOrder: "Commodity/Attribute/Country"
      }'
  )

  out="$WORKDIR/query_${code}.json"
  curl -sL --max-time 120 \
    -H 'Content-Type: application/json' \
    -X POST 'https://apps.fas.usda.gov/PSDOnlineApi/api/query/RunQuery' \
    --data "$payload" \
    -o "$out"

  printf '%s\t%s\t%s\t%s\n' \
    "$code" \
    "$group" \
    "$year" \
    "$(jq -r '.queryResult | length' "$out")" >> "$WORKDIR/fetch_log.tsv"
done < "$WORKDIR/commodities.tsv"

python3 /Users/anders/Documents/Playground/build_usda_psd_topic_data.py

echo "Done. Updated data file:"
echo "  /Users/anders/Documents/Playground/usda-psd-topic-data.js"
echo "Fetch log:"
cat "$WORKDIR/fetch_log.tsv"
