# SFIFO-8x8 — Synchronous FIFO

Datasheet, revision 1.0

## 1. Overview

SFIFO-8x8 is an 8-entry, 8-bit first-in first-out buffer on a single clock. Data written with `push`
comes out of `dout` in the same order. Status outputs report full, empty and the number of stored
entries. Pushing into a full FIFO or popping an empty one is ignored.

### Features

- 8 entries of 8 bits, single rising-edge clock
- First-word fall-through: `dout` always shows the oldest entry
- Simultaneous push and pop in the same cycle
- `full`, `empty` and a 4-bit `count`
- Active-low synchronous reset

## 2. Pin description

| Pin | Direction | Width | Description |
|-----|-----------|-------|-------------|
| `clk` | input | 1 | Clock, rising edge |
| `rst_n` | input | 1 | Synchronous reset, active low. Empties the FIFO. |
| `push` | input | 1 | Write `din` at the next rising edge, unless full |
| `din` | input | 8 | Data to write |
| `pop` | input | 1 | Remove the oldest entry at the next rising edge, unless empty |
| `dout` | output | 8 | Oldest entry; undefined while empty |
| `full` | output | 1 | 1 when 8 entries are stored |
| `empty` | output | 1 | 1 when no entries are stored |
| `count` | output | 4 | Number of stored entries, 0 to 8 |

## 3. Functional description

### 3.1 Reset

With `rst_n` = 0 on a rising edge the FIFO becomes empty: `count` = 0, `empty` = 1, `full` = 0.

### 3.2 Push and pop

| `push` | `pop` | State | Effect at the rising edge |
|--------|-------|-------|---------------------------|
| 0 | 0 | any | nothing |
| 1 | 0 | not full | store `din`, count + 1 |
| 1 | 0 | full | ignored |
| 0 | 1 | not empty | remove oldest, count − 1 |
| 0 | 1 | empty | ignored |
| 1 | 1 | empty | store `din` only (count + 1) |
| 1 | 1 | full | remove oldest only (count − 1) |
| 1 | 1 | otherwise | store and remove, count unchanged |

### 3.3 Output data

`dout` shows the oldest stored entry at all times (first-word fall-through), so after a push into an
empty FIFO the new word appears on `dout` right after the clock edge. Its value is undefined while
the FIFO is empty.

## 4. Requirements

- R1: After reset the FIFO is empty: count = 0, empty = 1, full = 0.
- R2: Words come out of dout in the order they were pushed.
- R3: count always equals pushes accepted minus pops accepted, between 0 and 8.
- R4: full is 1 exactly when count = 8; empty is 1 exactly when count = 0.
- R5: A push while full is ignored and does not change stored data or count.
- R6: A pop while empty is ignored and does not change count.
- R7: A simultaneous push and pop on a non-empty, non-full FIFO keeps count and order.
- R8: The write and read pointers wrap after entry 7 without losing or duplicating data.

## 5. Interesting cases

- fill to full, then push once more
- drain to empty, then pop once more
- push and pop together when empty, when full and in between
- more than eight pushes in total, so the pointers wrap
- reset in the middle of traffic
- data patterns 0x00, 0xFF, 0xAA, 0x55
