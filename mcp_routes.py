"""Authenticated MCP panel APIs, independently testable without Windows imports."""
from functools import wraps

from flask import jsonify, make_response, request

from mcp_manager import safe_error


def register_mcp_routes(app, login_required, manager):
    store = manager.store

    def guarded(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Cross-origin forms cannot supply this header. No CORS is enabled.
            if request.method != "GET" and request.headers.get("X-MCP-Request") != "1":
                return jsonify(status="error", message="无效请求，请从管理面板操作"), 403
            if request.method == "POST" and not request.is_json:
                return jsonify(status="error", message="需要 JSON 请求"), 400
            if request.content_length and request.content_length > 131072:
                return jsonify(status="error", message="配置数据过大"), 413
            try:
                response = make_response(fn(*args, **kwargs))
                response.headers['Cache-Control'] = 'no-store'
                return response
            except ValueError as exc:
                # Validation errors contain field descriptions, not credentials.
                return jsonify(status="error", message=str(exc)), 400
            except Exception as exc:
                return jsonify(status="error", message=safe_error(exc)), 502
        return login_required(wrapper)

    @app.route("/api/mcp/config", methods=["GET"])
    @guarded
    def mcp_get_config():
        return jsonify(status="success", config=store.public())

    @app.route("/api/mcp/settings", methods=["POST"])
    @guarded
    def mcp_save_settings():
        store.settings(request.get_json())
        return jsonify(status="success")

    @app.route("/api/mcp/servers", methods=["POST"])
    @guarded
    def mcp_save_server():
        server_id = store.save(request.get_json())
        return jsonify(status="success", id=server_id)

    @app.route("/api/mcp/servers/<server_id>", methods=["DELETE"])
    @guarded
    def mcp_delete_server(server_id):
        store.delete(server_id)
        return jsonify(status="success")

    @app.route("/api/mcp/test", methods=["POST"])
    @guarded
    def mcp_test_server():
        server = store.draft(request.get_json())
        if server.get("kind") == "hrzh_person":
            return jsonify(status="success", **manager.test_person(server))
        # Discovery only. Never invoke a tool from the connection-test button.
        return jsonify(status="success", tools=manager.test(server))
