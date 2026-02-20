"""
Worker: consumes job IDs from Redis, runs pipeline (fetch → preprocess → face → inference → report).
"""
import asyncio
import os
import sys

# Allow importing from parent for shared job logic if needed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from worker.redis_queue import consume_queue
from worker.pipeline import run_pipeline


async def main():
    print("Worker started, waiting for jobs...", flush=True)
    while True:
        try:
            await consume_queue(run_pipeline)
        except Exception as e:
            print(f"Worker error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
