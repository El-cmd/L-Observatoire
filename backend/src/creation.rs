//! Images tab: creates images with the image model served next to Qwen (qwen-image-turbo through
//! LiteLLM). Each image goes through image-guard like a sent image, then into the user's library
//! with the way it was made. The prompt can first be rewritten by Qwen ("Améliorer le prompt").
use crate::{App, Error, attachments, session};
use axum::{Json, body::Bytes, extract::State, http::{HeaderMap, StatusCode}};
use base64::{Engine, engine::general_purpose::STANDARD};
use rand::Rng;
use serde::Deserialize;
use serde_json::{Value, json};
use std::time::{Duration, Instant};

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

/// Buttons of the page: each format takes the allowed size closest to its proportions.
const FORMATS: &[(&str, f64)] = &[("2:3", 2.0 / 3.0), ("1:1", 1.0), ("16:9", 16.0 / 9.0)];

fn style(id: &str) -> Option<&'static (&'static str, &'static str, &'static str)> {
    STYLES.iter().find(|s| s.0 == id)
}

/// Prompt really sent to the image model.
pub fn compose(prompt: &str, style_id: &str) -> String {
    let prompt = prompt.trim();
    match style(style_id).map(|s| s.2).filter(|s| !s.is_empty()) {
        Some(words) => format!("{prompt}\n\nStyle: {words}."),
        None => prompt.to_string(),
    }
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
    session(&app, &headers, false).await?;
    let sizes = sizes(&app);
    let formats: Vec<Value> = FORMATS.iter().filter_map(|(name, ratio)| closest(&sizes, *ratio).map(|size| json!({"name": name, "size": size}))).collect();
    let default_size = if sizes.iter().any(|s| s == "1024x1024") { "1024x1024".to_string() } else { sizes.first().cloned().unwrap_or_default() };
    Ok(Json(json!({
        "configured": configured(&app),
        "styles": STYLES.iter().map(|(id, name, words)| json!({"id": id, "name": name, "words": words})).collect::<Vec<_>>(),
        "default_style": DEFAULT_STYLE,
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

pub async fn create(State(app): State<App>, headers: HeaderMap, Json(request): Json<Request>) -> Result<(StatusCode, Json<Value>), Error> {
    let user = session(&app, &headers, true).await?;
    if !configured(&app) { return Err(Error(StatusCode::SERVICE_UNAVAILABLE, "La création d’images n’est pas configurée.".into())); }
    check_prompt(&request.prompt)?;
    let improved = request.improved.as_deref().map(str::trim).filter(|s| !s.is_empty());
    if let Some(text) = improved { check_prompt(text)?; }
    let style_id = request.style.as_deref().unwrap_or(DEFAULT_STYLE);
    if style(style_id).is_none() { return Err(Error::bad("Style inconnu.")); }
    if !sizes(&app).contains(&request.size) { return Err(Error::bad("Taille d’image non prise en charge.")); }
    // An image weighs up to ~3 Mo before image-guard re-encodes it.
    if attachments::used_bytes(&app, user.user_id).await? + 3 * 1024 * 1024 > attachments::QUOTA_BYTES {
        return Err(Error::bad(attachments::FULL));
    }
    let sent = compose(improved.unwrap_or(&request.prompt), style_id);
    let seed: u32 = rand::thread_rng().gen_range(0..i32::MAX as u32);
    let busy = || Error(StatusCode::SERVICE_UNAVAILABLE, "Le service d’images est occupé ou indisponible. Réessayez dans un instant.".into());
    let started = Instant::now();
    let _turn = app.images.acquire().await.map_err(|_| busy())?;
    let response = app.http.post(format!("{}/images/generations", app.config.api_url)).bearer_auth(&app.config.api_key)
        .timeout(Duration::from_secs(150))
        .json(&json!({"model": app.config.image_model, "prompt": sent, "n": 1, "size": request.size, "seed": seed, "response_format": "b64_json"}))
        .send().await.map_err(|_| busy())?;
    let status = response.status();
    if !status.is_success() {
        tracing::warn!(status = status.as_u16(), "image generation failed");
        return Err(busy());
    }
    let value: Value = response.json().await.map_err(|_| busy())?;
    let data = value.pointer("/data/0/b64_json").and_then(Value::as_str).and_then(|b| STANDARD.decode(b).ok()).ok_or_else(busy)?;
    drop(_turn);
    let clean = attachments::sanitize(&app, Bytes::from(data)).await?;
    let generation = json!({"prompt": request.prompt.trim(), "sent": sent, "style": style_id, "size": request.size, "seed": seed,
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

pub fn improve_instructions(style_id: &str) -> String {
    let rule = match style(style_id) {
        Some((_, name, words)) if !words.is_empty() => format!(
            "The style \"{name}\" ({words}) is added separately after your prompt: describe the scene so it fits this style, but do not name another style or medium."),
        _ => "You may suggest an appropriate visual style or medium if the idea calls for one.".to_string(),
    };
    IMPROVE.replace("{style}", &rule)
}

/// Removes a possible <think> block, a "Prompt:" lead and quotes around the whole text.
pub fn clean_improved(text: &str) -> String {
    let mut text = text.rsplit_once("</think>").map_or(text, |(_, after)| after).trim();
    for lead in ["**Prompt:**", "Prompt:", "prompt:"] {
        if let Some(rest) = text.strip_prefix(lead) { text = rest.trim(); }
    }
    for (open, close) in [('"', '"'), ('\'', '\''), ('«', '»'), ('“', '”')] {
        if text.chars().count() > 1 && text.starts_with(open) && text.ends_with(close) {
            text = text[open.len_utf8()..text.len() - close.len_utf8()].trim();
            break;
        }
    }
    text.chars().take(MAX_PROMPT).collect()
}

#[derive(Deserialize)]
pub struct ImproveRequest {
    prompt: String,
    #[serde(default)]
    style: Option<String>,
}

pub async fn improve(State(app): State<App>, headers: HeaderMap, Json(request): Json<ImproveRequest>) -> Result<Json<Value>, Error> {
    session(&app, &headers, true).await?;
    if app.config.api_url.is_empty() || app.config.api_key.is_empty() { return Err(Error(StatusCode::SERVICE_UNAVAILABLE, "Qwen n’est pas configuré.".into())); }
    check_prompt(&request.prompt)?;
    let style_id = request.style.as_deref().unwrap_or(DEFAULT_STYLE);
    if style(style_id).is_none() { return Err(Error::bad("Style inconnu.")); }
    let failed = || Error(StatusCode::SERVICE_UNAVAILABLE, "Qwen n’a pas pu améliorer la description. Réessayez dans un instant.".into());
    let body = json!({"model": app.config.model, "reasoning_effort": "none", "temperature": 0.7, "max_tokens": 400, "stream": false,
        "messages": [{"role": "system", "content": improve_instructions(style_id)}, {"role": "user", "content": request.prompt.trim()}]});
    let response = app.http.post(format!("{}/chat/completions", app.config.api_url)).bearer_auth(&app.config.api_key)
        .timeout(Duration::from_secs(90)).json(&body).send().await.map_err(|_| failed())?;
    if !response.status().is_success() { return Err(failed()); }
    let value: Value = response.json().await.map_err(|_| failed())?;
    let text = clean_improved(value.pointer("/choices/0/message/content").and_then(Value::as_str).unwrap_or(""));
    if text.is_empty() || reserved(&text) { return Err(failed()); }
    Ok(Json(json!({"prompt": text})))
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
        assert_eq!(compose("  une pomme ", "aucun"), "une pomme");
        assert_eq!(compose("une pomme", "aquarelle"), "une pomme\n\nStyle: watercolor painting, soft washes, visible paper texture.");
        for (id, _, _) in STYLES {
            assert!(compose(&"x".repeat(MAX_PROMPT), id).chars().count() <= 2000, "{id}");
        }
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
        assert!(improve_instructions("aquarelle").contains("\"Aquarelle\""));
        assert!(improve_instructions("aucun").contains("may suggest"));
    }
    #[test]
    fn names_come_from_the_idea() {
        assert_eq!(image_name("un phare  breton\nau coucher du soleil.", "image/png"), "un phare breton au coucher du soleil.png");
        assert_eq!(image_name("../../etc", "image/jpeg"), "....etc.jpg");
    }
}
