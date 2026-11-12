"""Démarrage sur le réseau Docker interne du labo (port 8080, jamais publié sur la machine)."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8080, workers=1, access_log=False, log_level="warning", timeout_keep_alive=5)
