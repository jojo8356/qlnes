NES_REGS = {
    0x2000: "PPUCTRL",
    0x2001: "PPUMASK",
    0x2002: "PPUSTATUS",
    0x2003: "OAMADDR",
    0x2004: "OAMDATA",
    0x2005: "PPUSCROLL",
    0x2006: "PPUADDR",
    0x2007: "PPUDATA",
    0x4000: "APU_PULSE1_CTRL",
    0x4001: "APU_PULSE1_SWEEP",
    0x4002: "APU_PULSE1_TIMER_LO",
    0x4003: "APU_PULSE1_TIMER_HI",
    0x4004: "APU_PULSE2_CTRL",
    0x4005: "APU_PULSE2_SWEEP",
    0x4006: "APU_PULSE2_TIMER_LO",
    0x4007: "APU_PULSE2_TIMER_HI",
    0x4008: "APU_TRI_CTRL",
    0x4009: "APU_TRI_UNUSED",
    0x400A: "APU_TRI_TIMER_LO",
    0x400B: "APU_TRI_TIMER_HI",
    0x400C: "APU_NOISE_CTRL",
    0x400D: "APU_NOISE_UNUSED",
    0x400E: "APU_NOISE_PERIOD",
    0x400F: "APU_NOISE_LEN",
    0x4010: "APU_DMC_FREQ",
    0x4011: "APU_DMC_RAW",
    0x4012: "APU_DMC_START",
    0x4013: "APU_DMC_LEN",
    0x4014: "OAMDMA",
    0x4015: "APU_STATUS",
    0x4016: "JOY1",
    0x4017: "JOY2_FRAMECTR",
    0xFFFA: "VEC_NMI",
    0xFFFB: "VEC_NMI_HI",
    0xFFFC: "VEC_RESET",
    0xFFFD: "VEC_RESET_HI",
    0xFFFE: "VEC_IRQ",
    0xFFFF: "VEC_IRQ_HI",
}


def oam_name(addr: int) -> str:
    if not 0x0200 <= addr <= 0x02FF:
        raise ValueError(f"addr {addr:#06x} not in OAM range")
    n = (addr - 0x0200) // 4
    field = (addr - 0x0200) % 4
    suffix = ("y", "tile", "attr", "x")[field]
    return f"sprite_{n}_{suffix}"
