module instruction_memory8 #(
    parameter integer DEPTH = 32
)(
    input logic clk,

    // CPU fetch
    input logic [7:0] pc,
    output logic [7:0] instruction,

    // Programming interface
    input logic       we,
    input logic [7:0] prog_adress,
    input logic [7:0] prog_data
);

    logic [7:0] instructions [0:DEPTH-1];

    integer i;

    // =========================================================
    // Initialize memory to NOP
    // =========================================================

    initial begin

        for (i = 0; i < DEPTH; i = i + 1) begin

            instructions[i] = 8'h00;

        end

    end

    // =========================================================
    // Programming write port
    // =========================================================

    always_ff @(posedge clk) begin

        if (we) begin

            if (prog_adress < DEPTH) begin

                instructions[prog_adress] <= prog_data;

            end

        end

    end

    // =========================================================
    // Instruction fetch
    // =========================================================

    always_comb begin

        instruction = instructions[pc];

    end

endmodule
