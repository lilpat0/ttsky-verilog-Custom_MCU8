"""
Cocotb testbench for tt_um_cpu8

DUT hierarchy exercised (top-level only — this mirrors how the design is
actually driven on real silicon / the Tiny Tapeout harness):

    tt_um_cpu8
      |-- uart_programmer8   (rx = uio_in[0])
      |-- cpu8
            |-- instruction_memory8
            |-- decode8
            |-- alu8
            |-- ram8
            |-- gpio8
            |-- pc8

There is no direct access to program_we/program_address/program_data from
outside the chip, so the only way to load a program is to bit-bang the
same UART protocol the uart_programmer8 module expects:

    0xAA <addr> <data>   -> write <data> into instruction memory at <addr>
    0x55                 -> start the CPU (pc <- 0, running <- 1)

UART timing is derived from the RTL parameters that are hard-coded into
tt_um_cpu8 (CLK_FREQ = 60_000_000, BAUD_RATE = 115200), expressed in
*clock cycles*, so the testbench clock period itself is arbitrary.

ISA notes that shape what's testable (see decode8.sv / cpu_top8.sv):
  - The ALU only ever computes accumulator OP <4-bit immediate>; there is
    no register-register or memory-operand ALU op, so "sum values from
    RAM" style programs aren't representable.
  - STORE/LOAD addresses and JMP/BZ/BNZ targets are literal 4-bit values
    baked into the instruction (no indirect/computed addressing), so they
    only ever reach addresses 0-15 of instruction memory / RAM.
  - LOAD only special-cases operand 0xE (GPIO input); operand 0xC/0xD on a
    LOAD fall through to a plain RAM read at that address. Since STORE
    *does* special-case 0xC/0xD (GPIO output/direction) and therefore
    never writes RAM there, "LOAD 0xC"/"LOAD 0xD" will always read back 0,
    not whatever was last STOREd to GPIO. This is exercised explicitly
    below (test_load_gpio_addr_reads_ram_not_gpio) rather than "fixed",
    since it's the real, observable behaviour of the given RTL.
  - Instruction memory (instruction_memory8.sv) is not cleared by rst_n,
    only by the power-on `initial` block, so it retains whatever the
    UART programmer last wrote across resets/tests. Every test below
    therefore (re)loads its own complete program ending in HALT so it
    never falls through into another test's leftover instructions.

Run with (Icarus Verilog, from a directory containing all the .sv files
and this test.py + the accompanying Makefile):

    make
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

# ---------------------------------------------------------------------------
# Physical-pin-only access
#
# This testbench must only ever drive/observe tt_um_cpu8's actual chip
# pins — the same 8 signals available on real Tiny Tapeout silicon / the
# TT harness. No hierarchical references into cpu8, decode8, alu8, ram8,
# gpio8, pc8, instruction_memory8, or uart_programmer8 are used anywhere
# below; internal behavior (ALU results, RAM contents, decoded opcodes,
# etc.) is only ever inferred from what comes back out on these pins.
# ---------------------------------------------------------------------------

PHYSICAL_PINS = (
    "ui_in",    # [7:0] input
    "uo_out",   # [7:0] output
    "uio_in",   # [7:0] input  (bit 0 = UART RX)
    "uio_out",  # [7:0] output (tied 0 in this design)
    "uio_oe",   # [7:0] output (tied 0 in this design)
    "ena",      # input
    "clk",      # input
    "rst_n",    # input
)


def _assert_pin_only_access(dut):
    """Sanity check: fail fast if the DUT handle we were given doesn't
    expose exactly tt_um_cpu8's pin list (e.g. if TOPLEVEL in the
    Makefile ever gets pointed at cpu8 or another internal module
    instead of the real top level)."""
    missing = [p for p in PHYSICAL_PINS if not hasattr(dut, p)]
    assert not missing, (
        f"DUT is missing expected physical pin(s) {missing} — is TOPLEVEL "
        f"in the Makefile still set to tt_um_cpu8?"
    )

# ---------------------------------------------------------------------------
# ISA / encoding helpers (must match decode8.sv)
# ---------------------------------------------------------------------------

OP_NOP = 0x0
OP_LDI = 0x1
OP_ADD = 0x2
OP_SUB = 0x3
OP_AND = 0x4
OP_OR = 0x5
OP_XOR = 0x6
OP_NOT = 0x7
OP_INC = 0x8
OP_DEC = 0x9
OP_LOAD = 0xA
OP_STORE = 0xB
OP_JMP = 0xC
OP_BZ = 0xD
OP_BNZ = 0xE
OP_HALT = 0xF

# Memory-mapped GPIO "addresses" used as the 4-bit operand of LOAD/STORE.
GPIO_OUT_ADDR = 0xC
GPIO_DIR_ADDR = 0xD
GPIO_IN_ADDR = 0xE


def enc(opcode, operand):
    """Pack a 4-bit opcode + 4-bit operand into one instruction byte."""
    assert 0 <= opcode <= 0xF
    assert 0 <= operand <= 0xF
    return ((opcode & 0xF) << 4) | (operand & 0xF)


# ---------------------------------------------------------------------------
# UART bit-bang helpers
# ---------------------------------------------------------------------------

CLK_FREQ = 60_000_000
BAUD_RATE = 115200
CLKS_PER_BIT = CLK_FREQ // BAUD_RATE  # matches localparam in uart_programmer8.sv


class UartProgrammer:
    """Bit-bangs the tiny AA/addr/data + 55(start) protocol onto uio_in[0]."""

    def __init__(self, dut):
        self.dut = dut

    def _drive_rx(self, bit):
        # Only uio_in[0] is used by the design (UART RX); keep the other
        # bits at 0 since nothing else in this design consumes them.
        self.dut.uio_in.value = bit & 0x1

    async def _send_bit(self, bit):
        self._drive_rx(bit)
        await ClockCycles(self.dut.clk, CLKS_PER_BIT)

    async def idle(self, cycles=CLKS_PER_BIT):
        self._drive_rx(1)
        await ClockCycles(self.dut.clk, cycles)

    async def send_byte(self, byte_val):
        # start bit
        await self._send_bit(0)
        # 8 data bits, LSB first
        for i in range(8):
            await self._send_bit((byte_val >> i) & 0x1)
        # stop bit
        await self._send_bit(1)

    async def program(self, addr, data):
        await self.send_byte(0xAA)
        await self.send_byte(addr)
        await self.send_byte(data)

    async def load_program(self, instructions, start_addr=0):
        for offset, instr in enumerate(instructions):
            await self.program(start_addr + offset, instr)

    async def start_cpu(self):
        await self.send_byte(0x55)


# ---------------------------------------------------------------------------
# Common setup
# ---------------------------------------------------------------------------

async def reset_dut(dut, clk_period_ns=10):
    _assert_pin_only_access(dut)
    cocotb.start_soon(Clock(dut.clk, clk_period_ns, units="ns").start())

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 1  # UART idle = high

    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)

    uart = UartProgrammer(dut)
    await uart.idle(CLKS_PER_BIT * 2)
    return uart


async def run_program(dut, uart, instructions, settle_cycles=20):
    """Load `instructions` starting at address 0 and start the CPU."""
    await uart.load_program(instructions)
    await uart.start_cpu()
    # First instruction executes on the clock edge start_cpu is sampled;
    # give the CPU a little headroom before the caller starts checking pc/
    # accumulator effects, on top of whatever ClockCycles the caller adds.
    await ClockCycles(dut.clk, settle_cycles)


async def wait_for_halt(dut, timeout_cycles=2000):
    """Poll uo_out stability isn't observable directly (no halted pin at
    top level), so instead just run for a bounded number of cycles — the
    caller knows how many instructions the program has."""
    await ClockCycles(dut.clk, timeout_cycles)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_reset_state(dut):
    """After reset (before any program/start), outputs should be idle/0."""
    await reset_dut(dut)

    assert dut.uo_out.value == 0, "uo_out should be 0 out of reset"
    assert dut.uio_out.value == 0, "uio_out is tied to 0 in this design"
    assert dut.uio_oe.value == 0, "uio_oe is tied to 0 in this design"


@cocotb.test()
async def test_ldi_add_store(dut):
    """LDI 5; ADD 3; STORE gpio_out; HALT  ->  uo_out == 8"""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 5),
        enc(OP_ADD, 3),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)

    assert dut.uo_out.value == 8, f"expected uo_out=8, got {int(dut.uo_out.value)}"


@cocotb.test()
async def test_alu_ops(dut):
    """Sweep each ALU opcode through LDI <a>; <OP> <b>; STORE C; HALT and
    check the result against a Python model of the ALU."""

    def alu_model(op, a, b):
        if op == OP_ADD:
            return (a + b) & 0xFF
        if op == OP_SUB:
            return (a - b) & 0xFF
        if op == OP_AND:
            return a & b
        if op == OP_OR:
            return a | b
        if op == OP_XOR:
            return a ^ b
        if op == OP_NOT:
            return (~a) & 0xFF
        if op == OP_INC:
            return (a + 1) & 0xFF
        if op == OP_DEC:
            return (a - 1) & 0xFF
        raise ValueError(op)

    cases = [
        (OP_ADD, 5, 3),
        (OP_SUB, 9, 4),
        (OP_SUB, 2, 5),   # underflow wrap
        (OP_AND, 0b1100, 0b1010),
        (OP_OR, 0b1100, 0b0011),
        (OP_XOR, 0b1111, 0b1010),
        (OP_NOT, 0b0000_1010, 0),  # operand ignored for NOT
        (OP_INC, 7, 0),            # operand ignored for INC
        (OP_DEC, 7, 0),            # operand ignored for DEC
    ]

    for op, a, b in cases:
        uart = await reset_dut(dut)
        program = [
            enc(OP_LDI, a & 0xF),
            enc(op, b & 0xF),
            enc(OP_STORE, GPIO_OUT_ADDR),
            enc(OP_HALT, 0),
        ]
        await run_program(dut, uart, program)
        await wait_for_halt(dut, timeout_cycles=50)

        expected = alu_model(op, a & 0xF, b & 0xF)
        got = int(dut.uo_out.value)
        assert got == expected, (
            f"op={op:#x} a={a} b={b}: expected {expected}, got {got}"
        )


@cocotb.test()
async def test_ram_load_store(dut):
    """STORE an accumulator value into RAM, clear the accumulator, LOAD it
    back, then push it out to GPIO to observe it."""
    uart = await reset_dut(dut)

    ram_addr = 0x5  # any operand other than 0xC/0xD/0xE routes to RAM
    program = [
        enc(OP_LDI, 9),
        enc(OP_STORE, ram_addr),   # RAM[5] = 9
        enc(OP_LDI, 0),            # clear accumulator
        enc(OP_LOAD, ram_addr),    # accumulator = RAM[5]
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)

    assert dut.uo_out.value == 9, f"expected uo_out=9, got {int(dut.uo_out.value)}"


@cocotb.test()
async def test_gpio_input_passthrough(dut):
    """Drive ui_in, LOAD E (gpio input register), STORE C (gpio output),
    HALT -> uo_out should mirror the value driven on ui_in."""
    uart = await reset_dut(dut)

    test_value = 0xA5
    dut.ui_in.value = test_value

    program = [
        enc(OP_LOAD, GPIO_IN_ADDR),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)

    assert dut.uo_out.value == test_value, (
        f"expected uo_out={test_value:#x}, got {int(dut.uo_out.value):#x}"
    )


@cocotb.test()
async def test_jmp(dut):
    """JMP over a poison instruction straight to the store."""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 1),
        enc(OP_JMP, 4),            # jump to address 4
        enc(OP_LDI, 0xF),          # (skipped) would corrupt accumulator
        enc(OP_HALT, 0),           # (skipped)
        enc(OP_STORE, GPIO_OUT_ADDR),  # address 4
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)

    assert dut.uo_out.value == 1, f"expected uo_out=1, got {int(dut.uo_out.value)}"


@cocotb.test()
async def test_branch_zero_taken(dut):
    """LDI 0; BZ -> taken, skips the poison LDI."""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 0),
        enc(OP_BZ, 4),
        enc(OP_LDI, 0xF),              # skipped
        enc(OP_HALT, 0),               # skipped
        enc(OP_STORE, GPIO_OUT_ADDR),  # address 4
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)

    assert dut.uo_out.value == 0, f"expected uo_out=0, got {int(dut.uo_out.value)}"


@cocotb.test()
async def test_branch_zero_not_taken(dut):
    """LDI 3; BZ -> not taken, falls through and executes the next LDI."""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 3),
        enc(OP_BZ, 5),              # not taken (acc != 0)
        enc(OP_LDI, 7),             # falls through here
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
        enc(OP_STORE, GPIO_OUT_ADDR),  # address 5, must NOT be reached
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)

    assert dut.uo_out.value == 7, f"expected uo_out=7, got {int(dut.uo_out.value)}"


@cocotb.test()
async def test_branch_not_zero(dut):
    """LDI 3; BNZ -> taken since acc != 0."""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 3),
        enc(OP_BNZ, 4),
        enc(OP_LDI, 0xF),              # skipped
        enc(OP_HALT, 0),               # skipped
        enc(OP_STORE, GPIO_OUT_ADDR),  # address 4
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)

    assert dut.uo_out.value == 3, f"expected uo_out=3, got {int(dut.uo_out.value)}"


@cocotb.test()
async def test_halt_freezes_accumulator(dut):
    """Once HALTed, further clock edges must not change uo_out even though
    the instruction memory still contains more (unexecuted) instructions."""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 4),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
        enc(OP_LDI, 0xF),  # must never execute
        enc(OP_STORE, GPIO_OUT_ADDR),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)
    assert dut.uo_out.value == 4

    # Run for a good while longer; value must stay frozen at 4.
    await ClockCycles(dut.clk, 200)
    assert dut.uo_out.value == 4, "CPU kept executing past HALT"


@cocotb.test()
async def test_ena_gating(dut):
    """While ena=0 the CPU must not run (state is held/cleared)."""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 6),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]
    await uart.load_program(program)

    dut.ena.value = 0
    await uart.start_cpu()
    await ClockCycles(dut.clk, 50)

    assert dut.uo_out.value == 0, "CPU should not run while ena=0"

    # Re-enable and restart; program should now execute normally.
    dut.ena.value = 1
    await ClockCycles(dut.clk, 5)
    await uart.start_cpu()
    await ClockCycles(dut.clk, 50)

    assert dut.uo_out.value == 6, "CPU should run once ena=1 and restarted"


@cocotb.test()
async def test_nop(dut):
    """NOP must not disturb the accumulator or anything else."""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 6),
        enc(OP_NOP, 0),
        enc(OP_NOP, 0),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)

    assert dut.uo_out.value == 6, f"expected uo_out=6, got {int(dut.uo_out.value)}"


@cocotb.test()
async def test_ram_address_sweep(dut):
    """Store a distinct value at every addressable RAM location (every
    4-bit operand except the GPIO-mapped 0xC/0xD/0xE) and read each back
    to make sure there's no address aliasing."""
    ram_addrs = [a for a in range(16) if a not in (GPIO_OUT_ADDR, GPIO_DIR_ADDR, GPIO_IN_ADDR)]

    for addr in ram_addrs:
        value = (addr * 7 + 3) & 0xFF & 0xF  # keep it representable via LDI (4-bit immediate)
        uart = await reset_dut(dut)
        program = [
            enc(OP_LDI, value),
            enc(OP_STORE, addr),
            enc(OP_LDI, 0),          # clear accumulator so the LOAD below is meaningful
            enc(OP_LOAD, addr),
            enc(OP_STORE, GPIO_OUT_ADDR),
            enc(OP_HALT, 0),
        ]
        await run_program(dut, uart, program)
        await wait_for_halt(dut, timeout_cycles=50)

        got = int(dut.uo_out.value)
        assert got == value, f"RAM addr {addr:#x}: expected {value}, got {got}"


@cocotb.test()
async def test_load_gpio_addr_reads_ram_not_gpio(dut):
    """LOAD only special-cases operand 0xE. STORE 0xC/0xD never touch RAM
    (they go to the GPIO output/direction registers instead), so LOAD
    0xC / LOAD 0xD read back RAM addresses that were never written -> 0.
    This documents real RTL behaviour, not an "intended" readback path.
    """
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 0xA),
        enc(OP_STORE, GPIO_OUT_ADDR),      # gpio output register = 0xA
        enc(OP_LDI, 0xB),
        enc(OP_STORE, GPIO_DIR_ADDR),      # gpio direction register = 0xB
        enc(OP_LDI, 0xF),                  # poison the accumulator
        enc(OP_LOAD, GPIO_OUT_ADDR),       # actually reads RAM[0xC] (never written) -> 0
        enc(OP_STORE, 0x1),                # RAM[1] = 0
        enc(OP_LDI, 0xF),                  # poison again
        enc(OP_LOAD, GPIO_DIR_ADDR),       # actually reads RAM[0xD] (never written) -> 0
        enc(OP_STORE, 0x2),                # RAM[2] = 0
        enc(OP_LDI, 0),
        enc(OP_LOAD, 0x1),
        enc(OP_STORE, GPIO_OUT_ADDR),      # push RAM[1] out so we can observe it
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=80)

    assert dut.uo_out.value == 0, (
        f"LOAD 0xC should read RAM (never written -> 0), got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_gpio_direction_register_write_is_isolated(dut):
    """STORE 0xD (direction register) must not corrupt the GPIO output
    register / uo_out, and vice versa."""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 4),
        enc(OP_STORE, GPIO_OUT_ADDR),   # gpio_out = 4
        enc(OP_LDI, 0xF),
        enc(OP_STORE, GPIO_DIR_ADDR),   # direction reg = 0xF, must not touch gpio_out
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)

    assert dut.uo_out.value == 4, (
        f"STORE to direction register altered uo_out: got {int(dut.uo_out.value)}"
    )
    # gpio_oe from cpu8 is left unconnected at the tt_um top level, so the
    # direction register's effect isn't independently observable from the
    # chip pins; we can only confirm it doesn't corrupt gpio_out.


@cocotb.test()
async def test_gpio_input_tracks_live_changes(dut):
    """GPIO input read is combinational/live (gpio8: read_data = gpio_in
    when re & address==INPUT); changing ui_in between two LOAD/STORE
    passes should produce two different observed outputs."""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LOAD, GPIO_IN_ADDR),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    dut.ui_in.value = 0x3C
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)
    assert dut.uo_out.value == 0x3C

    dut.ui_in.value = 0xC3
    uart = await reset_dut(dut)
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)
    assert dut.uo_out.value == 0xC3


@cocotb.test()
async def test_backward_branch_loop(dut):
    """A real looping program: countdown from 3 to 0 using BNZ to branch
    backwards, STOREing the counter to GPIO on every pass so the loop
    body provably executes more than once before HALTing."""
    uart = await reset_dut(dut)

    # addr0: LDI 3
    # addr1: STORE C      <-- loop target
    # addr2: DEC
    # addr3: BNZ 1        (loop while acc != 0)
    # addr4: STORE C      (final value, 0, once the loop exits)
    # addr5: HALT
    program = [
        enc(OP_LDI, 3),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_DEC, 0),
        enc(OP_BNZ, 1),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]
    # Loop runs 3 times round-trip (3->2->1->0), give it plenty of margin.
    await run_program(dut, uart, program, settle_cycles=20)
    await wait_for_halt(dut, timeout_cycles=200)

    assert dut.uo_out.value == 0, (
        f"expected loop to count down to 0, got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_uart_garbage_bytes_are_ignored(dut):
    """Bytes that are neither 0xAA (program) nor 0x55 (start) while the
    command state machine is idle must be silently ignored, and must not
    leave the programmer wedged for subsequent, valid commands."""
    uart = await reset_dut(dut)

    for junk in (0x00, 0x01, 0xFF, 0x7E):
        await uart.send_byte(junk)

    program = [
        enc(OP_LDI, 2),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)

    assert dut.uo_out.value == 2, (
        f"garbage UART bytes should be ignored; got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_uart_reprogram_overwrites_instruction_memory(dut):
    """Program A, run it, then reprogram the same addresses with program
    B and confirm the CPU now executes the new program, not the old one."""
    uart = await reset_dut(dut)

    program_a = [
        enc(OP_LDI, 1),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program_a)
    await wait_for_halt(dut, timeout_cycles=50)
    assert dut.uo_out.value == 1

    program_b = [
        enc(OP_LDI, 9),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]
    await uart.load_program(program_b)  # overwrite addresses 0..2
    await uart.start_cpu()
    await ClockCycles(dut.clk, 30)

    assert dut.uo_out.value == 9, (
        f"expected reprogrammed value 9, got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_start_cpu_restarts_mid_execution(dut):
    """Sending 0x55 again while the CPU is mid-program (not yet halted)
    must reset pc back to 0 and clear the accumulator, per cpu_top8.sv's
    `else if (start_cpu)` branch taking priority every cycle it's sampled."""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 5),
        enc(OP_NOP, 0),
        enc(OP_NOP, 0),
        enc(OP_NOP, 0),
        enc(OP_STORE, GPIO_OUT_ADDR),   # would set uo_out=5 if left alone
        enc(OP_HALT, 0),
    ]
    await uart.load_program(program)
    await uart.start_cpu()

    # Interrupt after LDI has executed but before the STORE.
    await ClockCycles(dut.clk, 2)
    await uart.start_cpu()  # restart: pc<-0, accumulator<-0

    await ClockCycles(dut.clk, 30)

    assert dut.uo_out.value == 0, (
        "restart mid-program should re-run from pc=0 with a cleared "
        f"accumulator instead of finishing the interrupted run; got "
        f"{int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_start_cpu_restarts_after_halt(dut):
    """0x55 sent after HALT must clear `halted` and re-run from address 0."""
    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 7),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]
    await run_program(dut, uart, program)
    await wait_for_halt(dut, timeout_cycles=50)
    assert dut.uo_out.value == 7

    await uart.start_cpu()
    await ClockCycles(dut.clk, 30)

    assert dut.uo_out.value == 7, "restart after HALT should re-run the same program"


@cocotb.test()
async def test_random_alu_immediate_program(dut):
    """Randomized regression: chain several LDI/ALU ops and check the final
    accumulator value against a software model."""
    random.seed(1)

    ops = [OP_ADD, OP_SUB, OP_AND, OP_OR, OP_XOR]

    for trial in range(5):
        uart = await reset_dut(dut)

        acc = random.randint(0, 15)
        program = [enc(OP_LDI, acc)]

        model = acc
        for _ in range(4):
            op = random.choice(ops)
            b = random.randint(0, 15)
            program.append(enc(op, b))

            if op == OP_ADD:
                model = (model + b) & 0xFF
            elif op == OP_SUB:
                model = (model - b) & 0xFF
            elif op == OP_AND:
                model = model & b
            elif op == OP_OR:
                model = model | b
            elif op == OP_XOR:
                model = model ^ b

        program.append(enc(OP_STORE, GPIO_OUT_ADDR))
        program.append(enc(OP_HALT, 0))

        await run_program(dut, uart, program)
        await wait_for_halt(dut, timeout_cycles=80)

        got = int(dut.uo_out.value)
        assert got == model, (
            f"trial {trial}: expected {model}, got {got} "
            f"(program={[hex(i) for i in program]})"
        )
