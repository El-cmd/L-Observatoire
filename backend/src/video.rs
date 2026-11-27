//! Video tab: an image of the library becomes a short video (Wan 2.2 I2V A14B, served on the AI server behind
//! the same LiteLLM as Qwen). The video service makes one video at a time, forgets its videos after 24 h or
//! when it restarts, and can neither cancel nor delete one. So this API keeps its own queue in the `videos`
//! table: it sends one video at a time, follows it in a background task (never in the browser: a closed page
//! loses nothing, and a restarted API takes up the queue from the database), and stores the finished MP4 in
//! the user's library. GIF and WebP are made on demand from that kept MP4 (`/video-export` of LiteLLM).
use crate::{App, Error, attachments, creation, session};
use axum::{
    Json,
    extract::{Path, State},
    http::{HeaderMap, HeaderValue, StatusCode, header},
    response::{IntoResponse, Response},
};
use base64::{Engine, engine::general_purpose::STANDARD};
use rand::Rng;
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::types::Json as DbJson;
use std::time::Duration;
use uuid::Uuid;

/// Largest MP4 kept in the library (5 s in 480p weigh 2 to 4 Mo).
pub const MAX_VIDEO_BYTES: usize = 30 * 1024 * 1024;
/// Longest description; a camera sentence (~70 characters) is added after it.
pub const MAX_PROMPT: usize = 1800;
pub const MAX_NEGATIVE: usize = 1000;
/// Largest starting image sent to the video service.
const MAX_SOURCE_BYTES: usize = 10 * 1024 * 1024;
/// Videos of an account in the list of the tab.
const LISTED: i64 = 30;

/// What the image of Wan 2.2 should avoid; the same as the video lab of Amelia.
pub const DEFAULT_NEGATIVE: &str = "blurry, low quality, distorted, deformed, extra limbs, bad hands, jittery motion, flickering, static image, watermark, text, subtitles";

/// Sizes of Wan 2.2 I2V: (id, portrait, landscape, measured). 720p has never been timed on the AI server: its
/// duration is an estimate (about 3 times 480p), and the page says so.
pub const RESOLUTIONS: &[(&str, (u32, u32), (u32, u32), bool)] = &[("480p", (480, 832), (832, 480), true), ("720p", (720, 1280), (1280, 720), false)];
/// Durations offered (seconds) and their number of images, of the form 4k + 1 as the model wants (16 per second).
pub const DURATIONS: &[(u32, u32)] = &[(2, 33), (3, 49), (5, 81)];
/// 40 steps is the official setting; fewer is quicker and a little less sharp.
pub const STEPS: &[u32] = &[20, 30, 40];
pub const FPS: u32 = 16;
/// "Fluidité": RIFE doubles the images after the generation (16 → 32 per second, same duration).
pub const FPS_SMOOTH: u32 = 32;
const RIFE: &str = "/models/rife-4.22-lite";
// Official settings of Wan 2.2 I2V A14B (guidance of both experts, noise shift).
const GUIDANCE: &str = "3.5";
const SHIFT: &str = "5.0";

/// Camera movements offered in one click: an English sentence added after the description.
pub const CAMERAS: &[(&str, &str, &str)] = &[
    ("fixe", "Fixe", "Static camera, no camera movement."),
    ("avance", "Avance", "The camera slowly pushes in toward the subject."),
    ("recul", "Recul", "The camera slowly pulls back, revealing more of the scene."),
    ("gauche", "Vers la gauche", "The camera pans slowly to the left."),
    ("droite", "Vers la droite", "The camera pans slowly to the right."),
    ("orbite", "Orbite", "The camera slowly orbits around the subject."),
    ("travelling", "Travelling", "Smooth lateral tracking shot following the subject."),
    ("contre-plongee", "Contre-plongée", "Low-angle shot, the camera slowly tilts up."),
];

/// Seconds of computation, from the measures of 27/11/2026 on the AI server (480p): 491 s for 81 images and
/// 40 steps, 91 s for 33 images and 20 steps; the time follows images × steps. 720p: ×3, not measured.
pub fn estimate(frames: u32, steps: u32, hd: bool, smooth: bool) -> u32 {
    let seconds = (0.155 * frames as f64 * steps as f64 - 11.0) * if hd { 3.0 } else { 1.0 } * if smooth { 1.03 } else { 1.0 };
    seconds.round().max(30.0) as u32
}

/// The Qwen instruction to write the description of a video, from the video lab of Amelia (LaboVideoController::CONSIGNE).
const DESCRIBE: &str = "You write one prompt for the Wan 2.2 image-to-video model, which animates the attached image into a short video clip of a few seconds. The user says, in any language, what should happen; they may say nothing.

Rules:
- First look carefully at the attached image: the subjects and how many there are, their appearance, the setting, the lighting and the visual style.
- Describe the scene as it appears in the image, then the motion during the clip: what moves and how (speed, direction), facial expressions and gestures, and how the surroundings react (wind, water, light, background).
- Add one camera movement only if it helps the shot (for example a slow push-in, a gentle pan, an orbit, or a static shot). If the user asked for a camera movement, use exactly that one.
- Keep everything consistent with the image: same subjects, faces, clothes, colors and style. Do not add new people or objects unless the user asks for them.
- The motion must be physically plausible and fit in a few seconds.
- If the user said nothing, choose a natural, subtle motion that suits the image.
- Write in English, as a single paragraph of 60 to 120 words.
- Answer with the prompt only: no introduction, no title, no list, no quotes around the whole prompt.";

/// What the user asked, checked and ready to send.
#[derive(Debug, PartialEq)]
pub struct Settings {
    pub resolution: &'static str,
    pub orientation: &'static str,
    pub width: u32,
    pub height: u32,
    pub duration: u32,
    pub frames: u32,
    pub steps: u32,
    pub smooth: bool,
    pub seed: u32,
    pub camera: Option<&'static (&'static str, &'static str, &'static str)>,
}
impl Settings {
    fn json(&self) -> Value {
        json!({"resolution": self.resolution, "orientation": self.orientation, "size": format!("{}x{}", self.width, self.height),
               "duration": self.duration, "frames": self.frames, "steps": self.steps, "smooth": self.smooth,
               "fps": if self.smooth { FPS_SMOOTH } else { FPS }, "seed": self.seed, "camera": self.camera.map(|c| c.0),
               "estimate_seconds": estimate(self.frames, self.steps, self.resolution != "480p", self.smooth)})
    }
}

pub fn settings(resolution: &str, orientation: &str, duration: u32, steps: u32, smooth: bool, seed: Option<u32>, camera: Option<&str>) -> Result<Settings, Error> {
    let (resolution, portrait, landscape, _) = RESOLUTIONS.iter().find(|r| r.0 == resolution).ok_or_else(|| Error::bad("Résolution inconnue : 480p ou 720p."))?;
    let (orientation, (width, height)) = match orientation {
        "portrait" => ("portrait", *portrait),
        "paysage" => ("paysage", *landscape),
        _ => return Err(Error::bad("Format inconnu : portrait ou paysage.")),
    };
    let frames = DURATIONS.iter().find(|d| d.0 == duration).map(|d| d.1).ok_or_else(|| Error::bad("Durée possible : 2, 3 ou 5 secondes."))?;
    if !STEPS.contains(&steps) { return Err(Error::bad("Étapes possibles : 20, 30 ou 40.")); }
    let seed = match seed {
        Some(seed) if seed > i32::MAX as u32 => return Err(Error::bad("Graine trop grande (2 147 483 647 au plus).")),
        Some(seed) => seed,
        None => rand::thread_rng().gen_range(0..i32::MAX as u32),
    };
    let camera = match camera.map(str::trim).filter(|c| !c.is_empty()) {
        Some(id) => Some(CAMERAS.iter().find(|c| c.0 == id).ok_or_else(|| Error::bad("Mouvement de caméra inconnu."))?),
        None => None,
    };
    Ok(Settings { resolution, orientation, width, height, duration, frames, steps, smooth, seed, camera })
}

/// Text really sent to the video model: the description, then the camera sentence.
pub fn compose(text: &str, camera: Option<&str>) -> String {
    let text = text.split_whitespace().collect::<Vec<_>>().join(" ");
    match camera {
        Some(sentence) if !text.is_empty() => format!("{text} {sentence}"),
        Some(sentence) => sentence.to_string(),
        None => text,
    }
}

/// Tags read by the video server as native settings are refused, like in the Images tab.
fn check_text(text: &str, max: usize, what: &str) -> Result<(), Error> {
    if text.chars().count() > max { return Err(Error::bad(&format!("{what} trop longue ({max} caractères au maximum)."))); }
    let lower = text.to_lowercase();
    if lower.contains("<lora:") || lower.contains("sd_cpp_extra_args") { return Err(Error::bad(&format!("{what} contient une balise réservée."))); }
    Ok(())
}

/// The identifier given by LiteLLM: "video_" then base64 (it encodes the provider and the job). Kept exactly.
pub fn valid_id(id: &str) -> bool {
    id.len() <= 400 && id.strip_prefix("video_").is_some_and(|rest| rest.len() >= 8 && rest.bytes().all(|b| b.is_ascii_alphanumeric() || b"+/=_-".contains(&b)))
}

/// The identifier in a path: base64 may hold "/" and "+".
fn path_part(id: &str) -> String {
    id.bytes().map(|b| if b.is_ascii_alphanumeric() || b"-_.~".contains(&b) { (b as char).to_string() } else { format!("%{b:02X}") }).collect()
}

/// An MP4 starts with an "ftyp" box; anything else (an error page, JSON) is refused.
pub fn is_mp4(data: &[u8]) -> bool {
    data.len() >= 12 && &data[4..8] == b"ftyp"
}

fn configured(app: &App) -> bool {
    !app.config.api_url.is_empty() && !app.config.api_key.is_empty() && !app.config.video_model.is_empty()
}

fn not_configured() -> Error {
    Error(StatusCode::SERVICE_UNAVAILABLE, "La création de vidéos n’est pas configurée.".into())
}

fn video_missing() -> Error {
    Error(StatusCode::NOT_FOUND, "Vidéo introuvable.".into())
}

pub async fn config(State(app): State<App>, headers: HeaderMap) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, false).await?;
    Ok(Json(json!({
        "configured": configured(&app),
        "resolutions": RESOLUTIONS.iter().map(|(id, portrait, landscape, measured)| json!({"id": id, "portrait": format!("{}x{}", portrait.0, portrait.1),
            "paysage": format!("{}x{}", landscape.0, landscape.1), "measured": measured})).collect::<Vec<_>>(),
        "durations": DURATIONS.iter().map(|(seconds, frames)| json!({"seconds": seconds, "frames": frames})).collect::<Vec<_>>(),
        "steps": STEPS,
        "fps": FPS, "fps_smooth": FPS_SMOOTH,
        "cameras": CAMERAS.iter().map(|(id, name, sentence)| json!({"id": id, "name": name, "sentence": sentence})).collect::<Vec<_>>(),
        "default_negative": DEFAULT_NEGATIVE,
        "max_prompt": MAX_PROMPT, "max_negative": MAX_NEGATIVE,
        "max_total": app.config.video_max_total,
        // Videos of every account waiting or being made: the page says when the queue is full.
        "open": sqlx::query_scalar::<_, i64>("SELECT count(*) FROM videos WHERE status IN ('waiting','running')").fetch_one(&app.db).await?,
        "videos": listed(&app, user.user_id).await?,
    })))
}

const COLUMNS: &str = "id,status,service_status,settings,prompt,improved,sent,negative,source_id,attachment_id,error,created_at,submitted_at,started_at,finished_at";
type Time = chrono::DateTime<chrono::Utc>;
type Row = (Uuid, String, Option<String>, DbJson<Value>, String, Option<String>, String, String, Option<Uuid>, Option<Uuid>, Option<String>,
            Time, Option<Time>, Option<Time>, Option<Time>);

/// Place in the queue of L'Observatoire: 0 when sent to the video service, otherwise the number of videos
/// before it (the one being made included). Videos of other sites on the same server are not seen.
async fn position(app: &App, id: Uuid, status: &str, created: Time) -> Result<i64, Error> {
    if status != "waiting" { return Ok(0); }
    Ok(sqlx::query_scalar("SELECT count(*) FROM videos WHERE status IN ('waiting','running') AND (created_at,id) < ($1,$2)")
        .bind(created).bind(id).fetch_one(&app.db).await?)
}

async fn row_json(app: &App, row: Row) -> Result<Value, Error> {
    let (id, status, service_status, settings, prompt, improved, sent, negative, source, attachment, error, created, submitted, started, finished) = row;
    Ok(json!({"id": id, "status": status, "service_status": service_status, "settings": settings.0, "prompt": prompt, "improved": improved,
              "sent": sent, "negative": negative, "source": source, "attachment": attachment, "error": error, "created_at": created,
              "submitted_at": submitted, "started_at": started, "finished_at": finished, "position": position(app, id, &status, created).await?}))
}

async fn listed(app: &App, user: Uuid) -> Result<Vec<Value>, Error> {
    let rows: Vec<Row> = sqlx::query_as(&format!("SELECT {COLUMNS} FROM videos WHERE user_id=$1 ORDER BY created_at DESC LIMIT {LISTED}"))
        .bind(user).fetch_all(&app.db).await?;
    let mut list = Vec::with_capacity(rows.len());
    for row in rows { list.push(row_json(app, row).await?); }
    Ok(list)
}

async fn one(app: &App, user: Uuid, id: Uuid) -> Result<Value, Error> {
    let row: Row = sqlx::query_as(&format!("SELECT {COLUMNS} FROM videos WHERE id=$1 AND user_id=$2"))
        .bind(id).bind(user).fetch_optional(&app.db).await?.ok_or_else(video_missing)?;
    row_json(app, row).await
}

pub async fn get_one(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, false).await?;
    Ok(Json(one(&app, user.user_id, id).await?))
}

/// The starting image, shown while the video waits or is made (it becomes the thumbnail of the video).
pub async fn thumbnail(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<Response, Error> {
    let user = session(&app, &headers, false).await?;
    let data: Vec<u8> = sqlx::query_scalar("SELECT source_thumbnail FROM videos WHERE id=$1 AND user_id=$2")
        .bind(id).bind(user.user_id).fetch_optional(&app.db).await?.ok_or_else(video_missing)?;
    Ok(attachments::image_response(&headers, format!("video-{id}-t"), "image/jpeg", data, None))
}

#[derive(Deserialize)]
pub struct CreateRequest {
    /// An image of the user's library (sent from the device, it went through image-guard on its way in).
    source: Uuid,
    prompt: String,
    /// Written by "Améliorer"; `prompt` keeps the user's text.
    #[serde(default)]
    improved: Option<String>,
    resolution: String,
    orientation: String,
    duration: u32,
    steps: u32,
    #[serde(default)]
    smooth: bool,
    #[serde(default)]
    seed: Option<u32>,
    #[serde(default)]
    negative: Option<String>,
    #[serde(default)]
    camera: Option<String>,
}

/// Puts a video in the queue of L'Observatoire. At most one video waiting or being made per account, and
/// `VIDEO_MAX_TOTAL` in all (the server makes one at a time, 8 min for 5 s): 429 beyond.
pub async fn create(State(app): State<App>, headers: HeaderMap, Json(request): Json<CreateRequest>) -> Result<(StatusCode, Json<Value>), Error> {
    let user = session(&app, &headers, true).await?;
    if !configured(&app) { return Err(not_configured()); }
    let prompt = request.prompt.trim();
    let improved = request.improved.as_deref().map(str::trim).filter(|s| !s.is_empty());
    check_text(prompt, MAX_PROMPT, "La description")?;
    if let Some(text) = improved { check_text(text, MAX_PROMPT, "La description")?; }
    let negative = request.negative.as_deref().unwrap_or(DEFAULT_NEGATIVE).split_whitespace().collect::<Vec<_>>().join(" ");
    check_text(&negative, MAX_NEGATIVE, "La description négative")?;
    let settings = settings(&request.resolution, &request.orientation, request.duration, request.steps, request.smooth, request.seed, request.camera.as_deref())?;
    let sent = compose(improved.unwrap_or(prompt), settings.camera.map(|c| c.2));
    if sent.is_empty() { return Err(Error::bad("Décrivez le mouvement, ou choisissez un mouvement de caméra.")); }
    let found: Option<(String, Vec<u8>, Vec<u8>)> = sqlx::query_as("SELECT mime,data,thumbnail FROM attachments WHERE id=$1 AND user_id=$2 AND kind='image' AND status='ready'")
        .bind(request.source).bind(user.user_id).fetch_optional(&app.db).await?;
    let (mime, data, thumbnail) = found.ok_or_else(|| Error::bad("L’image de départ n’est plus dans votre bibliothèque."))?;
    if data.len() > MAX_SOURCE_BYTES { return Err(Error::bad("L’image de départ est trop lourde (10 Mo au maximum).")); }
    // Room kept for the MP4 to come.
    if attachments::used_bytes(&app, user.user_id).await? + MAX_VIDEO_BYTES as i64 > attachments::QUOTA_BYTES {
        return Err(Error::bad("Votre bibliothèque est presque pleine : gardez 30 Mo de libre pour une vidéo (supprimez des fichiers)."));
    }
    let mut tx = app.db.begin().await?;
    // One request at a time checks the limits: two clicks cannot both pass.
    sqlx::query("SELECT pg_advisory_xact_lock(hashtext('observatoire-videos'))").execute(&mut *tx).await?;
    let (mine, all): (i64, i64) = sqlx::query_as("SELECT count(*) FILTER (WHERE user_id=$1), count(*) FROM videos WHERE status IN ('waiting','running')")
        .bind(user.user_id).fetch_one(&mut *tx).await?;
    if mine > 0 {
        return Err(Error(StatusCode::TOO_MANY_REQUESTS, "Vous avez déjà une vidéo en cours : attendez qu’elle soit finie pour en lancer une autre.".into()));
    }
    if all >= app.config.video_max_total {
        return Err(Error(StatusCode::TOO_MANY_REQUESTS, "La file des vidéos est pleine : réessayez dans quelques minutes.".into()));
    }
    let id = Uuid::new_v4();
    sqlx::query("INSERT INTO videos(id,user_id,settings,prompt,improved,sent,negative,source_id,source_mime,source_data,source_thumbnail) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)")
        .bind(id).bind(user.user_id).bind(DbJson(settings.json())).bind(prompt).bind(improved).bind(&sent).bind(&negative)
        .bind(request.source).bind(&mime).bind(&data).bind(&thumbnail).execute(&mut *tx).await?;
    tx.commit().await?;
    app.videos.notify_one();
    Ok((StatusCode::CREATED, Json(one(&app, user.user_id, id).await?)))
}

/// Removes a video from the list: a waiting one leaves the queue (cancelled); one being made cannot be stopped
/// (the video service cannot cancel); a finished one stays in the library.
pub async fn delete(State(app): State<App>, headers: HeaderMap, Path(id): Path<Uuid>) -> Result<StatusCode, Error> {
    let user = session(&app, &headers, true).await?;
    let status: String = sqlx::query_scalar("SELECT status FROM videos WHERE id=$1 AND user_id=$2")
        .bind(id).bind(user.user_id).fetch_optional(&app.db).await?.ok_or_else(video_missing)?;
    if status == "running" {
        return Err(Error(StatusCode::CONFLICT, "Cette vidéo est déjà en cours de création : elle ne peut plus être arrêtée.".into()));
    }
    // Not sent meanwhile: the background task takes waiting videos only through the same status.
    let done = sqlx::query("DELETE FROM videos WHERE id=$1 AND user_id=$2 AND status<>'running'").bind(id).bind(user.user_id).execute(&app.db).await?;
    if done.rows_affected() == 0 {
        return Err(Error(StatusCode::CONFLICT, "Cette vidéo vient de partir en création : elle ne peut plus être arrêtée.".into()));
    }
    Ok(StatusCode::NO_CONTENT)
}

#[derive(Deserialize)]
pub struct ImproveRequest {
    #[serde(default)]
    prompt: String,
    source: Uuid,
}

/// "Améliorer": Qwen looks at the starting image and writes the description of the video, in English.
pub async fn improve(State(app): State<App>, headers: HeaderMap, Json(request): Json<ImproveRequest>) -> Result<Json<Value>, Error> {
    let user = session(&app, &headers, true).await?;
    if app.config.api_url.is_empty() || app.config.api_key.is_empty() { return Err(Error(StatusCode::SERVICE_UNAVAILABLE, "Qwen n’est pas configuré.".into())); }
    check_text(request.prompt.trim(), MAX_PROMPT, "La description")?;
    let thumbnail: Vec<u8> = sqlx::query_scalar("SELECT thumbnail FROM attachments WHERE id=$1 AND user_id=$2 AND kind='image' AND status='ready'")
        .bind(request.source).bind(user.user_id).fetch_optional(&app.db).await?
        .ok_or_else(|| Error::bad("L’image de départ n’est plus dans votre bibliothèque."))?;
    let asked = request.prompt.trim();
    let content = json!([
        {"type": "text", "text": if asked.is_empty() { "(nothing: choose a natural, subtle motion)" } else { asked }},
        {"type": "image_url", "image_url": {"url": format!("data:image/jpeg;base64,{}", STANDARD.encode(&thumbnail))}},
    ]);
    let failed = || Error(StatusCode::SERVICE_UNAVAILABLE, "Qwen n’a pas pu écrire la description. Réessayez dans un instant.".into());
    let text = creation::clean_improved(&creation::ask_qwen(&app, DESCRIBE, content, 0.7, 400).await.ok_or_else(failed)?);
    if text.is_empty() || check_text(&text, MAX_PROMPT, "La description").is_err() { return Err(failed()); }
    Ok(Json(json!({"prompt": text})))
}

#[derive(Deserialize)]
pub struct ExportRequest {
    /// A video of the library.
    attachment: Uuid,
    format: String,
}

/// GIF or animated WebP of a video of the library, made by the AI server from the kept MP4 (so it works long
/// after the 24 h of the video service). Given to download, not stored.
pub async fn export(State(app): State<App>, headers: HeaderMap, Json(request): Json<ExportRequest>) -> Result<Response, Error> {
    let user = session(&app, &headers, true).await?;
    if !configured(&app) { return Err(not_configured()); }
    let (mime, magic): (&str, fn(&[u8]) -> bool) = match request.format.as_str() {
        "gif" => ("image/gif", |d| d.starts_with(b"GIF89a")),
        "webp" => ("image/webp", |d| d.len() >= 12 && d.starts_with(b"RIFF") && &d[8..12] == b"WEBP"),
        _ => return Err(Error::bad("Format inconnu : GIF ou WebP.")),
    };
    let (name, data): (String, Vec<u8>) = sqlx::query_as("SELECT name,data FROM attachments WHERE id=$1 AND user_id=$2 AND kind='video'")
        .bind(request.attachment).bind(user.user_id).fetch_optional(&app.db).await?.ok_or_else(video_missing)?;
    let busy = || Error(StatusCode::SERVICE_UNAVAILABLE, "La conversion n’a pas pu se faire. Réessayez dans un instant.".into());
    let (content_type, body) = creation::multipart(&[("format", request.format.clone())], &[("file", data.as_slice(), "video/mp4")]);
    let response = app.http.post(format!("{}/video-export", app.config.api_url)).bearer_auth(&app.config.api_key)
        .header("Content-Type", content_type).body(body).timeout(Duration::from_secs(95)).send().await.map_err(|_| busy())?;
    let status = response.status();
    if status == StatusCode::TOO_MANY_REQUESTS {
        return Err(Error(StatusCode::SERVICE_UNAVAILABLE, "Deux conversions sont déjà en cours sur le serveur : réessayez dans un instant.".into()));
    }
    if !status.is_success() {
        tracing::warn!(status = status.as_u16(), "video export failed");
        return Err(busy());
    }
    let out = response.bytes().await.map_err(|_| busy())?;
    if !magic(&out) { return Err(busy()); }
    let stem = name.rsplit_once('.').map_or(name.as_str(), |(stem, _)| stem);
    let file = attachments::clean_name(Some(&format!("{stem}.{}", request.format)), &format!("video.{}", request.format));
    let mut response = out.into_response();
    let headers = response.headers_mut();
    headers.insert(header::CONTENT_TYPE, HeaderValue::from_static(mime));
    headers.insert(header::CONTENT_DISPOSITION, attachments::disposition(&file, true));
    Ok(response)
}

// --- Background task: the queue, the follow-up, the MP4 into the library ---

/// Follows the queue every `VIDEO_POLL_SECONDS` (sooner when a video is added) until the API stops.
pub async fn follow(app: App) {
    let mut shutdown = app.shutdown.clone();
    loop {
        if let Err(error) = tick(&app).await { tracing::warn!(error = %error.1, "video queue"); }
        tokio::select! {
            _ = tokio::time::sleep(app.config.video_poll) => {}
            _ = app.videos.notified() => {}
            _ = shutdown.changed() => return,
        }
    }
}

/// Sent videos without news for this long are given up (the tunnel or the server is down).
const GIVE_UP: &str = "3 hours";
/// Failed sendings before a waiting video is given up.
const MAX_ATTEMPTS: i32 = 5;

async fn tick(app: &App) -> Result<(), Error> {
    let running: Vec<(Uuid, String)> = sqlx::query_as("SELECT id,service_id FROM videos WHERE status='running' ORDER BY submitted_at")
        .fetch_all(&app.db).await?;
    for (id, service_id) in &running { check(app, *id, service_id).await?; }
    // One video at a time on the server: the next one leaves only when nothing of ours is being made.
    let still: i64 = sqlx::query_scalar("SELECT count(*) FROM videos WHERE status='running'").fetch_one(&app.db).await?;
    if still > 0 { return Ok(()); }
    let next: Option<Uuid> = sqlx::query_scalar("SELECT id FROM videos WHERE status='waiting' ORDER BY created_at,id LIMIT 1").fetch_optional(&app.db).await?;
    if let Some(id) = next { submit(app, id).await?; }
    Ok(())
}

async fn finish(app: &App, id: Uuid, status: &str, error: &str) -> Result<(), Error> {
    // The starting image is no longer needed (the library keeps its own copy, if any).
    sqlx::query("UPDATE videos SET status=$2,error=$3,finished_at=now(),source_data=''::bytea WHERE id=$1 AND status IN ('waiting','running')")
        .bind(id).bind(status).bind(error).execute(&app.db).await?;
    Ok(())
}

fn service_message(value: &Value) -> Option<String> {
    let message = value.pointer("/error/message").or_else(|| value.get("error")).or_else(|| value.get("detail")).and_then(Value::as_str)?;
    Some(message.chars().take(300).collect())
}

async fn submit(app: &App, id: Uuid) -> Result<(), Error> {
    type Waiting = (DbJson<Value>, String, String, String, Vec<u8>);
    let Some((settings, sent, negative, mime, data)): Option<Waiting> =
        sqlx::query_as("SELECT settings,sent,negative,source_mime,source_data FROM videos WHERE id=$1 AND status='waiting'").bind(id).fetch_optional(&app.db).await? else { return Ok(()); };
    let value = |name: &str| settings.0.get(name).map(|v| v.as_str().map(String::from).unwrap_or_else(|| v.to_string())).unwrap_or_default();
    let size = value("size");
    let (width, height) = size.split_once('x').map(|(w, h)| (w.to_string(), h.to_string())).unwrap_or_default();
    let mut fields = vec![("model", app.config.video_model.clone()), ("prompt", sent), ("size", size.clone()), ("width", width), ("height", height),
        ("num_frames", value("frames")), ("fps", FPS.to_string()), ("num_inference_steps", value("steps")), ("guidance_scale", GUIDANCE.into()),
        ("guidance_scale_2", GUIDANCE.into()), ("flow_shift", SHIFT.into()), ("seed", value("seed"))];
    if !negative.is_empty() { fields.push(("negative_prompt", negative)); }
    if settings.0.get("smooth").and_then(Value::as_bool) == Some(true) {
        fields.extend([("enable_frame_interpolation", "true".to_string()), ("frame_interpolation_exp", "1".into()), ("frame_interpolation_model_path", RIFE.into())]);
    }
    let (content_type, body) = creation::multipart(&fields, &[("input_reference", data.as_slice(), mime.as_str())]);
    // The service answers at once (the video is made afterwards): well under the 100 s of the tunnel.
    let sent = app.http.post(format!("{}/videos", app.config.api_url)).bearer_auth(&app.config.api_key)
        .header("Content-Type", content_type).body(body).timeout(Duration::from_secs(90)).send().await;
    let response = match sent {
        Ok(response) => response,
        Err(error) => { tracing::warn!(error = %error, "video not sent"); return retry(app, id).await; }
    };
    let status = response.status();
    let answer: Value = response.json().await.unwrap_or(Value::Null);
    if status.is_success() {
        let service_id = answer.get("id").and_then(Value::as_str).filter(|id| valid_id(id));
        let Some(service_id) = service_id else {
            tracing::warn!("video service answered without an id");
            return finish(app, id, "failed", "Le serveur de vidéos n’a pas renvoyé de numéro de vidéo.").await;
        };
        let state = answer.get("status").and_then(Value::as_str).unwrap_or("queued");
        sqlx::query("UPDATE videos SET status='running',service_id=$2,service_status=$3,submitted_at=now(),checked_at=now(),attempts=0,\
                     started_at=CASE WHEN $3='in_progress' THEN now() END WHERE id=$1 AND status='waiting'")
            .bind(id).bind(service_id).bind(state).execute(&app.db).await?;
        return Ok(());
    }
    tracing::warn!(status = status.as_u16(), "video refused");
    if status.is_client_error() && status != StatusCode::TOO_MANY_REQUESTS && status != StatusCode::REQUEST_TIMEOUT {
        let detail = service_message(&answer).map(|m| format!(" ({m})")).unwrap_or_default();
        return finish(app, id, "failed", &format!("Le serveur de vidéos a refusé la demande{detail}.")).await;
    }
    retry(app, id).await
}

/// Not sent (service unreachable or busy): the video stays first in the queue, a few times at most.
async fn retry(app: &App, id: Uuid) -> Result<(), Error> {
    let attempts: i32 = sqlx::query_scalar("UPDATE videos SET attempts=attempts+1 WHERE id=$1 RETURNING attempts").bind(id).fetch_one(&app.db).await?;
    if attempts >= MAX_ATTEMPTS { finish(app, id, "failed", "Le serveur de vidéos est injoignable. Réessayez plus tard.").await?; }
    Ok(())
}

/// No news (tunnel or server down): tried again at the next turn, given up after `GIVE_UP`.
async fn unreachable(app: &App, id: Uuid) -> Result<(), Error> {
    let stale: bool = sqlx::query_scalar(&format!("SELECT coalesce(submitted_at < now() - interval '{GIVE_UP}', false) FROM videos WHERE id=$1"))
        .bind(id).fetch_one(&app.db).await?;
    if stale { finish(app, id, "lost", "Le serveur de vidéos ne donne plus de nouvelles de cette vidéo depuis 3 heures. Relancez-la.").await?; }
    Ok(())
}

/// Answers 500 in a row before a video is said lost.
const LOST_AFTER: i32 = 3;
const LOST: &str = "Le serveur de vidéos ne connaît plus cette vidéo (il a sans doute redémarré, ou elle a plus de 24 h). Relancez-la.";

async fn check(app: &App, id: Uuid, service_id: &str) -> Result<(), Error> {
    let url = format!("{}/videos/{}", app.config.api_url, path_part(service_id));
    // The state can take more than 10 s to answer while a video is being made.
    let answer = app.http.get(&url).bearer_auth(&app.config.api_key).timeout(Duration::from_secs(40)).send().await;
    let response = match answer {
        Ok(response) => response,
        Err(_) => return unreachable(app, id).await,
    };
    let status = response.status();
    // Forgotten by the service (restarted, or more than 24 h): its state answers 404, or 500 (three times in a row,
    // so that one passing error does not give up a video still being made).
    if status == StatusCode::NOT_FOUND { return finish(app, id, "lost", LOST).await; }
    if status == StatusCode::INTERNAL_SERVER_ERROR {
        let errors: i32 = sqlx::query_scalar("UPDATE videos SET attempts=attempts+1,checked_at=now() WHERE id=$1 RETURNING attempts").bind(id).fetch_one(&app.db).await?;
        return if errors >= LOST_AFTER { finish(app, id, "lost", LOST).await } else { Ok(()) };
    }
    if !status.is_success() { return unreachable(app, id).await; }
    let Ok(value) = response.json::<Value>().await else { return unreachable(app, id).await };
    match value.get("status").and_then(Value::as_str).unwrap_or("") {
        "completed" => fetch(app, id, &url).await,
        "failed" => {
            let detail = service_message(&value).map(|m| format!(" : {m}")).unwrap_or_default();
            finish(app, id, "failed", &format!("Le serveur de vidéos n’a pas pu faire cette vidéo{detail}")).await
        }
        state @ ("queued" | "in_progress") => {
            // The computation starts when the service first says "in_progress" (it may first wait for videos of other sites).
            sqlx::query("UPDATE videos SET service_status=$2,checked_at=now(),attempts=0,started_at=CASE WHEN $2='in_progress' THEN coalesce(started_at,now()) ELSE started_at END WHERE id=$1")
                .bind(id).bind(state).execute(&app.db).await?;
            Ok(())
        }
        _ => unreachable(app, id).await,
    }
}

/// Downloads the finished MP4 and stores it in the library, with the starting image as thumbnail.
async fn fetch(app: &App, id: Uuid, url: &str) -> Result<(), Error> {
    // Tried again at the next turn when it fails, given up after `GIVE_UP`.
    let response = match app.http.get(format!("{url}/content")).bearer_auth(&app.config.api_key).timeout(Duration::from_secs(180)).send().await {
        Ok(response) => response,
        Err(_) => return unreachable(app, id).await,
    };
    let status = response.status();
    if status == StatusCode::NOT_FOUND { return finish(app, id, "lost", LOST).await; }
    if !status.is_success() { return unreachable(app, id).await; }
    if response.content_length().is_some_and(|length| length > MAX_VIDEO_BYTES as u64) {
        return finish(app, id, "failed", "La vidéo dépasse 30 Mo : elle n’a pas pu être rangée dans la bibliothèque.").await;
    }
    let Ok(data) = response.bytes().await else { return unreachable(app, id).await };
    if data.len() > MAX_VIDEO_BYTES {
        return finish(app, id, "failed", "La vidéo dépasse 30 Mo : elle n’a pas pu être rangée dans la bibliothèque.").await;
    }
    if !is_mp4(&data) {
        tracing::warn!("video service answered something else than an MP4");
        return finish(app, id, "failed", "Le serveur de vidéos n’a pas renvoyé de vidéo MP4.").await;
    }
    store(app, id, &data).await
}

/// File name from the description: its first words.
pub fn video_name(prompt: &str) -> String {
    let words: String = prompt.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(60).collect();
    let words = words.trim_end_matches(['.', ' ']);
    if words.is_empty() { return "video.mp4".into(); }
    attachments::clean_name(Some(&format!("{words}.mp4")), "video.mp4")
}

async fn store(app: &App, id: Uuid, data: &[u8]) -> Result<(), Error> {
    type Made = (Uuid, DbJson<Value>, String, Option<String>, String, String, Option<Uuid>, Vec<u8>, Option<f64>, f64);
    let mut tx = app.db.begin().await?;
    let Some((user, settings, prompt, improved, sent, negative, source, thumbnail, made, waited)): Option<Made> = sqlx::query_as(
        "SELECT user_id,settings,prompt,improved,sent,negative,source_id,source_thumbnail,extract(epoch FROM now()-submitted_at)::float8,\
         extract(epoch FROM now()-created_at)::float8 FROM videos WHERE id=$1 AND status='running' FOR UPDATE").bind(id).fetch_optional(&mut *tx).await? else { return Ok(()); };
    let size = settings.0.get("size").and_then(Value::as_str).unwrap_or("0x0").to_string();
    let (width, height) = size.split_once('x').and_then(|(w, h)| Some((w.parse::<i32>().ok()?, h.parse::<i32>().ok()?))).unwrap_or((1, 1));
    // How it was made, like a created image: the Video tab and the library show it.
    let mut generation = settings.0.clone();
    for (key, value) in [("video", json!(true)), ("prompt", json!(prompt)), ("improved", json!(improved)), ("sent", json!(sent)), ("negative", json!(negative)),
                         ("source", json!(source)), ("seconds", json!(made.map(|s| s.round()))), ("waited", json!(waited.round()))] {
        generation[key] = value;
    }
    let name = video_name(if prompt.is_empty() { improved.as_deref().unwrap_or(&sent) } else { &prompt });
    let sha = hex::encode(Sha256::digest(data));
    let attachment: Uuid = sqlx::query_scalar(
        "INSERT INTO attachments(id,user_id,sha256,kind,name,mime,width,height,size,data,thumbnail,generation) VALUES($1,$2,$3,'video',$4,'video/mp4',$5,$6,$7,$8,$9,$10)
         ON CONFLICT (user_id,sha256) DO UPDATE SET generation=coalesce(attachments.generation,EXCLUDED.generation) RETURNING id")
        .bind(Uuid::new_v4()).bind(user).bind(&sha).bind(&name).bind(width).bind(height).bind(data.len() as i32).bind(data).bind(&thumbnail)
        .bind(DbJson(generation)).fetch_one(&mut *tx).await?;
    sqlx::query("UPDATE videos SET status='ready',service_status='completed',attachment_id=$2,finished_at=now(),checked_at=now(),source_data=''::bytea WHERE id=$1")
        .bind(id).bind(attachment).execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn durations_follow_the_measures() {
        assert_eq!(estimate(81, 40, false, false), 491);
        assert_eq!(estimate(33, 20, false, false), 91);
        assert_eq!(estimate(33, 20, false, true), 94);
        assert_eq!(estimate(81, 40, true, false), 1474);
        for (_, frames) in DURATIONS { assert_eq!(frames % 4, 1, "4k + 1 images"); }
    }
    #[test]
    fn settings_are_checked() {
        let s = settings("480p", "portrait", 2, 20, false, Some(7), Some("avance")).unwrap();
        assert_eq!((s.width, s.height, s.frames, s.seed), (480, 832, 33, 7));
        assert_eq!(s.camera.unwrap().2, "The camera slowly pushes in toward the subject.");
        let s = settings("720p", "paysage", 5, 40, true, None, Some(" ")).unwrap();
        assert_eq!((s.width, s.height, s.frames), (1280, 720, 81));
        assert!(s.camera.is_none() && s.seed <= i32::MAX as u32);
        assert!(settings("1080p", "portrait", 2, 20, false, None, None).is_err());
        assert!(settings("480p", "carré", 2, 20, false, None, None).is_err());
        assert!(settings("480p", "portrait", 4, 20, false, None, None).is_err());
        assert!(settings("480p", "portrait", 2, 25, false, None, None).is_err());
        assert!(settings("480p", "portrait", 2, 20, false, Some(u32::MAX), None).is_err());
        assert!(settings("480p", "portrait", 2, 20, false, None, Some("zoom")).is_err());
    }
    #[test]
    fn the_camera_sentence_follows_the_description() {
        assert_eq!(compose("  A cat\n blinks. ", Some("Static camera, no camera movement.")), "A cat blinks. Static camera, no camera movement.");
        assert_eq!(compose(" ", Some("The camera pans slowly to the left.")), "The camera pans slowly to the left.");
        assert_eq!(compose("A cat blinks.", None), "A cat blinks.");
    }
    #[test]
    fn identifiers_are_kept_exactly_and_escaped_in_paths() {
        let id = "video_bGl0ZWxsbTpjdXN0b21fbGxtX3Byb3ZpZGVyOm9wZW5haTt2aWRlb19pZDp2aWRlb18x+/=";
        assert!(valid_id(id));
        assert!(!valid_id("video_x"));
        assert!(!valid_id("img_bGl0ZWxsbTpjdXN0b20"));
        assert!(!valid_id("video_bGl0ZWxsbTpj dXN0b20"));
        assert_eq!(path_part("video_ab+c/d=="), "video_ab%2Bc%2Fd%3D%3D");
    }
    #[test]
    fn only_mp4_files_are_kept() {
        assert!(is_mp4(b"\x00\x00\x00\x20ftypisom\x00\x00"));
        assert!(!is_mp4(b"{\"error\":\"x\"}"));
        assert!(!is_mp4(b"ftyp"));
    }
    #[test]
    fn names_come_from_the_description() {
        assert_eq!(video_name("un chat  qui\ncligne des yeux."), "un chat qui cligne des yeux.mp4");
        assert_eq!(video_name("  "), "video.mp4");
        assert!(check_text("x <LORA:a:1>", 100, "La description").is_err());
        assert!(check_text(&"é".repeat(MAX_PROMPT + 1), MAX_PROMPT, "La description").is_err());
    }
}
