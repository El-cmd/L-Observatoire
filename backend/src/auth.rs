use crate::{App, Error, session};
use anyhow::{Context, Result};
use argon2::{
    Argon2, PasswordHash, PasswordHasher, PasswordVerifier,
    password_hash::{SaltString, rand_core::OsRng},
};
use axum::{
    Json,
    extract::State,
    http::{HeaderMap, HeaderValue, StatusCode, header},
    response::{IntoResponse, Response},
};
use rand::RngCore;
use serde::Deserialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use sqlx::{FromRow, PgPool};
use std::{env, io::Read};
use uuid::Uuid;

#[derive(FromRow)]
pub struct Session {
    pub token_hash: String,
    pub csrf_token: String,
    pub user_id: Uuid,
    pub username: String,
    pub is_admin: bool,
}

#[derive(FromRow)]
struct User {
    id: Uuid,
    username: String,
    password_hash: String,
    is_admin: bool,
}

pub fn digest(value: &str) -> String {
    hex::encode(Sha256::digest(value.as_bytes()))
}
pub fn random_token() -> String {
    let mut bytes = [0u8; 32];
    rand::rngs::OsRng.fill_bytes(&mut bytes);
    hex::encode(bytes)
}

pub fn normalize_username(value: &str) -> Result<String> {
    let value = value.trim().to_ascii_lowercase();
    anyhow::ensure!(
        (3..=64).contains(&value.len())
            && value
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || "._-@".contains(c)),
        "Identifiant : 3 à 64 caractères, lettres, chiffres, point, tiret, @ ou underscore."
    );
    Ok(value)
}

pub fn validate_password(value: &str) -> Result<()> {
    anyhow::ensure!(
        (12..=256).contains(&value.chars().count()),
        "Le mot de passe doit contenir entre 12 et 256 caractères."
    );
    Ok(())
}

pub async fn hash_password(password: String) -> Result<String> {
    tokio::task::spawn_blocking(move || {
        let salt = SaltString::generate(&mut OsRng);
        Argon2::default()
            .hash_password(password.as_bytes(), &salt)
            .map(|h| h.to_string())
            .map_err(|_| anyhow::anyhow!("password hashing failed"))
    })
    .await?
}
async fn verify(password: String, hash: String) -> bool {
    tokio::task::spawn_blocking(move || {
        PasswordHash::new(&hash)
            .map(|h| {
                Argon2::default()
                    .verify_password(password.as_bytes(), &h)
                    .is_ok()
            })
            .unwrap_or(false)
    })
    .await
    .unwrap_or(false)
}

pub fn verify_origin(app: &App, headers: &HeaderMap) -> Result<(), Error> {
    let origin = headers.get(header::ORIGIN).and_then(|h| h.to_str().ok());
    if origin != Some(app.config.origin.as_str()) {
        return Err(Error(
            StatusCode::FORBIDDEN,
            "Origine non autorisée.".into(),
        ));
    }
    Ok(())
}
pub fn cookie_token(headers: &HeaderMap, secure: bool) -> Option<String> {
    let name = if secure {
        "__Host-observatoire_session="
    } else {
        "observatoire_session="
    };
    headers
        .get(header::COOKIE)?
        .to_str()
        .ok()?
        .split(';')
        .find_map(|part| {
            let token = part.trim().strip_prefix(name)?;
            (token.len() == 64 && token.bytes().all(|b| b.is_ascii_hexdigit()))
                .then(|| token.to_string())
        })
}
fn cookie(app: &App, token: &str, expire: bool) -> HeaderValue {
    cookie_header(app.config.secure_cookie, token, expire)
}
fn cookie_header(https: bool, token: &str, expire: bool) -> HeaderValue {
    let (name, secure) = if https {
        ("__Host-observatoire_session", "; Secure")
    } else {
        ("observatoire_session", "")
    };
    HeaderValue::from_str(&format!(
        "{name}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}{secure}",
        if expire { 0 } else { 86400 }
    ))
    .expect("hex cookie is a valid header")
}

#[derive(Deserialize)]
pub struct Login {
    username: String,
    password: String,
}

async fn attempt(db: &PgPool, key: &str, limit: i32) -> Result<(), Error> {
    let count: i32 = sqlx::query_scalar("INSERT INTO login_limits(key_hash,attempts) VALUES($1,1) ON CONFLICT(key_hash) DO UPDATE SET attempts=CASE WHEN login_limits.window_started_at < now()-interval '15 minutes' THEN 1 ELSE login_limits.attempts+1 END, window_started_at=CASE WHEN login_limits.window_started_at < now()-interval '15 minutes' THEN now() ELSE login_limits.window_started_at END RETURNING attempts")
        .bind(digest(key)).fetch_one(db).await?;
    if count > limit {
        return Err(Error(
            StatusCode::TOO_MANY_REQUESTS,
            "Trop de tentatives. Réessaie dans 15 minutes.".into(),
        ));
    }
    Ok(())
}

pub async fn login(
    State(app): State<App>,
    headers: HeaderMap,
    Json(input): Json<Login>,
) -> Result<Response, Error> {
    verify_origin(&app, &headers)?;
    if input.username.len() > 256 || input.password.len() > 1024 {
        return Err(Error::bad("Identifiants invalides."));
    }
    let username = input.username.trim().to_ascii_lowercase();
    let ip = headers
        .get("x-real-ip")
        .and_then(|h| h.to_str().ok())
        .unwrap_or("unknown");
    attempt(&app.db, &format!("ip:{ip}"), 40).await?;
    attempt(&app.db, &format!("user:{username}"), 8).await?;
    let _permit = app.password_work.clone().try_acquire_owned().map_err(|_| {
        Error(
            StatusCode::TOO_MANY_REQUESTS,
            "Réessaie dans quelques secondes.".into(),
        )
    })?;
    let user = sqlx::query_as::<_, User>(
        "SELECT id,username,password_hash,is_admin FROM users WHERE username=$1",
    )
    .bind(&username)
    .fetch_optional(&app.db)
    .await?;
    let hash = user
        .as_ref()
        .map(|u| u.password_hash.clone())
        .unwrap_or_else(|| app.dummy_hash.as_ref().clone());
    let valid = verify(input.password, hash).await;
    let user = user.filter(|_| valid).ok_or_else(|| {
        Error(
            StatusCode::UNAUTHORIZED,
            "Identifiant ou mot de passe incorrect.".into(),
        )
    })?;
    let mut tx = app.db.begin().await?;
    // Serialize session creation with password changes. A password verified before
    // a concurrent reset must not create a new session after the reset commits.
    let current_hash: Option<String> = sqlx::query_scalar("SELECT password_hash FROM users WHERE id=$1 FOR UPDATE")
        .bind(user.id).fetch_optional(&mut *tx).await?;
    if current_hash.as_deref() != Some(user.password_hash.as_str()) {
        return Err(Error(StatusCode::UNAUTHORIZED, "Identifiant ou mot de passe incorrect.".into()));
    }
    if let Some(token) = cookie_token(&headers, app.config.secure_cookie) {
        sqlx::query("DELETE FROM sessions WHERE token_hash=$1")
            .bind(digest(&token))
            .execute(&mut *tx)
            .await?;
    }
    // Retain at most ten sessions per account, removing oldest sessions first.
    sqlx::query("DELETE FROM sessions WHERE user_id=$1 AND token_hash IN (SELECT token_hash FROM sessions WHERE user_id=$1 ORDER BY created_at DESC OFFSET 9)").bind(user.id).execute(&mut *tx).await?;
    let token = random_token();
    let csrf = random_token();
    sqlx::query("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES($1,$2,$3,now()+interval '24 hours')").bind(digest(&token)).bind(user.id).bind(&csrf).execute(&mut *tx).await?;
    sqlx::query("DELETE FROM login_limits WHERE key_hash=$1")
        .bind(digest(&format!("user:{username}")))
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    let mut response=Json(json!({"user":{"id":user.id,"username":user.username,"is_admin":user.is_admin},"csrf_token":csrf,"configured":!app.config.api_key.is_empty()&&!app.config.api_url.is_empty()})).into_response();
    response
        .headers_mut()
        .insert(header::SET_COOKIE, cookie(&app, &token, false));
    Ok(response)
}

pub async fn me(
    State(app): State<App>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, Error> {
    let user = session(&app, &headers, false).await?;
    Ok(Json(
        json!({"user":{"id":user.user_id,"username":user.username,"is_admin":user.is_admin},"csrf_token":user.csrf_token,"configured":!app.config.api_key.is_empty()&&!app.config.api_url.is_empty()}),
    ))
}

pub async fn logout(State(app): State<App>, headers: HeaderMap) -> Result<Response, Error> {
    let user = session(&app, &headers, true).await?;
    sqlx::query("DELETE FROM sessions WHERE token_hash=$1")
        .bind(user.token_hash)
        .execute(&app.db)
        .await?;
    let mut response = StatusCode::NO_CONTENT.into_response();
    response
        .headers_mut()
        .insert(header::SET_COOKIE, cookie(&app, "", true));
    Ok(response)
}

#[derive(Deserialize)]
pub struct PasswordChange {
    current_password: String,
    new_password: String,
}
pub async fn change_password(
    State(app): State<App>,
    headers: HeaderMap,
    Json(input): Json<PasswordChange>,
) -> Result<Response, Error> {
    let user = session(&app, &headers, true).await?;
    validate_password(&input.new_password).map_err(|e| Error::bad(&e.to_string()))?;
    if input.current_password.len() > 1024 {
        return Err(Error::bad("Mot de passe invalide."));
    }
    attempt(&app.db, &format!("password:{}", user.user_id), 8).await?;
    let _permit = app.password_work.clone().try_acquire_owned().map_err(|_| {
        Error(
            StatusCode::TOO_MANY_REQUESTS,
            "Réessaie dans quelques secondes.".into(),
        )
    })?;
    let old_hash: String = sqlx::query_scalar("SELECT password_hash FROM users WHERE id=$1")
        .bind(user.user_id)
        .fetch_one(&app.db)
        .await?;
    if !verify(input.current_password, old_hash.clone()).await {
        return Err(Error(
            StatusCode::UNAUTHORIZED,
            "Mot de passe actuel incorrect.".into(),
        ));
    }
    let hash = hash_password(input.new_password).await.map_err(|_| {
        Error(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Impossible de modifier le mot de passe.".into(),
        )
    })?;
    let mut tx = app.db.begin().await?;
    let changed = sqlx::query("UPDATE users SET password_hash=$1 WHERE id=$2 AND password_hash=$3")
        .bind(hash)
        .bind(user.user_id)
        .bind(old_hash)
        .execute(&mut *tx)
        .await?;
    if changed.rows_affected() != 1 {
        return Err(Error::conflict());
    }
    sqlx::query("DELETE FROM sessions WHERE user_id=$1")
        .bind(user.user_id)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    let mut response = StatusCode::NO_CONTENT.into_response();
    response
        .headers_mut()
        .insert(header::SET_COOKIE, cookie(&app, "", true));
    Ok(response)
}

pub async fn bootstrap(db: &PgPool) -> Result<()> {
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM users")
        .fetch_one(db)
        .await?;
    if count != 0 {
        return Ok(());
    }
    let username = env::var("BOOTSTRAP_USERNAME").unwrap_or_default();
    let password = env::var("BOOTSTRAP_PASSWORD").unwrap_or_default();
    if username.is_empty() || password.is_empty() {
        tracing::warn!("No account exists. Run make user to create the first account.");
        return Ok(());
    }
    let username = normalize_username(&username)?;
    validate_password(&password)?;
    let hash = hash_password(password).await?;
    sqlx::query("INSERT INTO users(id,username,password_hash,is_admin) SELECT $1,$2,$3,true WHERE NOT EXISTS(SELECT 1 FROM users) ON CONFLICT(username) DO NOTHING").bind(Uuid::new_v4()).bind(username).bind(hash).execute(db).await?;
    tracing::info!("Initial administrator account created");
    Ok(())
}

pub async fn admin_command(db: &PgPool, command: &str) -> Result<()> {
    anyhow::ensure!(
        matches!(command, "create-user" | "reset-password"),
        "Unknown command"
    );
    let mut input = String::new();
    std::io::stdin().take(4096).read_to_string(&mut input)?;
    #[derive(Deserialize)]
    struct Credentials {
        username: String,
        password: String,
    }
    let input: Credentials =
        serde_json::from_str(&input).context("Expected JSON credentials on stdin")?;
    let username = normalize_username(&input.username)?;
    validate_password(&input.password)?;
    let hash = hash_password(input.password).await?;
    let mut tx = db.begin().await?;
    if command == "create-user" {
        let first: bool = sqlx::query_scalar("SELECT NOT EXISTS(SELECT 1 FROM users)")
            .fetch_one(&mut *tx)
            .await?;
        sqlx::query("INSERT INTO users(id,username,password_hash,is_admin) VALUES($1,$2,$3,$4)")
            .bind(Uuid::new_v4())
            .bind(username)
            .bind(hash)
            .bind(first)
            .execute(&mut *tx)
            .await
            .context("Account creation failed (username may already exist)")?;
    } else {
        let id: Option<Uuid> =
            sqlx::query_scalar("UPDATE users SET password_hash=$1 WHERE username=$2 RETURNING id")
                .bind(hash)
                .bind(username)
                .fetch_optional(&mut *tx)
                .await?;
        let id = id.context("Account not found")?;
        sqlx::query("DELETE FROM sessions WHERE user_id=$1")
            .bind(id)
            .execute(&mut *tx)
            .await?;
    }
    tx.commit().await?;
    println!("Account updated successfully. Existing sessions are revoked after a password reset.");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn secure_cookie_shape() {
        let value = cookie_header(true, &random_token(), false);
        let value = value.to_str().unwrap();
        assert!(value.starts_with("__Host-observatoire_session="));
        assert!(value.contains("; Secure"));
        assert!(value.contains("; HttpOnly"));
        assert!(value.contains("; SameSite=Lax"));
        assert!(!value.contains("Domain="));
        assert!(cookie_header(true, "", true).to_str().unwrap().contains("Max-Age=0"));
    }
    #[test]
    fn credentials_policy() {
        assert_eq!(
            normalize_username(" Alice.Example ").unwrap(),
            "alice.example"
        );
        assert!(normalize_username("a").is_err());
        assert!(normalize_username("alice\nadmin").is_err());
        assert!(validate_password("short").is_err());
        assert!(validate_password("a long passphrase 2026").is_ok());
        assert_eq!(random_token().len(), 64);
    }
    #[tokio::test]
    async fn hashes_are_salted_and_verifiable() {
        let a = hash_password("long-test-password".into()).await.unwrap();
        let b = hash_password("long-test-password".into()).await.unwrap();
        assert_ne!(a, b);
        assert!(a.starts_with("$argon2id$"));
        assert!(verify("long-test-password".into(), a.clone()).await);
        assert!(!verify("wrong-password".into(), a).await);
    }
}
