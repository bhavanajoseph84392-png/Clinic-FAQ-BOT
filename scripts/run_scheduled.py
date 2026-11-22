import sys

from app.scheduled import send_all_morning_digests, send_all_weekly_summaries


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("morning", "weekly"):
        print("Usage: python scripts/run_scheduled.py morning|weekly")
        return 1

    mode = sys.argv[1]
    if mode == "morning":
        send_all_morning_digests()
    else:
        send_all_weekly_summaries()
    return 0


if __name__ == "__main__":
    sys.exit(main())
