module ram8 (

    input logic       clk,
    input logic       rst_n,

    input logic       we,
    input logic [4:0] address,

    input logic [7:0] write_data,
    output logic [7:0] read_data

);

    logic [7:0] memory [0:31];

    integer i;

    // Initialize RAM for simulation.
    initial begin
        for (i = 0; i < 32; i = i + 1)
            memory[i] = 8'h00;
    end

    // Asynchronous read.
    always_comb begin
        read_data = memory[address];
    end

    // Synchronous write + reset.
    always_ff @(posedge clk or negedge rst_n) begin

        if (!rst_n) begin

            for (i = 0; i < 32; i = i + 1)
                memory[i] <= 8'h00;

        end

        else if (we) begin

            memory[address] <= write_data;

        end

    end

endmodule