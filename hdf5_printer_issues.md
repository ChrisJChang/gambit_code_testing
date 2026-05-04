# HDF5 printer audit — synthesized findings

Audit of the v1 (`Printers/src/printers/hdf5printer/`) and v2
(`Printers/src/printers/hdf5printer_v2/`) HDF5 printer implementations,
performed after the file_id fix for issue #495. Findings sorted by
severity and grouped where v1 and v2 share a class of bug.

## Critical (likely to bite real runs)

### [v2] `final_size` is uninitialised on workers in `HDF5Printer2::finalise()`
`hdf5printer_v2.cpp:1958-2010`. `final_size` is set only inside
`if(myRank==0)` at lines 1959-1967, but the loop at 1996-2010 runs on
**every** rank and calls `(*it)->extend_all_datasets_to(final_size)` at
line 2008. Workers pass garbage. There's no rank-0 guard around the
loop. This will misbehave any time a worker has a non-synchronised aux
buffer registered (which any scanner using RA aux streams over MPI
produces). The whole 1996-2010 block belongs inside `if(myRank==0)`,
alongside the matching block at 1930-1952.

### [v1] `errorsOff()` / `errorsOn()` nesting permanently silences HDF5 errors
`hdf5tools.cpp:369-386`. `errorsOff()` saves the old handler into
module-globals `old_func` / `old_client_data`. The function at line 377
calls `errorsOff()` again *while errors are already off* — so it saves
NULL into those globals. The matching `errorsOn()` at line 386 then
restores NULL, leaving HDF5 error reporting permanently disabled for the
rest of the process. Same pattern at lines 395/408 (less reachable). Any
subsequent HDF5 problem will fail silently.

### [v1] Aux printers' uninitialised `hid_t` members beyond `file_id`
`hdf5printer.hpp:336-345`. None of `file_id`, `group_id`, `RA_group_id`,
`metadata_id` (and arguably the `*_location_id` set) have default
initialisers. The aux constructor only assigns `location_id` /
`RA_location_id` / `metadata_location_id`. The `H5Fflush` issue we just
fixed (#495) is one example — others are latent. Suggests a wider fix:
either default-init all to `-1` (HDF5's invalid handle), or always go
through `primary_printer->X` in code that runs on aux instances.

### [v1] `openGroup` returns after creating only the first non-existent path component
`hdf5tools.cpp:540-574`. On the first iteration where `H5Gopen2` fails
and `H5Gcreate2` succeeds, the inner `else` branch at line 564 returns
immediately, exiting the loop before processing the remaining
components. Latent because v1 only ever opens single-level paths
(`/data`, `/data/RA`, etc. as separate calls), but the function would
silently mis-create any user-supplied deeper `group:` option.

### [v1] Buffer destructors do not close their HDF5 datasets
`VertexBufferNumeric1D_HDF5.hpp:294-303`,
`DataSetInterfaceBase.hpp:189-204`. Destructors are deliberately empty
(close calls commented out, with TODO about copy semantics). Cleanup
relies entirely on `finalise()` running. Any abnormal exit before
finalise — a constructor exception elsewhere, an error during
synchronisation, an uncaught signal — leaks dataset handles and likely
loses unflushed data when `H5Fclose` auto-closes them later.

### [v2] `H5Tclose` missing in `HDF5DataSet<T>::write_buffer` — leaks one type handle per flush
`hdf5printer_v2.hpp:304-311`. `hid_t dtype = H5Dget_type(get_dset_id())`
is opened but never closed. The companion `write_RA_buffer` at lines
438/467 *does* close it. Long scans with many datasets and many flushes
accumulate handles until HDF5's table or the OS file-handle limit gives.

### [v2] Stack-local `RAbuffer` added to member `aux_buffers`, then destroyed
`hdf5printer_v2.cpp:1973, 1994`. `HDF5MasterBuffer RAbuffer(...)` is a
local; `add_aux_buffer(RAbuffer)` pushes its address into the
`aux_buffers` vector. When `finalise` returns, the pointer dangles.
Currently dormant (no second `finalise` call, empty destructor at 1844)
but a bug-magnet for any future change.

## Major

### [v1] `masterWaitForAll(FINAL_SYNC)` deadlocks if any worker dies before reaching it
`hdf5printer.cpp:987` plus `Utils/src/mpiwrapper.cpp:163-188`. The
barrier is plain blocking `Recv`s on rank 0, no Iprobe-with-timeout
(unlike `allWaitForMasterWithFunc`). The TODO comment at line 988
acknowledges this. Same risk on the resume-mode `myComm.Barrier()` at
line 610 if `prepare_and_combine_tmp_files` raises on rank 0.

### [v1] `exit(1)` from inside the constructor after `closeFile`
`hdf5printer.cpp:467-469`. On any restart-without-`-r` against an
existing output file with the requested group missing — a normal user
mistake — rank 0 calls `exit(1)`, bypassing MPI shutdown. Workers
blocked on the upcoming `myComm.Barrier()` at line 610 hang forever.

### [v2] `MPI_flush_to_rank` / `MPI_recv_all_buffers` / `MPI_request_buffer_data` are dead code
`hdf5printer_v2.cpp:664-810`, `hdf5printer_v2.hpp:910-1001`, including
`recv_counter` / `send_counter` debug scaffolding. No callers.
`finalise()` uses the `gather_and_print` / `Gatherv` path instead.
Either half-finished refactor leftover or a missed wiring that should be
using this faster path. Recommend either deleting or wiring up — the
deadlock-warning comment is currently misleading.

### [v2] `HDF5Printer2::flush()` does not gather over MPI; only the calling rank's buffermaster is touched
`hdf5printer_v2.cpp:1876-1879`. So between scanner-driven `flush()`
calls, RA aux data on workers stays in worker memory until `finalise()`.
Different from v1's effective semantics. Any scanner that calls
`aux_stream->flush()` for durability (MultiNest's dumper at
`multinest_3.12/multinest.cpp:362-363` is exactly this) will *not* get
RA data from non-rank-0 ranks to disk until the scan ends.

### [v1] `synchronise_buffers` underflows if `sync_pos == 0`
`hdf5printer.cpp:1307`. `const unsigned long sync_pos = get_sync_pos()-1;`
becomes `ULONG_MAX`. Currently never reached because `check_for_new_point`
only triggers it after a real point has been seen, but the invariant is
not enforced anywhere.

### [v1] Unbounded growth of `postpone_write_queue_and_locs`
`VertexBufferNumeric1D_HDF5.hpp:63, 541-544`. RA writes that can't yet
be matched to a sync point get pushed without a cap. The MPI-based
queue-sending that was supposed to bound this has been disabled
(commented out) and the comments weren't updated.

### [v1] `_print_metadata` always passes `resume=false`
`hdf5printer.cpp:1681-1691`. Re-creates datasets on every call.
Currently only called once, at `finalise()`, so dormant — but any new
caller will trip the "Dataset with same name may already exist" path
immediately.

### [v1] Aux constructor doesn't validate `dynamic_cast` result
`hdf5printer.cpp:683`. If the cast fails (HDF5 aux attached to non-HDF5
primary), `primary_printer` becomes nullptr and the very next
`set_resume(primary_printer->get_resume())` segfaults.

### [v2] `print_metadata` underflow
`hdf5printer_v2.cpp:609-616`. `std::size_t size = get_next_metadata_position(); if(sameset) size --;`
— if the GAMBIT dataset doesn't exist yet, `get_next_metadata_position()`
returns 0, `--` underflows to `SIZE_MAX`. Currently protected by the
call-site `if (use_metadata)` at 1948, but the function is unsafe.

### [v1] Iterators decremented past `begin()` in combine size-trim loops
`hdf5_combine_tools.cpp:539-545`, `807-813`. Technically UB on
`std::vector::iterator` when all entries are false. Works on most STLs.

### [v1] `H5Dget_type` not closed in combine tools
`hdf5_combine_tools.cpp:949-950, 955-956, 1144-1145, 1273, 1278`.
Type-handle leak per file/parameter combined; contributes to "too many
open objects" warnings on big merges.

## Minor / Notes

A handful more across both files:

- v1 dead/stale state members (`current_dset_position`, `previous_points`,
  `global=false` field never assigned).
- v1 `errorsOff` / `errorsOn` use static globals → fundamentally not
  thread-safe.
- v1 hardcoded `BUFFERLENGTH=100` and `MAX_PPIDPAIRS=1000`.
- v1 `combine_output_py` is dead code (uses a Python helper that may not
  exist).
- v2 constructor's resource-leak risk if `printer_error()` raises
  mid-setup (no RAII).
- v2 generous `std::cout` / `std::cerr` use where `logger()` would be
  appropriate (e.g. lines 1514, 1539, 1543, 1705, 1713, 1716, 1745,
  1762, 1965, 2018).
- v2 narrowing conversions between `std::size_t` and `int` in MPI size
  handling.
- Both v1 and v2 shell out to `popen("rm ...")` and `popen("cp ...")`
  rather than calling `std::remove` / filesystem APIs. Brittle on paths
  with shell metacharacters.
- v2 `MAX_BUFFER_SIZE = 100000` `T buffer[MAX_BUFFER_SIZE]` is a stack
  array (~800 KB for `T=double`). Fine on Linux defaults, fragile
  elsewhere.
- v2 `H5Tequal(in-memory, on-disk)` check can fire spuriously on resume
  because on-disk types aren't normalised through `H5Tget_native_type`
  like v1 does.
- v2 `_isvalid` companion existence not separately tracked from value
  dataset (TODO at `hdf5printer_v2.hpp:888`).

## What to prioritize fixing

1. **v2 `final_size` / `extend_all_datasets_to` on workers** — same shape
   as the bug we just fixed: a finalise-time member-not-set-on-aux-path
   issue that hides because some scenarios mask the UB. Will hit any MPI
   scan with v2 + RA aux streams.
2. **v1 `errorsOff` / `errorsOn` nesting** — silently disables your
   safety net for HDF5 errors. Trivial to fix (save state in a local).
3. **v1 uninit `hid_t` cluster** — same root cause as #495. A small
   refactor to default-init or to collapse aux/primary handles into a
   single struct would prevent another year of "another field wasn't set
   on aux printers" bugs.
4. **v2 `H5Tclose` leak in `write_buffer`** — slow-burn but unbounded.
5. **v1 buffer-destructor cleanup** — would matter on any abnormal
   shutdown, including signal-driven ones from a scheduler killing a
   job.

Everything below "Major" is good to file as low-priority issues but
probably not urgent.

## Theme

A lot of the fragility across both printers comes from sharing state
between primary and auxiliary printer instances via raw pointers and
ad-hoc "use this one, not that one" rules. A refactor that makes the
auxiliary's role purely a *view* over a shared `HDF5File` object (so
there are no per-printer file/group handles to forget to initialise)
would eliminate this whole class of bug. Big change, but probably worth
scoping if you're touching this code anyway.
