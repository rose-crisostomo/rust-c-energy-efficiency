import io
import os
import queue
import random
import re
import sys
import threading
import time
from csv_utils import save_results
from metrics import CPU_FREQ_HZ, CURRENT_MA, VOLTAGE_V, Metrics, ENERGY_PER_INSTR_NJ

RESC_TEMPLATES: dict[str, str] = {
    "C": "renode_scripts/stm32_c.resc",
    "Rust": "renode_scripts/stm32_rust.resc",
}

N_INTERRUPTIONS = 100
TIMEOUT_S = 120 # wall-clock budget per simulation run

TICKS_PER_US = 10 # Renode ElapsedVirtualTime ticks are 100 ns units

_RE_SNAP = re.compile(r"CP_SNAP\s+instructions=(\d+)\s+vt_ticks=(\d+)")
_RE_FINAL = re.compile(r"\bMETRICS\b\s+instructions=(\d+)\s+vt_ticks=(\d+)")
_RE_NVM = re.compile(r"NVM_WRITES=(\d+)")

INTERMITTENT = "--intermittent" in sys.argv

def _parse_line(line: str, m: Metrics) -> bool:
    if "Test Started" in line:
        # print(line, end="\n")
        m.reboots += 1
        m._last_snap_i = 0
        m._last_snap_t = 0
    elif "No checkpoint found" in line:
        m.no_checkpoint_count += 1
    elif "Starting checkpoint" in line:
        # print(line, end="\n")
        m.starting_checkpoint_count += 1
    elif "Checkpoint saved" in line:
        # print(line, end="\n")
        m.checkpoint_count += 1
        if m._pending_nvm:
            m.nvm_writes_per_cp.append(m._pending_nvm.pop(0))
    elif "METRICS" in line:
        m.completed = True

    if nvm := _RE_NVM.search(line):
        m._pending_nvm.append(int(nvm.group(1)))

    if fin := _RE_FINAL.search(line):
        m.final_instructions = int(fin.group(1))
        m.final_vt_us = int(fin.group(2)) / TICKS_PER_US

    if snap := _RE_SNAP.search(line):
        # print(line, end="\n")
        i_now = int(snap.group(1))
        t_now = int(snap.group(2))
        # Compute delta from previous snapshot
        i_prev = m._last_snap_i
        t_prev = m._last_snap_t
        m.cp_instrs_delta.append(i_now - i_prev)
        m.cp_vt_delta_us.append((t_now - t_prev) / TICKS_PER_US)
        m._last_snap_i = i_now
        m._last_snap_t = t_now
        # print(m)

    return m.completed

def _generate_resc(lang: str, template_path: str, intermittent: bool) -> str:
    os.makedirs("renode_scripts/generated", exist_ok=True)
    out_path = f"renode_scripts/generated/{lang.lower()}_bench.resc"

    with open(template_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    while lines and lines[-1].strip() in ("start", ""):
        lines.pop()

    # for some reason, "machine Reset" will reset entirely for Rust
    reset_cmd = "sysbus.cpu Reset" if lang == "Rust" else "machine Reset"

    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
        f.write("\n\n")
        f.write("\n")

        if intermittent:
            # for fun :D https://grsahagian.medium.com/what-is-random-state-42-d803402ee76b
            rng = random.Random(42)
            for us in sorted(rng.sample(range(1, 1001), N_INTERRUPTIONS)):
                f.write(f'emulation RunFor "00:00:00.{us:06d}"\n')
                f.write(f"{reset_cmd}\n")

        f.write("start\n")

    return out_path

def _read_pipe(pipe: io.TextIOWrapper, q: "queue.Queue[str | None]") -> None:
    try:
        for line in iter(pipe.readline, ""):
            q.put(line)
    finally:
        q.put(None)

def run_simulation(resc_path: str, label: str) -> Metrics:
    import subprocess

    m = Metrics()

    try:
        process = subprocess.Popen(
            ["renode", "--disable-xwt", resc_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        line_queue: queue.Queue[str | None] = queue.Queue()
        threading.Thread(
            target=_read_pipe, args=(process.stdout, line_queue), daemon=True
        ).start()

        deadline = time.time() + TIMEOUT_S
        try:
            while time.time() < deadline:
                try:
                    line = line_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                if line is None: # EOF
                    break
                if _parse_line(line.rstrip(), m):
                    break
        finally:
            process.kill()
            process.wait()

    except Exception as e:
        raise RuntimeError(f"{label} simulation failed: {e}") from e

    if not m.completed:
        raise RuntimeError(f"{label}: TIMEOUT - Simulation did not complete within {TIMEOUT_S}s")

    return m

def _percentage(a: float, b: float) -> str:
    return f"{(b - a) / a * 100:+.2f}%" if a else "N/A"

def print_run_summary(m: Metrics) -> None:
    print(f"  Instructions          : {m.final_instructions:>14,}")
    print(f"  Virtual time (us)     : {m.final_vt_us:>14,.1f}")
    print(f"  Est. energy (uJ)      : {m.estimated_energy_uj:>14.2f}")
    # if INTERMITTENT:
    print(f"  Reboots               : {m.reboots:>14}")
    print(f"  CP attempts           : {m.starting_checkpoint_count:>14}")
    print(f"  CP saved              : {m.checkpoint_count:>14}")
    print(f"  Success rate          : {m.checkpoint_success_rate:>13.1f}%")
    print(f"  Total NVM writes      : {m.total_nvm_writes:>14}")
    if m.cp_instrs_delta:
        print(f"  Instrs/CP             : avg={m.avg_cp_instrs:.0f}"
                f"  min={min(m.cp_instrs_delta)}"
                f"  max={max(m.cp_instrs_delta)}")
        print(f"  Time/CP (us)          : avg={m.avg_cp_vt_us:.1f}"
                f"  min={min(m.cp_vt_delta_us):.1f}"
                f"  max={max(m.cp_vt_delta_us):.1f}")
        print(f"  Energy/CP (uJ)        : {m.energy_per_checkpoint_uj:>14.6f}")

def print_comparison(results: dict[str, Metrics]) -> None:
    if "C" not in results or "Rust" not in results:
        return
    c, rs = results["C"], results["Rust"]

    rows: list[tuple] = [
        ("Instructions", c.final_instructions, rs.final_instructions),
        ("Virtual time (us)", c.final_vt_us, rs.final_vt_us),
        ("Est. energy (uJ)", c.estimated_energy_uj, rs.estimated_energy_uj),
    ]
    # if INTERMITTENT:
    rows += [
        ("Reboots", c.reboots, rs.reboots),
        ("CP attempts", c.starting_checkpoint_count, rs.starting_checkpoint_count),
        ("CP saved", c.checkpoint_count, rs.checkpoint_count),
        ("Success rate (%)", c.checkpoint_success_rate, rs.checkpoint_success_rate),
        ("NVM writes", c.total_nvm_writes, rs.total_nvm_writes),
        ("Avg instrs/CP", c.avg_cp_instrs, rs.avg_cp_instrs),
        ("Avg time/CP (us)", c.avg_cp_vt_us, rs.avg_cp_vt_us),
        ("Avg energy/CP(uJ)", c.energy_per_checkpoint_uj, rs.energy_per_checkpoint_uj),
    ]

    print("\n" + "=" * 70)
    print("COMPARISON RESULTS (deterministic simulated metrics)")
    print("=" * 70)
    print(f"\n{'Metric':<25} {'C':>15} {'Rust':>15} {'Delta %':>9}")
    print("-" * 70)
    for label, cv, rv in rows:
        print(f"{label:<25} {cv:>15.2f} {rv:>15.2f} {_percentage(float(cv), float(rv)):>9}")

    winner = "Rust" if rs.final_instructions < c.final_instructions else "C"
    margin = abs((rs.final_instructions - c.final_instructions) / max(c.final_instructions, 1) * 100)
    print(f"\n{winner} executes fewer instructions ({margin:.2f}% difference)")

def main() -> None:
    mode = "intermittent power-loss" if INTERMITTENT else "single clean run"
    results: dict[str, Metrics] = {}

    print("=" * 70)
    print("ENERGY EFFICIENCY BENCHMARK - C vs Rust")
    print(f"  mode : {mode}")
    print(f"  model: {VOLTAGE_V}V x {CURRENT_MA}mA @ {CPU_FREQ_HZ // 1_000_000}MHz"
          f"  ->  {ENERGY_PER_INSTR_NJ:.4f} nJ / instruction")
    print("=" * 70)

    for lang, template in RESC_TEMPLATES.items():
        resc_path = _generate_resc(lang, template, INTERMITTENT)

        print(f"\n{lang}")
        print("-" * 70)

        m = run_simulation(resc_path, lang)

        results[lang] = m
        print_run_summary(m)

    print_comparison(results)

    print("\n" + "=" * 70)
    print("SAVING RESULTS")
    print("=" * 70)
    save_results(results, INTERMITTENT)


if __name__ == "__main__":
    main()