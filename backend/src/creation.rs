//! Images tab: creates images with the image model served next to Qwen (qwen-image-turbo through
//! LiteLLM). Each image goes through image-guard like a sent image, then into the user's library
//! with the way it was made. The prompt can first be rewritten by Qwen ("Améliorer le prompt").
use crate::{App, Error, attachments, session};
use axum::{Json, body::Bytes, extract::{Path, State}, http::{HeaderMap, StatusCode}, response::Response};
use base64::{Engine, engine::general_purpose::STANDARD};
use rand::Rng;
use serde::Deserialize;
use serde_json::{Value, json};
use std::time::{Duration, Instant};
use uuid::Uuid;

/// Longest idea accepted; the image service takes 2000 characters and a style adds up to ~120.
pub const MAX_PROMPT: usize = 1800;
/// Images asked in a row by the page (one request each: the service makes one image at a time).
pub const MAX_COUNT: u32 = 8;
/// Sizes accepted by the image service (IMAGE_GEN_SIZES on the AI server).
pub const DEFAULT_SIZES: &str = "1024x1024,1152x896,896x1152,1344x768,768x1344,768x768,512x512";

/// Styles: words added after the prompt. Qwen-Image Turbo runs at CFG 1.0, so a negative prompt
/// would do nothing. Same list as the image lab (~/labo-images), whose examples are in
/// frontend/public/creation/styles.
pub const STYLES: &[(&str, &str, &str)] = &[
    ("dynamique", "Dynamique", "dynamic composition, vivid colors, dramatic lighting, rich detail"),
    ("aucun", "Aucun", ""),
    ("photo", "Photo réaliste", "photorealistic photograph, natural light, 35mm lens, sharp focus, high detail"),
    ("cinema", "Cinématique", "cinematic film still, anamorphic lens, film grain, moody color grading, shallow depth of field"),
    ("portrait", "Portrait studio", "studio portrait, softbox lighting, 85mm lens, detailed skin texture, neutral backdrop"),
    ("illustration", "Illustration", "digital illustration, clean line art, rich colors, detailed"),
    ("anime", "Anime", "anime style, cel shading, vibrant colors, detailed background"),
    ("bd", "Bande dessinée", "franco-belgian comic style, ligne claire, flat colors, bold outlines"),
    ("aquarelle", "Aquarelle", "watercolor painting, soft washes, visible paper texture"),
    ("huile", "Peinture à l'huile", "oil painting on canvas, visible brush strokes, classical composition"),
    ("3d", "Rendu 3D", "3D render, soft global illumination, physically based materials, high detail"),
    ("pixel", "Pixel art", "pixel art, 16-bit, limited color palette, crisp pixels"),
    ("croquis", "Croquis", "graphite pencil sketch, cross-hatching, on white paper"),
    ("logo", "Logo / icône", "flat vector logo, minimal, centered, plain background"),
    ("affiche", "Affiche", "graphic poster design, bold layout, strong typography"),
];
const DEFAULT_STYLE: &str = "dynamique";

/// Styles written by a user ("Mes styles"): how many, and how long. 1 800 + "\n\nStyle: " + 180 + "."
/// stays under the 2 000 characters of the image service.
pub const MAX_STYLES: i64 = 30;
pub const MAX_STYLE_NAME: usize = 40;
pub const MAX_STYLE_WORDS: usize = 180;
const MAX_STYLE_DESCRIPTION: usize = 600;
/// Example of a user's style: the subject and seed of the built-in examples, at a quicker size.
const EXAMPLE_SUBJECT: &str = "un renard roux assis dans une clairière en automne, feuilles dorées, lumière douce";
const EXAMPLE_SEED: u32 = 42;

/// Buttons of the page: each format takes the allowed size closest to its proportions.
const FORMATS: &[(&str, f64)] = &[("2:3", 2.0 / 3.0), ("1:1", 1.0), ("16:9", 16.0 / 9.0)];

fn style(id: &str) -> Option<&'static (&'static str, &'static str, &'static str)> {
    STYLES.iter().find(|s| s.0 == id)
}

/// A style ready to use: built in, or written by this user.
pub struct Chosen {
    pub id: String,
    pub name: String,
    pub words: String,
}

async fn chosen(app: &App, user: Uuid, id: &str) -> Result<Chosen, Error> {
    if let Some((id, name, words)) = style(id) {
        return Ok(Chosen { id: id.to_string(), name: name.to_string(), words: words.to_string() });
    }
    let found: Option<(String, String)> = match Uuid::parse_str(id) {
        Ok(uuid) => sqlx::query_as("SELECT name,words FROM image_styles WHERE id=$1 AND user_id=$2").bind(uuid).bind(user).fetch_optional(&app.db).await?,
        Err(_) => None,
    };
    found.map(|(name, words)| Chosen { id: id.to_string(), name, words }).ok_or_else(|| Error::bad("Style inconnu."))
}

/// Prompt really sent to the image model.
pub fn compose(prompt: &str, words: &str) -> String {
    let prompt = prompt.trim();
    let words = words.trim();
    if words.is_empty() { prompt.to_string() } else { format!("{prompt}\n\nStyle: {words}.") }
}

fn dimensions(size: &str) -> Option<(u32, u32)> {
    let (w, h) = size.split_once('x')?;
    Some((w.parse().ok().filter(|v| (64..=4096).contains(v))?, h.parse().ok().filter(|v| (64..=4096).contains(v))?))
}

pub fn sizes(app: &App) -> Vec<String> {
    app.config.image_sizes.iter().filter(|s| dimensions(s).is_some()).cloned().collect()
}

/// Allowed size closest to a ratio; on a tie (2:3 between 896x1152 and 768x1344), the largest,
/// then the least elongated.
pub fn closest(sizes: &[String], ratio: f64) -> Option<String> {
    let key = |s: &String| {
        let (w, h) = dimensions(s).unwrap_or((1, 1));
        let r = (w as f64 / h as f64).ln();
        (((r - ratio.ln()).abs() * 1e6).round() as i64, -((w * h) as i64), (r.abs() * 1e6).round() as i64)
    };
    sizes.iter().min_by_key(|s| key(s)).cloned()
}

pub async fn config(State(app): State<App>, headers: HeaderMap) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, false).await?;
    let mine: Vec<StyleRow> = sqlx::query_as(STYLE_SELECT_MINE).bind(user.user_id).fetch_all(&app.db).await?;
    let sizes = sizes(&app);
    let formats: Vec<Value> = FORMATS.iter().filter_map(|(name, ratio)| closest(&sizes, *ratio).map(|size| json!({"name": name, "size": size}))).collect();
    let default_size = if sizes.iter().any(|s| s == "1024x1024") { "1024x1024".to_string() } else { sizes.first().cloned().unwrap_or_default() };
    Ok(Json(json!({
        "configured": configured(&app),
        "styles": STYLES.iter().map(|(id, name, words)| json!({"id": id, "name": name, "words": words})).collect::<Vec<_>>(),
        "default_style": DEFAULT_STYLE,
        "my_styles": mine.into_iter().map(style_json).collect::<Vec<_>>(),
        "max_styles": MAX_STYLES,
        "max_style_name": MAX_STYLE_NAME,
        "max_style_words": MAX_STYLE_WORDS,
        "formats": formats,
        "sizes": sizes,
        "default_size": default_size,
        "max_count": MAX_COUNT,
        "max_prompt": MAX_PROMPT,
    })))
}

fn configured(app: &App) -> bool {
    !app.config.api_url.is_empty() && !app.config.api_key.is_empty() && !app.config.image_model.is_empty()
}

/// Tags the image server reads as native settings: refused (the service refuses them too).
fn reserved(prompt: &str) -> bool {
    let lower = prompt.to_lowercase();
    lower.contains("sd_cpp_extra_args") || lower.contains("<lora:")
}

fn check_prompt(prompt: &str) -> Result<(), Error> {
    if prompt.trim().is_empty() { return Err(Error::bad("Décrivez l’image à créer.")); }
    if prompt.chars().count() > MAX_PROMPT { return Err(Error::bad("Description trop longue (1 800 caractères au maximum).")); }
    if reserved(prompt) { return Err(Error::bad("La description contient une balise réservée.")); }
    Ok(())
}

#[derive(Deserialize)]
pub struct Request {
    prompt: String,
    #[serde(default)]
    style: Option<String>,
    size: String,
    /// Rewritten by "Améliorer le prompt" (automatic mode); `prompt` keeps the user's idea.
    #[serde(default)]
    improved: Option<String>,
}

/// File name from the idea: its first words.
fn image_name(prompt: &str, mime: &str) -> String {
    let words: String = prompt.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(60).collect();
    let extension = if mime == "image/png" { "png" } else { "jpg" };
    attachments::clean_name(Some(&format!("{}.{extension}", words.trim_end_matches(['.', ' ']))), &format!("image.{extension}"))
}

/// One image from the image model (one at a time per API, see `App::images`).
async fn generate(app: &App, prompt: &str, size: &str, seed: u32) -> Result<Vec<u8>, Error> {
    let busy = || Error(StatusCode::SERVICE_UNAVAILABLE, "Le service d’images est occupé ou indisponible. Réessayez dans un instant.".into());
    let _turn = app.images.acquire().await.map_err(|_| busy())?;
    let response = app.http.post(format!("{}/images/generations", app.config.api_url)).bearer_auth(&app.config.api_key)
        .timeout(Duration::from_secs(150))
        .json(&json!({"model": app.config.image_model, "prompt": prompt, "n": 1, "size": size, "seed": seed, "response_format": "b64_json"}))
        .send().await.map_err(|_| busy())?;
    let status = response.status();
    if !status.is_success() {
        tracing::warn!(status = status.as_u16(), "image generation failed");
        return Err(busy());
    }
    let value: Value = response.json().await.map_err(|_| busy())?;
    value.pointer("/data/0/b64_json").and_then(Value::as_str).and_then(|b| STANDARD.decode(b).ok()).ok_or_else(busy)
}

fn not_configured() -> Error {
    Error(StatusCode::SERVICE_UNAVAILABLE, "La création d’images n’est pas configurée.".into())
}

pub async fn create(State(app): State<App>, headers: HeaderMap, Json(request): Json<Request>) -> Result<(StatusCode, Json<Value>), Error> {
    let user = session(&app, &headers, true).await?;
    if !configured(&app) { return Err(not_configured()); }
    check_prompt(&request.prompt)?;
    let improved = request.improved.as_deref().map(str::trim).filter(|s| !s.is_empty());
    if let Some(text) = improved { check_prompt(text)?; }
    let style = chosen(&app, user.user_id, request.style.as_deref().unwrap_or(DEFAULT_STYLE)).await?;
    if !sizes(&app).contains(&request.size) { return Err(Error::bad("Taille d’image non prise en charge.")); }
    // An image weighs up to ~3 Mo before image-guard re-encodes it.
    if attachments::used_bytes(&app, user.user_id).await? + 3 * 1024 * 1024 > attachments::QUOTA_BYTES {
        return Err(Error::bad(attachments::FULL));
    }
    let sent = compose(improved.unwrap_or(&request.prompt), &style.words);
    let seed: u32 = rand::thread_rng().gen_range(0..i32::MAX as u32);
    let started = Instant::now();
    let data = generate(&app, &sent, &request.size, seed).await?;
    let clean = attachments::sanitize(&app, Bytes::from(data)).await?;
    let generation = json!({"prompt": request.prompt.trim(), "sent": sent, "style": style.id, "style_name": style.name, "size": request.size, "seed": seed,
                            "seconds": (started.elapsed().as_secs_f64() * 10.0).round() / 10.0});
    let id = attachments::store_image(&app, user.user_id, &clean, &image_name(&request.prompt, &clean.mime), Some(generation)).await?;
    Ok((StatusCode::CREATED, Json(attachments::item(&app, user.user_id, id).await?)))
}

const IMPROVE: &str = "You turn a short image idea into one detailed prompt for the Qwen-Image text-to-image model.

Rules:
- Keep the user's intent and every element they asked for. Never change or remove the subject, the number of subjects, or any explicit detail.
- Add concrete visual details: appearance of the subject, setting, composition and framing, lighting, colors, mood.
- Any text that must be written in the image stays exactly as the user wrote it, between double quotes.
- {style}
- Do not invent text, logos or signatures to display in the image.
- Write in English, as a single paragraph of 50 to 110 words.
- Answer with the prompt only: no introduction, no title, no list, no quotes around the whole prompt.";

pub fn improve_instructions(name: &str, words: &str) -> String {
    let rule = match words.trim() {
        "" => "You may suggest an appropriate visual style or medium if the idea calls for one.".to_string(),
        words => format!(
            "The style \"{name}\" ({words}) is added separately after your prompt: describe the scene so it fits this style, but do not name another style or medium."),
    };
    IMPROVE.replace("{style}", &rule)
}

/// Removes a possible <think> block, a "Prompt:" lead and quotes around the whole text.
pub fn clean_improved(text: &str) -> String {
    unwrap_answer(text, &["**Prompt:**", "Prompt:", "prompt:"]).chars().take(MAX_PROMPT).collect()
}

fn unwrap_answer<'a>(text: &'a str, leads: &[&str]) -> &'a str {
    let mut text = text.rsplit_once("</think>").map_or(text, |(_, after)| after).trim();
    for lead in leads {
        if let Some(rest) = text.strip_prefix(lead) { text = rest.trim(); }
    }
    for (open, close) in [('"', '"'), ('\'', '\''), ('«', '»'), ('“', '”')] {
        if text.chars().count() > 1 && text.starts_with(open) && text.ends_with(close) {
            text = text[open.len_utf8()..text.len() - close.len_utf8()].trim();
            break;
        }
    }
    text
}

#[derive(Deserialize)]
pub struct ImproveRequest {
    prompt: String,
    #[serde(default)]
    style: Option<String>,
}

pub async fn improve(State(app): State<App>, headers: HeaderMap, Json(request): Json<ImproveRequest>) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, true).await?;
    if app.config.api_url.is_empty() || app.config.api_key.is_empty() { return Err(Error(StatusCode::SERVICE_UNAVAILABLE, "Qwen n’est pas configuré.".into())); }
    check_prompt(&request.prompt)?;
    let style = chosen(&app, user.user_id, request.style.as_deref().unwrap_or(DEFAULT_STYLE)).await?;
    let failed = || Error(StatusCode::SERVICE_UNAVAILABLE, "Qwen n’a pas pu améliorer la description. Réessayez dans un instant.".into());
    let text = clean_improved(&ask_qwen(&app, &improve_instructions(&style.name, &style.words), request.prompt.trim(), 0.7, 400).await.ok_or_else(failed)?);
    if text.is_empty() || reserved(&text) { return Err(failed()); }
    Ok(Json(json!({"prompt": text})))
}

/// One short answer from Qwen, without reasoning; None when it cannot answer.
async fn ask_qwen(app: &App, system: &str, user: &str, temperature: f64, max_tokens: u32) -> Option<String> {
    let body = json!({"model": app.config.model, "reasoning_effort": "none", "temperature": temperature, "max_tokens": max_tokens, "stream": false,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]});
    let response = app.http.post(format!("{}/chat/completions", app.config.api_url)).bearer_auth(&app.config.api_key)
        .timeout(Duration::from_secs(90)).json(&body).send().await.ok()?;
    if !response.status().is_success() { return None; }
    let value: Value = response.json().await.ok()?;
    value.pointer("/choices/0/message/content").and_then(Value::as_str).map(String::from)
}

// --- Styles written by the user ("Mes styles") ---

type StyleRow = (Uuid, String, String, bool, i64);
const STYLE_COLUMNS: &str = "id,name,words,example IS NOT NULL,(extract(epoch FROM updated_at)*1000)::bigint";
const STYLE_SELECT_MINE: &str = "SELECT id,name,words,example IS NOT NULL,(extract(epoch FROM updated_at)*1000)::bigint FROM image_styles WHERE user_id=$1 ORDER BY created_at";

/// `version` changes with the example: the page adds it to the example's address.
fn style_json((id, name, words, example, version): StyleRow) -> Value {
    json!({"id": id, "name": name, "words": words, "example": example, "version": version})
}

fn style_missing() -> Error {
    Error(StatusCode::NOT_FOUND, "Style introuvable.".into())
}

fn one_line(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Name and words of a style, on one line; the words lose a final period (compose adds one).
pub fn check_style(name: &str, words: &str) -> Result<(String, String), Error> {
    let name = one_line(name);
    let words = one_line(words).trim_end_matches(['.', ',', ';', ' ']).to_string();
    if name.is_empty() { return Err(Error::bad("Donnez un nom au style.")); }
    if name.chars().count() > MAX_STYLE_NAME { return Err(Error::bad("Nom trop long (40 caractères au maximum).")); }
    if words.is_empty() { return Err(Error::bad("Écrivez les mots du style, ou demandez-les à L’Observatoire.")); }
    if words.chars().count() > MAX_STYLE_WORDS { return Err(Error::bad("Mots du style trop longs (180 caractères au maximum).")); }
    if reserved(&name) || reserved(&words) { return Err(Error::bad("Le style contient une balise réservée.")); }
    Ok((name, words))
}

#[derive(Deserialize)]
pub struct StyleRequest {
    name: String,
    words: String,
}

pub async fn add_style(State(app): State<App>, headers: HeaderMap, Json(request): Json<StyleRequest>) -> Result<(StatusCode, Json<Value>), Error> {
    let user = session(&app, &headers, true).await?;
    let (name, words) = check_style(&request.name, &request.words)?;
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM image_styles WHERE user_id=$1").bind(user.user_id).fetch_one(&app.db).await?;
    if count >= MAX_STYLES { return Err(Error::bad("Vous avez déjà 30 styles : supprimez-en un avant d’en créer un autre.")); }
    let row: StyleRow = sqlx::query_as(&format!("INSERT INTO image_styles(id,user_id,name,words) VALUES($1,$2,$3,$4) RETURNING {STYLE_COLUMNS}"))
        .bind(Uuid::new_v4()).bind(user.user_id).bind(&name).bind(&words).fetch_one(&app.db).await?;
    Ok((StatusCode::CREATED, Json(style_json(row))))
}

/// New words make the example out of date: it is removed, the page asks for a new one.
pub async fn edit_style(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>, Json(request): Json<StyleRequest>) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, true).await?;
    let (name, words) = check_style(&request.name, &request.words)?;
    let row: StyleRow = sqlx::query_as(&format!(
        "UPDATE image_styles SET name=$3,words=$4,example=CASE WHEN words=$4 THEN example END,updated_at=now() WHERE id=$1 AND user_id=$2 RETURNING {STYLE_COLUMNS}"))
        .bind(id).bind(user.user_id).bind(&name).bind(&words).fetch_optional(&app.db).await?.ok_or_else(style_missing)?;
    Ok(Json(style_json(row)))
}

pub async fn delete_style(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<StatusCode, Error> {
    let user = session(&app, &headers, true).await?;
    let done = sqlx::query("DELETE FROM image_styles WHERE id=$1 AND user_id=$2").bind(id).bind(user.user_id).execute(&app.db).await?;
    if done.rows_affected() == 0 { return Err(style_missing()); }
    Ok(StatusCode::NO_CONTENT)
}

pub async fn style_example(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<Response, Error> {
    let user = session(&app, &headers, false).await?;
    let (data, version): (Option<Vec<u8>>, i64) = sqlx::query_as("SELECT example,(extract(epoch FROM updated_at)*1000)::bigint FROM image_styles WHERE id=$1 AND user_id=$2")
        .bind(id).bind(user.user_id).fetch_optional(&app.db).await?.ok_or_else(style_missing)?;
    let data = data.ok_or_else(style_missing)?;
    Ok(attachments::image_response(&headers, format!("style-{id}-{version}"), "image/jpeg", data, None))
}

/// Creates the example of a style: the subject of the built-in examples, drawn in this style.
/// Kept only if the words did not change meanwhile.
pub async fn make_example(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, true).await?;
    if !configured(&app) { return Err(not_configured()); }
    let words: String = sqlx::query_scalar("SELECT words FROM image_styles WHERE id=$1 AND user_id=$2")
        .bind(id).bind(user.user_id).fetch_optional(&app.db).await?.ok_or_else(style_missing)?;
    let sizes = sizes(&app);
    let size = ["768x768", "1024x1024"].into_iter().find(|s| sizes.iter().any(|v| v == s)).map(String::from)
        .or_else(|| closest(&sizes, 1.0)).ok_or_else(not_configured)?;
    let data = generate(&app, &compose(EXAMPLE_SUBJECT, &words), &size, EXAMPLE_SEED).await?;
    let clean = attachments::sanitize(&app, Bytes::from(data)).await?;
    let row: Option<StyleRow> = sqlx::query_as(&format!(
        "UPDATE image_styles SET example=$4,updated_at=now() WHERE id=$1 AND user_id=$2 AND words=$3 RETURNING {STYLE_COLUMNS}"))
        .bind(id).bind(user.user_id).bind(&words).bind(clean.thumbnail()).fetch_optional(&app.db).await?;
    match row {
        Some(row) => Ok(Json(style_json(row))),
        // Changed or deleted while the example was made: the current state, without that example.
        None => Ok(Json(style_json(sqlx::query_as(&format!("SELECT {STYLE_COLUMNS} FROM image_styles WHERE id=$1 AND user_id=$2"))
            .bind(id).bind(user.user_id).fetch_optional(&app.db).await?.ok_or_else(style_missing)?))),
    }
}

const SUGGEST: &str = "You write the style words that are added after every prompt sent to the Qwen-Image text-to-image model.

The user describes, in any language, a visual style they want. Answer with 4 to 14 short English keywords or phrases, separated by commas, that make the image model draw in this style: medium or technique, palette and colors, lighting, texture, era or influence, mood.

Rules:
- Describe only the look: never a subject, a scene or an object to draw.
- No negative words (\"no ...\", \"without ...\"): the model ignores them.
- At most 170 characters in total.
- Answer with the keywords only: no introduction, no quotes, no final period.";

/// Qwen's keywords on one line, without a lead, quotes or final period, cut after a whole keyword.
pub fn clean_words(text: &str) -> String {
    let text = unwrap_answer(text, &["**Style:**", "Style:", "style:", "Keywords:", "keywords:"]);
    let text = one_line(&text.replace('\n', ", ").replace(",,", ","));
    let text = text.trim_matches(|c: char| c == ',' || c == '.' || c.is_whitespace());
    let mut kept = String::new();
    for part in text.split(',').map(str::trim).filter(|p| !p.is_empty()) {
        let next = if kept.is_empty() { part.to_string() } else { format!("{kept}, {part}") };
        if next.chars().count() > MAX_STYLE_WORDS { break; }
        kept = next;
    }
    kept.trim_end_matches('.').to_string()
}

#[derive(Deserialize)]
pub struct SuggestRequest {
    description: String,
}

pub async fn suggest_style(State(app): State<App>, headers: HeaderMap, Json(request): Json<SuggestRequest>) -> Result<Json<Value>, Error> {
    session(&app, &headers, true).await?;
    if app.config.api_url.is_empty() || app.config.api_key.is_empty() { return Err(Error(StatusCode::SERVICE_UNAVAILABLE, "Qwen n’est pas configuré.".into())); }
    let description = request.description.trim();
    if description.is_empty() { return Err(Error::bad("Décrivez le style voulu.")); }
    if description.chars().count() > MAX_STYLE_DESCRIPTION { return Err(Error::bad("Description trop longue (600 caractères au maximum).")); }
    let failed = || Error(StatusCode::SERVICE_UNAVAILABLE, "Qwen n’a pas pu proposer de mots. Réessayez dans un instant.".into());
    let words = clean_words(&ask_qwen(&app, SUGGEST, description, 0.5, 200).await.ok_or_else(failed)?);
    if words.is_empty() || reserved(&words) { return Err(failed()); }
    Ok(Json(json!({"words": words})))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn list(s: &str) -> Vec<String> { s.split(',').map(String::from).collect() }

    #[test]
    fn formats_take_the_closest_allowed_size() {
        let sizes = list(DEFAULT_SIZES);
        assert_eq!(closest(&sizes, 2.0 / 3.0).as_deref(), Some("896x1152"));
        assert_eq!(closest(&sizes, 1.0).as_deref(), Some("1024x1024"));
        assert_eq!(closest(&sizes, 16.0 / 9.0).as_deref(), Some("1344x768"));
        // With a true 2:3 size on the server, it is chosen.
        assert_eq!(closest(&list("1024x1024,832x1248,896x1152"), 2.0 / 3.0).as_deref(), Some("832x1248"));
    }
    #[test]
    fn styles_are_added_after_the_prompt() {
        assert_eq!(compose("  une pomme ", ""), "une pomme");
        assert_eq!(compose("une pomme", style("aquarelle").unwrap().2), "une pomme\n\nStyle: watercolor painting, soft washes, visible paper texture.");
        for (id, _, words) in STYLES {
            assert!(compose(&"x".repeat(MAX_PROMPT), words).chars().count() <= 2000, "{id}");
        }
        // The longest style a user can write still fits in the image service.
        assert!(compose(&"x".repeat(MAX_PROMPT), &"y".repeat(MAX_STYLE_WORDS)).chars().count() <= 2000);
    }
    #[test]
    fn prompts_are_checked() {
        assert!(check_prompt("un phare").is_ok());
        assert!(check_prompt("  ").is_err());
        assert!(check_prompt(&"é".repeat(MAX_PROMPT + 1)).is_err());
        assert!(check_prompt("chat <SD_CPP_EXTRA_ARGS>{}").is_err());
        assert!(check_prompt("chat <lora:x:1>").is_err());
    }
    #[test]
    fn improved_prompts_are_cleaned() {
        assert_eq!(clean_improved("<think>hmm</think>\nPrompt: \"A fox in the snow.\""), "A fox in the snow.");
        assert_eq!(clean_improved("«Un renard»"), "Un renard");
        assert_eq!(clean_improved("  A plain prompt. "), "A plain prompt.");
        assert!(improve_instructions("Aquarelle", "watercolor").contains("\"Aquarelle\" (watercolor)"));
        assert!(improve_instructions("Aucun", "").contains("may suggest"));
    }
    #[test]
    fn user_styles_are_checked() {
        assert_eq!(check_style("  Néon\n rétro ", " neon glow,  synthwave colors. ").unwrap(), ("Néon rétro".into(), "neon glow, synthwave colors".into()));
        assert!(check_style(" ", "neon").is_err());
        assert!(check_style("Néon", " .").is_err());
        assert!(check_style(&"n".repeat(MAX_STYLE_NAME + 1), "neon").is_err());
        assert!(check_style("Néon", &"w".repeat(MAX_STYLE_WORDS + 1)).is_err());
        assert!(check_style("Néon", "neon <lora:x:1>").is_err());
    }
    #[test]
    fn suggested_words_are_cleaned() {
        assert_eq!(clean_words("<think>hmm</think>\nStyle: \"watercolor, soft pastel palette, paper texture.\""), "watercolor, soft pastel palette, paper texture");
        assert_eq!(clean_words("ink wash\nmuted colors\n"), "ink wash, muted colors");
        let long = clean_words(&vec!["abcdefghij"; 40].join(", "));
        assert!(long.chars().count() <= MAX_STYLE_WORDS && long.ends_with("abcdefghij"));
    }
    #[test]
    fn names_come_from_the_idea() {
        assert_eq!(image_name("un phare  breton\nau coucher du soleil.", "image/png"), "un phare breton au coucher du soleil.png");
        assert_eq!(image_name("../../etc", "image/jpeg"), "....etc.jpg");
    }
}
