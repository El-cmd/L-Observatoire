//! Decodes untrusted images in an isolated container and re-encodes them from their pixels
//! only: metadata, trailing data and anything hidden in the original file are dropped.
//! The API stores, displays and sends to Qwen only what this service returns.
use axum::{
    Json, Router,
    body::Bytes,
    extract::{DefaultBodyLimit, RawQuery, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
};
use base64::{Engine, engine::general_purpose::STANDARD};
use image::{
    DynamicImage, ImageEncoder, ImageFormat, ImageReader, Limits, RgbImage, RgbaImage,
    codecs::{jpeg::JpegEncoder, png::PngEncoder},
    imageops::FilterType,
};
use serde_json::json;
use std::{io::Cursor, sync::Arc, time::Duration};
use tokio::sync::Semaphore;

const MAX_INPUT: usize = 12 * 1024 * 1024;
const MAX_PIXELS: u64 = 40_000_000;
const MAX_SIDE: u32 = 2048;
const THUMB_SIDE: u32 = 640;
/// A PNG larger than this once re-encoded is stored as JPEG instead.
const MAX_PNG: usize = 3 * 1024 * 1024;
/// An image whose transparency is kept (`?alpha=1`, a background removed) stays PNG: reduced until it weighs this.
const MAX_ALPHA_PNG: usize = 8 * 1024 * 1024;
/// Below this opacity (a quarter), a pixel is nearly invisible: its colour is laid on white as when flattening,
/// so that Qwen, which gets the colours without the transparency, cannot read anything the user does not see.
const VISIBLE_ALPHA: u8 = 64;

#[derive(Debug, PartialEq)]
struct Clean {
    mime: &'static str,
    width: u32,
    height: u32,
    data: Vec<u8>,
    thumbnail: Vec<u8>,
    /// Some pixel at least is (partly) transparent: only with `keep_alpha`.
    transparent: bool,
}

fn reader(input: &[u8]) -> Result<ImageReader<Cursor<&[u8]>>, String> {
    let mut reader = ImageReader::new(Cursor::new(input))
        .with_guessed_format()
        .map_err(|_| "Fichier illisible.".to_string())?;
    match reader.format() {
        Some(ImageFormat::Png | ImageFormat::Jpeg | ImageFormat::WebP | ImageFormat::Gif) => {}
        _ => return Err("Format d’image non accepté : PNG, JPEG, WebP ou GIF attendu.".into()),
    }
    let mut limits = Limits::default();
    limits.max_image_width = Some(16_384);
    limits.max_image_height = Some(16_384);
    limits.max_alloc = Some(512 * 1024 * 1024);
    reader.limits(limits);
    Ok(reader)
}

/// Transparent pixels are laid on white: Qwen and JPEG both get a plain RGB image.
fn flatten(image: DynamicImage) -> RgbImage {
    if !image.color().has_alpha() {
        return image.into_rgb8();
    }
    let rgba = image.into_rgba8();
    RgbImage::from_fn(rgba.width(), rgba.height(), |x, y| {
        let [r, g, b, a] = rgba.get_pixel(x, y).0;
        let blend = |c: u8| ((c as u16 * a as u16 + 255 * (255 - a as u16)) / 255) as u8;
        image::Rgb([blend(r), blend(g), blend(b)])
    })
}

fn jpeg(image: &RgbImage, quality: u8) -> Result<Vec<u8>, String> {
    let mut out = Vec::new();
    JpegEncoder::new_with_quality(&mut out, quality)
        .write_image(image.as_raw(), image.width(), image.height(), image::ExtendedColorType::Rgb8)
        .map_err(|_| "Encodage impossible.".to_string())?;
    Ok(out)
}

fn png(image: &RgbImage) -> Result<Vec<u8>, String> {
    let mut out = Vec::new();
    PngEncoder::new(&mut out)
        .write_image(image.as_raw(), image.width(), image.height(), image::ExtendedColorType::Rgb8)
        .map_err(|_| "Encodage impossible.".to_string())?;
    Ok(out)
}

fn png_rgba(image: &RgbaImage) -> Result<Vec<u8>, String> {
    let mut out = Vec::new();
    PngEncoder::new(&mut out)
        .write_image(image.as_raw(), image.width(), image.height(), image::ExtendedColorType::Rgba8)
        .map_err(|_| "Encodage impossible.".to_string())?;
    Ok(out)
}

/// Transparency kept, nearly invisible pixels laid on white (see `VISIBLE_ALPHA`).
fn transparent(image: DynamicImage) -> RgbaImage {
    let mut rgba = image.into_rgba8();
    for pixel in rgba.pixels_mut() {
        let [r, g, b, a] = pixel.0;
        if a < VISIBLE_ALPHA {
            let blend = |c: u8| ((c as u16 * a as u16 + 255 * (255 - a as u16)) / 255) as u8;
            pixel.0 = [blend(r), blend(g), blend(b), a];
        }
    }
    rgba
}

#[cfg(test)]
fn sanitize(input: &[u8]) -> Result<Clean, String> {
    sanitize_with(input, false)
}

/// `keep_alpha`: a transparent image stays transparent (PNG); otherwise it is laid on white.
fn sanitize_with(input: &[u8], keep_alpha: bool) -> Result<Clean, String> {
    if input.is_empty() || input.len() > MAX_INPUT {
        return Err("Image vide ou trop lourde (12 Mo au maximum).".into());
    }
    let (width, height) = reader(input)?
        .into_dimensions()
        .map_err(|_| "Image illisible.".to_string())?;
    if width == 0 || height == 0 || width as u64 * height as u64 > MAX_PIXELS {
        return Err("Image trop grande (40 millions de pixels au maximum).".into());
    }
    let source_png = matches!(reader(input)?.format(), Some(ImageFormat::Png));
    // GIF: only the first frame is decoded.
    let mut image = reader(input)?
        .decode()
        .map_err(|_| "Image illisible ou corrompue.".to_string())?;
    if image.width().max(image.height()) > MAX_SIDE {
        image = image.resize(MAX_SIDE, MAX_SIDE, FilterType::Triangle);
    }
    let thumbnail = flatten(image.thumbnail(THUMB_SIDE, THUMB_SIDE));
    if keep_alpha && image.color().has_alpha() {
        let mut rgba = transparent(image);
        let see_through = rgba.pixels().any(|pixel| pixel.0[3] < 255);
        loop {
            let data = png_rgba(&rgba)?;
            if data.len() <= MAX_ALPHA_PNG || rgba.width().max(rgba.height()) <= 512 {
                return Ok(Clean { mime: "image/png", width: rgba.width(), height: rgba.height(), data, thumbnail: jpeg(&thumbnail, 78)?, transparent: see_through });
            }
            let (width, height) = ((rgba.width() * 3 / 4).max(1), (rgba.height() * 3 / 4).max(1));
            rgba = image::imageops::resize(&rgba, width, height, FilterType::Triangle);
        }
    }
    let rgb = flatten(image);
    // Screenshots stay PNG so that small text remains sharp; photos and heavy PNGs become JPEG.
    let (mime, data) = match source_png.then(|| png(&rgb)).transpose()? {
        Some(data) if data.len() <= MAX_PNG => ("image/png", data),
        _ => ("image/jpeg", jpeg(&rgb, 88)?),
    };
    Ok(Clean { mime, width: rgb.width(), height: rgb.height(), data, thumbnail: jpeg(&thumbnail, 78)?, transparent: false })
}

async fn handle(State(work): State<Arc<Semaphore>>, RawQuery(query): RawQuery, body: Bytes) -> Response {
    let keep_alpha = query.as_deref() == Some("alpha=1");
    let Ok(_permit) = work.acquire().await else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    let task = tokio::task::spawn_blocking(move || sanitize_with(&body, keep_alpha));
    match tokio::time::timeout(Duration::from_secs(20), task).await {
        Ok(Ok(Ok(clean))) => Json(json!({
            "mime": clean.mime, "width": clean.width, "height": clean.height,
            "data": STANDARD.encode(&clean.data), "thumbnail": STANDARD.encode(&clean.thumbnail), "transparent": clean.transparent,
        }))
        .into_response(),
        Ok(Ok(Err(message))) => (StatusCode::UNPROCESSABLE_ENTITY, Json(json!({"error": message}))).into_response(),
        Ok(Err(_)) => (StatusCode::UNPROCESSABLE_ENTITY, Json(json!({"error": "Image illisible ou corrompue."}))).into_response(),
        Err(_) => {
            // A decoder stuck on a crafted file cannot be cancelled: restart the container.
            eprintln!("image-guard: decoding exceeded 20 s, exiting");
            std::process::exit(70);
        }
    }
}

fn healthcheck() -> Result<(), String> {
    use std::io::{Read, Write};
    let mut stream = std::net::TcpStream::connect("127.0.0.1:8080").map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(Duration::from_secs(3))).map_err(|e| e.to_string())?;
    stream.write_all(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n").map_err(|e| e.to_string())?;
    let mut answer = String::new();
    stream.read_to_string(&mut answer).map_err(|e| e.to_string())?;
    answer.starts_with("HTTP/1.0 200").then_some(()).or_else(|| answer.starts_with("HTTP/1.1 200").then_some(())).ok_or(answer)
}

#[tokio::main]
async fn main() {
    if std::env::args().nth(1).as_deref() == Some("healthcheck") {
        if let Err(error) = healthcheck() {
            eprintln!("{error}");
            std::process::exit(1);
        }
        return;
    }
    let router = Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/sanitize", post(handle))
        .layer(DefaultBodyLimit::max(MAX_INPUT))
        .with_state(Arc::new(Semaphore::new(1)));
    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await.expect("bind 8080");
    axum::serve(listener, router)
        .with_graceful_shutdown(async {
            let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).expect("signal handler");
            tokio::select! { _ = tokio::signal::ctrl_c() => {}, _ = terminate.recv() => {} }
        })
        .await
        .expect("serve");
}

#[cfg(test)]
mod tests {
    use super::*;
    fn encoded(format: ImageFormat, width: u32, height: u32) -> Vec<u8> {
        let image = DynamicImage::ImageRgba8(image::RgbaImage::from_fn(width, height, |x, y| image::Rgba([x as u8, y as u8, 90, if x < 4 { 0 } else { 255 }])));
        let mut out = Cursor::new(Vec::new());
        match format {
            ImageFormat::Jpeg => DynamicImage::ImageRgb8(image.to_rgb8()).write_to(&mut out, format).unwrap(),
            _ => image.write_to(&mut out, format).unwrap(),
        }
        out.into_inner()
    }
    #[test]
    fn reencodes_screenshots_as_png_and_photos_as_jpeg() {
        let clean = sanitize(&encoded(ImageFormat::Png, 40, 30)).unwrap();
        assert_eq!((clean.mime, clean.width, clean.height), ("image/png", 40, 30));
        assert!(clean.data.starts_with(b"\x89PNG") && clean.thumbnail.starts_with(&[0xFF, 0xD8]));
        let photo = sanitize(&encoded(ImageFormat::Jpeg, 40, 30)).unwrap();
        assert_eq!(photo.mime, "image/jpeg");
        assert_eq!(sanitize(&encoded(ImageFormat::Gif, 8, 8)).unwrap().mime, "image/jpeg");
    }
    #[test]
    fn drops_trailing_data_and_caps_size() {
        let mut input = encoded(ImageFormat::Png, 3000, 10);
        input.extend_from_slice(b"<script>alert(1)</script>");
        let clean = sanitize(&input).unwrap();
        assert_eq!((clean.width, clean.height), (2048, 7));
        assert!(!clean.data.windows(8).any(|w| w == b"<script>"));
    }
    #[test]
    fn keeps_transparency_only_when_asked() {
        // Columns 0-3 transparent; one nearly invisible pixel hides a dark colour.
        let mut image = image::RgbaImage::from_fn(40, 30, |x, _| image::Rgba([10, 20, 30, if x < 4 { 0 } else { 255 }]));
        image.put_pixel(10, 10, image::Rgba([0, 0, 0, 20]));
        let mut input = Cursor::new(Vec::new());
        DynamicImage::ImageRgba8(image).write_to(&mut input, ImageFormat::Png).unwrap();
        let input = input.into_inner();
        let kept = sanitize_with(&input, true).unwrap();
        assert_eq!((kept.mime, kept.width, kept.height, kept.transparent), ("image/png", 40, 30, true));
        let decoded = image::load_from_memory(&kept.data).unwrap().into_rgba8();
        assert_eq!(decoded.get_pixel(0, 0).0[3], 0);
        assert_eq!(decoded.get_pixel(20, 5).0, [10, 20, 30, 255]);
        let hidden = decoded.get_pixel(10, 10).0;
        assert!(hidden[0] > 230 && hidden[3] == 20, "{hidden:?}");
        assert!(kept.thumbnail.starts_with(&[0xFF, 0xD8]));
        // Without asking: laid on white, as before.
        let flat = image::load_from_memory(&sanitize_with(&input, false).unwrap().data).unwrap();
        assert!(!flat.color().has_alpha());
        // A transparency channel without any transparent pixel: not transparent.
        let mut opaque = Cursor::new(Vec::new());
        DynamicImage::ImageRgba8(image::RgbaImage::from_pixel(20, 20, image::Rgba([1, 2, 3, 255]))).write_to(&mut opaque, ImageFormat::Png).unwrap();
        assert!(!sanitize_with(&opaque.into_inner(), true).unwrap().transparent);
        // An image without transparency is unchanged by the option.
        assert_eq!(sanitize_with(&encoded(ImageFormat::Jpeg, 40, 30), true).unwrap().mime, "image/jpeg");
    }
    #[test]
    fn rejects_non_images_and_pixel_bombs() {
        assert!(sanitize(b"%PDF-1.7 not an image").is_err());
        assert!(sanitize(b"<svg xmlns='http://www.w3.org/2000/svg'/>").is_err());
        assert!(sanitize(&[]).is_err());
        // A valid PNG header announcing 20000 x 20000 pixels, without the pixels.
        let mut bomb = encoded(ImageFormat::Png, 1, 1);
        bomb[16..24].copy_from_slice(&[0, 0, 0x4E, 0x20, 0, 0, 0x4E, 0x20]);
        assert!(sanitize(&bomb).is_err());
    }
}
