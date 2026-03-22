import csv
import shutil
import subprocess
import time
import os
import threading
import queue
import io
import random

overall_start = time.perf_counter()

def _read_pipe(pipe: io.TextIOWrapper, q: queue.Queue[str | None]):
    try:
        for line in iter(pipe.readline, ''):
            q.put(line)
    finally:
        q.put(None)

def run_simulation(script: str, label: str) -> tuple[int, int, int, int]:
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
        deadline = time.time() + 60
        reboot_count = 0
        no_checkpoint_count = 0
        starting_checkpoint_count = 0
        checkpoint_count = 0
        try:
            while time.time() < deadline:
                try:
                    line = line_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                if line is None: # found EOF
                    break
                line = line.rstrip()
                # print(f"    [renode] {line}")
                if "Test Started" in line:
                    reboot_count += 1
                    # elapsed_so_far = time.perf_counter() - overall_start
                    # print(f"    [elapsed] {elapsed_so_far:.2f} s since benchmark start")
                elif "No checkpoint found" in line:
                    no_checkpoint_count += 1
                elif "Starting checkpoint" in line:
                    starting_checkpoint_count += 1
                elif "Checkpoint saved" in line:
                    checkpoint_count += 1
                if "Test completed" in line:
                    completed = True
                    break
        finally:
            process.kill()
            process.wait()

    except Exception as e:
        raise RuntimeError(f"{label} simulation failed: {e}") from e

    if not completed:
        raise RuntimeError(f"{label}: TIMEOUT - simulation did not pause within 60s")

    return reboot_count, no_checkpoint_count, starting_checkpoint_count, checkpoint_count

def generate_resc_files(languages: dict[str, str]) -> dict[str, str]:
    duration_list = [f"00:00:00.{i:06d}" for i in sorted(random.sample(range(1, 1001), 100))]
    generated_files: dict[str, str] = {}

    for lang, path in languages.items():
        new_path = shutil.copy(path, "renode_scripts/generated/")
        with open(new_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if lines and lines[-1].strip() == "start":
            lines.pop()

        with open(new_path, "w") as f:
            f.writelines(lines)
            if lines and not lines[-1].endswith("\n"):
                f.write("\n")

            for duration in duration_list:
                f.write(f"emulation RunFor \"{duration}\"\n")
                f.write(f"{'sysbus.cpu' if lang == 'Rust' else 'machine'} Reset\n")

            f.write("start\n")

        generated_files[lang] = new_path

    return generated_files


os.makedirs("results", exist_ok=True)
os.makedirs("renode_scripts/generated", exist_ok=True)

template_languages = {"C": "renode_scripts/stm32_c.resc", "Rust": "renode_scripts/stm32_rust.resc"}
languages = generate_resc_files(template_languages)
results = dict[str, tuple[int, int, int, int]]()

print("=" * 70)
print("ENERGY EFFICIENCY BENCHMARK - C vs Rust")
print("=" * 70)

for lang, script in languages.items():
    print(f"\n{lang}")
    print("-" * 70)

    results[lang] = run_simulation(script, lang)
    reboot_count, no_checkpoint_count, starting_checkpoint_count, checkpoint_count = results[lang]

    print(f"  Reboots:                {reboot_count}")
    print(f"  No Checkpoints Found:   {no_checkpoint_count}")
    print(f"  Starting Checkpoints:   {starting_checkpoint_count}")
    print(f"  Checkpoints Saved:      {checkpoint_count}")

print("\n" + "=" * 70)
print("SAVING RESULTS")
print("=" * 70)

with open("results/checkpoint_test_results.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Language", "Reboots", "No Checkpoints Found", "Starting Checkpoints", "Checkpoints Saved"])
    for lang, m in results.items():
        writer.writerow([lang, m[0], m[1], m[2], m[3]])

if results.get("C") and results.get("Rust"):
    c  = results["C"]
    rs = results["Rust"]

    diff_reboots = abs(c[0] - rs[0])
    pct_reboots  = diff_reboots / max(c[0], rs[0]) * 100 if max(c[0], rs[0]) > 0 else 0
    diff_no_cp   = abs(c[1] - rs[1])
    pct_no_cp    = diff_no_cp  / max(c[1], rs[1]) * 100 if max(c[1], rs[1]) > 0 else 0
    diff_start_cp = abs(c[2] - rs[2])
    pct_start_cp  = diff_start_cp  / max(c[2], rs[2]) * 100 if max(c[2], rs[2]) > 0 else 0
    diff_cp      = abs(c[3] - rs[3])
    pct_cp       = diff_cp       / max(c[3], rs[3]) * 100 if max(c[3], rs[3]) > 0 else 0

    print("\n" + "=" * 70)
    print("COMPARISON RESULTS  (deterministic simulated metrics)")
    print("=" * 70)
    print(f"\n{'Metric':<25} {'C':>15} {'Rust':>15} {'Diff %':>8}")
    print("-" * 70)
    print(f"{'Reboots':<25} {c[0]:>15} {rs[0]:>15} {pct_reboots:>7.2f}%")
    print(f"{'No Checkpoints Found':<25} {c[1]:>15} {rs[1]:>15} {pct_no_cp:>7.2f}%")
    print(f"{'Starting Checkpoints':<25} {c[2]:>15} {rs[2]:>15} {pct_start_cp:>7.2f}%")
    print(f"{'Checkpoints Saved':<25} {c[3]:>15} {rs[3]:>15} {pct_cp:>7.2f}%")

elapsed_seconds = time.perf_counter() - overall_start
print(f"\nTotal elapsed wall time: {elapsed_seconds:.2f} s")