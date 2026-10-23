import hashlib, importlib.util, json, pathlib, shutil, subprocess
import httpx, httpx._decoders
import ru_llm_scanner.cli

modules = {
    n: importlib.util.find_spec(n) is not None
    for n in ("brotli", "brotlicffi", "_brotli")
}
decoders = sorted(httpx._decoders.SUPPORTED_DECODERS)
with httpx.Client(trust_env=False) as client:
    accept = client.headers.get("accept-encoding", "")
# This assertion precedes the deliberately non-Brotli synthetic response.
assert "br" not in decoders and not any(modules.values())
response = httpx.Response(
    200, headers={"content-encoding": "br"}, content=b"scanner-no-brotli-decoder"
)
assert response.content == b"scanner-no-brotli-decoder"
git = shutil.which("git")
git_links = subprocess.check_output(["ldd", git], text=True)
helper = (
    pathlib.Path(subprocess.check_output(["git", "--exec-path"], text=True).strip())
    / "git-remote-http"
)
helper_links = subprocess.check_output(["ldd", str(helper)], text=True)
loaded = pathlib.Path("/proc/self/maps").read_text()
result = {
    "component": "scanner",
    "python_optional_modules": modules,
    "httpx_supported_decoders": decoders,
    "httpx_default_accept_encoding": accept,
    "unsupported_br_response_left_opaque": True,
    "git_binary_sha256": hashlib.file_digest(open(git, "rb"), "sha256").hexdigest(),
    "git_binary_links_brotli": "brotli" in git_links.lower(),
    "git_binary_links_libcurl": "libcurl" in git_links.lower(),
    "remote_http_helper_links_brotli": "brotli" in helper_links.lower(),
    "remote_http_helper_links_libcurl": "libcurl" in helper_links.lower(),
    "brotli_loaded_in_python_process": "brotli" in loaded.lower(),
    "node_installed": shutil.which("node") is not None,
    "installed_lib_brotli": subprocess.check_output(
        ["dpkg-query", "-W", "-f=${Version}", "libbrotli1"], text=True
    ),
    "scope": "Default local Git-object reader and internal HTTPX route only; library remains vulnerable for other callers",
}
result["status"] = (
    "passed"
    if not any(
        (
            result["git_binary_links_brotli"],
            result["git_binary_links_libcurl"],
            result["brotli_loaded_in_python_process"],
            result["node_installed"],
        )
    )
    else "requires_review"
)
print(json.dumps(result))
