//! User library of images and documents. The API never decodes a file sent by a user:
//! image-guard, an isolated container without network or data, re-encodes images first, and
//! only that clean copy is stored, displayed and sent to Qwen. Documents go to doc-guard (see
//! documents.rs).
use crate::{App, Error, documents, session};
use axum::{
    Json,
    body::{Body, Bytes},
    extract::{Path, Query, State},
    http::{HeaderMap, HeaderValue, StatusCode, header},
    response::{IntoResponse, Response},
};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::types::Json as DbJson;
use std::{collections::HashMap, time::Duration};
use uuid::Uuid;

pub const QUOTA_BYTES: i64 = 500 * 1024 * 1024;
pub const MAX_UPLOAD: usize = 12 * 1024 * 1024;
pub const MAX_PER_MESSAGE: usize = 5;

#[derive(Clone, Copy, Default, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    #[default]
    Image,
    Document,
}
impl Kind {
    fn is_image(&self) -> bool { *self == Kind::Image }
}
fn is_zero(value: &u32) -> bool { *value == 0 }

/// Reference kept in a user message; the image or document itself stays in the library.
#[derive(Clone, PartialEq, Deserialize, Serialize)]
pub struct AttachmentRef {
    pub id: Uuid,
    pub name: String,
    #[serde(default, skip_serializing_if = "Kind::is_image")]
    pub kind: Kind,
    /// Images only; 0 for documents.
    #[serde(default)]
    pub width: u32,
    #[serde(default)]
    pub height: u32,
    /// Documents only: pages of a PDF (0 for Word and text files) and size of their Markdown.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub pages: u32,
    #[serde(default, skip_serializing_if = "is_zero")]
    pub tokens: u32,
}
impl AttachmentRef {
    pub fn is_valid(&self) -> bool {
        self.name.chars().count() <= 120 && match self.kind {
            Kind::Image => (1..=4096).contains(&self.width) && (1..=4096).contains(&self.height) && self.pages == 0 && self.tokens == 0,
            Kind::Document => self.width == 0 && self.height == 0 && self.pages <= documents::MAX_PAGES && (1..=documents::MAX_TOKENS).contains(&self.tokens),
        }
    }
}

/// Tokens Qwen counts for an image, measured on the live model: one per 32 x 32 pixel square
/// (dimensions rounded to the nearest multiple, halves to even like Python), at least 64, plus
/// two markers.
pub fn image_tokens(width: u32, height: u32) -> u64 {
    let side = |v: u32| ((v as f64) / 32.0).round_ties_even().max(1.0) as u64;
    (side(width) * side(height)).max(64) + 2
}

fn clean_name(name: Option<&str>, fallback: &str) -> String {
    let name: String = name.unwrap_or("").chars().filter(|c| !c.is_control() && !matches!(c, '/' | '\\')).take(120).collect();
    let name = name.trim();
    if name.is_empty() { fallback.to_string() } else { name.to_string() }
}

struct Clean {
    mime: String,
    width: i32,
    height: i32,
    data: Vec<u8>,
    thumbnail: Vec<u8>,
}

async fn sanitize(app: &App, body: Bytes) -> Result<Clean, Error> {
    let unavailable = || Error(StatusCode::SERVICE_UNAVAILABLE, "Le traitement des images est indisponible. Réessaie dans un instant.".into());
    let response = app.http.post(format!("{}/sanitize", app.config.image_guard))
        .timeout(Duration::from_secs(40)).body(body).send().await.map_err(|_| unavailable())?;
    let status = response.status();
    let value: Value = response.json().await.map_err(|_| unavailable())?;
    if status == StatusCode::UNPROCESSABLE_ENTITY {
        let message = value.get("error").and_then(Value::as_str).unwrap_or("Image refusée.");
        return Err(Error::bad(message));
    }
    if !status.is_success() {
        return Err(unavailable());
    }
    let field = |name: &str| value.get(name).and_then(Value::as_str).and_then(|v| STANDARD.decode(v).ok());
    let size = |name: &str| value.get(name).and_then(Value::as_u64).filter(|v| (1..=4096).contains(v)).map(|v| v as i32);
    let mime = value.get("mime").and_then(Value::as_str).filter(|m| matches!(*m, "image/jpeg" | "image/png"));
    match (mime, size("width"), size("height"), field("data"), field("thumbnail")) {
        (Some(mime), Some(width), Some(height), Some(data), Some(thumbnail)) if !data.is_empty() && !thumbnail.is_empty() =>
            Ok(Clean { mime: mime.to_string(), width, height, data, thumbnail }),
        _ => Err(unavailable()),
    }
}

async fn used_bytes(app: &App, user: Uuid) -> Result<i64, Error> {
    Ok(sqlx::query_scalar("SELECT coalesce(sum(size + octet_length(thumbnail) + coalesce(octet_length(content), 0)), 0)::bigint FROM attachments WHERE user_id=$1")
        .bind(user).fetch_one(&app.db).await?)
}

#[derive(Deserialize)]
pub struct UploadQuery {
    name: Option<String>,
}

pub async fn upload(
    State(app): State<App>,
    headers: HeaderMap,
    Query(query): Query<UploadQuery>,
    body: Bytes,
) -> Result<(StatusCode, Json<Value>), Error> {
    let user = session(&app, &headers, true).await?;
    let document = documents::is_document(&body);
    if body.is_empty() || body.len() > if document { documents::MAX_UPLOAD } else { MAX_UPLOAD } {
        return Err(Error::bad(if document { "Document vide ou trop lourd (20 Mo au maximum)." } else { "Image vide ou trop lourde (12 Mo au maximum)." }));
    }
    if used_bytes(&app, user.user_id).await? + body.len() as i64 > QUOTA_BYTES {
        return Err(Error::bad("Ta bibliothèque est pleine (500 Mo). Supprime des fichiers avant d’en envoyer d’autres."));
    }
    if document {
        let name = clean_name(query.name.as_deref(), "document");
        return Ok((StatusCode::CREATED, Json(documents::upload(&app, user.user_id, name, body).await?)));
    }
    let clean = sanitize(&app, body).await?;
    let sha = hex::encode(Sha256::digest(&clean.data));
    let name = clean_name(query.name.as_deref(), if clean.mime == "image/png" { "image.png" } else { "image.jpg" });
    // The same image sent twice is stored once: the existing entry is returned.
    let (id, name, width, height, size): (Uuid, String, i32, i32, i32) = sqlx::query_as(
        "INSERT INTO attachments(id,user_id,sha256,kind,name,mime,width,height,size,data,thumbnail) VALUES($1,$2,$3,'image',$4,$5,$6,$7,$8,$9,$10)
         ON CONFLICT (user_id,sha256) DO UPDATE SET sha256=EXCLUDED.sha256 RETURNING id,name,width,height,size")
        .bind(Uuid::new_v4()).bind(user.user_id).bind(&sha).bind(&name).bind(&clean.mime).bind(clean.width).bind(clean.height)
        .bind(clean.data.len() as i32).bind(&clean.data).bind(&clean.thumbnail).fetch_one(&app.db).await?;
    Ok((StatusCode::CREATED, Json(json!({"id": id, "name": name, "width": width, "height": height, "size": size}))))
}

/// A document is `reading` while Qwen lays out its pages (`progress` of `pages` done), then
/// `ready` or `failed` with an `error` for the user.
#[derive(Serialize, sqlx::FromRow)]
struct Item {
    id: Uuid,
    name: String,
    kind: String,
    mime: String,
    width: i32,
    height: i32,
    size: i32,
    created_at: chrono::DateTime<chrono::Utc>,
    status: String,
    pages: i32,
    progress: i32,
    scanned: i32,
    doubts: i32,
    tokens: i32,
    error: Option<String>,
}
const ITEM: &str = "SELECT id,name,kind,mime,width,height,size,created_at,status,pages,progress,scanned,doubts,tokens,error FROM attachments";

pub async fn item(app: &App, user: Uuid, id: Uuid) -> Result<Value, Error> {
    let found: Item = sqlx::query_as(&format!("{ITEM} WHERE id=$1 AND user_id=$2")).bind(id).bind(user)
        .fetch_optional(&app.db).await?.ok_or_else(|| Error(StatusCode::NOT_FOUND, "Fichier introuvable.".into()))?;
    Ok(json!(found))
}

/// Followed by the page while a document is being read.
pub async fn status(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, false).await?;
    Ok(Json(item(&app, user.user_id, id).await?))
}

/// Markdown read from a document, as Qwen will receive it.
pub async fn text(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, false).await?;
    let content = document_text(&app, user.user_id, id).await.ok_or_else(|| Error(StatusCode::NOT_FOUND, "Texte introuvable.".into()))?;
    Ok(Json(json!({"content": content})))
}

pub async fn list(State(app): State<App>, headers: HeaderMap) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, false).await?;
    let items: Vec<Item> = sqlx::query_as(&format!("{ITEM} WHERE user_id=$1 ORDER BY created_at DESC LIMIT 5000"))
        .bind(user.user_id).fetch_all(&app.db).await?;
    Ok(Json(json!({"items": items, "used_bytes": used_bytes(&app, user.user_id).await?, "quota_bytes": QUOTA_BYTES})))
}

#[derive(Deserialize)]
pub struct FileQuery {
    #[serde(default)]
    download: bool,
}

fn disposition(name: &str, download: bool) -> HeaderValue {
    let encoded: String = name.bytes().map(|b| if b.is_ascii_alphanumeric() || b"-._".contains(&b) { (b as char).to_string() } else { format!("%{b:02X}") }).collect();
    let kind = if download { "attachment" } else { "inline" };
    HeaderValue::from_str(&format!("{kind}; filename*=UTF-8''{encoded}")).unwrap_or(HeaderValue::from_static("inline"))
}

fn image_response(headers: &HeaderMap, etag: String, mime: &str, data: Vec<u8>, disposition: Option<HeaderValue>) -> Response {
    let etag = HeaderValue::from_str(&format!("\"{etag}\"")).expect("hex etag");
    let mut response = if headers.get(header::IF_NONE_MATCH) == Some(&etag) {
        StatusCode::NOT_MODIFIED.into_response()
    } else {
        let mut response = Body::from(data).into_response();
        response.headers_mut().insert(header::CONTENT_TYPE, HeaderValue::from_str(mime).expect("known mime"));
        if let Some(value) = disposition { response.headers_mut().insert(header::CONTENT_DISPOSITION, value); }
        response
    };
    let out = response.headers_mut();
    out.insert(header::ETAG, etag);
    // Revalidated each time (a cheap 304): a deleted image disappears from every message at once.
    out.insert(header::CACHE_CONTROL, HeaderValue::from_static("private, no-cache"));
    // Opened directly in a tab, the file can run nothing.
    out.insert(header::CONTENT_SECURITY_POLICY, HeaderValue::from_static("default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"));
    response
}

pub async fn file(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>, Query(query): Query<FileQuery>) -> Result<Response, Error> {
    let user = session(&app, &headers, false).await?;
    let (name, kind, mime, sha, data): (String, String, String, String, Vec<u8>) = sqlx::query_as("SELECT name,kind,mime,sha256,data FROM attachments WHERE id=$1 AND user_id=$2")
        .bind(id).bind(user.user_id).fetch_optional(&app.db).await?.ok_or_else(Error::missing)?;
    // Documents are never shown by the browser itself: always downloaded.
    Ok(image_response(&headers, sha, &mime, data, Some(disposition(&name, query.download || kind == "document"))))
}

pub async fn thumbnail(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<Response, Error> {
    let user = session(&app, &headers, false).await?;
    let (sha, data): (String, Vec<u8>) = sqlx::query_as("SELECT sha256,thumbnail FROM attachments WHERE id=$1 AND user_id=$2 AND kind='image'")
        .bind(id).bind(user.user_id).fetch_optional(&app.db).await?.ok_or_else(Error::missing)?;
    Ok(image_response(&headers, format!("{sha}-t"), "image/jpeg", data, None))
}

/// Conversations of the user whose messages show this image, most recent first.
pub async fn conversations(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, false).await?;
    let rows: Vec<(Uuid, String)> = sqlx::query_as("SELECT id,title FROM conversations WHERE user_id=$1 AND messages @> $2 ORDER BY updated_at DESC LIMIT 50")
        .bind(user.user_id).bind(DbJson(json!([{"attachments": [{"id": id}]}]))).fetch_all(&app.db).await?;
    Ok(Json(json!(rows.into_iter().map(|(id, title)| json!({"id": id, "title": title})).collect::<Vec<_>>())))
}

pub async fn delete(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<StatusCode, Error> {
    let user = session(&app, &headers, true).await?;
    let done = sqlx::query("DELETE FROM attachments WHERE id=$1 AND user_id=$2").bind(id).bind(user.user_id).execute(&app.db).await?;
    if done.rows_affected() == 0 { return Err(Error::missing()); }
    Ok(StatusCode::NO_CONTENT)
}

/// Refuses references to files the user does not own (kept references to deleted files
/// excepted), and documents not read yet or described differently from the library.
pub async fn check_owned(app: &App, user: Uuid, refs: &[&AttachmentRef]) -> Result<(), Error> {
    if refs.is_empty() { return Ok(()); }
    let ids: Vec<Uuid> = refs.iter().map(|a| a.id).collect();
    let rows: Vec<(Uuid, String, String, i32, i32)> = sqlx::query_as("SELECT id,kind,status,pages,tokens FROM attachments WHERE user_id=$1 AND id = ANY($2)")
        .bind(user).bind(&ids).fetch_all(&app.db).await?;
    let found: HashMap<Uuid, (String, String, i32, i32)> = rows.into_iter().map(|(id, kind, status, pages, tokens)| (id, (kind, status, pages, tokens))).collect();
    for attachment in refs {
        let Some((kind, status, pages, tokens)) = found.get(&attachment.id) else { return Err(Error::bad("Un fichier joint est introuvable dans ta bibliothèque.")); };
        if attachment.kind == Kind::Document && status == "reading" { return Err(Error::bad("Un document joint est encore en cours de lecture.")); }
        let same = match attachment.kind {
            Kind::Image => kind == "image",
            Kind::Document => kind == "document" && status == "ready" && *pages as u32 == attachment.pages && *tokens as u32 == attachment.tokens,
        };
        if !same { return Err(Error::bad("Un fichier joint est introuvable dans ta bibliothèque.")); }
    }
    Ok(())
}

pub struct Stored {
    pub mime: String,
    pub data: Vec<u8>,
    pub transcript: Option<String>,
    /// Markdown of a document.
    pub content: Option<String>,
}

/// Images with their data, documents with their Markdown (never their original file).
pub async fn load(app: &App, user: Uuid, ids: &[Uuid]) -> Result<HashMap<Uuid, Stored>, Error> {
    let rows: Vec<(Uuid, String, Vec<u8>, Option<String>, Option<String>)> = sqlx::query_as(
        "SELECT id,mime,CASE WHEN kind='image' THEN data ELSE ''::bytea END,transcript,content FROM attachments WHERE user_id=$1 AND id = ANY($2) AND status='ready'")
        .bind(user).bind(ids).fetch_all(&app.db).await?;
    Ok(rows.into_iter().map(|(id, mime, data, transcript, content)| (id, Stored { mime, data, transcript, content })).collect())
}

pub async fn document_text(app: &App, user: Uuid, id: Uuid) -> Option<String> {
    load(app, user, &[id]).await.ok()?.remove(&id)?.content
}

pub fn data_url(stored: &Stored) -> String {
    format!("data:{};base64,{}", stored.mime, STANDARD.encode(&stored.data))
}

const TRANSCRIBE_PROMPT: &str = "Transcris fidèlement tout le texte lisible de cette image en Markdown, tableaux compris, puis décris en quelques phrases ce qu’elle montre (schéma, photo, interface…). Écris [illisible] pour ce que tu ne peux pas lire et n’invente rien.";

/// Text version of an image, written by Qwen once and kept: used only when the messages that
/// show it are summarized because the context is full.
pub async fn transcript(app: &App, user: Uuid, image: &AttachmentRef) -> Option<String> {
    let stored = load(app, user, &[image.id]).await.ok()?.remove(&image.id)?;
    if let Some(text) = stored.transcript.as_deref().filter(|t| !t.trim().is_empty()) { return Some(text.to_string()); }
    let body = json!({"model": app.config.model, "reasoning_effort": "none", "temperature": 0.1, "max_tokens": 2048, "stream": false,
        "messages": [{"role": "user", "content": [{"type": "text", "text": TRANSCRIBE_PROMPT}, {"type": "image_url", "image_url": {"url": data_url(&stored)}}]}]});
    let response = app.http.post(format!("{}/chat/completions", app.config.api_url)).bearer_auth(&app.config.api_key)
        .timeout(Duration::from_secs(120)).json(&body).send().await.ok()?;
    if !response.status().is_success() { return None; }
    let value: Value = response.json().await.ok()?;
    let text = value.pointer("/choices/0/message/content")?.as_str()?.trim().to_string();
    if text.is_empty() { return None; }
    let _ = sqlx::query("UPDATE attachments SET transcript=$3 WHERE id=$1 AND user_id=$2").bind(image.id).bind(user).bind(&text).execute(&app.db).await;
    Some(text)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn image_tokens_match_counts_measured_on_qwen() {
        for (w, h, tokens) in [(28, 28, 66), (224, 224, 66), (448, 448, 198), (896, 672, 590), (1280, 720, 882), (1600, 1200, 1902), (2048, 1536, 3074)] {
            assert_eq!(image_tokens(w, h), tokens, "{w}x{h}");
        }
    }
    #[test]
    fn names_are_cleaned() {
        assert_eq!(clean_name(Some("../../etc/passwd\n"), "image.png"), "....etcpasswd");
        assert_eq!(clean_name(Some("  "), "image.png"), "image.png");
        assert_eq!(clean_name(None, "document"), "document");
    }
    #[test]
    fn image_references_keep_their_stored_form() {
        let stored = r#"{"id":"6f1c2a52-3a8e-4a8c-9a59-2f1d3c4b5a69","name":"a.png","width":40,"height":30}"#;
        let image: AttachmentRef = serde_json::from_str(stored).unwrap();
        assert!(image.kind == Kind::Image && image.is_valid());
        assert_eq!(serde_json::to_string(&image).unwrap(), stored);
        let document: AttachmentRef = serde_json::from_str(r#"{"id":"6f1c2a52-3a8e-4a8c-9a59-2f1d3c4b5a69","name":"a.pdf","kind":"document","pages":3,"tokens":900}"#).unwrap();
        assert!(document.is_valid());
        assert!(!AttachmentRef { tokens: documents::MAX_TOKENS + 1, ..document.clone() }.is_valid());
        assert!(!AttachmentRef { width: 10, height: 10, ..document }.is_valid());
        assert!(!AttachmentRef { pages: 2, ..image }.is_valid());
    }
}
