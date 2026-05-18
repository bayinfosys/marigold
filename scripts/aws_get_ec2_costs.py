"""
aws_get_ec2_costs.py

Fetches current on-demand and recent spot prices for a fixed set of
instance types, computes spot p25/p50/p75, and writes a pricing JSON
file compatible with the pump audit cost estimate.

Usage:
    python3 aws_get_ec2_costs.py
    python3 aws_get_ec2_costs.py --regions eu-west-2 us-east-1
    python3 aws_get_ec2_costs.py --regions eu-west-2 --days 30 --out pricing.json
    python3 aws_get_ec2_costs.py --instances g4dn.2xlarge g5.4xlarge r5.xlarge
"""

import argparse
import json
import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional

import boto3

log = logging.getLogger("ec2_costs")
logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=logging.INFO,
)

INSTANCE_TYPES = [
    "g4dn.xlarge",
    "g4dn.2xlarge",
    "g4dn.4xlarge",
    "g4dn.8xlarge",
    "g5.2xlarge",
    "g5.4xlarge",
    "g5.8xlarge",
    "g5.12xlarge",
    "r5.xlarge",
    "r5.2xlarge",
    "t3.medium",
    "t3.large",
]

REGION_LONG_NAMES = {
    "eu-west-1":    "EU (Ireland)",
    "eu-west-2":    "EU (London)",
    "eu-west-3":    "EU (Paris)",
    "eu-central-1": "EU (Frankfurt)",
    "us-east-1":    "US East (N. Virginia)",
    "us-east-2":    "US East (Ohio)",
    "us-west-2":    "US West (Oregon)",
}

DEFAULT_REGIONS = ["eu-west-2"]
SPOT_HISTORY_DAYS = 30


# ---------------------------------------------------------------------------
# On-demand pricing via AWS Price List API (us-east-1 only)
# ---------------------------------------------------------------------------

def get_od_prices(region: str, instance_types: list) -> dict[str, Optional[float]]:
    """
    Returns {instance_type: hourly_usd} for on-demand Linux prices.
    Price List API is only available in us-east-1.
    """
    client = boto3.client("pricing", region_name="us-east-1")

    region_name_map = _get_region_name_map()
    region_long = region_name_map.get(region)
    if not region_long:
        log.warning("no long name found for region %s -- OD prices unavailable", region)
        return {t: None for t in instance_types}

    results = {}
    for itype in instance_types:
        try:
            resp = client.get_products(
                ServiceCode="AmazonEC2",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "instanceType",    "Value": itype},
                    {"Type": "TERM_MATCH", "Field": "location", "Value": REGION_LONG_NAMES[region]},
                    {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
                    {"Type": "TERM_MATCH", "Field": "tenancy",         "Value": "Shared"},
                    {"Type": "TERM_MATCH", "Field": "capacitystatus",  "Value": "Used"},
                    {"Type": "TERM_MATCH", "Field": "preInstalledSw",  "Value": "NA"},
                ],
                MaxResults=1,
            )
            price_list = resp.get("PriceList", [])
            if not price_list:
                log.warning("no OD price found for %s in %s", itype, region)
                results[itype] = None
                continue

            doc = json.loads(price_list[0])
            od_terms = doc.get("terms", {}).get("OnDemand", {})
            price_usd = _extract_price(od_terms)
            results[itype] = price_usd

        except Exception as e:
            log.error("OD price fetch failed for %s/%s: %s", region, itype, e)
            results[itype] = None

    return results


def _extract_price(od_terms: dict) -> Optional[float]:
    for term in od_terms.values():
        for dimension in term.get("priceDimensions", {}).values():
            usd = dimension.get("pricePerUnit", {}).get("USD")
            if usd and float(usd) > 0:
                return float(usd)
    return None


def _get_region_name_map() -> dict[str, str]:
    """Map region codes to long names used by the Price List API."""
    ssm = boto3.client("ssm", region_name="us-east-1")
    result = {}
    try:
        paginator = ssm.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(Path="/aws/service/global-infrastructure/regions"):
            for param in page["Parameters"]:
                code = param["Name"].split("/")[-1]
                result[code] = param["Value"]
    except Exception as e:
        log.warning("region name map fetch failed: %s -- falling back to hardcoded", e)
        result = {
            "eu-west-1":  "EU (Ireland)",
            "eu-west-2":  "EU (London)",
            "eu-west-3":  "EU (Paris)",
            "eu-central-1": "EU (Frankfurt)",
            "us-east-1":  "US East (N. Virginia)",
            "us-east-2":  "US East (Ohio)",
            "us-west-2":  "US West (Oregon)",
        }
    return result


# ---------------------------------------------------------------------------
# Spot pricing
# ---------------------------------------------------------------------------

def get_spot_prices(region: str, instance_types: list, days: int) -> dict[str, list[float]]:
    """
    Returns {instance_type: [price, ...]} for Linux/UNIX spot prices
    over the trailing N days. All AZs included; prices are pooled per
    instance type.
    """
    client = boto3.client("ec2", region_name=region)
    start  = datetime.now(timezone.utc) - timedelta(days=days)

    results = {t: [] for t in instance_types}

    try:
        paginator = client.get_paginator("describe_spot_price_history")
        for page in paginator.paginate(
            InstanceTypes=instance_types,
            ProductDescriptions=["Linux/UNIX"],
            StartTime=start,
        ):
            for entry in page["SpotPriceHistory"]:
                itype = entry["InstanceType"]
                price = float(entry["SpotPrice"])
                if itype in results:
                    results[itype].append(price)
    except Exception as e:
        log.error("spot price fetch failed for %s: %s", region, e)

    return results


# ---------------------------------------------------------------------------
# Percentiles
# ---------------------------------------------------------------------------

def percentiles(prices: list[float]) -> Optional[dict]:
    if not prices:
        return None
    s = sorted(prices)
    n = len(s)
    return {
        "p25":    round(s[n // 4], 6),
        "p50":    round(statistics.median(s), 6),
        "p75":    round(s[min((n * 3) // 4, n - 1)], 6),
        "min":    round(s[0], 6),
        "max":    round(s[-1], 6),
        "sample": n,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_pricing(regions: list, instance_types: list, days: int) -> dict:
    output = {}

    for region in regions:
        log.info("fetching prices for region %s", region)
        output[region] = {}

        od_prices   = get_od_prices(region, instance_types)
        spot_prices = get_spot_prices(region, instance_types, days)

        for itype in instance_types:
            od    = od_prices.get(itype)
            spot  = percentiles(spot_prices.get(itype, []))

            if od is None and spot is None:
                continue

            output[region][itype] = {
                "od":   od,
                "spot": spot,
            }

            log.info(
                "  %-20s  od=%-8s  spot_p50=%-8s  (n=%d)",
                itype,
                "$%.4f" % od if od else "n/a",
                "$%.4f" % spot["p50"] if spot else "n/a",
                spot["sample"] if spot else 0,
            )

    return output


def main():
    parser = argparse.ArgumentParser(description="Fetch EC2 on-demand and spot prices.")
    parser.add_argument("--regions",   nargs="+", default=DEFAULT_REGIONS)
    parser.add_argument("--instances", nargs="+", default=INSTANCE_TYPES)
    parser.add_argument("--days",      type=int,  default=SPOT_HISTORY_DAYS,
                        help="trailing days for spot price history")
    parser.add_argument("--out",       default="ec2_pricing.json",
                        help="output JSON file path")
    args = parser.parse_args()

    pricing = build_pricing(args.regions, args.instances, args.days)

    with open(args.out, "w") as f:
        json.dump(pricing, f, indent=2)
    log.info("written to %s", args.out)

    # Print summary table
    print()
    print("%-14s  %-20s  %-8s  %-8s  %-8s  %-8s" % (
        "Region", "Instance", "OD/hr", "Spot p25", "Spot p50", "Spot p75"
    ))
    print("-" * 72)
    for region, instances in pricing.items():
        for itype, data in sorted(instances.items()):
            od   = "$%.4f" % data["od"]   if data.get("od")   else "n/a"
            spot = data.get("spot") or {}
            p25  = "$%.4f" % spot["p25"]  if spot.get("p25")  else "n/a"
            p50  = "$%.4f" % spot["p50"]  if spot.get("p50")  else "n/a"
            p75  = "$%.4f" % spot["p75"]  if spot.get("p75")  else "n/a"
            print("%-14s  %-20s  %-8s  %-8s  %-8s  %-8s" % (
                region, itype, od, p25, p50, p75
            ))
    print()


if __name__ == "__main__":
    main()
