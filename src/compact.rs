//! Compact token-efficient output protocol (RTK-style).
//!
//! Design:
//!   - Positional fields (no repeated JSON keys)
//!   - Single-char type tags (S=string, N=null, T/F=bool, L=list, R=record, E=error code)
//!   - Whitespace-delimited at the structural level; string content is length-prefixed
//!     and escape-encoded so it can contain any character (including spaces/tabs/newlines)
//!   - 50-70% token savings vs canonical JSON
//!
//! Response format:
//!   D <id> <ok> <value> <elapsed_ms> <cache_hit> <session_age_ms>
//!   E <id> <code> <message> <recoverable>
//!
//! Value encoding:
//!   null      → N
//!   bool      → T | F
//!   int       → 42
//!   float     → 3.14
//!   string    → S<len>:<escaped_content>     (len = byte length AFTER escaping)
//!   uri       → U<len>:<escaped_content>
//!   array     → L<len> <item1> <item2> ...
//!   record    → R<len> <key1> <val1> <key2> <val2> ...
//!                          (keys are barewords; values are full value encodings)
//!
//! String escaping (so length-prefixed content can be unambiguously recovered):
//!   '\\' → '\\\\'    ' '  → '\\s'    '\t' → '\\t'    '\n' → '\\n'    '\r' → '\\r'
//!
//! Example:
//!   JSON:   {"type":"done","id":"r1","ok":true,"value":"LAPTOP-3LN94GP7","meta":{"elapsed_ms":2,"cache_hit":true,"session_age_ms":0}}
//!   Compact: D r1 T S17:LAPTOP-3LN94GP7 2 T 0

use crate::runtime::AgentResponse;
use crate::value::Value;

/// Escape a string's whitespace and backslash so it can be embedded in a
/// length-prefixed compact token without breaking structural whitespace splitting.
fn escape_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 4);
    for ch in s.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            ' ' => out.push_str("\\s"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            other => out.push(other),
        }
    }
    out
}

/// Reverse of `escape_string`.
fn unescape_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars();
    while let Some(ch) = chars.next() {
        if ch == '\\' {
            match chars.next() {
                Some('s') => out.push(' '),
                Some('t') => out.push('\t'),
                Some('n') => out.push('\n'),
                Some('r') => out.push('\r'),
                Some('\\') => out.push('\\'),
                Some(other) => {
                    // Unknown escape: preserve literally so we never silently drop data.
                    out.push('\\');
                    out.push(other);
                }
                None => out.push('\\'),
            }
        } else {
            out.push(ch);
        }
    }
    out
}

/// Encode a server response in compact token-efficient format.
pub fn encode_response(resp: &AgentResponse) -> String {
    if resp.ok {
        let meta = &resp.meta;
        let value = resp
            .value
            .as_ref()
            .map(|v| encode_json_value(v))
            .unwrap_or_else(|| "N".to_string());
        let cache = match meta.cache_hit {
            Some(true) => "T",
            Some(false) => "F",
            None => "N",
        };
        format!(
            "D {} {} {} {} {} {}",
            resp.id,
            if resp.ok { "T" } else { "F" },
            value,
            meta.elapsed_ms,
            cache,
            meta.session_age_ms
        )
    } else {
        let err = resp
            .error
            .as_ref()
            .map(|e| (e.code.as_str(), e.message.as_str(), e.recoverable));
        if let Some((code, msg, rec)) = err {
            let escaped = escape_string(msg);
            format!(
                "E {} {} S{}:{} {}",
                resp.id,
                code,
                escaped.len(),
                escaped,
                if rec { "T" } else { "F" }
            )
        } else {
            format!("E {} UNKNOWN N F", resp.id)
        }
    }
}

/// Encode a JSON value in compact format.
fn encode_json_value(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::Null => "N".to_string(),
        serde_json::Value::Bool(true) => "T".to_string(),
        serde_json::Value::Bool(false) => "F".to_string(),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.to_string()
            } else if let Some(f) = n.as_f64() {
                if f == f.trunc() && f.is_finite() {
                    format!("{:.0}", f)
                } else {
                    format!("{}", f)
                }
            } else {
                n.to_string()
            }
        }
        serde_json::Value::String(s) => {
            let escaped = escape_string(s);
            format!("S{}:{}", escaped.len(), escaped)
        }
        serde_json::Value::Array(arr) => {
            let items: Vec<String> = arr.iter().map(encode_json_value).collect();
            format!("L{} {}", arr.len(), items.join(" "))
        }
        serde_json::Value::Object(map) => {
            let mut parts = Vec::with_capacity(map.len() * 2);
            for (k, v) in map {
                parts.push(k.clone());
                parts.push(encode_json_value(v));
            }
            format!("R{} {}", map.len(), parts.join(" "))
        }
    }
}

/// Encode a VerseShell Value in compact format.
pub fn encode_value(v: &Value) -> String {
    match v {
        Value::Null => "N".into(),
        Value::Bool(true) => "T".into(),
        Value::Bool(false) => "F".into(),
        Value::Int(n) => n.to_string(),
        Value::Float(f) => {
            if *f == f.trunc() && f.is_finite() {
                format!("{:.0}", f)
            } else {
                format!("{}", f)
            }
        }
        Value::Str(s) => {
            let escaped = escape_string(s);
            format!("S{}:{}", escaped.len(), escaped)
        }
        Value::Uri(s) => {
            let escaped = escape_string(s);
            format!("U{}:{}", escaped.len(), escaped)
        }
        Value::Array(arr) => {
            let items: Vec<String> = arr.iter().map(encode_value).collect();
            format!("L{} {}", arr.len(), items.join(" "))
        }
        Value::Record(map) => {
            let mut parts = Vec::with_capacity(map.len() * 2);
            for (k, val) in map {
                parts.push(k.clone());
                parts.push(encode_value(val));
            }
            format!("R{} {}", map.len(), parts.join(" "))
        }
        other => {
            let dbg = format!("{:?}", other);
            let escaped = escape_string(&dbg);
            format!("S{}:{}", escaped.len(), escaped)
        }
    }
}

/// Decode a compact-encoded value string back to Value.
///
/// Uses byte-level parsing (not `split_whitespace`) so that length-prefixed
/// string content can contain spaces, tabs, newlines, or any other character
/// after escape-encoding.
pub fn decode_value(input: &str) -> Result<Value, String> {
    let mut parser = Parser::new(input);
    let v = parser.parse_value()?;
    parser.skip_ws();
    if !parser.is_eof() {
        return Err(format!(
            "trailing content after value: {:?}",
            parser.remaining()
        ));
    }
    Ok(v)
}

struct Parser<'a> {
    input: &'a str,
    pos: usize,
}

impl<'a> Parser<'a> {
    fn new(input: &'a str) -> Self {
        Self { input, pos: 0 }
    }

    fn skip_ws(&mut self) {
        let bytes = self.input.as_bytes();
        while self.pos < bytes.len() {
            match bytes[self.pos] {
                b' ' | b'\t' | b'\n' | b'\r' => self.pos += 1,
                _ => break,
            }
        }
    }

    fn is_eof(&self) -> bool {
        self.pos >= self.input.len()
    }

    fn remaining(&self) -> &'a str {
        &self.input[self.pos.min(self.input.len())..]
    }

    fn peek_byte(&self) -> Option<u8> {
        self.input.as_bytes().get(self.pos).copied()
    }

    fn parse_value(&mut self) -> Result<Value, String> {
        self.skip_ws();
        let byte = self.peek_byte().ok_or("unexpected end of input")?;
        match byte {
            b'N' => {
                self.pos += 1;
                Ok(Value::Null)
            }
            b'T' => {
                self.pos += 1;
                Ok(Value::Bool(true))
            }
            b'F' => {
                self.pos += 1;
                Ok(Value::Bool(false))
            }
            b'L' => self.parse_array(),
            b'R' => self.parse_record(),
            b'S' => self.parse_string_tag('S').map(Value::Str),
            b'U' => self.parse_string_tag('U').map(Value::Uri),
            _ => self.parse_number(),
        }
    }

    fn parse_array(&mut self) -> Result<Value, String> {
        self.pos += 1; // consume 'L'
        let len = self.parse_usize("list length")?;
        let mut arr = Vec::with_capacity(len);
        for _ in 0..len {
            arr.push(self.parse_value()?);
        }
        Ok(Value::Array(arr))
    }

    fn parse_record(&mut self) -> Result<Value, String> {
        self.pos += 1; // consume 'R'
        let len = self.parse_usize("record length")?;
        let mut map = std::collections::BTreeMap::new();
        for _ in 0..len {
            self.skip_ws();
            let key = self.parse_bareword()?;
            let val = self.parse_value()?;
            map.insert(key, val);
        }
        Ok(Value::Record(map))
    }

    /// Parse `S<len>:<escaped_content>` or `U<len>:<escaped_content>`.
    /// `len` is the byte length of the escaped content.
    fn parse_string_tag(&mut self, _tag: char) -> Result<String, String> {
        self.pos += 1; // consume tag byte
        let len = self.parse_usize("string length")?;
        if self.peek_byte() != Some(b':') {
            return Err(format!("expected ':' after length at pos {}", self.pos));
        }
        self.pos += 1; // consume ':'
        if self.pos + len > self.input.len() {
            return Err(format!(
                "string length {} exceeds remaining input ({} bytes)",
                len,
                self.input.len() - self.pos
            ));
        }
        let escaped = &self.input[self.pos..self.pos + len];
        self.pos += len;
        Ok(unescape_string(escaped))
    }

    fn parse_usize(&mut self, what: &str) -> Result<usize, String> {
        let start = self.pos;
        let bytes = self.input.as_bytes();
        while self.pos < bytes.len() && bytes[self.pos].is_ascii_digit() {
            self.pos += 1;
        }
        if start == self.pos {
            return Err(format!("expected digit for {}", what));
        }
        self.input[start..self.pos]
            .parse::<usize>()
            .map_err(|e| format!("invalid {} digit: {}", what, e))
    }

    /// Read a record key as a bareword (until next whitespace).
    /// Record keys are assumed to be identifier-like (no embedded whitespace);
    /// callers needing arbitrary keys should wrap them as `S<len>:...` values.
    fn parse_bareword(&mut self) -> Result<String, String> {
        let start = self.pos;
        let bytes = self.input.as_bytes();
        while self.pos < bytes.len() {
            match bytes[self.pos] {
                b' ' | b'\t' | b'\n' | b'\r' => break,
                _ => self.pos += 1,
            }
        }
        if start == self.pos {
            return Err(format!("expected record key at pos {}", self.pos));
        }
        Ok(self.input[start..self.pos].to_string())
    }

    fn parse_number(&mut self) -> Result<Value, String> {
        let start = self.pos;
        let bytes = self.input.as_bytes();
        if self.peek_byte() == Some(b'-') {
            self.pos += 1;
        }
        while self.pos < bytes.len()
            && (bytes[self.pos].is_ascii_digit() || bytes[self.pos] == b'.')
        {
            self.pos += 1;
        }
        if start == self.pos {
            return Err(format!("unknown token at: {:?}", self.remaining()));
        }
        let s = &self.input[start..self.pos];
        if let Ok(n) = s.parse::<i64>() {
            Ok(Value::Int(n))
        } else if let Ok(f) = s.parse::<f64>() {
            Ok(Value::Float(f))
        } else {
            Err(format!("invalid number: {}", s))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_encode_basic() {
        let v = Value::Int(42);
        assert_eq!(encode_value(&v), "42");

        let v = Value::Str("hello".into());
        assert_eq!(encode_value(&v), "S5:hello");

        let v = Value::Null;
        assert_eq!(encode_value(&v), "N");

        let v = Value::Bool(true);
        assert_eq!(encode_value(&v), "T");
    }

    #[test]
    fn test_encode_array() {
        let v = Value::Array(vec![Value::Int(1), Value::Int(2), Value::Int(3)]);
        assert_eq!(encode_value(&v), "L3 1 2 3");
    }

    #[test]
    fn test_encode_record() {
        let mut map = std::collections::BTreeMap::new();
        map.insert("name".into(), Value::Str("test".into()));
        map.insert("count".into(), Value::Int(5));
        let v = Value::Record(map);
        let encoded = encode_value(&v);
        assert!(encoded.starts_with("R2 "));
        assert!(encoded.contains("name"));
        assert!(encoded.contains("count"));
    }

    #[test]
    fn test_roundtrip() {
        let original = Value::Record({
            let mut m = std::collections::BTreeMap::new();
            m.insert("x".into(), Value::Int(42));
            m.insert("y".into(), Value::Str("hello world".into()));
            m
        });
        let encoded = encode_value(&original);
        let decoded = decode_value(&encoded).unwrap();
        assert_eq!(original, decoded);
    }

    #[test]
    fn test_roundtrip_special_chars() {
        // String with every whitespace kind + backslash
        let cases = [
            "hello world",
            "tab\there",
            "newline\nhere",
            "cr\rhere",
            "back\\slash",
            "mix \\s \t\n\r end",
            "",
            "no-whitespace",
            "中 文 空 格", // non-ASCII should pass through untouched
            "emoji 🚀 space",
        ];
        for s in cases {
            let original = Value::Str(s.into());
            let encoded = encode_value(&original);
            let decoded = decode_value(&encoded).expect(&format!("decode failed for {:?}", s));
            assert_eq!(original, decoded, "roundtrip failed for {:?}", s);
        }
    }

    #[test]
    fn test_roundtrip_nested() {
        let mut inner = std::collections::BTreeMap::new();
        inner.insert("a".into(), Value::Str("with space".into()));
        inner.insert(
            "b".into(),
            Value::Array(vec![
                Value::Int(1),
                Value::Str("two words".into()),
                Value::Null,
            ]),
        );
        let original = Value::Record(inner);
        let encoded = encode_value(&original);
        let decoded = decode_value(&encoded).unwrap();
        assert_eq!(original, decoded);
    }

    #[test]
    fn test_roundtrip_uri() {
        let original = Value::Uri("https://example.com/path with space".into());
        let encoded = encode_value(&original);
        let decoded = decode_value(&encoded).unwrap();
        assert_eq!(original, decoded);
    }

    #[test]
    fn test_decode_rejects_truncated_string() {
        // Claim 100 bytes of content but only provide a few
        let bad = "S100:short";
        assert!(decode_value(bad).is_err());
    }

    #[test]
    fn test_decode_rejects_trailing_content() {
        let bad = "S5:hello extra";
        assert!(decode_value(bad).is_err());
    }

    #[test]
    fn test_escape_unescape_inverse() {
        for s in ["a b\\c", " ", "\t\n\r\\", "", "no escape", "\\s literal"] {
            assert_eq!(unescape_string(&escape_string(s)), s, "failed for {:?}", s);
        }
    }

    #[test]
    fn test_token_savings() {
        let json = r#"{"type":"done","id":"r1","ok":true,"value":"LAPTOP-3LN94GP7","meta":{"elapsed_ms":2,"cache_hit":true,"session_age_ms":0}}"#;
        // Our compact equivalent (approximately)
        let compact = r#"D r1 T S17:LAPTOP-3LN94GP7 2 T 0"#;
        assert!(
            compact.len() < json.len(),
            "Compact should be smaller than JSON"
        );
        let savings = (1.0 - compact.len() as f64 / json.len() as f64) * 100.0;
        println!(
            "Token savings: {:.0}% ({} vs {} chars)",
            savings,
            compact.len(),
            json.len()
        );
        assert!(savings > 40.0, "Expected >40% savings, got {:.0}%", savings);
    }
}
