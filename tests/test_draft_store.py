"""入力中の内容の保存（app/static/draft_store.js）のテスト

Node.jsで偽のlocalStorageと入力欄を用意して実行し、保存・復元・削除を確認する。
Node.jsが無い環境ではスキップする。
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "app" / "static" / "draft_store.js"
NODE = shutil.which("node")

RUNNER = r"""
const fs = require("fs");
const vm = require("vm");
const scenario = JSON.parse(fs.readFileSync(0, "utf8"));
const store = new Map(Object.entries(scenario.stored || {}));
const localStorage = scenario.storageBroken ? {
  getItem() { throw new Error("denied"); },
  setItem() { throw new Error("denied"); },
  removeItem() { throw new Error("denied"); },
} : {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
const context = { window: { localStorage } };
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
const listeners = [];
const input = { value: scenario.initial || "", addEventListener: (type, fn) => listeners.push(fn) };
const key = vm.runInContext(`draftKey(DRAFT_KINDS.${scenario.kind}, ${scenario.id})`, context);
context.input = input;
context.key = key;
vm.runInContext("bindDraft(input, key)", context);
const restored = input.value;
for (const value of scenario.typed || []) {
  input.value = value;
  listeners.forEach((fn) => fn());
}
if (scenario.clear) vm.runInContext("clearDraft(key)", context);
process.stdout.write(JSON.stringify({ key, restored, stored: Object.fromEntries(store) }));
"""

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.jsが無い")


def run(scenario: dict) -> dict:
    result = subprocess.run(
        [NODE, "-e", RUNNER, str(SCRIPT_PATH)],
        input=json.dumps(scenario),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def test_typed_value_is_saved_per_item():
    result = run({"kind": "cli", "id": 3, "typed": ["あ", "あい"]})
    assert result["key"] == "claude-tower.draft.cli.3"
    assert result["stored"] == {"claude-tower.draft.cli.3": "あい"}


def test_saved_draft_overrides_initial_value():
    stored = {"claude-tower.draft.mr.5": "下書き"}
    result = run({"kind": "mr", "id": 5, "initial": "前回の指示", "stored": stored})
    assert result["restored"] == "下書き"


def test_initial_value_is_kept_without_draft():
    result = run({"kind": "idea", "id": 7, "initial": "前回の観点", "stored": {"claude-tower.draft.idea.8": "別"}})
    assert result["restored"] == "前回の観点"


def test_empty_input_removes_draft():
    stored = {"claude-tower.draft.mr.5": "下書き"}
    result = run({"kind": "mr", "id": 5, "stored": stored, "typed": [""]})
    assert result["stored"] == {}


def test_clear_removes_draft():
    result = run({"kind": "cli", "id": 1, "typed": ["送信する内容"], "clear": True})
    assert result["stored"] == {}


def test_broken_storage_keeps_input_usable():
    result = run({"kind": "cli", "id": 1, "initial": "入力", "storageBroken": True, "typed": ["x"], "clear": True})
    assert result["restored"] == "入力"
