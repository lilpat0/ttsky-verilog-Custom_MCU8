// Custom 8-bit ALU
module alu8 (

    // Inputs
    input logic [7:0] a,
    input logic [7:0] b,

    // ALU control
    input logic [2:0] alu_control,

    // Output
    output logic [7:0] result
);

    // ALU operation definitions
    localparam logic [2:0] ALU_ADD = 3'b000;
    localparam logic [2:0] ALU_SUB = 3'b001;
    localparam logic [2:0] ALU_AND = 3'b010;
    localparam logic [2:0] ALU_OR  = 3'b011;
    localparam logic [2:0] ALU_XOR = 3'b100;
    localparam logic [2:0] ALU_NOT = 3'b101;
    localparam logic [2:0] ALU_INC = 3'b110;
    localparam logic [2:0] ALU_DEC = 3'b111;

    always_comb begin

        case (alu_control)

            ALU_ADD: begin
                result = a + b;
            end

            ALU_SUB: begin
                result = a - b;
            end

            ALU_AND: begin
                result = a & b;
            end

            ALU_OR: begin
                result = a | b;
            end

            ALU_XOR: begin
                result = a ^ b;
            end

            ALU_NOT: begin
                result = ~a;
            end

            ALU_INC: begin
                result = a + 8'b1;
            end

            ALU_DEC: begin
                result = a - 8'b1;
            end

            default: begin
                result = 8'b0;
            end

        endcase

    end

endmodule