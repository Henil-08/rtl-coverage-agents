// True dual-port RAM on one clock. Synchronous read, one cycle of latency.
// Both ports are read-first. When both ports write the same address in the
// same cycle, port A's data is stored.
module dpram #(
    parameter int DATA_W = 8,
    parameter int ADDR_W = 4
) (
    input  logic              clk,

    input  logic              en_a,
    input  logic              we_a,
    input  logic [ADDR_W-1:0] addr_a,
    input  logic [DATA_W-1:0] wdata_a,
    output logic [DATA_W-1:0] rdata_a,

    input  logic              en_b,
    input  logic              we_b,
    input  logic [ADDR_W-1:0] addr_b,
    input  logic [DATA_W-1:0] wdata_b,
    output logic [DATA_W-1:0] rdata_b
);

    logic [DATA_W-1:0] mem [2**ADDR_W];
    logic              a_wins;

    assign a_wins = en_a && we_a && (addr_a == addr_b);

    always_ff @(posedge clk) begin
        if (en_a) rdata_a <= mem[addr_a];
        if (en_b) rdata_b <= mem[addr_b];
        if (en_a && we_a) mem[addr_a] <= wdata_a;
        if (en_b && we_b && !a_wins) mem[addr_b] <= wdata_b;
    end

endmodule
