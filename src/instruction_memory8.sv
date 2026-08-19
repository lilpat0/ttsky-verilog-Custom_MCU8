module instruction_memory8 #(
    parameter integer DEPTH = 32
)(
    input  logic       clk,

    input  logic [7:0] pc,
    output logic [7:0] instruction,

    input  logic       we,
    input  logic [7:0] prog_adress,
    input  logic [7:0] prog_data
);

    logic [7:0] instructions [0:DEPTH-1];

    integer i;

    // Simulation initialization
    initial begin
        for (i = 0; i < DEPTH; i = i + 1)
            instructions[i] = 8'h00;
    end

    // Program write
    always_ff @(posedge clk) begin
        if (we && (prog_adress < DEPTH))
            instructions[prog_adress] <= prog_data;
    end

    // Instruction fetch
    always_comb begin
        if (pc < DEPTH)
            instruction = instructions[pc];
        else
            instruction = 8'h00;
    end

endmodule
