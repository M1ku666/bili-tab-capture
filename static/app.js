const state = {
  sourceId: null,
  sourceUrl: null,
  duration: null,
  cropStart: 0,
  cropEnd: 1,
  cropLeft: 0,
  cropRight: 1,
  activeHandle: null,
  timelineDrag: null,
  pollTimer: null,
  importing: false,
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
};

const els = {
  importPanel: document.getElementById("importPanel"),
  importForm: document.getElementById("importForm"),
  importButton: document.getElementById("importButton"),
  importStatus: document.getElementById("importStatus"),
  workspace: document.getElementById("workspace"),
  youtubeUrl: document.getElementById("youtubeUrl"),
  bvidInput: document.getElementById("bvidInput"),
  bilibiliLoginButton: document.getElementById("bilibiliLoginButton"),
  loginPanel: document.getElementById("loginPanel"),
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
  titleInput: document.getElementById("titleInput"),
  channelInput: document.getElementById("channelInput"),
  startMinInput: document.getElementById("startMinInput"),
  startSecInput: document.getElementById("startSecInput"),
  endMinInput: document.getElementById("endMinInput"),
  endSecInput: document.getElementById("endSecInput"),
  sampleEvery: document.getElementById("sampleEvery"),
  diffThreshold: document.getElementById("diffThreshold"),
  bandHalfWidth: document.getElementById("bandHalfWidth"),
  compareWindow: document.getElementById("compareWindow"),
  binarizeInput: document.getElementById("binarizeInput"),
  binarizeThreshold: document.getElementById("binarizeThreshold"),
  binarizeOptions: document.getElementById("binarizeOptions"),
  invertInput: document.getElementById("invertInput"),
  invertToggle: document.getElementById("invertToggle"),
  binarizeAutoToggle: document.getElementById("binarizeAutoToggle"),
  noteDarkToggle: document.getElementById("noteDarkToggle"),
  binarizeSliderRow: document.getElementById("binarizeSliderRow"),
  binarizeAuto: document.getElementById("binarizeAuto"),
  generateButton: document.getElementById("generateButton"),
  extractStatus: document.getElementById("extractStatus"),
  resultPdfView: document.getElementById("resultPdfView"),
  resultPdfDownload: document.getElementById("resultPdfDownload"),
  resultPdfFrame: document.getElementById("resultPdfFrame"),
  doneMeta: document.getElementById("doneMeta"),
  jobPanel: document.getElementById("jobPanel"),
  jobPhase: document.getElementById("jobPhase"),
  statChecked: document.getElementById("statChecked"),
  statSkipped: document.getElementById("statSkipped"),
  statKept: document.getElementById("statKept"),
  logBox: document.getElementById("logBox"),
  adjustPanel: document.getElementById("adjustPanel"),
  donePanel: document.getElementById("donePanel"),
  pageList: document.getElementById("pageList"),
  pageMargin: document.getElementById("pageMargin"),
  imageSpacing: document.getElementById("imageSpacing"),
  bgColor: document.getElementById("bgColor"),
  bgColorHex: document.getElementById("bgColorHex"),
  textColorHex: document.getElementById("textColorHex"),
  textColor: document.getElementById("textColor"),
  generatePdfButton: document.getElementById("generatePdfButton"),
  adjustStatus: document.getElementById("adjustStatus"),
  backButton: document.getElementById("backButton"),
  importNewButton: document.getElementById("importNewButton"),
  backToTop: document.getElementById("backToTop"),
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

function setStage(n) {
  state.stage = n;
  state.maxStage = Math.max(state.maxStage, n);
  els.importPanel.classList.toggle("hidden", n !== 1);
  els.workspace.classList.toggle("hidden", n !== 2);
  els.adjustPanel.classList.toggle("hidden", n !== 3);
  els.donePanel.classList.toggle("hidden", n !== 4);
  renderStepper();
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

// 通知气泡：补插小节的加载/结果提示，短暂弹出后自动消失。
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
  els.importButton.textContent = isLoading ? "导入中..." : "导入视频";
  setControlBusy(
    [els.importButton, els.youtubeUrl, els.bvidInput, els.bilibiliLoginButton, els.localFile],
    isLoading
  );
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
  if (!Number.isFinite(value)) return "0:00";
  const rounded = Math.max(0, Math.round(value));
  const minutes = Math.floor(rounded / 60);
  const seconds = rounded % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
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

  // 把手贴合裁剪区：上下把手横跨裁剪宽度、左右把手纵跨裁剪高度，
  // 使把手（及其可视横条）相对裁剪区居中，而非相对整个视频。
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
  els.jobPanel.classList.add("hidden");
  els.jobPhase.textContent = "排队中";
  els.statChecked.textContent = "0";
  els.statSkipped.textContent = "0";
  els.statKept.textContent = "0";
  els.logBox.textContent = "";
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
  state.images = [];
  state.captureJobId = null;

  state.sourceId = source.id;
  state.duration = source.duration || null;
  const metadata = source.metadata || {};
  els.titleInput.value = metadata.display_title || metadata.raw_title || "";
  els.channelInput.value = metadata.channel || "";
  state.sourceUrl = metadata.source_url || "";
  state.maxStage = 2;
  setStage(2);

  els.startMinInput.value = "0";
  els.startSecInput.value = "0";
  els.endMinInput.value = "";
  els.endSecInput.value = "";
  if (state.duration) {
    state.initialPreviewTime = Math.floor(Math.floor(state.duration) / 2);
  } else {
    state.initialPreviewTime = 0;
  }

  updateCropUi();
  updateTimeline();
}

async function loadPreview(timeValue) {
  if (!state.sourceId) return;
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
      headers: { "Content-Type": "application/json" },
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
  if (input.value === "") return fallback;
  return Number(input.value);
}

function currentNoteDark() {
  const checked = document.querySelector('input[name="noteDark"]:checked');
  return checked ? checked.value === "dark" : true;
}

function currentOrientation() {
  const checked = document.querySelector('input[name="orientation"]:checked');
  return checked ? checked.value : "portrait";
}

function currentAlign() {
  const checked = document.querySelector('input[name="align"]:checked');
  return checked ? checked.value : "left";
}

function syncThresholdControl() {
  els.binarizeSliderRow.classList.toggle("hidden", els.binarizeAuto.checked);
}

function syncBinarizeOptions() {
  const binarize = els.binarizeInput.checked;
  els.invertToggle.classList.toggle("hidden", binarize);
  els.binarizeAutoToggle.classList.toggle("hidden", !binarize);
  els.noteDarkToggle.classList.toggle("hidden", !binarize);
  els.binarizeOptions.classList.toggle("hidden", !binarize);
  syncThresholdControl();
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

function renderJob(job) {
  els.jobPanel.classList.remove("hidden");
  const phaseKey = job.status === "error" ? "error" : job.phase || job.status;
  els.jobPhase.textContent = PHASE_LABELS[phaseKey] || phaseKey;

  if (job.stats) {
    els.statChecked.textContent = job.stats.frames_checked ?? 0;
    els.statSkipped.textContent = job.stats.duplicates_skipped ?? 0;
    els.statKept.textContent = job.stats.captures_kept ?? 0;
  }

  els.logBox.textContent = (job.logs || []).join("\n");
  els.logBox.scrollTop = els.logBox.scrollHeight;

  if (job.status === "done") {
    const kept = job.stats?.captures_kept ?? 0;
    setStatus(els.extractStatus, `已生成 ${kept} 张截图。`, "success");
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    els.generateButton.disabled = false;
    state.maxStage = 3; // 重新生成截图后，顶栏「4 完成」不可直达
    setStage(3);
    renderImages(job.captures || []);
  } else if (job.status === "error") {
    setStatus(els.extractStatus, job.error || "处理失败。", "error");
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    els.generateButton.disabled = false;
  } else {
    setStatus(els.extractStatus, "生成中...");
  }
}

const PAGE_W = 1654;
const PAGE_H = 2339;
const FOOTER_H = 80;
const HEADER_RATIO = 0.2;
const HEADER_TITLE_SIZE = 64; // 与后端 HEADER_TITLE_SIZE 一致（标题基准字号）

function currentLayoutOpts() {
  return {
    orientation: currentOrientation(),
    margin: numericValue(els.pageMargin, 40),
    spacing: numericValue(els.imageSpacing, 25),
    bgColor: els.bgColor.value || "#ffffff",
    textColor: els.textColor.value || "#181818",
    title: els.titleInput.value.trim(),
    channel: els.channelInput.value.trim(),
    url: state.sourceUrl || "",
  };
}

function currentPageCssWidth() {
  const avail = els.pageList ? els.pageList.clientWidth : 0;
  return Math.max(280, Math.min(1600, avail || 700));
}

function captureSrc(m) {
  if (!els.binarizeInput.checked && !els.invertInput.checked) return m.url;
  const params = new URLSearchParams();
  params.set("invert", els.invertInput.checked ? "1" : "0");
  params.set("binarize", els.binarizeInput.checked ? "1" : "0");
  params.set("note_dark", currentNoteDark() ? "1" : "0");
  params.set("text_color", els.textColor.value || "#181818");
  params.set("bg_color", els.bgColor.value || "#ffffff");
  if (!els.binarizeAuto.checked) params.set("threshold", els.binarizeThreshold.value);
  return `/api/capture_preview/${state.captureJobId}/${m.file}?${params.toString()}`;
}

function layoutPages() {
  const opts = currentLayoutOpts();
  let pageW = PAGE_W;
  let pageH = PAGE_H;
  if (opts.orientation === "landscape") {
    pageW = PAGE_H;
    pageH = PAGE_W;
  }
  const contentW = pageW - 2 * opts.margin;
  const hasHeader = Boolean(opts.title || opts.channel || opts.url);

  const pages = [];
  let currentPage = null;
  let currentY = 0;

  const startPage = (first) => {
    currentPage = { first, hasHeader: first && hasHeader, items: [] };
    pages.push(currentPage);
    currentY = first && hasHeader ? Math.round(pageH * HEADER_RATIO) : opts.margin;
  };

  startPage(true);

  const align = currentAlign();

  for (let i = 0; i < state.images.length; i++) {
    const m = state.images[i];
    if (m.hidden) continue;
    const crop = m.crop || { l: 0, t: 0, r: 1, b: 1 };
    // 基准缩放：原图宽度铺满内容区；裁切后保留区缩放不变化，只按裁切比例缩小显示尺寸。
    const aspect = (m.h || 1) / (m.w || 1);
    const w = Math.max(1, Math.round(contentW * (crop.r - crop.l)));
    const h = Math.max(1, Math.round(contentW * aspect * (crop.b - crop.t)));
    const x = align === "center"
      ? opts.margin + Math.round((contentW - w) / 2)
      : opts.margin;

    if (currentY + h + opts.margin + FOOTER_H > pageH) {
      startPage(false);
    }

    currentPage.items.push({ index: i, m, w, h, x, y: currentY });
    currentY += h + opts.spacing;
  }

  return { pages, pageW, pageH, opts };
}

function renderImages(images) {
  state.images = (images || []).map((m) => ({
    file: m.file,
    url: m.url,
    t: m.t ?? 0,
    w: m.w,
    h: m.h,
    hidden: false,
    flash: false,
    crop: { l: 0, t: 0, r: 1, b: 1 },
  }));
  // 等调整面板显示、拿到真实宽度后再排版，保证 A4 预览一开始就撑满容器。
  requestAnimationFrame(renderPages);
}

const ICON_HIDE = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
const ICON_RESTORE = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
const ICON_INSERT_ABOVE = '<svg viewBox="0 0 1024 1024" width="18" height="18" fill="currentColor"><path d="M896 682.666667a74.666667 74.666667 0 0 0-74.666667-74.666667H202.666667A74.666667 74.666667 0 0 0 128 682.666667v138.666666c0 41.216 33.450667 74.666667 74.666667 74.666667h618.666666A74.666667 74.666667 0 0 0 896 821.333333V682.666667z m-74.666667-10.666667a10.666667 10.666667 0 0 1 10.666667 10.666667v138.666666a10.666667 10.666667 0 0 1-10.666667 10.666667H202.666667a10.666667 10.666667 0 0 1-10.666667-10.666667V682.666667a10.666667 10.666667 0 0 1 10.666667-10.666667h618.666666zM512 554.666667a213.333333 213.333333 0 1 1 0-426.666667 213.333333 213.333333 0 0 1 0 426.666667z m138.666667-213.333334a32 32 0 0 0-32-32h-74.666667V234.666667a32 32 0 0 0-64 0v74.666666H405.333333a32 32 0 0 0 0 64h74.666667v74.666667a32 32 0 0 0 64 0V373.333333h74.666667a32 32 0 0 0 32-32z"/></svg>';
const ICON_INSERT_BELOW = '<svg viewBox="0 0 1024 1024" width="18" height="18" fill="currentColor"><path d="M896 341.333333a74.666667 74.666667 0 0 1-74.666667 74.666667H202.666667A74.666667 74.666667 0 0 1 128 341.333333V202.666667C128 161.450667 161.450667 128 202.666667 128h618.666666c41.216 0 74.666667 33.450667 74.666667 74.666667V341.333333z m-74.666667 10.666667A10.666667 10.666667 0 0 0 832 341.333333V202.666667a10.666667 10.666667 0 0 0-10.666667-10.666667H202.666667a10.666667 10.666667 0 0 0-10.666667 10.666667V341.333333c0 5.888 4.778667 10.666667 10.666667 10.666667h618.666666zM512 469.333333a213.333333 213.333333 0 1 0 0 426.666667 213.333333 213.333333 0 0 0 0-426.666667z m138.666667 213.333334a32 32 0 0 1-32 32h-74.666667v74.666666a32 32 0 0 1-64 0v-74.666666H405.333333a32 32 0 0 1 0-64h74.666667V576a32 32 0 0 1 64 0v74.666667h74.666667a32 32 0 0 1 32 32z"/></svg>';
const ICON_CLONE = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';

function iconButton(svg, title, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "icon-btn";
  btn.title = title;
  btn.setAttribute("aria-label", title);
  btn.innerHTML = svg;
  btn.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick(event);
  });
  return btn;
}

function buildImage(item, scale) {
  const { index, m, w, h, x, y } = item;
  const crop = m.crop || { l: 0, t: 0, r: 1, b: 1 };
  const cropW = Math.max(1e-6, crop.r - crop.l);
  const cropH = Math.max(1e-6, crop.b - crop.t);
  const dispW = w * scale;              // 裁切后显示尺寸
  const dispH = h * scale;
  const fullDispW = dispW / cropW;      // 原图按基准缩放后的完整显示尺寸
  const fullDispH = dispH / cropH;

  const wrap = document.createElement("div");
  wrap.className = "image-item" + (m.flash ? " is-flash" : "");
  wrap.style.left = `${x * scale}px`;
  wrap.style.top = `${y * scale}px`;
  wrap.style.width = `${dispW}px`;
  wrap.style.height = `${dispH}px`;

  // 裁切后仅显示保留区：原图按基准缩放平铺，外层 overflow 隐藏裁掉部分。
  const img = document.createElement("img");
  img.className = "image-img";
  img.src = captureSrc(m);
  img.alt = "";
  img.draggable = false;
  img.style.left = `${-(crop.l * fullDispW)}px`;
  img.style.top = `${-(crop.t * fullDispH)}px`;
  img.style.width = `${fullDispW}px`;
  img.style.height = `${fullDispH}px`;
  wrap.appendChild(img);

  // 四边把手 + 遮罩：遮罩平时隐藏，拖动时显示被裁掉的部分。
  const refs = buildCropOverlay();
  [refs.shadeTop, refs.shadeBottom, refs.shadeLeft, refs.shadeRight, refs.win,
    refs.handleTop, refs.handleBottom, refs.handleLeft, refs.handleRight]
    .forEach((el) => wrap.appendChild(el));

  const actions = document.createElement("div");
  actions.className = "image-actions";
  actions.appendChild(iconButton(ICON_HIDE, "隐藏", () => hideImage(index)));
  actions.appendChild(iconButton(ICON_RESTORE, "恢复裁剪", () => resetImageCrop(index)));
  actions.appendChild(iconButton(ICON_CLONE, "克隆", () => cloneImage(index)));
  actions.appendChild(iconButton(ICON_INSERT_ABOVE, "在上方插入", () => insertImages(index, "above")));
  actions.appendChild(iconButton(ICON_INSERT_BELOW, "在下方插入", () => insertImages(index, "below")));
  wrap.appendChild(actions);

  refs.handleTop.addEventListener("pointerdown", (e) => beginImageCropDrag(index, "top", refs, wrap, img, e));
  refs.handleBottom.addEventListener("pointerdown", (e) => beginImageCropDrag(index, "bottom", refs, wrap, img, e));
  refs.handleLeft.addEventListener("pointerdown", (e) => beginImageCropDrag(index, "left", refs, wrap, img, e));
  refs.handleRight.addEventListener("pointerdown", (e) => beginImageCropDrag(index, "right", refs, wrap, img, e));
  wrap.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".image-handle") || event.target.closest(".image-actions")) return;
    clickImageCrop(index, refs, wrap, img, event);
  });

  return wrap;
}

function buildCropOverlay() {
  const make = (cls) => {
    const el = document.createElement("div");
    el.className = cls;
    return el;
  };
  const makeHandle = (which) => {
    const el = document.createElement("button");
    el.type = "button";
    el.className = `image-handle image-handle-${which}`;
    el.setAttribute("aria-label", which);
    return el;
  };
  return {
    shadeTop: make("shade shade-top"),
    shadeBottom: make("shade shade-bottom"),
    shadeLeft: make("shade shade-left"),
    shadeRight: make("shade shade-right"),
    win: make("crop-window"),
    handleTop: makeHandle("top"),
    handleBottom: makeHandle("bottom"),
    handleLeft: makeHandle("left"),
    handleRight: makeHandle("right"),
  };
}

function resetImageCrop(index) {
  const m = state.images[index];
  if (!m) return;
  m.crop = { l: 0, t: 0, r: 1, b: 1 };
  renderPages();
  showToast("已恢复为裁切前大小", "success");
}

let cropDrag = null;

// 最小裁切尺寸：中间四个按钮容器（.image-actions）各边 +15px，换算成原图归一化。
function minCropGap(wrap, base, fullDispW, fullDispH) {
  const actions = wrap.querySelector(".image-actions");
  const minW = (actions ? actions.offsetWidth : 154) + 15;
  const minH = (actions ? actions.offsetHeight : 34) + 15;
  const baseW = Math.max(1e-6, base.r - base.l);
  const baseH = Math.max(1e-6, base.b - base.t);
  return {
    w: Math.min(minW / fullDispW, baseW),
    h: Math.min(minH / fullDispH, baseH),
  };
}

function beginImageCropDrag(index, handle, refs, wrap, img, event) {
  event.preventDefault();
  event.stopPropagation();
  const m = state.images[index];
  if (!m) return;
  const c = m.crop || (m.crop = { l: 0, t: 0, r: 1, b: 1 });
  const cropW = Math.max(1e-6, c.r - c.l);
  const cropH = Math.max(1e-6, c.b - c.t);
  cropDrag = {
    index, handle, refs, wrap, img,
    // 记录拖动开始时的裁切框，遮罩以它为基准、只向内（越裁越小）。
    base: { l: c.l, t: c.t, r: c.r, b: c.b },
    fullDispW: wrap.offsetWidth / cropW,
    fullDispH: wrap.offsetHeight / cropH,
    startValue: handle === "top" ? c.t : handle === "bottom" ? c.b : handle === "left" ? c.l : c.r,
    startX: event.clientX,
    startY: event.clientY,
  };
  const gap = minCropGap(wrap, cropDrag.base, cropDrag.fullDispW, cropDrag.fullDispH);
  cropDrag.minW = gap.w;
  cropDrag.minH = gap.h;
  wrap.classList.add("is-cropping");
  updateImageCropOverlay(refs, cropDrag.base, c);
  event.currentTarget.setPointerCapture?.(event.pointerId);
}

function clickImageCrop(index, refs, wrap, img, event) {
  event.preventDefault();
  const m = state.images[index];
  if (!m) return;
  const c = m.crop || (m.crop = { l: 0, t: 0, r: 1, b: 1 });
  const rect = wrap.getBoundingClientRect();
  const px = clamp((event.clientX - rect.left) / rect.width, 0, 1);
  const py = clamp((event.clientY - rect.top) / rect.height, 0, 1);
  // 映射回原图归一化坐标，点击吸附最近的边线（上下左右四边都支持）。
  const rx = c.l + px * (c.r - c.l);
  const ry = c.t + py * (c.b - c.t);

  const distTop = Math.abs(ry - c.t);
  const distBottom = Math.abs(ry - c.b);
  const distLeft = Math.abs(rx - c.l);
  const distRight = Math.abs(rx - c.r);
  let handle;
  if (Math.min(distTop, distBottom) <= Math.min(distLeft, distRight)) {
    handle = distTop <= distBottom ? "top" : "bottom";
  } else {
    handle = distLeft <= distRight ? "left" : "right";
  }

  const cropW = Math.max(1e-6, c.r - c.l);
  const cropH = Math.max(1e-6, c.b - c.t);
  // 点击吸附：把最近边线直接移到点击处，之后可继续拖动。
  const snapped = handle === "top" || handle === "bottom" ? ry : rx;
  cropDrag = {
    index, handle, refs, wrap, img,
    base: { l: c.l, t: c.t, r: c.r, b: c.b },
    fullDispW: wrap.offsetWidth / cropW,
    fullDispH: wrap.offsetHeight / cropH,
    startValue: snapped,
    startX: event.clientX,
    startY: event.clientY,
  };
  const gap = minCropGap(wrap, cropDrag.base, cropDrag.fullDispW, cropDrag.fullDispH);
  cropDrag.minW = gap.w;
  cropDrag.minH = gap.h;
  wrap.classList.add("is-cropping");
  applyImageCropDragDelta(0, 0);
  wrap.setPointerCapture?.(event.pointerId);
}

function applyImageCropDragDelta(dx, dy) {
  if (!cropDrag) return;
  const m = state.images[cropDrag.index];
  if (!m) return;
  const c = m.crop;
  const base = cropDrag.base;
  const fw = cropDrag.fullDispW;
  const fh = cropDrag.fullDispH;
  // 最小裁切限制（.image-actions + 15px）；向内裁切，边界不超过拖动开始时的裁切框。
  const minW = cropDrag.minW || 0.01;
  const minH = cropDrag.minH || 0.01;
  if (cropDrag.handle === "top") c.t = clamp(cropDrag.startValue + dy / fh, base.t, c.b - minH);
  else if (cropDrag.handle === "bottom") c.b = clamp(cropDrag.startValue + dy / fh, c.t + minH, base.b);
  else if (cropDrag.handle === "left") c.l = clamp(cropDrag.startValue + dx / fw, base.l, c.r - minW);
  else c.r = clamp(cropDrag.startValue + dx / fw, c.l + minW, base.r);
  // 拖动期间图片大小保持不变，只更新遮罩与裁切窗；松手时才真正应用裁切。
  updateImageCropOverlay(cropDrag.refs, base, c);
}

// 以拖动开始时的裁切框（base）为基准，把遮罩/裁切窗/把手定位到新的裁切边界。
function updateImageCropOverlay(refs, base, c) {
  const bw = Math.max(1e-6, base.r - base.l);
  const bh = Math.max(1e-6, base.b - base.t);
  const top = ((c.t - base.t) / bh) * 100;
  const bottom = ((c.b - base.t) / bh) * 100;
  const left = ((c.l - base.l) / bw) * 100;
  const right = ((c.r - base.l) / bw) * 100;
  const height = bottom - top;
  const width = right - left;
  const cx = (left + right) / 2;
  const cy = (top + bottom) / 2;

  refs.shadeTop.style.height = `${top}%`;
  refs.shadeBottom.style.height = `${100 - bottom}%`;
  refs.shadeLeft.style.width = `${left}%`;
  refs.shadeLeft.style.top = `${top}%`;
  refs.shadeLeft.style.height = `${height}%`;
  refs.shadeRight.style.width = `${100 - right}%`;
  refs.shadeRight.style.top = `${top}%`;
  refs.shadeRight.style.height = `${height}%`;

  refs.win.style.top = `${top}%`;
  refs.win.style.left = `${left}%`;
  refs.win.style.height = `${height}%`;
  refs.win.style.width = `${width}%`;

  refs.handleTop.style.left = `${cx}%`;
  refs.handleTop.style.top = `${top}%`;
  refs.handleBottom.style.left = `${cx}%`;
  refs.handleBottom.style.top = `${bottom}%`;
  refs.handleLeft.style.left = `${left}%`;
  refs.handleLeft.style.top = `${cy}%`;
  refs.handleRight.style.left = `${right}%`;
  refs.handleRight.style.top = `${cy}%`;
}

function dragImageCrop(event) {
  if (!cropDrag) return;
  applyImageCropDragDelta(
    event.clientX - cropDrag.startX,
    event.clientY - cropDrag.startY
  );
}

function endImageCropDrag() {
  if (!cropDrag) return;
  cropDrag.wrap.classList.remove("is-cropping");
  cropDrag = null;
  renderPages();
}

function renderPages() {
  if (!els.pageList) return;
  const { pages, pageW, pageH, opts } = layoutPages();
  const cssW = currentPageCssWidth();
  const scale = cssW / pageW;
  els.pageList.innerHTML = "";

  const total = pages.length;
  pages.forEach((page, pageIndex) => {
    const pageEl = document.createElement("div");
    pageEl.className = "page";
    pageEl.style.width = `${cssW}px`;
    pageEl.style.height = `${Math.round(pageH * scale)}px`;
    pageEl.style.background = opts.bgColor;
    pageEl.style.color = opts.textColor;

    if (page.hasHeader) {
      const header = document.createElement("div");
      header.className = "page-header";
      header.style.height = `${Math.round(pageH * HEADER_RATIO * scale)}px`;
      header.style.padding = `${Math.round(opts.margin * scale)}px`;
      const titleSize = Math.round(HEADER_TITLE_SIZE * scale);
      if (opts.title) {
        const titleEl = document.createElement("div");
        titleEl.className = "page-title";
        titleEl.textContent = opts.title;
        titleEl.style.fontSize = `${titleSize}px`;
        titleEl.style.marginBottom = `${Math.round(28 * scale)}px`;
        header.appendChild(titleEl);
      }
      if (opts.channel) {
        const channelEl = document.createElement("div");
        channelEl.className = "page-channel";
        channelEl.textContent = opts.channel;
        channelEl.style.fontSize = `${Math.round(titleSize * 0.4375)}px`;
        header.appendChild(channelEl);
      }
      if (opts.url) {
        const urlEl = document.createElement("div");
        urlEl.className = "page-url";
        urlEl.textContent = opts.url;
        urlEl.style.fontSize = `${Math.round(titleSize * 0.25)}px`;
        header.appendChild(urlEl);
      }
      pageEl.appendChild(header);
    }

    page.items.forEach((item) => {
      pageEl.appendChild(buildImage(item, scale));
    });

    const footer = document.createElement("div");
    footer.className = "page-footer";
    footer.style.position = "absolute";
    footer.style.bottom = "0";
    footer.style.left = "0";
    footer.style.right = "0";
    footer.style.height = `${Math.round(FOOTER_H * scale)}px`;
    footer.textContent = `${pageIndex + 1} / ${total}`;
    pageEl.appendChild(footer);

    els.pageList.appendChild(pageEl);
  });

  state.images.forEach((m) => { m.flash = false; });
}

function hideImage(index) {
  const m = state.images[index];
  if (!m) return;
  m.hidden = true;
  renderPages();
  showToast("已隐藏图片，点击相邻图片的插入按钮恢复", "success");
}

function cloneImage(index) {
  const m = state.images[index];
  if (!m) return;
  // 深拷贝一份，连同裁剪状态一起克隆，放在原图下方。
  const copy = {
    ...m,
    crop: m.crop ? { ...m.crop } : { l: 0, t: 0, r: 1, b: 1 },
    hidden: false,
    flash: true,
  };
  state.images.splice(index + 1, 0, copy);
  renderPages();
  showToast("已克隆图片到下方", "success");
}

async function insertImages(index, side) {
  if (state.inserting) return;
  const list = state.images;

  // 点击插入时若有隐藏图片，先全部恢复，不重新采样。
  const hasHidden = list.some((m) => m.hidden);
  if (hasHidden) {
    list.forEach((m) => {
      if (m.hidden) {
        m.hidden = false;
        m.flash = true;
      }
    });
    showToast("已恢复隐藏的图片", "success");
    renderPages();
    return;
  }

  const m = list[index];
  if (!m) return;

  let insertIndex;
  let tStart;
  let tEnd;
  if (side === "above") {
    const prev = list[index - 1];
    if (!prev) {
      showToast("已经是第一张图片，无法在上方插入");
      return;
    }
    insertIndex = index;
    tStart = prev.t;
    tEnd = m.t;
  } else {
    const next = list[index + 1];
    if (!next) {
      showToast("已经是最后一张图片，无法在下方插入");
      return;
    }
    insertIndex = index + 1;
    tStart = m.t;
    tEnd = next.t;
  }

  if (!(tEnd > tStart)) {
    showToast("未发现遗漏内容");
    return;
  }

  state.inserting = true;
  showToast("正在插入...");
  try {
    const data = await fetchJson("/api/insert_captures", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: state.captureJobId,
        t_start: tStart,
        t_end: tEnd,
        index: insertIndex,
      }),
    });
    const inserted = data.captures || [];
    if (!inserted.length) {
      showToast("未发现遗漏内容");
      return;
    }
    const normalized = inserted.map((c) => ({
      file: c.file,
      url: c.url,
      t: c.t ?? 0,
      w: c.w,
      h: c.h,
      hidden: false,
      flash: true,
      crop: { l: 0, t: 0, r: 1, b: 1 },
    }));
    list.splice(insertIndex, 0, ...normalized);
    showToast(`已插入 ${inserted.length} 张图片`, "success");
    renderPages();
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    state.inserting = false;
  }
}

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
    setStatus(els.extractStatus, "请先导入视频。", "error");
    return;
  }

  els.generateButton.disabled = true;
  els.jobPanel.classList.remove("hidden");
  setStatus(els.extractStatus, "开始处理...");
  try {
    const data = await fetchJson("/api/captures", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildExtractPayload()),
    });
    state.captureJobId = data.job_id;
    const firstJob = await pollJob(data.job_id);
    if (firstJob && !["done", "error"].includes(firstJob.status)) {
      state.pollTimer = setInterval(() => pollJob(data.job_id), 1000);
    }
  } catch (error) {
    setStatus(els.extractStatus, error.message, "error");
    els.generateButton.disabled = false;
  }
}

async function generatePdf() {
  const images = state.images
    .filter((m) => !m.hidden)
    .map((m) => ({ file: m.file, crop: m.crop || { l: 0, t: 0, r: 1, b: 1 } }));

  if (!images.length) {
    setStatus(els.adjustStatus, "请至少保留一张截图。", "error");
    return;
  }

  const title = els.titleInput.value.trim();
  const output = title ? `${title}.pdf` : "tablatura.pdf";

  els.generatePdfButton.disabled = true;
  setStatus(els.adjustStatus, "正在生成 PDF...");
  try {
    const data = await fetchJson("/api/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: state.captureJobId,
        images,
        margin: numericValue(els.pageMargin, 40),
        spacing: numericValue(els.imageSpacing, 25),
        orientation: currentOrientation(),
        align: currentAlign(),
        bg_color: els.bgColor.value || "#ffffff",
        text_color: els.textColor.value || "#181818",
        note_dark: currentNoteDark(),
        binarize: els.binarizeInput.checked,
        invert: els.invertInput.checked,
        binarize_threshold: els.binarizeAuto.checked ? null : Number(els.binarizeThreshold.value),
        title,
        channel: els.channelInput.value.trim(),
        output,
      }),
    });

    els.resultPdfView.href = data.pdf_url;
    els.resultPdfDownload.href = data.pdf_url;
    els.resultPdfDownload.download = data.pdf_name || "tablatura.pdf";
    els.resultPdfFrame.src = data.pdf_url;
    const kept = images.length;
    els.doneMeta.textContent = `共 ${data.page_count} 页，包含 ${kept} 张截图。`;
    setStatus(els.adjustStatus, "PDF 已生成。", "success");
    setStage(4);
  } catch (error) {
    setStatus(els.adjustStatus, error.message, "error");
  } finally {
    els.generatePdfButton.disabled = false;
  }
}

els.importForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.importing) return;

  const formData = new FormData(els.importForm);
  setImportLoading(true);
  setStatus(els.importStatus, "正在读取视频信息...");
  try {
    const source = await fetchJson("/api/import", {
      method: "POST",
      body: formData,
    });
    applySource(source);
    setStatus(els.importStatus, "视频已导入。", "success");
    await loadPreview(state.initialPreviewTime);
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
  els.fileHint.textContent = file ? file.name : "拖入视频文件，或点击选择";
}

els.youtubeUrl?.addEventListener("input", () => {
  if (els.youtubeUrl.value.trim()) {
    els.bvidInput.value = "";
    els.localFile.value = "";
    updateFileHint();
  }
});

els.bvidInput.addEventListener("input", () => {
  if (els.bvidInput.value.trim()) {
    if (els.youtubeUrl) els.youtubeUrl.value = "";
    els.localFile.value = "";
    updateFileHint();
  }
});

els.localFile.addEventListener("change", () => {
  if (els.localFile.files.length > 0) {
    if (els.youtubeUrl) els.youtubeUrl.value = "";
    els.bvidInput.value = "";
  }
  updateFileHint();
});

function isVideoFile(file) {
  if (!file) return false;
  if (file.type && file.type.startsWith("video/")) return true;
  return /\.(mp4|mov|mkv|webm)$/i.test(file.name);
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

  const file = Array.from(event.dataTransfer.files).find(isVideoFile);
  if (!file) {
    setStatus(els.importStatus, "请拖入视频文件（MP4、MOV、WebM、MKV）。", "error");
    return;
  }

  const dataTransfer = new DataTransfer();
  dataTransfer.items.add(file);
  els.localFile.files = dataTransfer.files;
  els.localFile.dispatchEvent(new Event("change"));
});

function setLoggedIn(loggedIn) {
  state.bilibiliLoggedIn = loggedIn;
  els.bilibiliLoginButton.textContent = loggedIn ? "退出登录" : "扫码登录";
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
    els.loginPanel.classList.add("hidden");
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
      els.loginPanel.classList.add("hidden");
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
  els.loginPanel.classList.remove("hidden");
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
  // 父容器内容区宽度（去掉 padding，避免边框/padding 导致溢出）。
  const containerW = parent.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const maxH = Math.min(720, Math.round(window.innerHeight * 0.75));
  const ratio = previewNaturalW / previewNaturalH;
  let frameW, frameH;
  if (ratio >= 1) {
    // 横屏/方屏：宽度顶满容器，高度按比例。
    frameW = containerW;
    frameH = Math.round(containerW / ratio);
  } else {
    // 竖屏：按高度限制，宽度随之缩小并居中。
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

// A4 预览里的图片裁剪框拖动：松开鼠标时应用裁剪。
window.addEventListener("pointermove", dragImageCrop);
window.addEventListener("pointerup", endImageCropDrag);
window.addEventListener("pointercancel", endImageCropDrag);

els.timeline.addEventListener("pointerdown", beginTimelineTrackDrag);
els.timelineStartHandle.addEventListener("pointerdown", (event) => beginTimelineDrag("start", event));
els.timelineEndHandle.addEventListener("pointerdown", (event) => beginTimelineDrag("end", event));
window.addEventListener("pointermove", dragTimeline);
window.addEventListener("pointerup", endTimelineDrag);
window.addEventListener("pointercancel", endTimelineDrag);

els.generatePdfButton.addEventListener("click", generatePdf);
els.binarizeInput.addEventListener("change", () => {
  syncBinarizeOptions();
  renderPages();
});
els.binarizeAuto.addEventListener("change", () => {
  syncThresholdControl();
  renderPages();
});
els.invertInput.addEventListener("change", renderPages);
document.querySelectorAll('input[name="noteDark"]').forEach((radio) => {
  radio.addEventListener("change", renderPages);
});
let binarizePreviewTimer = null;
els.binarizeThreshold.addEventListener("input", () => {
  if (binarizePreviewTimer) clearTimeout(binarizePreviewTimer);
  binarizePreviewTimer = setTimeout(renderPages, 120);
});
syncBinarizeOptions();
els.backButton.addEventListener("click", () => {
  setStage(3);
});
els.importNewButton.addEventListener("click", () => {
  setStage(1);
});

els.generateButton.addEventListener("click", generateCaptures);

// 先绑定颜色字段同步，再挂所见即所得监听，保证取色器/文本框变化顺序正确。
bindColorField(els.bgColorHex, els.bgColor);
bindColorField(els.textColorHex, els.textColor);

// 所见即所得：标题/作者/配色/页边距/图间距/横竖向变化时实时重排预览。
const layoutInputs = [
  els.titleInput,
  els.channelInput,
  els.bgColor,
  els.bgColorHex,
  els.textColor,
  els.textColorHex,
  els.pageMargin,
  els.imageSpacing,
];
layoutInputs.forEach((input) => {
  if (input) input.addEventListener("input", renderPages);
});
document.querySelectorAll('input[name="orientation"]').forEach((radio) => {
  radio.addEventListener("change", renderPages);
});
document.querySelectorAll('input[name="align"]').forEach((radio) => {
  radio.addEventListener("change", renderPages);
});

// 窗口尺寸变化时重新填满容器（纸张保持 A4 比例）。
let resizeTimer = null;
window.addEventListener("resize", () => {
  fitPreviewFrame();
  if (state.stage !== 3) return;
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
setStage(1);

// Reflect an existing Bilibili login (cookie.txt) on page load.
fetchJson("/api/bilibili/login")
  .then((data) => {
    if (data.status === "success") {
      setLoggedIn(true);
      setStatus(els.loginStatus, data.message || "已登录。", "success");
    }
  })
  .catch(() => {});
