# Frozen experiment platform scope

This catalogue implements the supervisor notes from 9 September 2026.

Blocking benchmarks:

- BSBM
- KROWN synthetic
- DBBench

Deferred: RETE, WatDiv, WDBench, and the external QLever benchmark.

BSBM 10k starts only when the coverage audit says `ready_for_bsbm_10k: true`.

Required comparisons include COTTAS plus RDFLib, Vortex by-reference and by-copy in memory and on file, HDT plus RDFLib, native Oxigraph memory and RocksDB, PyOxigraph plus RDFLib, plain RDFLib, Fuseki memory and TDB2, QLever, and Virtuoso.

Required metrics include query time, query RAM, cold and warm load time, build time, build RAM, persistent size, correctness, and failure class. Persistent size is not applicable to transient memory-only setups.

All final reports must include JSON, CSV, Markdown, and Excel. The Patch 6A audit writes Excel-ready rows. The report writer will create the final XLSX workbook.

OOM means a confirmed process crash from memory exhaustion. Dataset size alone does not mean OOM.
