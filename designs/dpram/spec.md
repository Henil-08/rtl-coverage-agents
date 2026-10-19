# DPRAM-8x16 — True Dual-Port Synchronous RAM

Datasheet, revision 1.0

## 1. Overview

DPRAM-8x16 is a 16-word × 8-bit true dual-port static RAM with a single clock. Two independent
ports, A and B, can each read or write any word on every rising clock edge. Reads are synchronous
with one cycle of latency, both ports are read-first, and a write collision on the same address
resolves in favour of port A.

### Features

- Two fully independent read/write ports sharing one memory array
- Single rising-edge clock for both ports
- Synchronous read, one clock of latency
- Read-first on both ports (old data out while writing)
- Defined write-collision behaviour: port A has priority
- Output hold while a port is disabled
- Parameterised data width and depth
- No reset; contents are undefined until written

## 2. Parameters

| Name | Default | Range | Description |
|------|---------|-------|-------------|
| `DATA_W` | 8 | 1 to 64 | Bits per word |
| `ADDR_W` | 4 | 1 to 16 | Address bits; depth is 2^ADDR_W words (16 by default) |

## 3. Pin description

| Pin | Direction | Width | Description |
|-----|-----------|-------|-------------|
| `clk` | input | 1 | Clock. All inputs are sampled and all writes happen on the rising edge. |
| `en_a` | input | 1 | Port A enable. When 0, port A does nothing and `rdata_a` holds. |
| `we_a` | input | 1 | Port A write enable. Only meaningful when `en_a` = 1. |
| `addr_a` | input | `ADDR_W` | Port A word address |
| `wdata_a` | input | `DATA_W` | Port A write data |
| `rdata_a` | output | `DATA_W` | Port A read data, registered |
| `en_b` | input | 1 | Port B enable |
| `we_b` | input | 1 | Port B write enable |
| `addr_b` | input | `ADDR_W` | Port B word address |
| `wdata_b` | input | `DATA_W` | Port B write data |
| `rdata_b` | output | `DATA_W` | Port B read data, registered |

## 4. Block diagram

```
            ┌───────────────────────────────────────────┐
 en_a ─────►│                                           │
 we_a ─────►│  Port A        ┌───────────────┐  Port B  │◄───── en_b
 addr_a ═══►│  control ─────►│  mem[16] x 8  │◄──────── │◄───── we_b
 wdata_a ══►│                └───────┬───────┘  control │◄════ addr_b
            │   rdata_a reg ◄────────┴────────► rdata_b │◄════ wdata_b
 rdata_a ◄══│                                    reg    │══► rdata_b
 clk ──────►│        (A wins same-address writes)       │
            └───────────────────────────────────────────┘
```

## 5. Functional description

### 5.1 Port operation (each port independently)

| `en_X` | `we_X` | Operation on the rising edge | `rdata_X` after the edge |
|--------|--------|------------------------------|--------------------------|
| 0 | x | none | unchanged (hold) |
| 1 | 0 | read | `mem[addr_X]` |
| 1 | 1 | write `wdata_X` to `mem[addr_X]` | old `mem[addr_X]` (read-first) |

### 5.2 Read latency

The address presented before edge N is captured on edge N, and `rdata_X` shows the word after
edge N. A read issued in cycle N is therefore visible in cycle N + 1.

### 5.3 Read-first

Every enabled cycle reads the addressed word before any write in that cycle takes effect:

- a port that writes returns the old contents of that address;
- a port that reads an address the other port writes in the same cycle also returns the old contents;
- a read in the cycle after a write returns the new contents.

### 5.4 Same-address behaviour

When both ports address the same word in the same cycle:

| Port A | Port B | Stored after the edge | `rdata_a` | `rdata_b` |
|--------|--------|-----------------------|-----------|-----------|
| read | read | unchanged | old | old |
| write | read | `wdata_a` | old | old |
| read | write | `wdata_b` | old | old |
| write | write | `wdata_a` (port B's write is dropped) | old | old |

### 5.5 Different addresses

Operations on different addresses never interact. Every combination of idle, read and write on the
two ports is legal in the same cycle.

### 5.6 Initial state

There is no reset. Every word is undefined until it is first written, and `rdata_X` is undefined
until port X performs its first enabled operation. Reading a never-written word returns an
undefined value; that is not an error.

## 6. Timing diagrams

Write on port A, then read the same word back on port A and on port B:

```wavedrom
{ "signal": [
  { "name": "clk",     "wave": "p...." },
  { "name": "en_a",    "wave": "01.0." },
  { "name": "we_a",    "wave": "010.." },
  { "name": "addr_a",  "wave": "x33x.", "data": ["3", "3"] },
  { "name": "wdata_a", "wave": "x4x..", "data": ["55"] },
  { "name": "rdata_a", "wave": "x.=5.", "data": ["old", "55"] },
  { "name": "en_b",    "wave": "0..10" },
  { "name": "addr_b",  "wave": "x..3x", "data": ["3"] },
  { "name": "rdata_b", "wave": "x...5", "data": ["55"] }
]}
```

Write collision, then read back:

```wavedrom
{ "signal": [
  { "name": "clk",     "wave": "p..." },
  { "name": "we_a",    "wave": "010." },
  { "name": "wdata_a", "wave": "x4x.", "data": ["A4"] },
  { "name": "we_b",    "wave": "010." },
  { "name": "wdata_b", "wave": "x5x.", "data": ["B4"] },
  { "name": "addr",    "wave": "x3.x", "data": ["3 (both ports)"] },
  { "name": "rdata_b", "wave": "x.=4", "data": ["old", "A4"] }
]}
```

## 7. Requirements

- R1: A read on port A or B returns `mem[addr]` one clock after the edge that sampled the address.
- R2: A write on port A or B stores `wdata` at `addr` on the rising edge.
- R3: A port that writes returns the old contents of the written word on its own `rdata` (read-first).
- R4: A port that reads a word the other port writes in the same cycle returns the old contents.
- R5: A read in the cycle after a write to the same word returns the newly written data, from either port.
- R6: When both ports write the same word in the same cycle, port A's data is stored and port B's write is dropped.
- R7: Operations on different addresses never interact, for every combination of idle, read and write.
- R8: While `en_X` is 0, `rdata_X` keeps its last value.
- R9: Word 0 and word 15 behave like every other word on both ports.
- R10: Every bit of every word can hold both 0 and 1, including the patterns 0x00, 0xFF, 0xAA and 0x55.

## 8. Interesting cases

- every combination of idle, read and write on the two ports in the same cycle
- the first and last address on both ports, for reads and writes
- data patterns 0x00, 0xFF, 0xAA and 0x55 on both ports
- both ports on the same address: read/read, write/read, read/write, write/write
- read an address in the cycle right after it was written, from the same port and from the other port
- write collisions where the two addresses differ only in the top bit
- a port idling for several cycles between reads, to check that rdata holds
