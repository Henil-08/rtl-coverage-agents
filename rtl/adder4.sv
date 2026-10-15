// 4-bit ripple-carry adder
// {cout, sum} = a + b + cin
// overflow    = signed overflow, i.e. a, b same sign and sum sign differs
module adder4 (
    input  logic [3:0] a,
    input  logic [3:0] b,
    input  logic       cin,
    output logic [3:0] sum,
    output logic       cout,
    output logic       overflow
);

    logic [4:0] c;

    assign c[0] = cin;

    genvar i;
    generate
        for (i = 0; i < 4; i++) begin : g_fa
            assign sum[i]   = a[i] ^ b[i] ^ c[i];
            assign c[i+1]   = (a[i] & b[i]) | (a[i] & c[i]) | (b[i] & c[i]);
        end
    endgenerate

    assign cout     = c[4];
    // carry into MSB != carry out of MSB
    assign overflow = c[3] ^ c[4];

endmodule
