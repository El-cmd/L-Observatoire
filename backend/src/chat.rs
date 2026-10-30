use crate::{App, Error, session};
use axum::{
    Json,
    body::Body,
    extract::{Path, State},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
};
use bytes::Bytes;
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::{FromRow, types::Json as DbJson};
use std::convert::Infallible;
use tokio::sync::mpsc;
use uuid::Uuid;

#[derive(Clone, Deserialize, Serialize)]
pub struct Message {
    pub role: String,
    pub content: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub reasoning: String,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub interrupted: bool,
}

#[derive(Serialize, FromRow)]
pub struct Conversation {
    pub id: Uuid,
    pub title: String,
    pub messages: DbJson<Vec<Message>>,
    pub version: i64,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

#[derive(Serialize, FromRow)]
pub struct Summary {
    id: Uuid,
    title: String,
    version: i64,
    message_count: i32,
    updated_at: chrono::DateTime<chrono::Utc>,
}

fn validate_messages(messages: &[Message]) -> Result<(), Error> {
    if messages.len() > 100 {
        return Err(Error::bad("La conversation est limitée à 100 messages."));
    }
    let mut size = 0;
    for m in messages {
        if !matches!(m.role.as_str(), "user" | "assistant")
            || m.content.len() > 100_000
            || m.reasoning.len() > 100_000
            || (m.content.trim().is_empty() && (m.role == "user" || m.reasoning.is_empty()))
        {
            return Err(Error::bad(
                "Un message est vide, trop long ou son rôle est invalide.",
            ));
        }
        size += m.content.len() + m.reasoning.len();
    }
    if size > 400_000 {
        return Err(Error::bad(
            "Cette conversation est trop volumineuse. Ouvre un nouveau chat.",
        ));
    }
    Ok(())
}

fn title(messages: &[Message]) -> String {
    messages
        .iter()
        .find(|m| m.role == "user")
        .map(|m| m.content.chars().take(80).collect())
        .unwrap_or_else(|| "Nouveau chat".into())
}

fn truncate_utf8(value: &mut String, maximum: usize) {
    if value.len() > maximum {
        let mut end = maximum;
        while !value.is_char_boundary(end) {
            end -= 1;
        }
        value.truncate(end);
    }
}

pub async fn list(State(app): State<App>, headers: HeaderMap) -> Result<Json<Vec<Summary>>, Error> {
    let user = session(&app, &headers, false).await?;
    let rows=sqlx::query_as::<_,Summary>("SELECT id,title,version,jsonb_array_length(messages) AS message_count,updated_at FROM conversations WHERE user_id=$1 ORDER BY updated_at DESC LIMIT 1000").bind(user.user_id).fetch_all(&app.db).await?;
    Ok(Json(rows))
}

pub async fn create(
    State(app): State<App>,
    headers: HeaderMap,
) -> Result<(StatusCode, Json<Conversation>), Error> {
    let user = session(&app, &headers, true).await?;
    let mut tx = app.db.begin().await?;
    sqlx::query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))")
        .bind(user.user_id.to_string())
        .execute(&mut *tx)
        .await?;
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM conversations WHERE user_id=$1")
        .bind(user.user_id)
        .fetch_one(&mut *tx)
        .await?;
    if count >= 1000 {
        return Err(Error::bad("La limite de 1 000 conversations est atteinte."));
    }
    let row=sqlx::query_as::<_,Conversation>("INSERT INTO conversations(id,user_id) VALUES($1,$2) RETURNING id,title,messages,version,updated_at").bind(Uuid::new_v4()).bind(user.user_id).fetch_one(&mut *tx).await?;
    tx.commit().await?;
    Ok((StatusCode::CREATED, Json(row)))
}

pub async fn get_one(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Json<Conversation>, Error> {
    let user = session(&app, &headers, false).await?;
    let row = sqlx::query_as::<_, Conversation>(
        "SELECT id,title,messages,version,updated_at FROM conversations WHERE id=$1 AND user_id=$2",
    )
    .bind(id)
    .bind(user.user_id)
    .fetch_optional(&app.db)
    .await?
    .ok_or_else(Error::missing)?;
    Ok(Json(row))
}

#[derive(Deserialize)]
pub struct Update {
    version: i64,
    messages: Vec<Message>,
}

async fn not_found_or_conflict(app: &App, id: Uuid, user: Uuid) -> Error {
    let exists: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM conversations WHERE id=$1 AND user_id=$2)")
            .bind(id)
            .bind(user)
            .fetch_one(&app.db)
            .await
            .unwrap_or(false);
    if exists {
        Error::conflict()
    } else {
        Error::missing()
    }
}

pub async fn update(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
    Json(input): Json<Update>,
) -> Result<Json<Conversation>, Error> {
    let user = session(&app, &headers, true).await?;
    validate_messages(&input.messages)?;
    let row=sqlx::query_as::<_,Conversation>("UPDATE conversations SET title=$3,messages=$4,version=version+1,updated_at=now() WHERE id=$1 AND user_id=$2 AND version=$5 AND (active_generation IS NULL OR generation_started_at<now()-interval '5 minutes') RETURNING id,title,messages,version,updated_at")
        .bind(id).bind(user.user_id).bind(title(&input.messages)).bind(DbJson(input.messages)).bind(input.version).fetch_optional(&app.db).await?;
    match row {
        Some(row) => Ok(Json(row)),
        None => Err(not_found_or_conflict(&app, id, user.user_id).await),
    }
}

pub async fn delete(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<StatusCode, Error> {
    let user = session(&app, &headers, true).await?;
    let result=sqlx::query("DELETE FROM conversations WHERE id=$1 AND user_id=$2 AND (active_generation IS NULL OR generation_started_at<now()-interval '5 minutes')").bind(id).bind(user.user_id).execute(&app.db).await?;
    if result.rows_affected() == 0 {
        return Err(not_found_or_conflict(&app, id, user.user_id).await);
    }
    Ok(StatusCode::NO_CONTENT)
}

#[derive(Deserialize)]
pub struct Import {
    chats: Vec<ImportedChat>,
}
#[derive(Deserialize)]
struct ImportedChat {
    messages: Vec<Message>,
}
pub async fn import(
    State(app): State<App>,
    headers: HeaderMap,
    Json(input): Json<Import>,
) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, true).await?;
    if input.chats.is_empty() || input.chats.len() > 100 {
        return Err(Error::bad(
            "Importe entre 1 et 100 conversations à la fois.",
        ));
    }
    for chat in &input.chats {
        validate_messages(&chat.messages)?;
    }
    let mut tx = app.db.begin().await?;
    sqlx::query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))")
        .bind(user.user_id.to_string())
        .execute(&mut *tx)
        .await?;
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM conversations WHERE user_id=$1")
        .bind(user.user_id)
        .fetch_one(&mut *tx)
        .await?;
    if count + input.chats.len() as i64 > 1000 {
        return Err(Error::bad(
            "L’import dépasserait la limite de 1 000 conversations.",
        ));
    }
    let count = input.chats.len();
    for chat in input.chats {
        sqlx::query("INSERT INTO conversations(id,user_id,title,messages) VALUES($1,$2,$3,$4)")
            .bind(Uuid::new_v4())
            .bind(user.user_id)
            .bind(title(&chat.messages))
            .bind(DbJson(chat.messages))
            .execute(&mut *tx)
            .await?;
    }
    tx.commit().await?;
    Ok(Json(json!({"imported":count})))
}

fn default_effort() -> String {
    "none".into()
}
fn default_temperature() -> f64 {
    0.7
}
fn default_tokens() -> u32 {
    4096
}
#[derive(Deserialize)]
pub struct Generate {
    version: i64,
    #[serde(default = "default_effort")]
    reasoning_effort: String,
    #[serde(default = "default_temperature")]
    temperature: f64,
    #[serde(default = "default_tokens")]
    max_tokens: u32,
}
impl Generate {
    fn validate(&self) -> Result<(), Error> {
        if !matches!(
            self.reasoning_effort.as_str(),
            "none" | "low" | "medium" | "xhigh"
        ) || !self.temperature.is_finite()
            || !(0.0..=2.0).contains(&self.temperature)
            || !(128..=8192).contains(&self.max_tokens)
        {
            return Err(Error::bad("Réglages de génération invalides."));
        }
        Ok(())
    }
}

async fn release(app: &App, id: Uuid, generation: Uuid) {
    let _=sqlx::query("UPDATE conversations SET active_generation=NULL,generation_started_at=NULL WHERE id=$1 AND active_generation=$2").bind(id).bind(generation).execute(&app.db).await;
}

pub async fn generate(
    State(app): State<App>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
    Json(input): Json<Generate>,
) -> Result<Response, Error> {
    let user = session(&app, &headers, true).await?;
    input.validate()?;
    if app.config.api_key.is_empty() || app.config.api_url.is_empty() {
        return Err(Error(
            StatusCode::SERVICE_UNAVAILABLE,
            "L’API Qwen n’est pas configurée.".into(),
        ));
    }
    let permit = app.generations.clone().try_acquire_owned().map_err(|_| {
        Error(
            StatusCode::TOO_MANY_REQUESTS,
            "Le serveur traite déjà quatre réponses. Réessaie dans un instant.".into(),
        )
    })?;
    let generation = Uuid::new_v4();
    let row=sqlx::query_as::<_,Conversation>("UPDATE conversations SET active_generation=$3,generation_started_at=now() WHERE id=$1 AND user_id=$2 AND version=$4 AND (active_generation IS NULL OR generation_started_at<now()-interval '5 minutes') RETURNING id,title,messages,version,updated_at")
        .bind(id).bind(user.user_id).bind(generation).bind(input.version).fetch_optional(&app.db).await?;
    let mut row = match row {
        Some(row) => row,
        None => return Err(not_found_or_conflict(&app, id, user.user_id).await),
    };
    if row.messages.0.is_empty()
        || row.messages.0.len() >= 100
        || row.messages.0.last().is_none_or(|m| m.role != "user")
    {
        release(&app, id, generation).await;
        return Err(Error::bad(
            "Ajoute une question avant de demander une réponse.",
        ));
    }
    let messages: Vec<Value> = row
        .messages
        .0
        .iter()
        .filter(|m| !m.interrupted && !m.content.trim().is_empty())
        .map(|m| json!({"role":m.role,"content":m.content}))
        .collect();
    let payload = json!({"model":app.config.model,"messages":messages,"reasoning_effort":input.reasoning_effort,"temperature":input.temperature,"max_tokens":input.max_tokens,"stream":true,"stream_options":{"include_usage":true}});
    let response = app
        .http
        .post(format!("{}/chat/completions", app.config.api_url))
        .bearer_auth(&app.config.api_key)
        .json(&payload)
        .send()
        .await;
    let upstream = match response {
        Ok(response)
            if response.status().is_success()
                && response
                    .headers()
                    .get(header::CONTENT_TYPE)
                    .is_some_and(|h| h.to_str().unwrap_or("").contains("text/event-stream")) =>
        {
            response
        }
        Ok(response) => {
            let status = response.status().as_u16();
            release(&app, id, generation).await;
            return Err(Error(
                StatusCode::BAD_GATEWAY,
                format!("L’API Qwen a répondu HTTP {status} ou n’a pas renvoyé de flux SSE."),
            ));
        }
        Err(_) => {
            release(&app, id, generation).await;
            return Err(Error(
                StatusCode::BAD_GATEWAY,
                "Le serveur Qwen est inaccessible.".into(),
            ));
        }
    };
    let existing_bytes: usize = row
        .messages
        .0
        .iter()
        .map(|m| m.content.len() + m.reasoning.len())
        .sum();
    let (sender, receiver) = mpsc::channel::<Result<Bytes, Infallible>>(8);
    tokio::spawn(async move {
        let _permit = permit;
        let mut source = upstream.bytes_stream();
        let mut shutdown = app.shutdown.clone();
        let mut buffer = Vec::<u8>::new();
        let mut output = Message {
            role: "assistant".into(),
            content: String::new(),
            reasoning: String::new(),
            interrupted: false,
        };
        let mut done = false;
        let mut failed = false;
        let mut disconnected = false;
        'read: loop {
            let chunk = tokio::select! {_ = sender.closed()=>{disconnected=true;break;}, _ = shutdown.changed()=>{disconnected=true;break;}, chunk=source.next()=>chunk};
            let bytes = match chunk {
                Some(Ok(bytes)) => bytes,
                Some(Err(_)) => {
                    failed = true;
                    break;
                }
                None => break,
            };
            buffer.extend_from_slice(&bytes);
            if buffer.len() > 256 * 1024 {
                failed = true;
                break;
            }
            loop {
                let split = buffer
                    .windows(2)
                    .position(|w| w == b"\n\n")
                    .map(|p| (p, 2))
                    .or_else(|| {
                        buffer
                            .windows(4)
                            .position(|w| w == b"\r\n\r\n")
                            .map(|p| (p, 4))
                    });
                let Some((position, width)) = split else {
                    break;
                };
                let event = String::from_utf8_lossy(&buffer[..position]).to_string();
                buffer.drain(..position + width);
                let data = event
                    .lines()
                    .filter_map(|l| l.strip_prefix("data:"))
                    .map(str::trim_start)
                    .collect::<Vec<_>>()
                    .join("\n");
                if data.is_empty() {
                    continue;
                }
                if data.trim() == "[DONE]" {
                    done = true;
                    break 'read;
                }
                let value: Value = match serde_json::from_str(&data) {
                    Ok(v) => v,
                    Err(_) => {
                        failed = true;
                        break 'read;
                    }
                };
                if value.get("error").is_some() {
                    failed = true;
                    break 'read;
                }
                if let Some(delta) = value.pointer("/choices/0/delta") {
                    if let Some(content) = delta.get("content").and_then(Value::as_str) {
                        output.content.push_str(content);
                    }
                    if let Some(reasoning) = delta
                        .get("reasoning_content")
                        .or_else(|| delta.get("reasoning"))
                        .or_else(|| delta.pointer("/provider_specific_fields/reasoning"))
                        .and_then(Value::as_str)
                    {
                        output.reasoning.push_str(reasoning);
                    }
                }
                if output.content.len() > 100_000
                    || output.reasoning.len() > 100_000
                    || existing_bytes + output.content.len() + output.reasoning.len() > 400_000
                {
                    failed = true;
                    break 'read;
                }
                if sender
                    .send(Ok(Bytes::from(format!("data: {data}\n\n"))))
                    .await
                    .is_err()
                {
                    disconnected = true;
                    break 'read;
                }
            }
        }
        // Dropping source cancels the upstream HTTP request before persisting the result.
        drop(source);
        output.interrupted = !done || failed || disconnected;
        let budget = 400_000usize.saturating_sub(existing_bytes);
        truncate_utf8(&mut output.content, 100_000.min(budget));
        truncate_utf8(
            &mut output.reasoning,
            100_000.min(budget.saturating_sub(output.content.len())),
        );
        if !output.content.is_empty() || !output.reasoning.is_empty() {
            row.messages.0.push(output);
        }
        let saved=sqlx::query("UPDATE conversations SET messages=$3,version=version+1,active_generation=NULL,generation_started_at=NULL,updated_at=now() WHERE id=$1 AND active_generation=$2")
            .bind(id).bind(generation).bind(row.messages).execute(&app.db).await;
        let persisted = matches!(saved,Ok(ref result) if result.rows_affected()==1);
        if !persisted {
            tracing::error!(conversation=%id,"could not persist generation");
            release(&app, id, generation).await;
        }
        if !disconnected {
            let end = if !persisted {
                "data: {\"error\":{\"message\":\"Impossible de sauvegarder la réponse. Recharge la conversation.\"}}\n\n"
            } else if !done || failed {
                "data: {\"error\":{\"message\":\"La réponse a été interrompue. La partie reçue a été sauvegardée.\"}}\n\n"
            } else {
                "data: [DONE]\n\n"
            };
            let _ = sender.send(Ok(Bytes::from_static(end.as_bytes()))).await;
        }
    });
    let mut response =
        Body::from_stream(tokio_stream::wrappers::ReceiverStream::new(receiver)).into_response();
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        "text/event-stream; charset=utf-8".parse().unwrap(),
    );
    response
        .headers_mut()
        .insert("x-accel-buffering", "no".parse().unwrap());
    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_allowed_roles_and_bounded_messages() {
        let mut m = Message {
            role: "user".into(),
            content: "Bonjour".into(),
            reasoning: String::new(),
            interrupted: false,
        };
        assert!(validate_messages(&[m.clone()]).is_ok());
        m.role = "system".into();
        assert!(validate_messages(&[m.clone()]).is_err());
        m.role = "user".into();
        m.content.clear();
        assert!(validate_messages(&[m]).is_err());
    }
    #[test]
    fn reasoning_levels_match_live_model() {
        for level in ["none", "low", "medium", "xhigh"] {
            assert!(
                Generate {
                    version: 0,
                    reasoning_effort: level.into(),
                    temperature: 0.7,
                    max_tokens: 4096
                }
                .validate()
                .is_ok()
            );
        }
        assert!(
            Generate {
                version: 0,
                reasoning_effort: "high".into(),
                temperature: 0.7,
                max_tokens: 4096
            }
            .validate()
            .is_err()
        );
    }
}
