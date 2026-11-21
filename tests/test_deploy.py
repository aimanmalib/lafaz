"""Deploy files keep keys and state out of the image and the container within its host limits."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _lines(name: str) -> set[str]:
    return {ln.strip() for ln in (ROOT / name).read_text().splitlines() if ln.strip() and not ln.startswith("#")}


def test_build_context_excludes_keys_and_state():
    ignored = _lines(".dockerignore")
    for entry in (".env", ".env.*", "state/", "dalaman/", "*.db", "deploy/hos.env", ".git"):
        assert entry in ignored, entry


def test_host_values_and_tags_are_not_tracked():
    ignored = _lines(".gitignore")
    for entry in ("deploy/hos.env", "deploy/CURRENT_TAG", "deploy/PREVIOUS_TAG"):
        assert entry in ignored, entry


def test_container_is_named_for_the_project_and_capped():
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    assert "container_name: lafaz\n" in compose
    assert "cpus: 0.75" in compose
    assert "name: lafaz-data" in compose
    assert "read_only: true" in compose


def test_route_compresses_and_redirects():
    route = (ROOT / "deploy" / "traefik.yaml.tmpl").read_text()
    assert "compress:" in route and "redirectScheme:" in route
    assert "url: http://lafaz:8080" in route


def test_deploy_script_offers_rollback_and_status():
    script = (ROOT / "deploy" / "deploy.sh").read_text()
    assert "--rollback)" in script and "--status)" in script
    assert "git -C .. archive HEAD" in script
