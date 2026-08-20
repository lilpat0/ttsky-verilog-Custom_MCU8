// Custom ISA
module decode8 (
    // Instruction memory
    input logic [7:0] instruction,

    // Decoded instruction
    output logic [3:0] opcode,
    output logic [3:0] operand,

    // Register control
    output logic       reg_write,

    // ALU control
    output logic [2:0] alu_control,

    // Memory control
    output logic       mem_read,
    output logic       mem_write,

    // PC control
    output logic       jump,
    output logic       branch_zero,
    output logic       branch_not_zero,

    // CPU control
    output logic       halt
);

    // Opcode definitions
    localparam logic [3:0] OP_NOP   = 4'b0000;
    localparam logic [3:0] OP_LDI   = 4'b0001;
    localparam logic [3:0] OP_ADD   = 4'b0010;
    localparam logic [3:0] OP_SUB   = 4'b0011;
    localparam logic [3:0] OP_AND   = 4'b0100;
    localparam logic [3:0] OP_OR    = 4'b0101;
    localparam logic [3:0] OP_XOR   = 4'b0110;
    localparam logic [3:0] OP_NOT   = 4'b0111;
    localparam logic [3:0] OP_INC   = 4'b1000;
    localparam logic [3:0] OP_DEC   = 4'b1001;
    localparam logic [3:0] OP_LOAD  = 4'b1010;
    localparam logic [3:0] OP_STORE = 4'b1011;
    localparam logic [3:0] OP_JMP   = 4'b1100;
    localparam logic [3:0] OP_BZ    = 4'b1101;
    localparam logic [3:0] OP_BNZ   = 4'b1110;
    localparam logic [3:0] OP_HALT  = 4'b1111;

    // ALU operation definitions
    localparam logic [2:0] ALU_ADD = 3'b000;
    localparam logic [2:0] ALU_SUB = 3'b001;
    localparam logic [2:0] ALU_AND = 3'b010;
    localparam logic [2:0] ALU_OR  = 3'b011;
    localparam logic [2:0] ALU_XOR = 3'b100;
    localparam logic [2:0] ALU_NOT = 3'b101;
    localparam logic [2:0] ALU_INC = 3'b110;
    localparam logic [2:0] ALU_DEC = 3'b111;

    // -----------------------------------------------------------
    // Instruction field extraction.
    //
    // Done as continuous assigns to constant part-selects rather
    // than inside the always_comb block below. Icarus Verilog
    // does not fully support constant selects inside always_*
    // processes ("sorry: constant selects in always_* processes
    // are not currently supported (all bits will be included)"),
    // which can silently substitute the whole 8-bit instruction
    // for what should be a 4-bit slice. Slicing here, outside the
    // process, avoids relying on that unsupported behavior.
    // -----------------------------------------------------------
    logic [3:0] opcode_bits;
    logic [3:0] operand_bits;

    assign opcode_bits  = instruction[7:4];
    assign operand_bits = instruction[3:0];

    // Decode instruction
    always_comb begin

        // Extract instruction fields
        opcode  = opcode_bits;
        operand = operand_bits;

        // Default values
        reg_write       = 1'b0;
        alu_control     = ALU_ADD;

        mem_read        = 1'b0;
        mem_write       = 1'b0;

        jump            = 1'b0;
        branch_zero     = 1'b0;
        branch_not_zero = 1'b0;

        halt            = 1'b0;

        case (opcode_bits)

            // -------------------------
            // No operation
            // -------------------------
            OP_NOP: begin
                // Do nothing
            end

            // -------------------------
            // Load immediate
            // -------------------------
            OP_LDI: begin
                reg_write = 1'b1;
            end

            // -------------------------
            // Arithmetic / logic
            // -------------------------
            OP_ADD: begin
                reg_write   = 1'b1;
                alu_control = ALU_ADD;
            end

            OP_SUB: begin
                reg_write   = 1'b1;
                alu_control = ALU_SUB;
            end

            OP_AND: begin
                reg_write   = 1'b1;
                alu_control = ALU_AND;
            end

            OP_OR: begin
                reg_write   = 1'b1;
                alu_control = ALU_OR;
            end

            OP_XOR: begin
                reg_write   = 1'b1;
                alu_control = ALU_XOR;
            end

            OP_NOT: begin
                reg_write   = 1'b1;
                alu_control = ALU_NOT;
            end

            OP_INC: begin
                reg_write   = 1'b1;
                alu_control = ALU_INC;
            end

            OP_DEC: begin
                reg_write   = 1'b1;
                alu_control = ALU_DEC;
            end

            // -------------------------
            // Memory
            // -------------------------
            OP_LOAD: begin
                reg_write = 1'b1;
                mem_read  = 1'b1;
            end

            OP_STORE: begin
                mem_write = 1'b1;
            end

            // -------------------------
            // Program control
            // -------------------------
            OP_JMP: begin
                jump = 1'b1;
            end

            OP_BZ: begin
                branch_zero = 1'b1;
            end

            OP_BNZ: begin
                branch_not_zero = 1'b1;
            end

            // -------------------------
            // Halt
            // -------------------------
            OP_HALT: begin
                halt = 1'b1;
            end

            default: begin
                // Invalid opcode
            end

        endcase

    end

endmodule
