//! Ephemeral chat: the conversation lives only in the browser page. Each request carries the whole exchange; the
//! answer is relayed as it is written and nothing is written to the database (no messages, title, context
//! measurement or file). Files are refused: they would be kept in the user's library.
use crate::{App, Error, chat::{self, Conversation, Message}, context, session};
use axum::{Json, extract::{Path, State}, http::{HeaderMap, StatusCode}, response::Response};
use bytes::Bytes;
use futures_util::StreamExt;
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::types::Json as DbJson;
use std::{convert::Infallible, sync::Arc, time::Duration};
use tokio::sync::{Notify, mpsc};
use uuid::Uuid;

/// An ephemeral answer being written, by the identifier the page chose: the Stop button reaches it here.
pub struct Running {
    owner: Uuid,
    stop: Arc<Notify>,
}

/// Removes the answer from the running ones however it ends (error before the stream, end of the stream).
struct Registered {
    app: App,
    id: Uuid,
}
impl Drop for Registered {
    fn drop(&mut self) {
        self.app.ephemeres.lock().expect("ephemeral answers").remove(&self.id);
    }
}

#[derive(Deserialize)]
pub struct Generate {
    /// Chosen by the page for this answer, so that Stop works even before the first word arrives.
    id: Uuid,
    messages: Vec<Message>,
    #[serde(flatten)]
    settings: chat::Settings,
}

const NO_FILES: &str = "Un chat éphémère n’accepte pas de fichiers : ils seraient gardés dans ta bibliothèque.";
const TOO_LONG: &str = "Ce chat éphémère est devenu trop long pour la mémoire du modèle. Ouvre un nouveau chat éphémère.";

fn check(input: &Generate) -> Result<(), Error> {
    input.settings.validate()?;
    chat::validate_messages(&input.messages)?;
    if input.messages.iter().any(|m| !m.attachments.is_empty()) {
        return Err(Error::bad(NO_FILES));
    }
    let resume = input.settings.resume;
    let last = input.messages.last();
    let ready = if resume {
        last.is_some_and(|m| m.role == "assistant" && !m.interrupted && !m.content.trim().is_empty())
    } else {
        last.is_some_and(|m| m.role == "user")
    };
    if !ready {
        return Err(Error::bad(if resume { "Il n’y a pas de réponse à continuer." } else { "Ajoute une question avant de demander une réponse." }));
    }
    Ok(())
}

pub async fn generate(State(app): State<App>, headers: HeaderMap, Json(input): Json<Generate>) -> Result<Response, Error> {
    let user = session(&app, &headers, true).await?;
    check(&input)?;
    if app.config.api_key.is_empty() || app.config.api_url.is_empty() {
        return Err(Error(StatusCode::SERVICE_UNAVAILABLE, "L’API Qwen n’est pas configurée.".into()));
    }
    let searching = input.settings.recherche.is_some();
    if searching && !user.recherche_web {
        return Err(Error(StatusCode::FORBIDDEN, "La recherche web n’est pas ouverte à ce compte.".into()));
    }
    if searching && app.config.orchestrator_url.is_empty() {
        return Err(Error(StatusCode::SERVICE_UNAVAILABLE, "La recherche web n’est pas disponible sur ce serveur.".into()));
    }
    let stop = Arc::new(Notify::new());
    {
        let mut running = app.ephemeres.lock().expect("ephemeral answers");
        if running.contains_key(&input.id) || running.values().any(|r| r.owner == user.user_id) {
            return Err(Error(StatusCode::CONFLICT, "Une réponse est déjà en cours dans ton chat éphémère.".into()));
        }
        running.insert(input.id, Running { owner: user.user_id, stop: stop.clone() });
    }
    let registered = Registered { app: app.clone(), id: input.id };
    let permit = app.generations.clone().try_acquire_owned().map_err(|_| {
        Error(StatusCode::TOO_MANY_REQUESTS, "Le serveur traite déjà six réponses. Réessaie dans un instant.".into())
    })?;
    // The same prompt as a saved conversation, built in memory only (no summary: nothing can be stored).
    let row = Conversation {
        id: input.id,
        title: String::new(),
        messages: DbJson(input.messages),
        version: 0,
        context_summary: String::new(),
        compacted_through: 0,
        compaction_count: 0,
        updated_at: chrono::Utc::now(),
        measured_tokens: 0,
        measured_messages: 0,
        measured_digest: String::new(),
        title_source: String::new(),
    };
    let counted = context::count_prompt(&app, &row).await;
    if !context::fits(&counted, (input.settings.max_tokens as u64).min(context::MIN_OUTPUT)) {
        return Err(Error::bad(TOO_LONG));
    }
    let max_tokens = context::output_budget(&counted, input.settings.max_tokens as u64);
    let payload = chat::payload(&app, context::prompt(&row), &input.settings, max_tokens);
    let (upstream, notice) = chat::open_stream(&app, payload, searching).await?;
    let (sender, receiver) = mpsc::channel::<Result<Bytes, Infallible>>(8);
    tokio::spawn(async move {
        let _permit = permit;
        let _registered = registered;
        let mut source = upstream.bytes_stream();
        let mut shutdown = app.shutdown.clone();
        let mut buffer = Vec::<u8>::new();
        if let Some(notice) = notice {
            let line = format!("data: {}\n\n", json!({"observatoire":{"recherche_web":notice}}));
            let _ = sender.send(Ok(Bytes::from(line))).await;
        }
        let (mut done, mut failed, mut disconnected) = (false, false, false);
        // Keep-alive comments: Cloudflare closes a response that sends nothing for 100 s (very deep search).
        let mut heartbeat = tokio::time::interval(Duration::from_secs(15));
        heartbeat.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        heartbeat.tick().await;
        'read: loop {
            let chunk = tokio::select! {
                _ = sender.closed() => {disconnected = true; break;},
                _ = shutdown.changed() => {disconnected = true; break;},
                _ = stop.notified() => {disconnected = true; break;},
                _ = heartbeat.tick() => {
                    if sender.send(Ok(Bytes::from_static(b": keep-alive\n\n"))).await.is_err() {disconnected = true; break;}
                    continue;
                },
                chunk = source.next() => chunk,
            };
            let bytes = match chunk {
                Some(Ok(bytes)) => bytes,
                Some(Err(_)) => {failed = true; break;}
                None => break,
            };
            buffer.extend_from_slice(&bytes);
            if buffer.len() > 256 * 1024 {
                failed = true;
                break;
            }
            while let Some(data) = chat::next_event(&mut buffer) {
                if data.is_empty() {
                    continue;
                }
                if data.trim() == "[DONE]" {
                    done = true;
                    break 'read;
                }
                match serde_json::from_str::<Value>(&data) {
                    Ok(value) if value.get("error").is_none() => {}
                    _ => {failed = true; break 'read;}
                }
                if sender.send(Ok(Bytes::from(format!("data: {data}\n\n")))).await.is_err() {
                    disconnected = true;
                    break 'read;
                }
            }
        }
        // Dropping the source cancels the request to the orchestrator (and its search) at once.
        drop(source);
        if !disconnected {
            let end: &[u8] = if done && !failed {
                b"data: [DONE]\n\n"
            } else {
                "data: {\"error\":{\"message\":\"La réponse a été interrompue.\"}}\n\n".as_bytes()
            };
            let _ = sender.send(Ok(Bytes::from_static(end))).await;
        }
    });
    Ok(chat::event_stream(receiver))
}

/// Stop button of an ephemeral chat: only its owner reaches it; nothing running, nothing to do.
pub async fn stop(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<StatusCode, Error> {
    let user = session(&app, &headers, true).await?;
    if let Some(running) = app.ephemeres.lock().expect("ephemeral answers").get(&id).filter(|r| r.owner == user.user_id) {
        running.stop.notify_one();
    }
    Ok(StatusCode::NO_CONTENT)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input(messages: Value, settings: Value) -> Generate {
        let mut body = json!({"id": Uuid::new_v4(), "messages": messages});
        body.as_object_mut().unwrap().extend(settings.as_object().unwrap().clone());
        serde_json::from_value(body).unwrap()
    }

    #[test]
    fn only_a_question_or_an_answer_to_continue_and_no_files() {
        let question = json!([{"role":"user","content":"Bonjour"}]);
        assert!(check(&input(question.clone(), json!({}))).is_ok());
        assert!(check(&input(question.clone(), json!({"recherche":"tres_approfondie"}))).is_ok());
        assert!(check(&input(question.clone(), json!({"recherche":"extreme"}))).is_err());
        assert!(check(&input(json!([]), json!({}))).is_err());
        let answered = json!([{"role":"user","content":"Bonjour"},{"role":"assistant","content":"Salut"}]);
        assert!(check(&input(answered.clone(), json!({}))).is_err(), "an answer needs a question after it");
        assert!(check(&input(answered, json!({"continue":true}))).is_ok());
        let interrupted = json!([{"role":"user","content":"Bonjour"},{"role":"assistant","content":"Sal","interrupted":true}]);
        assert!(check(&input(interrupted, json!({"continue":true}))).is_err());
        let image = json!([{"role":"user","content":"Et ça ?","attachments":[{"id":Uuid::new_v4(),"name":"a.png","width":10,"height":10}]}]);
        assert_eq!(check(&input(image, json!({}))).unwrap_err().1, NO_FILES);
        assert!(check(&input(json!([{"role":"system","content":"x"}]), json!({}))).is_err());
    }
}
