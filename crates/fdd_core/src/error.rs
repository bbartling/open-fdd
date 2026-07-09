use thiserror::Error;

#[derive(Debug, Error)]
pub enum CoreError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("CSV error: {0}")]
    Csv(#[from] csv::Error),
    #[error("validation: {0}")]
    Validation(String),
    #[error("missing file: {0}")]
    MissingFile(String),
}

pub type Result<T> = std::result::Result<T, CoreError>;
