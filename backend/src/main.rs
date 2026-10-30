mod auth;
mod chat;

use anyhow::{Context, Result};
use axum::{
    Json, Router,
    extract::{DefaultBodyLimit, State},
    http::{HeaderMap, HeaderValue, StatusCode, header},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post, put},
};
use serde_json::json;
use sqlx::{PgPool, postgres::PgPoolOptions};
use std::{env, sync::Arc, time::Duration};
use tokio::sync::Semaphore;
use tower_http::trace::TraceLayer;

#[derive(Clone)]
pub struct App {
    pub db: PgPool,
    pub http: reqwest::Client,
    pub config: Arc<Config>,
    pub generations: Arc<Semaphore>,
    pub password_work: Arc<Semaphore>,
    pub dummy_hash: Arc<String>,
    pub shutdown: tokio::sync::watch::Receiver<bool>,
}

pub struct Config {
    pub api_url: String,
    pub api_key: String,
    pub model: String,
    pub origin: String,
    pub secure_cookie: bool,
}

#[derive(Debug)]
pub struct Error(pub StatusCode, pub String);
impl Error {
    pub fn bad(message: &str) -> Self {
        Self(StatusCode::BAD_REQUEST, message.into())
    }
    pub fn unauthorized() -> Self {
        Self(
            StatusCode::UNAUTHORIZED,
            "Connecte-toi pour continuer.".into(),
        )
    }
    pub fn conflict() -> Self {
        Self(StatusCode::CONFLICT, "La conversation a changé ou une réponse est déjà en cours. Recharge-la avant de réessayer.".into())
    }
    pub fn missing() -> Self {
        Self(StatusCode::NOT_FOUND, "Conversation introuvable.".into())
    }
}
impl IntoResponse for Error {
    fn into_response(self) -> Response {
        (self.0, Json(json!({"error": self.1}))).into_response()
    }
}
impl From<sqlx::Error> for Error {
    fn from(error: sqlx::Error) -> Self {
        tracing::error!(error = %error, "database operation failed");
        Self(
            StatusCode::SERVICE_UNAVAILABLE,
            "La base de données est temporairement indisponible.".into(),
        )
    }
}

pub async fn session(app: &App, headers: &HeaderMap, write: bool) -> Result<auth::Session, Error> {
    let token =
        auth::cookie_token(headers, app.config.secure_cookie).ok_or_else(Error::unauthorized)?;
    let found = sqlx::query_as::<_, auth::Session>(
        "SELECT s.token_hash,s.csrf_token,u.id AS user_id,u.username,u.is_admin FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=$1 AND s.expires_at>now()"
    ).bind(auth::digest(&token)).fetch_optional(&app.db).await?.ok_or_else(Error::unauthorized)?;
    if write {
        auth::verify_origin(app, headers)?;
        use subtle::ConstantTimeEq;
        let supplied = headers
            .get("x-csrf-token")
            .and_then(|h| h.to_str().ok())
            .unwrap_or("");
        if !bool::from(found.csrf_token.as_bytes().ct_eq(supplied.as_bytes())) {
            return Err(Error(
                StatusCode::FORBIDDEN,
                "Jeton de sécurité invalide. Recharge la page.".into(),
            ));
        }
    }
    Ok(found)
}

async fn security(request: axum::extract::Request, next: Next) -> Response {
    let mut response = next.run(request).await;
    let headers = response.headers_mut();
    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    headers.insert(
        "x-content-type-options",
        HeaderValue::from_static("nosniff"),
    );
    headers.insert("referrer-policy", HeaderValue::from_static("no-referrer"));
    response
}

async fn health(State(app): State<App>) -> Result<Json<serde_json::Value>, Error> {
    sqlx::query("SELECT 1").execute(&app.db).await?;
    Ok(Json(json!({"ok":true})))
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            env::var("RUST_LOG").unwrap_or_else(|_| "observatoire=info,tower_http=info".into()),
        )
        .init();
    if env::args().nth(1).as_deref() == Some("healthcheck") {
        reqwest::Client::new()
            .get("http://127.0.0.1:8080/api/health")
            .timeout(Duration::from_secs(3))
            .send()
            .await?
            .error_for_status()?;
        return Ok(());
    }
    let database_url = env::var("DATABASE_URL").context("DATABASE_URL is required")?;
    let db = PgPoolOptions::new()
        .max_connections(12)
        .acquire_timeout(Duration::from_secs(5))
        .connect(&database_url)
        .await
        .context("could not connect to PostgreSQL")?;
    sqlx::migrate!()
        .run(&db)
        .await
        .context("database migration failed")?;
    if let Some(command) = env::args().nth(1) {
        return auth::admin_command(&db, &command).await;
    }
    auth::bootstrap(&db).await?;
    // This deployment runs one API instance. Recover leases left by an API restart.
    sqlx::query("UPDATE conversations SET active_generation=NULL,generation_started_at=NULL WHERE active_generation IS NOT NULL").execute(&db).await?;
    let origin = env::var("PUBLIC_ORIGIN")
        .unwrap_or_else(|_| "http://localhost:8080".into())
        .trim_end_matches('/')
        .to_string();
    let parsed = reqwest::Url::parse(&origin).context("invalid PUBLIC_ORIGIN")?;
    anyhow::ensure!(
        matches!(parsed.scheme(), "http" | "https")
            && parsed.host_str().is_some()
            && parsed.path() == "/"
            && parsed.query().is_none()
            && parsed.fragment().is_none()
            && parsed.username().is_empty(),
        "PUBLIC_ORIGIN must be an HTTP(S) origin without path or credentials"
    );
    let config = Config {
        api_url: env::var("QWEN_BASE_URL")
            .unwrap_or_default()
            .trim_end_matches('/')
            .to_string(),
        api_key: env::var("QWEN_API_KEY").unwrap_or_default(),
        model: env::var("QWEN_MODEL").unwrap_or_else(|_| "qwen3.8-27b-abliterated".into()),
        secure_cookie: parsed.scheme() == "https",
        origin,
    };
    if !config.api_url.is_empty() {
        let url = reqwest::Url::parse(&config.api_url).context("invalid QWEN_BASE_URL")?;
        anyhow::ensure!(
            matches!(url.scheme(), "http" | "https") && url.host_str().is_some(),
            "QWEN_BASE_URL must be HTTP(S)"
        );
    }
    let (shutdown_tx, shutdown_rx) = tokio::sync::watch::channel(false);
    let app = App {
        shutdown: shutdown_rx,
        db: db.clone(),
        http: reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(190))
            .build()?,
        config: Arc::new(config),
        generations: Arc::new(Semaphore::new(4)),
        password_work: Arc::new(Semaphore::new(4)),
        dummy_hash: Arc::new(auth::hash_password("dummy-not-a-real-user-password".into()).await?),
    };
    let cleanup = db.clone();
    tokio::spawn(async move {
        let mut timer = tokio::time::interval(Duration::from_secs(3600));
        loop {
            timer.tick().await;
            let _ = sqlx::query("DELETE FROM sessions WHERE expires_at<now()")
                .execute(&cleanup)
                .await;
            let _ = sqlx::query(
                "DELETE FROM login_limits WHERE window_started_at<now()-interval '1 day'",
            )
            .execute(&cleanup)
            .await;
        }
    });
    let router = Router::new()
        .route("/api/health", get(health))
        .route("/api/auth/login", post(auth::login))
        .route("/api/auth/me", get(auth::me))
        .route("/api/auth/logout", post(auth::logout))
        .route("/api/auth/password", put(auth::change_password))
        .route("/api/conversations", get(chat::list).post(chat::create))
        .route("/api/conversations/import", post(chat::import))
        .route(
            "/api/conversations/{id}",
            get(chat::get_one).put(chat::update).delete(chat::delete),
        )
        .route("/api/conversations/{id}/generate", post(chat::generate))
        .fallback(|| async { Error(StatusCode::NOT_FOUND, "Route introuvable.".into()) })
        .layer(DefaultBodyLimit::max(512 * 1024))
        .layer(middleware::from_fn(security))
        .layer(TraceLayer::new_for_http())
        .with_state(app);
    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await?;
    tracing::info!("API ready on port 8080");
    axum::serve(listener, router)
        .with_graceful_shutdown(async move {
            #[cfg(unix)]
            {
                let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).expect("signal handler");
                tokio::select! { _ = tokio::signal::ctrl_c() => {}, _ = terminate.recv() => {} }
            }
            #[cfg(not(unix))]
            { let _ = tokio::signal::ctrl_c().await; }
            let _ = shutdown_tx.send(true);
        })
        .await?;
    db.close().await;
    Ok(())
}
