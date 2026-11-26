//! Thumbs up or down on an answer of the chat or on a created image. A thumbs down may say why (reasons from a
//! short list and a comment). Votes are only recorded: they never change the answers. The question and the answer
//! are copied with the vote, for a page that will show the votes later (not written yet).
use crate::{App, Error, session};
use axum::{Json, extract::{Path, State}, http::{HeaderMap, StatusCode}};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use uuid::Uuid;

/// Reasons of a thumbs down (ids stored; the page shows the same names, see frontend/src/lib/feedback.ts).
pub const ANSWER_REASONS: [&str; 6] = ["faux", "incomplet", "hors_sujet", "trop_long", "mal_compris", "sources"];
pub const IMAGE_REASONS: [&str; 5] = ["demande", "personnage", "defauts", "style", "retouche"];
const MAX_COMMENT: usize = 1000;
/// Question and answer copied with the vote, cut at this many characters.
const MAX_COPY: usize = 20_000;

#[derive(Deserialize)]
pub struct Vote {
    /// 1 (thumbs up), -1 (thumbs down), 0: the vote removed.
    rating: i16,
    #[serde(default)]
    reasons: Vec<String>,
    #[serde(default)]
    comment: Option<String>,
}

/// Reasons and comment only with a thumbs down, from the list, each once.
fn checked(vote: &Vote, allowed: &[&str]) -> Result<(Vec<String>, Option<String>), Error> {
    if !matches!(vote.rating, -1..=1) { return Err(Error::bad("Avis inconnu.")); }
    if vote.rating != -1 { return Ok((Vec::new(), None)); }
    let mut reasons: Vec<String> = Vec::new();
    for reason in &vote.reasons {
        if !allowed.contains(&reason.as_str()) { return Err(Error::bad("Raison inconnue.")); }
        if !reasons.contains(reason) { reasons.push(reason.clone()); }
    }
    let comment = vote.comment.as_deref().map(str::trim).filter(|c| !c.is_empty());
    if comment.is_some_and(|c| c.chars().count() > MAX_COMMENT) { return Err(Error::bad("Commentaire trop long (1 000 caractères au plus).")); }
    Ok((reasons, comment.map(String::from)))
}

fn sha(text: &str) -> String { hex::encode(Sha256::digest(text.as_bytes())) }
fn cut(text: &str) -> String { text.chars().take(MAX_COPY).collect() }
fn content(message: &Value) -> &str { message.get("content").and_then(Value::as_str).unwrap_or("") }

async fn messages(app: &App, user: Uuid, id: Uuid) -> Result<Vec<Value>, Error> {
    let found: Option<sqlx::types::Json<Vec<Value>>> = sqlx::query_scalar("SELECT messages FROM conversations WHERE id=$1 AND user_id=$2")
        .bind(id).bind(user).fetch_optional(&app.db).await?;
    found.map(|messages| messages.0).ok_or_else(Error::missing)
}

#[derive(Deserialize)]
pub struct AnswerVote {
    index: usize,
    #[serde(flatten)]
    vote: Vote,
}

/// PUT /api/conversations/{id}/feedback: the vote on the answer at `index`.
pub async fn answer(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>, Json(request): Json<AnswerVote>) -> Result<StatusCode, Error> {
    let user = session(&app, &headers, true).await?;
    let (reasons, comment) = checked(&request.vote, &ANSWER_REASONS)?;
    let messages = messages(&app, user.user_id, id).await?;
    let answer = messages.get(request.index).filter(|m| m.get("role").and_then(Value::as_str) == Some("assistant") && !content(m).trim().is_empty())
        .ok_or_else(|| Error::bad("Réponse introuvable."))?;
    let index = request.index as i32;
    if request.vote.rating == 0 {
        sqlx::query("DELETE FROM feedback WHERE conversation_id=$1 AND message_index=$2").bind(id).bind(index).execute(&app.db).await?;
        return Ok(StatusCode::NO_CONTENT);
    }
    let question = messages[..request.index].iter().rev().find(|m| m.get("role").and_then(Value::as_str) == Some("user")).map(content).unwrap_or("");
    sqlx::query("INSERT INTO feedback(id,user_id,conversation_id,message_index,answer_sha256,question,answer,rating,reasons,comment) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                 ON CONFLICT (conversation_id, message_index) WHERE conversation_id IS NOT NULL DO UPDATE SET answer_sha256=EXCLUDED.answer_sha256,
                 question=EXCLUDED.question, answer=EXCLUDED.answer, rating=EXCLUDED.rating, reasons=EXCLUDED.reasons, comment=EXCLUDED.comment, updated_at=now()")
        .bind(Uuid::new_v4()).bind(user.user_id).bind(id).bind(index).bind(sha(content(answer))).bind(cut(question)).bind(cut(content(answer)))
        .bind(request.vote.rating).bind(&reasons).bind(&comment).execute(&app.db).await?;
    Ok(StatusCode::NO_CONTENT)
}

/// GET /api/conversations/{id}/feedback: the votes on the answers still there (an answer replaced has lost its vote).
pub async fn conversation(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, false).await?;
    let messages = messages(&app, user.user_id, id).await?;
    let rows: Vec<(i32, String, i16, Vec<String>, Option<String>)> = sqlx::query_as(
        "SELECT message_index,answer_sha256,rating,reasons,comment FROM feedback WHERE conversation_id=$1 AND user_id=$2")
        .bind(id).bind(user.user_id).fetch_all(&app.db).await?;
    let votes: Vec<Value> = rows.into_iter()
        .filter(|(index, hash, ..)| messages.get(*index as usize).is_some_and(|m| sha(content(m)) == *hash))
        .map(|(index, _, rating, reasons, comment)| json!({"index": index, "rating": rating, "reasons": reasons, "comment": comment}))
        .collect();
    Ok(Json(json!({"votes": votes})))
}

/// PUT /api/attachments/{id}/feedback: the vote on an image created in the Images tab.
pub async fn image(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>, Json(vote): Json<Vote>) -> Result<StatusCode, Error> {
    let user = session(&app, &headers, true).await?;
    let (reasons, comment) = checked(&vote, &IMAGE_REASONS)?;
    let created: bool = sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM attachments WHERE id=$1 AND user_id=$2 AND kind='image' AND generation IS NOT NULL)")
        .bind(id).bind(user.user_id).fetch_one(&app.db).await?;
    if !created { return Err(Error::bad("Image introuvable.")); }
    if vote.rating == 0 {
        sqlx::query("DELETE FROM feedback WHERE attachment_id=$1 AND user_id=$2").bind(id).bind(user.user_id).execute(&app.db).await?;
        return Ok(StatusCode::NO_CONTENT);
    }
    sqlx::query("INSERT INTO feedback(id,user_id,attachment_id,rating,reasons,comment) VALUES($1,$2,$3,$4,$5,$6)
                 ON CONFLICT (user_id, attachment_id) WHERE attachment_id IS NOT NULL DO UPDATE SET rating=EXCLUDED.rating,
                 reasons=EXCLUDED.reasons, comment=EXCLUDED.comment, updated_at=now()")
        .bind(Uuid::new_v4()).bind(user.user_id).bind(id).bind(vote.rating).bind(&reasons).bind(&comment).execute(&app.db).await?;
    Ok(StatusCode::NO_CONTENT)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn vote(rating: i16, reasons: &[&str], comment: Option<&str>) -> Vote {
        Vote { rating, reasons: reasons.iter().map(|r| r.to_string()).collect(), comment: comment.map(String::from) }
    }
    #[test]
    fn reasons_only_with_a_thumbs_down() {
        assert_eq!(checked(&vote(1, &["faux"], Some("x")), &ANSWER_REASONS).unwrap(), (vec![], None));
        assert_eq!(checked(&vote(-1, &["faux", "faux", "trop_long"], Some("  ")), &ANSWER_REASONS).unwrap(), (vec!["faux".into(), "trop_long".into()], None));
        assert_eq!(checked(&vote(-1, &[], Some(" Date fausse ")), &ANSWER_REASONS).unwrap().1.as_deref(), Some("Date fausse"));
        assert!(checked(&vote(-1, &["inconnue"], None), &ANSWER_REASONS).is_err());
        assert!(checked(&vote(-1, &["faux"], None), &IMAGE_REASONS).is_err());
        assert!(checked(&vote(2, &[], None), &ANSWER_REASONS).is_err());
        assert!(checked(&vote(-1, &[], Some(&"x".repeat(1001))), &ANSWER_REASONS).is_err());
    }
}
