/**
 * 入力中の内容の保存（下書き）
 *
 * 指示内容などの入力欄の内容を、開始・送信の前でもブラウザに保存しておく。
 * 項目の切り替え・画面の再読み込みの後も、保存した内容を入力欄に戻す。
 * 開始・送信に成功したら、保存した内容を消す。
 * 保存先はブラウザのlocalStorageとし、使えない環境では保存しない。
 */

// 保存のキーの接頭辞
const DRAFT_KEY_PREFIX = "claude-tower.draft.";

// 下書きの種類（キーの一部）
const DRAFT_KINDS = { mr: "mr", cli: "cli", idea: "idea" };

function draftKey(kind, id) {
  return `${DRAFT_KEY_PREFIX}${kind}.${id}`;
}

function draftStorage() {
  try {
    return window.localStorage;
  } catch (error) {
    return null;
  }
}

/**
 * 保存した下書きを返す
 *
 * 保存していない・読み取れない場合はnullを返す。
 */
function loadDraft(key) {
  try {
    return draftStorage()?.getItem(key) ?? null;
  } catch (error) {
    return null;
  }
}

/**
 * 下書きを保存する
 *
 * 空欄は保存せず、保存済みの下書きを消す。
 * 容量超過などで保存できない場合は何もしない。
 */
function saveDraft(key, value) {
  try {
    if (value) draftStorage()?.setItem(key, value);
    else draftStorage()?.removeItem(key);
  } catch (error) {
    // 保存できなくても入力は続けられるため無視する
  }
}

function clearDraft(key) {
  saveDraft(key, "");
}

/**
 * 入力欄と下書きを結び付ける
 *
 * 下書きがあれば入力欄に戻し、入力のたびに保存する。
 * 下書きが無い場合は入力欄の内容をそのまま残す。
 */
function bindDraft(input, key) {
  const draft = loadDraft(key);
  if (draft !== null) input.value = draft;
  input.addEventListener("input", () => saveDraft(key, input.value));
}
