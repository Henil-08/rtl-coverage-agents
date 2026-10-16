# adder4

4-bit combinational adder with carry-in.

## Ports

| Port | Dir | Width | Meaning |
|------|-----|-------|---------|
| a, b | in | 4 | operands |
| cin | in | 1 | carry-in |
| sum | out | 4 | (a + b + cin) mod 16 |
| cout | out | 1 | unsigned carry-out, set when a + b + cin > 15 |
| overflow | out | 1 | signed two's-complement overflow |

## Behaviour

- `{cout, sum} == a + b + cin` for every input.
- `overflow` is set when `a` and `b` have the same sign bit and `sum` has the other one.
  Example: 7 + 1 = 8, which reads as -8 signed, so overflow = 1.
- The design is a ripple-carry chain. Internal carries are `c[0] = cin` and `c[i+1]` = carry out of bit i.
  `overflow == c[3] ^ c[4]`.
- Purely combinational: outputs settle with no clock. The testbench clock only paces stimulus.

## Interesting cases

- 0 + 0 + 0 and 15 + 15 + 1
- carry rippling through all four bits (15 + 0 + 1)
- positive overflow (7 + 1) and negative overflow (8 + 8)
