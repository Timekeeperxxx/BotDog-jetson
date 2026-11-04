import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("deployment_manifest", ROOT / "scripts/record-deployment.py")
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)


def test_code_fingerprint_includes_dirty_and_untracked_sources_but_excludes_secrets(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "backend/app.py"
    source.parent.mkdir()
    source.write_text("original")
    panel = tmp_path / "frontend/src/components/logs/LogPanel.tsx"
    panel.parent.mkdir(parents=True)
    panel.write_text("source under a directory named logs")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Regression", "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline"], cwd=tmp_path, check=True)
    original = manifest.code_identity(tmp_path)
    source.write_text("modified")
    (source.parent / "new.py").write_text("new source")
    for name in (".env", "settings.env"):
        (source.parent / name).write_text("SENSITIVE_VALUE=do-not-export")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/output.log").write_text("private runtime data")
    changed = manifest.code_identity(tmp_path)
    assert changed["commit"] == original["commit"]
    assert changed["source_tree_sha256"] != original["source_tree_sha256"]
    assert set(changed["source_files"]) == {"backend/app.py", "backend/new.py", "frontend/src/components/logs/LogPanel.tsx"}
    assert set(changed["dirty_source_files"]) == {"backend/app.py", "backend/new.py"}
    assert "SENSITIVE_VALUE" not in json.dumps(changed)


def test_model_checksum_changes_independently_of_code_and_missing_models_are_explicit(tmp_path):
    model = tmp_path / "detector.engine"
    model.write_bytes(b"first model")
    first = manifest.model_identity(tmp_path, {"AI_MODEL_PATH": "detector.engine"})
    model.write_bytes(b"new model")
    second = manifest.model_identity(tmp_path, {"AI_MODEL_PATH": "detector.engine", "POSE_MODEL_PATH": "missing.engine", "PACKAGE_DETAIL_MODEL_PATH": ""})
    assert first["AI_MODEL_PATH"]["sha256"] != second["AI_MODEL_PATH"]["sha256"]
    assert second["AI_MODEL_PATH"]["available"] is True
    assert second["POSE_MODEL_PATH"]["available"] is False
    assert second["PACKAGE_DETAIL_MODEL_PATH"] == {"configured": False}


def test_manifest_write_replaces_previous_complete_file(tmp_path):
    path = tmp_path / "deployments/current.json"
    manifest.write_manifest(path, {"schema_version": 1, "code": "first"})
    manifest.write_manifest(path, {"schema_version": 1, "code": "second"})
    assert json.loads(path.read_text())["code"] == "second"
    assert list(path.parent.iterdir()) == [path]
