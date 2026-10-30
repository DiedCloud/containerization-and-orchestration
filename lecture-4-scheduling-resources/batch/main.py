"""Disposable analytics: bounded CPU duty cycle and gradually allocated memory."""
import os
import time

memory_mib = int(os.getenv("MEMORY_MIB", "64"))
duty = float(os.getenv("CPU_DUTY", "0.2"))
if memory_mib < 0 or not 0 <= duty <= 1:
    raise ValueError("MEMORY_MIB >= 0 and 0 <= CPU_DUTY <= 1 required")
blocks = []
for _ in range(memory_mib):
    blocks.append(bytearray(b"x" * 1024 * 1024))
    time.sleep(float(os.getenv("ALLOCATION_DELAY", "0.02")))
print(f"Allocated {memory_mib} MiB, CPU duty={duty}", flush=True)
while True:
    start = time.monotonic()
    while time.monotonic() - start < duty * 0.1:
        sum(i * i for i in range(1000))
    time.sleep((1 - duty) * 0.1)
