const apiBaseUrl = new URLSearchParams(window.location.search).get("api") || "http://127.0.0.1:35105";

const state = {
  system: null,
  capabilities: [],
  catalog: null,
  nativeAssets: [],
  jobs: [],
  ttsVoices: [],
  localPipAssets: [],
  contentService: null,
  contentConfig: null,
  uiProfiles: {},
  subtitleRows: [],
  selectedPipAsset: null,
  renderedMetaHumans: [],
  renderedVoices: [],
  voicePickerItems: [],
  avatarPickerItems: [],
  userBackgroundMusic: [],
  pipAssets: [],
  coverPath: "",
  coverSourceOverride: "",
  lastAudioPath: "",
  lastExportPath: "",
  generating: false,
  jobScope: "real",
  activeView: "workbench",
  activeJobId: "",
  jobPollingTimer: null,
  jobRefreshInFlight: false,
  pendingImageTarget: null,
  draftSelectionsApplied: false,
  subtitleSourceText: "",
  voiceCloneMode: "record",
  voiceRecordingFile: null,
  voiceRecorder: null,
  voiceRecordingStream: null,
  voiceRecordingStartedAt: 0,
  voiceRecordingTimer: null,
  voiceRecordingAutoStopTimer: null,
};

const workbenchDraftKey = "yingyu_workbench_draft_v1";
const voiceCloneScript = "清晨的阳光落在窗边，我用自然、清晰的声音记录今天的想法。说话时不需要刻意加快速度，只要保持放松，让每个字都完整、稳定。接下来我会继续朗读这段文字，用平常交流的语气，表达不同的停顿和情绪，让系统更准确地学习我的声音特点。";
const voicePreviewScript = "你好，这是一段声音试听。愿你今天保持从容，把每一句话都表达得自然清晰。";
const voiceCloneMaxSeconds = 40;
const subtitleStyles = [
  { value: "clean", label: "清晰白字", preview: "清晰自然，适合通用口播" },
  { value: "bold_yellow", label: "重点黄字", preview: "高对比重点，更容易扫读" },
  { value: "news_bar", label: "新闻信息条", preview: "稳重信息条，适合资讯解读" },
  { value: "orange_pop", label: "活力橙字", preview: "醒目活力，适合短视频口播" },
  { value: "minimal", label: "轻量极简", preview: "低干扰字幕，突出人物画面" },
  { value: "center_focus", label: "居中强调", preview: "核心句上移，适合观点表达" },
];

const pageTitles = {
  workbench: "创作首页",
  digital_humans: "数字人",
  voices: "声音",
  pip_assets: "辅助画面",
  jobs: "任务",
  settings: "设置",
};

const scriptInput = document.querySelector("#scriptInput");
const toast = document.querySelector("#toast");
const presenterImage = document.querySelector("#presenterImage");
const videoPreview = document.querySelector("#videoPreview");
const audioPreview = document.querySelector("#audioPreview");

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 3200);
}

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json; charset=utf-8");
  }
  const response = await fetch(`${apiBaseUrl}${path}`, { ...options, headers });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    const detail = payload?.detail || payload?.message || payload || `HTTP ${response.status}`;
    throw new Error(String(detail));
  }
  return payload;
}

function assertLegacySuccess(payload, fallbackMessage = "本地引擎请求失败") {
  if (payload && typeof payload === "object" && payload.code != null && Number(payload.code) !== 0) {
    throw new Error(payload.message || fallbackMessage);
  }
  return payload;
}

function setActiveView(viewId) {
  state.activeView = viewId;
  document.querySelectorAll(".nav_item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewId);
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id === `view_${viewId}`);
  });
  document.querySelector("#pageTitle").textContent = pageTitles[viewId] || "数字人工作台";
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (viewId === "jobs") runAction(() => refreshJobsOnly());
  syncJobPolling();
}

function updateScriptStats() {
  const text = scriptInput.value.trim();
  document.querySelector("#scriptCount").textContent = text.length;
  document.querySelector("#durationEstimate").textContent = Math.max(0, Math.ceil(text.length / 4.2));
  document.querySelector("#previewCaption").textContent = subtitlePreviewLine(text) || "输入文案后，这里会同步显示口播字幕预览。";
}

function subtitlePreviewLine(text, maxChars = 14) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  let line = "";
  for (const char of normalized) {
    line += char;
    if (line.replaceAll(" ", "").length >= maxChars || "。！？!?；;".includes(char)) break;
  }
  return line;
}

function loadWorkbenchDraft() {
  try {
    return JSON.parse(window.localStorage.getItem(workbenchDraftKey) || "null") || {};
  } catch {
    return {};
  }
}

function restoreWorkbenchDraftEarly() {
  const draft = loadWorkbenchDraft();
  if (draft.script) {
    scriptInput.value = draft.script;
    scriptInput.dataset.edited = "true";
  }
  if (draft.title) document.querySelector("#videoTitle").value = draft.title;
  if (draft.topics) document.querySelector("#videoTopics").value = draft.topics;
}

function applyWorkbenchDraftSelections() {
  if (state.draftSelectionsApplied) return;
  const draft = loadWorkbenchDraft();
  const values = {
    rewriteMode: draft.rewriteMode,
    contentType: draft.contentType,
    toneSelect: draft.tone,
    voiceSelect: draft.voice,
    avatarSelect: draft.avatar,
    speedRange: draft.speed,
    targetFormat: draft.targetFormat,
    videoQuality: draft.videoQuality,
    subtitleTemplate: draft.subtitleTemplate,
  };
  Object.entries(values).forEach(([id, value]) => {
    if (value == null || value === "") return;
    const element = document.querySelector(`#${id}`);
    if (!element) return;
    if (element instanceof HTMLSelectElement && ![...element.options].some((option) => option.value === String(value))) return;
    element.value = String(value);
  });
  const selectedAvatarOption = document.querySelector("#avatarSelect").selectedOptions[0];
  if (selectedAvatarOption?.dataset.source) {
    document.querySelector("#avatarEngine").value = selectedAvatarOption.dataset.source;
  }
  if (draft.backgroundMusicEnabled != null) document.querySelector("#backgroundMusicEnabled").checked = Boolean(draft.backgroundMusicEnabled);
  if (draft.burnSubtitles != null) document.querySelector("#burnSubtitles").checked = Boolean(draft.burnSubtitles);
  document.querySelector("#speedValue").textContent = `${Number(document.querySelector("#speedRange").value).toFixed(2)}x`;
  updateSubtitleStylePreview();
  state.draftSelectionsApplied = true;
}

function saveWorkbenchDraft() {
  const draft = {
    script: scriptInput.value,
    title: document.querySelector("#videoTitle").value,
    topics: document.querySelector("#videoTopics").value,
    rewriteMode: document.querySelector("#rewriteMode").value,
    contentType: document.querySelector("#contentType").value,
    tone: document.querySelector("#toneSelect").value,
    voice: document.querySelector("#voiceSelect").value,
    avatar: document.querySelector("#avatarSelect").value,
    avatarEngine: document.querySelector("#avatarEngine").value,
    speed: document.querySelector("#speedRange").value,
    targetFormat: document.querySelector("#targetFormat").value,
    videoQuality: document.querySelector("#videoQuality").value,
    subtitleTemplate: document.querySelector("#subtitleTemplate").value,
    backgroundMusicEnabled: document.querySelector("#backgroundMusicEnabled").checked,
    burnSubtitles: document.querySelector("#burnSubtitles").checked,
    savedAt: new Date().toISOString(),
  };
  window.localStorage.setItem(workbenchDraftKey, JSON.stringify(draft));
  const time = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  document.querySelector("#draftStatus").textContent = `${time} 已保存`;
  document.querySelector("#draftSaveHint").textContent = `已于 ${time} 自动保存`;
}

function scheduleWorkbenchDraftSave() {
  window.clearTimeout(scheduleWorkbenchDraftSave.timer);
  document.querySelector("#draftStatus").textContent = "正在保存...";
  scheduleWorkbenchDraftSave.timer = window.setTimeout(saveWorkbenchDraft, 450);
}

function openImagePreview(source, title) {
  if (!source) return;
  document.querySelector("#imagePreviewFull").src = source;
  document.querySelector("#imagePreviewTitle").textContent = title || "图片预览";
  document.querySelector("#imagePreviewDialog").showModal();
}

function setDot(id, status) {
  const dot = document.querySelector(`#${id}`);
  dot.classList.remove("online", "warning", "offline");
  dot.classList.add(status);
}

function workerById(id) {
  return state.system?.workers?.find((worker) => worker.id === id);
}

function updateSystemStatus() {
  const tts = workerById("tts_worker");
  const avatar = workerById("avatar_worker");
  const render = workerById("render_worker");
  const legacy = workerById("legacy_engine_adapter");
  const ttsReady = tts?.status === "connected";
  const videoReady = avatar?.status === "connected" && render?.status === "connected";
  const legacyReady = legacy?.status === "connected";

  document.querySelector("#audioStatus").textContent = ttsReady ? "正常" : "未连接";
  document.querySelector("#videoStatus").textContent = videoReady ? "正常" : "未连接";
  document.querySelector("#legacyStatus").textContent = legacyReady ? "可用" : legacy ? "基础服务在线" : "未连接";
  setDot("audioStatusDot", ttsReady ? "online" : "offline");
  setDot("videoStatusDot", videoReady ? "online" : "offline");
  setDot("legacyStatusDot", legacyReady ? "online" : legacy ? "warning" : "offline");
  setDot("sidebarStatusDot", ttsReady && videoReady ? "online" : "warning");
  document.querySelector("#sidebarStatusText").textContent = ttsReady && videoReady ? "本机服务已就绪" : "部分服务未就绪";
  renderServiceList();
}

function unwrapList(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.items)) return value.items;
  if (Array.isArray(value?.data)) return value.data;
  if (Array.isArray(value?.data?.items)) return value.data.items;
  if (value?.data && typeof value.data === "object") {
    const nested = Object.values(value.data).find((item) => Array.isArray(item));
    if (nested) return nested;
  }
  return [];
}

function displayName(item, fallback) {
  const value = item?.display_name || item?.label || item?.name || item?.title || fallback;
  return String(value).replace(/\.(mp4|mov|mkv|webm|wav|mp3)$/i, "");
}

function itemId(item, fallback) {
  return item?.voice_id || item?.avatar_id || item?.asset_id || item?.id || item?.name || fallback;
}

function avatarSelectionId(item, fallback) {
  if (item?.avatar_id) return String(item.avatar_id);
  if (item?.engine_name) return `original_meta_human:${encodeURIComponent(item.engine_name)}`;
  if (item?.asset_id || item?.id) return String(item.asset_id || item.id);
  if (item?.name && (item?.type === "sync" || item?.video || item?.video_info)) {
    return `original_meta_human:${encodeURIComponent(item.name)}`;
  }
  return String(item?.name || fallback);
}

function stableProfileKey(item, fallback) {
  const raw = String(itemId(item, fallback));
  return encodeURIComponent(raw).replaceAll("%", "_").replaceAll("~", "_").slice(0, 150);
}

function profileFor(kind, item, fallback) {
  return state.uiProfiles?.[kind]?.[stableProfileKey(item, fallback)] || {};
}

function profileDisplayName(kind, item, fallback) {
  return profileFor(kind, item, fallback).display_name || displayName(item, fallback);
}

function resolveAssetUrl(value) {
  if (!value) return "";
  if (/^https?:\/\//i.test(value) || String(value).startsWith("data:")) return String(value);
  if (String(value).startsWith("/media/")) return `${apiBaseUrl}${value}`;
  return String(value);
}

function defaultVoicePortrait(index) {
  return "./assets/voice-placeholder.svg";
}

function defaultAvatarImage(item, index) {
  const direct = item.cover || item.cover_url || item.image_url || item.thumbnail || item.poster;
  if (direct) return resolveAssetUrl(direct);
  return "./assets/presenter-placeholder.svg";
}

function avatarPoseLabel(item) {
  if (item?.pose) return item.pose;
  const name = displayName(item, "");
  if (/走动|边走|walking/i.test(name)) return "站姿走动";
  if (/站|stand/i.test(name)) return "站姿";
  if (/坐|sit/i.test(name)) return "坐姿模板";
  return item?.type === "sync" || item?.video || item?.video_info ? "视频模板" : "单图形象";
}

function avatarEngineName(item) {
  return String(item?.engine_name || item?.name || "").trim().toLowerCase();
}

function avatarCatalogRows() {
  const rawTemplates = unwrapList(state.catalog?.meta_humans);
  const nativeAssets = state.nativeAssets || [];
  const defaultPresenter = nativeAssets.find((item) => item.asset_id === "business_presenter")
    || { asset_id: "business_presenter", display_name: "AI 口播主持人", license_status: "prototype_only" };
  const templateMetadata = nativeAssets.filter((item) => ["local_video_template", "legacy_video_template"].includes(item.asset_type));
  const consumedRawIndexes = new Set();
  const curatedRows = templateMetadata.map((metadata) => {
    const rawIndex = rawTemplates.findIndex((item, index) => !consumedRawIndexes.has(index) && avatarEngineName(item) === avatarEngineName(metadata));
    const raw = rawIndex >= 0 ? rawTemplates[rawIndex] : {};
    if (rawIndex >= 0) consumedRawIndexes.add(rawIndex);
    return {
      ...raw,
      ...metadata,
      name: raw.name || metadata.engine_name || metadata.display_name,
      avatar_id: raw.avatar_id || `original_meta_human:${encodeURIComponent(metadata.engine_name)}`,
      source: metadata.license_status === "test_only" ? "旧版测试模板" : "本地动作模板",
      managementSource: "curated",
    };
  });
  const importedRows = rawTemplates
    .filter((_, index) => !consumedRawIndexes.has(index))
    .map((item) => ({ ...item, source: "用户导入模板", managementSource: "legacy" }));
  return [
    { ...defaultPresenter, source: "本机单图形象", managementSource: "native" },
    ...curatedRows,
    ...importedRows,
  ];
}

function avatarRecommendationScore(item, text) {
  if (item?.license_status !== "commercial_ok") return -1;
  const content = String(text || "").toLowerCase();
  return (item.recommendation_keywords || []).reduce((score, keyword) => (
    content.includes(String(keyword).toLowerCase()) ? score + 1 : score
  ), 0);
}

function renderVoicePicker() {
  const container = document.querySelector("#voicePickerGrid");
  if (!container) return;
  const selectedId = document.querySelector("#voiceSelect").value;
  document.querySelector("#voicePickerCount").textContent = `${state.voicePickerItems.length} 个声音`;
  container.innerHTML = state.voicePickerItems.map((entry) => `
    <article class="asset_picker_option${entry.id === selectedId ? " active" : ""}">
      <button type="button" class="asset_picker_select" data-voice-id="${escapeHtml(entry.id)}" aria-pressed="${entry.id === selectedId}">
        <img src="${escapeHtml(entry.imageUrl)}" alt="" loading="lazy" />
        <span class="asset_picker_option_text"><strong>${escapeHtml(entry.name)}</strong><small>${escapeHtml(entry.category)}</small></span>
      </button>
      <button type="button" class="asset_preview_button" data-preview-voice-id="${escapeHtml(entry.id)}" title="试听${escapeHtml(entry.name)}" aria-label="试听${escapeHtml(entry.name)}">▶ <span>试听</span></button>
    </article>`).join("");
}

function updateSelectedVoicePreview() {
  const selectedId = document.querySelector("#voiceSelect").value;
  const entry = state.voicePickerItems.find((item) => item.id === selectedId) || state.voicePickerItems[0];
  if (!entry) return;
  document.querySelector("#selectedVoiceImage").src = entry.imageUrl;
  document.querySelector("#selectedVoiceName").textContent = entry.name;
  document.querySelector("#selectedVoiceType").textContent = entry.category;
  renderVoicePicker();
}

function updateSelectedAvatarPreview() {
  const selectedId = document.querySelector("#avatarSelect").value;
  const entry = state.avatarPickerItems.find((item) => item.id === selectedId) || state.avatarPickerItems[0];
  const fallbackItem = entry?.item || { asset_id: "business_presenter", display_name: "AI 口播主持人" };
  const fallbackIndex = entry?.index || 0;
  const profile = profileFor("avatars", fallbackItem, `avatar_template_${fallbackIndex}`);
  const name = entry?.name || profile.display_name || displayName(fallbackItem, "AI 口播主持人");
  const imageUrl = entry?.imageUrl || resolveAssetUrl(profile.image_url) || defaultAvatarImage(fallbackItem, fallbackIndex);
  presenterImage.src = imageUrl;
  presenterImage.alt = `${name}预览`;
  presenterImage.dataset.previewTitle = name;
  document.querySelector("#selectedAvatarImage").src = imageUrl;
  document.querySelector("#selectedAvatarName").textContent = name;
  document.querySelector("#selectedAvatarPose").textContent = entry?.licenseStatus === "test_only"
    ? "仅限内部测试 · 禁止正式发布"
    : [entry?.pose || avatarPoseLabel(fallbackItem), entry?.usage].filter(Boolean).join(" · ");
  const previewButton = document.querySelector("#previewSelectedAvatar");
  previewButton.disabled = !entry?.videoUrl;
  previewButton.dataset.avatarId = entry?.id || "";
  renderAvatarTemplateGallery();
}

function renderAvatarTemplateGallery() {
  const container = document.querySelector("#avatarTemplateGallery");
  if (!container) return;
  const rows = avatarCatalogRows();
  const selectedId = document.querySelector("#avatarSelect").value;
  const recommendationScores = rows.map((item) => avatarRecommendationScore(item, scriptInput.value));
  const bestScore = Math.max(...recommendationScores);
  const recommendedIndex = bestScore > 0
    ? recommendationScores.indexOf(bestScore)
    : rows.findIndex((item) => item.semantic_role === "balanced_explanation");
  state.avatarPickerItems = rows.map((item, index) => {
    const id = avatarSelectionId(item, `template_${index}`);
    const source = item.asset_id === "business_presenter" ? "image_avatar" : "legacy_video_avatar";
    const profile = profileFor("avatars", item, `avatar_template_${index}`);
    const name = profile.display_name || displayName(item, `模板角色 ${index + 1}`);
    const imageUrl = resolveAssetUrl(profile.image_url) || defaultAvatarImage(item, index);
    const videoUrl = resolveAssetUrl(item.preview_url || item.video || item.video_info?.file || item.url || item.file || "");
    return {
      id,
      source,
      item,
      index,
      name,
      imageUrl,
      videoUrl,
      pose: avatarPoseLabel(item),
      usage: item.usage || "",
      licenseStatus: item.license_status || "unknown",
      recommended: index === recommendedIndex,
      maxContinuousSpeechSeconds: Number(item.max_continuous_speech_seconds || 0),
      loopAllowed: item.loop_allowed !== false,
      requiresBrollForLongerScript: Boolean(item.requires_broll_for_longer_script),
      motionSafetyNote: item.motion_safety_note || "",
    };
  });
  document.querySelector("#avatarPickerCount").textContent = `${state.avatarPickerItems.length} 个模板`;
  container.innerHTML = state.avatarPickerItems.map((entry) => `
    <article class="asset_picker_option${entry.id === selectedId ? " active" : ""}${entry.licenseStatus === "test_only" ? " test_only" : ""}">
      <div class="template_badges">
        ${entry.recommended ? '<span class="template_badge recommended">按文案推荐</span>' : ""}
        ${entry.licenseStatus === "test_only" ? '<span class="template_badge test_only">仅限内部测试</span>' : ""}
      </div>
      <button type="button" class="asset_picker_select" data-avatar-id="${escapeHtml(entry.id)}" data-avatar-source="${entry.source}" aria-pressed="${entry.id === selectedId}">
        <img src="${escapeHtml(entry.imageUrl)}" alt="" loading="lazy" />
        <span class="asset_picker_option_text"><strong>${escapeHtml(entry.name)}</strong><small>${escapeHtml(entry.pose)}</small>${entry.usage ? `<small class="template_usage">${escapeHtml(entry.usage)}</small>` : ""}${entry.maxContinuousSpeechSeconds ? `<small class="template_safety">建议单段不超过 ${entry.maxContinuousSpeechSeconds.toFixed(1)} 秒${entry.requiresBrollForLongerScript ? "，更长内容请用界面画面转场" : ""}</small>` : ""}</span>
      </button>
      ${entry.videoUrl ? `<button type="button" class="asset_preview_button" data-preview-avatar-id="${escapeHtml(entry.id)}" title="播放${escapeHtml(entry.name)}" aria-label="播放${escapeHtml(entry.name)}">▶ <span>试看动作</span></button>` : `<span class="asset_preview_unavailable">单图形象，无模板视频</span>`}
    </article>`).join("");
}

function renderCatalog() {
  const legacyVoices = unwrapList(state.catalog?.voices);
  const music = unwrapList(state.catalog?.background_music);
  const voiceSelect = document.querySelector("#voiceSelect");
  const avatarSelect = document.querySelector("#avatarSelect");
  const previousAvatarId = avatarSelect.value;
  const musicSelect = document.querySelector("#musicSelect");
  const subtitleTemplate = document.querySelector("#subtitleTemplate");
  const previousSubtitleTemplate = subtitleTemplate.value;

  voiceSelect.innerHTML = "";
  state.voicePickerItems = [];
  const voiceIds = new Set();
  state.ttsVoices.forEach((voice, index) => {
    const id = String(itemId(voice, `voice_${index}`));
    if (voiceIds.has(id)) return;
    voiceIds.add(id);
    const option = document.createElement("option");
    option.value = id;
    const name = profileDisplayName("voices", voice, `声音 ${index + 1}`);
    option.textContent = `${name} · 合成声音`;
    voiceSelect.appendChild(option);
    const profile = profileFor("voices", voice, `voice_${index}`);
    state.voicePickerItems.push({ id, name, category: "合成声音", source: "native_tts", promptAudio: "", imageUrl: resolveAssetUrl(profile.image_url) || defaultVoicePortrait(index) });
  });
  legacyVoices.forEach((voice, index) => {
    const option = document.createElement("option");
    option.value = `legacy:${index}`;
    const name = profileDisplayName("voices", voice, `克隆声音 ${index + 1}`);
    option.textContent = `${name} · 克隆声音`;
    option.dataset.source = "legacy_engine";
    option.dataset.promptAudio = voice.audio_file || voice.url || "";
    option.dataset.voiceName = profileDisplayName("voices", voice, `克隆声音 ${index + 1}`);
    voiceSelect.appendChild(option);
    const profile = profileFor("voices", voice, `voice_${state.ttsVoices.length + index}`);
    state.voicePickerItems.push({ id: option.value, name, category: "克隆声音", source: "legacy_engine", promptAudio: voice.audio_file || voice.url || "", imageUrl: resolveAssetUrl(profile.image_url) || defaultVoicePortrait(state.ttsVoices.length + index) });
  });
  if (!voiceSelect.options.length) {
    voiceSelect.add(new Option("清晰男声", "clear_male_zh"));
    state.voicePickerItems.push({ id: "clear_male_zh", name: "清晰男声", category: "合成声音", source: "native_tts", promptAudio: "", imageUrl: defaultVoicePortrait(0) });
  }
  updateSelectedVoicePreview();

  avatarSelect.innerHTML = "";
  avatarCatalogRows().forEach((avatar, index) => {
    const label = profileDisplayName("avatars", avatar, `模板角色 ${index + 1}`);
    const suffix = avatar.license_status === "test_only" ? " · 仅限测试" : "";
    const option = new Option(`${label}${suffix}`, avatarSelectionId(avatar, `template_${index}`));
    option.dataset.source = avatar.asset_id === "business_presenter" ? "image_avatar" : "legacy_video_avatar";
    avatarSelect.add(option);
  });
  if ([...avatarSelect.options].some((option) => option.value === previousAvatarId)) {
    avatarSelect.value = previousAvatarId;
  }
  const selectedAvatarOption = avatarSelect.selectedOptions[0];
  if (selectedAvatarOption?.dataset.source) {
    document.querySelector("#avatarEngine").value = selectedAvatarOption.dataset.source;
  }
  renderAvatarTemplateGallery();

  musicSelect.innerHTML = '<option value="">不使用背景音乐</option>';
  music.forEach((track, index) => {
    musicSelect.add(new Option(displayName(track, `背景音乐 ${index + 1}`), resolveAssetUrl(track.url || track.file || "")));
  });
  state.userBackgroundMusic.forEach((track, index) => {
    const option = new Option(`${displayName(track, `我的音乐 ${index + 1}`)} · 本地导入`, resolveAssetUrl(track.url || track.file || ""));
    option.dataset.mediaId = track.id || "";
    musicSelect.add(option);
  });

  subtitleTemplate.innerHTML = "";
  const localStyleGroup = document.createElement("optgroup");
  localStyleGroup.label = "本地字幕样式";
  subtitleStyles.forEach((style) => {
    localStyleGroup.appendChild(new Option(style.label, style.value));
  });
  subtitleTemplate.appendChild(localStyleGroup);
  subtitleTemplate.value = [...subtitleTemplate.options].some(
    (option) => option.value === previousSubtitleTemplate,
  ) ? previousSubtitleTemplate : "clean";
  updateSubtitleStylePreview();

  renderDigitalHumans();
  renderVoiceLibrary([
    ...state.ttsVoices.map((voice) => ({ ...voice, managementSource: "native" })),
    ...legacyVoices.map((voice) => ({ ...voice, managementSource: "legacy" })),
  ]);
  renderPipAssets();
  renderCoverFontOptions();
}

function updateSubtitleStylePreview() {
  const select = document.querySelector("#subtitleTemplate");
  const preview = document.querySelector("#subtitleStylePreview");
  if (!select || !preview) return;
  const selectedStyle = subtitleStyles.find((style) => style.value === select.value) || subtitleStyles[0];
  preview.dataset.style = selectedStyle.value;
  preview.querySelector("span").textContent = selectedStyle.preview;
}

function renderDigitalHumans() {
  const rows = avatarCatalogRows();
  state.renderedMetaHumans = rows;
  document.querySelector("#digitalHumanCount").textContent = `${rows.length} 个角色`;
  const query = document.querySelector("#avatarSearch")?.value.trim().toLowerCase() || "";
  const visibleRows = rows.map((item, index) => ({ item, index })).filter(({ item, index }) => {
    const name = profileDisplayName("avatars", item, `数字人 ${index + 1}`);
    return !query || `${name} ${item.usage || ""} ${item.type || item.asset_type || ""}`.toLowerCase().includes(query);
  });
  const container = document.querySelector("#digitalHumanTable");
  container.innerHTML = visibleRows.length
    ? visibleRows.map(({ item, index }) => {
        const profile = profileFor("avatars", item, `avatar_${index}`);
        const imageUrl = resolveAssetUrl(profile.image_url) || defaultAvatarImage(item, index);
        const name = profile.display_name || displayName(item, `数字人 ${index + 1}`);
        return `<article class="profile_card">
          <div class="profile_media"><img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(name)}" loading="lazy" data-preview-image="true" data-preview-title="${escapeHtml(name)}" /><span class="source_badge">${escapeHtml(item.source)}</span></div>
          <div class="profile_body"><div><h3>${escapeHtml(name)}</h3><p>${escapeHtml(item.usage || "口播视频与内容讲解")}</p></div>
          <div class="profile_meta"><span class="status_tag${item.license_status === "test_only" ? " warning" : ""}">${item.license_status === "test_only" ? "仅限测试" : item.license_status === "commercial_ok" ? "可用于正式项目" : "授权待确认"}</span><span>${escapeHtml(item.pose || item.type || item.asset_type || "数字人形象")}</span></div>
          <div class="item_actions"><button type="button" data-action="rename-avatar" data-index="${index}">修改名称</button><button type="button" data-action="change-avatar-image" data-index="${index}">更换图片</button>${item.managementSource === "legacy" ? `<button class="danger" type="button" data-action="delete-avatar" data-index="${index}">删除</button>` : ""}</div></div>
        </article>`;
      }).join("")
    : `<div class="empty_state">${query ? "没有符合条件的数字人" : "尚未读取到数字人资产"}</div>`;
}

function renderVoiceLibrary(voices = []) {
  const container = document.querySelector("#voiceLibrary");
  state.renderedVoices = voices;
  document.querySelector("#voiceCount").textContent = `${voices.length} 个声音`;
  const query = document.querySelector("#voiceSearch")?.value.trim().toLowerCase() || "";
  const visibleVoices = voices.map((voice, index) => ({ voice, index })).filter(({ voice, index }) => {
    const name = profileDisplayName("voices", voice, `声音 ${index + 1}`);
    return !query || `${name} ${voice.text || ""} ${voice.description || ""}`.toLowerCase().includes(query);
  });
  container.innerHTML = visibleVoices.length
    ? visibleVoices.map(({ voice, index }) => {
        const profile = profileFor("voices", voice, `voice_${index}`);
        const name = profile.display_name || displayName(voice, `声音 ${index + 1}`);
        const imageUrl = resolveAssetUrl(profile.image_url) || defaultVoicePortrait(index);
        const category = voice.managementSource === "legacy" ? "克隆声音" : "合成声音";
        return `<article class="voice_card"><img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(name)}" loading="lazy" data-preview-image="true" data-preview-title="${escapeHtml(name)}" /><div class="voice_card_body"><div><span class="source_badge">${category}</span><h3>${escapeHtml(name)}</h3><p>${escapeHtml(voice.text || voice.description || "适合自然口播与内容讲解")}</p></div><div class="item_actions"><button type="button" data-action="preview-voice" data-index="${index}">试听</button><button type="button" data-action="rename-voice" data-index="${index}">改名</button><button type="button" data-action="change-voice-image" data-index="${index}">换图</button>${voice.managementSource === "legacy" ? `<button class="danger" type="button" data-action="delete-voice" data-index="${index}">删除</button>` : ""}</div></div></article>`;
      }).join("")
    : `<div class="empty_state">${query ? "没有符合条件的声音" : "尚未读取到声音资产"}</div>`;
}

function renderPipAssets() {
  const remoteAssets = unwrapList(state.catalog?.assets);
  const assets = [...state.localPipAssets, ...remoteAssets];
  state.pipAssets = assets;
  const gallery = document.querySelector("#pipAssetGallery");
  gallery.innerHTML = assets.length
    ? assets
        .map(
          (item, index) => `
            <article class="asset_card${state.selectedPipAsset === item ? " selected" : ""}">
              <div class="asset_thumbnail">${String(item.type || item.mime || "").includes("video") ? `<video src="${escapeHtml(item.file || item.url || "")}" muted preload="metadata"></video>` : `<img src="${escapeHtml(item.file || item.url || item.path || "./assets/cover-placeholder.svg")}" alt="${escapeHtml(displayName(item, `素材 ${index + 1}`))}" loading="lazy" data-preview-image="true" data-preview-title="${escapeHtml(displayName(item, `素材 ${index + 1}`))}" />`}</div>
              <strong>${escapeHtml(displayName(item, `素材 ${index + 1}`))}</strong>
              <span>${escapeHtml(String(item.type || item.mime || "辅助画面").includes("video") ? "视频素材" : "图片素材")}</span>
              <div class="item_actions"><button type="button" data-action="select-pip" data-index="${index}">${state.selectedPipAsset === item ? "已选中" : "选用"}</button>${item.id != null ? `<button type="button" data-action="rename-pip" data-index="${index}">改名</button><button class="danger" type="button" data-action="delete-pip" data-index="${index}">删除</button>` : ""}</div>
            </article>`,
        )
        .join("")
    : '<div class="empty_state">尚未加入辅助画面素材</div>';
}

function renderCoverFontOptions() {
  const fonts = unwrapList(state.catalog?.fonts);
  for (const id of ["coverFont1", "coverFont2"]) {
    const select = document.querySelector(`#${id}`);
    if (!select) continue;
    const previous = select.value;
    select.innerHTML = fonts
      .map((font, index) => `<option value="${escapeHtml(font.file || font.url || "")}">${escapeHtml(displayName(font, `字体 ${index + 1}`))}</option>`)
      .join("");
    if (previous && [...select.options].some((option) => option.value === previous)) select.value = previous;
  }
}

function subtitleSeconds(value) {
  if (typeof value === "number") return value;
  const raw = String(value || "").trim().replace(",", ".");
  if (!raw) return 0;
  const parts = raw.split(":").map(Number);
  if (parts.some((part) => !Number.isFinite(part))) return Number(raw) || 0;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return parts[0] || 0;
}

function renderSubtitleEditor() {
  const assets = state.pipAssets;
  const assetOptions = [
    '<option value="">不使用辅助画面</option>',
    ...assets.map((asset, index) => `<option value="${index}">${escapeHtml(displayName(asset, `素材 ${index + 1}`))}</option>`),
  ].join("");
  const container = document.querySelector("#subtitleEditorRows");
  container.innerHTML = state.subtitleRows.length
    ? state.subtitleRows
        .map((row, index) => {
          const selectedIndex = assets.findIndex((asset) => (asset.file || asset.url) === row.url);
          return `<div class="subtitle_editor_row" data-index="${index}">
            <span class="subtitle_editor_index">#${index + 1}<br><small>${escapeHtml(row.start || "")} - ${escapeHtml(row.end || "")}</small></span>
            <label>字幕文字<input data-field="content" type="text" value="${escapeHtml(row.content || row.text || "")}" /></label>
            <label>辅助画面<select data-field="asset">${assetOptions}</select></label>
            <label>X<input data-field="x" type="number" min="0" value="${Number(row.pipLayout?.x || 0)}" /></label>
            <label>Y<input data-field="y" type="number" min="0" value="${Number(row.pipLayout?.y || 0)}" /></label>
            <label>宽度<input data-field="width" type="number" min="80" value="${Number(row.pipLayout?.width || 420)}" /></label>
          </div>`;
        })
        .join("")
    : '<div class="empty_state">请先生成字幕</div>';
  state.subtitleRows.forEach((row, index) => {
    const selectedIndex = assets.findIndex((asset) => (asset.file || asset.url) === row.url);
    const select = container.querySelector(`.subtitle_editor_row[data-index="${index}"] [data-field="asset"]`);
    if (select) select.value = selectedIndex >= 0 ? String(selectedIndex) : "";
  });
}

function renderServiceList() {
  const container = document.querySelector("#serviceList");
  if (!state.system?.workers) {
    container.innerHTML = '<div class="empty_state">正在检测本地服务</div>';
    return;
  }
  container.innerHTML = state.system.workers
    .map((worker) => {
      const labels = { tts_worker: "声音合成", avatar_worker: "数字人驱动", render_worker: "视频合成", legacy_engine_adapter: "本地素材引擎", content_worker: "文案模型" };
      const ready = worker.status === "connected";
      const partial = worker.status === "adapter_only" || worker.status === "legacy_bridge_enabled";
      return `
        <div class="service_item">
          <div><strong>${escapeHtml(labels[worker.id] || worker.label)}</strong><span>${escapeHtml(worker.url || "本地服务")}</span></div>
          <span class="status_tag${ready ? "" : " warning"}">${ready ? "已连接" : partial ? "基础服务在线" : "未连接"}</span>
        </div>`;
    })
    .join("");
}

function renderCapabilities() {
  const grid = document.querySelector("#capabilityGrid");
  const availableCount = state.capabilities.filter((item) => ["available", "review_required"].includes(item.status)).length;
  document.querySelector("#capabilitySummary").textContent = `${availableCount}/${state.capabilities.length} 已接通`;
  grid.innerHTML = state.capabilities
    .map((item) => {
      const statusLabel = item.status === "available" ? "可用" : item.status === "review_required" ? "需审核" : "服务未启动";
      const sourceLabel = item.source === "native" ? "本机服务" : "扩展能力";
      return `<div class="capability_item"><span>${escapeHtml(item.group)} · ${sourceLabel}</span><strong>${escapeHtml(item.label)}</strong><span>${statusLabel}</span></div>`;
    })
    .join("");
}

function normalizeMediaUrl(path) {
  if (!path) return null;
  if (/^https?:\/\//i.test(path)) return path;
  const normalized = String(path).replaceAll("\\", "/");
  const marker = "/outputs/generated_media/";
  const markerIndex = normalized.toLowerCase().indexOf(marker);
  if (markerIndex >= 0) {
    return `${apiBaseUrl}/media/${normalized.slice(markerIndex + marker.length)}`;
  }
  return null;
}

function isSampleJob(job) {
  return Boolean(job.dry_run || job.project_id === "demo_project" || String(job.job_id || "").startsWith("demo_"));
}

function isActiveJob(job) {
  return ["queued", "running"].includes(job.status);
}

function formatJobTime(value) {
  if (!value) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = (part) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function formatJobDuration(job) {
  if (!isActiveJob(job) && !job.completed_at) return "未记录";
  const start = new Date(job.started_at || job.created_at || 0).getTime();
  const end = new Date(job.completed_at || Date.now()).getTime();
  if (!start || Number.isNaN(start) || Number.isNaN(end)) return "未记录";
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分 ${seconds % 60} 秒`;
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}

function renderJobStages(job) {
  const stageLabels = { tts: "语音生成", avatar: "口型匹配", render: "字幕与合成" };
  const statusLabels = { queued: "等待", running: "处理中", completed: "完成", skipped: "跳过", failed: "失败" };
  const stages = ["tts", "avatar", "render"].map((stageName) => (
    (job.stages || []).find((item) => item.stage === stageName)
      || { stage: stageName, status: "queued", message: "等待处理" }
  ));
  return stages.map((stage) => `
    <div class="job_stage ${escapeHtml(stage.status || "queued")}">
      <span class="job_stage_icon" aria-hidden="true"></span>
      <div><strong>${escapeHtml(stageLabels[stage.stage] || stage.stage)}</strong><small>${escapeHtml(stage.message || statusLabels[stage.status] || "等待")}</small></div>
      <b>${escapeHtml(statusLabels[stage.status] || "等待")}</b>
    </div>`).join("");
}

function updateWorkbenchFromJob(job) {
  if (!job || job.job_id !== state.activeJobId) return;
  setPipelineStages(job.stages || []);
  document.querySelector("#renderProgress").textContent = `${Number(job.progress || 0)}%`;
  const stateLabels = { queued: "排队中", running: "生成中", qa_required: "等待审片", failed: "生成失败" };
  document.querySelector("#generationState").textContent = stateLabels[job.status] || "已完成";
  if (job.export_path) {
    state.lastExportPath = job.export_path;
    document.querySelector("#publishVideoPath").value = job.export_path;
    const url = normalizeMediaUrl(job.export_path);
    if (url) {
      videoPreview.src = url;
      videoPreview.hidden = false;
      presenterImage.hidden = true;
      document.querySelector("#previewCaption").hidden = true;
    }
  }
  if (job.cover_path) {
    state.coverPath = normalizeMediaUrl(job.cover_path) || job.cover_path;
    document.querySelector("#coverPreview").src = state.coverPath;
  }
}

async function refreshJobsOnly() {
  if (state.jobRefreshInFlight) return;
  state.jobRefreshInFlight = true;
  try {
    state.jobs = await apiRequest("/api/jobs");
    renderJobs();
    updateWorkbenchFromJob(state.jobs.find((job) => job.job_id === state.activeJobId));
  } finally {
    state.jobRefreshInFlight = false;
  }
}

function syncJobPolling() {
  if (state.jobPollingTimer) {
    window.clearInterval(state.jobPollingTimer);
    state.jobPollingTimer = null;
  }
  const shouldPoll = state.activeView === "jobs" || state.jobs.some(isActiveJob);
  if (shouldPoll) {
    state.jobPollingTimer = window.setInterval(() => runAction(() => refreshJobsOnly()), 2000);
  }
}

function renderJobs() {
  const container = document.querySelector("#jobList");
  const realJobs = state.jobs.filter((job) => !isSampleJob(job));
  const sampleJobs = state.jobs.filter(isSampleJob);
  document.querySelector("#realJobCount").textContent = realJobs.length;
  document.querySelector("#sampleJobCount").textContent = sampleJobs.length;
  const jobs = state.jobScope === "samples" ? sampleJobs : realJobs;
  const activeJobs = state.jobs.filter(isActiveJob);
  const clearButton = document.querySelector("#clearCurrentJobs");
  clearButton.hidden = !jobs.length;
  clearButton.disabled = jobs.length > 0 && jobs.every(isActiveJob);
  document.querySelector("#deliveryResetJobs").disabled = Boolean(activeJobs.length);
  document.querySelector("#jobLiveStatus").textContent = activeJobs.length
    ? `${activeJobs.length} 条任务生成中 · 每 2 秒刷新`
    : "每 2 秒自动刷新";
  const statusLabels = { queued: "排队中", running: "生成中", qa_required: "等待审核", approved: "已审核", exported: "已导出", failed: "失败" };
  container.innerHTML = jobs.length
    ? jobs.map((job) => {
      const exportUrl = normalizeMediaUrl(job.export_path);
      const progress = Math.max(0, Math.min(100, Number(job.progress || 0)));
      const active = isActiveJob(job);
      return `
        <article class="job_card${active ? " active_job" : ""}">
          <div class="panel_actions">
            <div><span class="source_badge">${isSampleJob(job) ? "验收样例" : "正式任务"}</span><h3>${escapeHtml(job.title || "数字人视频任务")}</h3></div>
            <span class="status_tag${job.status === "failed" ? " warning" : ""}${active ? " live" : ""}">${escapeHtml(statusLabels[job.status] || "等待处理")}</span>
          </div>
          <p>${escapeHtml(job.description || "本地生成任务")}</p>
          <div class="job_avatar"><span>所选数字人</span><strong>${escapeHtml(job.avatar_name || job.avatar_id || "旧任务未记录")}</strong><small>${job.avatar_source === "image_avatar" ? "单图人物驱动" : job.avatar_source ? "模板视频驱动" : "驱动方式未记录"}</small></div>
          <div class="job_time_grid">
            <span><small>提交时间</small><strong>${escapeHtml(formatJobTime(job.created_at))}</strong></span>
            <span><small>开始时间</small><strong>${escapeHtml(formatJobTime(job.started_at))}</strong></span>
            <span><small>${active ? "已运行" : "总耗时"}</small><strong>${escapeHtml(formatJobDuration(job))}</strong></span>
            <span><small>完成时间</small><strong>${escapeHtml(formatJobTime(job.completed_at))}</strong></span>
          </div>
          <div class="job_stage_list">${renderJobStages(job)}</div>
          <div class="job_progress_row"><div class="progress_bar" role="progressbar" aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="100"><span style="width:${progress}%"></span></div><strong>${progress}%</strong></div>
          <div class="job_footer">
            <span>任务编号 ${escapeHtml(job.job_id || "未记录")}</span>
            <div class="job_footer_actions">${exportUrl ? `<a class="job_link" href="${escapeHtml(exportUrl)}" target="_blank" rel="noreferrer">查看成片</a>` : ""}<button class="text_button danger" type="button" data-action="delete-job" data-job-id="${escapeHtml(job.job_id)}" ${active ? 'disabled title="生成中的任务不能删除"' : ""}>删除</button></div>
          </div>
        </article>`;
    }).join("")
    : `<div class="empty_state">${state.jobScope === "samples" ? "没有样例或验收任务" : "尚无正式生成任务"}</div>`;
  syncJobPolling();
}

function pickText(payload, preferredKeys = ["text", "content", "result", "title"]) {
  if (typeof payload === "string") return payload;
  if (!payload || typeof payload !== "object") return "";
  for (const key of preferredKeys) {
    if (typeof payload[key] === "string" && payload[key].trim()) return payload[key];
  }
  if (payload.data) return pickText(payload.data, preferredKeys);
  return "";
}

function pickMediaUrl(payload) {
  if (typeof payload === "string" && /^https?:\/\//i.test(payload)) return payload;
  if (!payload || typeof payload !== "object") return "";
  for (const key of ["url", "file", "file_url", "audio_file", "video_file", "path", "result"]) {
    const value = payload[key];
    if (typeof value === "string" && /^https?:\/\//i.test(value)) return value;
  }
  return pickMediaUrl(payload.data);
}

function selectedLegacyTemplate() {
  const key = document.querySelector("#subtitleTemplate").value;
  return unwrapList(state.catalog?.clip_templates).find((item) => (item.key || item.name) === key) || null;
}

function selectedVoiceConfig() {
  const option = document.querySelector("#voiceSelect").selectedOptions[0];
  return {
    voiceId: option?.value || "clear_male_zh",
    voiceSource: option?.dataset.source || "native_tts",
    promptAudio: option?.dataset.promptAudio || "",
  };
}

function selectedLegacyFont(template) {
  const fontName = String(template?.template?.srt?.font_name || "").toLowerCase();
  const fonts = unwrapList(state.catalog?.fonts);
  return fonts.find((item) => String(item.name || item.file_name || "").toLowerCase().includes(fontName)) || fonts[0] || null;
}

async function uploadLegacyFile(file, key = "temp_uploads") {
  const body = new FormData();
  body.append("file", file, file.name);
  body.append("overwrite", "true");
  body.append("key", key);
  const result = assertLegacySuccess(
    await apiRequest("/api/legacy/files/upload/", { method: "POST", body }),
    "本地文件上传失败",
  );
  const url = pickMediaUrl(result);
  if (!url) throw new Error("文件上传成功但没有返回文件地址");
  return url;
}

async function previewVoicePickerEntry(entry, button) {
  if (!entry) return;
  const select = document.querySelector("#voiceSelect");
  select.value = entry.id;
  select.dispatchEvent(new Event("change"));
  await withBusy(button, "生成中", async () => {
    if (entry.source === "legacy_engine" && entry.promptAudio) {
      audioPreview.src = resolveAssetUrl(entry.promptAudio);
      audioPreview.hidden = false;
      await audioPreview.play();
      return;
    }
    const result = await apiRequest("/api/tts/preview", {
      method: "POST",
      body: JSON.stringify({
        text: voicePreviewScript,
        voice_id: entry.id,
        speed: Number(document.querySelector("#speedRange").value),
        dry_run: false,
      }),
    });
    const workerJob = result?.worker_job || result;
    if (workerJob?.status === "failed") throw new Error(workerJob.message || "试听生成失败");
    const url = normalizeMediaUrl(workerJob?.audio_path);
    if (!url) throw new Error("声音服务没有返回试听文件");
    audioPreview.src = url;
    audioPreview.hidden = false;
    await audioPreview.play();
  });
}

function openAvatarVideoPreview(entry) {
  if (!entry?.videoUrl) return showToast("这个形象没有可播放的模板视频");
  const dialog = document.querySelector("#assetVideoPreviewDialog");
  const preview = document.querySelector("#assetVideoPreview");
  document.querySelector("#assetVideoPreviewTitle").textContent = `${entry.name} · 动作预览`;
  preview.src = entry.videoUrl;
  dialog.showModal();
  preview.play().catch(() => {});
}

function closeAvatarVideoPreview() {
  const preview = document.querySelector("#assetVideoPreview");
  preview.pause();
  preview.removeAttribute("src");
  preview.load();
  document.querySelector("#assetVideoPreviewDialog").close();
}

async function importBackgroundMusic() {
  const input = document.querySelector("#backgroundMusicFile");
  const file = input.files?.[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file, file.name);
  body.append("name", file.name.replace(/\.[^.]+$/, ""));
  const response = await apiRequest("/api/media/background-music", { method: "POST", body });
  const result = response?.item || response;
  input.value = "";
  await loadAll();
  const url = resolveAssetUrl(result.url);
  const select = document.querySelector("#musicSelect");
  if ([...select.options].some((option) => option.value === url)) select.value = url;
  document.querySelector("#backgroundMusicEnabled").checked = true;
  select.disabled = false;
  await previewBackgroundMusic();
  scheduleWorkbenchDraftSave();
  showToast(`背景音乐“${displayName(result, "本地音乐")}”已导入`);
}

async function previewBackgroundMusic() {
  const url = document.querySelector("#musicSelect").value;
  if (!url) return showToast("请先选择背景音乐");
  const player = document.querySelector("#musicPreview");
  if (player.src !== url) player.src = url;
  player.hidden = false;
  await player.play();
}

async function prepareVoiceReference(file) {
  const body = new FormData();
  body.append("file", file, file.name);
  const prepared = await apiRequest("/api/media/voice-reference", { method: "POST", body });
  const response = await fetch(resolveAssetUrl(prepared.media_url));
  if (!response.ok) throw new Error("无法读取处理后的参考声音");
  const wavFile = new File([await response.blob()], `voice_reference_${Date.now()}.wav`, { type: "audio/wav" });
  return { ...prepared, legacyUrl: await uploadLegacyFile(wavFile, "voice_uploads") };
}

function setVoiceCloneMode(mode) {
  state.voiceCloneMode = mode;
  document.querySelectorAll("[data-clone-mode]").forEach((button) => button.classList.toggle("active", button.dataset.cloneMode === mode));
  document.querySelector("#voiceCloneRecordPanel").hidden = mode !== "record";
  document.querySelector("#voiceCloneUploadPanel").hidden = mode !== "upload";
  const text = document.querySelector('#voiceCloneForm textarea[name="text"]');
  if (mode === "record") text.value = voiceCloneScript;
  if (mode === "upload" && text.value.trim() === voiceCloneScript) text.value = "";
}

function stopVoiceRecordingTracks() {
  state.voiceRecordingStream?.getTracks().forEach((track) => track.stop());
  state.voiceRecordingStream = null;
  window.clearInterval(state.voiceRecordingTimer);
  window.clearTimeout(state.voiceRecordingAutoStopTimer);
  state.voiceRecordingTimer = null;
  state.voiceRecordingAutoStopTimer = null;
}

async function startVoiceRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error("当前浏览器不支持直接录音");
  stopVoiceRecordingTracks();
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  const chunks = [];
  const recorder = new MediaRecorder(stream);
  state.voiceRecorder = recorder;
  state.voiceRecordingStream = stream;
  state.voiceRecordingStartedAt = Date.now();
  state.voiceRecordingFile = null;
  recorder.addEventListener("dataavailable", (event) => { if (event.data.size) chunks.push(event.data); });
  recorder.addEventListener("stop", () => {
    const mimeType = recorder.mimeType || "audio/webm";
    state.voiceRecordingFile = new File([new Blob(chunks, { type: mimeType })], `voice_recording_${Date.now()}.webm`, { type: mimeType });
    const player = document.querySelector("#voiceRecordingPreview");
    player.src = URL.createObjectURL(state.voiceRecordingFile);
    player.hidden = false;
    const duration = Math.min(voiceCloneMaxSeconds, Math.max(1, Math.round((Date.now() - state.voiceRecordingStartedAt) / 1000)));
    document.querySelector("#voiceRecordingStatus").textContent = `录音完成 · ${duration} 秒`;
    stopVoiceRecordingTracks();
  });
  recorder.start(500);
  document.querySelector("#startVoiceRecording").disabled = true;
  document.querySelector("#stopVoiceRecording").disabled = false;
  document.querySelector("#voiceRecordingStatus").textContent = "正在录音 · 0 秒";
  state.voiceRecordingTimer = window.setInterval(() => {
    const elapsed = Math.min(voiceCloneMaxSeconds, Math.floor((Date.now() - state.voiceRecordingStartedAt) / 1000));
    document.querySelector("#voiceRecordingStatus").textContent = `正在录音 · ${elapsed}/${voiceCloneMaxSeconds} 秒`;
  }, 1000);
  state.voiceRecordingAutoStopTimer = window.setTimeout(() => {
    if (state.voiceRecorder?.state !== "recording") return;
    stopVoiceRecording();
    showToast("录音已达到 40 秒，系统已自动停止");
  }, 39500);
}

function stopVoiceRecording() {
  if (state.voiceRecorder?.state === "recording") state.voiceRecorder.stop();
  document.querySelector("#startVoiceRecording").disabled = false;
  document.querySelector("#stopVoiceRecording").disabled = true;
}

function srtTimestamp(seconds) {
  const millis = Math.max(0, Math.round(Number(seconds || 0) * 1000));
  const hours = Math.floor(millis / 3600000);
  const minutes = Math.floor((millis % 3600000) / 60000);
  const secs = Math.floor((millis % 60000) / 1000);
  const ms = millis % 1000;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")},${String(ms).padStart(3, "0")}`;
}

function createSrtFile(rows) {
  const content = rows
    .map((row, index) => `${index + 1}\n${srtTimestamp(subtitleSeconds(row.start))} --> ${srtTimestamp(subtitleSeconds(row.end))}\n${row.content || row.text || ""}\n`)
    .join("\n");
  return new File([content], `metahuman_subtitles_${Date.now()}.srt`, { type: "application/x-subrip;charset=utf-8" });
}

function readLegacyProgress(payload, fallbackMessage) {
  assertLegacySuccess(payload, fallbackMessage);
  const data = payload?.data;
  if (typeof data === "string" && /^https?:\/\//i.test(data)) return { done: true, url: data, progress: 100 };
  if (!data || typeof data !== "object") return { done: false, progress: null };
  const status = String(data.status || "").toLowerCase();
  if (["failed", "error"].includes(status)) throw new Error(data.message || fallbackMessage);
  if (["done", "success", "completed"].includes(status)) {
    const url = data.url || data.urlData || pickMediaUrl(data);
    if (!url) throw new Error(`${fallbackMessage}：任务完成但没有返回文件地址`);
    return { done: true, url, progress: 100 };
  }
  const rawProgress = typeof data.data === "number" ? data.data : data.progress;
  return { done: false, progress: Number.isFinite(Number(rawProgress)) ? Math.round(Number(rawProgress)) : null };
}

async function pollLegacyProgress(path, fallbackMessage, onProgress) {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const result = readLegacyProgress(await apiRequest(path), fallbackMessage);
    if (result.progress != null) onProgress?.(result.progress);
    if (result.done) return result.url;
    await new Promise((resolve) => window.setTimeout(resolve, 2000));
  }
  throw new Error(`${fallbackMessage}：等待超时`);
}

async function withBusy(button, busyLabel, operation) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = busyLabel;
  try {
    return await operation();
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function extractDouyin() {
  const button = document.querySelector("#extractDouyin");
  const url = document.querySelector("#douyinUrl").value.trim();
  if (!url) return showToast("请先粘贴抖音作品链接");
  await withBusy(button, "提取中...", async () => {
    const result = assertLegacySuccess(await apiRequest("/api/content/douyin/extract", {
      method: "POST",
      body: JSON.stringify({ text: url }),
    }), "抖音文案提取失败");
    const text = pickText(result);
    if (!text) throw new Error("文案服务没有返回可用内容");
    scriptInput.value = text;
    scriptInput.dataset.edited = "true";
    updateScriptStats();
    scheduleWorkbenchDraftSave();
    showToast("文案已提取");
    if (document.querySelector("#autoMode").checked) await runAutoWorkflow();
  });
}

async function runAutoWorkflow() {
  showToast("自动模式已启动，将依次生成文案、标题、音频、视频、字幕和成片");
  await rewriteScript();
  await generateTitle();
  await previewVoice();
  await generateVideo();
  await generateSubtitles();
  await submitLegacyClip();
  if (document.querySelector("#makeCover").checked) await generateCover();
  showToast("自动模式已完成，请人工审片后再发布");
}

async function rewriteScript() {
  const button = document.querySelector("#rewriteScript");
  if (!scriptInput.value.trim()) return showToast("请先输入口播文案");
  await withBusy(button, "仿写中...", async () => {
    const mode = document.querySelector("#rewriteMode").value;
    const modePrompts = {
      polish: "在不改变事实与核心观点的前提下，将文案润色得自然、可信、适合真人口播。不要虚构数据或案例。",
      shorten: "在不改变事实与核心观点的前提下精简文案，删除重复内容，保留关键信息并保持自然口语表达。",
    };
    const result = assertLegacySuccess(await apiRequest("/api/content/rewrite", {
      method: "POST",
      body: JSON.stringify({
        text: scriptInput.value.trim(),
        prompt1: mode === "custom" ? document.querySelector("#legacyPrompt1").value : modePrompts[mode] || "",
        prompt2: mode === "custom" ? document.querySelector("#legacyPrompt2").value : "",
      }),
    }), "DeepSeek 文案改写失败");
    const text = pickText(result);
    if (!text) throw new Error("文案服务没有返回改写结果");
    scriptInput.value = text;
    scriptInput.dataset.edited = "true";
    updateScriptStats();
    scheduleWorkbenchDraftSave();
    showToast("文案仿写完成");
  });
}

async function generateTitle() {
  const button = document.querySelector("#generateTitle");
  if (!scriptInput.value.trim()) return showToast("请先输入口播文案");
  await withBusy(button, "生成中...", async () => {
    const result = assertLegacySuccess(await apiRequest("/api/content/title", {
      method: "POST",
      body: JSON.stringify({ text: scriptInput.value.trim() }),
    }), "DeepSeek 标题生成失败");
    const data = result?.data || result || {};
    document.querySelector("#videoTitle").value = data.title || pickText(data, ["title"]) || "";
    const topics = data.topics || data.tags || [];
    document.querySelector("#videoTopics").value = Array.isArray(topics) ? topics.join(" ") : String(topics || "");
    scheduleWorkbenchDraftSave();
    showToast("标题与话题已生成");
  });
}

async function transcribeMedia() {
  const button = document.querySelector("#transcribeMedia");
  const file = document.querySelector("#asrFileInput").files[0];
  if (!file) return showToast("请先选择音频或视频文件");
  await withBusy(button, "识别中...", async () => {
    const fileUrl = await uploadLegacyFile(file, "temp_uploads");
    const result = assertLegacySuccess(await apiRequest("/api/legacy/text/asr/", {
      method: "POST",
      body: JSON.stringify({ audio_file: fileUrl }),
    }), "语音识别失败");
    const text = pickText(result);
    if (!text) throw new Error("语音识别完成但没有返回文字");
    scriptInput.value = text;
    scriptInput.dataset.edited = "true";
    updateScriptStats();
    scheduleWorkbenchDraftSave();
    showToast("音视频文案识别完成");
  });
}

async function generateSubtitles() {
  const button = document.querySelector("#subtitleGenerateProxy");
  if (!state.lastAudioPath) return showToast("请先生成音频");
  if (state.subtitleRows.length && state.subtitleSourceText === scriptInput.value.trim()) {
    document.querySelector("#generationState").textContent = `字幕 ${state.subtitleRows.length} 行`;
    renderSubtitleEditor();
    return showToast(`已使用语音时间轴生成 ${state.subtitleRows.length} 行单行字幕`);
  }
  await withBusy(button, "生成中...", async () => {
    const audioUrl = normalizeMediaUrl(state.lastAudioPath) || state.lastAudioPath;
    const result = assertLegacySuccess(await apiRequest("/api/legacy/srt/", {
      method: "POST",
      body: JSON.stringify({ audio_file: audioUrl }),
    }), "字幕生成失败");
    state.subtitleRows = unwrapList(result).map((row, index) => ({
      ...row,
      index: index + 1,
      content: row.content || row.text || "",
      url: row.url || "",
      pipLayout: row.pipLayout || null,
    }));
    state.subtitleSourceText = scriptInput.value.trim();
    if (!state.subtitleRows.length) throw new Error("字幕服务没有返回字幕行");
    document.querySelector("#generationState").textContent = `字幕 ${state.subtitleRows.length} 行`;
    renderSubtitleEditor();
    showToast(`字幕已生成，共 ${state.subtitleRows.length} 行`);
  });
}

function openSubtitleEditor() {
  if (!state.subtitleRows.length) return showToast("请先生成字幕");
  renderSubtitleEditor();
  document.querySelector("#subtitleDialog").showModal();
}

function saveSubtitleEdits() {
  document.querySelectorAll(".subtitle_editor_row").forEach((element) => {
    const index = Number(element.dataset.index);
    const row = state.subtitleRows[index];
    if (!row) return;
    row.content = element.querySelector('[data-field="content"]').value.trim();
    const assetIndex = element.querySelector('[data-field="asset"]').value;
    const asset = assetIndex === "" ? null : state.pipAssets[Number(assetIndex)];
    row.url = asset?.file || asset?.url || "";
    row.pipLayout = row.url
      ? {
          x: Number(element.querySelector('[data-field="x"]').value) || 0,
          y: Number(element.querySelector('[data-field="y"]').value) || 0,
          width: Math.max(80, Number(element.querySelector('[data-field="width"]').value) || 420),
        }
      : null;
  });
  document.querySelector("#subtitleDialog").close();
  showToast("字幕和辅助画面设置已保存");
}

async function previewVoice() {
  const button = document.querySelector("#previewVoice");
  if (!scriptInput.value.trim()) return showToast("请先输入口播文案");
  await withBusy(button, "生成试听...", async () => {
    const voice = selectedVoiceConfig();
    const result = await apiRequest(voice.voiceSource === "legacy_engine" ? "/api/tts/legacy-preview" : "/api/tts/preview", {
      method: "POST",
      body: JSON.stringify({
        text: scriptInput.value.trim().slice(0, 180),
        voice_id: voice.voiceId,
        prompt_audio: voice.promptAudio || null,
        speed: Number(document.querySelector("#speedRange").value),
        dry_run: false,
      }),
    });
    const workerJob = result?.worker_job || result;
    if (workerJob?.status === "failed") throw new Error(workerJob.message || "试听生成失败");
    const url = normalizeMediaUrl(workerJob?.audio_path);
    if (!url) throw new Error("语音服务没有返回可播放文件");
    audioPreview.src = url;
    state.lastAudioPath = workerJob.audio_path;
    if (Array.isArray(workerJob.subtitle_segments) && workerJob.subtitle_segments.length) {
      state.subtitleRows = workerJob.subtitle_segments.map((row, index) => ({
        index: index + 1,
        start: row.start,
        end: row.end,
        content: row.text || "",
        url: "",
        pipLayout: null,
      }));
      state.subtitleSourceText = scriptInput.value.trim().slice(0, 180);
    }
    audioPreview.hidden = false;
    await audioPreview.play();
    showToast("试听音频已生成");
  });
}

function setPipelineStages(stages = []) {
  const labels = { completed: "完成", failed: "失败", queued: "排队", running: "处理中", skipped: "跳过" };
  const byName = new Map(stages.map((stage) => [stage.stage, stage.status]));
  document.querySelector("#ttsStage").textContent = labels[byName.get("tts")] || "等待";
  document.querySelector("#avatarStage").textContent = labels[byName.get("avatar")] || "等待";
  document.querySelector("#renderStage").textContent = labels[byName.get("render")] || "等待";
}

async function generateVideo() {
  const button = document.querySelector("#generateVideo");
  if (state.generating) return;
  if (!scriptInput.value.trim()) return showToast("请先输入口播文案");
  state.generating = true;
  document.querySelector("#generationState").textContent = "生成中";
  document.querySelector("#renderProgress").textContent = "10%";
  setPipelineStages([]);
  try {
    await withBusy(button, "正在生成...", async () => {
      const avatarSelect = document.querySelector("#avatarSelect");
      const selectedAvatarOption = avatarSelect.selectedOptions[0];
      const selectedAvatarEntry = state.avatarPickerItems.find((item) => item.id === avatarSelect.value);
      const avatarSource = selectedAvatarEntry?.source || selectedAvatarOption?.dataset.source;
      if (!selectedAvatarOption || !avatarSource) throw new Error("当前数字人模板无效，请重新选择");
      const estimatedSeconds = Math.max(0, scriptInput.value.trim().length / 4.2);
      if (
        selectedAvatarEntry?.maxContinuousSpeechSeconds
        && estimatedSeconds > selectedAvatarEntry.maxContinuousSpeechSeconds
      ) {
        throw new Error(
          `当前动作适合 ${selectedAvatarEntry.maxContinuousSpeechSeconds.toFixed(1)} 秒以内的单段口播，`
          + `这段文案约 ${Math.ceil(estimatedSeconds)} 秒。请缩短文案，或分段生成并用产品界面画面转场。`,
        );
      }
      document.querySelector("#avatarEngine").value = avatarSource;
      const voice = selectedVoiceConfig();
      const coverTitle = document.querySelector("#videoTitle").value.trim() || scriptInput.value.trim();
      const job = await apiRequest("/api/jobs", {
        method: "POST",
        body: JSON.stringify({
          project_id: "studio_project",
          output_category: avatarSource === "image_avatar" ? "image_avatar_videos" : "talking_videos",
          script: scriptInput.value.trim(),
          voice_id: voice.voiceId,
          voice_source: voice.voiceSource,
          legacy_prompt_audio: voice.promptAudio || null,
          avatar_id: avatarSelect.value,
          avatar_name: selectedAvatarEntry?.name || selectedAvatarOption.textContent.trim(),
          avatar_source: avatarSource,
          target_format: document.querySelector("#targetFormat").value,
          speed: Number(document.querySelector("#speedRange").value),
          burn_subtitles: document.querySelector("#burnSubtitles").checked,
          make_cover: document.querySelector("#makeCover").checked,
          cover_title_line_1: coverTitle.slice(0, 10),
          cover_title_line_2: coverTitle.slice(10, 20),
          cover_style: document.querySelector("#coverStyle").value,
          cover_accent_color: document.querySelector("#coverAccentColor").value,
          subtitle_template: document.querySelector("#subtitleTemplate").value,
          background_music_id: document.querySelector("#musicSelect").value || null,
          video_quality: document.querySelector("#videoQuality").value,
          dry_run: false,
        }),
      });
      state.activeJobId = job.job_id;
      state.jobs.unshift(job);
      renderJobs();
      setPipelineStages(job.stages || []);
      const ttsResult = job.stages?.find((stage) => stage.stage === "tts")?.result;
      if (ttsResult?.audio_path) state.lastAudioPath = ttsResult.audio_path;
      if (Array.isArray(ttsResult?.subtitle_segments) && ttsResult.subtitle_segments.length) {
        state.subtitleRows = ttsResult.subtitle_segments.map((row, index) => ({
          index: index + 1,
          start: row.start,
          end: row.end,
          content: row.text || "",
          url: "",
          pipLayout: null,
        }));
        state.subtitleSourceText = scriptInput.value.trim();
      }
      document.querySelector("#renderProgress").textContent = `${job.progress || 0}%`;
      document.querySelector("#generationState").textContent = job.status === "failed" ? "生成失败" : job.status === "queued" ? "排队中" : "生成中";
      if (job.export_path) {
        state.lastExportPath = job.export_path;
        document.querySelector("#publishVideoPath").value = job.export_path;
        const url = normalizeMediaUrl(job.export_path);
        if (url) {
          videoPreview.src = url;
          videoPreview.hidden = false;
          presenterImage.hidden = true;
          document.querySelector("#previewCaption").hidden = true;
        }
      }
      if (job.cover_path) {
        state.coverPath = normalizeMediaUrl(job.cover_path) || job.cover_path;
        document.querySelector("#coverPreview").src = state.coverPath;
      }
      showToast(job.status === "failed" ? "视频生成失败，请到任务中心查看" : "任务已提交，可在任务中心查看实时进度");
      syncJobPolling();
    });
  } catch (error) {
    document.querySelector("#generationState").textContent = "生成失败";
    throw error;
  } finally {
    state.generating = false;
  }
}

async function submitLegacyClip() {
  const button = document.querySelector("#submitClip");
  const videoFile = document.querySelector("#publishVideoPath").value.trim() || state.lastExportPath;
  if (!videoFile) return showToast("请先生成数字人视频");
  await withBusy(button, "提交中...", async () => {
    const [width, height] = document.querySelector("#targetFormat").value.split("x").map(Number);
    const videoUrl = normalizeMediaUrl(videoFile) || (/^https?:\/\//i.test(videoFile) ? videoFile : "");
    if (!videoUrl) throw new Error("剪辑服务需要可访问的成片地址");

    const clips = [{
      type: "FFMPEGVideoClip",
      data: {
        start: 0,
        duration: null,
        file_url: videoUrl,
        position: { x: 0, y: 0 },
        scale: { x: width, y: -1 },
        volume: Number(document.querySelector("#voiceVolume").value),
      },
    }];

    const musicUrl = document.querySelector("#musicSelect").value;
    if (musicUrl) {
      clips.push({ type: "FFMPEGAudioClip", data: { start: 0, duration: -1, file_url: musicUrl, volume: Number(document.querySelector("#backgroundVolume").value) } });
    }

    for (const row of state.subtitleRows) {
      if (!row.url) continue;
      const start = subtitleSeconds(row.start);
      const end = subtitleSeconds(row.end);
      const extension = row.url.split(/[?#]/)[0].split(".").pop().toLowerCase();
      const type = ["jpg", "jpeg", "png", "gif", "bmp", "webp"].includes(extension) ? "FFMPEGImageClip" : "FFMPEGVideoClip";
      clips.push({
        type,
        data: {
          start,
          duration: end > start ? end - start : null,
          file_url: row.url,
          position: { x: Number(row.pipLayout?.x || 0), y: Number(row.pipLayout?.y || 0) },
          scale: { x: Number(row.pipLayout?.width || width), y: -1 },
          ...(type === "FFMPEGVideoClip" ? { volume: 0 } : {}),
        },
      });
    }

    const template = selectedLegacyTemplate() || unwrapList(state.catalog?.clip_templates)[0] || null;
    if (document.querySelector("#burnSubtitles").checked && state.lastAudioPath) {
      let rows = state.subtitleRows;
      if (!rows.length) {
        const audioUrl = normalizeMediaUrl(state.lastAudioPath) || state.lastAudioPath;
        const srtResult = assertLegacySuccess(await apiRequest("/api/legacy/srt/", {
          method: "POST",
          body: JSON.stringify({ audio_file: audioUrl }),
        }), "字幕识别失败");
        rows = unwrapList(srtResult);
        state.subtitleRows = rows;
      }
      if (rows.length && template) {
        const srtUrl = await uploadLegacyFile(createSrtFile(rows), "subtitle_uploads");
        const srtStyle = template.template?.srt || {};
        const font = selectedLegacyFont(template);
        const fontUrl = font?.url || font?.file || font?.font_file || "";
        if (fontUrl) {
          clips.push({
            type: "FFMPEGAssSubtitlesClip",
            data: {
              file: srtUrl,
              font_file: fontUrl,
              font_size: Number(srtStyle.font_size || 70),
              margin_v: Number(srtStyle.margin_bottom || 50),
              margin_l: Number(srtStyle.margin_left_right || 20),
              margin_r: Number(srtStyle.margin_left_right || 20),
              color: `#${String(srtStyle.primary_color || "FFFFFF").replace("#", "")}`,
              stroke_width: 1,
              stroke_color: `#${String(srtStyle.outline_color || "000000").replace("#", "")}`,
              effect: "",
            },
          });
        }
      }
    }

    const result = assertLegacySuccess(await apiRequest("/api/legacy/video/clip_v3/", {
      method: "POST",
      body: JSON.stringify({
        timeline: { width, height, color: "#000000", tracks: [{ clips }], duration: null },
        exporter: {
          fps: 25,
          encoder: document.querySelector('input[name="clip_mode"]:checked')?.value || "libx264",
          video_bitrate: document.querySelector("#videoQuality").value === "high" ? "8M" : "6M",
        },
      }),
    }), "剪辑任务提交失败");
    showToast(result?.message || "剪辑任务已提交");
    document.querySelector("#generationState").textContent = "剪辑中";
    const clipUrl = await pollLegacyProgress(
      "/api/legacy/video/clip_v3/progress/",
      "剪辑失败",
      (progress) => {
        document.querySelector("#renderProgress").textContent = `${progress}%`;
      },
    );
    state.lastExportPath = clipUrl;
    document.querySelector("#publishVideoPath").value = clipUrl;
    videoPreview.src = clipUrl;
    videoPreview.hidden = false;
    presenterImage.hidden = true;
    document.querySelector("#previewCaption").hidden = true;
    document.querySelector("#generationState").textContent = "等待审片";
    document.querySelector("#renderProgress").textContent = "100%";
    showToast("剪辑已完成，请先审片");
  });
}

async function cancelLegacyGeneration() {
  const results = await Promise.allSettled([
    apiRequest("/api/legacy/audio/cancel/", { method: "POST", body: "{}" }),
    apiRequest("/api/legacy/video/meta_human_video/cancel/", { method: "POST", body: "{}" }),
  ]);
  const accepted = results.filter((result) => result.status === "fulfilled").length;
  document.querySelector("#generationState").textContent = "已请求取消";
  showToast(accepted ? "已向音频和数字人服务发送取消请求" : "当前没有可取消的生成任务");
}

async function cancelLegacyClip() {
  const result = assertLegacySuccess(await apiRequest("/api/legacy/video/clip_v3/cancel/", {
    method: "POST",
    body: "{}",
  }), "取消剪辑失败");
  document.querySelector("#generationState").textContent = "剪辑已取消";
  showToast(result?.message || "剪辑取消请求已发送");
}

function openCoverEditor() {
  const title = document.querySelector("#videoTitle").value.trim();
  if (!document.querySelector("#coverTitleLine1").value) document.querySelector("#coverTitleLine1").value = title.slice(0, 8);
  if (!document.querySelector("#coverTitleLine2").value) document.querySelector("#coverTitleLine2").value = title.slice(8, 16);
  document.querySelector("#coverSourcePreview").src = currentCoverSource();
  document.querySelector("#coverSourceLabel").textContent = state.coverSourceOverride ? "当前使用自定义底图" : "当前使用人物封面";
  document.querySelector("#coverDialog").showModal();
}

function currentCoverSource() {
  if (state.coverSourceOverride) return state.coverSourceOverride;
  const selectedAvatar = document.querySelector("#avatarSelect").value;
  const avatar = unwrapList(state.catalog?.meta_humans).find((item, index) => avatarSelectionId(item, `legacy_${index}`) === selectedAvatar);
  if (avatar?.cover) return avatar.cover;
  const selectedEntry = state.avatarPickerItems.find((item) => item.id === selectedAvatar);
  if (selectedEntry?.imageUrl) return new URL(selectedEntry.imageUrl, window.location.href).href;
  const latestCover = state.jobs.find((job) => job.cover_path)?.cover_path;
  if (latestCover) return normalizeMediaUrl(latestCover) || latestCover;
  return new URL(presenterImage.getAttribute("src"), window.location.href).href;
}

async function captureCoverFrame() {
  const button = document.querySelector("#captureCoverFrame");
  const videoSource = document.querySelector("#publishVideoPath").value.trim() || state.lastExportPath || videoPreview.src;
  if (!videoSource) return showToast("请先生成成片，再从视频中选择关键帧");
  await withBusy(button, "取帧中...", async () => {
    const result = await apiRequest("/api/media/video-frame", {
      method: "POST",
      body: JSON.stringify({ video_source: videoSource, time_seconds: Number(document.querySelector("#coverFrameTime").value) || 0 }),
    });
    state.coverSourceOverride = resolveAssetUrl(result.image_url);
    document.querySelector("#coverSourcePreview").src = state.coverSourceOverride;
    document.querySelector("#coverSourceLabel").textContent = `已使用成片 ${Number(result.time_seconds || 0).toFixed(1)} 秒画面`;
    showToast("已提取视频关键帧");
  });
}

async function uploadCoverSourceImage(file) {
  if (!file) return;
  const key = `cover_${Date.now()}`;
  const dataUrl = await imageFileToDataUrl(file);
  const result = await apiRequest("/api/ui/images", {
    method: "POST",
    body: JSON.stringify({ kind: "covers", key, data_url: dataUrl }),
  });
  state.coverSourceOverride = resolveAssetUrl(result.image_url);
  document.querySelector("#coverSourcePreview").src = state.coverSourceOverride;
  document.querySelector("#coverSourceLabel").textContent = `已上传底图：${file.name}`;
  showToast("封面底图已更新");
}

async function generateCover() {
  const button = document.querySelector("#generateCover");
  const line1 = document.querySelector("#coverTitleLine1").value.trim();
  const line2 = document.querySelector("#coverTitleLine2").value.trim();
  if (!line1 && !line2) return showToast("请至少输入一行封面文字");
  await withBusy(button, "生成中...", async () => {
    const result = await apiRequest("/api/media/designed-cover", {
      method: "POST",
      body: JSON.stringify({
        image_source: currentCoverSource(),
        title_line_1: line1,
        title_line_2: line2,
        style: document.querySelector("#coverStyle").value,
        target_format: document.querySelector("#targetFormat").value,
        accent_color: document.querySelector("#coverAccentColor").value,
      }),
    });
    const url = resolveAssetUrl(result.image_url);
    if (!url) throw new Error("封面服务没有返回图片地址");
    state.coverPath = url;
    document.querySelector("#coverPreview").src = url;
    document.querySelector("#coverDialog").close();
    showToast("封面已生成");
  });
}

async function submitPublish() {
  const button = document.querySelector("#submitPublish");
  if (!document.querySelector("#reviewApproved").checked) return showToast("发布前必须完成人工审核");
  const selectedAvatar = state.avatarPickerItems.find((item) => item.id === document.querySelector("#avatarSelect").value);
  if (selectedAvatar?.licenseStatus === "test_only") return showToast("当前数字人模板仅限内部测试，不能提交正式发布");
  const videoFile = document.querySelector("#publishVideoPath").value.trim();
  if (!videoFile) return showToast("请先生成或填写成片路径");
  const platforms = [...document.querySelectorAll("#publishPlatform input:checked")].map((input) => input.value);
  if (!platforms.length) return showToast("请至少选择一个发布平台");
  const includeCover = document.querySelector('input[name="publish_cover_mode"]:checked')?.value === "with_cover";
  if (includeCover && !state.coverPath) return showToast("请先制作封面，或选择直接发布");
  await withBusy(button, "提交中...", async () => {
    for (const platform of platforms) {
      assertLegacySuccess(await apiRequest("/api/legacy/video/publish_v2/", {
        method: "POST",
        headers: { "X-Metahuman-Review-Approved": "true" },
        body: JSON.stringify({
          video_file: videoFile,
          title: document.querySelector("#videoTitle").value.trim(),
          topics: document.querySelector("#videoTopics").value.trim().split(/[\s,，]+/).filter(Boolean),
          platform,
          auto_publish: false,
          ...(includeCover && state.coverPath ? { cover: state.coverPath } : {}),
        }),
      }), `${platform} 发布任务提交失败`);
    }
    showToast(`已向 ${platforms.length} 个平台提交发布任务`);
  });
}

async function importAvatar() {
  const button = document.querySelector("#importAvatar");
  const videoPath = document.querySelector("#avatarImportPath").value.trim();
  const name = document.querySelector("#avatarImportName").value.trim();
  if (!videoPath || !name) return showToast("请填写源视频路径和数字人名称");
  await withBusy(button, "导入中...", async () => {
    const result = await apiRequest("/api/avatar/original-engine/meta-humans/import-from-path", {
      method: "POST",
      body: JSON.stringify({ video_path: videoPath, name, type: "sync" }),
    });
    if (result?.status === "failed") throw new Error(result.message || "数字人导入失败");
    showToast("数字人已导入");
    await loadAll();
  });
}

async function importAvatarFile() {
  const button = document.querySelector("#importAvatarFile");
  const file = document.querySelector("#avatarImportFile").files[0];
  const name = document.querySelector("#avatarImportName").value.trim();
  if (!file || !name) return showToast("请选择数字人视频并填写名称");
  await withBusy(button, "导入中...", async () => {
    const body = new FormData();
    body.append("type", "sync");
    body.append("file", file, file.name);
    body.append("name", name);
    assertLegacySuccess(await apiRequest("/api/legacy/meta_human/", { method: "POST", body }), "数字人导入失败");
    document.querySelector("#avatarImportFile").value = "";
    showToast("数字人已上传并导入");
    await loadAll();
  });
}

async function uploadWorkbenchAvatarVideo() {
  const button = document.querySelector("#uploadWorkbenchAvatarVideo");
  const input = document.querySelector("#workbenchAvatarVideo");
  const file = input.files?.[0];
  if (!file) return showToast("请先选择一个模板视频");
  const name = file.name.replace(/\.[^.]+$/, "").trim().slice(0, 80) || "自定义数字人";
  await withBusy(button, "导入中...", async () => {
    const body = new FormData();
    body.append("type", "sync");
    body.append("file", file, file.name);
    body.append("name", name);
    assertLegacySuccess(await apiRequest("/api/legacy/meta_human/", { method: "POST", body }), "模板视频导入失败");
    input.value = "";
    await loadAll();
    const select = document.querySelector("#avatarSelect");
    const option = [...select.options].find((item) => item.textContent.trim() === name || item.textContent.includes(name));
    if (option) {
      select.value = option.value;
      select.dispatchEvent(new Event("change"));
    }
    showToast(`已导入并选中模板“${name}”`);
  });
}

async function updateUiProfile(kind, item, index, update) {
  const key = stableProfileKey(item, `${kind}_${index}`);
  await apiRequest(`/api/ui/profiles/${kind}/${encodeURIComponent(key)}`, {
    method: "PUT",
    body: JSON.stringify(update),
  });
}

function chooseProfileImage(kind, index) {
  state.pendingImageTarget = { kind, index };
  document.querySelector(kind === "avatars" ? "#profileImageInput" : "#voiceImageInput").click();
}

async function imageFileToDataUrl(file) {
  const source = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("图片读取失败"));
    reader.readAsDataURL(file);
  });
  const image = await new Promise((resolve, reject) => {
    const element = new Image();
    element.onload = () => resolve(element);
    element.onerror = () => reject(new Error("图片格式无法识别"));
    element.src = source;
  });
  const maxDimension = 1440;
  const scale = Math.min(1, maxDimension / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  const context = canvas.getContext("2d");
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/webp", 0.88);
}

async function handleProfileImageChange(event) {
  const file = event.target.files?.[0];
  const target = state.pendingImageTarget;
  event.target.value = "";
  state.pendingImageTarget = null;
  if (!file || !target) return;
  const items = target.kind === "avatars" ? state.renderedMetaHumans : state.renderedVoices;
  const item = items[target.index];
  if (!item) return;
  const dataUrl = await imageFileToDataUrl(file);
  const key = stableProfileKey(item, `${target.kind}_${target.index}`);
  const result = await apiRequest("/api/ui/images", {
    method: "POST",
    body: JSON.stringify({ kind: target.kind, key, data_url: dataUrl }),
  });
  await updateUiProfile(target.kind, item, target.index, { image_url: result.image_url });
  showToast("人物图片已更新");
  await loadAll();
}

async function handleDigitalHumanAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const item = state.renderedMetaHumans[Number(button.dataset.index)];
  const index = Number(button.dataset.index);
  if (!item) return;
  if (button.dataset.action === "rename-avatar") {
    const currentName = profileDisplayName("avatars", item, `数字人 ${index + 1}`);
    const name = window.prompt("输入新的数字人名称", currentName);
    if (!name?.trim() || name.trim() === currentName) return;
    await updateUiProfile("avatars", item, index, { display_name: name.trim() });
    showToast("数字人名称已更新");
  }
  if (button.dataset.action === "change-avatar-image") {
    chooseProfileImage("avatars", index);
    return;
  }
  if (button.dataset.action === "delete-avatar") {
    if (!window.confirm(`确定删除数字人“${item.name}”吗？`)) return;
    assertLegacySuccess(await apiRequest("/api/legacy/meta_human/", {
      method: "DELETE",
      body: JSON.stringify({ type: item.type, name: item.name }),
    }), "数字人删除失败");
    showToast("数字人已删除");
  }
  await loadAll();
}

async function submitVoiceClone(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  await withBusy(button, "创建中...", async () => {
    const formData = new FormData(form);
    if (formData.get("authorized") !== "on") throw new Error("请先确认已获得声音授权");
    const importedFile = formData.get("file");
    const file = state.voiceCloneMode === "record" ? state.voiceRecordingFile : importedFile;
    if (!(file instanceof File) || !file.size) throw new Error(state.voiceCloneMode === "record" ? "请先完成一段朗读录音" : "请选择参考音频或视频");
    const name = String(formData.get("name") || "").trim();
    if (!name) throw new Error("请输入声音名称");
    const prepared = await prepareVoiceReference(file);
    let referenceText = String(formData.get("text") || "").trim();
    if (!referenceText && state.voiceCloneMode === "upload") {
      const asrResult = assertLegacySuccess(await apiRequest("/api/legacy/text/asr/", {
        method: "POST",
        body: JSON.stringify({ audio_file: prepared.legacyUrl }),
      }), "参考声音文字识别失败");
      referenceText = pickText(asrResult);
    }
    if (!referenceText) throw new Error("没有识别到参考文字，请手动填写后再创建");
    const result = assertLegacySuccess(await apiRequest("/api/legacy/voices/", {
      method: "POST",
      body: JSON.stringify({
        name,
        audio_file: prepared.legacyUrl,
        text: referenceText,
      }),
    }), "声音创建失败");
    const portrait = formData.get("portrait");
    if (portrait instanceof File && portrait.size) {
      const profileItem = { name };
      const key = stableProfileKey(profileItem, "voice_profile");
      const imageResult = await apiRequest("/api/ui/images", {
        method: "POST",
        body: JSON.stringify({ kind: "voices", key, data_url: await imageFileToDataUrl(portrait) }),
      });
      await updateUiProfile("voices", profileItem, 0, { display_name: name, image_url: imageResult.image_url });
    }
    stopVoiceRecordingTracks();
    state.voiceRecordingFile = null;
    document.querySelector("#voiceRecordingPreview").hidden = true;
    document.querySelector("#voiceRecordingStatus").textContent = "尚未录音";
    form.reset();
    setVoiceCloneMode("record");
    await loadAll();
    showToast(result?.message || `克隆声音“${name}”已创建，可立即试听`);
  });
}

async function handleVoiceAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const voice = state.renderedVoices[Number(button.dataset.index)];
  const index = Number(button.dataset.index);
  if (!voice) return;
  if (button.dataset.action === "preview-voice") {
    if (voice.managementSource === "legacy") {
      audioPreview.src = voice.audio_file || voice.url;
      await audioPreview.play();
    } else {
      const option = [...document.querySelector("#voiceSelect").options].find((item) => item.value === String(itemId(voice, "")));
      if (option) document.querySelector("#voiceSelect").value = option.value;
      await previewVoice();
    }
    return;
  }
  if (button.dataset.action === "rename-voice") {
    const currentName = profileDisplayName("voices", voice, `声音 ${index + 1}`);
    const name = window.prompt("输入新的声音名称", currentName);
    if (!name?.trim()) return;
    await updateUiProfile("voices", voice, index, { display_name: name.trim() });
    showToast("声音名称已更新");
  }
  if (button.dataset.action === "change-voice-image") {
    chooseProfileImage("voices", index);
    return;
  }
  if (button.dataset.action === "delete-voice") {
    if (!window.confirm(`确定删除声音“${voice.name}”吗？`)) return;
    assertLegacySuccess(await apiRequest("/api/legacy/voices/", {
      method: "DELETE",
      body: JSON.stringify({ name: voice.name }),
    }), "声音删除失败");
    showToast("声音已删除");
  }
  await loadAll();
}

function renderLegacySettings() {
  const contentStatus = document.querySelector("#contentServiceStatus");
  const contentDetail = document.querySelector("#contentServiceDetail");
  if (contentStatus) {
    const ready = state.contentService?.available && state.contentService?.configured && state.contentService?.enabled;
    contentStatus.textContent = ready ? "已连接" : state.contentService?.available ? "未配置" : "未连接";
    contentStatus.classList.toggle("success_text", Boolean(ready));
  }
  if (contentDetail) {
    const model = state.contentService?.model || "-";
    contentDetail.textContent = model;
  }
  const llm = state.contentConfig?.llm;
  if (llm && !document.querySelector("#contentModel").dataset.edited) {
    document.querySelector("#contentModel").value = llm.model || "";
    document.querySelector("#contentBaseUrl").value = llm.base_url || "";
    document.querySelector("#contentEnabled").checked = Boolean(llm.enabled);
    document.querySelector("#contentApiKeyHint").textContent = llm.api_key_info?.set ? `当前密钥：${llm.api_key_info.hint}` : "当前未设置密钥";
    document.querySelector("#contentProviderPreset").value = detectContentPreset(llm);
  }
  const config = state.catalog?.runtime_config || {};
  const voiceType = { 1: "v1_voice", 2: "v2_voice", 3: "v3_voice" }[Number(config.voiceModelType)] || "v1_voice";
  const voiceRadio = document.querySelector(`input[name="voice_model"][value="${voiceType}"]`);
  if (voiceRadio) voiceRadio.checked = true;
  const videoRadio = document.querySelector(`input[name="video_model"][value="${config.videoServiceType || "video_sync"}"]`);
  if (videoRadio) videoRadio.checked = true;
  const clipRadio = document.querySelector(`input[name="clip_mode"][value="${config.videoClipEncoder || "libx264"}"]`);
  if (clipRadio) clipRadio.checked = true;
  document.querySelector("#legacyBatchSize").value = Number(config.batchSize || 8);
  const promptConfig = state.catalog?.prompt_config?.data || {};
  if (!document.querySelector("#legacyPrompt1").dataset.edited) document.querySelector("#legacyPrompt1").value = promptConfig.prompt1 || "";
  if (!document.querySelector("#legacyPrompt2").dataset.edited) document.querySelector("#legacyPrompt2").value = promptConfig.prompt2 || "";
  updateLegacyServiceControls();
  updateClipModeNote();
}

const contentProviderPresets = {
  deepseek_flash: { base_url: "https://api.deepseek.com", model: "deepseek-v4-flash" },
  deepseek_pro: { base_url: "https://api.deepseek.com", model: "deepseek-v4-pro" },
  qwen: { base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
};

function detectContentPreset(llm) {
  if (String(llm.base_url || "").includes("deepseek.com") && llm.model === "deepseek-v4-pro") return "deepseek_pro";
  if (String(llm.base_url || "").includes("deepseek.com")) return "deepseek_flash";
  if (String(llm.base_url || "").includes("aliyuncs.com") || String(llm.model || "").startsWith("qwen")) return "qwen";
  return "custom";
}

function applyContentProviderPreset() {
  const preset = contentProviderPresets[document.querySelector("#contentProviderPreset").value];
  if (!preset) return;
  document.querySelector("#contentBaseUrl").value = preset.base_url;
  document.querySelector("#contentModel").value = preset.model;
  document.querySelector("#contentModel").dataset.edited = "true";
}

async function saveContentConfig({ clearApiKey = false } = {}) {
  const apiKey = document.querySelector("#contentApiKey").value.trim();
  const payload = {
    llm: {
      enabled: document.querySelector("#contentEnabled").checked,
      provider: "openai_compatible",
      base_url: document.querySelector("#contentBaseUrl").value.trim(),
      model: document.querySelector("#contentModel").value.trim(),
      api_key: apiKey,
      clear_api_key: clearApiKey,
    },
  };
  assertLegacySuccess(await apiRequest("/api/content/config", { method: "POST", body: JSON.stringify(payload) }), "模型配置保存失败");
  document.querySelector("#contentApiKey").value = "";
  document.querySelector("#contentModel").dataset.edited = "";
  showToast(clearApiKey ? "接口密钥已清除" : "模型配置已保存");
  await loadAll();
}

async function saveLegacySettings() {
  const voiceType = document.querySelector('input[name="voice_model"]:checked')?.value || "v1_voice";
  const voiceModelType = { v1_voice: 1, v2_voice: 2, v3_voice: 3 }[voiceType];
  assertLegacySuccess(await apiRequest("/api/legacy/runtime-config", {
    method: "POST",
    body: JSON.stringify({
      wordService: 1,
      titleService: 1,
      voiceModelType,
      videoServiceType: document.querySelector('input[name="video_model"]:checked')?.value || "video_sync",
      batchSize: Number(document.querySelector("#legacyBatchSize").value),
      videoClipEncoder: document.querySelector('input[name="clip_mode"]:checked')?.value || "libx264",
    }),
  }), "本地运行配置保存失败");
  assertLegacySuccess(await apiRequest("/api/legacy/config/prompt/", {
    method: "POST",
    body: JSON.stringify({
      prompt1: document.querySelector("#legacyPrompt1").value,
      prompt2: document.querySelector("#legacyPrompt2").value,
    }),
  }), "自定义提示词保存失败");
  showToast("运行设置和提示词已保存到本地服务");
  await loadAll();
}

async function testContentService() {
  const button = document.querySelector("#testContentService");
  await withBusy(button, "测试中...", async () => {
    const result = assertLegacySuccess(await apiRequest("/api/content/test", {
      method: "POST",
      body: "{}",
    }), "模型连接测试失败");
    if (!pickText(result)) throw new Error("模型已连接，但没有返回测试正文");
    showToast("模型连接正常");
    await loadAll();
  });
}

function legacyAlgorithmStatus() {
  return state.catalog?.algorithm?.data || {};
}

function updateLegacyServiceControls() {
  const status = legacyAlgorithmStatus();
  const voiceType = document.querySelector('input[name="voice_model"]:checked')?.value || "v1_voice";
  const videoType = document.querySelector('input[name="video_model"]:checked')?.value || "video_sync";
  document.querySelector("#legacyAudioServiceStatus").textContent = status[`${voiceType}_status`] === "open" ? "已启动" : "未启动";
  document.querySelector("#legacyVideoServiceStatus").textContent = status[`${videoType}_status`] === "open" ? "已启动" : "未启动";
}

function updateClipModeNote() {
  const mode = document.querySelector('input[name="clip_mode"]:checked')?.value || "libx264";
  document.querySelector("#clipModeNote").textContent = mode === "h264_nvenc" ? "快速剪辑会占用 GPU 资源。" : "普通剪辑仅占用 CPU 资源。";
}

async function setLegacyService(group, action) {
  const inputName = group === "audio" ? "voice_model" : "video_model";
  const type = document.querySelector(`input[name="${inputName}"]:checked`)?.value;
  if (!type) throw new Error("请先选择服务类型");
  const status = legacyAlgorithmStatus();
  if (action === "start") {
    const alternatives = group === "audio" ? ["v1_voice", "v2_voice", "v3_voice"] : ["video_sync", "video_pro"];
    for (const alternative of alternatives) {
      if (alternative !== type && status[`${alternative}_status`] === "open") {
        assertLegacySuccess(await apiRequest("/api/legacy/algorithm/stop/", {
          method: "POST",
          body: JSON.stringify({ type: alternative }),
        }), `关闭 ${alternative} 失败`);
      }
    }
  }
  const result = assertLegacySuccess(await apiRequest(`/api/legacy/algorithm/${action}/`, {
    method: "POST",
    body: JSON.stringify({ type }),
  }), `${action === "start" ? "启动" : "关闭"}本地服务失败`);
  showToast(result?.message || `本地服务已${action === "start" ? "启动" : "关闭"}`);
  await new Promise((resolve) => window.setTimeout(resolve, action === "start" ? 1200 : 300));
  await loadAll();
}

async function addLocalPipAssets() {
  const files = [...document.querySelector("#pipFileInput").files];
  if (!files.length) return showToast("请先选择图片或视频素材");
  for (const file of files) {
    const fileUrl = await uploadLegacyFile(file, "temp_uploads");
    const type = file.type.startsWith("image/") ? "image" : "video";
    assertLegacySuccess(await apiRequest("/api/legacy/assets/", {
      method: "POST",
      body: JSON.stringify({ type, file: fileUrl, name: file.name }),
    }), `素材 ${file.name} 导入失败`);
  }
  document.querySelector("#pipFileInput").value = "";
  showToast(`已导入 ${files.length} 个辅助画面素材`);
  await loadAll();
}

async function handlePipAssetAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const item = state.pipAssets[Number(button.dataset.index)];
  if (!item) return;
  if (button.dataset.action === "select-pip") {
    state.selectedPipAsset = item;
    renderPipAssets();
    showToast("已选为辅助画面，可在字幕编辑中按行使用");
    return;
  }
  if (button.dataset.action === "rename-pip") {
    const name = window.prompt("输入新的素材名称", item.name || "");
    if (!name?.trim()) return;
    assertLegacySuccess(await apiRequest(`/api/legacy/assets/?id=${encodeURIComponent(item.id)}`, {
      method: "PUT",
      body: JSON.stringify({ name: name.trim() }),
    }), "素材重命名失败");
    showToast("素材已重命名");
  }
  if (button.dataset.action === "delete-pip") {
    if (!window.confirm(`确定删除素材“${displayName(item, "未命名素材")}”吗？`)) return;
    assertLegacySuccess(await apiRequest(`/api/legacy/assets/?id=${encodeURIComponent(item.id)}`, {
      method: "DELETE",
    }), "素材删除失败");
    if (state.selectedPipAsset === item) state.selectedPipAsset = null;
    showToast("素材已删除");
  }
  await loadAll();
}

async function loadAll() {
  const results = await Promise.allSettled([
    apiRequest("/api/system/status"),
    apiRequest("/api/project"),
    apiRequest("/api/jobs"),
    apiRequest("/api/capabilities"),
    apiRequest("/api/legacy/catalog"),
    apiRequest("/api/tts/voices"),
    apiRequest("/api/assets"),
    apiRequest("/api/content/status"),
    apiRequest("/api/content/config"),
    apiRequest("/api/ui/profiles"),
    apiRequest("/api/media/background-music"),
  ]);

  if (results[0].status === "fulfilled") state.system = results[0].value;
  if (results[1].status === "fulfilled" && !scriptInput.dataset.edited) scriptInput.value = results[1].value?.script || scriptInput.value;
  if (results[2].status === "fulfilled") state.jobs = results[2].value || [];
  if (results[3].status === "fulfilled") state.capabilities = results[3].value?.items || [];
  if (results[4].status === "fulfilled") state.catalog = results[4].value;
  if (results[5].status === "fulfilled") state.ttsVoices = results[5].value?.items || [];
  if (results[6].status === "fulfilled") state.nativeAssets = results[6].value || [];
  if (results[7].status === "fulfilled") state.contentService = results[7].value;
  if (results[8].status === "fulfilled") state.contentConfig = results[8].value?.data || null;
  if (results[9].status === "fulfilled") state.uiProfiles = results[9].value?.items || {};
  if (results[10].status === "fulfilled") state.userBackgroundMusic = results[10].value?.items || [];

  updateScriptStats();
  updateSystemStatus();
  renderCatalog();
  applyWorkbenchDraftSelections();
  updateSelectedVoicePreview();
  updateSelectedAvatarPreview();
  document.querySelector("#musicSelect").disabled = !document.querySelector("#backgroundMusicEnabled").checked;
  renderCapabilities();
  renderJobs();
  renderLegacySettings();
  const failures = results.filter((result) => result.status === "rejected");
  if (failures.length && !state.system) showToast("API 网关未连接，请先启动本地服务");
}

function bindEvents() {
  document.querySelectorAll(".nav_item").forEach((button) => button.addEventListener("click", () => setActiveView(button.dataset.view)));
  document.querySelector(".sidebar_workbench").addEventListener("click", () => setActiveView("workbench"));
  scriptInput.addEventListener("input", () => {
    scriptInput.dataset.edited = "true";
    state.subtitleRows = [];
    state.subtitleSourceText = "";
    if (!state.generating) document.querySelector("#generationState").textContent = "待生成";
    updateScriptStats();
    scheduleWorkbenchDraftSave();
  });
  document.querySelector("#speedRange").addEventListener("input", (event) => {
    document.querySelector("#speedValue").textContent = `${Number(event.target.value).toFixed(2)}x`;
    scheduleWorkbenchDraftSave();
  });
  document.querySelector("#voiceSelect").addEventListener("change", updateSelectedVoicePreview);
  document.querySelector("#openVoicePicker").addEventListener("click", () => {
    renderVoicePicker();
    document.querySelector("#voicePickerDialog").showModal();
  });
  document.querySelector("#voicePickerGrid").addEventListener("click", (event) => {
    const previewButton = event.target.closest("button[data-preview-voice-id]");
    if (previewButton) {
      const entry = state.voicePickerItems.find((item) => item.id === previewButton.dataset.previewVoiceId);
      return runAction(() => previewVoicePickerEntry(entry, previewButton));
    }
    const button = event.target.closest("button[data-voice-id]");
    if (!button) return;
    const select = document.querySelector("#voiceSelect");
    select.value = button.dataset.voiceId;
    select.dispatchEvent(new Event("change"));
    document.querySelector("#voicePickerDialog").close();
  });
  document.querySelector("#openAvatarPicker").addEventListener("click", () => {
    renderAvatarTemplateGallery();
    document.querySelector("#avatarPickerDialog").showModal();
  });
  document.querySelector("#avatarSelect").addEventListener("change", (event) => {
    const source = event.target.selectedOptions[0]?.dataset.source;
    if (source) document.querySelector("#avatarEngine").value = source;
    updateSelectedAvatarPreview();
    scheduleWorkbenchDraftSave();
  });
  document.querySelector("#avatarTemplateGallery").addEventListener("click", (event) => {
    const previewButton = event.target.closest("button[data-preview-avatar-id]");
    if (previewButton) {
      const entry = state.avatarPickerItems.find((item) => item.id === previewButton.dataset.previewAvatarId);
      openAvatarVideoPreview(entry);
      return;
    }
    const button = event.target.closest("button[data-avatar-id]");
    if (!button) return;
    const select = document.querySelector("#avatarSelect");
    select.value = button.dataset.avatarId;
    document.querySelector("#avatarEngine").value = button.dataset.avatarSource;
    select.dispatchEvent(new Event("change"));
    const selectedEntry = state.avatarPickerItems.find((item) => item.id === button.dataset.avatarId);
    if (selectedEntry?.licenseStatus === "test_only") showToast("该旧版模板仅供内部测试，不可用于正式发布");
    document.querySelector("#avatarPickerDialog").close();
  });
  document.querySelector("#previewSelectedAvatar").addEventListener("click", () => {
    const entry = state.avatarPickerItems.find((item) => item.id === document.querySelector("#avatarSelect").value);
    openAvatarVideoPreview(entry);
  });
  document.querySelector("#closeAssetVideoPreview").addEventListener("click", closeAvatarVideoPreview);
  document.querySelector("#assetVideoPreviewDialog").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeAvatarVideoPreview();
  });
  document.querySelector("#assetVideoPreviewDialog").addEventListener("close", () => {
    const preview = document.querySelector("#assetVideoPreview");
    preview.pause();
  });
  document.querySelector("#avatarPickerImport").addEventListener("click", () => {
    const input = document.querySelector("#workbenchAvatarVideo");
    input.dataset.importFromPicker = "true";
    input.click();
  });
  document.querySelector("#workbenchAvatarVideo").addEventListener("change", (event) => {
    if (event.target.dataset.importFromPicker !== "true" || !event.target.files?.length) return;
    event.target.dataset.importFromPicker = "";
    document.querySelector("#avatarPickerDialog").close();
    runAction(uploadWorkbenchAvatarVideo);
  });
  document.querySelector("#extractDouyin").addEventListener("click", () => runAction(extractDouyin));
  document.querySelector("#transcribeMedia").addEventListener("click", () => runAction(transcribeMedia));
  document.querySelector("#rewriteScript").addEventListener("click", () => runAction(rewriteScript));
  document.querySelector("#generateTitle").addEventListener("click", () => runAction(generateTitle));
  document.querySelector("#previewVoice").addEventListener("click", () => runAction(previewVoice));
  document.querySelector("#generateVideo").addEventListener("click", () => runAction(generateVideo));
  document.querySelector("#submitClip").addEventListener("click", () => runAction(submitLegacyClip));
  document.querySelector("#cancelGeneration").addEventListener("click", () => runAction(cancelLegacyGeneration));
  document.querySelector("#cancelClip").addEventListener("click", () => runAction(cancelLegacyClip));
  document.querySelector("#submitPublish").addEventListener("click", () => runAction(submitPublish));
  document.querySelector("#importAvatar").addEventListener("click", () => runAction(importAvatar));
  document.querySelector("#importAvatarFile").addEventListener("click", () => runAction(importAvatarFile));
  document.querySelector("#uploadWorkbenchAvatarVideo").addEventListener("click", () => runAction(uploadWorkbenchAvatarVideo));
  document.querySelector("#voiceCloneForm").addEventListener("submit", (event) => runAction(() => submitVoiceClone(event)));
  document.querySelectorAll("[data-clone-mode]").forEach((button) => button.addEventListener("click", () => setVoiceCloneMode(button.dataset.cloneMode)));
  document.querySelector("#copyVoiceCloneScript").addEventListener("click", () => runAction(async () => {
    await navigator.clipboard.writeText(voiceCloneScript);
    showToast("朗读文稿已复制");
  }));
  document.querySelector("#startVoiceRecording").addEventListener("click", () => runAction(startVoiceRecording));
  document.querySelector("#stopVoiceRecording").addEventListener("click", stopVoiceRecording);
  document.querySelector("#digitalHumanTable").addEventListener("click", (event) => runAction(() => handleDigitalHumanAction(event)));
  document.querySelector("#voiceLibrary").addEventListener("click", (event) => runAction(() => handleVoiceAction(event)));
  document.querySelector("#avatarSearch").addEventListener("input", () => renderDigitalHumans());
  document.querySelector("#voiceSearch").addEventListener("input", () => renderVoiceLibrary(state.renderedVoices));
  document.querySelector("#profileImageInput").addEventListener("change", (event) => runAction(() => handleProfileImageChange(event)));
  document.querySelector("#voiceImageInput").addEventListener("change", (event) => runAction(() => handleProfileImageChange(event)));
  document.querySelector("#pipAssetGallery").addEventListener("click", (event) => runAction(() => handlePipAssetAction(event)));
  document.querySelector("#addLocalPip").addEventListener("click", () => runAction(addLocalPipAssets));
  document.querySelector("#saveLegacySettings").addEventListener("click", () => runAction(saveLegacySettings));
  document.querySelector("#testContentService").addEventListener("click", () => runAction(testContentService));
  document.querySelector("#saveContentConfig").addEventListener("click", () => runAction(() => saveContentConfig()));
  document.querySelector("#contentConfigForm").addEventListener("submit", (event) => {
    event.preventDefault();
    runAction(() => saveContentConfig());
  });
  document.querySelector("#clearContentToken").addEventListener("click", () => runAction(async () => {
    if (window.confirm("确定清除当前文案模型的接口密钥吗？")) await saveContentConfig({ clearApiKey: true });
  }));
  document.querySelector("#contentProviderPreset").addEventListener("change", applyContentProviderPreset);
  ["contentModel", "contentBaseUrl"].forEach((id) => document.querySelector(`#${id}`).addEventListener("input", (event) => { event.target.dataset.edited = "true"; }));
  document.querySelector("#showRealJobs").addEventListener("click", () => {
    state.jobScope = "real";
    document.querySelector("#showRealJobs").classList.add("active");
    document.querySelector("#showSampleJobs").classList.remove("active");
    renderJobs();
  });
  document.querySelector("#showSampleJobs").addEventListener("click", () => {
    state.jobScope = "samples";
    document.querySelector("#showSampleJobs").classList.add("active");
    document.querySelector("#showRealJobs").classList.remove("active");
    renderJobs();
  });
  document.querySelector("#jobList").addEventListener("click", (event) => {
    const button = event.target.closest('button[data-action="delete-job"]');
    if (!button || button.disabled) return;
    runAction(async () => {
      if (!window.confirm("确定删除这条任务记录吗？已生成的成片文件不会被删除。")) return;
      await apiRequest(`/api/jobs/${encodeURIComponent(button.dataset.jobId)}`, { method: "DELETE" });
      showToast("任务记录已删除");
      await refreshJobsOnly();
    });
  });
  document.querySelector("#clearCurrentJobs").addEventListener("click", () => runAction(async () => {
    const scopeLabel = state.jobScope === "samples" ? "样例与验收" : "正式";
    if (!window.confirm(`确定清空全部${scopeLabel}任务记录吗？生成中的任务会保留。`)) return;
    const result = await apiRequest(`/api/jobs?scope=${state.jobScope}`, { method: "DELETE" });
    showToast(`已清理 ${result.deleted_count || 0} 条${scopeLabel}任务`);
    await refreshJobsOnly();
  }));
  document.querySelector("#deliveryResetJobs").addEventListener("click", () => runAction(async () => {
    if (!window.confirm("交付前清理会删除全部正式任务、样例任务和本机工作台草稿。数字人模板、模型和程序不会删除。是否继续？")) return;
    const phrase = window.prompt("请输入“确认清空”后继续");
    if (phrase !== "确认清空") return showToast("输入内容不正确，已取消清理");
    const result = await apiRequest("/api/jobs?scope=all", { method: "DELETE" });
    window.localStorage.removeItem(workbenchDraftKey);
    window.localStorage.removeItem("metahuman_legacy_ai_settings");
    state.activeJobId = "";
    showToast(`交付前任务数据已清理，共删除 ${result.deleted_count || 0} 条记录`);
    await refreshJobsOnly();
  }));
  document.querySelector("#subtitleGenerateProxy").addEventListener("click", () => runAction(generateSubtitles));
  document.querySelector("#subtitleEditProxy").addEventListener("click", openSubtitleEditor);
  document.querySelector("#saveSubtitleEdits").addEventListener("click", saveSubtitleEdits);
  document.querySelector("#openCoverEditor").addEventListener("click", openCoverEditor);
  document.querySelector("#generateCover").addEventListener("click", () => runAction(generateCover));
  document.querySelector("#captureCoverFrame").addEventListener("click", () => runAction(captureCoverFrame));
  document.querySelector("#uploadCoverSource").addEventListener("click", () => document.querySelector("#coverSourceFile").click());
  document.querySelector("#coverSourceFile").addEventListener("change", (event) => runAction(async () => {
    const file = event.target.files?.[0];
    event.target.value = "";
    await uploadCoverSourceImage(file);
  }));
  document.querySelector("#refreshMusicProxy").addEventListener("click", () => runAction(loadAll));
  document.querySelector("#importBackgroundMusic").addEventListener("click", () => document.querySelector("#backgroundMusicFile").click());
  document.querySelector("#backgroundMusicFile").addEventListener("change", () => runAction(importBackgroundMusic));
  document.querySelector("#previewMusic").addEventListener("click", () => runAction(previewBackgroundMusic));
  document.querySelector("#musicSelect").addEventListener("change", (event) => {
    if (event.target.value) document.querySelector("#backgroundMusicEnabled").checked = true;
    scheduleWorkbenchDraftSave();
  });
  document.querySelector("#backgroundMusicEnabled").addEventListener("change", (event) => {
    const musicSelect = document.querySelector("#musicSelect");
    musicSelect.disabled = !event.target.checked;
    if (!event.target.checked) musicSelect.value = "";
    scheduleWorkbenchDraftSave();
  });
  ["videoTitle", "videoTopics"].forEach((id) => document.querySelector(`#${id}`).addEventListener("input", scheduleWorkbenchDraftSave));
  ["rewriteMode", "contentType", "toneSelect", "voiceSelect", "avatarEngine", "targetFormat", "videoQuality", "subtitleTemplate", "burnSubtitles"].forEach((id) => {
    document.querySelector(`#${id}`).addEventListener("change", scheduleWorkbenchDraftSave);
  });
  document.querySelector("#subtitleTemplate").addEventListener("change", updateSubtitleStylePreview);
  document.addEventListener("click", (event) => {
    const image = event.target.closest("img[data-preview-image]");
    if (image) openImagePreview(image.currentSrc || image.src, image.dataset.previewTitle || image.alt);
  });
  document.querySelector("#closeImagePreview").addEventListener("click", () => document.querySelector("#imagePreviewDialog").close());
  document.querySelector("#imagePreviewDialog").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  });
  document.querySelector("#previewPlayProxy").addEventListener("click", () => runAction(async () => {
    if (videoPreview.hidden || !videoPreview.src) return showToast("请先生成数字人视频");
    await videoPreview.play();
  }));
  ["audioServiceRefreshProxy", "videoServiceRefreshProxy"].forEach((id) => {
    document.querySelector(`#${id}`).addEventListener("click", () => runAction(loadAll));
  });
  document.querySelector("#startAudioService").addEventListener("click", () => runAction(() => setLegacyService("audio", "start")));
  document.querySelector("#stopAudioService").addEventListener("click", () => runAction(() => setLegacyService("audio", "stop")));
  document.querySelector("#startVideoService").addEventListener("click", () => runAction(() => setLegacyService("video", "start")));
  document.querySelector("#stopVideoService").addEventListener("click", () => runAction(() => setLegacyService("video", "stop")));
  document.querySelectorAll('input[name="voice_model"], input[name="video_model"]').forEach((input) => input.addEventListener("change", updateLegacyServiceControls));
  document.querySelectorAll('input[name="clip_mode"]').forEach((input) => input.addEventListener("change", updateClipModeNote));
  for (const id of ["legacyPrompt1", "legacyPrompt2"]) {
    document.querySelector(`#${id}`).addEventListener("input", (event) => { event.target.dataset.edited = "true"; });
  }
  document.querySelectorAll("[data-open-settings]").forEach((button) => {
    button.addEventListener("click", () => setActiveView("settings"));
  });
  ["refreshAll", "refreshSettings"].forEach((id) => document.querySelector(`#${id}`).addEventListener("click", () => runAction(loadAll)));
  document.querySelector("#refreshJobs").addEventListener("click", () => runAction(refreshJobsOnly));
  videoPreview.addEventListener("play", () => { document.querySelector("#previewPlayProxy").hidden = true; });
  videoPreview.addEventListener("pause", () => { document.querySelector("#previewPlayProxy").hidden = false; });
}

async function runAction(action) {
  try {
    await action();
  } catch (error) {
    showToast(error.message || String(error));
  }
}

scriptInput.value = "今天我们用一分钟讲清楚，怎样把一段文案稳定地生成自然语音、数字人口型视频、字幕和最终成片。整个过程保留人工审片，让每一步都可检查、可调整。";
window.localStorage.removeItem("metahuman_legacy_ai_settings");
restoreWorkbenchDraftEarly();
bindEvents();
setVoiceCloneMode("record");
document.querySelector("#musicSelect").disabled = true;
updateScriptStats();
loadAll();
