//! Documents of the user's library: PDF, Word and text files. The API never opens them:
//! doc-guard, an isolated container without network, data or secrets, extracts their text and
//! renders PDF pages. Each PDF page is then laid out by Qwen once, when the document is added:
//! - a page whose text is reliable is annotated: Qwen sees its image and its numbered text
//!   segments and returns only the structure; the Markdown is built from the PDF's own text, so
//!   no word or number can be changed;
//! - a scanned page (no text, invisible scanner text, broken font) is read on its image at
//!   2 400 px, Qwen marking the readings it is unsure of with [?].
//! The Markdown is kept and sent with the questions; the original file is kept for download.
use crate::{App, Error, context};
use axum::{body::Bytes, http::StatusCode};
use futures_util::{StreamExt, stream};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::HashMap, time::Duration};
use uuid::Uuid;

pub const MAX_UPLOAD: usize = 20 * 1024 * 1024;
/// A document is sent whole with the questions: at most 30 % of Qwen's context.
pub const MAX_TOKENS: u32 = 39_300;
pub const MAX_PAGES: u32 = 60;
/// Pages of one document sent to Qwen at the same time, leaving room for the conversations.
const PARALLEL_PAGES: usize = 4;
const TEXT_SIDE: u32 = 1600;
const SCAN_SIDE: u32 = 2400;

const READ: &str = "Transcris fidèlement tout le texte de cette page de document en Markdown, tableaux compris (en tableaux Markdown), dans l’ordre de lecture. Écris [illisible] pour ce que tu ne peux pas lire et n’invente rien. Pour l’écriture manuscrite et les caractères peu lisibles : si tu n’es pas sûr d’un mot ou d’un nombre, écris ta meilleure lecture suivie de [?] (par exemple « treize[?] ») ; garde [illisible] pour ce que tu ne peux pas lire du tout. Ne corrige jamais une donnée par une autre : si une même information est écrite deux fois (en lettres et en chiffres) et que tes deux lectures ne concordent pas, transcris chacune telle que tu la lis et ajoute [?] aux deux. Réponds uniquement avec la transcription.";
const ANNOTATE: &str = r#"Voici l’image d’une page de document et, après cette consigne, la liste numérotée de ses segments de texte (morceaux de ligne, les colonnes d’un tableau sont séparées), extraits du PDF, avec leur position (x, y en points depuis le coin haut gauche).
Indique la structure de la page SANS recopier le texte. Réponds uniquement en JSON, de la forme :
{"blocs": [
  {"type": "titre", "niveau": 1, "lignes": [1]},
  {"type": "paragraphe", "lignes": [2, 3, 4]},
  {"type": "liste", "elements": [[5], [6, 7]]},
  {"type": "tableau", "rangees": [[8, 9, 10], [11, [12, 13], []]]},
  {"type": "ignorer", "lignes": [14]}
]}
Règles : les blocs suivent l’ordre de lecture (colonnes comprises) ; chaque numéro de segment apparaît exactement une fois ; « niveau » vaut 1, 2 ou 3 ; dans un tableau, la première rangée est l’en-tête et chaque cellule est un numéro, une liste de numéros (cellule en plusieurs segments) ou [] (cellule vide) ; « ignorer » sert aux en-têtes et pieds de page répétés et aux numéros de page.

Segments :
"#;

/// Images reach the API already re-encoded by the browser; anything else is a document.
pub fn is_document(body: &[u8]) -> bool {
    !(body.starts_with(&[0xFF, 0xD8, 0xFF]) || body.starts_with(b"\x89PNG\r\n\x1a\n"))
}

#[derive(Deserialize)]
struct Analysis {
    kind: String,
    #[serde(default)]
    pages: Vec<Page>,
    #[serde(default)]
    markdown: String,
}

#[derive(Deserialize)]
struct Page {
    /// Why the page is read on its image (scan); None when its text is reliable.
    image: Option<String>,
    /// x, y (points from the top left corner), text.
    segments: Vec<(i64, i64, String)>,
    /// Text of the page line by line, kept when Qwen cannot lay it out.
    text: String,
}

fn unavailable() -> Error {
    Error(StatusCode::SERVICE_UNAVAILABLE, "La lecture des documents est indisponible. Réessaie dans un instant.".into())
}

fn too_long(tokens: u32) -> String {
    format!("Ce document est trop long : environ {} tokens, pour {} au maximum (30 % de la mémoire de Qwen).", group(tokens), group(MAX_TOKENS))
}

fn group(value: u32) -> String {
    let digits = value.to_string();
    let mut out = String::new();
    for (index, digit) in digits.chars().enumerate() {
        if index > 0 && (digits.len() - index) % 3 == 0 { out.push('\u{202f}'); }
        out.push(digit);
    }
    out
}

async fn analyse(app: &App, name: &str, body: Bytes) -> Result<Analysis, Error> {
    let response = app.http.post(format!("{}/analyse", app.config.doc_guard)).query(&[("name", name)])
        .timeout(Duration::from_secs(150)).body(body).send().await.map_err(|_| unavailable())?;
    let status = response.status();
    if status == StatusCode::UNPROCESSABLE_ENTITY || status == StatusCode::PAYLOAD_TOO_LARGE {
        let value: Value = response.json().await.map_err(|_| unavailable())?;
        return Err(Error::bad(value.get("error").and_then(Value::as_str).unwrap_or("Document refusé.")));
    }
    if !status.is_success() { return Err(unavailable()); }
    response.json().await.map_err(|_| unavailable())
}

/// Size of a Markdown text for Qwen, counted by its tokenizer when available.
async fn measure(app: &App, text: &str) -> u32 {
    context::count(app, &[json!({"role": "user", "content": text})]).await.tokens.min(u32::MAX as u64) as u32
}

/// Adds a document to the library. Word and text files are ready at once; a PDF is returned
/// while it is being read, and `read` completes it in the background.
pub async fn upload(app: &App, user: Uuid, name: String, body: Bytes) -> Result<Value, Error> {
    let sha = hex::encode(Sha256::digest(&body));
    // The same document sent twice is stored once; a failed reading is tried again.
    let existing: Option<(Uuid, String)> = sqlx::query_as("SELECT id,status FROM attachments WHERE user_id=$1 AND sha256=$2")
        .bind(user).bind(&sha).fetch_optional(&app.db).await?;
    match existing {
        Some((id, status)) if status != "failed" => return crate::attachments::item(app, user, id).await,
        Some((id, _)) => { sqlx::query("DELETE FROM attachments WHERE id=$1").bind(id).execute(&app.db).await?; }
        None => {}
    }
    let analysis = analyse(app, &name, body.clone()).await?;
    let id = Uuid::new_v4();
    let insert = "INSERT INTO attachments(id,user_id,sha256,kind,name,mime,width,height,size,data,thumbnail,status,pages,content,tokens)
        VALUES($1,$2,$3,'document',$4,$5,0,0,$6,$7,''::bytea,$8,$9,$10,$11) ON CONFLICT (user_id,sha256) DO NOTHING RETURNING id";
    if analysis.kind == "pdf" {
        let pages = analysis.pages;
        if pages.is_empty() || pages.len() > MAX_PAGES as usize { return Err(Error::bad("Ce PDF n’a pas pu être lu.")); }
        // Refused before any Qwen call when its text alone is already too long.
        let estimate = (pages.iter().filter(|p| p.image.is_none()).map(|p| p.text.chars().count()).sum::<usize>() as f64 / 3.5) as u32;
        if estimate > MAX_TOKENS + MAX_TOKENS / 10 { return Err(Error::bad(&too_long(estimate))); }
        let created: Option<Uuid> = sqlx::query_scalar(insert).bind(id).bind(user).bind(&sha).bind(&name).bind("application/pdf")
            .bind(body.len() as i32).bind(body.as_ref()).bind("reading").bind(pages.len() as i32).bind(None::<String>).bind(0)
            .fetch_optional(&app.db).await?;
        let Some(id) = created else { return same_document(app, user, &sha).await; };
        tokio::spawn(read(app.clone(), id, body, pages));
        return crate::attachments::item(app, user, id).await;
    }
    let mime = if analysis.kind == "docx" { "application/vnd.openxmlformats-officedocument.wordprocessingml.document" } else { "text/plain" };
    let tokens = measure(app, &analysis.markdown).await;
    if tokens > MAX_TOKENS { return Err(Error::bad(&too_long(tokens))); }
    let created: Option<Uuid> = sqlx::query_scalar(insert).bind(id).bind(user).bind(&sha).bind(&name).bind(mime)
        .bind(body.len() as i32).bind(body.as_ref()).bind("ready").bind(0).bind(&analysis.markdown).bind(tokens as i32)
        .fetch_optional(&app.db).await?;
    let Some(id) = created else { return same_document(app, user, &sha).await; };
    crate::attachments::item(app, user, id).await
}

/// The same document sent twice at the same time: the one stored first is returned.
async fn same_document(app: &App, user: Uuid, sha: &str) -> Result<Value, Error> {
    let id: Uuid = sqlx::query_scalar("SELECT id FROM attachments WHERE user_id=$1 AND sha256=$2").bind(user).bind(sha)
        .fetch_optional(&app.db).await?.ok_or_else(unavailable)?;
    crate::attachments::item(app, user, id).await
}

struct Done {
    text: String,
    scanned: bool,
    doubts: u32,
    failed: bool,
}

async fn render(app: &App, body: &Bytes, number: usize, side: u32) -> Option<Vec<u8>> {
    let response = app.http.post(format!("{}/page", app.config.doc_guard)).query(&[("number", number as u32), ("side", side)])
        .timeout(Duration::from_secs(90)).body(body.clone()).send().await.ok()?;
    if !response.status().is_success() { return None; }
    response.bytes().await.ok().map(|b| b.to_vec())
}

async fn qwen(app: &App, prompt: String, jpeg: &[u8], json_mode: bool) -> Option<String> {
    use base64::{Engine, engine::general_purpose::STANDARD};
    let image = json!({"type": "image_url", "image_url": {"url": format!("data:image/jpeg;base64,{}", STANDARD.encode(jpeg))}});
    let mut body = json!({"model": app.config.model, "reasoning_effort": "none", "temperature": 0, "max_tokens": 4096, "stream": false,
        "messages": [{"role": "user", "content": [image, {"type": "text", "text": prompt}]}]});
    if json_mode { body["response_format"] = json!({"type": "json_object"}); }
    let response = app.http.post(format!("{}/chat/completions", app.config.api_url)).bearer_auth(&app.config.api_key)
        .timeout(Duration::from_secs(300)).json(&body).send().await.ok()?;
    if !response.status().is_success() { return None; }
    let value: Value = response.json().await.ok()?;
    Some(value.pointer("/choices/0/message/content")?.as_str()?.trim().to_string()).filter(|text| !text.is_empty())
}

fn doubts(text: &str) -> u32 {
    (text.matches("[?]").count() + text.matches("[illisible]").count()) as u32
}

async fn read_page(app: &App, body: &Bytes, number: usize, page: Page) -> Done {
    let scanned = page.image.is_some();
    let side = if scanned { SCAN_SIDE } else { TEXT_SIDE };
    let fallback = |text: String| Done { failed: scanned, text, scanned, doubts: 0 };
    let Some(jpeg) = render(app, body, number, side).await else {
        return fallback(if scanned { "[Page illisible : son image n’a pas pu être lue.]".into() } else { page.text });
    };
    if scanned {
        return match qwen(app, READ.into(), &jpeg, false).await {
            Some(text) => Done { doubts: doubts(&text), text, scanned, failed: false },
            None => fallback("[Page illisible : Qwen n’a pas pu la lire.]".into()),
        };
    }
    let list: String = page.segments.iter().enumerate().map(|(i, (x, y, text))| format!("[{}] ({x}, {y}) {text}\n", i + 1)).collect();
    let structure = qwen(app, format!("{ANNOTATE}{list}"), &jpeg, true).await.and_then(|reply| serde_json::from_str::<Value>(&reply).ok());
    match structure.and_then(|structure| assemble(&structure, &page.segments).ok()) {
        Some(text) => Done { text, scanned, doubts: 0, failed: false },
        None => fallback(page.text),
    }
}

/// Reads the pages of a PDF with Qwen, then stores the Markdown or the reason of the failure.
async fn read(app: App, id: Uuid, body: Bytes, pages: Vec<Page>) {
    let _permit = app.documents.clone().acquire_owned().await;
    let total = pages.len();
    let done: Vec<Done> = stream::iter(pages.into_iter().enumerate()).map(|(index, page)| {
        let (app, body) = (app.clone(), body.clone());
        async move {
            let done = read_page(&app, &body, index + 1, page).await;
            let _ = sqlx::query("UPDATE attachments SET progress=progress+1 WHERE id=$1").bind(id).execute(&app.db).await;
            done
        }
    }).buffered(PARALLEL_PAGES).collect().await;
    let failed = done.iter().filter(|page| page.failed).count();
    let content = if total == 1 { done[0].text.clone() } else {
        done.iter().enumerate().map(|(index, page)| format!("--- Page {} ---\n\n{}", index + 1, page.text)).collect::<Vec<_>>().join("\n\n")
    };
    let tokens = measure(&app, &content).await;
    let error = if failed * 2 > total { Some("Qwen n’a pas pu lire ce document. Supprime-le et réessaie plus tard.".to_string()) }
        else if tokens > MAX_TOKENS { Some(too_long(tokens)) } else { None };
    let scanned = done.iter().filter(|page| page.scanned).count() as i32;
    let doubts = done.iter().map(|page| page.doubts).sum::<u32>() as i32;
    let saved = match error {
        Some(error) => sqlx::query("UPDATE attachments SET status='failed',error=$2 WHERE id=$1").bind(id).bind(error).execute(&app.db).await,
        None => sqlx::query("UPDATE attachments SET status='ready',content=$2,tokens=$3,scanned=$4,doubts=$5 WHERE id=$1")
            .bind(id).bind(&content).bind(tokens as i32).bind(scanned).bind(doubts).execute(&app.db).await,
    };
    if let Err(error) = saved { tracing::error!(error = %error, "document reading not saved"); }
}

fn table(rows: &[Vec<String>]) -> String {
    let width = rows.iter().map(Vec::len).max().unwrap_or(0).max(1);
    let line = |row: &Vec<String>| {
        let cells: Vec<String> = (0..width).map(|i| row.get(i).map(|c| c.replace('|', "\\|")).unwrap_or_default()).collect();
        format!("| {} |", cells.join(" | "))
    };
    let mut out = vec![line(&rows[0]), format!("|{}", " --- |".repeat(width))];
    out.extend(rows[1..].iter().map(line));
    out.join("\n")
}

/// Markdown built from the original segments, following the structure given by Qwen. Every
/// segment must be placed once; a few forgotten ones are put back at the end.
pub fn assemble(structure: &Value, segments: &[(i64, i64, String)]) -> Result<String, String> {
    let mut seen: HashMap<usize, u32> = HashMap::new();
    let mut take = |value: &Value| -> Result<String, String> {
        let numbers: Vec<&Value> = match value { Value::Array(items) => items.iter().collect(), other => vec![other] };
        let mut words = Vec::new();
        for number in numbers {
            let index = number.as_u64().filter(|n| (1..=segments.len() as u64).contains(n)).ok_or_else(|| format!("segment {number} inconnu"))? as usize;
            *seen.entry(index).or_default() += 1;
            words.push(segments[index - 1].2.trim().to_string());
        }
        Ok(words.join(" "))
    };
    let blocks = structure.get("blocs").and_then(Value::as_array).ok_or("pas de blocs")?;
    let mut parts = Vec::new();
    for block in blocks {
        let field = |name: &str| block.get(name).ok_or_else(|| format!("champ {name} absent"));
        match block.get("type").and_then(Value::as_str) {
            Some("titre") => {
                let level = block.get("niveau").and_then(Value::as_u64).unwrap_or(1).clamp(1, 3) as usize;
                parts.push(format!("{} {}", "#".repeat(level), take(field("lignes")?)?));
            }
            Some("paragraphe") => parts.push(take(field("lignes")?)?),
            Some("liste") => {
                let items = field("elements")?.as_array().ok_or("liste invalide")?;
                parts.push(items.iter().map(|item| take(item).map(|text| format!("- {text}"))).collect::<Result<Vec<_>, _>>()?.join("\n"));
            }
            Some("tableau") => {
                let rows = field("rangees")?.as_array().ok_or("tableau invalide")?;
                let mut cells = Vec::new();
                for row in rows.iter().filter_map(Value::as_array).filter(|row| !row.is_empty()) {
                    cells.push(row.iter().map(|cell| take(cell)).collect::<Result<Vec<_>, _>>()?);
                }
                if !cells.is_empty() { parts.push(table(&cells)); }
            }
            Some("ignorer") => { take(field("lignes")?)?; }
            other => return Err(format!("type de bloc inconnu : {other:?}")),
        }
    }
    if seen.values().any(|count| *count > 1) { return Err("segment placé deux fois".into()); }
    let forgotten: Vec<usize> = (1..=segments.len()).filter(|n| !seen.contains_key(n)).collect();
    if forgotten.len() > (segments.len() / 10).max(2) { return Err(format!("{} segments oubliés", forgotten.len())); }
    if !forgotten.is_empty() { parts.push(forgotten.iter().map(|n| segments[n - 1].2.trim()).collect::<Vec<_>>().join(" ")); }
    Ok(parts.into_iter().filter(|part| !part.trim().is_empty()).collect::<Vec<_>>().join("\n\n"))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn segments(texts: &[&str]) -> Vec<(i64, i64, String)> { texts.iter().map(|t| (0, 0, t.to_string())).collect() }

    #[test]
    fn markdown_is_built_from_the_original_text() {
        let found = segments(&["Budget 2026", "Mois", "Recettes (€)", "Janvier", "12 400", "Texte", "suite.", "3"]);
        let structure = json!({"blocs": [{"type": "titre", "niveau": 2, "lignes": [1]},
            {"type": "tableau", "rangees": [[2, 3], [4, [5]], []]}, {"type": "paragraphe", "lignes": [6, 7]}, {"type": "ignorer", "lignes": [8]}]});
        assert_eq!(assemble(&structure, &found).unwrap(),
            "## Budget 2026\n\n| Mois | Recettes (€) |\n| --- | --- |\n| Janvier | 12 400 |\n\nTexte suite.");
    }
    #[test]
    fn misplaced_segments_are_refused_and_a_few_forgotten_ones_kept() {
        let found = segments(&["a", "b", "c"]);
        assert!(assemble(&json!({"blocs": [{"type": "paragraphe", "lignes": [1, 1, 2, 3]}]}), &found).is_err());
        assert!(assemble(&json!({"blocs": [{"type": "paragraphe", "lignes": [4]}]}), &found).is_err());
        assert!(assemble(&json!({"blocs": [{"type": "image", "lignes": [1]}]}), &found).is_err());
        assert_eq!(assemble(&json!({"blocs": [{"type": "liste", "elements": [[1], [2]]}]}), &found).unwrap(), "- a\n- b\n\nc");
        assert!(assemble(&json!({"blocs": []}), &segments(&["a", "b", "c", "d"])).is_err());
    }
    #[test]
    fn table_cells_cannot_break_the_table() {
        assert_eq!(table(&[vec!["a|b".into()], vec!["c".into(), "d".into()]]), "| a\\|b |  |\n| --- | --- |\n| c | d |");
    }
    #[test]
    fn images_from_the_browser_are_not_documents() {
        assert!(!is_document(b"\xFF\xD8\xFF\xE0jpeg"));
        assert!(!is_document(b"\x89PNG\r\n\x1a\nrest"));
        assert!(is_document(b"%PDF-1.7"));
        assert!(is_document(b"Bonjour"));
    }
    #[test]
    fn sizes_are_grouped_like_in_french() {
        assert_eq!(group(39_300), "39\u{202f}300");
        assert_eq!(group(950), "950");
    }
}
