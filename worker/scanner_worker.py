from __future__ import annotations
import os
import time
import logging
from engine import PrimeEngine, PrimeConfig

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("prime-worker")

class ScannerWorker:
    def __init__(self, engine=None):
        self.engine = engine or PrimeEngine(PrimeConfig())
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        # Broker WebSocket and persistence are intentionally injected later.
        # This loop is the always-on process boundary; Vercel must not own it.
        log.info("Prime scanner worker started")
        while self.running:
            time.sleep(5)

if __name__ == "__main__":
    ScannerWorker().run()
