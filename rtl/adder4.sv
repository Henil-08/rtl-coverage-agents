// -----------------------------------------------------------------------------
// adder4 - 4-bit combinational adder
//
// Ports
//   a, b      : 4-bit operands
//   cin       : carry-in
//   sum       : 4-bit result, (a + b + cin) mod 16
//   cout      : unsigned carry-out (result > 15)
//   overflow  : signed two's-complement overflow
//               (a and b share a sign bit and sum's sign bit differs)
//
// Spec
//   {cout, sum} == a + b + cin                       (unsigned view)
//   overflow    == (a[3] == b[3]) && (sum[3] != a[3]) (signed view)
//
// Implementation is an explicit ripple-carry chain so that mutation testing
// can target individual carry stages.
// -----------------------------------------------------------------------------
module adder4 (
    input  logic [3:0] a,
    input  logic [3:0] b,
    input  logic       cin,
    output logic [3:0] sum,
    output logic       cout,
    output logic       overflow
);

    logic [4:0] c;  // c[0] = cin, c[i+1] = carry out of bit i

    assign c[0] = cin;

    genvar i;
    generate
        for (i = 0; i < 4; i++) begin : g_fa
            assign sum[i]   = a[i] ^ b[i] ^ c[i];
            assign c[i+1]   = (a[i] & b[i]) | (a[i] & c[i]) | (b[i] & c[i]);
        end
    endgenerate

    assign cout     = c[4];
    // Signed overflow: carry into MSB differs from carry out of MSB.
    assign overflow = c[3] ^ c[4];

endmodule
