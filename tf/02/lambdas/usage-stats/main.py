"""
account usage logging

Handles receipt of usage metrics on DynamoDB Streams and aggregates metrics.

NB: these access patterns are used in the tools.usage definitions for the api
"""
import os
import logging
import json

from datetime import datetime
from dynawrap import DynamodbWrapper, DBItem

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
USAGE_TABLE_NAME = os.environ["DYNAMODB_USAGE_TABLE"]


def add_metrics(ag_metrics, raw_metrics: dict):
    """Sum two metric dicts

    Args:
        raw_metrics (RawUsageMetrics): Raw metrics to add.
    """
    new_metrics = {k: ag_metrics.get(k, 0) + v for k, v in raw_metrics.items()}
    new_metrics["count"] = ag_metrics.get("count", 0) + 1

    return new_metrics


class AggregateOperationUsageMetrics(DBItem):
    """Aggregate metrics table row definition
    aggregates by operation
    """

    table_name = USAGE_TABLE_NAME
    pk_pattern = "METRIC#SUM#USER#{user_id}"
    sk_pattern = "DATE_RANGE#{range_type}#{range_key}#OP#{operation}"

    def __init__(self, db_wrapper):
        super().__init__(db_wrapper)
        self.metrics = {}

    def add_raw_metrics(self, raw_metrics: dict):
        """Add raw metrics to the aggregate
        updates the internal .metrics field

        Args:
            raw_metrics (RawUsageMetrics): Raw metrics to add.
        """
        self.metrics = add_metrics(self.metrics, raw_metrics)


class AggregateUsageMetrics(DBItem):
    """Aggregate metrics table row definition
    aggregates over all operations.
    NB: this could be derived from AggregateOperationUsageMetrics but
        I don't know how the metaclass will behave and have no time to test rn
    """

    table_name = USAGE_TABLE_NAME
    pk_pattern = "METRIC#SUM#USER#{user_id}"
    sk_pattern = "DATE_RANGE#{range_type}#{range_key}#OP#ALL"

    def __init__(self, db_wrapper):
        super().__init__(db_wrapper)
        self.metrics = {}

    def add_raw_metrics(self, raw_metrics: dict):
        """Add raw metrics to the aggregate
        updates the internal .metrics field

        Args:
            raw_metrics (RawUsageMetrics): Raw metrics to add.
        """
        self.metrics = add_metrics(self.metrics, raw_metrics)


db_wrapper = DynamodbWrapper(AggregateOperationUsageMetrics)


def extract_numeric_metrics(data: dict):
    """Return only numeric fields of the `data` dict.

    Returns:
        dict: Validated dictionary with numeric values.
    """
    m = {}

    for k, v in data.items():
        if isinstance(v, (int, float)):
            m[k] = v
        else:
            try:
                m[k] = float(v)
            except (ValueError, TypeError):
                pass
            except Exception as e:
                raise e

    return m


def dynamodb_stream_handler(event, context):
    """
    Handles DynamoDB Stream events to aggregate metrics.
    """
    logger.debug("processing: '%s'", str(event))

    for idx, record in enumerate(event["Records"]):
        # process only MODIFY or INSERT events
        if record["eventName"] not in ("MODIFY", "INSERT"):
            logger.debug("ignoring '%s' event", record["eventName"])
            continue

        logger.debug("[%i/%i] '%s'", idx, len(event["Records"]), str(record))

        # Extract the new image from the stream
        if "NewImage" not in record["dynamodb"]:
            logger.warning("No NewImage in record: %s", record)
            continue

        new_image = record["dynamodb"]["NewImage"]

        # process only raw events
        if not new_image["PK"]["S"].startswith("METRIC#RAW"):
            logger.debug("ignoring non-raw metric: '%s'", new_image["PK"]["S"])
            continue

        if any(x not in new_image for x in ("operation", "user_id", "date")):
            logger.error(
                "'operation', 'user_id' or 'date' missing from row: '%s'",
                str(new_image),
            )
            continue

        user_id = new_image["user_id"]["S"]
        op = new_image["operation"]["S"]
        date = new_image["date"]["S"]
        metrics = json.loads(new_image["data"]["S"])

        logger.debug("[%s/%s] processing updated row", user_id, op)

        # Parse the date
        try:
            event_date = datetime.strptime(date, "%Y%m%dT%H%M%SZ")
        except ValueError:
            logger.error("Invalid date format: %s", date)
            continue

        # Update daily, monthly, and yearly aggregates
        update_aggregate_row(
            user_id,
            op,
            "D",
            event_date.strftime("%Y%m%d"),
            metrics,
            AggregateOperationUsageMetrics,
        )  # day
        update_aggregate_row(
            user_id,
            op,
            "M",
            event_date.strftime("%Y%m"),
            metrics,
            AggregateOperationUsageMetrics,
        )  # month
        update_aggregate_row(
            user_id,
            "all",
            "D",
            event_date.strftime("%Y%m%d"),
            metrics,
            AggregateUsageMetrics,
        )  # day
        update_aggregate_row(
            user_id,
            "all",
            "M",
            event_date.strftime("%Y%m"),
            metrics,
            AggregateUsageMetrics,
        )  # month


def update_aggregate_row(
    user_id,
    operation,
    range_type,
    range_key,
    raw_metrics: dict,
    ag_type=AggregateOperationUsageMetrics,
):
    """Update the row aggregates for the specified range (day, month, year).
    # FIXME: get the metric METRICS#SUM#DAY and increment

    ag_type is the access pattern for the row data, operation field is ignored for AggregateUsageMetric
    """
    # fetch the associated METRIC#SUM row from the db
    # populate the AggregateOperationUsageMetrics object
    # add the new RawUsageMetrics object
    # write the updated AggregateMetrics object back to the row

    logger.debug("aggregating: '%s/%s'", str(range_type), str(range_key))

    try:
        ag = ag_type.read(
            db_wrapper,
            user_id=user_id,
            range_type=range_type,
            range_key=range_key,
            operation=operation,
        )
        ag.metrics = json.loads(ag.data["data"])
        ag.metrics = extract_numeric_metrics(ag.metrics)
    except ValueError:
        # no item found
        logger.warning("[%s/%s/%s] aggregate not found", user_id, range_type, range_key)
        ag = ag_type(db_wrapper)

    logger.debug("adding '%s' to '%s'", str(raw_metrics), str(ag.metrics))
    ag.add_raw_metrics(extract_numeric_metrics(raw_metrics))

    save_item = dict(
        user_id=user_id,
        operation=operation,
        range_type=range_type,
        range_key=range_key,
        data=json.dumps(ag.metrics),
    )

    logger.debug("saving aggregate: '%s'", str(save_item))

    try:
        ag.save(save_item)
    except Exception as e:
        logger.error("Failed to update aggregate row for %s: %s", range_type, e)

    logger.debug("aggregated for %s: %s", range_type, ag)
