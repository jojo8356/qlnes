-- qlnes APU trace recorder — runs in fceux, traps writes to $4000-$4017.
-- Output: tab-separated text file at $QLNES_TRACE_OUT
--   columns: frame  cycle  addr_hex  value_hex
-- Auto-presses START a few times to get past title screens.
-- Exits cleanly after $QLNES_FRAMES frames (default 600 = 10s NTSC).

local out_path = os.getenv("QLNES_TRACE_OUT") or "/tmp/apu_trace.tsv"
local total_frames = tonumber(os.getenv("QLNES_FRAMES")) or 600

local fh = io.open(out_path, "w")
if not fh then
    error("cannot open " .. out_path .. " for writing")
end
fh:write("# qlnes APU trace — fceux Lua\n")
fh:write("# columns: frame\tcycle\taddr_hex\tvalue_hex\n")

-- cycle counter is global since power-on; resetting once gives us
-- 0-based timestamps relative to capture start.
debugger.resetcyclescount()

local function on_apu_write(addr, size, value)
    -- The fceux callback signature has historically been (addr) only,
    -- with the actual byte readable via memory.readbyte(addr). We read
    -- back to be safe — the value is whatever was just written.
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
end)

-- Title-screen bypass: tap START a few times during the first second.
local press_at = { [60] = true, [120] = true, [180] = true }

for i = 1, total_frames do
    if press_at[i] then
        joypad.set(1, { start = true })
    end
    emu.frameadvance()
end

fh:close()
fh = nil
emu.exit()
