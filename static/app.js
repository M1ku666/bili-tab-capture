const state = {
  sourceId: null,
  duration: null,
  cropStart: 0,
  cropEnd: 0.46,
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
  captures: [],
  activeCrop: null,
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
  cropWindow: document.getElementById("cropWindow"),
  cropTop: document.getElementById("cropTop"),
  cropBottom: document.getElementById("cropBottom"),
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
  captureGrid: document.getElementById("captureGrid"),
  batchCrop: document.getElementById("batchCrop"),
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
  const height = (state.cropEnd - state.cropStart) * 100;

  els.shadeTop.style.height = `${top}%`;
  els.shadeBottom.style.height = `${bottom}%`;
  els.cropWindow.style.top = `${top}%`;
  els.cropWindow.style.height = `${height}%`;
  els.cropTop.style.top = `${top}%`;
  els.cropBottom.style.top = `${state.cropEnd * 100}%`;
}

function pointerRatio(event) {
  const rect = els.previewFrame.getBoundingClientRect();
  return clamp((event.clientY - rect.top) / rect.height, 0, 1);
}

function beginDrag(handle, event) {
  event.preventDefault();
  state.activeHandle = handle;
  event.currentTarget.setPointerCapture?.(event.pointerId);
}

function dragCrop(event) {
  if (!state.activeHandle) return;
  const ratio = pointerRatio(event);
  const gap = 0.05;

  if (state.activeHandle === "top") {
    state.cropStart = clamp(ratio, 0, state.cropEnd - gap);
  } else {
    state.cropEnd = clamp(ratio, state.cropStart + gap, 1);
  }
  updateCropUi();
}

function endDrag() {
  state.activeHandle = null;
}

function clickCrop(event) {
  if (event.target.closest(".crop-handle")) return;
  event.preventDefault();
  const ratio = pointerRatio(event);
  const gap = 0.05;
  const distTop = Math.abs(ratio - state.cropStart);
  const distBottom = Math.abs(ratio - state.cropEnd);
  state.activeHandle = distTop <= distBottom ? "top" : "bottom";
  if (state.activeHandle === "top") {
    state.cropStart = clamp(ratio, 0, state.cropEnd - gap);
  } else {
    state.cropEnd = clamp(ratio, state.cropStart + gap, 1);
  }
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
  state.captures = [];
  state.captureJobId = null;

  state.sourceId = source.id;
  state.duration = source.duration || null;
  const metadata = source.metadata || {};
  els.titleInput.value = metadata.display_title || metadata.raw_title || "";
  els.channelInput.value = metadata.channel || "";
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
    renderCaptures(job.captures || []);
    state.maxStage = 3; // 重新生成截图后，顶栏「4 完成」不可直达
    setStage(3);
  } else if (job.status === "error") {
    setStatus(els.extractStatus, job.error || "处理失败。", "error");
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    els.generateButton.disabled = false;
  } else {
    setStatus(els.extractStatus, "生成中...");
  }
}

function updateCropCard(cap) {
  if (!cap._els) return;
  const leftPct = cap.left * 100;
  const rightPct = (1 - cap.right) * 100;
  const widthPct = (cap.right - cap.left) * 100;

  cap._els.shadeLeft.style.width = `${leftPct}%`;
  cap._els.shadeRight.style.width = `${rightPct}%`;
  cap._els.win.style.left = `${leftPct}%`;
  cap._els.win.style.width = `${widthPct}%`;
  cap._els.handleLeft.style.left = `${leftPct}%`;
  cap._els.handleRight.style.left = `${cap.right * 100}%`;
}

function updateAllCrops() {
  state.captures.forEach(updateCropCard);
}

function renderCaptures(captures) {
  state.captures = captures.map((capture) => ({
    file: capture.file,
    url: capture.url,
    keep: true,
    left: 0,
    right: 1,
  }));
  els.captureGrid.innerHTML = "";

  state.captures.forEach((cap, index) => {
    const card = document.createElement("div");
    card.className = "capture-card";
    card.dataset.index = String(index);

    const top = document.createElement("div");
    top.className = "capture-top";

    const keepLabel = document.createElement("label");
    keepLabel.className = "keep-toggle";
    const keepCheckbox = document.createElement("input");
    keepCheckbox.type = "checkbox";
    keepCheckbox.checked = true;
    keepCheckbox.addEventListener("change", () => {
      cap.keep = keepCheckbox.checked;
    });
    keepLabel.appendChild(keepCheckbox);
    keepLabel.appendChild(document.createTextNode(`保留截图 ${index + 1}`));

    top.appendChild(keepLabel);

    const frame = document.createElement("div");
    frame.className = "capture-frame";

    const img = document.createElement("img");
    img.className = "capture-img";
    img.src = cap.url;
    img.alt = `截图 ${index + 1}`;
    img.draggable = false;
    frame.appendChild(img);

    const overlay = document.createElement("div");
    overlay.className = "h-crop-overlay";

    const shadeLeft = document.createElement("div");
    shadeLeft.className = "h-shade h-shade-left";
    const shadeRight = document.createElement("div");
    shadeRight.className = "h-shade h-shade-right";
    const cropWindow = document.createElement("div");
    cropWindow.className = "h-crop-window";

    const handleLeft = document.createElement("button");
    handleLeft.type = "button";
    handleLeft.className = "h-handle h-handle-left";
    handleLeft.addEventListener("pointerdown", (event) => beginHCrop(event, index, "left"));
    const handleRight = document.createElement("button");
    handleRight.type = "button";
    handleRight.className = "h-handle h-handle-right";
    handleRight.addEventListener("pointerdown", (event) => beginHCrop(event, index, "right"));

    overlay.appendChild(shadeLeft);
    overlay.appendChild(shadeRight);
    overlay.appendChild(cropWindow);
    overlay.appendChild(handleLeft);
    overlay.appendChild(handleRight);
    frame.appendChild(overlay);
    frame.addEventListener("pointerdown", (event) => clickHCrop(event, index));

    card.appendChild(top);
    card.appendChild(frame);
    els.captureGrid.appendChild(card);

    cap._els = { shadeLeft, shadeRight, win: cropWindow, handleLeft, handleRight };
  });

  updateAllCrops();
}

function beginHCrop(event, index, side) {
  event.preventDefault();
  state.activeCrop = { index, side };
  event.currentTarget.setPointerCapture?.(event.pointerId);
}

function dragHCrop(event) {
  if (!state.activeCrop) return;
  const { index, side } = state.activeCrop;
  const cap = state.captures[index];
  if (!cap) return;

  const frame = els.captureGrid.querySelector(
    `.capture-card[data-index="${index}"] .capture-frame`
  );
  if (!frame) return;
  const rect = frame.getBoundingClientRect();
  const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
  const gap = 0.02;

  if (side === "left") {
    cap.left = clamp(ratio, 0, cap.right - gap);
  } else {
    cap.right = clamp(ratio, cap.left + gap, 1);
  }

  if (els.batchCrop.checked) {
    state.captures.forEach((other) => {
      if (side === "left") {
        other.left = clamp(cap.left, 0, other.right - gap);
      } else {
        other.right = clamp(cap.right, other.left + gap, 1);
      }
    });
  }

  updateAllCrops();
}

function endHCrop() {
  state.activeCrop = null;
}

function clickHCrop(event, index) {
  const cap = state.captures[index];
  if (!cap) return;
  if (event.target.closest(".h-handle")) return;
  const frame = els.captureGrid.querySelector(
    `.capture-card[data-index="${index}"] .capture-frame`
  );
  if (!frame) return;
  event.preventDefault();
  const rect = frame.getBoundingClientRect();
  const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
  const gap = 0.02;
  const distLeft = Math.abs(ratio - cap.left);
  const distRight = Math.abs(ratio - cap.right);
  const side = distLeft <= distRight ? "left" : "right";
  state.activeCrop = { index, side };
  if (side === "left") {
    cap.left = clamp(ratio, 0, cap.right - gap);
  } else {
    cap.right = clamp(ratio, cap.left + gap, 1);
  }
  if (els.batchCrop.checked) {
    state.captures.forEach((other) => {
      if (side === "left") {
        other.left = clamp(cap.left, 0, other.right - gap);
      } else {
        other.right = clamp(cap.right, other.left + gap, 1);
      }
    });
  }
  updateAllCrops();
  frame.setPointerCapture?.(event.pointerId);
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
  const images = state.captures.map((cap) => ({
    file: cap.file,
    keep: cap.keep,
    left: cap.left,
    right: cap.right,
  }));

  if (!images.some((item) => item.keep)) {
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
    const kept = images.filter((item) => item.keep).length;
    els.doneMeta.textContent = `共 ${data.page_count} 页，包含 ${kept} 张乐谱截图。`;
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
els.previewFrame.addEventListener("pointerdown", clickCrop);
window.addEventListener("pointermove", dragCrop);
window.addEventListener("pointerup", endDrag);
window.addEventListener("pointercancel", endDrag);

els.timeline.addEventListener("pointerdown", beginTimelineTrackDrag);
els.timelineStartHandle.addEventListener("pointerdown", (event) => beginTimelineDrag("start", event));
els.timelineEndHandle.addEventListener("pointerdown", (event) => beginTimelineDrag("end", event));
window.addEventListener("pointermove", dragTimeline);
window.addEventListener("pointerup", endTimelineDrag);
window.addEventListener("pointercancel", endTimelineDrag);

els.generatePdfButton.addEventListener("click", generatePdf);
els.binarizeInput.addEventListener("change", syncBinarizeOptions);
els.binarizeAuto.addEventListener("change", syncThresholdControl);
syncBinarizeOptions();
els.backButton.addEventListener("click", () => {
  setStage(3);
});
els.importNewButton.addEventListener("click", () => {
  setStage(1);
});
window.addEventListener("pointermove", dragHCrop);
window.addEventListener("pointerup", endHCrop);
window.addEventListener("pointercancel", endHCrop);

els.generateButton.addEventListener("click", generateCaptures);

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

bindColorField(els.bgColorHex, els.bgColor);
bindColorField(els.textColorHex, els.textColor);

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
