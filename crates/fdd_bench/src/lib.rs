//! Benchmarks and pandas-vs-SQL parity comparison.

pub mod benchmark;
pub mod compare;

pub use benchmark::{run_benchmark, BenchmarkReport};
pub use compare::{compare_results, write_compare_markdown, CompareReport};
