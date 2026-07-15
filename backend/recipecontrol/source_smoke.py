"""Read-only collector diagnostics; this module never opens the application database."""

import argparse
import json
from datetime import UTC, datetime, timedelta

from recipecontrol.source import get_source_repository


def _minute(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    parsed = parsed.astimezone(UTC)
    if parsed.second or parsed.microsecond:
        raise argparse.ArgumentTypeError("timestamp must have minute precision")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only opcua_collector smoke checks")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health")
    subparsers.add_parser("machines")
    tags = subparsers.add_parser("tags")
    tags.add_argument("--machine", required=True)
    tags.add_argument("--query", default="")
    tags.add_argument("--limit", type=int, default=20)
    bounds = subparsers.add_parser("range")
    bounds.add_argument("--machine", required=True)
    dry = subparsers.add_parser("dry-run")
    dry.add_argument("--machine", required=True)
    dry.add_argument("--tag", required=True)
    dry.add_argument("--kind", choices=("numeric", "boolean", "text"), required=True)
    dry.add_argument("--start", type=_minute, required=True)
    dry.add_argument("--inclusive-end", type=_minute, required=True)
    args = parser.parse_args()
    source = get_source_repository()
    result: object
    if args.command == "health":
        result = source.health()
    elif args.command == "machines":
        result = [{"id": item.key, "name": item.name} for item in source.list_machines()]
    elif args.command == "tags":
        page = source.search_tags(args.machine, args.query, limit=args.limit)
        result = {
            "items": [
                {
                    "id": item.key,
                    "name": item.display_name,
                    "raw_data_type": item.raw_data_type,
                    "data_kind": item.data_kind,
                }
                for item in page.items
            ],
            "has_more": page.has_more,
        }
    elif args.command == "range":
        minimum, maximum = source.sample_bounds(args.machine)
        result = {
            "minimum_utc": minimum.isoformat() if minimum else None,
            "maximum_utc": maximum.isoformat() if maximum else None,
        }
    else:
        rows = list(
            source.get_samples(
                args.machine,
                {args.tag: args.kind},
                args.start,
                args.inclusive_end + timedelta(minutes=1),
            )
        )
        result = {
            "read_only": True,
            "query_start_utc": args.start.isoformat(),
            "query_end_exclusive_utc": (args.inclusive_end + timedelta(minutes=1)).isoformat(),
            "row_count": len(rows),
            "preview": [
                {
                    "sample_id": row.tie_breaker,
                    "sampled_at_utc": row.sampled_at_utc.isoformat(),
                    "value": str(row.value) if row.value is not None else None,
                    "quality": row.quality,
                    "status_code": row.status_code,
                }
                for row in rows[:10]
            ],
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
