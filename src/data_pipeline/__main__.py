"""CLI entry: python -m src.data_pipeline [--db PATH]"""
import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(description="寻龙诀 盘中实时数据管道")
    parser.add_argument("--db", default=None, help="recap.db path")
    args = parser.parse_args()

    from .engine import Pipeline

    pipeline = Pipeline(db_path=args.db) if args.db else Pipeline()

    try:
        asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        logging.getLogger("data_pipeline").info("Shutdown by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
