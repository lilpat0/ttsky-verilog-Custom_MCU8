module ram8 (
    input logic       clk,
    input logic       rst_n,

    input logic       we,
    input logic [3:0] address,

    input logic [7:0] write_data,
    output logic [7:0] read_data
);

    logic [7:0] memory [0:15];

    integer i;

    // Asynchronous read
    always_comb begin
        if (!rst_n)
            read_data = 8'h00;
        else
            read_data = memory[address];
    end

    // Synchronous reset and write
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            // Explicitly clear all RAM locations on reset.
            // This avoids relying on 'initial' simulation-only
            // initialization for deterministic post-reset state.
            for (i = 0; i < 16; i = i + 1)
                memory[i] <= 8'h00;
        end
        else if (we) begin
            memory[address] <= write_data;
        end
    end

endmodule
