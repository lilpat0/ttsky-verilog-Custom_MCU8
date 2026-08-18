module register_file (
    // Control
    input  logic       clk,
    input  logic       rst_n,

    // Input
    input  logic [3:0] rs1,
    input  logic [3:0] rs2,

    input  logic [3:0] rd,
    input  logic [7:0] write_data,
    input  logic       we,

    // Output
    output logic [7:0] read_data1,
    output logic [7:0] read_data2
);

    // Create the register array
    logic [7:0] register8 [0:15];

    // Read
    always_comb begin 
        if (!rst_n) begin
            read_data1 = 8'b0;
            read_data2 = 8'b0;

        end else begin 
        read_data1 = register8[rs1];
        read_data2 = register8[rs2];

        end
    end

    // Write
    always_ff @(posedge clk) begin
        if(rst_n) begin
            if(we) begin
                register8[rd] <= write_data;

            end
        end
    end

endmodule