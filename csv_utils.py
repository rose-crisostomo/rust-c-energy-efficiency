import os
import csv
from metrics import Metrics, ENERGY_PER_INSTR_NJ

def save_results(results: dict[str, Metrics], is_intermittent: bool) -> None:
    os.makedirs("results", exist_ok=True)

    with open("results/execution_times.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Language",
            "Instructions",
            "Virtual Time us",
            "Est Energy uJ",
            "Reboots",
            "CP Attempts",
            "CP Saved",
            "Success Rate %",
            "Total NVM Writes",
            "Avg Instrs per CP",
        ])
        for lang, m in results.items():
            writer.writerow([
                lang,
                m.final_instructions,
                round(m.final_vt_us, 2),
                round(m.estimated_energy_uj, 4),
                m.reboots,
                m.starting_checkpoint_count,
                m.checkpoint_count,
                round(m.checkpoint_success_rate, 2),
                m.total_nvm_writes,
                round(m.avg_cp_instrs, 2),
            ])
    print(f"\nDetailed results saved to: results/execution_times.csv")

    if is_intermittent and any(m.cp_instrs_delta for m in results.values()):
        with open("results/per_checkpoint_energy.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Language",
                "Checkpoint #",
                "Instructions Delta",
                "Virtual Time Delta us",
                "NVM Writes",
                "Est Energy uJ",
            ])
            for lang, m in results.items():
                # chance that NVM write finished but system resets just before "Checkpoint saved" is emitted
                n = max(len(m.cp_instrs_delta), len(m.nvm_writes_per_cp), 1)
                for i in range(n):
                    instr_d = m.cp_instrs_delta[i] if i < len(m.cp_instrs_delta) else ""
                    vt_d = round(m.cp_vt_delta_us[i], 2) if i < len(m.cp_vt_delta_us) else ""
                    nvm_w = m.nvm_writes_per_cp[i] if i < len(m.nvm_writes_per_cp) else ""
                    e_uj = round(int(instr_d) * ENERGY_PER_INSTR_NJ / 1_000, 6) if instr_d != "" else ""
                    writer.writerow([lang, i + 1, instr_d, vt_d, nvm_w, e_uj])
        print(f"Per-checkpoint energy saved to: results/per_checkpoint_energy.csv")