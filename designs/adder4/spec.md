# ADD4 — 4-Bit Binary Adder with Carry and Overflow

Datasheet, revision 1.0

## 1. Overview

ADD4 adds two 4-bit operands and a carry-in. It produces a 4-bit sum, an unsigned carry-out, and a
signed two's-complement overflow flag. It is purely combinational and is built as a ripple-carry
chain of four full adders, similar in function to the classic 74x283 4-bit adder, with an added
overflow output.

### Features

- 4-bit operands A and B with carry-in
- 4-bit sum and carry-out for unsigned arithmetic (range 0 to 31)
- Overflow flag for signed two's-complement arithmetic (range −8 to +7)
- Purely combinational, no clock and no state
- Ripple-carry structure; internal carries `c[4:0]` are visible for debug

## 2. Pin description

| Pin | Direction | Width | Description |
|-----|-----------|-------|-------------|
| `a` | input | 4 | Operand A |
| `b` | input | 4 | Operand B |
| `cin` | input | 1 | Carry-in |
| `sum` | output | 4 | Low four bits of a + b + cin |
| `cout` | output | 1 | Carry-out: 1 when a + b + cin > 15 |
| `overflow` | output | 1 | Signed overflow: 1 when a and b have the same sign and sum has the other sign |

## 3. Block diagram

```
 a[0] b[0]      a[1] b[1]      a[2] b[2]      a[3] b[3]
   │   │          │   │          │   │          │   │
 ┌─▼───▼─┐ c[1] ┌─▼───▼─┐ c[2] ┌─▼───▼─┐ c[3] ┌─▼───▼─┐ c[4]
 │  FA0  ├─────►│  FA1  ├─────►│  FA2  ├─────►│  FA3  ├──────┬──► cout
 └─▲───┬─┘      └───┬───┘      └───┬───┘      └───┬───┘      │
  cin  │sum[0]      │sum[1]        │sum[2]        │sum[3]   c[3] XOR c[4] ──► overflow
```

## 4. Functional description

### 4.1 Unsigned view

`{cout, sum} = a + b + cin`, a 5-bit result from 0 to 31.

### 4.2 Signed view

Interpreting `a`, `b` and `sum` as two's-complement numbers from −8 to +7, `overflow` is 1 exactly
when the true result does not fit in 4 bits:

- two non-negative operands give a negative sum (positive overflow), or
- two negative operands give a non-negative sum (negative overflow).

Equivalently, `overflow = (a[3] == b[3]) && (sum[3] != a[3])`, which equals `c[3] XOR c[4]`.
Operands with different signs can never overflow.

### 4.3 Internal carries

`c[0] = cin`, and `c[i+1]` is the carry out of bit i:
`c[i+1] = a[i]·b[i] + a[i]·c[i] + b[i]·c[i]`. `cout = c[4]`.

### 4.4 Examples

| a | b | cin | sum | cout | overflow | Note |
|---|---|-----|-----|------|----------|------|
| 0 | 0 | 0 | 0 | 0 | 0 | all zero |
| 3 | 4 | 0 | 7 | 0 | 0 | no carry |
| 7 | 1 | 0 | 8 | 0 | 1 | +7 + 1 overflows to −8 |
| 8 | 8 | 0 | 0 | 1 | 1 | −8 + −8 overflows |
| 15 | 1 | 0 | 0 | 1 | 0 | −1 + 1 = 0, carry out only |
| 15 | 0 | 1 | 0 | 1 | 0 | carry ripples through all four bits |
| 15 | 15 | 1 | 15 | 1 | 0 | maximum input |
| 9 | 6 | 0 | 15 | 0 | 0 | −7 + 6 = −1 |

## 5. Timing

The outputs are a pure function of the inputs and settle after the carry has rippled through four
stages. There is no clock. A testbench may use a clock only to pace its stimulus and should sample
the outputs after they have settled.

## 6. Requirements

- R1: `{cout, sum}` equals `a + b + cin` for every one of the 512 input combinations.
- R2: `overflow` is 1 exactly when `a` and `b` have the same sign bit and `sum` has the other sign bit.
- R3: Operands with different sign bits never set `overflow`.
- R4: A carry generated in bit 0 propagates through bits 1 to 3 when they all propagate.
- R5: `cin` contributes exactly one to the result.
- R6: The outputs depend only on the current inputs (no state).

## 7. Interesting cases

- 0 + 0 + 0 and 15 + 15 + 1
- a carry rippling through all four bits (15 + 0 + 1)
- positive overflow (7 + 1) and negative overflow (8 + 8)
- different-sign operands at the extremes (7 + 8, 15 + 1)
- carry-in set with and without a carry-out
- every pair of operand ranges: zero, low (1-7), high (8-14) and fifteen
