-- qlnes APU trace recorder — runs inside fceux's Lua engine.
--
-- Schema: qlnes-trace v1
-- Columns: frame  cycle  addr_hex  value_hex
--   frame     : NTSC frame number (60 fps), int
--   cycle     : CPU cycle since this script started, int
--   addr_hex  : APU register written ($4000-$4017), 4-digit hex
--   value_hex : byte that was written, 2-digit hex
--
-- Env vars:
--   QLNES_TRACE_OUT          required — output TSV path
--   QLNES_FRAMES             optional — frames to capture (default 600 = 10s NTSC)
--   QLNES_REFERENCE_WAV      optional — if set, also captures fceux's audio
--                            output to this path via sound.recordstart()
--
-- Title-screen bypass: taps START at frames 60, 120, 180 to get most ROMs
-- past their splash. ROMs that need different inputs need a per-engine tweak
-- in phase 7.4+ (qlnes/audio/engines/<engine>.py).

local out_path = os.getenv("QLNES_TRACE_OUT") or "/tmp/apu_trace.tsv"
local total_frames = tonumber(os.getenv("QLNES_FRAMES")) or 600
local ref_wav_path = os.getenv("QLNES_REFERENCE_WAV")

local fh = io.open(out_path, "w")
if not fh then
    error("cannot open " .. out_path .. " for writing")
end

fh:write("# qlnes-trace v1\n")
fh:write("# columns: frame\tcycle\taddr_hex\tvalue_hex\n")

debugger.resetcyclescount()

local function on_apu_write(addr, size, value)
    local v = memory.readbyte(addr)
    fh:write(string.format(
        "%d\t%d\t%04X\t%02X\n",
        emu.framecount(), debugger.getcyclescount(), addr, v
    ))
end

for a = 0x4000, 0x4017 do
    memory.registerwrite(a, on_apu_write)
end

emu.registerexit(function()
    if fh then fh:close() end
    if ref_wav_path then
        pcall(sound.recordstop)
    end
end)

if ref_wav_path then
    sound.recordstart(ref_wav_path)
end

local press_at = { [60] = true, [120] = true, [180] = true }

for i = 1, total_frames do
    if press_at[i] then
        joypad.set(1, { start = true })
    end
    emu.frameadvance()
end

if ref_wav_path then
    sound.recordstop()
end

fh:close()
fh = nil
emu.exit()
