//! Typed application errors. Tauri commands and the HTTP layer both surface
//! these; HTTP maps each variant to a status code, and `Display` renders the
//! user-facing Chinese message the frontend already expects.

use serde::Serialize;

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("账号不存在: {0}")]
    NotFound(String),
    #[error("{0}")]
    Validation(String),
    #[error("该账号浏览器已在运行")]
    AlreadyRunning,
    /// launch/stop filesystem or process failures carrying a user-facing message.
    #[error("{0}")]
    Operation(String),
    /// Low-level storage/IO failures; messages may contain OS error detail.
    #[error("{0}")]
    Io(String),
}

impl AppError {
    /// Status code the HTTP API should return for this error.
    pub fn http_status(&self) -> u16 {
        match self {
            AppError::NotFound(_) => 404,
            AppError::Validation(_) | AppError::AlreadyRunning => 400,
            AppError::Operation(_) => 400,
            AppError::Io(_) => 500,
        }
    }
}

impl From<String> for AppError {
    fn from(e: String) -> Self {
        AppError::Operation(e)
    }
}

/// Tauri commands require the error type to impl Serialize (it becomes the
/// string rejection the frontend already handles) + Display + Debug.
impl Serialize for AppError {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.to_string())
    }
}

pub type AppResult<T> = Result<T, AppError>;
