"""
Cocotb testbench for tt_um_cpu8

Physical-pin-only testbench.

UART programming protocol:

    0xAA <addr> <data>   -> write instruction memory
    0x55                 -> start/restart CPU

Physical UIO mapping:

    uio_in[0]   = UART RX
    uio_in[3:1] = 3 general-purpose inputs
    uio_in[7:4] = unused inputs

    uio_out[7:4] = general-purpose outputs
    uio_out[3:0] = 0

    uio_oe = 8'hF0
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles


# ============================================================================
# PHYSICAL PINS
# ============================================================================

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
    missing = [p for p in PHYSICAL_PINS if not hasattr(dut, p)]

    assert not missing, (
        f"DUT is missing expected physical pin(s) {missing} — "
        f"is TOPLEVEL in the Makefile still set to tt_um_cpu8?"
    )


# ============================================================================
# ISA
# ============================================================================

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


# ============================================================================
# MEMORY-MAPPED ADDRESSES
# ============================================================================

GPIO_OUT_ADDR = 0xC
UIO_ADDR      = 0xD
GPIO_IN_ADDR  = 0xE


def enc(opcode, operand):
    assert 0 <= opcode <= 0xF
    assert 0 <= operand <= 0xF

    return ((opcode & 0xF) << 4) | (operand & 0xF)


# ============================================================================
# UART
# ============================================================================

CLK_FREQ = 60_000_000
BAUD_RATE = 115200

CLKS_PER_BIT = CLK_FREQ // BAUD_RATE
CLKS_PER_BYTE = CLKS_PER_BIT * 10


class UartProgrammer:
    """
    Bit-bangs UART RX on uio_in[0].

    uio_in[0]   = UART RX
    uio_in[3:1] = general-purpose inputs

    UART operations preserve uio_in[7:1].
    """

    def __init__(self, dut):
        self.dut = dut

    def _drive_rx(self, bit):
        """
        Change ONLY uio_in[0].

        Preserve uio_in[7:1].
        """

        current = int(self.dut.uio_in.value)

        new_value = (current & 0xFE) | (bit & 0x01)

        self.dut.uio_in.value = new_value

    async def _send_bit(self, bit):
        self._drive_rx(bit)

        await ClockCycles(
            self.dut.clk,
            CLKS_PER_BIT
        )

    async def idle(self, cycles=CLKS_PER_BIT):
        """
        Drive UART RX idle-high while preserving uio_in[7:1].
        """

        self._drive_rx(1)

        await ClockCycles(
            self.dut.clk,
            cycles
        )

    async def send_byte(self, byte_val):
        """
        UART:

            start = 0
            8 data bits, LSB first
            stop = 1
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

        for offset, instr in enumerate(instructions):

            await self.program(
                start_addr + offset,
                instr
            )

    async def start_cpu(self):
        """
        Send the 0x55 start command.
        """

        await self.send_byte(0x55)


# ============================================================================
# UIO HELPERS
# ============================================================================

def drive_uio_general_inputs(dut, bits3to1):
    """
    Drive the three general-purpose UIO inputs.

    Mapping:

        uio_in[3:1] = bits3to1
        uio_in[0]   = UART idle-high

    Bits [7:4] remain zero.

    Example:

        bits3to1 = 101

        uio_in = 0000_1011
                       ^^^
                       101
    """

    assert 0 <= bits3to1 <= 0x7

    value = ((bits3to1 & 0x7) << 1) | 0x01

    # Drive the entire physical input bus.
    dut.uio_in.value = value


async def set_uio_general_inputs(dut, bits3to1):
    """
    Drive UIO inputs and allow the new value to propagate.

    This deliberately does NOT assert the value immediately after
    assignment.  The physical UIO bus is treated as an input pin bus,
    so we give the simulator one clock edge to settle.
    """

    drive_uio_general_inputs(
        dut,
        bits3to1
    )

    await ClockCycles(
        dut.clk,
        1
    )


# ============================================================================
# RESET
# ============================================================================

async def reset_dut(dut, clk_period_ns=10):
    """
    Reset the DUT and start the clock.

    uio_in is initialized to:

        uio_in[0] = 1
        uio_in[7:1] = 0
    """

    _assert_pin_only_access(dut)

    cocotb.start_soon(
        Clock(
            dut.clk,
            clk_period_ns,
            unit="ns",
        ).start()
    )

    dut.ena.value = 1
    dut.ui_in.value = 0

    # UART idle-high.
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

    # Restore UART idle while keeping all general inputs at zero.
    dut.uio_in.value = 0x01

    await ClockCycles(
        dut.clk,
        2
    )

    return uart


# ============================================================================
# PROGRAM RUNNER
# ============================================================================

async def run_program(
    dut,
    uart,
    instructions,
    settle_cycles=20,
):
    """
    Load program at address 0 and start CPU.
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
    timeout_cycles=2000,
):
    """
    HALT is not externally visible.

    Wait long enough for the known test program to finish.
    """

    await ClockCycles(
        dut.clk,
        timeout_cycles
    )


# ============================================================================
# RESET TEST
# ============================================================================

@cocotb.test()
async def test_reset_state(dut):

    await reset_dut(dut)

    assert dut.uo_out.value == 0, (
        "uo_out should be 0 out of reset"
    )

    assert dut.uio_oe.value == 0xF0, (
        "uio_oe should equal 0xF0; "
        f"got {int(dut.uio_oe.value):#04x}"
    )

    assert (int(dut.uio_out.value) >> 4) == 0, (
        "uio_out[7:4] should be zero out of reset"
    )


# ============================================================================
# LDI / ADD / STORE
# ============================================================================

@cocotb.test()
async def test_ldi_add_store(dut):

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
        50
    )

    assert dut.uo_out.value == 8, (
        f"expected uo_out=8, "
        f"got {int(dut.uo_out.value)}"
    )


# ============================================================================
# ALU
# ============================================================================

@cocotb.test()
async def test_alu_ops(dut):

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
        (OP_NOT, 0b1010, 0),
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
            50
        )

        expected = alu_model(
            op,
            a & 0xF,
            b & 0xF
        )

        got = int(dut.uo_out.value)

        assert got == expected, (
            f"op={op:#x} a={a} b={b}: "
            f"expected {expected}, got {got}"
        )


# ============================================================================
# RAM
# ============================================================================

@cocotb.test()
async def test_ram_load_store(dut):

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
        50
    )

    assert dut.uo_out.value == 9


# ============================================================================
# GPIO INPUT
# ============================================================================

@cocotb.test()
async def test_gpio_input_passthrough(dut):

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
        50
    )

    assert dut.uo_out.value == test_value


# ============================================================================
# JMP
# ============================================================================

@cocotb.test()
async def test_jmp(dut):

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
        50
    )

    assert dut.uo_out.value == 1


# ============================================================================
# BZ TAKEN
# ============================================================================

@cocotb.test()
async def test_branch_zero_taken(dut):

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
        50
    )

    assert dut.uo_out.value == 0


# ============================================================================
# BZ NOT TAKEN
# ============================================================================

@cocotb.test()
async def test_branch_zero_not_taken(dut):

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
        50
    )

    assert dut.uo_out.value == 7


# ============================================================================
# BNZ
# ============================================================================

@cocotb.test()
async def test_branch_not_zero(dut):

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
        50
    )

    assert dut.uo_out.value == 3


# ============================================================================
# HALT
# ============================================================================

@cocotb.test()
async def test_halt_freezes_accumulator(dut):

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
        50
    )

    assert dut.uo_out.value == 4

    await ClockCycles(
        dut.clk,
        200
    )

    assert dut.uo_out.value == 4


# ============================================================================
# ENA
# ============================================================================

@cocotb.test()
async def test_ena_gating(dut):

    uart = await reset_dut(dut)

    program = [
        enc(OP_LDI, 6),
        enc(OP_STORE, GPIO_OUT_ADDR),
        enc(OP_HALT, 0),
    ]

    await uart.load_program(program)

    dut.ena.value = 0

    await uart.start_cpu()

    await ClockCycles(
        dut.clk,
        50
    )

    assert dut.uo_out.value == 0

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

    assert dut.uo_out.value == 6


# ============================================================================
# NOP
# ============================================================================

@cocotb.test()
async def test_nop(dut):

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
        50
    )

    assert dut.uo_out.value == 6


# ============================================================================
# RAM ADDRESS SWEEP
# ============================================================================

@cocotb.test()
async def test_ram_address_sweep(dut):

    ram_addrs = [
        a
        for a in range(16)
        if a not in (
            GPIO_OUT_ADDR,
            UIO_ADDR,
            GPIO_IN_ADDR,
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
            50
        )

        got = int(dut.uo_out.value)

        assert got == value, (
            f"RAM addr {addr:#x}: "
            f"expected {value}, got {got}"
        )


# ============================================================================
# UIO INPUT
# ============================================================================

@cocotb.test()
async def test_uio_input_passthrough(dut):
    """
    LOAD 0xD reads uio_in[3:1].

    Physical mapping:

        uio_in[0]   = UART RX
        uio_in[3:1] = general-purpose inputs

    The CPU exposes the three UIO input bits as the
    low three bits of the accumulator.
    """

    test_values = [
        0b000,
        0b001,
        0b010,
        0b011,
        0b100,
        0b101,
        0b110,
        0b111,
    ]

    for value in test_values:

        uart = await reset_dut(dut)

        # ------------------------------------------------------------
        # IMPORTANT FIX:
        #
        # Drive UIO inputs AFTER reset and allow one clock cycle for
        # the physical input bus to settle.
        # ------------------------------------------------------------

        await set_uio_general_inputs(
            dut,
            value
        )

        # Verify only after the simulator has had a chance to settle.
        actual = int(dut.uio_in.value)

        assert ((actual >> 1) & 0x7) == value, (
            "UIO input pins did not retain requested value: "
            f"requested={value:03b}, "
            f"uio_in={actual:#04x}"
        )

        # UART RX must remain idle-high.
        assert (actual & 0x1) == 1, (
            "UART RX must remain idle-high; "
            f"uio_in={actual:#04x}"
        )

        program = [
            enc(OP_LOAD, UIO_ADDR),
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
            50
        )

        got = int(dut.uo_out.value)

        assert got == value, (
            f"UIO input {value:03b}: "
            f"expected uo_out={value:#04x}, "
            f"got {got:#04x}"
        )


# ============================================================================
# UIO OUTPUT
# ============================================================================

@cocotb.test()
async def test_uio_store_isolated_from_gpio_out(dut):

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
        50
    )

    assert dut.uo_out.value == 4

    assert (
        (int(dut.uio_out.value) >> 4) == 0xF
    )


# ============================================================================
# LIVE GPIO INPUT
# ============================================================================

@cocotb.test()
async def test_gpio_input_tracks_live_changes(dut):

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
        50
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
        50
    )

    assert dut.uo_out.value == 0xC3


# ============================================================================
# BACKWARD BRANCH LOOP
# ============================================================================

@cocotb.test()
async def test_backward_branch_loop(dut):

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
        program
    )

    await wait_for_halt(
        dut,
        200
    )

    assert dut.uo_out.value == 0


# ============================================================================
# UART GARBAGE
# ============================================================================

@cocotb.test()
async def test_uart_garbage_bytes_are_ignored(dut):

    uart = await reset_dut(dut)

    for junk in (
        0x00,
        0x01,
        0xFF,
        0x7E,
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
        50
    )

    assert dut.uo_out.value == 2


# ============================================================================
# UART REPROGRAMMING
# ============================================================================

@cocotb.test()
async def test_uart_reprogram_overwrites_instruction_memory(dut):

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
        50
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

    assert dut.uo_out.value == 9


# ============================================================================
# LONG-RUNNING RESTART TEST
# ============================================================================

INNER_LOOP_NOP_COUNT = 24


def build_interruptible_loop_program(
    counter_ram_addr=0x5
):

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


# ============================================================================
# RESTART MID-EXECUTION
# ============================================================================

@cocotb.test()
async def test_start_cpu_restarts_mid_execution(dut):

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
        "restart should re-run from PC=0; "
        f"got {int(dut.uo_out.value)}"
    )


# ============================================================================
# RESTART AFTER HALT
# ============================================================================

@cocotb.test()
async def test_start_cpu_restarts_after_halt(dut):

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
        50
    )

    assert dut.uo_out.value == 7

    await uart.start_cpu()

    await ClockCycles(
        dut.clk,
        30
    )

    assert dut.uo_out.value == 7


# ============================================================================
# RANDOMIZED ALU REGRESSION
# ============================================================================

@cocotb.test()
async def test_random_alu_immediate_program(dut):

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

                model = model & b

            elif op == OP_OR:

                model = model | b

            elif op == OP_XOR:

                model = model ^ b

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
            80
        )

        got = int(
            dut.uo_out.value
        )

        assert got == model, (
            f"trial {trial}: "
            f"expected {model}, got {got} "
            f"(program={[hex(i) for i in program]})"
        )
