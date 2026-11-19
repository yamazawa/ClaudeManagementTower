/**
 * 画像添付のお絵かきダイアログ
 *
 * ドラッグで赤い四角枠、タップで赤い丸数字（①、②…）を描く。
 * 描いた内容を画像に焼き込み、PNGファイルとして返す。
 */

// 見た目の調整値（サイズは画像の長辺に対する比率で指定する）
const IMAGE_EDITOR_STYLE = {
  color: "#e01e1e",
  numberFill: "#ffffff",
  rectLineRatio: 0.004,
  numberRadiusRatio: 0.022,
  numberLineRatio: 0.003,
  numberFontRatio: 1.3,
  numberWideFontRatio: 1.0,
  minRectLine: 2,
  minNumberRadius: 12,
  dragThresholdPx: 8,
  maxOutputSide: 2560,
};

const IMAGE_EDITOR_MESSAGES = {
  loadFailed: "画像を読み込めませんでした",
  exportFailed: "画像の出力に失敗しました",
};

/**
 * 画像を開いてお絵かきダイアログを表示する
 *
 * 添付ボタンで加工後のPNGファイル、キャンセルでnullを返す。
 */
async function openImageEditor(file) {
  const image = await loadImageFile(file).catch(() => null);
  if (!image) {
    alert(IMAGE_EDITOR_MESSAGES.loadFailed);
    return null;
  }
  const editor = createImageEditorState(image);
  redrawImageEditor(editor);
  return showImageEditorDialog(editor, file.name);
}

function loadImageFile(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = (error) => {
      URL.revokeObjectURL(url);
      reject(error);
    };
    image.src = url;
  });
}

/**
 * 編集状態を作る
 *
 * 大きすぎる画像は添付サイズを抑えるため長辺を縮小する。
 */
function createImageEditorState(image) {
  const canvas = document.getElementById("image-editor-canvas");
  const scale = Math.min(1, IMAGE_EDITOR_STYLE.maxOutputSide / Math.max(image.naturalWidth, image.naturalHeight));
  canvas.width = Math.round(image.naturalWidth * scale);
  canvas.height = Math.round(image.naturalHeight * scale);
  URL.revokeObjectURL(image.src);
  return { canvas, image, shapes: [], drag: null };
}

/**
 * ダイアログを表示し、閉じられるまで待つ
 *
 * イベントはダイアログを開くたびに登録し、閉じたら解除する。
 */
function showImageEditorDialog(editor, filename) {
  const dialog = document.getElementById("image-editor");
  return new Promise((resolve) => {
    const controller = new AbortController();
    const finish = (result) => {
      controller.abort();
      dialog.close();
      resolve(result);
    };
    bindImageEditorPointer(editor, controller.signal);
    bindImageEditorButtons(editor, filename, finish, controller.signal);
    dialog.showModal();
  });
}

function bindImageEditorButtons(editor, filename, finish, signal) {
  const on = (id, handler) => document.getElementById(id).addEventListener("click", handler, { signal });
  on("image-editor-undo", () => {
    editor.shapes.pop();
    redrawImageEditor(editor);
  });
  on("image-editor-cancel", () => finish(null));
  on("image-editor-attach", async () => {
    const edited = await exportImageEditor(editor, filename);
    if (!edited) alert(IMAGE_EDITOR_MESSAGES.exportFailed);
    finish(edited);
  });
  document.getElementById("image-editor").addEventListener(
    "cancel",
    (event) => {
      event.preventDefault();
      finish(null);
    },
    { signal }
  );
}

/**
 * ポインタ操作（マウス・タッチ共通）を登録する
 *
 * 移動量がしきい値未満ならタップとして丸数字、以上ならドラッグとして四角枠にする。
 */
function bindImageEditorPointer(editor, signal) {
  const { canvas } = editor;
  const on = (type, handler) => canvas.addEventListener(type, handler, { signal });
  on("pointerdown", (event) => {
    canvas.setPointerCapture(event.pointerId);
    editor.drag = { start: toCanvasPoint(canvas, event), current: null, startClient: clientPoint(event) };
  });
  on("pointermove", (event) => {
    if (!editor.drag || !isDragging(editor.drag, event)) return;
    editor.drag.current = toCanvasPoint(canvas, event);
    redrawImageEditor(editor);
  });
  on("pointerup", (event) => finishPointer(editor, event));
  on("pointercancel", () => {
    editor.drag = null;
    redrawImageEditor(editor);
  });
}

function finishPointer(editor, event) {
  const drag = editor.drag;
  editor.drag = null;
  if (!drag) return;
  if (isDragging(drag, event)) {
    editor.shapes.push({ type: "rect", start: drag.start, end: toCanvasPoint(editor.canvas, event) });
  } else {
    const number = editor.shapes.filter((s) => s.type === "number").length + 1;
    editor.shapes.push({ type: "number", center: drag.start, number });
  }
  redrawImageEditor(editor);
}

function clientPoint(event) {
  return { x: event.clientX, y: event.clientY };
}

function isDragging(drag, event) {
  const dx = event.clientX - drag.startClient.x;
  const dy = event.clientY - drag.startClient.y;
  return Math.hypot(dx, dy) >= IMAGE_EDITOR_STYLE.dragThresholdPx;
}

/**
 * 画面上の座標をキャンバスの座標に変換する
 *
 * キャンバスは画面に合わせて縮小表示するため、表示倍率で割り戻す。
 */
function toCanvasPoint(canvas, event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) * canvas.width) / rect.width,
    y: ((event.clientY - rect.top) * canvas.height) / rect.height,
  };
}

function redrawImageEditor(editor) {
  const { canvas, image, shapes, drag } = editor;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
  const sizes = imageEditorSizes(canvas);
  shapes.forEach((shape) => drawImageEditorShape(ctx, shape, sizes));
  if (drag && drag.current) drawImageEditorShape(ctx, { type: "rect", start: drag.start, end: drag.current }, sizes);
}

function imageEditorSizes(canvas) {
  const side = Math.max(canvas.width, canvas.height);
  return {
    rectLine: Math.max(IMAGE_EDITOR_STYLE.minRectLine, side * IMAGE_EDITOR_STYLE.rectLineRatio),
    numberRadius: Math.max(IMAGE_EDITOR_STYLE.minNumberRadius, side * IMAGE_EDITOR_STYLE.numberRadiusRatio),
    numberLine: Math.max(1, side * IMAGE_EDITOR_STYLE.numberLineRatio),
  };
}

function drawImageEditorShape(ctx, shape, sizes) {
  if (shape.type === "rect") drawEditorRect(ctx, shape, sizes);
  else drawEditorNumber(ctx, shape, sizes);
}

function drawEditorRect(ctx, { start, end }, sizes) {
  ctx.strokeStyle = IMAGE_EDITOR_STYLE.color;
  ctx.lineWidth = sizes.rectLine;
  ctx.strokeRect(start.x, start.y, end.x - start.x, end.y - start.y);
}

/**
 * 丸数字を描く
 *
 * 背景に埋もれないよう、白抜きの円に赤い枠と赤い数字を描く。
 */
function drawEditorNumber(ctx, { center, number }, sizes) {
  const radius = sizes.numberRadius;
  ctx.beginPath();
  ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
  ctx.fillStyle = IMAGE_EDITOR_STYLE.numberFill;
  ctx.fill();
  ctx.strokeStyle = IMAGE_EDITOR_STYLE.color;
  ctx.lineWidth = sizes.numberLine;
  ctx.stroke();
  const fontRatio = number < 10 ? IMAGE_EDITOR_STYLE.numberFontRatio : IMAGE_EDITOR_STYLE.numberWideFontRatio;
  ctx.font = `bold ${Math.round(radius * fontRatio)}px system-ui, sans-serif`;
  ctx.fillStyle = IMAGE_EDITOR_STYLE.color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(String(number), center.x, center.y + radius * 0.05);
}

/**
 * 加工後の画像をPNGファイルにする
 *
 * ファイル名は元の名前の拡張子をpngに置き換える。
 */
function exportImageEditor(editor, filename) {
  redrawImageEditor({ ...editor, drag: null });
  const baseName = filename.replace(/\.[^.]*$/, "") || "image";
  return new Promise((resolve) => {
    editor.canvas.toBlob(
      (blob) => resolve(blob ? new File([blob], `${baseName}.png`, { type: "image/png" }) : null),
      "image/png"
    );
  });
}
