# Parser fuzzing lane

Initial parser targets:

- `PBG3` archive header parsing and LZSS decompression;
- replay validation and deobfuscation;
- stage `.std` loading and object/script walking.

The tracked Python code in `src/danmakufuzz/corpus/pbg3.py` provides a clean
reference parser for corpus extraction and format understanding. Native
harnesses under `fuzzers/parser/` will target the original or reconstructed C++
implementations for sanitizer-backed fuzzing.
