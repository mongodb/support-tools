import logging
import os
import sys

from flask import (
    Flask,
    make_response,
    render_template,
    request,
    send_from_directory,
)

from blueprints.live import bp as live_bp
from blueprints.logs import bp as logs_bp
from lib.app_config import (
    DEVELOPER_CREDITS,
    APP_VERSION,
    HOST,
    LOG_STORE_DIR,
    LOG_STORE_MAX_AGE_HOURS,
    MAX_FILE_SIZE,
    PORT,
    get_app_info,
    session_store,
    setup_logging,
    validate_config,
)
from lib.log_store import LogStore
from lib.log_store_registry import log_store_registry
from lib.session_support import SESSION_COOKIE_NAME
from lib.snapshot_store import cleanup_old_snapshots

try:
    validate_config()
except (PermissionError, ValueError) as e:
    print(f"Configuration error: {e}")
    exit(1)

logger = setup_logging()

if getattr(sys, "frozen", False):
    _base_path = sys._MEIPASS
else:
    _base_path = os.path.dirname(os.path.abspath(__file__))


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(_base_path, "templates"),
        static_folder=os.path.join(_base_path, "images"),
        static_url_path="/images",
    )
    app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

    @app.route("/static/js/<path:filename>")
    def mi_static_js(filename):
        return send_from_directory(
            os.path.join(_base_path, "static", "js"), filename
        )

    @app.after_request
    def add_security_headers(response):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.plot.ly; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' blob:;"
        )
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

    @app.context_processor
    def inject_app_version():
        return dict(app_version=APP_VERSION, developer_credits=DEVELOPER_CREDITS)

    @app.errorhandler(413)
    def too_large(e):
        max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
        return (
            render_template(
                "error.html",
                error_title="File Too Large",
                error_message=(
                    f"File size exceeds maximum allowed size ({max_size_mb:.1f} MB)."
                ),
            ),
            413,
        )

    @app.route("/")
    def hub():
        return render_template("hub.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if session_id:
            session_store.delete_session(session_id)
        log_store_registry.cleanup_expired()
        cleanup_old_snapshots(LOG_STORE_DIR, LOG_STORE_MAX_AGE_HOURS)
        response = make_response("", 200)
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

    app.register_blueprint(logs_bp)
    app.register_blueprint(live_bp)

    return app


app = create_app()

if __name__ == "__main__":
    app_info = get_app_info()
    logger.info("Starting %s v%s", app_info["name"], app_info["version"])
    logger.info("Log file: %s", app_info["log_file"])
    logger.info("Server: %s:%s", app_info["host"], app_info["port"])

    LogStore.cleanup_old_stores(LOG_STORE_DIR, LOG_STORE_MAX_AGE_HOURS)
    cleanup_old_snapshots(LOG_STORE_DIR, LOG_STORE_MAX_AGE_HOURS)

    from lib.app_config import SSL_CERT_PATH, SSL_ENABLED, SSL_KEY_PATH

    if SSL_ENABLED:
        import ssl

        if not os.path.exists(SSL_CERT_PATH):
            logger.error("SSL certificate not found: %s", SSL_CERT_PATH)
            logger.error("Please provide a valid SSL certificate or set MI_SSL_ENABLED=false")
            exit(1)
        if not os.path.exists(SSL_KEY_PATH):
            logger.error("SSL key not found: %s", SSL_KEY_PATH)
            logger.error("Please provide a valid SSL private key or set MI_SSL_ENABLED=false")
            exit(1)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(SSL_CERT_PATH, SSL_KEY_PATH)

        logger.info("HTTPS enabled - Starting with SSL/TLS encryption")
        logger.info("SSL Certificate: %s", SSL_CERT_PATH)
        app.run(host=HOST, port=PORT, ssl_context=context)
    else:
        logger.warning("HTTPS disabled - Starting with HTTP (insecure)")
        logger.warning("For production use, enable HTTPS by setting MI_SSL_ENABLED=true")
        app.run(host=HOST, port=PORT)
