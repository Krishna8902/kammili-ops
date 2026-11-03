"""Read the kammili-ops Pages project and stop Git from publishing it.

GitHub Actions uploads a freshly built out/ with wrangler. The Git-connected
Pages build does not have the OwnerRez secrets, and out/ is not in the repo,
so a push build would publish an empty tree over the live site.

This script prints the build command, output directory, and environment
variable names. It does not print variable values or the API token.

Then it turns off automatic production and preview deployments. Wrangler
direct uploads still publish to the production branch.
"""
import json
import os
import sys
import urllib.error
import urllib.request

PROJECT = "kammili-ops"


def safe_summary(result):
    source = result.get("source") or {}
    config = source.get("config") or {}
    build = result.get("build_config") or {}
    production = (result.get("deployment_configs") or {}).get("production") or {}
    env = production.get("env_vars") or {}
    return {
        "source_type": source.get("type") or "",
        "production_branch": result.get("production_branch") or config.get("production_branch") or "",
        "build_command": build.get("build_command") or "",
        "destination_dir": build.get("destination_dir") or "",
        "root_dir": build.get("root_dir") or "",
        "production_deployments_enabled": config.get("production_deployments_enabled"),
        "preview_deployment_setting": config.get("preview_deployment_setting"),
        "env_var_names": sorted(env),
    }


def git_disable_patch(result):
    """Body for PATCH, or None when the project is not Git-connected."""
    source = result.get("source") or {}
    kind = source.get("type")
    if kind not in ("github", "gitlab"):
        return None
    config = source.get("config") or {}
    keep = (
        "owner", "repo_name", "production_branch", "pr_comments_enabled",
        "path_includes", "path_excludes", "preview_branch_includes",
        "preview_branch_excludes",
    )
    slim = {key: config[key] for key in keep if config.get(key) is not None}
    slim["production_deployments_enabled"] = False
    slim["preview_deployment_setting"] = "none"
    return {"source": {"type": kind, "config": slim}}


def _request(url, token, method, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        # The body can echo project settings. Keep it off the log.
        raise SystemExit(f"Cloudflare API HTTP {exc.code} on {method} pages project") from None
    if not payload.get("success"):
        messages = "; ".join(err.get("message", "") for err in payload.get("errors") or [])
        raise SystemExit(f"Cloudflare API {method} failed: {messages or 'unknown error'}")
    return payload["result"]


def main():
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account:
        raise SystemExit(
            "CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are required. "
            "Set them under GitHub → Settings → Secrets and variables → Actions."
        )
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/pages/projects/{PROJECT}"
    result = _request(url, token, "GET")
    summary = safe_summary(result)
    print("Pages project", PROJECT)
    for key in (
        "source_type", "production_branch", "build_command", "destination_dir",
        "root_dir", "production_deployments_enabled", "preview_deployment_setting",
    ):
        print(f"  {key}: {summary[key]!r}")
    print("  production_env_var_names:", ", ".join(summary["env_var_names"]) or "(none)")
    print("  ownerrez_secrets_on_pages:",
          "OWNERREZ_USER" in summary["env_var_names"] and "OWNERREZ_TOKEN" in summary["env_var_names"])

    patch = git_disable_patch(result)
    if patch is None:
        print("No Git source. Wrangler is the only publisher.")
        return
    updated = _request(url, token, "PATCH", patch)
    after = safe_summary(updated)
    print("git production deployments now:", after["production_deployments_enabled"])
    print("preview deployments now:", after["preview_deployment_setting"])
    if after["production_deployments_enabled"] is True:
        raise SystemExit("Git production deployments are still enabled.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Avoid str(exc): request errors can include the URL or response.
        raise SystemExit("Cloudflare Pages update failed.") from None
