from dataclasses import dataclass, field
import statistics

VOLTAGE_V = 3.3 # or V_dd, bet. 1.8 - 3.6
CURRENT_MA = 7.0 # or I_dd, typically 7, max 19 most peripherals off
CPU_FREQ_HZ = 16_000_000 # or f_HCLK, default 16 at startup, up to 168 MHz
POWER_MW = VOLTAGE_V * CURRENT_MA # 33 mW
ENERGY_PER_INSTR_NJ = (POWER_MW * 1e-3) / CPU_FREQ_HZ * 1e9 # ~1.444 nJ/instr

@dataclass
class Metrics:
    # UART event counters
    reboots: int = 0
    no_checkpoint_count: int = 0
    starting_checkpoint_count: int = 0
    checkpoint_count: int = 0
    nvm_writes_per_cp: list[int] = field(default_factory=list)

    # Per-checkpoint deltas (from CP_METRICS log lines)
    cp_instrs_delta: list[int] = field(default_factory=list)
    cp_vt_delta_us: list[float] = field(default_factory=list)

    # Final cumulative totals (from METRICS log line)
    final_instructions: int = 0
    final_vt_us: float = 0.0
    completed: bool = False

    # buffer NVM_WRITES lines until the matching "Checkpoint saved"
    _pending_nvm: list[int] = field(default_factory=list)

    # for computing deltas between CP_SNAP lines (reset on reboot)
    _last_snap_i: int = 0
    _last_snap_t: int = 0

    @property
    def total_nvm_writes(self) -> int:
        return sum(self.nvm_writes_per_cp)

    @property
    def avg_cp_instrs(self) -> float:
        return statistics.mean(self.cp_instrs_delta) if self.cp_instrs_delta else 0.0

    @property
    def avg_cp_vt_us(self) -> float:
        return statistics.mean(self.cp_vt_delta_us) if self.cp_vt_delta_us else 0.0

    @property
    def estimated_energy_uj(self) -> float:
        return self.final_instructions * ENERGY_PER_INSTR_NJ / 1_000.0

    @property
    def energy_per_checkpoint_uj(self) -> float:
        return self.avg_cp_instrs * ENERGY_PER_INSTR_NJ / 1_000.0

    @property
    def checkpoint_success_rate(self) -> float:
        if self.starting_checkpoint_count == 0:
            return 0.0
        return self.checkpoint_count / self.starting_checkpoint_count * 100.0