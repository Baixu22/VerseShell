//! MCP wire protocol: JSON-RPC 2.0 over stdio with dual framing.
//!
//! Supports two input formats (auto-detected per message):
//!   1. **JSON-line**: a single JSON object terminated by `\n`.
//!   2. **Content-Length framed**: headers (`Content-Length: N\r\n`) terminated
//!      by `\r\n`, followed by N bytes of JSON body.
//!
//! Output format mirrors the input format of the corresponding request, so a
//! client that sends JSON-line requests receives JSON-line responses, and a
//! client that sends framed requests receives framed responses.
//!
//! Notifications (requests without an `id`) receive no response, per JSON-RPC.

use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncReadExt, AsyncWrite, AsyncWriteExt};

// ── JSON-RPC 2.0 types ──────────────────────────────────────────────

#[derive(Debug, Deserialize)]
pub struct JsonRpcRequest {
    pub jsonrpc: String,
    /// `None` for notifications (no response expected).
    #[serde(default)]
    pub id: Option<Value>,
    pub method: String,
    #[serde(default)]
    pub params: Value,
}

#[derive(Debug, Serialize)]
pub struct JsonRpcResponse {
    pub jsonrpc: String,
    pub id: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<JsonRpcError>,
}

#[derive(Debug, Serialize)]
pub struct JsonRpcError {
    pub code: i64,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
}

impl JsonRpcResponse {
    pub fn ok(id: Value, result: Value) -> Self {
        Self {
            jsonrpc: "2.0".into(),
            id,
            result: Some(result),
            error: None,
        }
    }

    pub fn error(id: Value, code: i64, message: impl Into<String>, data: Option<Value>) -> Self {
        Self {
            jsonrpc: "2.0".into(),
            id,
            result: None,
            error: Some(JsonRpcError {
                code,
                message: message.into(),
                data,
            }),
        }
    }
}

// ── Framing ─────────────────────────────────────────────────────────

/// A parsed inbound message with the framing format it arrived in.
/// The same format is used to encode the matching response.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Framing {
    /// Single-line JSON terminated by `\n`.
    JsonLine,
    /// `Content-Length: N\r\n\r\n<body>` framing (LSP/MCP standard).
    ContentLength,
}

/// Read one message from `reader`, auto-detecting framing.
///
/// Returns `Ok(None)` at EOF (stdin closed). Returns `Ok(Some(msg))` with the
/// message body and detected framing. The body is a JSON string ready to be
/// parsed into `JsonRpcRequest`.
pub async fn read_message<R: AsyncBufRead + Unpin>(
    reader: &mut R,
) -> Result<Option<(String, Framing)>> {
    // Loop to skip stray blank lines between messages (some clients emit `\r\n`
    // separators). Using a loop instead of recursion avoids the async-fn
    // recursion boxing requirement.
    loop {
        let mut line = String::new();
        let n = reader.read_line(&mut line).await?;
        if n == 0 {
            return Ok(None); // EOF
        }
        if line.trim().is_empty() {
            continue; // skip blank separator line
        }

        if line.starts_with("Content-Length:") || line.starts_with("content-length:") {
            // Framed mode. Parse headers until blank line, then read body.
            let content_length = parse_content_length_header(&line)?
                .ok_or_else(|| anyhow!("Content-Length header missing value"))?;
            // Consume remaining headers until empty line.
            loop {
                let mut hdr = String::new();
                let hn = reader.read_line(&mut hdr).await?;
                if hn == 0 {
                    return Err(anyhow!("unexpected EOF in framed headers"));
                }
                if hdr.trim().is_empty() {
                    break;
                }
                // Ignore other headers (Content-Type, etc).
            }
            // Read exactly `content_length` bytes of body.
            let mut buf = vec![0u8; content_length];
            reader.read_exact(&mut buf).await?;
            let body = String::from_utf8(buf)?;
            return Ok(Some((body, Framing::ContentLength)));
        } else {
            // JSON-line mode. The line (minus trailing newline) is the body.
            let body = line.trim_end_matches(&['\r', '\n'][..]).to_string();
            if body.is_empty() {
                continue; // skip empty JSON-line
            }
            return Ok(Some((body, Framing::JsonLine)));
        }
    }
}

fn parse_content_length_header(line: &str) -> Result<Option<usize>> {
    let trimmed = line.trim_end_matches(&['\r', '\n'][..]);
    let (_, value) = trimmed
        .split_once(':')
        .ok_or_else(|| anyhow!("malformed header line: {line:?}"))?;
    let v: usize = value.trim().parse()?;
    Ok(Some(v))
}

/// Write one message to `writer` using the given framing.
pub async fn write_message<W: AsyncWrite + Unpin>(
    writer: &mut W,
    body: &str,
    framing: Framing,
) -> Result<()> {
    match framing {
        Framing::JsonLine => {
            writer.write_all(body.as_bytes()).await?;
            writer.write_all(b"\n").await?;
        }
        Framing::ContentLength => {
            let header = format!("Content-Length: {}\r\n\r\n", body.as_bytes().len());
            writer.write_all(header.as_bytes()).await?;
            writer.write_all(body.as_bytes()).await?;
        }
    }
    writer.flush().await?;
    Ok(())
}
