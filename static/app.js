const state = {
  sourceId: null,
  sourceUrl: null,
  sourceType: null, // "image" | "video"
  duration: null,
  cropStart: 0,
  cropEnd: 1,
  cropLeft: 0,
  cropRight: 1,
  activeHandle: null,
  timelineDrag: null,
  pollTimer: null,
  importing: false,
  downloading: false,
  downloadPollTimer: null,
  cacheKey: false, // source 是否有可持久化的缓存目录（bilibili / local）
  previewLoading: false,
  previewRequestId: 0,
  previewTime: null,
  initialPreviewTime: null,
  pendingPreviewTime: null,
  pendingPreviewSourceId: null,
  loginPollTimer: null,
  bilibiliLoggedIn: false,
  stage: 1,
  maxStage: 1,
  captureJobId: null,
  images: [],
  inserting: false,
  generating: false,
  insertIndex: null,
  noteColorSelected: false, // 第三步是否已选定音符颜色并去色
  recolorPreviewTimer: null, // 第四步着色预览节流
  latestVersion: null, // 检查更新得到的最新版本号
  skippedVersion: null, // 跳过的版本号（不在启动时弹窗）
};

const JSON_HEADERS = { "Content-Type": "application/json" };

const els = {
  importPanel: document.getElementById("importPanel"),
  importForm: document.getElementById("importForm"),
  importButton: document.getElementById("importButton"),
  importStatus: document.getElementById("importStatus"),
  importProgressWrap: document.getElementById("importProgressWrap"),
  importProgressFill: document.getElementById("importProgressFill"),
  importProgressText: document.getElementById("importProgressText"),
  workspace: document.getElementById("workspace"),
  bvidInput: document.getElementById("bvidInput"),
  bilibiliLoginButton: document.getElementById("bilibiliLoginButton"),
  loginModal: document.getElementById("loginModal"),
  loginModalClose: document.getElementById("loginModalClose"),
  loginQrImage: document.getElementById("loginQrImage"),
  loginStatus: document.getElementById("loginStatus"),
  localFile: document.getElementById("localFile"),
  fileField: document.querySelector(".file-field"),
  fileHint: document.querySelector(".file-hint"),
  previewFrame: document.getElementById("previewFrame"),
  timeline: document.getElementById("timeline"),
  timelineTrack: document.getElementById("timelineTrack"),
  timelineProgress: document.getElementById("timelineProgress"),
  timelineStartHandle: document.getElementById("timelineStartHandle"),
  timelineEndHandle: document.getElementById("timelineEndHandle"),
  timelineEndLabel: document.getElementById("timelineEndLabel"),
  previewImage: document.getElementById("previewImage"),
  previewLoadingOverlay: document.getElementById("previewLoadingOverlay"),
  previewStatus: document.getElementById("previewStatus"),
  previewTimeHint: document.getElementById("previewTimeHint"),
  shadeTop: document.getElementById("shadeTop"),
  shadeBottom: document.getElementById("shadeBottom"),
  shadeLeft: document.getElementById("shadeLeft"),
  shadeRight: document.getElementById("shadeRight"),
  cropWindow: document.getElementById("cropWindow"),
  cropTop: document.getElementById("cropTop"),
  cropBottom: document.getElementById("cropBottom"),
  cropLeft: document.getElementById("cropLeft"),
  cropRight: document.getElementById("cropRight"),
  timeRow: document.getElementById("timeRow"),
  advancedSettings: document.getElementById("advancedSettings"),
  startMinInput: document.getElementById("startMinInput"),
  startSecInput: document.getElementById("startSecInput"),
  endMinInput: document.getElementById("endMinInput"),
  endSecInput: document.getElementById("endSecInput"),
  sampleEvery: document.getElementById("sampleEvery"),
  diffThreshold: document.getElementById("diffThreshold"),
  bandHalfWidth: document.getElementById("bandHalfWidth"),
  compareWindow: document.getElementById("compareWindow"),
  generateButton: document.getElementById("generateButton"),
  extractStatus: document.getElementById("extractStatus"),
  extractProgressWrap: document.getElementById("extractProgressWrap"),
  extractProgressFill: document.getElementById("extractProgressFill"),
  extractProgressText: document.getElementById("extractProgressText"),
  adjustPanel: document.getElementById("adjustPanel"),
  cardList: document.getElementById("cardList"),
  toLayoutButton: document.getElementById("toLayoutButton"),
  adjustStatus: document.getElementById("adjustStatus"),
  autoCropButton: document.getElementById("autoCropButton"),
  autoMeasureButton: document.getElementById("autoMeasureButton"),
  coeffHorizontal: document.getElementById("coeffHorizontal"),
  coeffVertical: document.getElementById("coeffVertical"),
  stitchMaxWidth: document.getElementById("stitchMaxWidth"),
  layoutPanel: document.getElementById("layoutPanel"),
  titleArea: document.getElementById("titleArea"),
  scaleSlider: document.getElementById("scaleSlider"),
  scaleInput: document.getElementById("scaleInput"),
  marginSlider: document.getElementById("marginSlider"),
  pageMargin: document.getElementById("pageMargin"),
  spacingSlider: document.getElementById("spacingSlider"),
  imageSpacing: document.getElementById("imageSpacing"),
  titleSpacingSlider: document.getElementById("titleSpacingSlider"),
  titleSpacing: document.getElementById("titleSpacing"),
  bgColorHex: document.getElementById("bgColorHex"),
  bgColor: document.getElementById("bgColor"),
  bgColorEyedrop: document.getElementById("bgColorEyedrop"),
  textColorHex: document.getElementById("textColorHex"),
  textColor: document.getElementById("textColor"),
  textColorEyedrop: document.getElementById("textColorEyedrop"),
  invertInput: document.getElementById("invertInput"),
  recolorInput: document.getElementById("recolorInput"),
  cleanDetails: document.getElementById("cleanDetails"),
  cleanDetailsSummary: document.querySelector("#cleanDetails summary"),
  noteColorHex: document.getElementById("noteColorHex"),
  noteColor: document.getElementById("noteColor"),
  noteColorEyedrop: document.getElementById("noteColorEyedrop"),
  noteColorModal: document.getElementById("noteColorModal"),
  noteColorModalClose: document.getElementById("noteColorModalClose"),
  noteColorModalTitle: document.getElementById("noteColorModalTitle"),
  noteColorSampleImage: document.getElementById("noteColorSampleImage"),
  noteColorConfirm: document.getElementById("noteColorConfirm"),
  tolerance: document.getElementById("tolerance"),
  toleranceNum: document.getElementById("toleranceNum"),
  softness: document.getElementById("softness"),
  softnessNum: document.getElementById("softnessNum"),
  insertModal: document.getElementById("insertModal"),
  insertFileField: document.getElementById("insertFileField"),
  insertFileInput: document.getElementById("insertFileInput"),
  insertVideoButton: document.getElementById("insertVideoButton"),
  insertDivider: document.getElementById("insertDivider"),
  insertModalClose: document.getElementById("insertModalClose"),
  downloadPdfButton: document.getElementById("downloadPdfButton"),
  downloadLongButton: document.getElementById("downloadLongButton"),
  layoutStatus: document.getElementById("layoutStatus"),
  generateProgressWrap: document.getElementById("generateProgressWrap"),
  progressFill: document.getElementById("progressFill"),
  progressText: document.getElementById("progressText"),
  pageList: document.getElementById("pageList"),
  backToTop: document.getElementById("backToTop"),
  infoButton: document.getElementById("infoButton"),
  infoModal: document.getElementById("infoModal"),
  infoModalClose: document.getElementById("infoModalClose"),
  updateLink: document.getElementById("updateLink"),
  updateModal: document.getElementById("updateModal"),
  updateModalClose: document.getElementById("updateModalClose"),
  updateLog: document.getElementById("updateLog"),
  updateDownloadBtn: document.getElementById("updateDownloadBtn"),
  updateSkipBtn: document.getElementById("updateSkipBtn"),
};

const PHASE_LABELS = {
  queued: "排队中",
  downloading: "下载中",
  extracting: "提取中",
  building_pdf: "生成 PDF 中",
  done: "完成",
  error: "错误",
};

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

// 让十六进制文本框与原生取色器双向同步。
function bindColorField(hexEl, pickerEl) {
  const normalize = (value) => {
    let v = (value || "").trim().toLowerCase();
    if (/^[0-9a-f]{6}$/.test(v)) v = "#" + v;
    return /^#[0-9a-f]{6}$/.test(v) ? v : null;
  };

  hexEl.addEventListener("input", () => {
    const v = normalize(hexEl.value);
    if (v) pickerEl.value = v;
  });
  pickerEl.addEventListener("input", () => {
    hexEl.value = pickerEl.value;
  });
  hexEl.addEventListener("blur", () => {
    hexEl.value = normalize(hexEl.value) || pickerEl.value;
  });
}

// 吸管取色：用浏览器原生 EyeDropper 从屏幕取样，写入文本与取色器。
function bindEyedropper(btn, hexEl, pickerEl, onChange) {
  if (!btn) return;
  if (typeof window.EyeDropper !== "function") {
    btn.classList.add("hidden");
    return;
  }
  btn.addEventListener("click", async () => {
    try {
      const dropper = new window.EyeDropper();
      const result = await dropper.open();
      const hex = (result && result.sRGBHex) || null;
      if (!hex) return;
      hexEl.value = hex;
      pickerEl.value = hex;
      if (onChange) onChange();
    } catch (e) {
      /* 用户取消或浏览器不支持 */
    }
  });
}

// 滑块 + 文本框双向同步，变化时触发回调（用于排版实时重渲染）。
function bindSliderPair(rangeEl, numberEl, onChange) {
  rangeEl.addEventListener("input", () => {
    numberEl.value = rangeEl.value;
    if (onChange) onChange();
  });
  numberEl.addEventListener("input", () => {
    const v = parseFloat(numberEl.value);
    if (!Number.isFinite(v)) return;
    rangeEl.value = String(clamp(v, parseFloat(rangeEl.min), parseFloat(rangeEl.max)));
    if (onChange) onChange();
  });
}

function setStage(n) {
  state.stage = n;
  state.maxStage = Math.max(state.maxStage, n);
  els.importPanel.classList.toggle("hidden", n !== 1);
  els.workspace.classList.toggle("hidden", n !== 2);
  els.adjustPanel.classList.toggle("hidden", n !== 3);
  els.layoutPanel.classList.toggle("hidden", n !== 4);
  renderStepper();
  if (n === 2 && state.sourceId && state.previewTime === null && !state.previewLoading) {
    // 进入截图步骤时，若尚未加载预览，默认显示视频时间中点的一帧。
    loadPreview(state.initialPreviewTime);
  }
  if (n === 4) {
    renderPages();
    schedulePersist();
  }
}

function renderStepper() {
  document.querySelectorAll(".stepper li[data-step]").forEach((li) => {
    const step = Number(li.dataset.step);
    const active = step === state.stage;
    const clickable = !active && step <= state.maxStage;
    li.classList.toggle("is-active", active);
    li.classList.toggle("is-done", clickable);
    li.classList.toggle("is-clickable", clickable);
    if (clickable) {
      li.setAttribute("role", "button");
      li.setAttribute("tabindex", "0");
    } else {
      li.removeAttribute("role");
      li.removeAttribute("tabindex");
    }
    if (active) {
      li.setAttribute("aria-current", "step");
    } else {
      li.removeAttribute("aria-current");
    }
  });
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `请求失败：${response.status}`);
  }
  return data;
}

function setStatus(element, message, mode = "") {
  element.textContent = message;
  element.dataset.mode = mode;
}

// 清空各步骤的状态提示（回到上一步操作、重新生成后使用）。
function clearStatuses() {
  setStatus(els.importStatus, "");
  setStatus(els.extractStatus, "");
  setStatus(els.adjustStatus, "");
  setStatus(els.layoutStatus, "");
}

// 通知气泡：短暂弹出后自动消失。
function showToast(message, mode = "") {
  let host = document.querySelector(".toast-host");
  if (!host) {
    host = document.createElement("div");
    host.className = "toast-host";
    document.body.appendChild(host);
  }
  const toast = document.createElement("div");
  toast.className = "toast" + (mode ? ` toast-${mode}` : "");
  toast.textContent = message;
  host.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("is-visible"));
  setTimeout(() => {
    toast.classList.remove("is-visible");
    setTimeout(() => toast.remove(), 240);
  }, 2600);
}

function setControlBusy(controls, busy) {
  controls.forEach((control) => {
    if (control) control.disabled = busy;
  });
}

function setImportLoading(isLoading) {
  state.importing = isLoading;
  els.importPanel.setAttribute("aria-busy", String(isLoading));
  els.importPanel.classList.toggle("is-loading", isLoading);
  els.importButton.textContent = isLoading ? "导入中..." : "导入";
  setControlBusy([els.importButton, els.bvidInput, els.bilibiliLoginButton, els.localFile], isLoading);
}

// 导入阶段的下载进度（不确定动画）。
function setImportProgress(text) {
  if (!els.importProgressWrap) return;
  els.importProgressWrap.classList.remove("hidden");
  els.importProgressFill.classList.remove("is-determinate");
  els.importProgressFill.style.width = "";
  els.importProgressText.textContent = text || "下载中…";
}

function hideImportProgress() {
  if (els.importProgressWrap) els.importProgressWrap.classList.add("hidden");
}

// 轮询 B 站视频下载状态，完成后加载预览并进入截图页。
async function pollDownload(sourceId) {
  if (state.downloading) return;
  state.downloading = true;
  setImportProgress("下载中…");
  try {
    const result = await fetchJson(`/api/source/${sourceId}/download`);
    if (sourceId !== state.sourceId) return;
    if (result.status === "done") {
      hideImportProgress();
      setStatus(els.importStatus, "已导入。", "success");
      state.maxStage = 2;
      setStage(2);
      return;
    }
    if (result.status === "error") {
      hideImportProgress();
      setStatus(els.importStatus, result.message || "下载失败。", "error");
      return;
    }
    state.downloadPollTimer = setTimeout(() => pollDownload(sourceId), 1000);
  } catch (error) {
    hideImportProgress();
    setStatus(els.importStatus, error.message, "error");
  } finally {
    state.downloading = false;
  }
}

function serializeImages() {
  return state.images.map((m) => ({
    file: m.file,
    t: m.t ?? 0,
    w: m.w,
    h: m.h,
    hidden: !!m.hidden,
    crop: { l: m.crop.l, r: m.crop.r, t: m.crop.t ?? 0, b: m.crop.b ?? 1 },
    measures: m.measures || [],
  }));
}

// 序列化第四步排版参数，随缓存一起持久化以便恢复。
function serializeLayout() {
  return {
    title: els.titleArea.value || "",
    scale: els.scaleInput.value || "1",
    margin: els.pageMargin.value || "40",
    spacing: els.imageSpacing.value || "25",
    titleSpacing: els.titleSpacing.value || "130",
    bgColor: els.bgColor.value || "#ffffff",
    textColor: els.textColor.value || "#181818",
    orientation: currentOrientation(),
    align: currentAlign(),
    valign: currentValign(),
    previewCols: currentPreviewCols(),
    invert: !!els.invertInput.checked,
    recolor: !!(els.recolorInput && els.recolorInput.checked),
  };
}

// 每张图片可变更字段的签名，用于 diff 增量持久化。
function imageSignature(m) {
  return JSON.stringify({
    hidden: !!m.hidden,
    crop: { l: m.crop.l, r: m.crop.r, t: m.crop.t ?? 0, b: m.crop.b ?? 1 },
    measures: m.measures || [],
  });
}

// 上一次持久化到后端的快照（按 file 存签名），用于只发送变更部分。
let persistSnapshot = null;

// 持久化调整状态：只把「改了什么」发给后端，避免整表反复序列化导致卡顿。
function persistStateNow() {
  if (!state.cacheKey || !state.captureJobId) return;
  const images = state.images;
  const layout = serializeLayout();
  const maxStage = state.maxStage;
  const body = { job_id: state.captureJobId };

  if (!persistSnapshot) {
    // 首次保存：发送完整列表。
    body.images = serializeImages();
    body.layout = layout;
    body.maxStage = maxStage;
  } else {
    const oldSigs = persistSnapshot.images;
    const newFiles = new Set(images.map((m) => m.file));
    const removed = [...oldSigs.keys()].some((f) => !newFiles.has(f));
    const added = images.some((m) => !oldSigs.has(m.file));

    const patches = [];
    for (const m of images) {
      if (!oldSigs.has(m.file)) continue;
      if (oldSigs.get(m.file) !== imageSignature(m)) {
        patches.push({
          file: m.file,
          hidden: !!m.hidden,
          crop: { l: m.crop.l, r: m.crop.r, t: m.crop.t ?? 0, b: m.crop.b ?? 1 },
          measures: m.measures || [],
        });
      }
    }

    if (removed || added || patches.length > 1) {
      body.images = serializeImages();
    } else if (patches.length === 1) {
      body.image = patches[0];
    }

    if (persistSnapshot.layout !== JSON.stringify(layout)) body.layout = layout;
    if (persistSnapshot.maxStage !== maxStage) body.maxStage = maxStage;
  }

  fetchJson("/api/save_state", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
    keepalive: true,
  }).then(() => {
    persistSnapshot = {
      images: new Map(images.map((m) => [m.file, imageSignature(m)])),
      layout: JSON.stringify(layout),
      maxStage,
    };
  }).catch(() => {});
}

let persistTimer = null;
function schedulePersist() {
  if (!state.cacheKey) return;
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(persistStateNow, 800);
}

function setPreviewLoading(isLoading, message = "更新预览中...", mode = "") {
  state.previewLoading = isLoading;
  els.workspace.setAttribute("aria-busy", String(isLoading));
  els.previewFrame.setAttribute("aria-busy", String(isLoading));
  els.previewFrame.classList.toggle("is-loading", isLoading);
  els.previewStatus.textContent = message;
  els.previewStatus.dataset.mode = mode;
  els.previewLoadingOverlay.classList.toggle("hidden", !isLoading && !message);
  els.previewLoadingOverlay.classList.toggle("is-error", mode === "error");
  els.previewLoadingOverlay.classList.remove("is-stale");
}

function clearPreviewStatus() {
  setPreviewLoading(false, "");
}

function formatSeconds(value) {
  if (!Number.isFinite(value)) return "00:00";
  const rounded = Math.max(0, Math.round(value));
  const minutes = Math.floor(rounded / 60);
  const seconds = rounded % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function updatePreviewTimeHint() {
  els.previewTimeHint.textContent = state.previewTime === null ? "" : `当前预览：${formatSeconds(state.previewTime)}`;
}

function readTimeParts(minInput, secInput) {
  const minText = (minInput.value || "").trim();
  const secText = (secInput.value || "").trim();
  if (minText === "" && secText === "") return null;
  const minutes = Math.max(0, Number(minText) || 0);
  const seconds = Math.max(0, Number(secText) || 0);
  return minutes * 60 + seconds;
}

function currentStartTime() {
  const value = readTimeParts(els.startMinInput, els.startSecInput);
  return Number.isFinite(value) ? value : 0;
}

function currentEndTime() {
  return readTimeParts(els.endMinInput, els.endSecInput);
}

function updateCropUi() {
  const top = state.cropStart * 100;
  const bottom = (1 - state.cropEnd) * 100;
  const left = state.cropLeft * 100;
  const right = (1 - state.cropRight) * 100;
  const height = (state.cropEnd - state.cropStart) * 100;
  const width = (state.cropRight - state.cropLeft) * 100;

  els.shadeTop.style.height = `${top}%`;
  els.shadeBottom.style.height = `${bottom}%`;
  els.shadeLeft.style.width = `${left}%`;
  els.shadeLeft.style.top = `${top}%`;
  els.shadeLeft.style.height = `${height}%`;
  els.shadeRight.style.width = `${right}%`;
  els.shadeRight.style.top = `${top}%`;
  els.shadeRight.style.height = `${height}%`;
  els.cropWindow.style.top = `${top}%`;
  els.cropWindow.style.left = `${left}%`;
  els.cropWindow.style.height = `${height}%`;
  els.cropWindow.style.width = `${width}%`;

  els.cropTop.style.left = `${left}%`;
  els.cropTop.style.width = `${width}%`;
  els.cropTop.style.top = `${top}%`;

  els.cropBottom.style.left = `${left}%`;
  els.cropBottom.style.width = `${width}%`;
  els.cropBottom.style.top = `${state.cropEnd * 100}%`;

  els.cropLeft.style.top = `${top}%`;
  els.cropLeft.style.height = `${height}%`;
  els.cropLeft.style.left = `${left}%`;

  els.cropRight.style.top = `${top}%`;
  els.cropRight.style.height = `${height}%`;
  els.cropRight.style.left = `${state.cropRight * 100}%`;
}

function pointerRatio(event) {
  const rect = els.previewFrame.getBoundingClientRect();
  return clamp((event.clientY - rect.top) / rect.height, 0, 1);
}

function pointerRatioX(event) {
  const rect = els.previewFrame.getBoundingClientRect();
  return clamp((event.clientX - rect.left) / rect.width, 0, 1);
}

const V_GAP = 0.05;
const H_GAP = 0.01;

function applyCropDrag(handle, ratioY, ratioX) {
  if (handle === "top") {
    state.cropStart = clamp(ratioY, 0, state.cropEnd - V_GAP);
  } else if (handle === "bottom") {
    state.cropEnd = clamp(ratioY, state.cropStart + V_GAP, 1);
  } else if (handle === "left") {
    state.cropLeft = clamp(ratioX, 0, state.cropRight - H_GAP);
  } else {
    state.cropRight = clamp(ratioX, state.cropLeft + H_GAP, 1);
  }
}

function beginDrag(handle, event) {
  event.preventDefault();
  state.activeHandle = handle;
  event.currentTarget.setPointerCapture?.(event.pointerId);
}

function dragCrop(event) {
  if (!state.activeHandle) return;
  applyCropDrag(state.activeHandle, pointerRatio(event), pointerRatioX(event));
  updateCropUi();
}

function endDrag() {
  state.activeHandle = null;
}

function clickCrop(event) {
  if (event.target.closest(".crop-handle")) return;
  event.preventDefault();
  const ratioY = pointerRatio(event);
  const ratioX = pointerRatioX(event);
  const distTop = Math.abs(ratioY - state.cropStart);
  const distBottom = Math.abs(ratioY - state.cropEnd);
  const distLeft = Math.abs(ratioX - state.cropLeft);
  const distRight = Math.abs(ratioX - state.cropRight);

  let handle;
  if (Math.min(distTop, distBottom) <= Math.min(distLeft, distRight)) {
    handle = distTop <= distBottom ? "top" : "bottom";
  } else {
    handle = distLeft <= distRight ? "left" : "right";
  }
  state.activeHandle = handle;
  applyCropDrag(handle, ratioY, ratioX);
  updateCropUi();
  event.currentTarget.setPointerCapture?.(event.pointerId);
}

const MIN_TIMELINE_GAP = 0.5;

function hasTimelineDuration() {
  return Number.isFinite(state.duration) && state.duration > 0;
}

function resolvedEndTime() {
  const end = currentEndTime();
  if (Number.isFinite(end)) return end;
  return state.duration ?? 0;
}

function setTimeInputs(minInput, secInput, totalSeconds) {
  const whole = Math.max(0, Math.round(totalSeconds));
  minInput.value = String(Math.floor(whole / 60));
  secInput.value = String(whole % 60);
}

function timeToRatio(time) {
  if (!hasTimelineDuration()) return 0;
  return clamp(time / state.duration, 0, 1);
}

function updateTimeline() {
  if (!hasTimelineDuration()) {
    els.timeline.classList.add("is-disabled");
    return;
  }
  els.timeline.classList.remove("is-disabled");
  els.timelineEndLabel.textContent = formatSeconds(state.duration);
  const startPct = timeToRatio(currentStartTime()) * 100;
  const endPct = timeToRatio(resolvedEndTime()) * 100;
  els.timelineStartHandle.style.left = `${startPct}%`;
  els.timelineEndHandle.style.left = `${endPct}%`;
  els.timelineProgress.style.left = `${startPct}%`;
  els.timelineProgress.style.width = `${Math.max(0, endPct - startPct)}%`;
}

function timelineRatioFromEvent(event) {
  const rect = els.timelineTrack.getBoundingClientRect();
  return clamp((event.clientX - rect.left) / rect.width, 0, 1);
}

function beginTimelineDrag(which, event) {
  if (!hasTimelineDuration()) return;
  event.preventDefault();
  state.timelineDrag = which;
  event.currentTarget.setPointerCapture?.(event.pointerId);
}

function applyTimelineDrag(ratio) {
  const time = ratio * state.duration;
  if (state.timelineDrag === "start") {
    const maxStart = Math.max(0, resolvedEndTime() - MIN_TIMELINE_GAP);
    setTimeInputs(els.startMinInput, els.startSecInput, clamp(time, 0, maxStart));
  } else {
    const minEnd = Math.min(state.duration, currentStartTime() + MIN_TIMELINE_GAP);
    setTimeInputs(els.endMinInput, els.endSecInput, clamp(time, minEnd, state.duration));
  }
  updateTimeline();
}

function dragTimeline(event) {
  if (!state.timelineDrag) return;
  applyTimelineDrag(timelineRatioFromEvent(event));
}

function beginTimelineTrackDrag(event) {
  if (!hasTimelineDuration()) return;
  if (event.target.closest(".timeline-handle")) return;
  event.preventDefault();
  const ratio = timelineRatioFromEvent(event);
  const startRatio = timeToRatio(currentStartTime());
  const endRatio = timeToRatio(resolvedEndTime());
  state.timelineDrag = Math.abs(ratio - startRatio) <= Math.abs(ratio - endRatio) ? "start" : "end";
  applyTimelineDrag(ratio);
  els.timeline.setPointerCapture?.(event.pointerId);
}

function endTimelineDrag() {
  if (!state.timelineDrag) return;
  const which = state.timelineDrag;
  state.timelineDrag = null;
  if (which === "start") {
    loadPreview(currentStartTime());
  } else {
    loadPreview(resolvedEndTime());
  }
}

function resetExtractionState() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  els.generateButton.disabled = false;
  hideExtractProgress();
  setStatus(els.extractStatus, "");
}

function applySource(source) {
  state.previewRequestId += 1;
  state.previewTime = null;
  state.pendingPreviewTime = null;
  state.pendingPreviewSourceId = null;
  clearPreviewStatus();
  updatePreviewTimeHint();
  resetExtractionState();
  clearStatuses();
  state.images = [];
  state.captureJobId = null;
  persistSnapshot = null;
  if (state.downloadPollTimer) {
    clearTimeout(state.downloadPollTimer);
    state.downloadPollTimer = null;
  }
  state.downloading = false;
  hideImportProgress();

  state.sourceId = source.id;
  state.cacheKey = !!source.cache_dir;
  state.duration = source.duration || null;
  state.sourceType = source.type === "image" ? "image" : "video";
  const metadata = source.metadata || {};
  const title = metadata.display_title || metadata.raw_title || "";
  const channel = metadata.channel || "";
  state.sourceUrl = metadata.source_url || "";
  // URL 导入自动识别的标题/作者直接分两行放入文本域；本地图片/视频只有标题。
  els.titleArea.value = channel ? `${title}\n${channel}` : title;

  const isImage = state.sourceType === "image";
  els.timeline.classList.toggle("hidden", isImage);
  els.timeRow.classList.toggle("hidden", isImage);
  els.advancedSettings.classList.toggle("hidden", isImage);

  els.startMinInput.value = "0";
  els.startSecInput.value = "0";
  if (state.duration && state.duration > 0) {
    setTimeInputs(els.endMinInput, els.endSecInput, state.duration);
  } else {
    els.endMinInput.value = "";
    els.endSecInput.value = "";
  }
  state.initialPreviewTime = state.duration ? Math.floor(Math.floor(state.duration) / 2) : 0;

  updateCropUi();
  updateTimeline();

  // 命中缓存：直接恢复截图、调整状态与排版参数；若已保存过排版则直接跳到第四步。
  if (source.restore) {
    state.captureJobId = source.restore.job_id;
    restoreCards(source.restore.images);
    restoreLayout(source.restore.layout);
    const targetStage = source.restore.maxStage === 4 ? 4 : 3;
    state.maxStage = Math.max(3, targetStage);
    setStage(targetStage);
    setStatus(els.importStatus, "已从缓存恢复。", "success");
    return;
  }

  // B 站视频在导入时即开始下载：停留在导入页显示进度，下载完成后再进入截图页。
  if (source.download && source.download.status === "downloading") {
    state.maxStage = 1;
    setStage(1);
    pollDownload(source.id);
    return;
  }

  state.maxStage = 2;
  setStage(2);
}

async function loadPreview(timeValue) {
  if (!state.sourceId) return;

  if (state.sourceType === "image") {
    // 图片源没有时间轴，直接显示原图。
    els.previewImage.src = `/api/source_image/${state.sourceId}?v=${Date.now()}`;
    state.previewTime = null;
    updatePreviewTimeHint();
    clearPreviewStatus();
    return;
  }

  const time = Number.isFinite(Number(timeValue)) ? Number(timeValue) : 0;
  const sourceId = state.sourceId;

  if (state.previewLoading) {
    state.pendingPreviewTime = time;
    state.pendingPreviewSourceId = sourceId;
    state.previewRequestId += 1;
    els.previewStatus.textContent = "更新预览中...";
    return;
  }

  const requestId = state.previewRequestId + 1;
  state.previewRequestId = requestId;
  setPreviewLoading(true, "更新预览中...");

  try {
    const data = await fetchJson("/api/preview", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ source_id: sourceId, time }),
    });
    if (requestId !== state.previewRequestId || sourceId !== state.sourceId) return;
    els.previewImage.src = `${data.preview_url}?v=${Date.now()}`;
    state.previewTime = time;
    updatePreviewTimeHint();
    clearPreviewStatus();
  } catch (error) {
    if (requestId !== state.previewRequestId || sourceId !== state.sourceId) return;
    setPreviewLoading(false, error.message, "error");
  } finally {
    if (sourceId !== state.sourceId) return;
    if (state.pendingPreviewTime !== null && state.pendingPreviewSourceId === state.sourceId) {
      const nextTime = state.pendingPreviewTime;
      state.pendingPreviewTime = null;
      state.pendingPreviewSourceId = null;
      state.previewLoading = false;
      loadPreview(nextTime);
    } else if (requestId === state.previewRequestId) {
      state.previewLoading = false;
    }
  }
}

function numericValue(input, fallback = null) {
  // 元素被注释/不存在时（如高级设置被注释掉）返回默认值，避免报错。
  if (!input || input.value === "") return fallback;
  return Number(input.value);
}

function currentOrientation() {
  const checked = document.querySelector('input[name="orientation"]:checked');
  return checked ? checked.value : "portrait";
}

function currentAlign() {
  const checked = document.querySelector('input[name="align"]:checked');
  return checked ? checked.value : "left";
}

function currentValign() {
  const checked = document.querySelector('input[name="valign"]:checked');
  return checked ? checked.value : "top";
}

function currentPreviewCols() {
  const checked = document.querySelector('input[name="previewCols"]:checked');
  const n = Number(checked ? checked.value : 1);
  return n === 2 ? 2 : 1;
}

// 第四步「去除彩色背景」开关状态：未在第三步去色时直接 disable。
// 提示文字始终为「到第三步调整去色效果」，不再随状态切换。
function syncRecolorOption() {
  const btn = els.recolorInput && els.recolorInput.closest(".seg-btn");
  if (!btn) return;
  if (state.noteColorSelected) {
    btn.classList.remove("is-disabled");
    els.recolorInput.disabled = false;
  } else {
    btn.classList.add("is-disabled");
    els.recolorInput.disabled = true;
    els.recolorInput.checked = false;
  }
}

// 去色 details 摘要文案：未去色显示「点此去色：提升自动识别准确度」；已去色显示「点此取消去色」。
function updateCleanSummary() {
  if (els.cleanDetailsSummary) {
    els.cleanDetailsSummary.textContent = state.noteColorSelected ? "点此取消去色" : "点此去色：提升自动识别准确度";
  }
}

function buildExtractPayload() {
  return {
    source_id: state.sourceId,
    start: currentStartTime(),
    end: currentEndTime(),
    crop_y_start: state.cropStart,
    crop_y_end: state.cropEnd,
    crop_x_start: state.cropLeft,
    crop_x_end: state.cropRight,
    sample_every: numericValue(els.sampleEvery, 2),
    diff_threshold: numericValue(els.diffThreshold, 0.01),
    band_half_width: numericValue(els.bandHalfWidth, 90),
    compare_window: numericValue(els.compareWindow, 1),
  };
}

// 计算本次提取的总帧数（用于进度条）：(结束-开始) / 采样间隔，向上取整。
function totalFrames() {
  const start = currentStartTime();
  const end = currentEndTime();
  const sampleEvery = numericValue(els.sampleEvery, 2);
  if (!Number.isFinite(end) || end <= start || sampleEvery <= 0) return 0;
  return Math.ceil((end - start) / sampleEvery);
}

// 更新提取进度：确定态（已检查/总数）百分比；下载等无总量的阶段用不确定动画。
function setExtractProgress(percent, text) {
  if (!els.extractProgressWrap) return;
  els.extractProgressWrap.classList.remove("hidden");
  if (percent == null) {
    // 不确定进度（如下载阶段）：恢复滑动动画。
    els.extractProgressFill.classList.remove("is-determinate");
    els.extractProgressFill.style.width = "";
  } else {
    els.extractProgressFill.classList.add("is-determinate");
    els.extractProgressFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  }
  if (els.extractProgressText) els.extractProgressText.textContent = text || "";
}

function hideExtractProgress() {
  if (els.extractProgressWrap) els.extractProgressWrap.classList.add("hidden");
}

function renderJob(job) {
  const phaseKey = job.status === "error" ? "error" : job.phase || job.status;
  const total = totalFrames();

  if (job.status === "done") {
    const kept = job.stats?.captures_kept ?? 0;
    hideExtractProgress();
    setStatus(els.extractStatus, `已生成 ${kept} 张截图。`, "success");
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    els.generateButton.disabled = false;
    state.maxStage = 3;
    setStage(3);
    // 新一批截图：重置去色状态。
    state.noteColorSelected = false;
    if (els.cleanDetails) els.cleanDetails.open = false;
    updateCleanSummary();
    syncRecolorOption();
    renderCards(job.captures || []);
  } else if (job.status === "error") {
    hideExtractProgress();
    setStatus(els.extractStatus, job.error || "处理失败。", "error");
    showToast(job.error || "处理失败。", "error");
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    els.generateButton.disabled = false;
  } else {
    // 进行中：有 stats（frames_checked）说明正在提取，用确定进度；
    // 下载/排队等阶段没有 stats，用不确定进度动画。
    const frames = job.stats?.frames_checked ?? 0;
    if (job.stats && total > 0) {
      const percent = (frames / total) * 100;
      setExtractProgress(percent, `${frames} / ${total}`);
    } else {
      setExtractProgress(null, PHASE_LABELS[phaseKey] || phaseKey);
    }
    setStatus(els.extractStatus, "生成中...");
  }
}

const PAGE_W = 1654;
const PAGE_H = 2339;
const FOOTER_H = 80;
const HEADER_TITLE_SIZE = 64; // 与后端 HEADER_TITLE_SIZE 一致（标题基准字号）
const MEASURE_EPS = 0.008; // 小节线距裁剪边「过近」的判定阈值（归一化）

function currentLayoutOpts() {
  return {
    orientation: currentOrientation(),
    align: currentAlign(),
    valign: currentValign(),
    margin: numericValue(els.pageMargin, 40),
    spacing: numericValue(els.imageSpacing, 25),
    titleSpacing: numericValue(els.titleSpacing, 130),
    scale: numericValue(els.scaleInput, 1),
    bgColor: els.bgColor.value || "#ffffff",
    textColor: els.textColor.value || "#181818",
    titleLines: (els.titleArea.value || "")
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean),
    url: state.sourceUrl || "",
  };
}

function currentPageCssWidth() {
  const avail = els.pageList ? els.pageList.clientWidth : 0;
  const base = Math.max(280, Math.min(1600, avail || 700));
  if (currentPreviewCols() === 2) {
    return Math.max(280, Math.floor((base - 22) / 2));
  }
  return base;
}

// 第三步卡片预览：若已去色则显示黑白音符图（音符黑/背景白），否则原图。
function step3Src(m) {
  if (!state.noteColorSelected) return m.url;
  const params = new URLSearchParams();
  params.set("binarize", "1");
  params.set("note_color", els.noteColor.value || "#000000");
  params.set("tolerance", els.tolerance.value);
  params.set("softness", els.softness.value);
  return `/api/capture_preview/${state.captureJobId}/${m.file}?${params.toString()}`;
}

// 第四步条带预览：去色（音符黑/背景白）→(可选)反色。
function step4Src(m) {
  const recolor = els.recolorInput && els.recolorInput.checked;
  const invert = els.invertInput.checked;
  if (!recolor && !invert) return m.url;
  const params = new URLSearchParams();
  params.set("invert", invert ? "1" : "0");
  if (recolor) {
    params.set("binarize", "1");
    params.set("note_color", els.noteColor.value || "#000000");
    params.set("tolerance", els.tolerance.value);
    params.set("softness", els.softness.value);
  }
  return `/api/capture_preview/${state.captureJobId}/${m.file}?${params.toString()}`;
}

// 只刷新卡片预览图的 src，不重建整张卡片（供去色参数拖动时轻量更新）。
function refreshCardPreviews() {
  state.images.forEach((m, i) => {
    const card = els.cardList.querySelector(`.card[data-index="${i}"]`);
    if (card) {
      const img = card.querySelector(".preview-img");
      if (img) img.src = step3Src(m);
    }
  });
}

// 去色相关参数变化：刷新第三步卡片预览，并在第四步时重渲染排版。
function onCleanChange() {
  refreshCardPreviews();
  scheduleRecolorPreview();
}

// 第四步着色预览的节流：拖动颜色条时避免疯狂重渲染导致卡顿。
function scheduleRecolorPreview() {
  if (state.stage !== 4) return;
  if (state.recolorPreviewTimer) clearTimeout(state.recolorPreviewTimer);
  state.recolorPreviewTimer = setTimeout(() => {
    state.recolorPreviewTimer = null;
    renderPages();
  }, 160);
}

// 全局小节编号：左裁剪边界占一个编号（无圆圈、不可删除）；裁剪框内的小节线
// 按顺序编号并显示圆圈；裁剪框外的小节线不变号、显示为 ×、可删除。
function numberMeasures() {
  let n = 0;
  state.images.forEach((m) => {
    if (m.hidden) {
      // 隐藏的卡片：所有小节线显示为 ×，且不参与全局编号。
      m.edgeLeftNum = null;
      m.measureItems = (m.measures || [])
        .slice()
        .sort((a, b) => a - b)
        .map((x) => ({ x, num: null }));
      return;
    }
    const l = m.crop.l;
    const r = m.crop.r;
    m.edgeLeftNum = ++n;
    m.measureItems = [];
    (m.measures || []).slice().sort((a, b) => a - b).forEach((x) => {
      const inside = x > l + MEASURE_EPS && x < r - MEASURE_EPS;
      m.measureItems.push({ x, num: inside ? ++n : null });
    });
  });
}

/* ===================== 第 3 步：截图卡片 ===================== */

// 图标以独立 SVG 文件存放在 /static/icons/，便于直接修改。
const ICONS = {};
async function loadIcons() {
  const files = {
    grip: "grip",
    eye: "eye",
    eyeOff: "eye-off",
    insert: "insert",
    scissors: "scissors",
    clear: "broom",
    magic: "magic",
    arrowUp: "arrow-up",
    arrowDown: "arrow-down",
    portrait: "portrait",
    landscape: "landscape",
    "align-center": "align-center",
    "align-left": "align-left",
    "align-right": "align-right",
    "align-top": "align-top",
    "align-middle": "align-middle",
    "align-bottom": "align-bottom",
    "columns-1": "columns-1",
    "columns-2": "columns-2",
    contrast: "contrast",
    "droplet-off": "droplet-off",
    sliders: "sliders",
    upload: "upload",
  };
  await Promise.all(
    Object.entries(files).map(async ([key, file]) => {
      try {
        const res = await fetch(`/static/icons/${file}.svg`);
        if (res.ok) ICONS[key] = await res.text();
      } catch (e) {
        /* 图标缺失时退化为空 */
      }
    })
  );
  fillToolbarIcons();
}
function iconSvg(key) {
  return ICONS[key] || "";
}
function fillToolbarIcons() {
  document.querySelectorAll(".seg-icon[data-icon], .file-icon[data-icon]").forEach((el) => {
    el.innerHTML = iconSvg(el.dataset.icon);
  });
}

function renderCards(images) {
  state.images = (images || []).map((m) => ({
    file: m.file,
    url: m.url,
    t: m.t ?? 0,
    w: m.w,
    h: m.h,
    hidden: false,
    flash: false,
    crop: { l: 0, r: 1, t: 0, b: 1 },
    measures: [],
  }));
  renderCardList();
}

// 从缓存恢复：保留隐藏、裁剪、小节线等调整状态，url 用当前 job_id 重建。
function restoreCards(images) {
  state.images = (images || []).map((m) => ({
    file: m.file,
    url: `/api/captures/${state.captureJobId}/${m.file}`,
    t: m.t ?? 0,
    w: m.w,
    h: m.h,
    hidden: !!m.hidden,
    flash: false,
    crop: { l: m.crop?.l ?? 0, r: m.crop?.r ?? 1, t: m.crop?.t ?? 0, b: m.crop?.b ?? 1 },
    measures: m.measures || [],
  }));
  renderCardList();
}

// 从缓存恢复第四步排版参数。
function restoreLayout(layout) {
  if (!layout) return;
  const setVal = (input, slider, value) => {
    if (input) input.value = value;
    if (slider) slider.value = value;
  };
  if (layout.title != null) els.titleArea.value = layout.title;
  setVal(els.scaleInput, els.scaleSlider, layout.scale);
  setVal(els.pageMargin, els.marginSlider, layout.margin);
  setVal(els.imageSpacing, els.spacingSlider, layout.spacing);
  setVal(els.titleSpacing, els.titleSpacingSlider, layout.titleSpacing);
  setVal(els.bgColor, els.bgColorHex, layout.bgColor);
  setVal(els.textColor, els.textColorHex, layout.textColor);
  const setRadio = (name, value) => {
    if (value == null) return;
    const radio = document.querySelector(`input[name="${name}"][value="${value}"]`);
    if (radio) radio.checked = true;
  };
  setRadio("orientation", layout.orientation);
  setRadio("align", layout.align);
  setRadio("valign", layout.valign);
  setRadio("previewCols", String(layout.previewCols));
  if (layout.invert != null) els.invertInput.checked = !!layout.invert;
  if (els.recolorInput && layout.recolor != null) els.recolorInput.checked = !!layout.recolor;
  syncRecolorOption();
}

function renderCardList() {
  numberMeasures();
  const scrollY = window.scrollY;
  els.cardList.innerHTML = "";
  state.images.forEach((m, i) => {
    const card = buildCard(m, i);
    els.cardList.appendChild(card);
    applyCardCropVisual(card, m);
  });
  if (Math.abs(window.scrollY - scrollY) > 1) window.scrollTo(0, scrollY);
  syncAutoDetectButtons();
  syncSplitButtons();
  schedulePersist();
}

// 仅更新卡片动态内容（小节线、编号、裁剪视觉、按钮图标），不重建整个 DOM。
// 大量截图时避免整体重建导致卡顿与滚动条跳动；排序/增删/分割/合并等结构变化
// 会改变卡片顺序，检测到顺序不一致时自动退回整体重建。
function syncCardList() {
  numberMeasures();
  const scrollY = window.scrollY;
  const cards = [...els.cardList.querySelectorAll(".card")];
  const currentOrder = cards.map((c) => c.dataset.file).join("");
  const targetOrder = state.images.map((m) => m.file).join("");
  if (currentOrder !== targetOrder) {
    renderCardList();
    return;
  }
  state.images.forEach((m, i) => {
    const card = cards[i];
    if (card) syncCardContent(card, m, i);
  });
  if (Math.abs(window.scrollY - scrollY) > 1) window.scrollTo(0, scrollY);
  syncAutoDetectButtons();
  syncSplitButtons();
  schedulePersist();
}

function syncCardContent(card, m, i) {
  card.dataset.index = String(i);
  if (m.hidden) card.dataset.hidden = "true";
  else delete card.dataset.hidden;

  const preview = card.querySelector(".card-preview");
  if (!preview) return;
  preview.querySelectorAll(".measure-line").forEach((el) => el.remove());
  (m.measureItems || []).forEach((it) => {
    const line = document.createElement("div");
    line.className = "measure-line";
    line.dataset.x = String(it.x);
    preview.appendChild(line);
  });

  const strip = card.querySelector(".card-measure-strip");
  if (strip) {
    strip.querySelectorAll(".measure-num").forEach((el) => el.remove());
    const edge = strip.querySelector(".measure-edge");
    if (edge) {
      edge.dataset.x = String(m.crop.l);
      edge.textContent = String(m.edgeLeftNum ?? "");
    }
    (m.measureItems || []).forEach((it) => {
      const num = document.createElement("span");
      num.className = "measure-num";
      num.dataset.x = String(it.x);
      if (it.num != null) {
        num.innerHTML = `<span class="measure-num-label">${it.num}</span><span class="measure-x">×</span>`;
      } else {
        num.textContent = "×";
        num.title = "删除此小节线";
      }
      num.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteMeasure(i, it.x);
      });
      strip.appendChild(num);
    });
  }

  applyCardCropVisual(card, m);

  const hideBtn = card.querySelector('.card-btn[data-action="hide"]');
  if (hideBtn) {
    const title = m.hidden ? "显示" : "隐藏";
    hideBtn.innerHTML = iconSvg(m.hidden ? "eyeOff" : "eye");
    hideBtn.title = title;
    hideBtn.setAttribute("aria-label", title);
  }
  const measureBtn = card.querySelector('.card-btn[data-action="clear"]');
  if (measureBtn) {
    const has = Boolean(m.measures && m.measures.length);
    const title = has ? "清空小节线" : "自动识别小节线";
    measureBtn.innerHTML = iconSvg(has ? "clear" : "magic");
    measureBtn.title = title;
    measureBtn.setAttribute("aria-label", title);
  }
}

// 让「横向分割」按钮的高度跟随预览图（图片）高度。
function syncSplitButtons() {
  if (!els.cardList) return;
  els.cardList.querySelectorAll(".card").forEach((card) => {
    const preview = card.querySelector(".card-preview");
    const btn = card.querySelector(".split-btn");
    if (preview && btn) {
      btn.style.height = `${Math.max(40, preview.clientHeight)}px`;
    }
  });
}

// 是否已有自动裁剪结果（存在非默认的水平裁剪框）。
function hasAutoCrop() {
  return state.images.some((m) => m.crop.l > 0.001 || m.crop.r < 0.999);
}

// 是否已标记小节线。
function hasMeasures() {
  return state.images.some((m) => (m.measures || []).length > 0);
}

// 根据当前状态在「自动xx / 清空xx」之间切换按钮文案。
function syncAutoDetectButtons() {
  const crop = els.autoCropButton;
  const measure = els.autoMeasureButton;
  if (crop && crop.querySelector(".auto-detect-label")) {
    const clear = hasAutoCrop();
    crop.querySelector(".auto-detect-label").textContent = clear ? "清空裁剪" : "自动裁剪";
    crop.classList.toggle("is-clear", clear);
  }
  if (measure && measure.querySelector(".auto-detect-label")) {
    const clear = hasMeasures();
    measure.querySelector(".auto-detect-label").textContent = clear ? "清空小节" : "自动小节";
    measure.classList.toggle("is-clear", clear);
  }
}

// 读取「自动检测高级设置」里的小节线识别参数。
function detectParams() {
  const p = {
    coefficient_horizontal: numericValue(els.coeffHorizontal, 0.7),
    coefficient_vertical: numericValue(els.coeffVertical, 0.8),
  };
  // 第三步已去色时，按音符颜色二值化后再检测。
  if (state.noteColorSelected) {
    p.note_color = els.noteColor.value || "#000000";
    p.tolerance = numericValue(els.tolerance, 60);
    p.softness = numericValue(els.softness, 20);
  }
  return p;
}

// 自动裁剪：去除相邻截图之间重复的小节（把拼接缝对齐到小节线上）。
async function autoCrop() {
  const files = state.images.map((m) => m.file);
  if (!files.length) return;
  const data = await fetchJson("/api/stitch", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      job_id: state.captureJobId,
      files,
      ...detectParams(),
      max_width: numericValue(els.stitchMaxWidth, 600),
    }),
  });

  const seams = data.seams || [];
  state.images.forEach((m, i) => {
    if (i > 0) {
      const s = seams[i - 1];
      if (s && typeof s[1] === "number") m.crop.l = clamp(s[1], 0, 1);
    }
    if (i < state.images.length - 1) {
      const s = seams[i];
      if (s && typeof s[0] === "number") m.crop.r = clamp(s[0], 0, 1);
    }
    if (m.crop.r - m.crop.l < 0.02) {
      m.crop.l = 0;
      m.crop.r = 1;
    }
  });

  syncCardList();
}

// 自动小节：标记每张截图里的小节线（标记后排版可放大图片）。
async function autoMeasures() {
  const files = state.images.map((m) => m.file);
  if (!files.length) return;
  const data = await fetchJson("/api/detect_measures", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      job_id: state.captureJobId,
      files,
      ...detectParams(),
    }),
  });
  const measures = data.measures || {};
  state.images.forEach((m) => {
    m.measures = measures[m.file] || [];
  });
  syncCardList();
}

async function detectMeasuresFor(files) {
  if (!files.length) return;
  const data = await fetchJson("/api/detect_measures", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ job_id: state.captureJobId, files, ...detectParams() }),
  });
  const measures = data.measures || {};
  files.forEach((f) => {
    const m = state.images.find((img) => img.file === f);
    if (m) m.measures = measures[f] || [];
  });
}

function makeCardBtn(iconName, title, key, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "card-btn";
  if (key === "grip") b.classList.add("card-grip");
  b.title = title;
  b.setAttribute("aria-label", title);
  b.dataset.action = key;
  b.innerHTML = iconSvg(iconName);
  if (onClick) b.addEventListener("click", (e) => onClick(e));
  return b;
}

function applyCardCropVisual(cardEl, m) {
  // 预览图与编号条始终顶满卡片宽度（CSS width:100%），随卡片/窗口宽度自适应；
  // 所有小节线、裁剪框、编号均用百分比定位，与图片一一对应。
  cardEl.querySelectorAll(".measure-line").forEach((el) => {
    el.style.left = `${parseFloat(el.dataset.x) * 100}%`;
  });
  cardEl.querySelectorAll(".measure-num, .measure-edge").forEach((el) => {
    el.style.left = `${parseFloat(el.dataset.x) * 100}%`;
  });
  const t = m.crop.t ?? 0;
  const b = m.crop.b ?? 1;
  const l = m.crop.l;
  const r = m.crop.r;
  const vTop = t * 100;
  const vH = (b - t) * 100;
  const hW = (r - l) * 100;

  // 裁剪把手：参考工作区裁剪框，左右把手跨越裁剪区高度，上下把手跨越裁剪区宽度。
  const handleLeft = cardEl.querySelector('.card-crop-handle[data-side="left"]');
  const handleRight = cardEl.querySelector('.card-crop-handle[data-side="right"]');
  const handleTop = cardEl.querySelector('.card-crop-handle[data-side="top"]');
  const handleBottom = cardEl.querySelector('.card-crop-handle[data-side="bottom"]');
  if (handleLeft) {
    handleLeft.style.left = `${l * 100}%`;
    handleLeft.style.top = `${vTop}%`;
    handleLeft.style.height = `${vH}%`;
  }
  if (handleRight) {
    handleRight.style.left = `${r * 100}%`;
    handleRight.style.top = `${vTop}%`;
    handleRight.style.height = `${vH}%`;
  }
  if (handleTop) {
    handleTop.style.top = `${vTop}%`;
    handleTop.style.left = `${l * 100}%`;
    handleTop.style.width = `${hW}%`;
  }
  if (handleBottom) {
    handleBottom.style.top = `${b * 100}%`;
    handleBottom.style.left = `${l * 100}%`;
    handleBottom.style.width = `${hW}%`;
  }

  // 裁剪框外遮罩：上下遮罩覆盖全宽，左右遮罩被约束在裁剪区高度内。
  const shadeTop = cardEl.querySelector('.crop-shade[data-side="top"]');
  const shadeBottom = cardEl.querySelector('.crop-shade[data-side="bottom"]');
  const shadeLeft = cardEl.querySelector('.crop-shade[data-side="left"]');
  const shadeRight = cardEl.querySelector('.crop-shade[data-side="right"]');
  if (shadeTop) {
    shadeTop.style.left = "0";
    shadeTop.style.top = "0";
    shadeTop.style.width = "100%";
    shadeTop.style.height = `${vTop}%`;
  }
  if (shadeBottom) {
    shadeBottom.style.left = "0";
    shadeBottom.style.bottom = "0";
    shadeBottom.style.width = "100%";
    shadeBottom.style.height = `${(1 - b) * 100}%`;
  }
  if (shadeLeft) {
    shadeLeft.style.left = "0";
    shadeLeft.style.top = `${vTop}%`;
    shadeLeft.style.width = `${l * 100}%`;
    shadeLeft.style.height = `${vH}%`;
  }
  if (shadeRight) {
    shadeRight.style.left = `${r * 100}%`;
    shadeRight.style.top = `${vTop}%`;
    shadeRight.style.width = `${(1 - r) * 100}%`;
    shadeRight.style.height = `${vH}%`;
  }

  // 裁剪框四周边线。
  const edgeLeft = cardEl.querySelector('.crop-edge[data-side="left"]');
  const edgeRight = cardEl.querySelector('.crop-edge[data-side="right"]');
  const edgeTop = cardEl.querySelector('.crop-edge[data-side="top"]');
  const edgeBottom = cardEl.querySelector('.crop-edge[data-side="bottom"]');
  if (edgeLeft) {
    edgeLeft.style.left = `${l * 100}%`;
    edgeLeft.style.top = `${vTop}%`;
    edgeLeft.style.height = `${vH}%`;
  }
  if (edgeRight) {
    edgeRight.style.left = `${r * 100}%`;
    edgeRight.style.top = `${vTop}%`;
    edgeRight.style.height = `${vH}%`;
  }
  if (edgeTop) {
    edgeTop.style.top = `${vTop}%`;
    edgeTop.style.left = `${l * 100}%`;
    edgeTop.style.width = `${hW}%`;
  }
  if (edgeBottom) {
    edgeBottom.style.top = `${b * 100}%`;
    edgeBottom.style.left = `${l * 100}%`;
    edgeBottom.style.width = `${hW}%`;
  }

  // 左右裁剪边线位置的小节线（虚线，贯穿整张预览）。
  const measureLineLeft = cardEl.querySelector('.crop-measure-line[data-side="left"]');
  const measureLineRight = cardEl.querySelector('.crop-measure-line[data-side="right"]');
  if (measureLineLeft) measureLineLeft.style.left = `${l * 100}%`;
  if (measureLineRight) measureLineRight.style.left = `${r * 100}%`;
}

function buildCard(m, index) {
  const card = document.createElement("div");
  card.className = "card";
  card.dataset.index = String(index);
  card.dataset.file = m.file;
  if (m.hidden) card.dataset.hidden = "true";
  if (m.flash) card.classList.add("is-flash");

  // —— 列 1：排序 / 隐藏 / 下方插入 ——
  const col1 = document.createElement("div");
  col1.className = "card-col";
  const gripBtn = makeCardBtn("grip", "拖动排序", "grip", null);
  gripBtn.addEventListener("pointerdown", (e) => beginCardSort(index, card, e));
  col1.appendChild(gripBtn);
  col1.appendChild(makeCardBtn(m.hidden ? "eyeOff" : "eye", m.hidden ? "显示" : "隐藏", "hide", () => toggleHidden(index)));
  const menuBtn = makeCardBtn("insert", "在下方插入", "insert", () => openInsertModal(index));
  col1.appendChild(menuBtn);

  // —— 列 2：预览 + 水平裁剪 + 小节线 ——
  const col2 = document.createElement("div");
  col2.className = "card-col-2";

  const preview = document.createElement("div");
  preview.className = "card-preview";
  const img = document.createElement("img");
  img.className = "preview-img";
  img.src = step3Src(m);
  img.alt = "";
  img.draggable = false;
  // 用已知宽高锁定宽高比，图片加载前即占位，避免列表重建时高度抖动导致滚动条跳动。
  if (m.w && m.h) img.style.aspectRatio = `${m.w} / ${m.h}`;
  preview.appendChild(img);

  (m.measureItems || []).forEach((it) => {
    const line = document.createElement("div");
    line.className = "measure-line";
    line.dataset.x = String(it.x);
    preview.appendChild(line);
  });

  const splitLine = document.createElement("div");
  splitLine.className = "split-line";
  splitLine.style.display = "none";
  preview.appendChild(splitLine);

  const guide = document.createElement("div");
  guide.className = "measure-guide";
  guide.style.display = "none";
  preview.appendChild(guide);

  const handleLeft = document.createElement("button");
  handleLeft.type = "button";
  handleLeft.className = "card-crop-handle";
  handleLeft.style.left = "0";
  handleLeft.dataset.side = "left";
  handleLeft.setAttribute("aria-label", "向左移动裁剪左边界");
  const handleRight = document.createElement("button");
  handleRight.type = "button";
  handleRight.className = "card-crop-handle";
  handleRight.style.left = "100%";
  handleRight.dataset.side = "right";
  handleRight.setAttribute("aria-label", "向右移动裁剪右边界");
  const handleTop = document.createElement("button");
  handleTop.type = "button";
  handleTop.className = "card-crop-handle";
  handleTop.style.top = "0";
  handleTop.dataset.side = "top";
  handleTop.setAttribute("aria-label", "向上移动裁剪上边界");
  const handleBottom = document.createElement("button");
  handleBottom.type = "button";
  handleBottom.className = "card-crop-handle";
  handleBottom.style.top = "100%";
  handleBottom.dataset.side = "bottom";
  handleBottom.setAttribute("aria-label", "向下移动裁剪下边界");
  preview.appendChild(handleLeft);
  preview.appendChild(handleRight);
  preview.appendChild(handleTop);
  preview.appendChild(handleBottom);

  const shadeLeft = document.createElement("div");
  shadeLeft.className = "crop-shade";
  shadeLeft.dataset.side = "left";
  preview.appendChild(shadeLeft);
  const shadeRight = document.createElement("div");
  shadeRight.className = "crop-shade";
  shadeRight.dataset.side = "right";
  preview.appendChild(shadeRight);
  const shadeTop = document.createElement("div");
  shadeTop.className = "crop-shade";
  shadeTop.dataset.side = "top";
  preview.appendChild(shadeTop);
  const shadeBottom = document.createElement("div");
  shadeBottom.className = "crop-shade";
  shadeBottom.dataset.side = "bottom";
  preview.appendChild(shadeBottom);

  // 裁剪框左右竖直边线（与工作区裁剪窗一致的边框线）。
  const edgeLeft = document.createElement("div");
  edgeLeft.className = "crop-edge";
  edgeLeft.dataset.side = "left";
  preview.appendChild(edgeLeft);
  const edgeRight = document.createElement("div");
  edgeRight.className = "crop-edge";
  edgeRight.dataset.side = "right";
  preview.appendChild(edgeRight);
  const edgeTop = document.createElement("div");
  edgeTop.className = "crop-edge";
  edgeTop.dataset.side = "top";
  preview.appendChild(edgeTop);
  const edgeBottom = document.createElement("div");
  edgeBottom.className = "crop-edge";
  edgeBottom.dataset.side = "bottom";
  preview.appendChild(edgeBottom);

  // 左右裁剪边线位置的小节线（虚线，贯穿整张预览，与实线边框并存）。
  const measureLineLeft = document.createElement("div");
  measureLineLeft.className = "crop-measure-line";
  measureLineLeft.dataset.side = "left";
  preview.appendChild(measureLineLeft);
  const measureLineRight = document.createElement("div");
  measureLineRight.className = "crop-measure-line";
  measureLineRight.dataset.side = "right";
  preview.appendChild(measureLineRight);

  const strip = document.createElement("div");
  strip.className = "card-measure-strip";
  // 左裁剪边界：小节号（无圆形背景，不可删除）。
  const edge = document.createElement("span");
  edge.className = "measure-edge";
  edge.dataset.x = String(m.crop.l);
  edge.textContent = String(m.edgeLeftNum ?? "");
  strip.appendChild(edge);
  // 裁剪框内小节线：带圆圈编号；裁剪框外小节线：显示为 ×、不变号，均可删除。
  // 裁剪框内小节线：带圆圈编号；裁剪框外小节线：同一圆圈但显示为 ×、不可变号，均可删除。
  (m.measureItems || []).forEach((it) => {
    const num = document.createElement("span");
    num.className = "measure-num";
    num.dataset.x = String(it.x);
    if (it.num != null) {
      num.innerHTML = `<span class="measure-num-label">${it.num}</span><span class="measure-x">×</span>`;
    } else {
      num.textContent = "×";
      num.title = "删除此小节线";
    }
    num.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteMeasure(index, it.x);
    });
    strip.appendChild(num);
  });
  strip.addEventListener("click", (e) => {
    if (e.target === strip) addMeasure(index, strip, e);
  });
  strip.addEventListener("mousemove", (e) => {
    const r = strip.getBoundingClientRect();
    const p = clamp((e.clientX - r.left) / r.width, 0, 1);
    guide.style.display = "block";
    guide.style.left = `${p * 100}%`;
  });
  strip.addEventListener("mouseleave", () => {
    guide.style.display = "none";
  });

  col2.appendChild(strip);
  col2.appendChild(preview);

  // —— 列 3：清空/识别小节线 + 合并上下 + 横向分割 ——
  const col3 = document.createElement("div");
  col3.className = "card-col";
  const canSplit = Boolean(splitRatioBounds(m));
  const hasMeasures = Boolean(m.measures && m.measures.length);
  col3.appendChild(makeCardBtn(hasMeasures ? "clear" : "magic", hasMeasures ? "清空小节线" : "自动识别小节线", "clear", () => clearOrDetect(index)));
  col3.appendChild(makeCardBtn("arrowUp", "合并到上方", "merge", () => mergeCardUpward(index)));
  if (canSplit) {
    const splitBtn = document.createElement("button");
    splitBtn.type = "button";
    splitBtn.className = "split-btn";
    splitBtn.setAttribute("aria-label", "横向分割");
    const scissors = document.createElement("span");
    scissors.className = "split-scissors";
    scissors.innerHTML = iconSvg("scissors");
    splitBtn.appendChild(scissors);
    splitBtn.addEventListener("mousemove", (e) => previewSplitHover(splitLine, scissors, splitBtn, e));
    splitBtn.addEventListener("mouseleave", () => {
      splitLine.style.display = "none";
      scissors.style.top = "50%";
    });
    splitBtn.addEventListener("pointerdown", (e) => splitCard(index, splitBtn, e));
    col3.appendChild(splitBtn);
  }
  col3.appendChild(makeCardBtn("arrowDown", "合并到下方", "merge-down", () => mergeCardDownward(index)));

  card.appendChild(col1);
  card.appendChild(col2);
  card.appendChild(col3);

  // 四边裁剪：把手拖动 + 点击吸附最近边线。
  handleLeft.addEventListener("pointerdown", (e) => beginCardCrop(index, "left", e));
  handleRight.addEventListener("pointerdown", (e) => beginCardCrop(index, "right", e));
  handleTop.addEventListener("pointerdown", (e) => beginCardCrop(index, "top", e));
  handleBottom.addEventListener("pointerdown", (e) => beginCardCrop(index, "bottom", e));
  preview.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".card-crop-handle") || e.target.closest(".measure-line")) return;
    clickCardCrop(index, e);
  });

  // 拖放图片：拖到预览区域替换当前卡片图片，虚线框只加在裁剪区；拖到菜单按钮在下方插入。
  preview.addEventListener("dragover", (e) => {
    e.preventDefault();
    preview.classList.add("is-drop-target");
  });
  preview.addEventListener("dragleave", () => preview.classList.remove("is-drop-target"));
  preview.addEventListener("drop", (e) => {
    e.preventDefault();
    preview.classList.remove("is-drop-target");
    handleCardDrop(index, "replace", e);
  });
  menuBtn.addEventListener("dragover", (e) => {
    e.preventDefault();
    menuBtn.classList.add("is-drop-target");
  });
  menuBtn.addEventListener("dragleave", () => menuBtn.classList.remove("is-drop-target"));
  menuBtn.addEventListener("drop", (e) => {
    e.preventDefault();
    menuBtn.classList.remove("is-drop-target");
    handleCardDrop(index, "insert", e);
  });

  return card;
}

/* —— 卡片交互 —— */

function toggleHidden(index) {
  const m = state.images[index];
  if (!m) return;
  m.hidden = !m.hidden;
  syncCardList();
}

function openInsertModal(index) {
  state.insertIndex = index;
  els.insertModal.classList.remove("hidden");
  // 图片源没有原视频，不显示「从原视频插入」。
  els.insertDivider.classList.toggle("hidden", state.sourceType === "image");
  els.insertVideoButton.classList.toggle("hidden", state.sourceType === "image");
  els.insertFileInput.value = "";
}

function closeInsertModal() {
  els.insertModal.classList.add("hidden");
  state.insertIndex = null;
}

// —— 音符颜色选取弹窗 ——
function openNoteColorModal() {
  // 用第一张截图作为取样预览。
  const first = state.images[0];
  if (first && els.noteColorSampleImage) {
    els.noteColorSampleImage.src = first.url;
  }
  els.noteColorModal.classList.remove("hidden");
}

function closeNoteColorModal() {
  els.noteColorModal.classList.add("hidden");
}

function confirmNoteColor() {
  // 用选定颜色去色：折叠弹窗并展开 details。
  state.noteColorSelected = true;
  els.noteColorModal.classList.add("hidden");
  if (els.cleanDetails) els.cleanDetails.open = true;
  // 第三步去色后，第四步默认勾选着色。
  if (els.recolorInput) els.recolorInput.checked = true;
  updateCleanSummary();
  onCleanChange();
  syncRecolorOption();
}

async function insertFromVideo(index) {
  if (state.sourceType === "image") {
    showToast("图片源无法从原视频补插", "error");
    return;
  }
  if (state.inserting) return;
  const m = state.images[index];
  const next = state.images[index + 1];
  let tEnd;
  if (next) {
    if (!(next.t > m.t)) {
      showToast("未发现遗漏内容");
      return;
    }
    tEnd = next.t;
  } else {
    // 最后一张卡片也能向视频/提取区间末尾补插。
    tEnd = resolvedEndTime();
    if (!Number.isFinite(tEnd) || tEnd - m.t < 0.1) {
      showToast("已经是最后一张，无法在下方插入", "error");
      return;
    }
  }
  state.inserting = true;
  showToast("正在插入...");
  try {
    const data = await fetchJson("/api/insert_captures", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ job_id: state.captureJobId, t_start: m.t, t_end: tEnd, index: index + 1 }),
    });
    const inserted = data.captures || [];
    if (!inserted.length) {
      showToast("未发现遗漏内容");
      return;
    }
    const newImgs = inserted.map((c) => ({
      file: c.file,
      url: c.url,
      t: c.t ?? 0,
      w: c.w,
      h: c.h,
      hidden: false,
      flash: true,
      crop: { l: 0, r: 1, t: 0, b: 1 },
      measures: [],
    }));
    state.images.splice(index + 1, 0, ...newImgs);
    await detectMeasuresFor(newImgs.map((c) => c.file));
    renderCardList();
    showToast(`已插入 ${inserted.length} 张图片`, "success");
  } catch (e) {
    showToast(e.message, "error");
  } finally {
    state.inserting = false;
  }
}

function insertFromFile(index) {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/*";
  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (file) await uploadAndInsert(index, file);
  });
  input.click();
}

async function insertFromClipboard(index) {
  try {
    const items = await navigator.clipboard.read();
    for (const item of items) {
      const type = item.types.find((t) => t.startsWith("image/"));
      if (type) {
        const blob = await item.getType(type);
        await uploadAndInsert(index, blob);
        return;
      }
    }
    showToast("剪贴板没有图片", "error");
  } catch (e) {
    showToast("无法读取剪贴板：" + e.message, "error");
  }
}

async function uploadImageFile(fileOrBlob) {
  const fd = new FormData();
  fd.append("job_id", state.captureJobId);
  fd.append("file", fileOrBlob, fileOrBlob.name || "untitled.png");
  return fetchJson("/api/import_image", { method: "POST", body: fd });
}

async function uploadAndInsert(index, fileOrBlob) {
  showToast("正在上传图片...");
  try {
    const data = await uploadImageFile(fileOrBlob);
    const newImg = {
      file: data.file,
      url: data.url,
      t: 0,
      w: data.w,
      h: data.h,
      hidden: false,
      flash: true,
      crop: { l: 0, r: 1, t: 0, b: 1 },
      measures: [],
    };
    state.images.splice(index + 1, 0, newImg);
    await detectMeasuresFor([data.file]);
    renderCardList();
    showToast("已插入图片", "success");
  } catch (e) {
    showToast(e.message, "error");
  }
}

async function insertLocalFiles(index, files) {
  files = Array.from(files || []).filter(Boolean);
  if (!files.length) return;
  showToast("正在上传图片...");
  const inserted = [];
  try {
    for (let k = 0; k < files.length; k++) {
      const data = await uploadImageFile(files[k]);
      state.images.splice(index + 1 + k, 0, {
        file: data.file,
        url: data.url,
        t: 0,
        w: data.w,
        h: data.h,
        hidden: false,
        flash: true,
        crop: { l: 0, r: 1, t: 0, b: 1 },
        measures: [],
      });
      inserted.push(data.file);
    }
    await detectMeasuresFor(inserted);
    renderCardList();
    showToast(`已插入 ${inserted.length} 张图片`, "success");
    closeInsertModal();
  } catch (e) {
    showToast(e.message, "error");
  }
}

async function replaceCardImage(index, file) {
  showToast("正在替换图片...");
  try {
    const fd = new FormData();
    fd.append("job_id", state.captureJobId);
    fd.append("file", file, file.name);
    const data = await fetchJson("/api/import_image", { method: "POST", body: fd });
    const m = state.images[index];
    m.file = data.file;
    m.url = data.url;
    m.w = data.w;
    m.h = data.h;
    m.crop = { l: 0, r: 1, t: 0, b: 1 };
    m.measures = [];
    await detectMeasuresFor([data.file]);
    renderCardList();
    showToast("已替换图片", "success");
  } catch (e) {
    showToast(e.message, "error");
  }
}

async function handleCardDrop(index, mode, event) {
  const file = Array.from(event.dataTransfer?.files || []).find((f) => f.type && f.type.startsWith("image/"));
  if (!file) {
    showToast("请拖入图片文件", "error");
    return;
  }
  if (mode === "replace") {
    await replaceCardImage(index, file);
  } else {
    await uploadAndInsert(index, file);
  }
}

/* —— 卡片拖动排序 —— */
let sortDrag = null;
let sortScrollRaf = null;
const SORT_SCROLL_EDGE = 90; // 靠近视口上下边缘多少 px 内触发自动滚动
const SORT_SCROLL_MAX = 22;  // 单帧最大滚动步长（px）

function sortScrollTick() {
  if (!sortDrag) {
    sortScrollRaf = null;
    return;
  }
  const y = sortDrag.clientY;
  const top = y;
  const bottom = window.innerHeight - y;
  let step = 0;
  if (top < SORT_SCROLL_EDGE) {
    step = -Math.round(SORT_SCROLL_MAX * ((SORT_SCROLL_EDGE - top) / SORT_SCROLL_EDGE));
  } else if (bottom < SORT_SCROLL_EDGE) {
    step = Math.round(SORT_SCROLL_MAX * ((SORT_SCROLL_EDGE - bottom) / SORT_SCROLL_EDGE));
  }
  if (step) window.scrollBy(0, step);
  sortScrollRaf = requestAnimationFrame(sortScrollTick);
}

function beginCardSort(index, card, event) {
  event.preventDefault();
  sortDrag = {
    from: index,
    to: null,
    toObj: null,
    startX: event.clientX,
    startY: event.clientY,
    clientX: event.clientX,
    clientY: event.clientY,
    moved: false,
  };
  card.classList.add("is-sorting");
  event.currentTarget.setPointerCapture?.(event.pointerId);
  sortScrollRaf = requestAnimationFrame(sortScrollTick);
}

function cardIndexAtPoint(clientX, clientY) {
  const cards = els.cardList.querySelectorAll(".card");
  for (const c of cards) {
    const r = c.getBoundingClientRect();
    if (clientX >= r.left && clientX <= r.right && clientY >= r.top && clientY <= r.bottom) {
      return Number(c.dataset.index);
    }
  }
  return null;
}

function dragCardSort(event) {
  if (!sortDrag) return;
  sortDrag.clientX = event.clientX;
  sortDrag.clientY = event.clientY;
  if (!sortDrag.moved && Math.abs(event.clientX - sortDrag.startX) + Math.abs(event.clientY - sortDrag.startY) > 4) {
    sortDrag.moved = true;
  }
  els.cardList.querySelectorAll(".card.is-drop-target").forEach((c) => c.classList.remove("is-drop-target"));
  const target = cardIndexAtPoint(event.clientX, event.clientY);
  if (sortDrag.moved && target != null && target !== sortDrag.from) {
    sortDrag.to = target;
    sortDrag.toObj = state.images[target];
    // 高亮当前悬浮的目标卡片（松开即移动到该卡片的位置）。
    const cards = els.cardList.querySelectorAll(".card");
    cards.forEach((c) => {
      if (Number(c.dataset.index) === target) c.classList.add("is-drop-target");
    });
  } else {
    sortDrag.to = null;
    sortDrag.toObj = null;
  }
}

function endCardSort() {
  if (!sortDrag) return;
  const { from, to, toObj, moved } = sortDrag;
  if (moved && toObj && toObj !== state.images[from]) {
    const [movedImg] = state.images.splice(from, 1);
    const targetIdx = state.images.indexOf(toObj);
    if (targetIdx >= 0) {
      // 目标卡片在移除后，若原本在下方则上移了一位，需 +1 落回其原位置。
      const insertAt = from < to ? targetIdx + 1 : targetIdx;
      state.images.splice(insertAt, 0, movedImg);
    }
  } else if (!moved) {
    showToast("按住拖动卡片到目标位置进行排序");
  }
  sortDrag = null;
  if (sortScrollRaf) cancelAnimationFrame(sortScrollRaf);
  sortScrollRaf = null;
  renderCardList();
}

/* —— 卡片水平裁剪 —— */
const CARD_MIN_CROP = 0.02;
const CARD_MIN_CROP_V = 0.2; // 上下裁剪的最小高度（图片高度的百分比）
const MIN_SPLIT_PX = 30; // 横向分割的最小高度（绝对像素），两段各自都不能低于该值
let cardDrag = null;

// 返回可分割的归一化比例区间 [min, max]；图片高度不足 2×MIN_SPLIT_PX 时返回 null。
function splitRatioBounds(m) {
  const h = m && m.h ? m.h : 0;
  if (!h || h < MIN_SPLIT_PX * 2) return null;
  return { min: MIN_SPLIT_PX / h, max: 1 - MIN_SPLIT_PX / h };
}

function cropValueFor(crop, side) {
  if (side === "left") return crop.l;
  if (side === "right") return crop.r;
  if (side === "top") return crop.t ?? 0;
  return crop.b ?? 1;
}

function beginCardCrop(index, side, event) {
  const m = state.images[index];
  if (!m) return;
  event.preventDefault();
  event.stopPropagation();
  const preview = event.currentTarget.closest(".card-preview");
  const rect = preview.getBoundingClientRect();
  preview.classList.add("is-cropping");
  cardDrag = {
    index,
    side,
    startX: event.clientX,
    startY: event.clientY,
    startValue: cropValueFor(m.crop, side),
    pxWidth: rect.width || 1,
    pxHeight: rect.height || 1,
  };
}

function clickCardCrop(index, event) {
  const m = state.images[index];
  if (!m) return;
  event.preventDefault();
  const rect = event.currentTarget.getBoundingClientRect();
  const px = clamp((event.clientX - rect.left) / rect.width, 0, 1);
  // 点击仅吸附到最近的左右边线（上下边线只能拖把手，不参与吸附）。
  const side = Math.abs(px - m.crop.l) <= Math.abs(px - m.crop.r) ? "left" : "right";
  const startValue = side === "left"
    ? clamp(px, 0, m.crop.r - CARD_MIN_CROP)
    : clamp(px, m.crop.l + CARD_MIN_CROP, 1);
  cardDrag = {
    index,
    side,
    startX: event.clientX,
    startY: event.clientY,
    startValue,
    pxWidth: rect.width || 1,
    pxHeight: rect.height || 1,
  };
  event.currentTarget.classList.add("is-cropping");
  applyCardCropValue(index, side, startValue);
}

function applyCardCropValue(index, side, val) {
  const m = state.images[index];
  if (side === "left") {
    m.crop.l = clamp(val, 0, m.crop.r - CARD_MIN_CROP);
  } else if (side === "right") {
    m.crop.r = clamp(val, m.crop.l + CARD_MIN_CROP, 1);
  } else if (side === "top") {
    m.crop.t = clamp(val, 0, (m.crop.b ?? 1) - CARD_MIN_CROP_V);
  } else {
    m.crop.b = clamp(val, (m.crop.t ?? 0) + CARD_MIN_CROP_V, 1);
  }
  const cardEl = els.cardList.querySelector(`.card[data-index="${index}"]`);
  if (cardEl) applyCardCropVisual(cardEl, m);
}

function dragCardCrop(event) {
  if (!cardDrag) return;
  const vertical = cardDrag.side === "top" || cardDrag.side === "bottom";
  const delta = vertical
    ? (event.clientY - cardDrag.startY) / cardDrag.pxHeight
    : (event.clientX - cardDrag.startX) / cardDrag.pxWidth;
  applyCardCropValue(cardDrag.index, cardDrag.side, cardDrag.startValue + delta);
}

function endCardCrop() {
  if (!cardDrag) return;
  cardDrag = null;
  syncCardList();
}

/* —— 横向分割 —— */
function previewSplitHover(splitLine, scissors, splitBtn, event) {
  const card = splitBtn.closest(".card");
  const preview = card ? card.querySelector(".card-preview") : null;
  const m = card ? state.images[Number(card.dataset.index)] : null;
  const b = splitRatioBounds(m);
  if (!b || !preview) {
    splitLine.style.display = "none";
    return;
  }
  // 分割线按预览图（整图）定位；剪刀图标按 split-btn 自身定位，二者都落在鼠标所在的
  // 绝对纵向位置，保证分割线与剪刀图标在同一水平线上。
  const pr = preview.getBoundingClientRect();
  const ratio = clamp((event.clientY - pr.top) / pr.height, b.min, b.max);
  const sr = splitBtn.getBoundingClientRect();
  scissors.style.top = `${clamp((event.clientY - sr.top) / sr.height, 0, 1) * 100}%`;
  splitLine.style.display = "block";
  splitLine.style.top = `${ratio * 100}%`;
}

async function splitCard(index, splitBtn, event) {
  const m = state.images[index];
  if (!m) return;
  const b = splitRatioBounds(m);
  if (!b) {
    showToast("图片高度不足，无法继续分割", "error");
    return;
  }
  const preview = splitBtn.closest(".card")?.querySelector(".card-preview");
  const rect = preview ? preview.getBoundingClientRect() : splitBtn.getBoundingClientRect();
  const ratio = clamp((event.clientY - rect.top) / rect.height, b.min, b.max);
  showToast("正在分割...");
  try {
    const data = await fetchJson("/api/split_image", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ job_id: state.captureJobId, file: m.file, y: ratio }),
    });
    const parts = data.parts || [];
    if (parts.length !== 2) {
      showToast("分割失败", "error");
      return;
    }
    const newCards = parts.map((p) => ({
      file: p.file,
      url: p.url,
      t: m.t,
      w: p.w,
      h: p.h,
      hidden: false,
      flash: true,
      crop: { l: 0, r: 1, t: 0, b: 1 },
      measures: [],
    }));
    state.images.splice(index, 1, ...newCards);
    await detectMeasuresFor([newCards[0].file, newCards[1].file]);
    renderCardList();
    showToast("已分割为两张图片", "success");
  } catch (e) {
    showToast(e.message, "error");
  }
}

/* 高度不足时：合并到上方（与上一张截图纵向拼接成一张）。 */
async function mergeCardUpward(index) {
  const m = state.images[index];
  const above = state.images[index - 1];
  if (!m || !above) {
    showToast("没有上方图片可合并", "error");
    return;
  }
  showToast("正在合并...");
  try {
    const data = await fetchJson("/api/merge_image", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ job_id: state.captureJobId, top: above.file, bottom: m.file }),
    });
    const merged = {
      file: data.file,
      url: data.url,
      t: above.t,
      w: data.w,
      h: data.h,
      hidden: above.hidden,
      flash: true,
      crop: { l: 0, r: 1, t: 0, b: 1 },
      measures: [],
    };
    state.images.splice(index - 1, 2, merged);
    await detectMeasuresFor([data.file]);
    renderCardList();
    showToast("已合并到上方", "success");
  } catch (e) {
    showToast(e.message, "error");
  }
}

/* 高度不足时：合并到下方（与下一张截图纵向拼接成一张）。 */
async function mergeCardDownward(index) {
  const m = state.images[index];
  const below = state.images[index + 1];
  if (!m || !below) {
    showToast("没有下方图片可合并", "error");
    return;
  }
  showToast("正在合并...");
  try {
    const data = await fetchJson("/api/merge_image", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ job_id: state.captureJobId, top: m.file, bottom: below.file }),
    });
    const merged = {
      file: data.file,
      url: data.url,
      t: m.t,
      w: data.w,
      h: data.h,
      hidden: m.hidden,
      flash: true,
      crop: { l: 0, r: 1, t: 0, b: 1 },
      measures: [],
    };
    state.images.splice(index, 2, merged);
    await detectMeasuresFor([data.file]);
    renderCardList();
    showToast("已合并到下方", "success");
  } catch (e) {
    showToast(e.message, "error");
  }
}

/* —— 小节线增删 —— */
function addMeasure(index, strip, event) {
  const m = state.images[index];
  if (!m) return;
  const rect = strip.getBoundingClientRect();
  const p = clamp((event.clientX - rect.left) / rect.width, 0, 1);
  m.measures = m.measures || [];
  m.measures.push(p);
  m.measures.sort((a, b) => a - b);
  syncCardList();
}

function deleteMeasure(index, x) {
  const m = state.images[index];
  if (!m) return;
  m.measures = (m.measures || []).filter((mm) => Math.abs(mm - x) > 1e-6);
  syncCardList();
}

function clearOrDetect(index) {
  const m = state.images[index];
  if (!m) return;
  if (m.measures && m.measures.length) {
    m.measures = [];
    syncCardList();
  } else {
    showToast("正在识别……");
    detectMeasuresFor([m.file]).then(() => {
      syncCardList();
      showToast("已自动识别小节线", "success");
    });
  }
}

/* ===================== 第 4 步：排版 ===================== */

function layoutMeasurePages(headerH) {
  const opts = currentLayoutOpts();
  let pageW = PAGE_W;
  let pageH = PAGE_H;
  if (opts.orientation === "landscape") {
    pageW = PAGE_H;
    pageH = PAGE_W;
  }
  const contentW = pageW - 2 * opts.margin;
  const hasHeader = headerH != null;
  const firstY = hasHeader ? headerH : opts.margin;

  const pages = [];
  let page = null;
  let y = 0;
  let rowH = 0;
  let rowItems = []; // 当前行内的小节项引用
  let rowUsed = 0;   // 当前行已占用的宽度（不含间隙）

  const flushRow = () => {
    if (!rowItems.length) return;
    let offset = 0;
    if (opts.align === "center" && rowUsed < contentW) offset = Math.floor((contentW - rowUsed) / 2);
    else if (opts.align === "right" && rowUsed < contentW) offset = contentW - rowUsed;
    let px = opts.margin + offset;
    for (const it of rowItems) {
      it.x = px;
      if (opts.valign === "center") it.y += Math.floor((rowH - it.h) / 2);
      else if (opts.valign === "bottom") it.y += rowH - it.h;
      px += it.w;
    }
    rowItems = [];
    rowUsed = 0;
  };

  const startPage = (first) => {
    page = { first, items: [] };
    pages.push(page);
    y = first ? firstY : opts.margin;
    rowH = 0;
    rowItems = [];
    rowUsed = 0;
  };
  startPage(true);

  state.images.forEach((m) => {
    if (m.hidden) return;
    const l = m.crop.l;
    const r = m.crop.r;
    const t = m.crop.t ?? 0;
    const b = m.crop.b ?? 1;
    const fullW = (m.w || 1) * opts.scale;
    const fullH = (m.h || 1) * opts.scale;
    const interior = (m.measures || [])
      .filter((mm) => mm > l + MEASURE_EPS && mm < r - MEASURE_EPS)
      .sort((a, b) => a - b);
    const bounds = [l, ...interior, r];

    for (let bi = 0; bi < bounds.length - 1; bi++) {
      let w = (bounds[bi + 1] - bounds[bi]) * fullW;
      let h = fullH * (b - t);
      // 单张图若比整行内容宽（已顶满纸张减页边距后的宽度），
      // 则不再放得更大：按比例缩到内容宽度 contentW。
      let fit = 1;
      if (w > contentW) {
        fit = contentW / w;
        w = contentW;
        h = Math.round(h * fit);
      }
      // 放不下则换行：先确定上一行的横向位置。
      if (rowItems.length && rowUsed + w > contentW) {
        flushRow();
        y += rowH + opts.spacing;
        rowH = 0;
      }
      // 换行后仍放不下则翻页。
      if (y + h + opts.margin + FOOTER_H > pageH) {
        flushRow();
        startPage(false);
      }
      const item = { m, leftNorm: bounds[bi], rightNorm: bounds[bi + 1], topNorm: t, bottomNorm: b, w, h, x: 0, y, fit };
      page.items.push(item);
      rowItems.push(item);
      rowUsed += w;
      rowH = Math.max(rowH, h);
    }
  });
  flushRow();

  return { pages, pageW, pageH, opts };
}

function buildStrip(item, opts, scale) {
  const { m, leftNorm, rightNorm, topNorm, bottomNorm, w, h, x, y, fit = 1 } = item;
  const wrap = document.createElement("div");
  wrap.className = "strip-item";
  wrap.style.left = `${x * scale}px`;
  wrap.style.top = `${y * scale}px`;
  wrap.style.width = `${w * scale}px`;
  wrap.style.height = `${h * scale}px`;

  const fullW = (m.w || 1) * opts.scale * fit;
  const fullH = (m.h || 1) * opts.scale * fit;
  const img = document.createElement("img");
  img.className = "strip-img";
  img.src = step4Src(m);
  img.alt = "";
  img.draggable = false;
  img.style.left = `${-(leftNorm * fullW) * scale}px`;
  img.style.top = `${-(topNorm * fullH) * scale}px`;
  img.style.width = `${fullW * scale}px`;
  img.style.height = `${fullH * scale}px`;
  wrap.appendChild(img);
  return wrap;
}

function renderHeaderEl(opts, scale) {
  if (!opts.titleLines.length && !opts.url) return null;
  const header = document.createElement("div");
  header.className = "page-header";
  header.style.padding = `${Math.round((opts.margin + opts.titleSpacing) * scale)}px ${Math.round(opts.margin * scale)}px 0 ${Math.round(opts.margin * scale)}px`;
  const titleSize = Math.round(HEADER_TITLE_SIZE * scale);
  opts.titleLines.forEach((ln, i) => {
    const el = document.createElement("div");
    el.className = i === 0 ? "page-title" : "page-channel";
    el.textContent = ln;
    el.style.fontSize = `${Math.round(i === 0 ? titleSize : titleSize * 0.4375)}px`;
    if (i > 0) el.style.marginTop = `${Math.round(8 * scale)}px`;
    header.appendChild(el);
  });
  if (opts.url) {
    const urlEl = document.createElement("div");
    urlEl.className = "page-url";
    urlEl.textContent = opts.url;
    urlEl.style.fontSize = `${Math.round(titleSize * 0.25)}px`;
    urlEl.style.marginTop = `${Math.round(12 * scale)}px`;
    header.appendChild(urlEl);
  }
  return header;
}

// 用真实 DOM 测量页头高度（含 CSS line-height 与换行），换算回页面单位，
// 使预览的首图起始 Y 与后端 draw_first_page_header 严格一致。
function measureHeaderHeightPx(opts, scale, cssW) {
  const header = renderHeaderEl(opts, scale);
  if (!header) return null;
  const host = document.createElement("div");
  host.style.cssText = "position:absolute;visibility:hidden;pointer-events:none;left:-9999px;top:0;";
  host.style.width = `${cssW}px`;
  host.appendChild(header);
  document.body.appendChild(host);
  const fullH = header.getBoundingClientRect().height;
  const paddingTop = (opts.margin + opts.titleSpacing) * scale;
  const contentH = Math.max(0, fullH - paddingTop) / scale;
  host.remove();
  return Math.round(opts.titleSpacing + contentH + opts.titleSpacing);
}

function renderPages() {
  if (!els.pageList) return;
  if (state.stage !== 4) return;
  const opts = currentLayoutOpts();
  const pageW = opts.orientation === "landscape" ? PAGE_H : PAGE_W;
  const cssW = currentPageCssWidth();
  const scale = cssW / pageW;
  const headerH = measureHeaderHeightPx(opts, scale, cssW);
  const { pages, pageH } = layoutMeasurePages(headerH);
  const scrollY = window.scrollY;
  els.pageList.style.gridTemplateColumns = currentPreviewCols() === 2 ? "repeat(2, minmax(0, 1fr))" : "";
  els.pageList.innerHTML = "";

  pages.forEach((page, pi) => {
    const pageEl = document.createElement("div");
    pageEl.className = "page";
    pageEl.style.width = `${cssW}px`;
    pageEl.style.height = `${Math.round(pageH * scale)}px`;
    pageEl.style.background = opts.bgColor;
    pageEl.style.color = opts.textColor;

    if (page.first && (opts.titleLines.length || opts.url)) {
      pageEl.appendChild(renderHeaderEl(opts, scale));
    }

    page.items.forEach((item) => pageEl.appendChild(buildStrip(item, opts, scale)));

    const footer = document.createElement("div");
    footer.className = "page-footer";
    footer.style.position = "absolute";
    footer.style.bottom = "0";
    footer.style.left = "0";
    footer.style.right = "0";
    footer.style.height = `${Math.round(FOOTER_H * scale)}px`;
    footer.textContent = `${pi + 1} / ${pages.length}`;
    pageEl.appendChild(footer);

    els.pageList.appendChild(pageEl);
  });

  if (Math.abs(window.scrollY - scrollY) > 1) window.scrollTo(0, scrollY);

  state.images.forEach((m) => {
    m.flash = false;
  });
}

function firstTitleLine() {
  return (
    (els.titleArea.value || "")
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)[0] || ""
  );
}

function layoutPayload() {
  return {
    job_id: state.captureJobId,
    images: state.images
      .filter((m) => !m.hidden)
      .map((m) => ({
        file: m.file,
        crop: { l: m.crop.l, r: m.crop.r, t: m.crop.t ?? 0, b: m.crop.b ?? 1 },
        measures: m.measures || [],
      })),
    margin: numericValue(els.pageMargin, 40),
    spacing: numericValue(els.imageSpacing, 25),
    title_spacing: numericValue(els.titleSpacing, 130),
    scale: numericValue(els.scaleInput, 1),
    orientation: currentOrientation(),
    align: currentAlign(),
    valign: currentValign(),
    bg_color: els.bgColor.value || "#ffffff",
    text_color: els.textColor.value || "#181818",
    binarize: !!(state.noteColorSelected && els.recolorInput && els.recolorInput.checked),
    invert: els.invertInput.checked,
    note_color: els.noteColor.value || "#000000",
    tolerance: numericValue(els.tolerance, 60),
    softness: numericValue(els.softness, 20),
    title: els.titleArea.value,
    output: firstTitleLine() || "tablatura.pdf",
  };
}

function setGenerating(busy, text) {
  state.generating = busy;
  els.generateProgressWrap.classList.toggle("hidden", !busy);
  els.progressText.textContent = text || "";
  setControlBusy([els.downloadPdfButton, els.downloadLongButton], busy);
}

function triggerDownload(url, name) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name || "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function downloadPdf() {
  const payload = layoutPayload();
  if (!payload.images.length) {
    setStatus(els.layoutStatus, "没有可导出的截图。", "error");
    return;
  }
  if (state.generating) return;
  setGenerating(true, "正在生成 PDF…");
  setStatus(els.layoutStatus, "");
  try {
    const data = await fetchJson("/api/pdf", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    });
    triggerDownload(data.pdf_url, data.pdf_name);
    setStatus(els.layoutStatus, `PDF 已生成（${data.page_count} 页）。`, "success");
  } catch (e) {
    setStatus(els.layoutStatus, e.message, "error");
  } finally {
    setGenerating(false);
  }
}

async function downloadLongImage() {
  const payload = layoutPayload();
  if (!payload.images.length) {
    setStatus(els.layoutStatus, "没有可导出的截图。", "error");
    return;
  }
  if (state.generating) return;
  setGenerating(true, "正在生成长图…");
  setStatus(els.layoutStatus, "");
  try {
    const data = await fetchJson("/api/long_image", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    });
    triggerDownload(data.long_url, data.long_name);
    setStatus(els.layoutStatus, "长图已生成。", "success");
  } catch (e) {
    setStatus(els.layoutStatus, e.message, "error");
  } finally {
    setGenerating(false);
  }
}

/* ===================== 轮询与生成 ===================== */

async function pollJob(jobId) {
  try {
    const job = await fetchJson(`/api/jobs/${jobId}`);
    renderJob(job);
    return job;
  } catch (error) {
    setStatus(els.extractStatus, error.message, "error");
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    els.generateButton.disabled = false;
    return null;
  }
}

async function generateCaptures() {
  if (!state.sourceId) {
    setStatus(els.extractStatus, "请先导入视频或图片。", "error");
    return;
  }

  clearStatuses();
  els.generateButton.disabled = true;
  setExtractProgress(null, "排队中...");
  setStatus(els.extractStatus, "开始处理...");
  try {
    const data = await fetchJson("/api/captures", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(buildExtractPayload()),
    });
    state.captureJobId = data.job_id;
    const firstJob = await pollJob(data.job_id);
    if (firstJob && !["done", "error"].includes(firstJob.status)) {
      state.pollTimer = setInterval(() => pollJob(data.job_id), 1000);
    }
  } catch (error) {
    hideExtractProgress();
    setStatus(els.extractStatus, error.message, "error");
    showToast(error.message, "error");
    els.generateButton.disabled = false;
  }
}

/* ===================== 事件绑定 ===================== */

els.importForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.importing) return;

  const formData = new FormData(els.importForm);
  setImportLoading(true);
  setStatus(els.importStatus, "正在读取信息...");
  try {
    const source = await fetchJson("/api/import", {
      method: "POST",
      body: formData,
    });
    applySource(source);
    const needPreview = !source.restore && !(source.download && source.download.status === "downloading");
    if (needPreview) {
      setStatus(els.importStatus, "已导入。", "success");
    }
  } catch (error) {
    setStatus(els.importStatus, error.message, "error");
  } finally {
    setImportLoading(false);
  }
});

els.startMinInput.addEventListener("change", updateTimeline);
els.startSecInput.addEventListener("change", updateTimeline);
els.endMinInput.addEventListener("change", updateTimeline);
els.endSecInput.addEventListener("change", updateTimeline);

function updateFileHint() {
  const file = els.localFile.files && els.localFile.files[0];
  els.fileHint.textContent = file ? file.name : "本地视频或图片";
}

els.bvidInput.addEventListener("input", () => {
  if (els.bvidInput.value.trim()) {
    els.localFile.value = "";
    updateFileHint();
  }
});

els.localFile.addEventListener("change", () => {
  if (els.localFile.files.length > 0) {
    els.bvidInput.value = "";
    els.importForm.requestSubmit();
  }
  updateFileHint();
});

function isImportableFile(file) {
  if (!file) return false;
  if (file.type && (file.type.startsWith("video/") || file.type.startsWith("image/"))) return true;
  return /\.(mp4|mov|mkv|webm|png|jpe?g|webp|bmp|gif)$/i.test(file.name);
}

let fileDragDepth = 0;

els.fileField.addEventListener("dragenter", (event) => {
  event.preventDefault();
  event.stopPropagation();
  fileDragDepth += 1;
  els.fileField.classList.add("is-dragover");
});

els.fileField.addEventListener("dragover", (event) => {
  event.preventDefault();
  event.stopPropagation();
});

els.fileField.addEventListener("dragleave", (event) => {
  event.preventDefault();
  event.stopPropagation();
  fileDragDepth -= 1;
  if (fileDragDepth <= 0) {
    fileDragDepth = 0;
    els.fileField.classList.remove("is-dragover");
  }
});

els.fileField.addEventListener("drop", (event) => {
  event.preventDefault();
  event.stopPropagation();
  fileDragDepth = 0;
  els.fileField.classList.remove("is-dragover");
  if (state.importing) return;

  const file = Array.from(event.dataTransfer.files).find(isImportableFile);
  if (!file) {
    setStatus(els.importStatus, "请拖入视频（MP4/MOV/WebM/MKV）或图片（PNG/JPG/WebP/BMP/GIF）。", "error");
    return;
  }

  const dataTransfer = new DataTransfer();
  dataTransfer.items.add(file);
  els.localFile.files = dataTransfer.files;
  els.localFile.dispatchEvent(new Event("change"));
});

// 第 1 步：Ctrl+V 从剪贴板导入图片；第 3 步插入弹窗打开时：插入到目标卡片下方。
document.addEventListener("paste", (event) => {
  const item = Array.from(event.clipboardData?.items || []).find((i) => i.type && i.type.startsWith("image/"));
  if (!item) return;
  const blob = item.getAsFile();
  if (!blob) return;

  if (state.stage === 1) {
    event.preventDefault();
    const file = new File([blob], "untitled.png", { type: blob.type || "image/png" });
    const dt = new DataTransfer();
    dt.items.add(file);
    els.localFile.files = dt.files;
    els.localFile.dispatchEvent(new Event("change"));
  } else if (state.stage === 3 && state.insertIndex != null && !els.insertModal.classList.contains("hidden")) {
    event.preventDefault();
    const file = new File([blob], "untitled.png", { type: blob.type || "image/png" });
    insertLocalFiles(state.insertIndex, [file]);
  }
});

function setLoggedIn(loggedIn) {
  state.bilibiliLoggedIn = loggedIn;
  els.bilibiliLoginButton.textContent = loggedIn ? "退出登录" : "登录高清";
}

function stopLoginPolling() {
  if (state.loginPollTimer) {
    clearInterval(state.loginPollTimer);
    state.loginPollTimer = null;
  }
}

function renderLoginStatus(data) {
  if (data.qr) {
    els.loginQrImage.src = data.qr;
    setStatus(els.loginStatus, data.message || "请用手机扫码。");
  }

  if (data.status === "success") {
    stopLoginPolling();
    els.loginQrImage.removeAttribute("src");
    els.loginModal.classList.add("hidden");
    setLoggedIn(true);
    setStatus(els.loginStatus, data.message || "已登录。", "success");
  } else if (data.status === "error") {
    stopLoginPolling();
    els.loginQrImage.removeAttribute("src");
    setStatus(els.loginStatus, data.message || "登录失败。", "error");
  }
}

async function pollBilibiliLogin() {
  try {
    const data = await fetchJson("/api/bilibili/login");
    renderLoginStatus(data);
    return data.status;
  } catch (error) {
    stopLoginPolling();
    setStatus(els.loginStatus, error.message, "error");
    return "error";
  }
}

els.bilibiliLoginButton.addEventListener("click", async () => {
  if (state.bilibiliLoggedIn) {
    els.bilibiliLoginButton.disabled = true;
    try {
      await fetchJson("/api/bilibili/logout", { method: "POST" });
      setLoggedIn(false);
      stopLoginPolling();
      els.loginModal.classList.add("hidden");
      els.loginQrImage.removeAttribute("src");
      setStatus(els.loginStatus, "已退出登录。");
    } catch (error) {
      setStatus(els.loginStatus, error.message, "error");
    } finally {
      els.bilibiliLoginButton.disabled = false;
    }
    return;
  }

  els.bilibiliLoginButton.disabled = true;
  els.loginModal.classList.remove("hidden");
  setStatus(els.loginStatus, "正在开始登录...");
  try {
    await fetchJson("/api/bilibili/login", { method: "POST" });
  } catch (error) {
    setStatus(els.loginStatus, error.message, "error");
    els.bilibiliLoginButton.disabled = false;
    return;
  }
  els.bilibiliLoginButton.disabled = false;
  stopLoginPolling();
  const status = await pollBilibiliLogin();
  if (status !== "success" && status !== "error") {
    state.loginPollTimer = setInterval(pollBilibiliLogin, 1500);
  }
});

// 登录弹窗关闭。
els.loginModalClose.addEventListener("click", () => {
  els.loginModal.classList.add("hidden");
  stopLoginPolling();
});
els.loginModal.addEventListener("click", (e) => {
  if (e.target === els.loginModal) {
    els.loginModal.classList.add("hidden");
    stopLoginPolling();
  }
});

els.cropTop.addEventListener("pointerdown", (event) => beginDrag("top", event));
els.cropBottom.addEventListener("pointerdown", (event) => beginDrag("bottom", event));
els.cropLeft.addEventListener("pointerdown", (event) => beginDrag("left", event));
els.cropRight.addEventListener("pointerdown", (event) => beginDrag("right", event));
els.previewFrame.addEventListener("pointerdown", clickCrop);
window.addEventListener("pointermove", dragCrop);
window.addEventListener("pointerup", endDrag);
window.addEventListener("pointercancel", endDrag);

// 预览框随视频真实比例变化：横屏宽度顶满容器，竖屏按高度限制。
let previewNaturalW = 0;
let previewNaturalH = 0;

function fitPreviewFrame() {
  if (!previewNaturalW || !previewNaturalH) return;
  const parent = els.previewFrame.parentElement;
  const cs = getComputedStyle(parent);
  const containerW = parent.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const maxH = Math.min(720, Math.round(window.innerHeight * 0.75));
  const ratio = previewNaturalW / previewNaturalH;
  let frameW, frameH;
  if (ratio >= 1) {
    frameW = containerW;
    frameH = Math.round(containerW / ratio);
  } else {
    frameH = maxH;
    frameW = Math.round(maxH * ratio);
  }
  els.previewFrame.style.width = `${frameW}px`;
  els.previewFrame.style.height = `${frameH}px`;
}

els.previewImage.addEventListener("load", () => {
  previewNaturalW = els.previewImage.naturalWidth;
  previewNaturalH = els.previewImage.naturalHeight;
  fitPreviewFrame();
});

// 卡片裁剪 / 拖动排序的全局拖动监听。
window.addEventListener("pointermove", dragCardCrop);
window.addEventListener("pointerup", endCardCrop);
window.addEventListener("pointercancel", endCardCrop);
window.addEventListener("pointermove", dragCardSort);
window.addEventListener("pointerup", endCardSort);
window.addEventListener("pointercancel", endCardSort);

els.timeline.addEventListener("pointerdown", beginTimelineTrackDrag);
els.timelineStartHandle.addEventListener("pointerdown", (event) => beginTimelineDrag("start", event));
els.timelineEndHandle.addEventListener("pointerdown", (event) => beginTimelineDrag("end", event));
window.addEventListener("pointermove", dragTimeline);
window.addEventListener("pointerup", endTimelineDrag);
window.addEventListener("pointercancel", endTimelineDrag);

els.generateButton.addEventListener("click", generateCaptures);
els.toLayoutButton.addEventListener("click", () => setStage(4));
els.autoCropButton.addEventListener("click", async () => {
  if (hasAutoCrop()) {
    // 清空裁剪：恢复整图（不包含手动设置的垂直裁剪）。
    state.images.forEach((m) => {
      m.crop.l = 0;
      m.crop.r = 1;
    });
    syncCardList();
    showToast("已清空自动裁剪。");
    return;
  }
  showToast("正在自动裁剪…");
  try {
    await autoCrop();
    showToast("已自动裁剪。", "success");
  } catch (e) {
    showToast(e.message || "自动裁剪失败。", "error");
  }
});
els.autoMeasureButton.addEventListener("click", async () => {
  if (hasMeasures()) {
    // 清空小节：清除所有截图的小节线标记。
    state.images.forEach((m) => {
      m.measures = [];
    });
    syncCardList();
    showToast("已清空小节线。");
    return;
  }
  showToast("正在识别小节线…");
  try {
    await autoMeasures();
    showToast("已自动识别小节线。", "success");
  } catch (e) {
    showToast(e.message || "自动识别小节线失败。", "error");
  }
});
els.downloadPdfButton.addEventListener("click", downloadPdf);
els.downloadLongButton.addEventListener("click", downloadLongImage);

// 去色 details：摘要点击控制。
if (els.cleanDetailsSummary) {
  els.cleanDetailsSummary.addEventListener("click", (e) => {
    e.preventDefault();
    if (state.noteColorSelected) {
      // 已去色 → 折叠 details 并取消去色效果。
      els.cleanDetails.open = false;
      state.noteColorSelected = false;
      updateCleanSummary();
      syncRecolorOption();
      refreshCardPreviews();
      if (state.stage === 4) renderPages();
    } else {
      // 未去色 → 弹出取色窗口。
      openNoteColorModal();
    }
  });
}

// 音符颜色选取弹窗。
els.noteColorModalClose.addEventListener("click", closeNoteColorModal);
els.noteColorModal.addEventListener("click", (e) => {
  if (e.target === els.noteColorModal) closeNoteColorModal();
});
els.noteColorConfirm.addEventListener("click", confirmNoteColor);

// 插入弹窗。
els.insertModalClose.addEventListener("click", closeInsertModal);
els.insertModal.addEventListener("click", (e) => {
  if (e.target === els.insertModal) closeInsertModal();
});
els.insertVideoButton.addEventListener("click", () => {
  const index = state.insertIndex;
  closeInsertModal();
  if (index != null) insertFromVideo(index);
});
els.insertFileInput.addEventListener("change", () => {
  const index = state.insertIndex;
  if (index == null) return;
  insertLocalFiles(index, Array.from(els.insertFileInput.files || []));
});

// 插入弹窗文件框的拖放。
let insertDragDepth = 0;
els.insertFileField.addEventListener("dragenter", (e) => {
  e.preventDefault();
  insertDragDepth += 1;
  els.insertFileField.classList.add("is-dragover");
});
els.insertFileField.addEventListener("dragover", (e) => e.preventDefault());
els.insertFileField.addEventListener("dragleave", (e) => {
  e.preventDefault();
  insertDragDepth -= 1;
  if (insertDragDepth <= 0) {
    insertDragDepth = 0;
    els.insertFileField.classList.remove("is-dragover");
  }
});
els.insertFileField.addEventListener("drop", (e) => {
  e.preventDefault();
  insertDragDepth = 0;
  els.insertFileField.classList.remove("is-dragover");
  const index = state.insertIndex;
  if (index == null) return;
  const files = Array.from(e.dataTransfer?.files || []).filter((f) => f.type && f.type.startsWith("image/"));
  if (files.length) insertLocalFiles(index, files);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!els.loginModal.classList.contains("hidden")) {
      els.loginModal.classList.add("hidden");
      stopLoginPolling();
    } else if (!els.infoModal.classList.contains("hidden")) {
      els.infoModal.classList.add("hidden");
    } else if (!els.updateModal.classList.contains("hidden")) {
      els.updateModal.classList.add("hidden");
    } else if (!els.noteColorModal.classList.contains("hidden")) closeNoteColorModal();
    else if (!els.insertModal.classList.contains("hidden")) closeInsertModal();
  }
});

// ===================== 版本与更新检查 =====================
const APP_VERSION = (document.querySelector(".version-badge")?.textContent || "").replace(/^v/, "").trim();

// 把 "v3.1.0" / "3.1.0" 解析成可比较的数字数组。
function parseVersion(v) {
  return String(v || "")
    .trim()
    .replace(/^[vV]/, "")
    .split(/[.\-+]/)
    .map((s) => parseInt(s, 10) || 0);
}

function compareVersions(a, b) {
  const pa = parseVersion(a);
  const pb = parseVersion(b);
  const n = Math.max(pa.length, pb.length);
  for (let i = 0; i < n; i++) {
    const x = pa[i] || 0;
    const y = pb[i] || 0;
    if (x !== y) return x - y;
  }
  return 0;
}

// 读取本地已跳过的版本（BiliTabCapture_cache/skipped_version.txt）。
async function readSkippedVersion() {
  try {
    const res = await fetch("/api/skipped_version", { method: "GET" });
    if (!res.ok) return null;
    const data = await res.json();
    return data && data.skipped_version ? data.skipped_version : null;
  } catch (e) {
    return null;
  }
}

// 记录本次启动要跳过的版本（写入 BiliTabCapture_cache）。
async function writeSkippedVersion(version) {
  try {
    await fetch("/api/skipped_version", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: version || "" }),
    });
  } catch (e) { /* ignore */ }
}

// 渲染更新日志：从最新版本到「当前版本的下一版」，只显示比当前新的版本。
function renderUpdateLog(tags) {
  const current = APP_VERSION;
  const newer = tags
    .filter((t) => compareVersions(t.name, current) > 0)
    .sort((a, b) => compareVersions(b.name, a.name));
  els.updateLog.innerHTML = "";
  if (!newer.length) {
    const p = document.createElement("p");
    p.className = "about-row";
    p.textContent = "暂无更新日志。";
    els.updateLog.appendChild(p);
    return;
  }
  newer.forEach((t) => {
    const entry = document.createElement("div");
    entry.className = "update-entry";
    const name = document.createElement("div");
    name.className = "update-entry-name";
    name.textContent = t.name || "";
    entry.appendChild(name);
    if (t.message) {
      const msg = document.createElement("div");
      msg.className = "update-entry-msg";
      msg.textContent = t.message;
      entry.appendChild(msg);
    }
    els.updateLog.appendChild(entry);
  });
}

// 检查更新：GET gitee tags API。
async function checkForUpdate() {
  try {
    const res = await fetch("https://gitee.com/api/v5/repos/m1ku666/bili-tab-capture/tags/", { method: "GET" });
    if (!res.ok) return;
    const tags = await res.json();
    if (!Array.isArray(tags) || !tags.length) return;
    // gitee tags 接口返回的可能是按时间倒序；这里取版本号最大者作为最新。
    const latest = tags.reduce((a, b) => (compareVersions(b.name, a.name) > 0 ? b : a), tags[0]);
    state.latestVersion = latest.name;
    const isNewer = compareVersions(latest.name, APP_VERSION) > 0;
    if (!isNewer) return; // 已是最新，不显示「下载新版本」
    els.updateLink.classList.remove("hidden");
    // 若已跳过该最新版本，则启动时不自动弹窗。
    if ((await readSkippedVersion()) === latest.name) return;
    renderUpdateLog(tags);
    els.updateModal.classList.remove("hidden");
  } catch (e) {
    // 网络失败静默处理。
  }
}

// i 图标：打开关于弹窗。
els.infoButton.addEventListener("click", () => {
  els.infoModal.classList.remove("hidden");
});
els.infoModalClose.addEventListener("click", () => els.infoModal.classList.add("hidden"));
els.infoModal.addEventListener("click", (e) => {
  if (e.target === els.infoModal) els.infoModal.classList.add("hidden");
});

// 「复制邮箱」：复制到剪贴板并给出提示。
const copyEmailLink = document.getElementById("copyEmailLink");
if (copyEmailLink) {
  copyEmailLink.addEventListener("click", async (e) => {
    e.preventDefault();
    const email = "m1ku666@foxmail.com";
    try {
      await navigator.clipboard.writeText(email);
      showToast(`已复制 ${email}`, "success");
    } catch (err) {
      showToast("复制失败：" + err.message, "error");
    }
  });
}

// 更新弹窗。
els.updateModalClose.addEventListener("click", () => els.updateModal.classList.add("hidden"));
els.updateModal.addEventListener("click", (e) => {
  if (e.target === els.updateModal) els.updateModal.classList.add("hidden");
});
els.updateSkipBtn.addEventListener("click", () => {
  if (state.latestVersion) writeSkippedVersion(state.latestVersion);
  els.updateModal.classList.add("hidden");
});

// 每次启动时检查更新。
checkForUpdate();

// 颜色字段同步（文本 + 原生取色器 + 吸管）。
bindColorField(els.bgColorHex, els.bgColor);
bindColorField(els.textColorHex, els.textColor);
bindColorField(els.noteColorHex, els.noteColor);
// 背景/文字颜色影响着色预览图，走节流；音符颜色直接刷新第三/四步。
bindEyedropper(els.bgColorEyedrop, els.bgColorHex, els.bgColor, scheduleRecolorPreview);
bindEyedropper(els.textColorEyedrop, els.textColorHex, els.textColor, scheduleRecolorPreview);
bindEyedropper(els.noteColorEyedrop, els.noteColorHex, els.noteColor, onCleanChange);

// 去色参数滑块。
bindSliderPair(els.tolerance, els.toleranceNum, onCleanChange);
bindSliderPair(els.softness, els.softnessNum, onCleanChange);

// 排版数值滑块 + 文本框同步。
bindSliderPair(els.scaleSlider, els.scaleInput, renderPages);
bindSliderPair(els.marginSlider, els.pageMargin, renderPages);
bindSliderPair(els.spacingSlider, els.imageSpacing, renderPages);
bindSliderPair(els.titleSpacingSlider, els.titleSpacing, renderPages);

// 排版实时重渲染监听（几何布局类参数走即时路径）。
const layoutInputs = [
  els.titleArea,
  els.pageMargin,
  els.imageSpacing,
  els.titleSpacing,
  els.scaleInput,
];
layoutInputs.forEach((input) => {
  if (input) input.addEventListener("input", renderPages);
});
// 背景/文字颜色影响着色预览图，走节流避免卡死。
[els.bgColor, els.bgColorHex, els.textColor, els.textColorHex].forEach((input) => {
  if (input) input.addEventListener("input", scheduleRecolorPreview);
});
els.invertInput.addEventListener("change", scheduleRecolorPreview);
els.recolorInput.addEventListener("change", () => {
  scheduleRecolorPreview();
});
// 音符颜色变化：同步刷新第三步预览与第四步排版。
[els.noteColor, els.noteColorHex].forEach((input) => {
  if (input) input.addEventListener("input", onCleanChange);
});
document.querySelectorAll('input[name="orientation"]').forEach((radio) => {
  radio.addEventListener("change", renderPages);
});
document.querySelectorAll('input[name="align"]').forEach((radio) => {
  radio.addEventListener("change", renderPages);
});
document.querySelectorAll('input[name="valign"]').forEach((radio) => {
  radio.addEventListener("change", renderPages);
});
document.querySelectorAll('input[name="previewCols"]').forEach((radio) => {
  radio.addEventListener("change", renderPages);
});
// 排版参数变化时同步持久化（用于缓存恢复）。
const layoutPersistTargets = [
  els.titleArea,
  els.pageMargin,
  els.imageSpacing,
  els.titleSpacing,
  els.scaleInput,
  els.scaleSlider,
  els.marginSlider,
  els.spacingSlider,
  els.titleSpacingSlider,
  els.bgColor,
  els.bgColorHex,
  els.textColor,
  els.textColorHex,
  els.invertInput,
  els.recolorInput,
];
layoutPersistTargets.forEach((input) => {
  if (!input) return;
  input.addEventListener("input", schedulePersist);
  input.addEventListener("change", schedulePersist);
});
document.querySelectorAll('input[name="orientation"], input[name="align"], input[name="valign"], input[name="previewCols"]').forEach((radio) => {
  radio.addEventListener("change", schedulePersist);
});
syncRecolorOption();
updateCleanSummary();

// 卡片列表尺寸变化（窗口缩放 / 图片加载后）时，同步「横向分割」按钮高度。
if (typeof ResizeObserver === "function" && els.cardList) {
  const cardListObserver = new ResizeObserver(() => syncSplitButtons());
  cardListObserver.observe(els.cardList);
}

// 窗口尺寸变化时重新填满容器。
let resizeTimer = null;
window.addEventListener("resize", () => {
  fitPreviewFrame();
  if (state.stage !== 4) return;
  if (resizeTimer) clearTimeout(resizeTimer);
  resizeTimer = setTimeout(renderPages, 150);
});

const stepperList = document.querySelector(".stepper ol");
stepperList.addEventListener("click", (event) => {
  const li = event.target.closest("li[data-step]");
  if (!li) return;
  const step = Number(li.dataset.step);
  if (step <= state.maxStage && step !== state.stage) {
    setStage(step);
  }
});
stepperList.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const li = event.target.closest("li[data-step]");
  if (!li) return;
  event.preventDefault();
  const step = Number(li.dataset.step);
  if (step <= state.maxStage && step !== state.stage) {
    setStage(step);
  }
});

function updateBackToTop() {
  els.backToTop.classList.toggle("is-visible", window.scrollY > 400);
}
window.addEventListener("scroll", updateBackToTop, { passive: true });
els.backToTop.addEventListener("click", () => {
  window.scrollTo({ top: 0, behavior: "smooth" });
});
updateBackToTop();

updateCropUi();
updateTimeline();
loadIcons();
setStage(1);

// Reflect an existing Bilibili login (cookie.txt) on page load.
fetchJson("/api/bilibili/login")
  .then((data) => {
    if (data.status === "success") {
      setLoggedIn(true);
      setStatus(els.loginStatus, data.message || "已登录。", "success");
    }
  })
  .catch(() => { });

// 关闭/刷新前立即持久化一次调整状态（keepalive 保证请求能发出）。
window.addEventListener("beforeunload", () => {
  if (persistTimer) clearTimeout(persistTimer);
  persistStateNow();
});
