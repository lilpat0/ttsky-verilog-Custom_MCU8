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
clock cycles, so the testbench clock period itself is arbitrary.

Run with Icarus Verilog, from a directory containing all the .sv files
and this test.py + the accompanying Makefile:

    make
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles


# ---------------------------------------------------------------------------
# Physical-pin-only access
# ---------------------------------------------------------------------------

PHYSICAL_PINS = (
    "ui_in",
    "uo_out",
    "uio_in",
    "uio_out",
    "uio_oe",
    "ena",
    "clk",
    "rst_n",
)


def _assert_pin_only_access(dut):
    """Fail fast if the DUT is not the expected Tiny Tapeout wrapper."""

    missing = [p for p in PHYSICAL_PINS if not hasattr(dut, p)]

    assert not missing, (
        f"DUT is missing expected physical pin(s) {missing} — "
        f"is TOPLEVEL in the Makefile still set to tt_um_cpu8?"
    )


# ---------------------------------------------------------------------------
# ISA / encoding helpers
# ---------------------------------------------------------------------------

OP_NOP   = 0x0
OP_LDI   = 0x1
OP_ADD   = 0x2
OP_SUB   = 0x3
OP_AND   = 0x4
OP_OR    = 0x5
OP_XOR   = 0x6
OP_NOT   = 0x7
OP_INC   = 0x8
OP_DEC   = 0x9
OP_LOAD  = 0xA
OP_STORE = 0xB
OP_JMP   = 0xC
OP_BZ    = 0xD
OP_BNZ   = 0xE
OP_HALT  = 0xF


# ---------------------------------------------------------------------------
# Memory-mapped GPIO addresses
# ---------------------------------------------------------------------------

GPIO_OUT_ADDR = 0xC
UIO_ADDR      = 0xD
GPIO_IN_ADDR  = 0xE


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

CLKS_PER_BIT = CLK_FREQ // BAUD_RATE
CLKS_PER_BYTE = CLKS_PER_BIT * 10


class UartProgrammer:
    """
    Bit-bangs the AA/addr/data + 55 protocol onto uio_in[0].

    IMPORTANT:

        uio_in[0]   = UART RX
        uio_in[3:1] = fixed general-purpose inputs
        uio_in[7:4] = unused inputs

    Bits [7:1] are NEVER modified by UART transmission.
    """

    def __init__(self, dut):
        self.dut = dut

        # Capture all non-UART bits when the programmer is created.
        #
        # bit 0 is deliberately excluded because UART owns it.
        self.fixed_uio_bits = int(self.dut.uio_in.value) & 0xFE

    def set_general_inputs(self, bits3to1):
        """
        Set uio_in[3:1] and preserve them for all future UART activity.

        bits3to1 is a 3-bit value corresponding to uio_in[3:1].
        """

        assert 0 <= bits3to1 <= 0x7

        self.fixed_uio_bits = (
            (self.fixed_uio_bits & 0xF1)
            | ((bits3to1 & 0x7) << 1)
        )

        # UART idle high.
        self.dut.uio_in.value = self.fixed_uio_bits | 0x01

    def _drive_rx(self, bit):
        """
        Drive ONLY uio_in[0].

        Bits [7:1] come from fixed_uio_bits and are never overwritten.
        """

        self.dut.uio_in.value = (
            self.fixed_uio_bits
            | (bit & 0x01)
        )

    async def _send_bit(self, bit):
        """Drive one UART bit for exactly CLKS_PER_BIT clock cycles."""

        self._drive_rx(bit)
        await ClockCycles(
            self.dut.clk,
            CLKS_PER_BIT
        )

    async def idle(self, cycles=CLKS_PER_BIT):
        """UART idle state is logic 1."""

        self._drive_rx(1)

        await ClockCycles(
            self.dut.clk,
            cycles
        )

    async def send_byte(self, byte_val):
        """
        Send one UART byte:

            start bit = 0
            8 data bits, LSB first
            stop bit = 1
        """

        await self._send_bit(0)

        for i in range(8):
            await self._send_bit(
                (byte_val >> i) & 0x1
            )

        await self._send_bit(1)

    async def program(self, addr, data):
        """
        Send:

            0xAA <address> <data>
        """

        await self.send_byte(0xAA)
        await self.send_byte(addr)
        await self.send_byte(data)

    async def load_program(self, instructions, start_addr=0):
        """Program a sequence of instructions into instruction memory."""

        for offset, instr in enumerate(instructions):
            await self.program(
                start_addr + offset,
                instr
            )

    async def start_cpu(self):
        """Send the 0x55 CPU-start command."""

        await self.send_byte(0x55)


# ---------------------------------------------------------------------------
# Common setup
# ---------------------------------------------------------------------------

async def reset_dut(dut, clk_period_ns=10):
    """
    Reset the DUT and start the clock.

    uio_in starts with UART RX idle-high.
    """

    _assert_pin_only_access(dut)

    cocotb.start_soon(
        Clock(
            dut.clk,
            clk_period_ns,
            units="ns"
        ).start()
    )

    dut.ena.value = 1
    dut.ui_in.value = 0

    # UART RX idle-high.
    dut.uio_in.value = 0x01

    dut.rst_n.value = 0

    await ClockCycles(
        dut.clk,
        10
    )

    dut.rst_n.value = 1

    await ClockCycles(
        dut.clk,
        10
    )

    uart = UartProgrammer(dut)

    await uart.idle(
        CLKS_PER_BIT * 2
    )

    return uart


async def run_program(
    dut,
    uart,
    instructions,
    settle_cycles=20
):
    """
    Load instructions starting at address 0 and start the CPU.
    """

    await uart.load_program(
        instructions
    )

    await uart.start_cpu()

    await ClockCycles(
        dut.clk,
        settle_cycles
    )


async def wait_for_halt(
    dut,
    timeout_cycles=2000
):
    """
    HALT is not directly exposed as a physical pin.

    Therefore tests simply wait long enough for the known program
    to complete.
    """

    await ClockCycles(
        dut.clk,
        timeout_cycles
    )


def set_uio_general_inputs(dut, bits3to1):
    """
    Set uio_in[3:1] while keeping UART RX uio_in[0] high.

    bits3to1:
        3-bit value corresponding to uio_in[3:1].
    """

    assert 0 <= bits3to1 <= 0x7

    current = int(dut.uio_in.value)

    # Preserve bits [7:4], replace [3:1], force UART RX high.
    dut.uio_in.value = (
        (current & 0xF0)
        | ((bits3to1 & 0x7) << 1)
        | 0x01
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_reset_state(dut):
    """
    After reset, before any program/start:

        uo_out = 0
        uio_oe = 0xF0
        uio_out[7:4] = 0
    """

    await reset_dut(dut)

    assert dut.uo_out.value == 0, (
        "uo_out should be 0 out of reset"
    )

    assert dut.uio_oe.value == 0xF0, (
        "uio_oe should be 0xF0"
    )

    assert (int(dut.uio_out.value) >> 4) == 0, (
        "uio general outputs should be 0 out of reset"
    )


@cocotb.test()
async def test_ldi_add_store(dut):
    """
    LDI 5
    ADD 3
    STORE GPIO
    HALT

    Expected:
        uo_out = 8
    """

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 5),
        enc(OP_ADD, 3),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 8, (
        f"expected uo_out=8, "
        f"got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_alu_ops(dut):
    """Sweep each ALU opcode through a simple program."""

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
        (OP_SUB, 2, 5),
        (OP_AND, 0b1100, 0b1010),
        (OP_OR, 0b1100, 0b0011),
        (OP_XOR, 0b1111, 0b1010),
        (OP_NOT, 0b0000_1010, 0),
        (OP_INC, 7, 0),
        (OP_DEC, 7, 0),
    ]

    for op, a, b in cases:

        uart = await reset_dut(dut)

        program = [
            enc(OP_LDI, a & 0xF),
            enc(op, b & 0xF),
            enc(OP_STORE, GPIO_OUT_ADDR),
            enc(OP_HALT, 0),
        ]

        await run_program(
            dut,
            uart,
            program
        )

        await wait_for_halt(
            dut,
            timeout_cycles=50
        )

        expected = alu_model(
            op,
            a & 0xF,
            b & 0xF
        )

        got = int(
            dut.uo_out.value
        )

        assert got == expected, (
            f"op={op:#x} a={a} b={b}: "
            f"expected {expected}, got {got}"
        )


@cocotb.test()
async def test_ram_load_store(dut):
    """STORE to RAM, LOAD from RAM, output through GPIO."""

    uart = await reset_dut(dut)

    ram_addr = 0x5

    program = [
        enc(OP_LDI, 9),
        enc(OP_STORE, ram_addr),
        enc(OP_LDI, 0),
        enc(OP_LOAD, ram_addr),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 9, (
        f"expected uo_out=9, "
        f"got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_gpio_input_passthrough(dut):
    """LOAD GPIO input and output it through GPIO output."""

    uart = await reset_dut(dut)

    test_value = 0xA5

    dut.ui_in.value = test_value

    program = [
        enc(OP_LOAD, GPIO_IN_ADDR),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == test_value, (
        f"expected uo_out={test_value:#x}, "
        f"got {int(dut.uo_out.value):#x}"
    )


@cocotb.test()
async def test_jmp(dut):
    """JMP over a poison instruction."""

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 1),
        enc(OP_JMP, 4),
        enc(OP_LDI, 0xF),
        enc(OP_HALT, 0),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 1, (
        f"expected uo_out=1, "
        f"got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_branch_zero_taken(dut):
    """BZ taken."""

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 0),
        enc(OP_BZ, 4),
        enc(OP_LDI, 0xF),
        enc(OP_HALT, 0),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 0, (
        f"expected uo_out=0, "
        f"got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_branch_zero_not_taken(dut):
    """BZ not taken."""

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 3),
        enc(OP_BZ, 5),
        enc(OP_LDI, 7),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
        enc(OP_STORE, GPIO_OUT_ADDR),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 7, (
        f"expected uo_out=7, "
        f"got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_branch_not_zero(dut):
    """BNZ taken."""

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 3),
        enc(OP_BNZ, 4),
        enc(OP_LDI, 0xF),
        enc(OP_HALT, 0),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 3, (
        f"expected uo_out=3, "
        f"got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_halt_freezes_accumulator(dut):
    """HALT must stop further execution."""

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 4),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
        enc(OP_LDI, 0xF),
        enc(OP_STORE, GPIO_OUT_ADDR),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 4

    await ClockCycles(
        dut.clk,
        200
    )

    assert dut.uo_out.value == 4, (
        "CPU kept executing past HALT"
    )


@cocotb.test()
async def test_ena_gating(dut):
    """CPU must not run while ena=0."""

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 6),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await uart.load_program(
        program
    )

    dut.ena.value = 0

    await uart.start_cpu()

    await ClockCycles(
        dut.clk,
        50
    )

    assert dut.uo_out.value == 0, (
        "CPU should not run while ena=0"
    )

    dut.ena.value = 1

    await ClockCycles(
        dut.clk,
        5
    )

    await uart.start_cpu()

    await ClockCycles(
        dut.clk,
        50
    )

    assert dut.uo_out.value == 6, (
        "CPU should run once ena=1 and restarted"
    )


@cocotb.test()
async def test_nop(dut):
    """NOP must not disturb the accumulator."""

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 6),
        enc(OP_NOP, 0),
        enc(OP_NOP, 0),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 6, (
        f"expected uo_out=6, "
        f"got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_ram_address_sweep(dut):
    """Store and load every normal RAM address."""

    ram_addrs = [
        a
        for a in range(16)
        if a not in (
            GPIO_OUT_ADDR,
            UIO_ADDR,
            GPIO_IN_ADDR
        )
    ]

    for addr in ram_addrs:

        value = (
            (addr * 7 + 3)
            & 0xFF
            & 0xF
        )

        uart = await reset_dut(dut)

        program = [
            enc(OP_LDI, value),
            enc(OP_STORE, addr),
            enc(OP_LDI, 0),
            enc(OP_LOAD, addr),
            enc(OP_STORE, GPIO_OUT_ADDR),
            enc(OP_HALT, 0),
        ]

        await run_program(
            dut,
            uart,
            program
        )

        await wait_for_halt(
            dut,
            timeout_cycles=50
        )

        got = int(
            dut.uo_out.value
        )

        assert got == value, (
            f"RAM addr {addr:#x}: "
            f"expected {value}, got {got}"
        )


@cocotb.test()
async def test_load_gpio_addr_reads_ram_not_gpio(dut):
    """
    LOAD 0xC reads RAM[0xC], not the GPIO output register.
    """

    def make_program(gpio_value):
        return [
            enc(OP_LDI, gpio_value),
            enc(OP_STORE, GPIO_OUT_ADDR),

            enc(OP_LDI, 0xF),

            enc(OP_LOAD, GPIO_OUT_ADDR),

            enc(OP_STORE, 0x1),

            enc(OP_LDI, 0),
            enc(OP_LOAD, 0x1),

            enc(OP_STORE, GPIO_OUT_ADDR),
            enc(OP_HALT, 0),
        ]

    uart = await reset_dut(dut)

    await run_program(
        dut,
        uart,
        make_program(0x5)
    )

    await wait_for_halt(
        dut,
        timeout_cycles=80
    )

    first_result = dut.uo_out.value

    uart = await reset_dut(dut)

    await run_program(
        dut,
        uart,
        make_program(0xA)
    )

    await wait_for_halt(
        dut,
        timeout_cycles=80
    )

    second_result = dut.uo_out.value

    assert first_result == second_result, (
        "LOAD 0xC should read a fixed RAM location, independent "
        "of GPIO output; "
        f"got {first_result} vs {second_result}"
    )


@cocotb.test()
async def test_uio_store_isolated_from_gpio_out(dut):
    """STORE 0xD must not corrupt GPIO output."""

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 4),
        enc(OP_STORE, GPIO_OUT_ADDR),

        enc(OP_LDI, 0xF),
        enc(OP_STORE, UIO_ADDR),

        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 4, (
        "STORE to UIO altered uo_out: "
        f"got {int(dut.uo_out.value)}"
    )

    assert (int(dut.uio_out.value) >> 4) == 0xF, (
        "STORE 0xD should drive uio_out[7:4]=0xF, "
        f"got {int(dut.uio_out.value):#04x}"
    )


@cocotb.test()
async def test_uio_fixed_io(dut):
    """
    Verify the fixed UIO direction:

        uio[7:4] = outputs
        uio[3:1] = general inputs
        uio[0]   = UART RX

    uio_oe must always equal 0xF0.

    IMPORTANT:
    The general input value is deliberately applied AFTER UART programming.
    This guarantees that the UART activity cannot accidentally overwrite the
    value being tested.
    """

    uart = await reset_dut(dut)

    # ---------------------------------------------------------------
    # Fixed direction
    # ---------------------------------------------------------------

    assert dut.uio_oe.value == 0xF0, (
        f"expected uio_oe=0xF0, "
        f"got {int(dut.uio_oe.value):#04x}"
    )

    # ---------------------------------------------------------------
    # STORE 0xD -> uio_out[7:4]
    # ---------------------------------------------------------------

    program = [
        enc(OP_LDI, 0xB),
        enc(OP_STORE, UIO_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert (int(dut.uio_out.value) >> 4) == 0xB, (
        "expected uio_out[7:4]=0xB, "
        f"got {int(dut.uio_out.value):#04x}"
    )

    # ---------------------------------------------------------------
    # LOAD 0xD -> uio_in[3:1]
    # ---------------------------------------------------------------

    uart = await reset_dut(dut)

    program = [
        enc(OP_LOAD, UIO_ADDR),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    # ---------------------------------------------------------------
    # IMPORTANT FIX:
    #
    # Program the instruction memory FIRST.
    #
    # Then set uio_in[3:1].
    #
    # Then explicitly restore the same value after programming and
    # immediately before sending 0x55.
    # ---------------------------------------------------------------

    await uart.load_program(
        program
    )

    set_uio_general_inputs(
        dut,
        0b101
    )

    # Verify the actual physical input pins before starting the CPU.
    actual_uio = int(
        dut.uio_in.value
    )

    assert ((actual_uio >> 1) & 0x7) == 0b101, (
        "testbench failed to drive uio_in[3:1]=101 before CPU start; "
        f"uio_in={actual_uio:#04x}"
    )

    assert (actual_uio & 0x1) == 1, (
        "UART RX must remain idle-high before CPU start"
    )

    # Start CPU only AFTER the UIO input has been established.
    await uart.start_cpu()

    await ClockCycles(
        dut.clk,
        20
    )

    # The UART helper preserves bits [7:1], but explicitly restore the
    # expected value once more before the CPU gets enough cycles to
    # execute the LOAD instruction.
    set_uio_general_inputs(
        dut,
        0b101
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    got = int(
        dut.uo_out.value
    )

    assert got == 0b101, (
        "expected uo_out=0b101 from uio_in[3:1], "
        f"got {got:#04x}; "
        f"uio_in={int(dut.uio_in.value):#04x}"
    )


@cocotb.test()
async def test_gpio_input_tracks_live_changes(dut):
    """GPIO input must be live/combinational."""

    uart = await reset_dut(dut)

    program = [
        enc(OP_LOAD, GPIO_IN_ADDR),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    dut.ui_in.value = 0x3C

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 0x3C

    uart = await reset_dut(dut)

    dut.ui_in.value = 0xC3

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 0xC3


@cocotb.test()
async def test_backward_branch_loop(dut):
    """Countdown loop."""

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 3),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_DEC, 0),
        enc(OP_BNZ, 1),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program,
        settle_cycles=20
    )

    await wait_for_halt(
        dut,
        timeout_cycles=200
    )

    assert dut.uo_out.value == 0, (
        "expected loop to count down to 0, "
        f"got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_uart_garbage_bytes_are_ignored(dut):
    """Garbage UART bytes must be ignored."""

    uart = await reset_dut(dut)

    for junk in (
        0x00,
        0x01,
        0xFF,
        0x7E
    ):
        await uart.send_byte(junk)

    program = [
        enc(OP_LDI, 2),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 2, (
        "garbage UART bytes should be ignored; "
        f"got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_uart_reprogram_overwrites_instruction_memory(dut):
    """Program A, then overwrite it with Program B."""

    uart = await reset_dut(dut)

    program_a = [
        enc(OP_LDI, 1),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program_a
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 1

    program_b = [
        enc(OP_LDI, 9),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await uart.load_program(
        program_b
    )

    await uart.start_cpu()

    await ClockCycles(
        dut.clk,
        30
    )

    assert dut.uo_out.value == 9, (
        f"expected reprogrammed value 9, "
        f"got {int(dut.uo_out.value)}"
    )


# ---------------------------------------------------------------------------
# Long-running interruptible program
# ---------------------------------------------------------------------------

INNER_LOOP_NOP_COUNT = 24


def build_interruptible_loop_program(counter_ram_addr=0x5):

    program = []

    def addr():
        return len(program)

    program.append(
        enc(OP_LDI, 15)
    )

    program.append(
        enc(OP_STORE, counter_ram_addr)
    )

    outer_start = addr()

    program.append(
        enc(OP_LOAD, counter_ram_addr)
    )

    program.append(
        enc(OP_STORE, GPIO_OUT_ADDR)
    )

    program.append(
        enc(OP_LDI, 15)
    )

    inner_start = addr()

    program.append(
        enc(OP_DEC, 0)
    )

    for _ in range(INNER_LOOP_NOP_COUNT):
        program.append(
            enc(OP_NOP, 0)
        )

    program.append(
        enc(OP_BNZ, inner_start)
    )

    program.append(
        enc(OP_LOAD, counter_ram_addr)
    )

    program.append(
        enc(OP_DEC, 0)
    )

    program.append(
        enc(OP_STORE, counter_ram_addr)
    )

    program.append(
        enc(OP_BNZ, outer_start)
    )

    program.append(
        enc(OP_STORE, GPIO_OUT_ADDR)
    )

    program.append(
        enc(OP_HALT, 0)
    )

    return program, outer_start


@cocotb.test()
async def test_start_cpu_restarts_mid_execution(dut):
    """
    Sending 0x55 again while CPU is still running must restart it.
    """

    uart = await reset_dut(dut)

    program, _ = build_interruptible_loop_program()

    await uart.load_program(
        program
    )

    await uart.start_cpu()

    await ClockCycles(
        dut.clk,
        2
    )

    await uart.start_cpu()

    await ClockCycles(
        dut.clk,
        10
    )

    assert dut.uo_out.value == 15, (
        "restart mid-program should re-run from pc=0 and re-write "
        "the outer counter's initial value (15) to GPIO; "
        f"got {int(dut.uo_out.value)}"
    )


@cocotb.test()
async def test_start_cpu_restarts_after_halt(dut):
    """0x55 after HALT must restart execution."""

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 7),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await run_program(
        dut,
        uart,
        program
    )

    await wait_for_halt(
        dut,
        timeout_cycles=50
    )

    assert dut.uo_out.value == 7

    await uart.start_cpu()

    await ClockCycles(
        dut.clk,
        30
    )

    assert dut.uo_out.value == 7, (
        "restart after HALT should re-run the same program"
    )


@cocotb.test()
async def test_random_alu_immediate_program(dut):
    """Randomized ALU regression."""

    random.seed(1)

    ops = [
        OP_ADD,
        OP_SUB,
        OP_AND,
        OP_OR,
        OP_XOR,
    ]

    for trial in range(5):

        uart = await reset_dut(dut)

        acc = random.randint(
            0,
            15
        )

        program = [
            enc(
                OP_LDI,
                acc
            )
        ]

        model = acc

        for _ in range(4):

            op = random.choice(
                ops
            )

            b = random.randint(
                0,
                15
            )

            program.append(
                enc(
                    op,
                    b
                )
            )

            if op == OP_ADD:
                model = (
                    model + b
                ) & 0xFF

            elif op == OP_SUB:
                model = (
                    model - b
                ) & 0xFF

            elif op == OP_AND:
                model = (
                    model & b
                )

            elif op == OP_OR:
                model = (
                    model | b
                )

            elif op == OP_XOR:
                model = (
                    model ^ b
                )

        program.append(
            enc(
                OP_STORE,
                GPIO_OUT_ADDR
            )
        )

        program.append(
            enc(
                OP_HALT,
                0
            )
        )

        await run_program(
            dut,
            uart,
            program
        )

        await wait_for_halt(
            dut,
            timeout_cycles=80
        )

        got = int(
            dut.uo_out.value
        )

        assert got == model, (
            f"trial {trial}: "
            f"expected {model}, got {got} "
            f"(program={[hex(i) for i in program]})"
        )
