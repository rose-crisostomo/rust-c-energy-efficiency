import subprocess
import sys
import time
import csv
import os
import re
import threading
import queue
import io

# regex to parse the METRICS line emitted by the Renode hook:
# [INFO] usart2: METRICS instructions=<N> virtual_us=<N>
_METRICS_RE = re.compile(r"instructions=(\d+)\s+virtual_us=(\d+)")

# run a second time and assert results match
# expected to be deterministic/same in Renode
VERIFY = "--verify" in sys.argv

def _read_pipe(pipe: io.TextIOWrapper, q: queue.Queue[str | None]):
    try:
        for line in iter(pipe.readline, ''):
            q.put(line)
    finally:
        q.put(None)

def run_simulation(script: str, label: str) -> dict[str, int]:
    try:
        process = subprocess.Popen(
            ["renode", "--disable-xwt", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        line_queue = queue.Queue[str | None]()
        threading.Thread(target=_read_pipe, args=(process.stdout, line_queue), daemon=True).start()

        completed = False
        metrics = None
        deadline = time.time() + 60
        try:
            while time.time() < deadline:
                try:
                    line = line_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                if line is None: # found EOF
                    break
                line = line.rstrip()
                if any(k in line for k in ("ERROR", "WARNING", "Machine started", "Machine paused", "METRICS")):
                    print(f"    [renode] {line}")
                m = _METRICS_RE.search(line)
                if m:
                    metrics = {
                        "instructions": int(m.group(1)),
                        "virtual_us":   int(m.group(2)),
                    }
                if metrics is not None:
                    completed = True
                    break
        finally:
            process.kill()
            process.wait()

    except Exception as e:
        raise RuntimeError(f"{label} simulation failed: {e}") from e

    if not completed:
        raise RuntimeError(f"{label}: TIMEOUT - simulation did not pause within 60s")
    if metrics is None:
        raise RuntimeError(f"{label}: METRICS line not found in output")
    return metrics

os.makedirs("results", exist_ok=True)

languages = {"C": "renode_scripts/stm32_c.resc", "Rust": "renode_scripts/stm32_rust.resc"}
results = dict[str, dict[str, int]]()

print("=" * 70)
print("ENERGY EFFICIENCY BENCHMARK - C vs Rust")
if VERIFY:
    print("  mode: single run + determinism verification")
else:
    print("  mode: single run  (use --verify to run twice and check determinism)")
print("=" * 70)

for lang, script in languages.items():
    print(f"\n{lang}")
    print("-" * 70)

    metrics = run_simulation(script, lang)
    print(f"  Instructions:  {metrics['instructions']:>12,}")
    print(f"  Virtual Time:  {metrics['virtual_us']:>12,} us")

    if VERIFY:
        print(f"  Verifying determinism (second run)...")
        metrics2 = run_simulation(script, lang)
        if metrics2 == metrics:
            print(f"    Determinism confirmed: both runs identical")
        else:
            print(f"    DETERMINISM FAILURE:")
            print(f"    Run 1: instructions={metrics['instructions']}  virtual_us={metrics['virtual_us']}")
            print(f"    Run 2: instructions={metrics2['instructions']}  virtual_us={metrics2['virtual_us']}")
            sys.exit(1)

    results[lang] = metrics

print("\n" + "=" * 70)
print("SAVING RESULTS")
print("=" * 70)

with open("results/execution_times.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Language", "Instructions", "Virtual Time (us)"])
    for lang, m in results.items():
        writer.writerow([lang, m["instructions"], m["virtual_us"]])

if results.get("C") and results.get("Rust"):
    c  = results["C"]
    rs = results["Rust"]

    diff_i  = abs(c["instructions"] - rs["instructions"])
    pct_i   = diff_i  / max(c["instructions"], rs["instructions"]) * 100
    diff_vt = abs(c["virtual_us"] - rs["virtual_us"])
    pct_vt  = diff_vt / max(c["virtual_us"],   rs["virtual_us"]) * 100

    print("\n" + "=" * 70)
    print("COMPARISON RESULTS  (deterministic simulated metrics)")
    print("=" * 70)
    print(f"\n{'Metric':<25} {'C':>15} {'Rust':>15} {'Diff %':>8}")
    print("-" * 70)
    print(f"{'Instructions':<25} {c['instructions']:>15,} {rs['instructions']:>15,} {pct_i:>7.2f}%")
    print(f"{'Virtual Time (us)':<25} {c['virtual_us']:>15,} {rs['virtual_us']:>15,} {pct_vt:>7.2f}%")

    faster = "C" if c["instructions"] < rs["instructions"] else "Rust"
    print(f"\n{faster} executes fewer instructions ({pct_i:.2f}% difference)")
    print(f"\nDetailed results saved to: results/execution_times.csv")

print("\n" + "=" * 70)