//! Benchmarks and pandas-vs-SQL parity comparison.

pub mod benchmark;
pub mod compare;
pub mod parity;

pub use benchmark::{run_benchmark, BenchmarkReport};
pub use compare::{compare_results, write_compare_markdown, CompareReport};
pub use parity::{overlap_class, run_parity, ParitySummary};
